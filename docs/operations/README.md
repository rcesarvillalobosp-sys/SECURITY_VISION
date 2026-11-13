# Guía de operación

Para quien opera la plataforma en el día a día. Instalación: [Windows](../installation/local-windows.md) · [Docker](../installation/docker.md) · [Linux + GPU](../installation/linux-gpu.md).

## 1. Componentes y puertos

| Proceso | Función | Puerto (por defecto) | Expuesto |
|---|---|---|---|
| PostgreSQL 17 | Datos, auditoría, bus de eventos (LISTEN/NOTIFY), outbox | 5433 | Solo local |
| API (`svctl serve` / uvicorn) | REST, WebSocket en vivo, web compilada, alertas, autorización de MediaMTX | 8000 | Sí (detrás de HTTPS) |
| Worker (`sv-worker`) | Captura, detección, tracking, reglas, evidencias | 9101 (métricas) | Solo local |
| MediaMTX | Vídeo en directo: RTSP para el worker y WebRTC para la web | 8554 (RTSP), 9997 (API), 8889 + 8189/udp (WebRTC) | Solo WebRTC |

**Orden de arranque:** PostgreSQL → API → MediaMTX → worker.
- MediaMTX consulta a la API para autorizar cada conexión.
- Si la API cae, las conexiones ya abiertas siguen funcionando; las nuevas se rechazan hasta que vuelva, y el worker reintenta.

**Comprobación rápida:**

```bash
uv run svctl doctor
```

Comprueba la base de datos, las migraciones, los usuarios, el modelo (sha256), la GPU, el almacenamiento, MediaMTX y los ajustes inseguros.

## 2. Salud y monitorización

- `GET /health/live` (proceso vivo) y `GET /health/ready` (base de datos accesible).
- **Métricas Prometheus:**
  - API: `http://<host>:8000/metrics`, solo desde las redes de `SV_METRICS_ALLOWED_NETWORKS`;
  - worker: `http://127.0.0.1:9101/metrics`.
- Con Docker: `docker compose --profile monitoring up -d` levanta Prometheus y Grafana con el panel «Security Vision» ya cargado.

| Métrica | Qué vigilar |
|---|---|
| `sv_camera_up{camera}` | 0 = cámara sin vídeo. Alerta si dura más de 1 min |
| `rate(sv_analysis_frames_total[1m])` | Análisis por segundo de cada cámara: debe acercarse a su `analysis_fps` |
| `sv_stage_ms{stage="end_to_end"}` | Retraso entre la captura y el resultado. Si crece, el equipo está saturado |
| `sv_stage_ms{stage="detect_wait"}` | Cola de la GPU: si sube, hay demasiadas cámaras o demasiados fps de análisis |
| `sv_gpu_pstate`, `sv_gpu_throttle_active` | GPU limitada por energía o temperatura (portátiles): ver §8 |
| `sv_inference_errors_total`, `sv_incident_errors_total` | Deben ser 0 |
| `sv_violations_confirmed_total` | Incumplimientos confirmados por EPP |
| `sv_http_requests_total{status=~"5.."}` | Errores de la API |

**Trazas (opcional):**
- `SV_OTEL_ENDPOINT=http://<colector>:4318`, con muestreo `SV_OTEL_SAMPLE_RATIO`.
- Spans:
  - por fotograma: `analysis.frame` → `detect` / `analyze` / `evidence_and_events`;
  - por petición HTTP de la API.

**Logs:**
- en JSON con `SV_LOG_JSON=true`;
- cada petición lleva su `X-Request-ID`;
- los incidentes se registran como `incumplimiento confirmado` / `incidente registrado`.

## 3. Capacidad y dimensionamiento

Medido en la Fase 9 ([informe](../progress/fase-9.md)) con una GTX 1650 de portátil **limitada por energía**:
- unos 5,5–6 análisis por segundo en total;
- configuraciones verificadas: 2 cámaras a 2 fps, 5 a 1 fps y 8 a 0,6 fps, con una latencia p95 de 0,3–1,1 s.

Las reglas exigen ausencia sostenida (varios segundos), así que **0,6–1 fps de análisis por cámara basta** para confirmar incumplimientos.

