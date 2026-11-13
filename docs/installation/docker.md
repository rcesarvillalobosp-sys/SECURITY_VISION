# Instalación con Docker Compose

> **Estado:** los archivos están escritos y validados de forma estática (`tests/unit/test_deploy_artifacts.py`):
> - el compose es YAML válido;
> - existen todos los archivos que se copian o se montan;
> - las variables obligatorias están documentadas;
> - las imágenes están fijadas a versiones que existen en el registro;
> - MediaMTX está endurecido;
> - los paneles de Grafana usan métricas que el código publica.
>
> **No se han construido ni ejecutado**: en el equipo de desarrollo la virtualización está desactivada en la BIOS y no hay Docker. Antes de usarlo en producción, hay que hacer una ejecución completa siguiendo esta guía.

## Requisitos

- Docker Engine 24 o posterior con Compose v2 (Linux), o Docker Desktop con WSL2 (Windows, con la virtualización activada).
- GPU (opcional): driver NVIDIA y [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/) en Linux, o Docker Desktop con soporte de GPU en WSL2.
- Los modelos `.onnx` en `ml/model_registry/<modelo>/<versión>/` del equipo anfitrión, o en `SV_MODELS_DIR` (ver el paso 6 de la [guía de Windows](local-windows.md)).

## Pasos

1. Preparar la configuración:

   ```bash
   cp .env.example .env
   uv run svctl gen-secrets --docker
   ```

   Si no hay `uv`, se puede generar cada secreto con `python -c "import secrets; print(secrets.token_urlsafe(32))"`. En ese caso `SV_SECRETS_KEY` debe tener 32 bytes en base64 url-safe.

2. En `.env`, **descomentar la sección de Docker** y completar:
   - `SV_DB_PASSWORD`, `SV_JWT_SECRET`, `SV_SECRETS_KEY`;
   - `SV_MEDIAMTX_API_PASSWORD`, `SV_MEDIAMTX_PUBLISH_PASSWORD`, `SV_MEDIAMTX_AUTH_KEY`;
   - `SV_BOOTSTRAP_ADMIN_EMAIL` y `SV_BOOTSTRAP_ADMIN_PASSWORD`;
   - **`SV_PUBLIC_HOST`**: IP o nombre del equipo tal como lo ven los navegadores. Lo usan WebRTC y CORS;
   - **`SV_BIND_IP`**: `127.0.0.1` para solo este equipo, o la IP de la LAN para servir a la red.

3. Arrancar:

   ```bash
   docker compose up -d --build
   ```

   - con GPU: `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build`;
   - con Prometheus (127.0.0.1:9090) y Grafana (127.0.0.1:3000, panel «Security Vision»): `docker compose --profile monitoring up -d`.

4. Comprobar:

   ```bash
   docker compose ps
   docker compose exec api svctl doctor
   ```

   Abrir `http://<SV_PUBLIC_HOST>:8000`. Después, quitar `SV_BOOTSTRAP_ADMIN_PASSWORD` de `.env` y cambiar la contraseña.

## Qué levanta

| Servicio | Imagen | Función |
|---|---|---|
| `postgres` | `postgres:17.12-bookworm` | Base de datos (volumen `pgdata`) |
| `migrate` | `security-vision-api:local` | `svctl migrate && svctl bootstrap`, y termina |
| `api` | `security-vision-api:local` (destino `api`) | API, web compilada y autorización de MediaMTX. Puerto 8000 |
| `worker` | `security-vision-worker:local` (destino `worker`) | Captura e IA. Modelos montados de solo lectura y evidencias en el volumen `storage`, compartido con la API |
| `mediamtx` | `bluenviron/mediamtx:1.21.3` | WebRTC 8889/tcp + 8189/udp. RTSP y su API solo dentro de la red del compose |
| `prometheus`, `grafana` | `prom/prometheus:v3.5.0`, `grafana/grafana-oss:12.1.0` | Perfil `monitoring`, solo en 127.0.0.1 |

**Imagen** (`docker/app.Dockerfile`):
- etapa `web`: Node 26 compila la web;
- etapa `api`: Python 3.12 y uv 0.13.7, con dependencias congeladas por `uv.lock`;
- etapa `worker`: añade ONNX Runtime GPU, que trae CUDA y cuDNN como paquetes de Python;
- se ejecuta con un usuario sin privilegios (`sv`, uid 10001);
- `.dockerignore` excluye `.env`, `.venv`, los datasets, `var`, los tests y los `.onnx`.

## Cámaras

- **Cámaras IP (RTSP):** MediaMTX las toma directamente y el worker las lee desde MediaMTX.
- **Cámaras USB:** dentro de un contenedor hay que pasar el dispositivo (`devices: ["/dev/video0:/dev/video0"]` en Linux). En Windows con WSL2 no es directo: usar una cámara IP o la instalación nativa.
- **Vídeos de prueba:** se montan en `/data/videos` (`SV_VIDEOS_DIR`).
