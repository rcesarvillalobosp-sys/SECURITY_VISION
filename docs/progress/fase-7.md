# Fase 7: dashboard y monitoreo multicámara. Resultados

Fecha: 2026-11-13.

## Entregado

### Backend
- **Datos en vivo:** el worker publica en cada fotograma analizado un resumen compacto (cajas normalizadas, ID temporal, estado de cada persona, EPP con su asociación) en el canal `sv_live` de PostgreSQL. Es efímero, sin outbox: perder un fotograma no importa.
- **Hub en vivo en la API** (`LiveHub`): reparte por **WebSocket** `/api/v1/ws` los fotogramas de las cámaras suscritas y los eventos (incidente confirmado o actualizado, estado de cámara, cambio de cumplimiento), filtrados por permiso.
  - Autenticación en el **primer mensaje**, nunca con el token en la URL.
  - Renovación del token sin reconectar; cierre (4401) si caduca sin renovarse.
  - **Control de `Origin`**, contra el secuestro de WebSocket entre sitios.
  - Los clientes lentos pierden mensajes en lugar de bloquear a los demás.
- **Estadísticas** `camera_stats` por cámara y minuto (fotogramas-persona por estado), escritas por el worker cada 30 s de forma aditiva.
- `GET /api/v1/dashboard/summary`: cámaras activas o desconectadas, personas ahora, incidentes de hoy y pendientes, cumplimiento de hoy. El "hoy" respeta la zona horaria del navegador.
- `GET /api/v1/dashboard/series?range=24h|7d|30d`: cumplimiento y ocupación por hora o día, e incidentes por día y tipo.
- **Cumplimiento** = conformes / (conformes + posibles + confirmados). Los no verificables y los que están en revisión **no cuentan** ni a favor ni en contra.
- La API sirve el frontend compilado si `SV_WEB_DIST=apps/web/dist`, desde el mismo origen. Una ruta `/api` inexistente da 404 y no la SPA; el *path traversal* no sale de `dist`.

### Frontend (`apps/web`: React 19, TypeScript, Vite 8, Tailwind 4, TanStack Query, ECharts 6)
- **Estética de sala de control:**
  - fondo profundo con rejilla técnica y acento ámbar de señalización;
  - IBM Plex Sans y Mono **empaquetadas localmente** (OFL), sin CDN externos;
  - **los mismos colores de estado** en vídeo, tablas, gráficas y leyenda.
- **Login.** El token de acceso solo vive en memoria; el refresh va en una cookie httpOnly. La sesión se restaura al recargar, la renovación es proactiva y ante un 401 se hace **una sola** renovación compartida.
- **Panel:** 6 KPI, cumplimiento y ocupación (24h/7d/30d), distribución de los incidentes de hoy por tipo, incidentes por día y últimos incidentes.
- **Centro de monitoreo:**
  - mosaicos 1, 2×2 y 3×3, con vista ampliada de una cámara;
  - **vídeo WebRTC (WHEP) desde MediaMTX**, con **snapshot autenticado** como respaldo;
  - superposición en un canvas: persona con ID y color por estado; EPP en verde si está presente, rojo si se detecta ausencia, blanco si no tiene persona y discontinuo si es ambiguo;
  - contadores por estado y resumen de lo que falta;
  - panel de eventos en vivo y **alertas emergentes** de incidente confirmado.
- **Incidentes:**
  - lista con filtros y paginación;
  - detalle con galería de evidencias (contexto, original, anotada, recorte), datos y observaciones;
  - **revisión** (solo transiciones válidas, con nota), historial y comentarios, y detecciones persistidas.
- **Diseño adaptable:** en móvil la navegación pasa a una barra superior y los mosaicos a una columna.

## Verificación

- **Backend:** 3 tests de integración nuevos.
  - Resumen y series desde estadísticas reales (escritura aditiva, cálculo del cumplimiento).
  - WebSocket: sin auth → cierre, origen ajeno → rechazo, reparto solo a cámaras suscritas, reenvío de eventos y liberación del cliente.
  - **WebSocket a través de uvicorn real.**
- **Frontend:** `tsc` sin errores y 5 tests vitest (geometría de la superposición con `object-fit: contain`, renovación única ante 401 simultáneos, error si la renovación falla).
- **Prueba en navegador real**, con el sistema completo (MediaMTX, API, worker con el modelo EPP y 2 cámaras de archivo):
  - panel con datos reales;
  - monitoreo con **vídeo WebRTC en las dos cámaras y la superposición alineada**;
  - eventos en vivo y alerta emergente;
  - flujo de revisión desde la UI (descartar sin nota → error del servidor visible; confirmar con nota → historial; comentario);
  - vista móvil (375 px).

## Errores encontrados en la prueba real (corregidos)

1. **El WebSocket no conectaba:** uvicorn no tenía instalada ninguna biblioteca de WebSocket. **El test de integración no lo detectó** porque el `TestClient` no pasa por uvicorn. Se añadió `websockets` (BSD-3) y un **test con uvicorn real** que cubre ese hueco.
2. El gráfico circular quedaba cortado por el desbordamiento de la rejilla CSS (`min-w-0`).
3. La leyenda se solapaba con el nombre del eje; una serie de un solo punto no se veía.
4. La etiqueta del contexto mostraba demasiados decimales.

## Limitaciones

- **Sincronización vídeo-superposición aproximada:** el vídeo WebRTC y los datos analizados (de 2 a 5 por segundo) llegan por caminos distintos (ADR-0002). Es suficiente para supervisar; la evidencia exacta está en el incidente.
- **MediaMTX permite la lectura WebRTC anónima solo desde localhost.** Para acceder desde otros equipos hay que configurar la autenticación de lectura de MediaMTX (por ejemplo, JWT emitido por la API). Pendiente para el despliegue.
- La negociación WebRTC tardó entre 5 y 10 s en algunos arranques de la prueba (espera de ICE). Se puede optimizar con *trickle ICE*.
- Los datos en vivo viajan por NOTIFY de PostgreSQL: válido para pocas cámaras. A gran escala se migrará a Valkey o NATS detrás del mismo hub.
