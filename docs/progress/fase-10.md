# Fase 10: documentación y despliegue. Resultados

Fecha: 2026-11-13.

## Entregado

### Seguridad del vídeo en directo (ADR-0032)
- **MediaMTX autorizado por la API** (`authMethod: http`, endpoint `/api/v1/media/auth` con clave compartida):
  - el worker publica y lee con su usuario;
  - el navegador lee por WebRTC con el **token de su sesión web** (`Authorization: Bearer` en WHEP), solo rutas de cámaras existentes y con `cameras:read`;
  - cada acceso al vídeo se audita (`media.read_granted`).
  - Esto resuelve lo que quedó pendiente en la Fase 7: ver el vídeo desde otros equipos (`scripts/dev_mediamtx.py config --lan`).
- **Protocolos innecesarios apagados:** MediaMTX 1.21 activa **MoQ por defecto en todas las interfaces** (`:8892`/`:8893`), y nuestra configuración no lo apagaba porque se escribió antes de esa versión. Ahora están apagados de forma explícita MoQ, RTMP, HLS, SRT, métricas, pprof y grabación. Verificado: MediaMTX solo escucha en 127.0.0.1 (RTSP 8554, API 9997, WebRTC 8889, ICE 8189/udp).
- **Certificado y clave privada en git:** MoQ generaba `auto.crt`/`auto.key` en la carpeta de trabajo. Estaban versionados desde la Fase 2:
  - eran autofirmados para localhost y no hay remoto, así que nunca se publicaron;
  - se retiraron de git, se borraron y se añadieron a `.gitignore`;
  - MediaMTX se ejecuta ahora con su propia carpeta como directorio de trabajo.
- `/metrics` de la API solo responde a las redes permitidas (`SV_METRICS_ALLOWED_NETWORKS`): revela nombres de cámaras y actividad.

### Despliegue (ADR-0033)
- **Windows nativo:** [guía](../installation/local-windows.md) reescrita de principio a fin y verificada con una instalación limpia (ver abajo).
- **Docker Compose:**
  - imagen multietapa `docker/app.Dockerfile` (web con Node 26, destinos `api` y `worker`, uv 0.13.7, `uv.lock` congelado, usuario sin privilegios);
  - compose con PostgreSQL 17.12, migración y bootstrap, API, worker (GPU opcional con `docker-compose.gpu.yml`), MediaMTX 1.21.3 con autorización HTTP, y Prometheus y Grafana con un panel aprovisionado;
  - todas las versiones de imagen se comprobaron en el registro;
  - Valkey se retiró: nunca se usó (el bus es PostgreSQL).
- **Linux + GPU:** [guía](../installation/linux-gpu.md), unidades systemd con aislamiento y ejemplo de proxy HTTPS (Caddy).
- **`svctl doctor`:** comprueba la base de datos y las migraciones, los usuarios, el modelo (sha256), la GPU (incluido el estado de energía), el almacenamiento, MediaMTX y los ajustes inseguros. `svctl gen-secrets --docker` genera también los secretos del compose.
- **`.env.example`** reorganizado y completo.

### Operación y API
- [Guía de operación](../operations/README.md):
  - componentes y puertos;
  - monitorización: métricas a vigilar, trazas y logs;
  - capacidad medida;
  - usuarios, cámaras, modelos, incidentes y retención;
  - copias de seguridad, problemas frecuentes, actualizaciones y lista de seguridad para producción.
- **Copias verificables** (`scripts/backup.py`, ADR-0034): `create` (pg_dump + evidencias) y `verify`, que **restaura** en una base desechable y compara filas tabla a tabla.
- **API documentada desde el código:** `scripts/export_openapi.py` genera [openapi.json](../api/openapi.json) y la [tabla de 49 endpoints](../api/endpoints.md) con el **permiso real** de cada ruta, extraído de sus dependencias `require(...)`. El CI falla si quedan desfasados.
- [README](../../README.md) reescrito. La [arquitectura](../architecture/01-arquitectura.md) incluye ahora una tabla «diseño frente a lo implementado».

## Verificación

- **Autorización de MediaMTX con servicios reales** (MediaMTX 1.21.3, API, worker y una cámara H.264 simulada):

  | Caso | Resultado |
  |---|---|
  | El worker lee la cámara a través de MediaMTX con sus credenciales | `streaming` ✅ |
  | WHEP sin token / token falso / sesión cerrada | 401 ✅ |
  | WHEP con el token de la sesión | 201 + `Location`; DELETE 200 ✅ |
  | WHEP con token a una ruta que no es de una cámara | 401 ✅ |
  | RTSP anónimo o con credenciales falsas desde localhost | denegado ✅ |
  | `/media/auth` con clave errónea | 403 ✅ |
  | Puertos de MediaMTX | solo 127.0.0.1, sin MoQ ✅ |

- **Copia de seguridad real:** 0,2 MB de base de datos y 458 evidencias, restaurada en `security_vision_test`. 12 de 13 tablas idénticas. `camera_stats` tenía una fila más en el origen porque el worker siguió escribiendo durante la copia; el script lo señala en lugar de ocultarlo.
- **Tests:** 155 (10 nuevos):
  - autorización de MediaMTX: publicar, leer, API, clave, auditoría y sesión cerrada;
  - `/metrics` según la red de origen;
  - validación estática del despliegue: compose, Dockerfile, `.dockerignore`, MediaMTX endurecido, Prometheus y métricas del panel de Grafana;
  - dependencias declaradas frente a imports reales;
  - secretos con valores de ejemplo rechazados.

  CI local en verde, incluida la documentación de la API al día.

