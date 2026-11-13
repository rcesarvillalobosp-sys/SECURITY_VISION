# Plan de implementación

Cada fase termina con: tests ejecutados (resultado real documentado en `docs/progress/fase-N.md`), corrección de errores, verificación manual de la funcionalidad y documentación actualizada. No se avanza con funcionalidades simuladas: lo que dependa de hardware o datos ausentes se marca como **bloqueado**, no como hecho.

## Prerrequisitos (acción del usuario)

| # | Acción | Bloquea |
|---|---|---|
| P1 | Activar la virtualización (Intel VT-x) en la BIOS | Docker / WSL2 |
| P2 | Instalar WSL2 + Docker Desktop (o usar servicios nativos: PostgreSQL, MediaMTX) | Fase 1 (compose) |
| P3 | Disponer de una cámara USB (la webcam integrada no aparece en Windows) | Criterio 2 |
| P4 | Disponer de una cámara IP RTSP (mientras tanto: RTSP simulado desde un archivo con MediaMTX + FFmpeg, declarado como tal) | Criterio 3 |
| P5 | Decidir el dataset de EPP / aportar imágenes propias | Criterio 6 |

## Fases

| Fase | Entregables | Criterio de salida verificable |
|---|---|---|
| **1. Base** | `git init`, `pyproject.toml` (uv, Python 3.12), estructura del repo, `core/` (dominio, interfaces, eventos, registro), configuración (pydantic-settings + YAML), logging estructurado, FastAPI con `/health` y `/metrics`, SQLAlchemy + Alembic con las primeras tablas (users, roles, cameras, zones, profiles, models), auth (Argon2id + JWT + RBAC), `docker-compose.yml` (postgres, valkey, mediamtx, prometheus, grafana), pre-commit (ruff, mypy, import-linter), CI local | `pytest` en verde; `alembic upgrade head` contra PG real; import-linter sin violaciones; login funcional |
| **2. Captura** | Adaptadores `file`, `ffmpeg` (PyAV: USB por dshow/v4l2 + RTSP) y `gstreamer` (Linux); `CameraSupervisor` con reconexión; `FrameSlot`; CRUD de cámaras + prueba de conectividad; integración con MediaMTX; snapshot de diagnóstico; métricas por cámara | Tests de contrato de `VideoSource`; desconectar una cámara no afecta a las demás (test de integración); fps y drops medidos y documentados |
| **3. Inferencia** | Adaptador ONNX Runtime (CPU/CUDA, TensorRT opcional) y OpenVINO; `DetectionModel` RT-DETR y RF-DETR; registro de modelos (`model.yaml` + sha256); script de exportación a ONNX; benchmark reproducible; evaluación de COCO-person; **pipeline de entrenamiento EPP** (ver la decisión de modelo) | Benchmark real en este equipo (CPU, CUDA) documentado; mAP de EPP medido en un conjunto de validación propio; cambiar de motor solo por configuración (test) |
| **4. Tracking y asociación** | ByteTrack detrás de `ObjectTracker`; `PPEAssociator` geométrico + asignación húngara | Tests con secuencias anotadas: estabilidad de IDs y precisión de la asociación |
| **5. Reglas** | `SecurityEvaluator` con reglas por EPP, verificabilidad, ventana temporal, histéresis, zonas y perfiles por cámara | Tests unitarios exhaustivos de la máquina de estados, incluidos los casos "objeto no detectado en 1 fotograma ≠ incumplimiento" y "región no verificable → NO_VERIFICABLE" |
| **6. Incidentes y evidencias** | `ObjectStorage` local; captura de evidencias; `MessageBus` (in-process + Valkey); servicio de incidentes idempotente; outbox; retención | Test e2e: vídeo de prueba → incidente con evidencia en BD/disco |
| **7. Dashboard** | Web: login, panel principal, centro de monitoreo multicámara (WebRTC + overlay en canvas), incidentes con revisión e historial | Verificación en navegador; WebSocket con reconexión |
| **8. Administración, reportes y alertas** | Usuarios/roles, configuración de cámaras/zonas (editor de polígonos)/reglas/modelos/alertas; reportes PDF/Excel; canales UI + webhook + email (SMTP propio) | Tests de API + verificación manual |
| **9. Rendimiento** | Pruebas de carga con N cámaras simuladas, perfilado, micro-batching, OpenTelemetry | Informe con cifras medidas en el hardware disponible |
| **10. Documentación y despliegue** | Guías de instalación (Windows nativo, Docker, Linux+GPU), operación, API (OpenAPI), ADRs, licencias verificadas | Instalación limpia siguiendo la guía |

## Decisión pendiente sobre el modelo EPP (Fase 3)

Con honestidad: **ningún modelo preentrenado con licencia permisiva** cubre de forma fiable persona + casco + chaleco + botas. Propuesta:

1. **Detector único afinado** (RT-DETR-R18 o RF-DETR-Nano/Small, ambos Apache-2.0) con las clases `person, helmet, vest, boots` (y opcionalmente `no_helmet`, `no_vest` como señal auxiliar, nunca como prueba única).
2. Entrenamiento en GPU. La GTX 1650 (4 GB) permite afinar modelos pequeños con lotes reducidos, aunque despacio; para iterar más rápido, el entrenamiento se puede hacer en otra máquina o en la nube y el producto sigue siendo 100 % local.
3. Mientras tanto, el pipeline se valida extremo a extremo con un detector COCO (solo la clase `person`) y las clases EPP se marcan como "modelo no disponible" → `NO_VERIFICABLE`, sin inventar detecciones.

## ADRs iniciales (en `docs/decisions/`, a redactar en la Fase 1)

- ADR-0001 Arquitectura hexagonal + paquete único `security_vision` + import-linter
- ADR-0002 Overlay en el cliente en lugar de re-codificar el vídeo anotado
- ADR-0003 PyAV/FFmpeg como adaptador de captura en Windows; GStreamer en Linux
- ADR-0004 Valkey en lugar de Redis (licencia)
- ADR-0005 Exclusión de Ultralytics (AGPL) y de las variantes PML de RF-DETR
- ADR-0006 Máquina de estados de cumplimiento con verificabilidad explícita
