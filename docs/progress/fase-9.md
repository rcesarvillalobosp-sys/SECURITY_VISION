# Fase 9: rendimiento. Resultados

Fecha: 2026-11-13. Todas las cifras son **medidas** en este equipo: i7-9750H (12 hilos), 16 GB de RAM, GTX 1650 de portátil (4 GB, driver 591.74), Windows 11, ONNX Runtime CUDA FP32 y modelo `rtdetr-v2-r18-ppe-pilot@1`. Los JSON con cada muestra están en `ml/evaluation/results/load_*.json` y `engine_latency_*.json`.

## Cómo se mide

- **Cámaras IP simuladas** (`scripts/rtsp_simulator.py`): un vídeo 1080p a 15 fps publicado por RTSP en MediaMTX **sin recodificar** (copia de paquetes, ~0 % de CPU), una cámara por ruta y cada una desfasada en el vídeo. El worker las lee igual que a una cámara real: RTSP a través de MediaMTX, decodificación, detección, tracking, reglas y evidencias.
- **Vídeos de carga** (`scripts/make_load_video.py`): imágenes reales de EPP a 1080p y 15 fps, con un fotograma clave cada 2 s.
  - **MPEG-4 Part 2:** codificador nativo LGPL. Se usó para comparar las optimizaciones.
  - **H.264 Constrained Baseline:** generado con NVENC, el codificador por hardware de la GPU (sin x264, que es GPL). Es el caso realista y el único que el navegador reproduce por WebRTC.
- **Prueba de carga** (`scripts/load_test.py`):
  - para cada nivel de N cámaras, 20 s de calentamiento y 60 s de muestreo cada 2 s;
  - qué se mide: análisis por segundo de cada cámara, tiempos por etapa del worker, latencia de extremo a extremo (captura → resultado), CPU del equipo y de cada proceso, RAM, y uso, VRAM y temperatura de la GPU;
  - al terminar borra las cámaras.
  - El objetivo de cada cámara es **2 análisis por segundo**.

## Instrumentación nueva (queda en producción)

- `sv_stage_ms{stage,quantile}`: tiempos por etapa en una ventana de 60 s. Etapas: preproceso, espera de GPU, inferencia, postproceso, tracking + reglas, compactado del contexto, evidencias, extremo a extremo y tamaño de lote.
- `sv_worker_thread_cpu_seconds{group}`: CPU por grupo de hilos (captura, análisis, despachador, nativos, principal). En este Windows py-spy no pudo adjuntarse al proceso (error 87), y con esta métrica el perfilado funciona en producción sin herramientas externas.
- `sv_gpu_*` (NVML): uso, VRAM, temperatura, **estado de energía (P-state)**, relojes y motivos de limitación activos. También `sv_system_cpu_percent` y `sv_system_memory_used_bytes`.
- `sv_inference_batches_total{size}`: lotes inferidos, por tamaño.
- **OpenTelemetry** (opcional, `SV_OTEL_ENDPOINT`):
  - trazas de la API (FastAPI) y del ciclo de análisis (`analysis.frame` → `detect`, `analyze`, `evidence_and_events`), con muestreo configurable;
  - desactivado no tiene coste: sin proveedor, cada span es un `nullcontext`.

## Hallazgo principal: la GPU del portátil está limitada por energía

| Medida del motor aislado (`ml/evaluation/engine_latency.py`) | Resultado |
|---|---|
| Inferencia, lote 1 (llamadas seguidas) | **155 ms** (en la Fase 3 fueron 49 ms) |
| Estado de la GPU durante la medición | **P5**, memoria a **810 MHz**, limitadores `sw_power_cap` y `sw_thermal` activos |
| Por imagen con lote 2 / 4 / 8 | 145 / 140 / 129 ms |
| Lote 1 cada 500 ms | 156 ms |
| `cudnn_conv_algo_search` HEURISTIC / EXHAUSTIVE / DEFAULT | 155,6 / 155,2 / 155,0 ms |

Incluso con carga continua, el portátil (enchufado, plan «Equilibrado») mantiene la GPU en P5 con la memoria de vídeo a 810 MHz. El modelo depende del ancho de banda de memoria, de ahí que tarde 3 veces más que en la Fase 3. **No es un fallo del código**, y no he cambiado ajustes del sistema. Todas las comparaciones de esta fase se hicieron en las mismas condiciones.

Recomendaciones para la persona usuaria:
- plan de energía «Máximo rendimiento»;
- en el Panel de control de NVIDIA, «Modo de administración de energía: preferir rendimiento máximo» para Python;
- buena ventilación.

Las métricas `sv_gpu_pstate` y `sv_gpu_throttle_active` muestran si el equipo está limitado.

## Optimizaciones y efecto medido

