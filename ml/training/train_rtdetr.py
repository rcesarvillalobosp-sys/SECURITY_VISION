"""Afinado de RT-DETRv2 para EPP sobre una exportación auditada (svds export, formato YOLO canónico).

    uv run python ml/training/train_rtdetr.py --data ml/datasets/exports/ppe_v1 --out ml/training/runs/ppe-v1 \
        --epochs 30 --batch 4

Garantías:
- Solo acepta exportaciones generadas por ``svds export`` (exige ATTRIBUTION.md y data.yaml canónico),
  es decir, datos con licencia verificada y sin cajas pendientes de revisión.
- La partición ``test`` NUNCA se usa durante el entrenamiento ni para elegir el mejor checkpoint
  (eso se hace con ``val``); se evalúa una sola vez al final.
- Registra todo en ``<out>/run.json`` (hiperparámetros, datos, semillas, métricas por época).
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))
from evaluation.detection_metrics import evaluate_detections  # noqa: E402


def load_split(data: Path, split: str, names: list[str]) -> list[tuple[Path, np.ndarray, np.ndarray]]:
    items = []
    for img in sorted((data / "images" / split).glob("*")):
        lbl = data / "labels" / split / (img.stem + ".txt")
        cls, boxes = [], []
        if lbl.exists():
            for line in lbl.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    c, cx, cy, w, h = line.split()
                    cls.append(int(c))
                    boxes.append([float(cx), float(cy), float(w), float(h)])
        items.append((img, np.array(cls, dtype=np.int64), np.array(boxes, dtype=np.float32).reshape(-1, 4)))
    return items


class YoloDataset:
    def __init__(self, items, size: int, train: bool) -> None:
        self.items, self.size, self.train = items, size, train

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, i: int):
        import torch

        path, cls, boxes = self.items[i]
        img = Image.open(path).convert("RGB")
        boxes = boxes.copy()
        if self.train and random.random() < 0.5:  # volteo horizontal (no altera la semántica de EPP)
            img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            boxes[:, 0] = 1.0 - boxes[:, 0]
        if self.train:  # jitter fotométrico suave
            arr = np.asarray(img, dtype=np.float32) * random.uniform(0.8, 1.2) + random.uniform(-20, 20)
            img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        img = img.resize((self.size, self.size), Image.Resampling.BILINEAR)
        x = torch.from_numpy(np.asarray(img, dtype=np.float32).transpose(2, 0, 1) / 255.0)
        target = {"class_labels": torch.from_numpy(cls), "boxes": torch.from_numpy(boxes)}
        return x, target


def collate(batch):
    import torch

    return torch.stack([b[0] for b in batch]), [b[1] for b in batch]


@np.errstate(over="ignore")
def predict(model, loader, device, num_classes: int, threshold: float = 0.001):
    import torch

    preds = []
    model.eval()
    with torch.no_grad():
        for x, _ in loader:
            with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
                out = model(pixel_values=x.to(device))
            probs = out.logits.float().sigmoid().cpu().numpy()
            bx = out.pred_boxes.float().cpu().numpy()
            for p, b in zip(probs, bx, strict=True):
                scores = p.max(-1)
                labels = p.argmax(-1)
                keep = scores >= threshold
                xyxy = np.stack([b[:, 0] - b[:, 2] / 2, b[:, 1] - b[:, 3] / 2,
                                 b[:, 0] + b[:, 2] / 2, b[:, 1] + b[:, 3] / 2], -1).clip(0, 1)
                preds.append({"boxes": xyxy[keep], "scores": scores[keep], "labels": labels[keep]})
    return preds


def ground_truth(items):
    gts = []
    for _p, cls, b in items:
        xyxy = np.stack([b[:, 0] - b[:, 2] / 2, b[:, 1] - b[:, 3] / 2, b[:, 0] + b[:, 2] / 2,
                         b[:, 1] + b[:, 3] / 2], -1) if len(b) else np.zeros((0, 4), np.float32)
        gts.append({"boxes": xyxy, "labels": cls})
    return gts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--base", default="PekingU/rtdetr_v2_r18vd")
    ap.add_argument("--base-revision", default=None)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--accum", type=int, default=2)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--lr-backbone", type=float, default=1e-5)
    ap.add_argument("--size", type=int, default=640)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--max-train-images", type=int, default=0, help="0 = todas (solo para pruebas rápidas)")
    a = ap.parse_args()

    if not (a.data / "ATTRIBUTION.md").exists() or not (a.data / "data.yaml").exists():
        sys.exit("solo se aceptan exportaciones de 'svds export' (faltan ATTRIBUTION.md/data.yaml)")
    import torch
    from transformers import AutoModelForObjectDetection

    random.seed(a.seed)
    np.random.seed(a.seed)
    torch.manual_seed(a.seed)
    names_map = yaml.safe_load((a.data / "data.yaml").read_text(encoding="utf-8"))["names"]
    names = [names_map[i] for i in range(len(names_map))]
    train_items = load_split(a.data, "train", names)
    val_items = load_split(a.data, "val", names)
    test_items = load_split(a.data, "test", names)
    if a.max_train_images:
        train_items = train_items[: a.max_train_images]
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = AutoModelForObjectDetection.from_pretrained(
        a.base, revision=a.base_revision, num_labels=len(names), ignore_mismatched_sizes=True,
        id2label=dict(enumerate(names)), label2id={n: i for i, n in enumerate(names)}).to(device)

    backbone = [p for n, p in model.named_parameters() if "backbone" in n]
    rest = [p for n, p in model.named_parameters() if "backbone" not in n]
    opt = torch.optim.AdamW([{"params": backbone, "lr": a.lr_backbone}, {"params": rest, "lr": a.lr}],
                            weight_decay=1e-4)
    tl = torch.utils.data.DataLoader(YoloDataset(train_items, a.size, True), batch_size=a.batch, shuffle=True,
                                     collate_fn=collate, num_workers=a.workers, persistent_workers=a.workers > 0)
    vl = torch.utils.data.DataLoader(YoloDataset(val_items, a.size, False), batch_size=a.batch,
                                     collate_fn=collate, num_workers=a.workers)
    steps = a.epochs * math.ceil(len(tl) / a.accum)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=[a.lr_backbone, a.lr], total_steps=steps,
                                                pct_start=0.1)
    scaler = torch.amp.GradScaler(enabled=device.type == "cuda")
    a.out.mkdir(parents=True, exist_ok=True)
    run = {"args": {k: str(v) for k, v in vars(a).items()}, "classes": names, "device": str(device),
           "gpu": torch.cuda.get_device_name(0) if device.type == "cuda" else None,
           "images": {"train": len(train_items), "val": len(val_items), "test": len(test_items)},
           "attribution": (a.data / "ATTRIBUTION.md").read_text(encoding="utf-8"), "epochs": []}
    best = -1.0
    gts_val = ground_truth(val_items)
    for epoch in range(1, a.epochs + 1):
        model.train()
        t0 = time.time()
        total, n = 0.0, 0
        opt.zero_grad()
        for step, (x, targets) in enumerate(tl, 1):
            targets = [{k: v.to(device) for k, v in t.items()} for t in targets]
            with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
                loss = model(pixel_values=x.to(device), labels=targets).loss / a.accum
            scaler.scale(loss).backward()
            if step % a.accum == 0 or step == len(tl):
                scaler.unscale_(opt)
                torch.nn.utils.clip_grad_norm_(model.parameters(), 0.1)
                scaler.step(opt)
                scaler.update()
                opt.zero_grad()
                if sched.last_epoch < steps - 1:
                    sched.step()
            total += loss.item() * a.accum
            n += 1
        metrics = evaluate_detections(predict(model, vl, device, len(names)), gts_val, names)
        rec = {"epoch": epoch, "train_loss": total / max(1, n), "val_mAP50": metrics["mAP50"],
               "val_mAP50_95": metrics["mAP50_95"], "seconds": round(time.time() - t0, 1)}
        run["epochs"].append(rec)
        print(json.dumps(rec), flush=True)
        if metrics["mAP50_95"] > best:
            best = metrics["mAP50_95"]
            model.save_pretrained(a.out / "best")
            run["best"] = {"epoch": epoch, "val": metrics}
        (a.out / "run.json").write_text(json.dumps(run, indent=1, ensure_ascii=False), encoding="utf-8")

    # Evaluación final ÚNICA sobre test con el mejor checkpoint elegido en val.
    if test_items:
        best_model = AutoModelForObjectDetection.from_pretrained(a.out / "best").to(device)
        tsl = torch.utils.data.DataLoader(YoloDataset(test_items, a.size, False), batch_size=a.batch,
                                          collate_fn=collate)
        run["test"] = evaluate_detections(predict(best_model, tsl, device, len(names)), ground_truth(test_items),
                                          names)
    (a.out / "run.json").write_text(json.dumps(run, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"best": run.get("best"), "test": run.get("test")}, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