Ajustes:
- `analysis_fps` de cada cámara;
- `SV_DETECTION_MAX_BATCH`: lote de inferencia, 4 por defecto;
- `decode_threads` en las opciones de la fuente (0 = automático, para 4K).

Con H.264, MediaMTX consumió el 76–114 % de un núcleo para 8 cámaras a 4 Mbit/s.

## 4. Usuarios y accesos

- **Alta, roles y desactivación:** web › Administración › Usuarios.
  - Desactivar a alguien o cambiar sus roles cierra sus sesiones al momento.
  - Roles: `admin`, `supervisor`, `operator` (monitoreo y revisión), `viewer` (solo lectura).
- **Contraseñas:** mínimo 12 caracteres y 3 tipos.
  - Tras 5 intentos fallidos, la cuenta se bloquea 15 minutos.
  - Cada persona cambia la suya en «Mi cuenta», y eso cierra todas sus sesiones.
- **Primer administrador:** sale de `SV_BOOTSTRAP_ADMIN_*` en el primer `svctl bootstrap`. Después, **quitar esas variables** y cambiar la contraseña (`svctl doctor` avisa).
- **Auditoría:** web › Administración › Auditoría.
  - Es de solo inserción: la base de datos impide modificarla.
  - Registra inicios de sesión, cambios de configuración, revisiones de incidentes, accesos a evidencias, accesos al vídeo en directo (`media.read_granted`), activaciones de modelos y reportes generados.

## 5. Cámaras, zonas, reglas y modelos

- **Cámaras:** web › Administración › Cámaras y zonas.
  - Las credenciales RTSP se guardan cifradas (AES-GCM) y nunca se muestran.
  - «Probar conexión» comprueba la cámara sin afectar al worker.
- **Zonas:** se dibujan sobre la imagen real. Una persona está en la zona si su punto de apoyo (el pie de la caja) cae dentro.
- **Perfiles EPP:** qué EPP se exige y con qué umbrales.
  - Cada cambio crea una versión, y el worker la recarga sin cortar el vídeo.
  - Los incidentes guardan la versión con la que se confirmaron.
- **Modelos:** web › Administración › Modelos.
  - Al activar un modelo, el worker lo carga en caliente (unos 2 s).
  - La página distingue el modelo «activo» (el pedido) del modelo «en uso» (lo que el worker tiene cargado). Si la carga falla, se conserva el anterior.
- **Añadir un modelo:**
  1. exportarlo a ONNX (`ml/export/`);
  2. crear `ml/model_registry/<nombre>/<versión>/model.yaml` con su sha256, licencias y métricas medidas;
  3. copiar el `.onnx`.
  - El registro comprueba la integridad con el sha256 al cargar.

## 6. Incidentes, evidencias y retención

- Un incidente es una **confirmación del motor de reglas**, no un fotograma suelto, y queda PENDIENTE de revisión humana.
- Flujo: PENDIENTE → EN_REVISION → CONFIRMADO / DESCARTADO → RESUELTO. Descartar o resolver exige una nota.
- **Evidencias** (contexto, fotograma, anotada, recorte):
  - se sirven con URL firmada de 5 minutos, ligada a la persona que la pide;
  - cada acceso se audita;
  - el sha256 se verifica al servirla: una evidencia alterada no se entrega.
- **Retención:**
  - evidencias `SV_RETENTION_EVIDENCES_DAYS` (90 días) e historial de conectividad 30 días;
  - el worker purga una vez al día; a mano: `uv run svctl purge`;
  - los metadatos del incidente se conservan, solo se borran las imágenes.

## 7. Copias de seguridad

```bash
uv run python scripts/backup.py create --out D:/backups
```

Genera `pg_dump -Fc` de la base de datos más un zip con las evidencias (`SV_STORAGE_DIR`).

**Verificar una copia** (la única forma de saber que sirve):

```bash
uv run python scripts/backup.py verify --dump D:/backups/sv-<fecha>.dump --scratch-db security_vision_test
```

Restaura en una base desechable, que se sobrescribe, y compara las filas tabla a tabla. Lo comprobé con datos reales en la Fase 10: 13 tablas idénticas, salvo las estadísticas que el worker siguió escribiendo durante la copia.

