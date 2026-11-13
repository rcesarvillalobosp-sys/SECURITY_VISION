# Fase 6: registro de incidentes y evidencias. Resultados

Fecha: 2026-11-13.

## Flujo (requisito 8)

1. **Registrar el evento.** El motor de reglas confirma un incumplimiento en el worker.
2. **Capturar la evidencia.** Se toma del búfer de contexto del worker (un fotograma por segundo de los últimos ~12 s):
   - `context`: el inicio del periodo de ausencia y el punto medio;
   - `frame`: el fotograma exacto de la confirmación, sin alterar (JPEG q92);
   - `annotated`: la persona y su EPP marcados;
   - `crop`: recorte ampliado de la persona.
3. **Guardar los metadatos.** Una única transacción PostgreSQL incluye el incidente, las evidencias (clave, sha256, tamaño, fotograma), las **detecciones de esos fotogramas** con todos los campos del requisito 4 (cámara, ID temporal, clase, caja, confianza, fecha, fotograma, modelo y tiempo de inferencia), el historial y un evento en el **outbox**. El registro es **idempotente**: el identificador se deriva de la confirmación, así que los reintentos no duplican.
4. **Generar la alerta y actualizar el dashboard.** El relé del outbox (en la API y en el worker, con `SKIP LOCKED`) publica `incident.confirmed.v1` con entrega "al menos una vez". Los canales de alerta llegan en la Fase 8 y el dashboard en la Fase 7.
5. **Revisión humana.** El incidente pasa por PENDIENTE → EN_REVISION → CONFIRMADO o DESCARTADO → RESUELTO, solo por transiciones válidas. Descartar o resolver **exige una nota**. Hay comentarios e historial completo con el autor de cada cambio, y todo queda en la auditoría.
6. **Fin de la situación.** Cuando el motor deja de ver el incumplimiento (`corrected` o `track_lost`) se anota `ended_at`, sin tocar el estado de revisión.

## Protección de las evidencias

- Los archivos están fuera de la base de datos (`LocalFileStorage`, intercambiable por S3) y nunca se sirven directamente.
- Se accede solo con **URL firmada por HMAC, ligada al usuario que la pidió y válida 5 minutos**. Cada acceso queda auditado (`evidence.viewed`) con la identidad del usuario.
- **Integridad:** se comprueba el sha256 en cada lectura. Una evidencia alterada devuelve 409 y queda auditada (`evidence.integrity_failed`).
- **Retención:** `svctl purge` y la tarea diaria del worker borran los archivos de evidencia con más de `SV_RETENTION_EVIDENCES_DAYS` días (90 por defecto), pero conservan los metadatos del incidente. También borran el historial de conectividad antiguo y los archivos huérfanos (más de 24 h sin fila en la BD).

## API

- `GET /api/v1/incidents`: filtros por estado, cámara, tipo y rango de fechas, con paginación.
- `GET /api/v1/incidents/{id}`: evidencias con URL firmada, detecciones, historial y comentarios.
- `PATCH /api/v1/incidents/{id}/status` y `POST /api/v1/incidents/{id}/comments`: requieren `incidents:review` (operador, supervisor o administrador; el rol de lectura no puede).
- `GET /api/v1/files/{clave}?exp&u&sig`.

## Verificación

- **Integración** (PostgreSQL real), 5 tests:
  - registro idempotente y transaccional, con un único evento en el outbox pese al reintento;
  - el relé vacía el outbox;
  - flujo de revisión completo: transición inválida rechazada, nota obligatoria, historial y comentarios;
  - URL firmada correcta, URL manipulada → 403, URL de otro usuario → 403, archivo alterado en disco → 409, con auditoría;
  - RBAC;
  - retención: purga de evidencias antiguas y de huérfanos, conservando los metadatos;
  - **extremo a extremo**: cámara del worker real + detector simulado + reglas → **un** incidente (no uno por fotograma) con JPEG real en disco y detecciones en la BD.
- **Unidad**, 4 tests: constructor de evidencias (contexto, fotograma, anotada y recorte, con los IDs de track correctos), transiciones e identificador determinista.
- **Prueba en vivo** (modelo EPP real, perfil "EPP básico", vídeo de test):
  - incidente de casco correcto: la trabajadora sin casco, `no_helmet` 0.77;
  - 5 evidencias, 70 detecciones persistidas e historial creado → finalizado (`track_lost`).

## Hallazgo importante (y corrección)

Al revisar visualmente un incidente de **chaleco** que también apareció en la Fase 5, resultó ser un **falso positivo**: una figura lejana de unos 35 px con un `no_vest` de 0.46. La causa estaba en `PPERule.observe`: **la evidencia explícita `no_*` se aceptaba antes de comprobar si la persona era verificable**.

- **Corrección:** la verificabilidad (tamaño, confianza, bordes, oclusión) se comprueba primero, y si falla, ninguna detección cuenta.
- **Tests de regresión:** persona diminuta con `no_vest` sostenido → nunca confirmado; región ocluida con `no_vest` → no verificable.
- Los dos incidentes falsos se **descartaron por el flujo de revisión**, con nota justificativa.
- Tras la corrección, una vuelta completa al vídeo produce **1 incidente, el real**.

Este fallo sí afectaba a la Fase 5: su prueba en vivo informó de una confirmación de chaleco que era este falso positivo.

## Limitaciones

- La `confidence` del incidente es la **cuota de ausencia ponderada en la ventana**, no una probabilidad calibrada. Un 1.0 significa que ninguna observación verificable mostró el EPP.
- El búfer de contexto guarda fotogramas completos: unos 6 MB por fotograma en 1080p y 12 por cámara (≈72 MB). Se optimizará en la Fase 9.
- No hay clips de vídeo: la evidencia son imágenes fijas. Los clips requieren grabación continua (Fase 9+).
- Los rostros aparecen en la evidencia (datos personales). El difuminado opcional queda pendiente; ahora el acceso está restringido, firmado y auditado.
