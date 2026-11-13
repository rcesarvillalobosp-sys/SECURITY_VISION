# Fase 8: administración, reportes y alertas. Resultados

Fecha: 2026-11-13.

## Entregado

### Administración (web + API)
- **Usuarios y roles:** alta, edición, roles, desactivación (cierra sus sesiones al instante) y restablecimiento de contraseña (cierra sesiones y desbloquea). Nadie puede desactivarse a sí mismo ni quitarse el rol admin. Cada usuario puede cambiar su contraseña en **Mi cuenta**: se exige la actual y se cierran todas sus sesiones.
- **Cámaras:** alta y edición (RTSP, USB, archivo, patrón de prueba), credenciales cifradas que nunca se devuelven, descubrimiento ONVIF y USB, prueba de conexión y perfil por defecto.
- **Editor de zonas** sobre la imagen real de la cámara (último snapshot del worker):
  - dibujar el polígono con clics y cerrarlo en el primer vértice o con Intro;
  - arrastrar vértices, insertar uno desde el punto medio de un lado, doble clic para borrar;
  - perfil exigido por zona.
  - Se explica la regla del **punto de apoyo** (pie de la caja) y la unión de EPP en los solapes.
- **Perfiles EPP:** EPP exigido y los 19 umbrales del motor, con sus valores por defecto y una ayuda. Cada cambio crea una versión nueva; el worker recarga las reglas sin cortar el vídeo.
- **Modelos:**
  - catálogo del registro con arquitectura, clases, **métricas medidas y su conjunto de evaluación**, licencias de código y pesos, y notas;
  - **activación en caliente**: el worker carga el modelo nuevo mientras el anterior sigue analizando y publica lo que tiene cargado de verdad (ADR-0026).
- **Auditoría:** visor filtrable por área y entidad, con el cambio antes → después de cada acción.

### Alertas (ADR-0024)
- **En pantalla:** ya existían (Fase 7). Se movieron arriba a la derecha porque tapaban el botón «Guardar» de los formularios.
- **Webhook:** JSON firmado con HMAC-SHA256, secreto cifrado, protección SSRF y sin seguir redirecciones.
- **Correo** por SMTP propio (STARTTLS, TLS o sin cifrar solo fuera de producción): texto y HTML, enlace al incidente y la **evidencia anotada adjunta**.
- **Filtros por canal:** tipo de incumplimiento y cámaras. Botón «Enviar prueba».
- **Entrega fiable:** cola persistente idempotente por (canal, incidente) y reintentos con espera creciente. Los fallos permanentes no se reintentan solos, pero se pueden reintentar a mano. Historial de entregas en la interfaz.

### Reportes (ADR-0025)
- **Periodos:** diario, semanal (lunes a domingo) y mensual, en la zona horaria del usuario, con filtro por cámara.
- **Vista previa web**, **PDF** (ReportLab) con indicadores, gráficas, tablas, listado de incidentes y metodología, y **Excel** (openpyxl) con 4 hojas, filtros y gráficas nativas.
- **Contenido:** incidentes por estado de revisión (confirmados, descartados = falsos positivos, pendientes), por tipo, por cámara y por día; cumplimiento y **proporción no verificable**.
- **Garantías:** los días sin análisis aparecen vacíos, no como 0 %. Excel protegido contra la inyección de fórmulas. Cada descarga se audita.

## Verificación

- **Backend:** 135 tests (126 anteriores + 9 nuevos), todos en verde contra PostgreSQL real.
  - **Usuarios:** ciclo completo (desactivar → 401 inmediato, política de contraseñas, cambio propio que cierra sesiones) y auditoría sin contraseñas.
  - **Modelos:** catálogo y activación (outbox, auditoría, rechazo de rutas `../`).
  - **Worker con modelos ONNX reales:** cambia de modelo, libera el anterior, infiere con el nuevo y, si un modelo no carga, conserva el actual e informa del error.
  - **Webhook contra un servidor HTTP real:** firma verificada, filtros, idempotencia, 500 → reintento a los 30 s, 400 → fallo definitivo, reintento manual, canal pausado y quitar el secreto.
  - **SSRF:** destino local bloqueado salvo autorización.
  - **Correo contra un servidor SMTP real (aiosmtpd):** destinatarios normalizados, asunto, enlace y evidencia JPEG adjunta.
  - **Reportes:** JSON (totales, cumplimiento, no verificables, desplazamiento de zona horaria, días vacíos), PDF válido, Excel con sus hojas y valores, filtro por cámara, permisos y auditoría. Neutralización de fórmulas en Excel.
  - **Sesiones:** dos pestañas renovando a la vez ya no revocan la sesión; un token robado usado fuera del margen sigue revocándola.
