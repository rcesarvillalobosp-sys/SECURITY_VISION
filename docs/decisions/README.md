# Registro de decisiones de arquitectura (ADR)

Formato breve: contexto → decisión → consecuencias. Estado: **Aceptada** salvo indicación.

## ADR-0001 Arquitectura hexagonal en un paquete único verificado por import-linter
- **Contexto:** hay que poder cambiar cámaras, motores de inferencia, modelos y almacenamiento sin reescribir el sistema.
- **Decisión:** `core` contiene el dominio y los puertos; `modules` contiene los casos de uso y solo depende de `core`; `infrastructure` y `plugins` contienen los adaptadores; `apps/*` son las raíces de composición. Seis contratos de import-linter lo hacen cumplir en CI (por ejemplo, el núcleo no puede importar FastAPI, SQLAlchemy ni ONNX Runtime, y el dominio no puede importar numpy).
- **Consecuencias:** cada repositorio tiene su puerto y su implementación SQL, lo que añade algo de código repetitivo. A cambio, el dominio se puede probar sin base de datos.

## ADR-0002 Overlay de detecciones en el cliente
- **Decisión:** el vídeo llega al navegador por WebRTC desde MediaMTX y las detecciones viajan aparte por WebSocket; se dibujan en un `<canvas>` superpuesto. El vídeo anotado no se re-codifica.
- **Consecuencias:** se ahorra mucha CPU/GPU. En directo, la sincronización entre vídeo y recuadros es aproximada; en la evidencia de un incidente es exacta.

## ADR-0003 PyAV/FFmpeg en Windows y GStreamer en Linux
- **Contexto:** los enlaces de GStreamer para Python (PyGObject) son frágiles en Windows nativo.
- **Decisión:** dos adaptadores detrás del puerto `VideoSource`, elegidos por configuración.

## ADR-0004 Valkey en lugar de Redis
- **Contexto:** Redis ≥ 7.4 cambió a RSALv2/SSPL (y AGPL desde la versión 8).
- **Decisión:** Valkey (BSD-3), compatible a nivel de protocolo.

## ADR-0005 Exclusiones de licencia
- **Decisión:** no se usa Ultralytics (AGPL-3.0) ni las variantes de RF-DETR con licencia PML. Datasets: solo se usan los que tienen uso comercial verificado en su manifiesto (ver `ml/datasets/sources/`).

## ADR-0006 Cumplimiento con verificabilidad explícita
- **Decisión:** cada EPP se observa como presente, ausente o no verificable. Un incumplimiento solo se confirma cuando la ausencia es sostenida, con un mínimo de observaciones verificables y con histéresis. La semántica de cada clase está en `CLASS_DEFINITIONS`; por ejemplo, `safety_boot` no certifica protección.

## ADR-0007 Sesiones: JWT de acceso corto + refresh rotativo en cookie httpOnly
- **Decisión:**
  - El JWT HS256 dura 15 minutos y lleva permisos.
  - En cada petición se comprueba que la sesión no esté revocada, así un logout o un cambio de roles surte efecto de inmediato.
  - El refresh token es opaco (`<session_id>.<secreto>`) y en la base de datos solo se guarda su SHA-256. Rota en cada uso; si se reutiliza uno ya rotado, se revoca la sesión entera.
  - Viaja únicamente en una cookie `HttpOnly; SameSite=Strict`, con `Secure` en producción.
- **Consecuencias:** cada petición autenticada hace una consulta a la tabla `sessions`; se puede cachear en Valkey si hiciera falta.

## ADR-0008 PostgreSQL portable para desarrollo sin Docker
- **Contexto:** la virtualización está desactivada en este equipo y no hay permisos de administrador garantizados.
- **Decisión:** usar los binarios zip oficiales de EDB, con el clúster en el espacio del usuario, gestionado por `scripts/dev_postgres.py`. Docker Compose queda como vía estándar en cuanto Docker esté disponible.

## ADR-0010 PyAV: licencia de las ruedas binarias
- **Contexto (verificado el 2026-11-12):** la rueda de PyPI `av 19.0.2` incluye FFmpeg 9.0.2. `avcodec_license()` devuelve "LGPL version 3 or later", pero la configuración incluye `--enable-libx264` y la rueda trae `libx264-165.dll` y `libx265.dll`, que son **GPL**.
- **Decisión:**
  - Uso permitido en desarrollo y en uso interno.
  - El código solo decodifica con PyAV y publica con codificadores no GPL (NVENC, QSV, Media Foundation o libvpx). `libx264`/`libx265` están en una lista de prohibidos.
  - **Antes de distribuir el producto** hay que compilar PyAV contra un FFmpeg LGPL sin x264/x265, o usar el adaptador GStreamer. Como FFmpeg es LGPLv3, en appliances hay que revisar además las obligaciones de "User Products" (instrucciones de instalación).

## ADR-0011 Bus de control sobre PostgreSQL LISTEN/NOTIFY
- **Decisión:** las notificaciones de control (cambios de cámara, estado) viajan por NOTIFY, sin infraestructura adicional. Es difusión "como mucho una vez", así que el worker además reconcilia contra la BD cada 30 s. Los eventos que necesitan durabilidad (incidentes) usarán outbox + Valkey Streams detrás del mismo puerto `MessageBus`.

