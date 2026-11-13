# Matriz de licencias de terceros

**Estado:** borrador inicial (2026-11-12), elaborado con información conocida y **pendiente de verificar contra la fuente oficial** de cada componente antes de incorporarlo (columna *Verificado*). Ninguna dependencia entra en el repositorio sin pasar a ✅. La licencia del código **no** implica la licencia de los pesos ni del dataset: se revisan por separado.

**Actualización 2026-11-12 (Fase 1):** las dependencias Python instaladas se verifican de forma automática contra los metadatos de cada paquete. El inventario está en [docs/licenses/python-dependencies.md](docs/licenses/python-dependencies.md) y lo genera `scripts/license_report.py --check` en CI. De ahí: FastAPI MIT, Starlette BSD-3, Pydantic MIT, SQLAlchemy MIT, Alembic MIT, asyncpg Apache-2.0, argon2-cffi MIT, PyJWT MIT, cryptography Apache-2.0/BSD-3, prometheus-client Apache-2.0/BSD-2, uvicorn BSD-3, NumPy BSD-3, Pillow MIT-CMU. Única licencia no permisiva pura: certifi, MPL-2.0 (copyleft débil a nivel de archivo; se usa sin modificar). PostgreSQL 17.12 se usa con los binarios de EDB bajo la PostgreSQL License. Datasets: estado verificado en `ml/datasets/sources/*.yaml` (ver [docs/progress/etapa-datasets.md](docs/progress/etapa-datasets.md)).

Leyenda de uso comercial: ✅ permitido · ⚠️ permitido con obligaciones o matices · ❌ no apto para el producto principal.

## Componentes del producto

| Componente | Rol | Licencia (esperada) | Uso comercial | Obligaciones / notas | Verificado |
|---|---|---|---|---|---|
| Python | Runtime | PSF-2.0 | ✅ | | ⏳ |
| FastAPI / Starlette | API | MIT / BSD-3 | ✅ | Conservar el aviso | ⏳ |
| Pydantic v2 | Contratos | MIT | ✅ | | ⏳ |
| SQLAlchemy 2 / Alembic | ORM / migraciones | MIT | ✅ | | ⏳ |
| asyncpg | Driver PG | Apache-2.0 | ✅ | Preferido frente a psycopg3 (LGPL-3.0) | ⏳ |
| PostgreSQL | BD | PostgreSQL License | ✅ | Servicio externo | ⏳ |
| Valkey | Bus/caché | BSD-3 | ✅ | **Redis ≥ 7.4 cambió a RSALv2/SSPL (y AGPL-3.0 desde Redis 8)** → se prefiere Valkey | ⏳ |
| argon2-cffi | Hash de contraseñas | MIT | ✅ | | ⏳ |
| cryptography | Cifrado de credenciales | Apache-2.0 / BSD | ✅ | | ⏳ |
| GStreamer core + plugins-base/good | Pipelines de vídeo | LGPL-2.1+ | ⚠️ | Enlace dinámico; permitir la sustitución de la biblioteca. **plugins-ugly/bad** pueden incluir códecs con patentes o GPL (x264) → no se distribuyen por defecto | ⏳ |
| FFmpeg | Decodificación | LGPL-2.1+ (GPL si se compila con `--enable-gpl`) | ⚠️ | Usar compilaciones LGPL; no distribuir builds con x264/x265 GPL | ⏳ |
| PyAV | Enlace con FFmpeg | BSD-3 (*wheels* con FFmpeg LGPL) | ⚠️ | Hereda las obligaciones de FFmpeg | ⏳ |
| MediaMTX | Servidor de medios | MIT | ✅ | Binario aparte | ⏳ |
| OpenCV ≥ 4.5 | Auxiliar | Apache-2.0 | ✅ | Usar `opencv-python-headless` | ⏳ |
| NumPy | Arrays | BSD-3 | ✅ | | ⏳ |
| ONNX Runtime (+ GPU) | Inferencia | MIT | ✅ | El paquete GPU depende de CUDA/cuDNN (licencias NVIDIA) | ⏳ |
| OpenVINO | Inferencia Intel | Apache-2.0 | ✅ | | ⏳ |
| CUDA / cuDNN runtime | Aceleración | NVIDIA EULA (propietaria, gratuita) | ⚠️ | Redistribución limitada a los componentes permitidos por el EULA | ⏳ |
| TensorRT | Aceleración | NVIDIA SLA (propietaria, gratuita) | ⚠️ | Opcional, nunca obligatoria. Revisar las cláusulas de redistribución | ⏳ |
| NVIDIA DeepStream | Pipeline avanzado | NVIDIA DeepStream SDK License | ⚠️ | Fase avanzada; adaptador opcional | ⏳ |
| supervision (Roboflow) | ByteTrack / utilidades | MIT | ✅ | Alternativa: portar ByteTrack (MIT) directamente | ⏳ |
| ByteTrack (original) | Algoritmo | MIT | ✅ | El repositorio original depende de YOLOX (Apache-2.0) | ⏳ |
| scipy | Asignación húngara | BSD-3 | ✅ | | ⏳ |
| prometheus-client | Métricas | Apache-2.0 | ✅ | | ⏳ |
| Prometheus | Monitoreo | Apache-2.0 | ✅ | | ⏳ |
| Grafana | Dashboards técnicos | **AGPL-3.0** | ⚠️ | Se usa como servicio aparte y sin modificar → sin obligación de liberar nuestro código. No se embebe en el producto | ⏳ |
| OpenTelemetry SDK | Trazas | Apache-2.0 | ✅ | | ⏳ |
| React / Vite / Tailwind CSS | Frontend | MIT | ✅ | | ⏳ |
| TanStack Query | Frontend | MIT | ✅ | | ⏳ |
| Apache ECharts | Gráficos | Apache-2.0 | ✅ | | ⏳ |
| openpyxl | Excel | MIT | ✅ | | ⏳ |
| WeasyPrint | PDF | BSD-3 | ✅ | Depende de Pango (LGPL), que en Windows es delicado; alternativa: ReportLab (BSD) | ⏳ |
| SeaweedFS | Almacenamiento S3 (futuro) | Apache-2.0 | ✅ | **MinIO es AGPL-3.0** → evitar como componente embebido | ⏳ |
| import-linter | Reglas de arquitectura | BSD-2 | ✅ | Solo desarrollo | ⏳ |

