# Modelos e inferencia

## Registro de modelos

`ml/model_registry/<nombre>/<versión>/model.yaml` (versionado en git) + `model.onnx` (no versionado; se regenera con el script de exportación indicado en `notes` y `weights_source`).

| Campo | Significado |
|---|---|
| `architecture` | Adaptador `DetectionModel` (`rtdetr`, `rfdetr`, `detr`) |
| `sha256` | Integridad del artefacto: el motor **se niega** a cargar un ONNX que no coincida |
| `labels` | Etiqueta de cada salida del modelo |
| `class_map` | Etiqueta del modelo → clase canónica. Lo no mapeado se ignora (por ejemplo, las 79 clases COCO que no son `person`) |
| `score_threshold` / `class_thresholds` | Umbrales global y por clase canónica |
| `params` | Normalización y nombres de entradas/salidas del grafo |
| `license` / `weights_license` / `weights_source` / `dataset_ref` | Trazabilidad legal de código, pesos y datos |

## Cambiar de modelo o de motor: solo configuración (criterios 13 y 14)

```bash
SV_DETECTION_MODEL=rtdetr-v2-r18-coco@1   # cualquier modelo registrado
SV_INFERENCE_ENGINE=onnxruntime           # onnxruntime | openvino
SV_INFERENCE_DEVICES=["cuda","cpu"]       # preferencia; el respaldo queda registrado en el log
```

Dispositivos admitidos:
- `onnxruntime`: `cpu`, `cuda`, `tensorrt` (requiere las bibliotecas TensorRT), `directml`.
- `openvino`: `openvino-cpu`, `openvino-gpu` (GPU integrada Intel).

El dominio, los incidentes, la base de datos y la API no cambian: solo cambian el adaptador y el artefacto. Un test lo verifica comparando las detecciones de ONNX Runtime y OpenVINO.

## Añadir un modelo propio

1. Entrenar con `ml/training/train_rtdetr.py` sobre una exportación de `svds export`. Solo acepta datos auditados.
2. Exportar con `ml/export/export_rtdetr_hf.py --repo <run>/best --class-map-identity`.
3. Medir con `ml/evaluation/benchmark_inference.py`.
4. Activarlo con `SV_DETECTION_MODEL=<nombre>@<versión>`.

Una arquitectura nueva necesita un adaptador `DetectionModel`, registrado en `composition.py` o como *entry point* `security_vision.detection_models` desde un paquete externo.