**Restaurar:**
1. parar la API y el worker;
2. `uv run python scripts/backup.py restore --dump <archivo> --target-db security_vision`;
3. descomprimir las evidencias en `SV_STORAGE_DIR`;
4. `svctl migrate`, si el código es más nuevo que la copia.

**Con Docker:**

```bash
docker compose exec postgres pg_dump -U security_vision -Fc security_vision > sv.dump
```

y el volumen `storage`.

Guarda también **`.env`**: sin `SV_SECRETS_KEY` no se pueden descifrar las credenciales de las cámaras.

## 8. Problemas frecuentes

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| Cámara en `reconnecting` | Cámara inaccesible, credenciales o URL | «Probar conexión» y `last_error` en la lista de cámaras |
| Cámara en `reconnecting` y MediaMTX registra `401` en la fuente | La ruta tira de un RTSP que exige credenciales que la cámara no tiene configuradas | Completar el usuario y la contraseña de la cámara |
| La web muestra «Snapshot» en vez de «WebRTC» | MediaMTX caído, puerto 8889/8189 bloqueado u origen no permitido | `svctl doctor`; con `--lan`, revisar `--origin` y `--host` en `scripts/dev_mediamtx.py config` |
| Inferencia lenta (más de 150 ms en una GTX 1650) | GPU en P5 por energía o temperatura | Plan de energía «Máximo rendimiento», «preferir rendimiento máximo» en el panel de NVIDIA y ventilación. Ver `sv_gpu_pstate` |
| `detect_wait` creciente | Más análisis por segundo de los que da la GPU | Bajar `analysis_fps` o repartir cámaras entre workers |
| Muchas personas «no verificables» | Personas pequeñas, cortadas u ocluidas | Acercar o reorientar la cámara. `min_person_height_px` en el perfil |
| No llegan alertas por correo | SMTP mal configurado | Administración › Alertas › «Enviar prueba» y el historial de entregas. Reintentar a mano tras corregirlo |
| La web se queda en el login tras reiniciar la API | Se pidió la página justo mientras la API arrancaba | La web reintenta la renovación 3 veces; si no, recargar |
| `uv sync` falla en Windows con «archivo en uso» | La API o el worker siguen en marcha | Pararlos antes de actualizar |

## 9. Actualizaciones

1. Copia de seguridad (§7).
2. Parar el worker y la API (en Windows, imprescindible para que `uv sync` pueda reemplazar los ejecutables).
3. `git pull`
4. `uv sync --extra inference --extra otel`
5. `npm --prefix apps/web ci && npm --prefix apps/web run build`
6. `uv run svctl migrate`
7. `uv run svctl bootstrap` (sincroniza permisos nuevos; es idempotente)
8. Arrancar en el orden de §1.
9. `uv run svctl doctor`

## 10. Seguridad en producción (lista de comprobación)

- [ ] `SV_ENVIRONMENT=production`: rechaza secretos de ejemplo, CORS `*`, fuentes de prueba y SMTP sin cifrar.
- [ ] HTTPS delante de la API y de WHEP ([ejemplo con Caddy](../../deploy/Caddyfile.example)): el login envía contraseñas.
- [ ] MediaMTX en modo `http` (por defecto): el vídeo solo se ve con sesión y permiso `cameras:read`, y queda auditado. MoQ, RTMP, HLS y SRT apagados.
- [ ] Puertos expuestos: solo 443 (o 8000 en la LAN) y 8889 + 8189/udp. PostgreSQL, la API de MediaMTX, RTSP y las métricas del worker, solo locales.
- [ ] `SV_BOOTSTRAP_ADMIN_PASSWORD` quitado de `.env` y contraseña del administrador cambiada.
- [ ] `SV_ALERT_WEBHOOK_ALLOW_PRIVATE=false`, salvo receptores en la LAN.
- [ ] Copias de `.env` y de la base de datos fuera del equipo, cifradas.
- [ ] Aviso de videovigilancia y base legal del tratamiento (imágenes de personas). No hay reconocimiento facial ni biometría.
