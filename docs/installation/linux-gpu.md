# Instalación nativa en Linux con GPU NVIDIA (servicios systemd)

> **Estado:** guía y unidades escritas para Ubuntu 24.04 / Debian 12 a partir de la instalación verificada en Windows. Los pasos de Python, PostgreSQL y MediaMTX son los mismos. **No se han ejecutado en Linux**: no había un equipo Linux disponible. Validarla en el primer despliegue.
>
> Alternativa más sencilla: [Docker Compose con GPU](docker.md).

## 1. Sistema

```bash
sudo apt install -y postgresql-17 git curl ca-certificates
nvidia-smi
curl -LsSf https://astral.sh/uv/install.sh | sh
```

`nvidia-smi` comprueba el driver: basta con él, porque CUDA y cuDNN llegan como paquetes de Python. La instalación de uv deja el binario en `~/.local/bin`; copiarlo a `/usr/local/bin`.

Instalar Node.js 26 (solo para compilar la web) desde nodejs.org o con el gestor de paquetes de la distribución.

Usuario y carpetas:

```bash
sudo useradd --system --home /var/lib/security-vision --shell /usr/sbin/nologin security-vision
sudo mkdir -p /opt/security-vision /var/lib/security-vision/{storage,mediamtx} /etc/security-vision
sudo chown -R security-vision: /var/lib/security-vision
```

## 2. Base de datos

```bash
sudo -u postgres psql -c "CREATE ROLE security_vision LOGIN PASSWORD '<contraseña>';"
sudo -u postgres psql -c "CREATE DATABASE security_vision OWNER security_vision;"
```

PostgreSQL de la distribución escucha en `127.0.0.1:5432` por defecto.

## 3. Aplicación

```bash
sudo git clone <repositorio> /opt/security-vision && cd /opt/security-vision
sudo uv sync --frozen --no-dev --extra inference --extra otel
sudo npm --prefix apps/web ci
sudo npm --prefix apps/web run build
```

Copiar los modelos `.onnx` a `ml/model_registry/<modelo>/<versión>/`.

Crear `/etc/security-vision/env` (modo 640, grupo `security-vision`) a partir de `.env.example`, con:
- `SV_ENVIRONMENT=production`
- `SV_DATABASE_URL=postgresql+asyncpg://security_vision:<contraseña>@127.0.0.1:5432/security_vision`
- los secretos: `uv run svctl gen-secrets`
- `SV_WEB_DIST=/opt/security-vision/apps/web/dist`
- `SV_STORAGE_DIR=/var/lib/security-vision/storage`
- `SV_MODEL_REGISTRY_DIR=/opt/security-vision/ml/model_registry`
- las variables `SV_MEDIAMTX_*` del paso 4 y `SV_BOOTSTRAP_ADMIN_*` para el primer arranque.

Migrar y crear el administrador inicial (`svx` carga el entorno del servicio y ejecuta como su usuario):

```bash
svx() { sudo -u security-vision bash -c "set -a; . /etc/security-vision/env; set +a; cd /opt/security-vision; $*"; }
svx .venv/bin/svctl migrate
svx .venv/bin/svctl bootstrap
```

Los valores con espacios en `/etc/security-vision/env` van entre comillas (por ejemplo, `SV_SMTP_FROM`).

## 4. MediaMTX

Descargar `mediamtx_v1.21.3_linux_amd64.tar.gz`, verificar su sha256 y extraerlo en `/opt/mediamtx`. Generar la configuración con el mismo script (rutas por variable de entorno):

```bash
sudo SV_MEDIAMTX_HOME=/var/lib/security-vision/mediamtx uv run python scripts/dev_mediamtx.py config --lan --origin https://seguridad.ejemplo.com --host <IP-del-servidor> --public-webrtc-url https://seguridad.ejemplo.com/whep
```

El script escribe las credenciales en `.env`: pasarlas a `/etc/security-vision/env` y borrar ese `.env`.

## 5. Servicios

```bash
sudo cp deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now security-vision-api mediamtx security-vision-worker
svx .venv/bin/svctl doctor
```

Las unidades aplican aislamiento:
- usuario sin privilegios;
- sistema de ficheros de solo lectura salvo `/var/lib/security-vision`;
- `NoNewPrivileges`.

El worker entra además en los grupos `video` (cámaras USB) y `render` (GPU).

## 6. HTTPS

La API escucha en `127.0.0.1:8000`. Delante va un proxy con TLS: [Caddyfile de ejemplo](../../deploy/Caddyfile.example), que obtiene el certificado automáticamente. Hay que abrir 443/tcp y 8189/udp (el vídeo WebRTC).

Logs: `journalctl -u security-vision-worker -f`. Operación: [guía de operación](../operations/README.md).