Cámaras MPEG-4 (comparación controlada entre versiones del código). Formato de las celdas: análisis por segundo / latencia p95 de extremo a extremo.

| N | base | opt1 | opt2 |
|---|---|---|---|
| 1 | 2,00 / 0,30 s | 2,00 / 0,29 s | 2,00 / 0,32 s |
| 2 | 4,00 / 0,34 s | 4,00 / 0,34 s | 3,98 / 0,32 s |
| 4 | 4,40 / 1,17 s | 5,20 / 1,04 s | **5,56 / 0,92 s** |
| 6 | 4,01 / 2,12 s | 5,14 / 1,48 s | **5,64 / 1,33 s** |
| 8 | 3,89 / 2,47 s | 5,44 / 2,02 s | **5,96 / 1,56 s** |

| 8 cámaras | base | opt2 | cambio |
|---|---|---|---|
| Capacidad total | 3,89 análisis/s | 5,96 | **+53 %** |
| CPU del worker | 368 % | 256 % | **−30 %** (con un 53 % más de trabajo) |
| Memoria del worker | 2,42 GB | 1,21 GB | **−50 %** |
| Latencia p95 de extremo a extremo | 2,47 s | 1,56 s | −37 % |
| Uso de la GPU | 60 % | 82 % | ahora la GPU es el límite |

1. **opt1: preproceso en paralelo y micro-batching voraz** (`DetectionService`).
   - Antes, cada cámara redimensionaba su fotograma dentro del turno de GPU: con 8 cámaras, la GPU esperaba al 60 % de uso.
   - Ahora cada cámara prepara su fotograma en su propio hilo, y un despachador infiere juntas todas las peticiones en cola, hasta `SV_DETECTION_MAX_BATCH`=4.
   - Con poca carga no hay espera añadida: el lote es de 1. Con 8 cámaras, los lotes son de 4.
2. **Búfer de contexto en JPEG.**
   - Los 12 fotogramas de contexto por cámara se guardaban en bruto: ~6 MB cada uno a 1080p.
   - Ahora se guardan en JPEG de calidad 90, ajustados al tamaño de la evidencia. El fotograma que confirma el incidente se mantiene en bruto para el recorte.
3. **opt2: conversión a RGB perezosa.**
   - Antes, cada fotograma capturado (15 por segundo) se convertía a RGB aunque el análisis solo usara 2.
   - Ahora `Frame.lazy` conserva el fotograma decodificado y lo convierte solo si se lee.
4. **opt2: decodificador de un hilo.**
   - Medido con una cámara RTSP 1080p a 15 fps: un hilo usa el **15 %** de CPU; `AUTO` usa el 22 % y crea 13 hilos por cámara.
   - Para 4K se puede volver al modo automático con `decode_threads: 0`.

**Desglose de CPU por hilos con 8 cámaras.** Dato de la ejecución de 8 cámaras con el código de opt1 (el desglose por hilos se añadió en ese punto):

| Hilos | CPU |
|---|---|
| Nativos (decodificadores FFmpeg con `AUTO`) | **248 %** |
| Análisis | 77 % |
| Captura | 66 % |
| Despachador | 58 % |

Tras opt2 los nativos bajan al 9 %, y la decodificación pasa a contarse en los hilos de captura (68 %).

## Resultado final realista: cámaras H.264

| N cámaras × fps de análisis | Análisis/s | ¿Objetivo? | Latencia p50 / p95 | CPU del equipo | Memoria del worker | GPU |
|---|---|---|---|---|---|---|
| 1 × 2 | 1,99 | ✅ | 0,25 / 0,30 s | 27 % | 1,01 GB | 30 % |
| 2 × 2 | 3,98 | ✅ | 0,27 / 0,32 s | 33 % | 1,04 GB | 60 % |
| 4 × 2 | 5,32 | ❌ (1,33 por cámara) | 0,78 / 1,01 s | 50 % | 1,15 GB | 75 % |
| 8 × 2 | 5,86 | ❌ (0,73 por cámara) | 1,44 / 1,66 s | 63 % | 1,31 GB | 82 % |
| **5 × 1** | 4,99 | ✅ | 0,61 / 0,83 s | 52 % | 1,23 GB | 74 % |
| **8 × 0,6** | 4,80 | ✅ | 0,67 / 1,08 s | 58 % | 1,32 GB | 71 % |

**Capacidad de este equipo con la GPU limitada: unos 5,5–6 análisis por segundo en total.** Las configuraciones verificadas son 2 cámaras a 2 fps, 5 a 1 fps y 8 a 0,6 fps.

Las reglas de EPP piden ausencia sostenida durante varios segundos, así que 0,6–1 fps por cámara es suficiente para confirmar incumplimientos. La frecuencia por cámara (`analysis_fps`) se elige al dar de alta la cámara.

