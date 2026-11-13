# Security Vision

Plataforma modular de videovigilancia con IA para supervisar el uso de **equipos de protección individual (EPP)**: casco, chaleco, botas, guantes y gafas. Procesa todo en local, sin reconocimiento facial ni biometría, con una arquitectura hexagonal y proveedores intercambiables (fuente de vídeo, motor de inferencia, modelo, tracker).

**Funcionalidad:**
- cámaras RTSP/IP, USB y archivos de vídeo;
- detección de personas y EPP (RT-DETRv2, ONNX Runtime en CUDA/CPU u OpenVINO);
- tracking (ByteTrack) y asociación del EPP a cada persona;
- motor de reglas que **nunca confirma un incumplimiento con un solo fotograma**, distingue «no verificable» de «incumplimiento» y admite zonas y perfiles por cámara;
- incidentes con evidencia firmada y revisión humana;
- panel y monitoreo multicámara con vídeo WebRTC y superposición en vivo;
- administración (usuarios y roles, cámaras, editor de zonas, perfiles, modelos con cambio en caliente) y auditoría de solo inserción;
- alertas por webhook firmado y correo, y reportes en PDF y Excel;
- métricas Prometheus, trazas OpenTelemetry y pruebas de carga.

## Documentación

| | |
|---|---|
| **Instalación** | [Windows nativo](docs/installation/local-windows.md) (verificada con una instalación limpia) · [Docker Compose](docs/installation/docker.md) · [Linux + GPU (systemd)](docs/installation/linux-gpu.md) |
| **Operación** | [Guía de operación](docs/operations/README.md): monitorización, capacidad, copias de seguridad, problemas frecuentes, actualizaciones y lista de seguridad |
| **API** | [Endpoints y permisos](docs/api/endpoints.md) · [OpenAPI](docs/api/openapi.json) |
| **Arquitectura** | [Arquitectura](docs/architecture/01-arquitectura.md) · [Modelo de datos](docs/architecture/02-modelo-datos.md) · [Interfaces y adaptadores](docs/architecture/03-interfaces-adaptadores.md) · [Decisiones (ADR)](docs/decisions/README.md) |
| **IA** | [Modelos](docs/models/README.md) · [Datasets y auditoría](docs/datasets/README.md) |
| **Avance** | [Plan por fases](docs/04-plan-implementacion.md) · [Informes de cada fase](docs/progress/) · [Análisis del entorno](docs/00-analisis-entorno.md) |
| **Licencias** | [Terceros](THIRD_PARTY_LICENSES.md) · [Dependencias Python](docs/licenses/python-dependencies.md) · [Dependencias web](docs/licenses/web-dependencies.md) |

## Inicio rápido (Windows, desarrollo)

Resumen de la [guía completa](docs/installation/local-windows.md), que también explica cómo conseguir los binarios de PostgreSQL y MediaMTX y los modelos.

```bash
uv sync --python 3.12 --extra inference --extra otel
npm --prefix apps/web ci && npm --prefix apps/web run build
copy .env.example .env
uv run svctl gen-secrets
uv run python scripts/dev_postgres.py init
uv run svctl migrate && uv run svctl bootstrap
uv run python scripts/dev_mediamtx.py config
```

Después, `gen-secrets` imprime los secretos que hay que pegar en `.env` junto con `SV_WEB_DIST=apps/web/dist` y el administrador inicial. Arranque, cada uno en su terminal:

```bash
uv run svctl serve
uv run python scripts/dev_mediamtx.py run
uv run sv-worker
```

Comprobación:

```bash
uv run svctl doctor
```

Web en http://127.0.0.1:8000.

## Verificación

```bash
uv run python scripts/check.py
```

Ejecuta ruff, las reglas de arquitectura (import-linter), `alembic check`, los tests (unitarios e integración contra PostgreSQL real), el inventario de licencias, la documentación de la API al día y los tipos, tests y licencias de la web.

## Estructura

```
apps/api/security_vision_api/              API (FastAPI): composición, routers, svctl, doctor
apps/processing-worker/security_vision_worker/  worker: captura, análisis, evidencias, métricas
apps/web/                                  frontend (React, TypeScript, Vite, Tailwind)
src/security_vision/core/                  dominio, puertos, eventos, configuración (sin frameworks)
src/security_vision/modules/               casos de uso (usuarios, cámaras, reglas, incidentes, alertas, reportes...)
src/security_vision/infrastructure/        adaptadores: PostgreSQL, MediaMTX, seguridad, almacenamiento, alertas, reportes
src/security_vision/plugins/               vídeo (PyAV), inferencia (ONNX Runtime, OpenVINO), modelos DETR, ByteTrack
src/security_vision_ml/                    herramientas de datos y ML (fuera del runtime del producto)
ml/                                        registro de modelos, exportación, entrenamiento, evaluación
scripts/                                   PostgreSQL/MediaMTX locales, copias de seguridad, pruebas de carga, CI
docker/, docker-compose*.yml, deploy/      despliegue (Docker, systemd, proxy HTTPS)
```

## Estado

Las 10 fases del plan están completas. Lo pendiente y sus motivos están en el [informe de la Fase 10](docs/progress/fase-10.md):
- validar Docker y Linux en un equipo que los tenga;
- medir TensorRT;
- evaluar el modelo EPP con imágenes reales del lugar de despliegue;
- corrección de datos `no_boots_relabel_v1`.
