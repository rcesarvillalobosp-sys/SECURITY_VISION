# Fase 4: seguimiento de personas y asociación EPP–persona. Resultados

Fecha: 2026-11-13.

## Entregado

| Componente | Descripción |
|---|---|
| `ByteTracker` (`plugins/trackers/bytetrack.py`) | Implementación propia de ByteTrack (algoritmo MIT), sin OpenCV ni `supervision`. Kalman xyah, asociación en dos etapas (detecciones altas y bajas) y algoritmo húngaro. Detrás del puerto `ObjectTracker`, intercambiable con `SV_TRACKER`. |
| Adaptaciones para baja frecuencia de análisis | Vida de los tracks y tolerancia de los tentativos **en segundos**. Kalman en "fotogramas de referencia de 1/30 s" (los parámetros originales siguen siendo válidos a cualquier fps). **Rescate por distancia entre centros** cuando el IoU es 0 por gran desplazamiento entre análisis. |
| `GeometricPPEAssociator` | Regiones corporales relativas a la persona (cabeza, ojos, torso, manos, pies), con **capacidad** (1 casco, 2 guantes, 2 botas) y asignación global con algoritmo húngaro. Marca las asignaciones ambiguas y deja **sin persona** los EPP sueltos o con escala imposible. Regiones configurables. |
| `CameraAnalyzer` | Un tracker por cámara y un asociador compartido; genera `AnalyzedFrame` (tracks y asociaciones) con tiempos. |
| Worker | Detección → tracking → asociación en cada fotograma analizado. Snapshot con `P<id>` y EPP por persona. Métricas `sv_camera_tracked_persons`, `sv_camera_ppe_unassigned` y `sv_camera_ppe_ambiguous`. |
| Evaluación | `ml/evaluation/tracking_metrics.py` (MOTA, IDSW, IDF1), escenarios sintéticos con verdad conocida, `eval_tracking.py` y `eval_association.py` (con láminas de revisión). |

## Errores encontrados al validar (y corregidos)

1. **Unidades del Kalman:** al pasar de pasos por fotograma a segundos no reescalé la incertidumbre de la velocidad, y el filtro asumía velocidades unas 30 veces menores que las reales. En el cruce de dos personas había 24 cambios de identidad. Corregido con fotogramas de referencia.
2. **ByteTrack a 2 fps:** con el IoU como única señal, una persona rápida se pierde antes de que el filtro aprenda su velocidad. Se añadieron el rescate por distancia y la tolerancia temporal de los tentativos.

## Tracking: escenarios sintéticos (media de 5 semillas)

Personas caminando en 1280×720, con jitter de detector, detecciones perdidas, falsos positivos y oclusiones con detecciones de baja confianza.

| Escenario | Antes (bug) | ByteTrack original (Kalman corregido) | **Versión final** |
|---|---|---|---|
| tranquilo, 3 fps, 3 personas | MOTA 0.893 / IDF1 0.753 | 0.913 / 0.910 | **0.918 / 0.947**, IDSW 0.4 |
| concurrido, 3 fps, 8 personas | 0.746 / 0.667 | 0.778 / 0.742 | **0.795 / 0.828**, IDSW 4.4 |
| cruce frontal, 3 fps | 0.403 / 0.257 (IDSW 24) | 0.885 / 0.708 | **0.947 / 0.973**, IDSW 0 |
| rápido, 2 fps | 0.158 / 0.192 | 0.300 / 0.334 | **0.821 / 0.778**, IDSW 3.0 |
| detector malo (30 % FN, 15 % FP) | 0.353 / 0.398 | 0.354 / 0.357 | 0.396 / 0.405 |

Los umbrales de regresión de los cuatro primeros escenarios están en `tests/unit/test_tracking.py`. El escenario con detector malo muestra un límite real: el tracker no compensa un detector que falla un 30 % de las veces.

**Limitación:** son escenarios sintéticos. Validan el algoritmo, no el comportamiento con vídeo real de obra. No hay vídeo real anotado con licencia comercial (MOT17 es NC), así que se validará con vídeo propio de las cámaras.

## Asociación: imágenes reales del test (69 imágenes)

El dataset no anota a qué persona pertenece cada EPP, así que se miden propiedades observables y se revisan láminas.

| Entrada | EPP | Asignados a alguna persona | Ambiguos |
|---|---|---|---|
| Cajas anotadas (GT) | 819 | **97.6 %** | 4.1 % |
| Predicciones del modelo EPP piloto (umbral 0.4) | 812 | **90.5 %** | 6.1 % |

Por clase con predicciones: botas 94 %, casco 93 %, chaleco 90 %, guantes 89 % (16 % ambiguos en grupos apretados), `no_helmet` 73 %.

**Revisión visual** (2 láminas: un grupo de 6 personas y un estadio con figuras diminutas): no se ven asignaciones claramente erróneas. Un casco apoyado en una mesa queda correctamente "sin persona". Los guantes en grupos apretados se marcan como ambiguos. Un `no_helmet` queda huérfano porque el detector no encontró a la persona diminuta. Es una muestra pequeña: las láminas para revisión humana están en `var/association_review/`.

## Prueba con el worker real

Cámara de archivo con imágenes de test, a 3 análisis/s en CUDA (p50 74 ms), sin errores. En el snapshot aparecen las personas con su ID temporal y su EPP (`P10:helmet`).

En la primera prueba el snapshot devolvió 404 a los 16 s y no se pudo reproducir: en la repetición apareció a los 3–6 s. Queda anotado como observación.

## Pendiente

- Validación con **vídeo real** de las cámaras: estabilidad de IDs e IDSW con oclusiones reales.
- Ajustar las regiones corporales para encuadres cenitales o lejanos, si las cámaras reales lo requieren (son configurables).
