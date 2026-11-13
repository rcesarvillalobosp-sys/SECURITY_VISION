# Fase 3: motor de inferencia y detección de personas y EPP. Resultados

Fechas: 2026-11-12/13. Equipo: i7-9750H, GTX 1650 4 GB (sm_75), UHD 630.

## Entregado

| Componente | Descripción |
|---|---|
| `OnnxRuntimeEngine` | CPU, CUDA y TensorRT (con caché de motores). Recorre la lista de preferencia y **detecta el respaldo silencioso** de ONNX Runtime (comprueba el proveedor activo). Verifica el sha256 del modelo. Latencias p50/p95. |
| `OpenVinoEngine` | `openvino-cpu`, `openvino-igpu`, `openvino-dgpu` y `openvino-gpu.N` (ADR-0015). |
| `DetrDetectionModel` (+ `rtdetr`, `rfdetr`) | Preproceso, postproceso top-k sin NMS, umbrales global y por clase, mapeo a la taxonomía canónica. Las clases no mapeadas se ignoran. |
| Registro de modelos | `ml/model_registry/<nombre>/<versión>/model.yaml` con sha256, etiquetas, licencias y origen exacto de los pesos. |
| Exportación | `export_rtdetr_hf.py`: commit de HF fijado y verificación por detecciones contra PyTorch (ADR-0014). `export_rfdetr.py`: en un entorno aislado, con comprobación empírica del mapa de clases. |
| Evaluación | Métricas COCO propias (AP50 y AP50:95 con 101 puntos), con tests. `benchmark_inference.py` reproducible. |
| Worker | Detección integrada en el consumidor de análisis (modelo compartido), snapshots anotados y métricas `sv_inference_ms{quantile}`, `sv_detections_total{class}`, `sv_camera_persons` y `sv_inference_errors_total`. |
| Entrenamiento | `train_rtdetr.py`: solo acepta exportaciones auditadas. Elige el mejor modelo en val y evalúa test una sola vez. **Guarda un checkpoint completo en cada época y admite `--resume`** (añadido tras el apagado del equipo). Incluye protección térmica. |

## Modelos registrados

| Modelo | Origen | Licencia | Clases útiles |
|---|---|---|---|
| `rtdetr-v2-r18-coco@1` | `PekingU/rtdetr_v2_r18vd@5650961…` | Apache-2.0 | `person` |
| `rfdetr-nano-coco@1` | `rfdetr==1.12.1` RFDETRNano | Apache-2.0 | `person` |
| `rtdetr-v2-r18-ppe-pilot@1` | Afinado propio (piloto) | Derivado: base Apache-2.0 + datos CC BY 4.0 (atribución) | 10 clases (sin `no_safety_boot`) |

## Benchmark (cifras medidas; `ml/evaluation/results/*.json`)

Latencia de una sola imagen. "e2e" incluye el preproceso de imágenes reales de 1080p o más. Precisión de `person` sobre las 200 imágenes de val del dataset original.

| Modelo | Motor/dispositivo | e2e p50 / p95 (ms) | Solo motor p50 | person AP50 / AP50:95 |
|---|---|---|---|---|
| RT-DETRv2-r18 | ORT CUDA (GTX 1650) | 95.9 / 144.7 | 49.0 | 0.961 / 0.822 |
| RT-DETRv2-r18 | ORT CPU | 449.6 / 648.0 | 401.9 | 0.961 / 0.822 |
| RT-DETRv2-r18 | OpenVINO CPU | 355.4 / 529.4 | 310.6 | 0.961 / 0.822 |
| RF-DETR Nano (384) | ORT CUDA | 55.5 / 63.2 | 31.5 | 0.945 / 0.777 |
| RF-DETR Nano (384) | ORT CPU | 242.3 / 362.3 | 213.5 | 0.945 / 0.777 |
| RF-DETR Nano (384) | OpenVINO CPU | 151.9 / 183.8 | 123.6 | 0.945 / 0.777 |

- **Criterio 14:** la precisión es **idéntica** en los tres motores. Cambiar de motor es solo configuración.
- **TensorRT:** el proveedor aparece en ONNX Runtime, pero faltan las bibliotecas TensorRT. El motor lo **detecta y lo rechaza** en lugar de fingir que lo usa. Se instalará en la Fase 9.
- **OpenVINO GPU:** la iGPU UHD 630 tumba el proceso (driver de 2019). La GTX 1650 vía OpenVINO tarda unos 495 ms, así que no tiene sentido. Ver ADR-0015.
- **Preproceso:** con CUDA, el redimensionado de imágenes grandes (unos 45 ms) pesa casi tanto como la inferencia. Es candidato a optimizar en la Fase 9.

## Piloto EPP

- **Datos:** `svds split ppe_v1`, solo con la fuente autorizada (Ultralytics, CC BY 4.0). 547 imágenes de entrenamiento, 69 de val y 69 de test, **0 fugas**. Se excluyen las imágenes pendientes de la corrección `no_boots_relabel_v1`, así que no hay ejemplos de `no_safety_boot`.
- **Entrenamiento:** RT-DETRv2-r18 en la GTX 1650 (AMP, batch 4×2), unos 5 min por época.
  - **Incidencia:** el equipo se apagó en la época 10 de 30 (probable sobrecalentamiento: las épocas pasaron de 300 a 549 s).
  - El script de entonces no guardaba el estado del optimizador, así que la continuación es **aproximada**: 20 épocas nuevas desde los pesos de la mejor época (la 9), con optimizador y programa de LR nuevos. Las dos ejecuciones están en `run.json`.
  - Con la protección térmica, la temperatura se mantuvo entre 45 y 86 °C.
- **Selección:** la mejor época de la continuación fue la 16 (val mAP50 0.799, mAP50:95 0.560).

### Test (69 imágenes, evaluado una sola vez), modelo ONNX desplegado

| Clase | AP50 | | Clase | AP50 |
|---|---|---|---|---|
| person | 0.954 | | no_helmet | 0.620 |
| helmet | 0.849 | | no_vest | 0.787 |
| safety_vest | 0.917 | | no_gloves | 0.676 |
| safety_boot | 0.826 | | no_goggles | 0.428 |
| gloves | 0.853 | | | |
| goggles | 0.965 | | | |
| **mAP50** | **0.787** | | **mAP50:95** | **0.565** |

Con CUDA, el modelo tarda 54.7 ms en el motor y 109 ms en el ciclo completo.

En el worker real, con un vídeo de imágenes de test, sale `streaming` en CUDA (p50 71 ms) con 0 errores. Detecta EPP y marca `no_helmet` en trabajadores sin casco.

### Lectura honesta de estas cifras

- **No es la evaluación final del requisito.** El test procede de la **misma fuente** que el entrenamiento: un único publicador, con parte de imágenes sintéticas y todas de construcción. Con cámaras reales la precisión será previsiblemente **menor**. La evaluación final exige imágenes y vídeos propios (holdout), que todavía no existen.
- Las clases `no_*` son débiles (0.43–0.79). Se confirma que deben usarse solo como señal auxiliar, nunca como prueba única de un incumplimiento (Fase 5).
- `safety_boot` significa "bota de trabajo visible", **no** calzado certificado.
- `no_safety_boot` no está entrenada y queda excluida del `class_map`.

## Pendiente

1. Corrección `no_boots_relabel_v1` en CVAT, para habilitar `no_safety_boot` y recuperar 315 imágenes.
2. Imágenes y vídeos propios del entorno real, para el holdout de test final.
3. TensorRT y optimización del preproceso (Fase 9).
4. Driver Intel actualizado, si se quiere usar la iGPU con OpenVINO.