## Modelos de detección (código ≠ pesos)

| Modelo | Código | Pesos preentrenados | Uso comercial | Notas | Verificado |
|---|---|---|---|---|---|
| RT-DETR / RT-DETRv2 (repo oficial `lyuwenyu/RT-DETR`) | Apache-2.0 | Apache-2.0 según el repo; entrenados en COCO/Objects365 | ⚠️ | Verificar la licencia de los pesos publicados y los términos de los datasets de preentrenamiento | ⏳ |
| RT-DETR en Hugging Face Transformers | Apache-2.0 | Según la *model card* de cada checkpoint | ⚠️ | Revisar cada *model card* | ⏳ |
| RT-DETR en **Ultralytics** | **AGPL-3.0** | AGPL-3.0 / licencia comercial | ❌ | **No usar** la implementación de Ultralytics | ⏳ |
| RF-DETR (Roboflow) | Apache-2.0 | Las variantes pequeñas (Nano/Small/Medium/Base) se publican como Apache-2.0; **las variantes grandes usan la Platform Model License (PML) de Roboflow** | ⚠️ / ❌ | Usar solo las variantes Apache-2.0; confirmar en el repo y en `LICENSE` de cada peso | ⏳ |
| D-FINE / DEIM | Apache-2.0 | Apache-2.0 (verificar) | ✅ | Alternativas DETR en tiempo real | ⏳ |
| YOLOX (Megvii) | Apache-2.0 | Apache-2.0 | ✅ | Alternativa YOLO compatible | ⏳ |
| YOLOv5/v8/v11 (Ultralytics) | AGPL-3.0 | AGPL-3.0 | ❌ | Excluido salvo licencia comercial | ⏳ |
| YOLOv7 / YOLOv9 (originales) | GPL-3.0 | GPL-3.0 | ❌ | Copyleft fuerte | ⏳ |
| YOLO-NAS (Deci) | Apache-2.0 | **Licencia de pesos no comercial** | ❌ | | ⏳ |

## Datasets de EPP (candidatos — todos pendientes)

La licencia de cada dataset de Roboflow Universe la fija quien lo sube, y es frecuente encontrar CC BY 4.0 (con atribución), CC BY-NC (no comercial → ❌) o datasets sin licencia clara (→ ❌ hasta aclararlo). Antes de entrenar se documentará, por cada dataset: licencia, origen de las imágenes, si permite uso comercial del **modelo derivado**, la atribución exigida y la presencia de datos personales (rostros). Candidatos a evaluar: *Hard Hat Workers*, *SH17*, *Construction Site Safety* y variantes en Roboflow Universe, *Pictor-PPE*. **Ninguno queda aprobado en este documento.**

Recomendación estratégica: complementar los datasets públicos con imágenes propias del entorno objetivo, etiquetadas en CVAT (MIT). Es la forma más fiable de obtener precisión real y derechos claros sobre el modelo.

## Herramientas de ML y anotación (fuera del producto en ejecución)

| Herramienta | Licencia | Notas |
|---|---|---|
| CVAT | MIT | Servicio de anotación aparte |
| PyTorch | BSD-3 | Entrenamiento |
| PaddlePaddle | Apache-2.0 | Solo si se elige un modelo de PaddleDetection |
| DVC | Apache-2.0 | Versionado de datasets/modelos |
| MLflow | Apache-2.0 | Registro de experimentos (opcional) |
