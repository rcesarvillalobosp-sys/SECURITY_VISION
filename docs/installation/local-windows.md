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