Con H.264, **MediaMTX consume 76–114 % de CPU** (con MPEG-4 eran 8–39 %) para retransmitir 8 cámaras a 4 Mbit/s. Es un coste real que hay que dimensionar.

## Lo que se probó y se descartó (con datos)

- **FP16 con ONNX Runtime CUDA** (`ml/export/convert_fp16.py`): **más lento**, 230 ms frente a 155 ms con lote 1. La GTX 1650 no tiene Tensor Cores y la conversión llena el grafo de `Cast`. El primer convertidor (onnxconverter-common) generaba además un modelo inválido. La variante FP16 no se registra.
- **Trickle ICE en WHEP:**
  - **más lento**: mediana de 1,79 s frente a 1,26 s hasta el primer fotograma, en 15 + 15 mediciones en el navegador;
  - añade una ida y vuelta, y aquí la recolección local de candidatos es casi instantánea;
  - se conserva la oferta completa y se añade el DELETE de la sesión al cerrar: MediaMTX libera las sesiones al momento (comprobado con su API).
  - Con cámaras H.264 el vídeo arranca en **0,8–2,6 s**. La variación la marca la espera al siguiente fotograma clave (GOP de 2 s): para arranques más rápidos, configurar en las cámaras un GOP de 1 s.
- **Sin *spinning* en ONNX Runtime:** sin efecto (~74 % de CPU con o sin él). La CPU del hilo despachador es la espera activa del driver de CUDA mientras la GPU trabaja.
- **`reducing_gap` en el redimensionado:** mismo resultado y más lento (28,6 frente a 24,1 ms).

## TensorRT: pendiente

- ONNX Runtime 1.31 necesita TensorRT **10** (`nvinfer_10.dll`). Para CUDA 13 en Windows existe `tensorrt-cu13-libs==10.16.1.11`, que admite SM 7.5 (Turing) y ocupa **1,9 GB**.
- La descarga desde `pypi.nvidia.com` fue a 0,1–0,2 MB/s (662 MB en ~2 h) y la detuve para no bloquear la fase.
- TensorRT es software propietario de NVIDIA, así que se instala fuera de las dependencias del proyecto:

```bash
uv pip install --index-url https://pypi.nvidia.com "tensorrt-cu13-libs==10.16.1.11"
```

- Con él instalado, el motor ya admite el dispositivo `tensorrt` (FP16 y caché de motores en `var/trt_cache`). Habrá que medirlo con `ml/evaluation/engine_latency.py --device tensorrt` y con la prueba de carga. No se publica ninguna cifra sin medirla.

## Trazas: verificación real

- **Receptor:** como receptor OTLP/HTTP propio se usó `scripts/otlp_sink.py`, que decodifica el protobuf real. No se pudo ejecutar el binario de Jaeger descargado, así que se borró.
- **Resultado:** con 4 cámaras y muestreo de 0,2 llegaron 421 spans del worker y de la API. **100 de 100** trazas de fotograma tenían su jerarquía completa.
- **Sobrecarga:** 5,88 análisis/s con trazas frente a 5,56/s sin ellas. La diferencia está dentro del ruido: no se aprecia sobrecarga.

## Verificación

- **Backend:** 145 tests (10 nuevos).
  - Micro-batching: agrupa bajo carga; nunca mezcla los resultados de distintas cámaras; el preproceso ocurre en los hilos de las cámaras; sin espera añadida con poca carga; propagación de errores; modelo sin `prepare`; cierre ordenado.
  - Ventana temporal de los tiempos por etapa; fotograma perezoso; trazas (desactivadas, jerarquía y muestreo).
  - El cambio de modelo en caliente de la Fase 8 sigue pasando con el nuevo servicio: el modelo anterior se cierra drenando sus lotes.
- **Web:** `tsc` y 7 tests vitest. CI local en verde.
- **Navegador:** vídeo WebRTC 1080p H.264 de la cámara simulada y 40 mediciones del tiempo hasta el primer fotograma.

## Limitaciones

- **GPU limitada por la política de energía y temperatura del portátil.** En un equipo de escritorio, o con «máximo rendimiento», la capacidad debería ser bastante mayor, pero no lo he medido.
- **TensorRT** sin evaluar, por la velocidad de descarga.
- **El hilo despachador consume casi un núcleo** esperando a la GPU (espera activa del driver de CUDA). ONNX Runtime no expone el modo de espera bloqueante.
- **Las cámaras simuladas** son la misma secuencia desfasada, no escenas distintas. El número de personas por imagen (1 a 8) afecta poco al coste: tracking + reglas cuestan 2–7 ms.
- **Decodificación por GPU (NVDEC) no evaluada:** la decodificación por CPU ya no es el cuello de botella.