## ADR-0012 MediaMTX como punto único de conexión a cada cámara
- **Decisión:** si hay MediaMTX, las cámaras RTSP se leen a través de su proxy: la cámara sirve una sola conexión, y navegador y worker leen de MediaMTX. Las cámaras locales (USB) las publica el worker. MediaMTX escucha solo en localhost y exige usuario para publicar y para su API.

## ADR-0013 Un adaptador DETR configurable en lugar de uno por modelo
- **Decisión:** RT-DETR, RT-DETRv2 y RF-DETR comparten postproceso (consultas con logits sigmoide y cajas cxcywh, sin NMS). Un único `DetrDetectionModel` se parametriza desde `model.yaml` (normalización y nombres de entrada/salida); las subclases `rtdetr` y `rfdetr` solo fijan valores por defecto. D-FINE y DEIM encajarían igual.

## ADR-0014 Verificación de exportaciones por detecciones, con referencia previa
- **Contexto:** comparar los tensores ONNX y PyTorch elemento a elemento falla aunque el modelo sea correcto, porque la selección top-k de consultas de RT-DETR puede reordenarse. Además, `torch.onnx.export` altera el estado interno del modelo, así que la referencia calculada **después** de exportar era incorrecta. Se detectó al exportar y se diagnosticó: en 20 imágenes, 301 detecciones coinciden con Δ ≤ 1e-5.
- **Decisión:** la referencia PyTorch se calcula antes de exportar. Se comparan detecciones emparejadas (clase, score y caja, con Δ < 2e-2), tolerando las que cruzan el umbral. Si la exportación no es fiel, no se registra.

## ADR-0015 Selección explícita de GPU en OpenVINO; iGPU no validada
- **Decisión:** los dispositivos `openvino-igpu`, `openvino-dgpu` y `openvino-gpu.N` se resuelven por tipo de dispositivo. En este equipo la UHD 630 (driver de 2019) provoca un **fallo nativo** que tumba el proceso al compilar el modelo, así que **no se debe configurar** hasta actualizar el driver de Intel y validarlo. La GTX 1650 vía OpenVINO funciona, pero tarda unos 495 ms, frente a 31 ms con ONNX Runtime CUDA.

## ADR-0016 ByteTrack propio, adaptado a baja frecuencia de análisis
- **Contexto:** `supervision` haría obligatorio OpenCV. Además, ByteTrack está calibrado para 30 fps, mientras que aquí se analiza a 2–5 fps.
- **Decisión:** implementación propia con tiempos en segundos, Kalman en fotogramas de referencia de 1/30 s, rescate por distancia entre centros (normalizada por la altura) y tolerancia temporal de los tentativos. Validado con escenarios sintéticos y umbrales de regresión (fase-4.md).

## ADR-0017 Asociación EPP–persona por regiones con capacidad y algoritmo húngaro
- **Decisión:** cada EPP solo puede asignarse dentro de su región corporal, cada región tiene capacidad (1 casco, 2 guantes…) y la asignación es global. Las asignaciones con un competidor cercano se marcan como `ambiguous`, y el motor de reglas las tratará como no verificables. Los EPP sin persona plausible se reportan como `unassigned`, nunca se fuerzan.

## ADR-0018 Confirmar un incumplimiento exige evidencia positiva de ausencia
- **Contexto:** el requisito exige no confundir la ausencia de detección con la ausencia del EPP. El detector tiene falsos negativos sistemáticos en algunas escenas.
- **Decisión:** la ausencia implícita (región visible sin detección) solo puede llevar a `POSIBLE_INCUMPLIMIENTO`, que requiere revisión humana. `INCUMPLIMIENTO_CONFIRMADO` requiere además al menos 2 detecciones `no_*` en la ventana (configurable por perfil). Se prefiere perder algún incumplimiento a acusar falsamente a un trabajador.

## ADR-0009 Auditoría de solo inserción reforzada en la base de datos
- **Decisión:** un trigger en PostgreSQL rechaza cualquier UPDATE o DELETE sobre `audit_log`. La única excepción es anonimizar al actor cuando se borra su usuario (`SET NULL`).

## ADR-0019 Incidentes escritos por el worker en una transacción con outbox
- **Decisión:** el worker registra el incidente, la evidencia, las detecciones y el historial directamente en PostgreSQL, en una transacción idempotente (identificador derivado de la confirmación). Las notificaciones salen por un **outbox** que publican relés con `FOR UPDATE SKIP LOCKED`, entrega al menos una vez. NOTIFY sin outbox ("como mucho una vez") no es aceptable para incidentes.

## ADR-0020 Evidencias con URL firmadas ligadas al usuario e integridad verificada
- **Decisión:** HMAC sobre (clave, usuario, caducidad de 5 min). Cada acceso se audita con la identidad. El sha256 se verifica al servir: una evidencia alterada no se entrega. Al aplicar la retención se borran los archivos y se conservan los metadatos.

## ADR-0021 La verificabilidad precede a cualquier evidencia (corrección)
- **Contexto:** en la revisión de evidencias de la Fase 6 se encontró un incidente falso de chaleco sobre una persona de unos 35 px. La regla aceptaba `no_*` antes de comprobar si la persona era verificable.
- **Decisión:** si la persona o la región no son verificables, ninguna detección cuenta, ni de presencia ni de ausencia. Hay tests de regresión.
