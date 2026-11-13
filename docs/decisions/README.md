# Registro de decisiones de arquitectura (ADR)

Formato breve: contexto → decisión → consecuencias. Estado: **Aceptada** salvo indicación.

## ADR-0001 Arquitectura hexagonal en un paquete único verificado por import-linter
- **Contexto:** hay que poder cambiar cámaras, motores de inferencia, modelos y almacenamiento sin reescribir el sistema.
- **Decisión:** `core` contiene el dominio y los puertos; `modules` contiene los casos de uso y solo depende de `core`; `infrastructure` y `plugins` contienen los adaptadores; `apps/*` son las raíces de composición. Seis contratos de import-linter lo hacen cumplir en CI (por ejemplo, el núcleo no puede importar FastAPI, SQLAlchemy ni ONNX Runtime, y el dominio no puede importar numpy).
- **Consecuencias:** cada repositorio tiene su puerto y su implementación SQL, lo que añade algo de código repetitivo. A cambio, el dominio se puede probar sin base de datos.

## ADR-0002 Overlay de detecciones en el cliente
- **Decisión:** el vídeo llega al navegador por WebRTC desde MediaMTX y las detecciones viajan aparte por WebSocket; se dibujan en un `<canvas>` superpuesto. El vídeo anotado no se re-codifica.
- **Consecuencias:** se ahorra mucha CPU/GPU. En directo, la sincronización entre vídeo y recuadros es aproximada; en la evidencia de un incidente es exacta.

## ADR-0003 PyAV/FFmpeg en Windows y GStreamer en Linux
- **Contexto:** los enlaces de GStreamer para Python (PyGObject) son frágiles en Windows nativo.
- **Decisión:** dos adaptadores detrás del puerto `VideoSource`, elegidos por configuración.

## ADR-0004 Valkey en lugar de Redis
- **Contexto:** Redis ≥ 7.4 cambió a RSALv2/SSPL (y AGPL desde la versión 8).
- **Decisión:** Valkey (BSD-3), compatible a nivel de protocolo.

## ADR-0005 Exclusiones de licencia
- **Decisión:** no se usa Ultralytics (AGPL-3.0) ni las variantes de RF-DETR con licencia PML. Datasets: solo se usan los que tienen uso comercial verificado en su manifiesto (ver `ml/datasets/sources/`).

## ADR-0006 Cumplimiento con verificabilidad explícita
- **Decisión:** cada EPP se observa como presente, ausente o no verificable. Un incumplimiento solo se confirma cuando la ausencia es sostenida, con un mínimo de observaciones verificables y con histéresis. La semántica de cada clase está en `CLASS_DEFINITIONS`; por ejemplo, `safety_boot` no certifica protección.

## ADR-0007 Sesiones: JWT de acceso corto + refresh rotativo en cookie httpOnly
- **Decisión:**
  - El JWT HS256 dura 15 minutos y lleva permisos.
  - En cada petición se comprueba que la sesión no esté revocada, así un logout o un cambio de roles surte efecto de inmediato.
  - El refresh token es opaco (`<session_id>.<secreto>`) y en la base de datos solo se guarda su SHA-256. Rota en cada uso; si se reutiliza uno ya rotado, se revoca la sesión entera.
  - Viaja únicamente en una cookie `HttpOnly; SameSite=Strict`, con `Secure` en producción.
- **Consecuencias:** cada petición autenticada hace una consulta a la tabla `sessions`; se puede cachear en Valkey si hiciera falta.

## ADR-0008 PostgreSQL portable para desarrollo sin Docker
- **Contexto:** la virtualización está desactivada en este equipo y no hay permisos de administrador garantizados.
- **Decisión:** usar los binarios zip oficiales de EDB, con el clúster en el espacio del usuario, gestionado por `scripts/dev_postgres.py`. Docker Compose queda como vía estándar en cuanto Docker esté disponible.

## ADR-0009 Auditoría de solo inserción reforzada en la base de datos
- **Decisión:** un trigger en PostgreSQL rechaza cualquier UPDATE o DELETE sobre `audit_log`. La única excepción es anonimizar al actor cuando se borra su usuario (`SET NULL`).
