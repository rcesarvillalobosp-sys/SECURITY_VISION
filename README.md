# Security Vision

Plataforma modular de videovigilancia y análisis de seguridad (EPP) mediante IA. Procesamiento local, arquitectura hexagonal y proveedores intercambiables.

- Arquitectura: [docs/architecture/01-arquitectura.md](docs/architecture/01-arquitectura.md)
- Plan por fases: [docs/04-plan-implementacion.md](docs/04-plan-implementacion.md)
- Estado de avance: [docs/progress/](docs/progress/)
- Decisiones (ADR): [docs/decisions/](docs/decisions/)
- Datasets EPP: [docs/datasets/README.md](docs/datasets/README.md)
- Licencias: [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) · [dependencias Python](docs/licenses/python-dependencies.md)

## Puesta en marcha (Windows, sin Docker)

Requisitos: [uv](https://docs.astral.sh/uv/) y los binarios portables de PostgreSQL 17 (EDB). Ver [docs/installation/local-windows.md](docs/installation/local-windows.md).

```bash
uv sync --python 3.12 --extra ml
```

```bash
uv run svctl gen-secrets
```

```bash
uv run python scripts/dev_postgres.py init
```

```bash
uv run svctl migrate
```

```bash
uv run svctl bootstrap
```

```bash
uv run svctl serve
```

La API queda en http://127.0.0.1:8000 (documentación OpenAPI en `/docs`, salvo en producción).

## Con Docker

```bash
docker compose up -d
```

Requiere la virtualización activada en la BIOS y Docker Desktop. El `docker-compose.yml` está escrito, pero **todavía no se ha ejecutado** en este equipo.

## Verificación

```bash
uv run python scripts/check.py
```

Ejecuta ruff, las reglas de arquitectura (import-linter), `alembic check`, los tests (unitarios + integración contra PostgreSQL real) y el inventario de licencias.

## Estructura

```
apps/api/security_vision_api/   raíz de composición de la API (FastAPI)
src/security_vision/core/       dominio, puertos (interfaces), eventos, configuración, registro de proveedores
src/security_vision/modules/    casos de uso (usuarios/RBAC; cámaras, incidentes... en sus fases)
src/security_vision/infrastructure/  adaptadores: PostgreSQL, seguridad, métricas, logging
src/security_vision/plugins/    adaptadores de vídeo, inferencia, modelos y trackers (Fases 2-4)
src/security_vision_ml/         herramientas de datos/ML (fuera del runtime del producto)
ml/datasets/                    manifiestos de fuentes, correcciones (datos crudos fuera de git)
```
