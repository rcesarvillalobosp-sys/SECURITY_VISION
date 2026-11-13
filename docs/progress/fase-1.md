# Fase 1: infraestructura y arquitectura base. Resultados

Fecha: 2026-11-12.

## Entregado

| Área | Contenido |
|---|---|
| Núcleo | Dominio en Python puro (geometría, detecciones/tracks, vocabulario de cumplimiento, identidad/RBAC, errores, UUIDv7, taxonomía con definiciones). Puertos: `VideoSource`, `InferenceEngine`, `DetectionModel`, `ObjectTracker`, `PPEAssociator`, `SecurityEvaluator`, `AnalysisPipeline`, `ObjectStorage`, `MessageBus`, `AlertChannel`, seguridad y repositorios. Eventos versionados. `ProviderRegistry` con descubrimiento por entry points. Configuración `SV_*` con salvaguardas para producción. |
| Base de datos | Modelo SQLAlchemy 2 + migración Alembic: usuarios, roles, permisos, sesiones, auditoría (con trigger de solo inserción), sitios, cámaras (CHECK que impide credenciales en la URI), zonas, perfiles de seguridad, modelos de IA y retención. |
| Seguridad | Argon2id, JWT de acceso de 15 min con verificación de sesión activa, refresh rotativo con detección de reutilización (cookie httpOnly), bloqueo tras intentos fallidos, mensajes genéricos que no permiten saber si un usuario existe, política de contraseñas, AES-256-GCM para secretos, logs con credenciales enmascaradas, cabeceras de seguridad y CORS restringido. |
| API | `/health/live`, `/health/ready`, `/metrics` (Prometheus), `/api/v1/auth/{login,refresh,logout,me}`, `/api/v1/users` (listar, crear, ver, cambiar roles) y `/api/v1/roles`. |
| Operación | `svctl` (migrate, bootstrap, serve, gen-secrets), `scripts/dev_postgres.py`, `scripts/check.py` (CI local), workflow de CI, pre-commit, Dockerfile y `docker-compose.yml` (postgres, api, valkey, mediamtx, prometheus, grafana). |

## Verificación (resultados reales en este equipo)

- `scripts/check.py`: **OK**.
  - ruff sin hallazgos.
  - import-linter: 6 contratos cumplidos, 0 rotos.
  - `alembic check`: sin diferencias entre el modelo y las migraciones.
  - 38 tests en verde: datasets, núcleo y 9 de integración contra **PostgreSQL 17.12 real**.
  - Licencias: 48 paquetes, ninguno copyleft fuerte ni de licencia desconocida.
- Las migraciones se probaron también hacia abajo: `alembic downgrade base` seguido de `upgrade head`.
- Prueba de humo con el servidor real (`svctl serve`): ready OK, login 200 con cookie HttpOnly, `/me` con 14 permisos de admin, refresh 200, métricas `sv_auth_logins_total{outcome="success"}`.

## No verificado o pendiente (con motivo)

- **Docker Compose y Dockerfile no se han ejecutado:** Docker no está instalado y la virtualización está desactivada. Las versiones de las imágenes están fijadas, pero aún no se han descargado.
- **Workflow de CI de GitHub:** no hay repositorio remoto, así que nunca se ha ejecutado.
- **Métricas de CPU, RAM y GPU:** se añaden en la Fase 9 (psutil/pynvml). Ahora solo hay uptime y métricas HTTP.
- **Frontend:** no hay pantalla de login todavía (Fase 7). La API ya ofrece lo necesario.
- **Ningún adaptador de vídeo ni de inferencia implementado:** solo sus puertos (Fases 2 y 3).