- **Frontend:** `tsc` sin errores y 7 tests vitest (2 nuevos: la renovación sobrevive a un 502 o a la red caída, y no entra en bucle).
- **Prueba real en navegador** con el sistema completo (MediaMTX, API, worker con el modelo EPP en CUDA, un receptor de webhooks y un servidor SMTP locales):
  - cámara de archivo creada desde la UI;
  - zona dibujada sobre la imagen real (arrastre e inserción de vértices); el worker registró «reglas recargadas»;
  - perfil nuevo con un umbral propio;
  - **cambio de modelo en caliente** piloto → COCO → piloto en unos 2 s por carga, sin parar la cámara; los incidentes siguieron confirmándose y hubo 0 errores de inferencia;
  - webhook: 12 envíos (1 de prueba y 11 de incidentes reales), todos con **firma HMAC válida** en el receptor;
  - correo: 4 mensajes reales a 2 destinatarios con la evidencia anotada adjunta (~150 KB) y el enlace al incidente;
  - reporte semanal en pantalla y descargas PDF/Excel desde la UI;
  - 11 páginas sin errores de consola en una pestaña limpia;
  - 375 px sin desbordamiento horizontal.

## Errores encontrados en la prueba real (corregidos)

1. **Una renovación simultánea revocaba la sesión.** Dos renovaciones con la misma cookie se interpretaban como robo de token. Ocurrió con el recargado en caliente de Vite, pero en producción pasaría con **dos pestañas** abiertas. Corrección: bloqueo de fila y margen de gracia de 10 s (ADR-0027), con test de regresión.
2. **Reiniciar la API cerraba la sesión en el navegador.** Un 502 o un error de red al renovar se trataba como «sesión no válida». Ahora se reintenta 3 veces y solo un 4xx cierra la sesión (tests vitest).
3. **Log del worker inundado:** el aviso `ScatterND` de ONNX Runtime CUDA se escribía en cada inferencia, porque la opción de la sesión no afecta al registrador global. Se fija también la severidad global.
4. **No había forma de reenviar una entrega fallida** tras corregir el problema. Se descubrió con un error del servidor SMTP de prueba (el SMTP 5xx es permanente y, correctamente, no se reintenta solo). Se añadió el reintento manual, auditado.
5. Los vértices del editor de zonas salían achatados (el SVG se estiraba sin mantener la proporción): ahora se dibuja en píxeles.
6. La alerta emergente tapaba el botón «Guardar» de los formularios laterales: se movió arriba.
7. Se retiró la opción «zona restringida» de la interfaz: **el motor no la trata de forma distinta** y ofrecerla habría prometido algo que no existe. El campo sigue en la API.

## Limitaciones

- **Reportes programados:** se generan bajo demanda; el envío automático diario o semanal por correo queda pendiente.
- **Al borrar una cámara se pierden sus estadísticas de cumplimiento** (`camera_stats` se borra en cascada). Sus incidentes sí se conservan; en los reportes salen con el cumplimiento «—».
- **El despachador de alertas corre dentro de la API.** Con varias réplicas el reparto es seguro (concesiones), pero cada réplica sondea la base de datos.
- **SSRF:** queda el riesgo residual de re-resolución DNS (*DNS rebinding*) entre la comprobación y la conexión.
- La «confianza» del incidente (proporción de ausencias en la ventana) sale casi siempre a 1.00 con estos vídeos: es poco informativa.
- El listado de los reportes se limita a 2000 incidentes; si se supera, se indica.
- Al cambiar de modelo, un incidente en curso puede quedar registrado con el identificador del modelo nuevo.
- En la prueba en navegador, la creación de usuarios se verificó por API y tests, no con clics en la UI.
