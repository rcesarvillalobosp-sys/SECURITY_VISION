# Instalación local en Windows (sin Docker ni permisos de administrador)

Pensada para este equipo mientras la virtualización siga desactivada en la BIOS.

1. **Python**: `uv` instala Python 3.12 automáticamente (`uv sync --python 3.12 --extra ml`).
2. **PostgreSQL 17 portable**: descargar los binarios zip de EDB (`postgresql-17.x-windows-x64-binaries.zip`, desde https://www.enterprisedb.com/download-postgresql-binaries) y extraerlos, por ejemplo en `%LOCALAPPDATA%\security-vision\pg17`. Si se usa otra ruta, definir `SV_PG_HOME` (la carpeta que contiene `bin\`).
3. **Secretos**: `uv run svctl gen-secrets >> .env`, y añadir `SV_BOOTSTRAP_ADMIN_EMAIL` y `SV_BOOTSTRAP_ADMIN_PASSWORD`.
4. **Clúster**: `uv run python scripts/dev_postgres.py init`. Crea el clúster en `%LOCALAPPDATA%\security-vision\pgdata` escuchando solo en `127.0.0.1:5433`, con autenticación SCRAM, el rol `security_vision` y las bases `security_vision` y `security_vision_test`. Escribe las URLs y contraseñas en `.env` y no las muestra por pantalla.
5. `uv run svctl migrate`, luego `uv run svctl bootstrap`, luego `uv run svctl serve`.

Tras reiniciar el equipo: `uv run python scripts/dev_postgres.py start`.

## Notas

- El clúster no se registra como servicio de Windows. Arranca con `start` y se detiene con `stop`.
- Los tests de integración usan **exclusivamente** `SV_TEST_DATABASE_URL`, que debe terminar en `_test`, y la vacían en cada test.

## MediaMTX y worker (Fase 2)

1. Descargar `mediamtx_vX.Y.Z_windows_amd64.zip` de https://github.com/bluenviron/mediamtx/releases, verificar su sha256 con `checksums.sha256` y extraerlo en `%LOCALAPPDATA%\security-vision\mediamtx`.
2. `uv run python scripts/dev_mediamtx.py config`: genera la configuración autenticada y las variables `SV_MEDIAMTX_*` en `.env`.
3. En terminales separados:
   - `uv run python scripts/dev_mediamtx.py run`
   - `uv run svctl serve`
   - `uv run sv-worker`
4. Para probar sin cámaras, añade `SV_ALLOW_TEST_SOURCES=true` y da de alta una cámara `source_type: test` con `testpattern://?width=1280&height=720&fps=15`. El vídeo se ve en `http://127.0.0.1:8889/<ruta>/`; la URL WebRTC aparece en la respuesta de la API.
5. Métricas del worker: `http://127.0.0.1:9101/metrics`.

## Alertas por correo y webhook (Fase 8)

- **Correo:** define `SV_SMTP_HOST`, `SV_SMTP_PORT`, `SV_SMTP_SECURITY` (`starttls`, `ssl` o `none`; `none` no se permite en producción), `SV_SMTP_USER`, `SV_SMTP_PASSWORD` y `SV_SMTP_FROM` en `.env`. Sin `SV_SMTP_HOST` el canal de correo aparece como no disponible.
- **Enlaces:** con `SV_PUBLIC_WEB_URL` (por ejemplo `http://localhost:5173`) los avisos incluyen un enlace al incidente.
- **Webhooks en la red local:** por seguridad (SSRF) se rechazan los destinos privados o locales. Para un receptor en la LAN, activa `SV_ALERT_WEBHOOK_ALLOW_PRIVATE=true`.
- Los canales se crean en **Administración › Alertas**; el botón «Enviar prueba» comprueba la configuración sin crear incidentes.
- **SMTP de pruebas local** (sin enviar correo real): `uv run python -m aiosmtpd -n -l 127.0.0.1:2525` y `SV_SMTP_HOST=127.0.0.1`, `SV_SMTP_PORT=2525`, `SV_SMTP_SECURITY=none`.

Tras cambiar `.env`, reinicia la API (`svctl serve`): el despachador de alertas se ejecuta en su proceso.

## Rendimiento y pruebas de carga (Fase 9)

- **Energía de la GPU (portátiles):** con el plan «Equilibrado» la GTX 1650 se quedó en P5, con la memoria a 810 MHz, y la inferencia tardó 155 ms en lugar de 49. Para producción conviene usar el plan «Máximo rendimiento» y, en el Panel de control de NVIDIA, «preferir rendimiento máximo». En `/metrics` del worker, `sv_gpu_pstate` y `sv_gpu_throttle_active` muestran si la GPU está limitada.
- **Prueba de carga reproducible:**
  1. `uv run python scripts/make_load_video.py --codec h264_nvenc --out var/videos/load_1080p15_h264.mp4`
  2. `uv run python scripts/rtsp_simulator.py --cameras 8 --video var/videos/load_1080p15_h264.mp4`
  3. con MediaMTX, la API y el worker en marcha, y sin otras cámaras: `uv run python scripts/load_test.py --cameras 1 2 4 8 --analysis-fps 2 --label prueba`
- **Motor aislado:** `uv run python ml/evaluation/engine_latency.py --device cuda`
- **Trazas:** `uv sync --extra otel`; arrancar un receptor (Jaeger/Tempo/Collector o `scripts/otlp_sink.py`) y definir `SV_OTEL_ENDPOINT=http://127.0.0.1:4318`.
- **Cámaras 4K:** si la decodificación de un hilo no da abasto, añadir `"decode_threads": 0` a las opciones de la fuente.
