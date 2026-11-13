# Instalación nativa en Windows (sin Docker ni permisos de administrador)

Probada de principio a fin en una copia limpia del repositorio (Fase 10, ver [informe](../progress/fase-10.md)). Todo escucha en `127.0.0.1` salvo lo que se abra a la red local en el paso 9.

## Requisitos

| Componente | Versión probada | Notas |
|---|---|---|
| Windows 10/11 x64 | 11 Pro | Sin permisos de administrador |
| [uv](https://docs.astral.sh/uv/) | 0.13 | Instala Python 3.12 por su cuenta |
| [Node.js](https://nodejs.org/) | 26 | Solo para compilar la web |
| [Git](https://git-scm.com/) | — | |
| PostgreSQL 17, binarios portables de EDB | 17.12 | [Descarga](https://www.enterprisedb.com/download-postgresql-binaries): `postgresql-17.x-windows-x64-binaries.zip` |
| [MediaMTX](https://github.com/bluenviron/mediamtx/releases) | 1.21.3 | `mediamtx_v1.21.3_windows_amd64.zip`. Verificar su sha256 con el `checksums.sha256` de la publicación |
| GPU NVIDIA (opcional) | GTX 1650, driver 591 | CUDA y cuDNN se instalan como paquetes de Python; basta con el driver. Sin GPU, la inferencia va en CPU |

## Pasos

**1. Código y dependencias**

```bash
git clone <repositorio> security-vision
cd security-vision
uv sync --python 3.12 --extra inference --extra otel
```

**2. Web**

```bash
npm --prefix apps/web ci
npm --prefix apps/web run build
```

**3. Binarios.** Extraer PostgreSQL en `%LOCALAPPDATA%\security-vision\pg17` (debe quedar `pg17\pgsql\bin`) y MediaMTX en `%LOCALAPPDATA%\security-vision\mediamtx`. Con otras rutas, definir `SV_PG_HOME` (la carpeta que contiene `bin\`) y `SV_MEDIAMTX_HOME`.

**4. Configuración y secretos**

```bash
copy .env.example .env
uv run svctl gen-secrets
```

Pegar `SV_JWT_SECRET` y `SV_SECRETS_KEY` en `.env`. Completar `SV_BOOTSTRAP_ADMIN_EMAIL` y `SV_BOOTSTRAP_ADMIN_PASSWORD` (12 caracteres o más, con 3 tipos). Añadir `SV_WEB_DIST=apps/web/dist`.

**5. Base de datos**

```bash
uv run python scripts/dev_postgres.py init
uv run svctl migrate
uv run svctl bootstrap
```

`init` crea el clúster en `%LOCALAPPDATA%\security-vision\pgdata`:
- otra carpeta: `SV_PG_DATA`; otro puerto: `SV_PG_PORT`;
- escucha solo en `127.0.0.1:5433`, con autenticación SCRAM;
- crea el rol `security_vision` y las bases `security_vision` y `security_vision_test`;
- escribe las credenciales en `.env` sin mostrarlas.

**6. Modelos.** Los `.onnx` no se versionan (pesan unos 80 MB y el registro guarda su sha256). Hay dos opciones:
- **Copiarlos** desde una instalación existente o una copia de seguridad: `ml/model_registry/<modelo>/<versión>/model.onnx`. Al cargar se comprueba que el sha256 coincide con `model.yaml`.
- **Regenerar el detector COCO:**

  ```bash
  uv sync --extra train
  uv run python ml/export/export_rtdetr_hf.py
  ```

  Descarga los pesos de Hugging Face en un commit fijado. El modelo EPP piloto se entrena con `ml/training/train_rtdetr.py`; ver [modelos](../models/README.md).

**7. MediaMTX**

```bash
uv run python scripts/dev_mediamtx.py config
```

Genera la configuración y sus credenciales en `.env`:
- autorización HTTP contra la API;
- solo RTSP y WebRTC; MoQ, RTMP, HLS y SRT apagados.

**8. Arranque.** Cada uno en su terminal, en este orden:

```bash
uv run python scripts/dev_postgres.py start
uv run svctl serve
uv run python scripts/dev_mediamtx.py run
uv run sv-worker
```

Comprobación:

```bash
uv run svctl doctor
```

Abrir http://127.0.0.1:8000 y entrar con el administrador inicial. Después:
- **quitar `SV_BOOTSTRAP_ADMIN_PASSWORD` de `.env`**;
- cambiar la contraseña en «Mi cuenta».

**9. Acceso desde otros equipos de la red (opcional)**

```bash
uv run python scripts/dev_mediamtx.py config --lan --origin http://192.168.1.20:8000 --host 192.168.1.20 --public-webrtc-url http://192.168.1.20:8889
uv run svctl serve --host 0.0.0.0
```

Con `SV_CORS_ORIGINS=["http://192.168.1.20:8000"]`. Abrir en el cortafuegos de Windows los puertos 8000, 8889/tcp y 8189/udp. Fuera de una red de confianza, poner HTTPS delante ([ejemplo con Caddy](../../deploy/Caddyfile.example)).

**Tras reiniciar el equipo:** repetir el paso 8. Los procesos no se instalan como servicios de Windows.

## Verificación del desarrollo

```bash
uv sync --extra ml --extra inference --extra otel
uv run python scripts/check.py
```

Ejecuta ruff, las reglas de arquitectura, `alembic check`, los tests (unitarios e integración contra PostgreSQL real, **exclusivamente** en `SV_TEST_DATABASE_URL`, que debe terminar en `_test`), las licencias, la documentación de la API y los tipos y tests de la web.

Para desarrollar la web con recarga en caliente: `npm --prefix apps/web run dev` (http://localhost:5173, con proxy a la API).

## Alertas por correo y webhook

- **Correo:** `SV_SMTP_HOST`, `SV_SMTP_PORT`, `SV_SMTP_SECURITY` (`starttls`, `ssl` o `none`; `none` no se permite en producción), `SV_SMTP_USER`, `SV_SMTP_PASSWORD` y `SV_SMTP_FROM`. Sin `SV_SMTP_HOST`, el canal de correo aparece como no disponible.
- **Enlaces:** con `SV_PUBLIC_WEB_URL`, los avisos incluyen un enlace al incidente.
- **Webhooks:** por seguridad (SSRF) se rechazan los destinos privados o locales. Para un receptor en la LAN: `SV_ALERT_WEBHOOK_ALLOW_PRIVATE=true`.
- **SMTP de pruebas local**, sin enviar correo real:

  ```bash
  uv run python -m aiosmtpd -n -l 127.0.0.1:2525
  ```

  con `SV_SMTP_HOST=127.0.0.1`, `SV_SMTP_PORT=2525` y `SV_SMTP_SECURITY=none`.

## Rendimiento y pruebas de carga

- **Energía de la GPU (portátiles):** con el plan «Equilibrado», la GTX 1650 se quedó en P5 y la inferencia tardó 155 ms en lugar de 49. Conviene usar el plan «Máximo rendimiento» y, en el panel de NVIDIA, «preferir rendimiento máximo». En las métricas del worker, `sv_gpu_pstate` y `sv_gpu_throttle_active` lo muestran.
- **Prueba de carga reproducible:**
  1. `uv run python scripts/make_load_video.py --codec h264_nvenc --out var/videos/load_1080p15_h264.mp4`
  2. `uv run python scripts/rtsp_simulator.py --cameras 8 --video var/videos/load_1080p15_h264.mp4`
  3. sin otras cámaras: `uv run python scripts/load_test.py --cameras 1 2 4 8 --analysis-fps 2 --label prueba`
- **Motor aislado:** `uv run python ml/evaluation/engine_latency.py --device cuda`
- **Trazas:** un receptor OTLP (Jaeger, Tempo, un Collector o `scripts/otlp_sink.py`) y `SV_OTEL_ENDPOINT=http://127.0.0.1:4318`.
- **Cámaras 4K:** `"decode_threads": 0` en las opciones de la fuente.
