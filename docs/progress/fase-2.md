# Fase 2: captura de vídeo (USB y RTSP). Resultados

Fecha: 2026-11-12.

## Entregado

| Componente | Descripción |
|---|---|
| `FrameSlot` | Cola acotada en la que siempre gana el fotograma más reciente: la captura nunca se bloquea y el análisis siempre recibe un fotograma fresco. Cuenta los descartes. |
| `PyAVVideoSource` | RTSP/RTSPS (TCP, baja latencia, plazos de apertura y lectura), archivos (bucle y ritmo de tiempo real) y USB (DirectShow, V4L2, AVFoundation). Las credenciales se inyectan solo en el momento de conectar. |
| `TestPatternSource` | Patrón sintético para pruebas (`testpattern://`). En producción está prohibido por configuración. |
| `CameraSupervisor` | Un hilo por cámara con aislamiento total, backoff exponencial con jitter, detección de atascos, reconciliación con la configuración deseada y estadísticas (fps, errores, reconexiones). |
| Módulo de cámaras | CRUD con validación (no admite credenciales en la URI ni rutas fuera de `SV_VIDEO_FILES_DIR`), credenciales AES-256-GCM ligadas al id de la cámara, auditoría sin secretos, prueba de conectividad con plazo, snapshot, descubrimiento ONVIF (WS-Discovery) y USB. |
| Worker `sv-worker` | Arranca las cámaras habilitadas, guarda los cambios de estado en BD (`cameras.last_status` + `camera_status_events`) y los notifica, publica un snapshot cada N s, consume a `analysis_fps` (aún sin inferencia), republica las cámaras locales en MediaMTX y expone métricas en `127.0.0.1:9101/metrics`. |
| Bus de eventos | `PostgresMessageBus` (LISTEN/NOTIFY). Un alta o un cambio en la API llega al worker sin reiniciarlo. |
| MediaMTX | Adaptador de su API de control. Las cámaras RTSP pasan por un proxy (una sola conexión a la cámara) y las locales se publican. Configuración de desarrollo con autenticación (`scripts/dev_mediamtx.py`). |
| Almacenamiento | `LocalFileStorage`: escritura atómica, claves validadas y URLs firmadas con HMAC. |

## Verificación (resultados reales)

- **56 tests en verde**, de los cuales 16 nuevos de esta fase:
  - Contrato `VideoSource` para todas las implementaciones.
  - Aislamiento: 3 cámaras con una caída, y las otras siguen.
  - Reconexión tras corte.
  - Consumidor lento recibe fotogramas frescos.
  - CRUD y protección de credenciales.
  - RBAC.
  - Bus PostgreSQL.
  - Worker con PostgreSQL real.
  - Cadena RTSP real publicador → MediaMTX → proxy → lector PyAV.
  - Publicación anónima rechazada.
- **Prueba de humo con procesos reales** (API + worker + MediaMTX, por separado):
  - Alta por API → el worker la arranca vía NOTIFY → estado `streaming` en BD.
  - Snapshot JPEG servido por la API.
  - MediaMTX recibe la pista H.264.
  - **El vídeo en directo se reproduce por WebRTC en el navegador** a 1280×720 (el tiempo de reproducción avanza 2,0 s en 2 s).

### Mediciones de captura (`scripts/measure_capture.py`)

Cámaras RTSP **simuladas**: patrón sintético a 1280×720 y 15 fps, publicado en MediaMTX desde otro proceso y capturado con PyAV por RTSP/TCP. Análisis a 2/s sin inferencia. Equipo: i7-9750H (12 hilos).

| Cámaras | Duración | FPS captura (por cámara) | Análisis/s | Antigüedad del fotograma al analizar | Errores / reconexiones | CPU del proceso de captura | RAM máx. |
|---|---|---|---|---|---|---|---|
| 4 | 60 s | 15,01 | 1,97 | 29–38 ms | 0 / 0 | 72 % de un núcleo (6,0 % del equipo) | 272 MB |
| 8 | 30 s | 14,98–15,12 | 1,96 | 30–43 ms | 0 / 0 | 151 % de un núcleo (12,6 % del equipo) | 482 MB |

Cómo interpretar estas cifras:
- **Descartes:** con 15 fps de captura y 2/s de análisis, 783 fotogramas en 60 s por cámara (unos 13 de cada 15) se descartan **a propósito** por backpressure. No se pierde vídeo: el análisis toma siempre el más reciente y nunca acumula retraso (antigüedad < 45 ms).
- **El escalado es lineal** (unos 18 % de un núcleo por cámara 720p15) y la RAM crece unos 52 MB por cámara.
- **Limitación:** el patrón sintético se comprime mucho. Una cámara real (texturas, ruido, más bitrate) costará más al decodificar. Son una línea base, no la capacidad final.

## No verificado o pendiente

| Elemento | Motivo | Cómo se cerrará |
|---|---|---|
| **Cámara USB real** (criterio 2) | Windows no detecta ninguna cámara en el equipo (`discover?kind=usb` devuelve una lista vacía) | Conectar una cámara USB y probar `usb:<nombre>`. El código de DirectShow está escrito, pero sin hardware no se ha probado. |
| **Cámara IP real** (criterio 3) | No hay cámara IP disponible. Sí se probó un servidor RTSP real (MediaMTX) con una fuente simulada. | Dar de alta la cámara con `rtsp://…` y sus credenciales. |
| ONVIF | WS-Discovery implementado y su parser probado; en esta red no hay dispositivos ONVIF | Probar con una cámara ONVIF |
| GStreamer | No hay entorno Linux/Docker (virtualización desactivada) | Adaptador en Linux (ADR-0003) |
| WebRTC en el dashboard propio | El frontend llega en la Fase 7. Ahora mismo se usa el reproductor integrado de MediaMTX. | Fase 7 |
| Worker y MediaMTX en `docker-compose.yml` | Añadidos, pero sin ejecutar | Cuando Docker esté disponible |