## Errores encontrados (corregidos)

1. **El `docker-compose.yml` no era YAML válido**, y nunca había podido ejecutarse: los mensajes `${VAR:?generar con: ...}` contienen «: ». Lo detectó la validación estática nueva.
2. **El Dockerfile de la Fase 1 no incluía el worker ni la web**, y el compose usaba MediaMTX 1.13 con una configuración de lectura anónima.
3. **MoQ escuchando en todas las interfaces** y su clave privada versionada (ver arriba).
4. **El simulador de cámaras dejó de funcionar con la autorización nueva.** La ruta de la cámara tiraba del propio MediaMTX sin credenciales; ahora las cámaras simuladas llevan credenciales, como una cámara IP real. Es lo correcto: la autorización no debe dejar pasar lecturas anónimas.
5. **El rol de la aplicación no puede crear bases de datos**, así que la primera versión de `backup.py verify` fallaba. Ahora restaura en una base desechable existente, sin necesitar ese privilegio.

## Instalación limpia (criterio de salida de la fase)

Se siguió la [guía de Windows](../installation/local-windows.md) paso a paso en un **clon nuevo del repositorio**, con un clúster de PostgreSQL y una carpeta de MediaMTX nuevos (la instalación de desarrollo, parada).

- Solo se reutilizaron los binarios ya descargados de PostgreSQL y MediaMTX: equivale a extraer los zip del paso 3.
- Los `.onnx` se copiaron, como indica el paso 6.

**Primer intento: aparecieron 3 fallos reales**, que no se habían visto en desarrollo porque ese entorno tenía más cosas instaladas o configuradas:

1. **El worker no arrancaba: `No module named 'scipy'`.** La asociación EPP–persona usa `scipy`, que solo estaba declarado en el extra `train`. En producción, y en la imagen Docker del worker, **no habría funcionado**. Ahora es una dependencia principal, y un test nuevo (`test_dependencies_declared.py`) compara cada import de terceros del producto con las dependencias declaradas.
2. **MediaMTX lo rechazaba todo (`svctl doctor` → error 401).**
   - `.env.example` traía sin comentar los marcadores de Docker, como `SV_MEDIAMTX_AUTH_KEY=<solo docker-compose>`.
   - `dev_mediamtx.py config` reutilizaba ese valor como clave real, y su espacio rompía la URL de autorización.
   - Correcciones:
     - las variables de Docker van comentadas;
     - los scripts ignoran los valores `<...>` y la clave va codificada en la URL;
     - la configuración **rechaza cualquier secreto que siga con el valor de ejemplo**.
3. **`test_inference.py` se saltaba** sin el extra `train` (le faltaba `onnx`): ahora `onnx` está en el grupo de desarrollo.

`svctl doctor` cumplió su función: detectó el error de MediaMTX en el primer intento, con un mensaje que apuntaba a la causa.

**Segundo intento, desde cero con las correcciones** (commits `e974e45` y `154be93`):

| Paso de la guía | Resultado |
|---|---|
| 1–2 `uv sync`, `npm ci`, `npm run build` | ✅ |
| 4 `.env` desde `.env.example` + `gen-secrets` | ✅ |
| 5 `dev_postgres.py init` (otra carpeta de datos), `migrate`, `bootstrap` | ✅ administrador y perfil por defecto creados |
| 7 `dev_mediamtx.py config` | ✅ modo `http` |
| 8 API + MediaMTX + worker; `svctl doctor` | ✅ 0 errores (solo avisos esperados: entorno de desarrollo, contraseña inicial en `.env`) |
| Web servida por la API, login, alta de una cámara RTSP H.264 desde la UI | ✅ |
| Monitor: vídeo **WebRTC 1920×1080 autorizado con el token de la sesión** | ✅ primera imagen en 1,8 s; superposición en vivo con 3 personas |
| Análisis | ✅ cámara `streaming`, 109 fotogramas analizados, 0 errores de inferencia |
| Auditoría | ✅ `media.read_granted`, `camera.created`, `auth.login`… |
| «Mi cuenta» › cambiar la contraseña | ✅ cierra la sesión; la contraseña antigua se rechaza y la nueva entra |
| Quitar `SV_BOOTSTRAP_ADMIN_PASSWORD` → `svctl doctor` | ✅ desaparece el aviso |
| «Verificación del desarrollo» (`check.py`) en la copia limpia | ✅ **155 tests pasados, 0 saltados**; ruff, arquitectura, `alembic check`, licencias, API al día y web |

## Limitaciones

- **Docker y Linux:** no se han podido ejecutar en este equipo (virtualización desactivada en la BIOS, sin Linux). Están validados de forma estática; la primera ejecución real debe seguir las guías.
- **HTTPS:** se documenta con un ejemplo de Caddy, sin probar. Sin HTTPS, las contraseñas viajan en claro por la red local.
- **Dependencia de la API:** con la autorización HTTP, las conexiones nuevas a MediaMTX necesitan la API en marcha (las ya abiertas continúan).
- Siguen pendientes de fases anteriores: TensorRT sin medir, evaluación del modelo EPP con imágenes reales del despliegue, corrección `no_boots_relabel_v1` en CVAT y verificación manual de la licencia de Roboflow.
