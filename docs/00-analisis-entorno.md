# Análisis del entorno de desarrollo

Fecha del análisis: 2026-11-12. Los datos se obtuvieron con consultas al sistema (WMI, `nvidia-smi` y comprobación de binarios en el `PATH`). No se ha hecho todavía ninguna medición de rendimiento.

## Hardware

| Recurso | Valor detectado | Implicación |
|---|---|---|
| CPU | Intel Core i7-9750H (6 núcleos / 12 hilos, 2.6 GHz) | Suficiente para 1–2 cámaras con inferencia en CPU a baja frecuencia de análisis. Compatible con OpenVINO (CPU). |
| RAM | 15.9 GB | Alcanza para el desarrollo, pero se queda justa con Docker, PostgreSQL, el worker, el frontend y el IDE abiertos a la vez. |
| GPU dedicada | NVIDIA GeForce GTX 1650, 4 GB VRAM, compute capability 7.5 (Turing TU117), driver 591.74 | Admite CUDA 12.x y TensorRT. **No tiene Tensor Cores**: FP16 funciona, pero sin la aceleración propia de Tensor Cores. Los 4 GB de VRAM limitan el tamaño del modelo y del lote. |
| GPU integrada | Intel UHD Graphics 630 | Posible destino de OpenVINO GPU y de decodificación por hardware (QSV). |
| Disco | C: 122.6 GB libres de 475.9 GB | Válido para el desarrollo. Las evidencias y grabaciones necesitan una política de retención desde el principio. |
| Cámara | **No se detectó ninguna cámara** (clases `Camera`/`Image`) | Hay que revisar si la webcam integrada está desactivada (BIOS, interruptor físico o privacidad de Windows) o conectar una cámara USB externa. |

## Software

| Herramienta | Estado |
|---|---|
| Python | 3.13.17 (sistema) + `uv` disponible → se gestionará un intérprete fijado por proyecto |
| Node.js | v26.13.0 (npm disponible, pnpm no) |
| Git | 2.56 (la carpeta del proyecto aún **no** es un repositorio) |
| `nvidia-smi` | Disponible. `CUDA_PATH` no está definido (no hay CUDA Toolkit instalado; con ONNX Runtime GPU basta con las bibliotecas de runtime vía pip) |
| Docker / Docker Compose | **No instalado** |
| WSL2 | **No instalado** |
| Virtualización en firmware | **Reporta `False`** → hay que activar VT-x en la BIOS antes de instalar Docker Desktop o WSL2 |
| FFmpeg, GStreamer, MediaMTX, PostgreSQL | No instalados |

## Bloqueos y riesgos detectados

1. **Docker no se puede usar todavía.** Docker Desktop en Windows necesita WSL2 o Hyper-V, y ambos requieren la virtualización activada en la BIOS. Hasta que se active, PostgreSQL, MediaMTX y el resto de servicios tienen que ejecutarse de forma nativa.
2. **GStreamer + Python en Windows nativo.** Los instaladores oficiales de GStreamer para Windows no traen enlaces de Python (PyGObject) fáciles de usar. En contenedores Linux (o WSL2) sí funcionan bien. Decisión: GStreamer será el adaptador principal en Linux/Docker, y en Windows nativo el desarrollo usará el adaptador FFmpeg (PyAV). Ambos implementan la misma interfaz (ver ADR-0003).
3. **Sin cámara disponible.** Las fases 2 y 3 se pueden validar con archivos de vídeo y un stream RTSP local generado con MediaMTX + FFmpeg, pero el criterio de aceptación "conectar cámara USB" exige hardware real.
4. **Modelo EPP.** No hay ningún modelo preentrenado con licencia permisiva que podamos garantizar que detecta casco, chaleco **y botas** con la precisión necesaria. Hará falta un dataset con licencia verificada y un entrenamiento propio (ver la matriz de licencias). Las botas son la clase más difícil: los pies suelen quedar fuera de cuadro, ocultos o a muy baja resolución.

## Capacidad estimada (pendiente de medir)

No se publican cifras de FPS hasta medirlas en la Fase 3 con el benchmark del proyecto (`tests/performance`). Hipótesis de trabajo que habrá que validar:

- ONNX Runtime CUDA en la GTX 1650 con un detector ligero (RT-DETR-R18 o RF-DETR-Nano) a 640×640 debería permitir analizar varias cámaras a 2–5 análisis/s cada una.
- En CPU (ONNX Runtime u OpenVINO), 1–2 cámaras a 1–2 análisis/s.

La frecuencia de análisis por cámara es configurable precisamente para ajustar la carga al hardware real.
