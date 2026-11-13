# API REST: endpoints

Generado por `scripts/export_openapi.py` a partir del código (versión 0.1.0). Especificación completa: [openapi.json](openapi.json). En desarrollo, documentación interactiva en `/docs` (desactivada en producción).

- **Autenticación:** `Authorization: Bearer <token de acceso>` (`POST /api/v1/auth/login`; renovación con la cookie httpOnly `sv_refresh` en `POST /api/v1/auth/refresh`).
- **Errores:** JSON `{"detail": ..., "code": ...}` con 401/403/404/409/422.
- **Tiempo real:** WebSocket `/api/v1/ws` (autenticación en el primer mensaje `{"type":"auth","token":...}`).
- **Fuera de la especificación:** `/metrics` (solo redes permitidas), `/api/v1/files/...` (evidencias con URL firmada) y `/api/v1/media/auth` (uso interno de MediaMTX).

| Método | Ruta | Permiso | Área | Operación |
|---|---|---|---|---|
| GET | `/api/v1/alert-channels` | alerts:write | admin | list channels |
| POST | `/api/v1/alert-channels` | alerts:write | admin | create channel |
| GET | `/api/v1/alert-channels/info` | alerts:write | admin | alerts info |
| DELETE | `/api/v1/alert-channels/{channel_id}` | alerts:write | admin | delete channel |
| PATCH | `/api/v1/alert-channels/{channel_id}` | alerts:write | admin | update channel |
| POST | `/api/v1/alert-channels/{channel_id}/test` | alerts:write | admin | test channel |
| GET | `/api/v1/alert-deliveries` | alerts:write | admin | deliveries |
| POST | `/api/v1/alert-deliveries/{delivery_id}/retry` | alerts:write | admin | retry delivery |
| GET | `/api/v1/audit` | audit:read | admin | audit |
| POST | `/api/v1/auth/login` | pública | auth | login |
| POST | `/api/v1/auth/logout` | sesión | auth | logout |
| GET | `/api/v1/auth/me` | sesión | auth | me |
| POST | `/api/v1/auth/refresh` | pública | auth | refresh |
| GET | `/api/v1/cameras` | cameras:read | cameras | list cameras |
| POST | `/api/v1/cameras` | cameras:write | cameras | create camera |
| GET | `/api/v1/cameras/discover` | cameras:write | cameras | ONVIF (WS-Discovery en la red local del servidor) o USB (dispositivos del propio servidor). |
| DELETE | `/api/v1/cameras/{camera_id}` | cameras:write | cameras | delete camera |
| GET | `/api/v1/cameras/{camera_id}` | cameras:read | cameras | get camera |
| PATCH | `/api/v1/cameras/{camera_id}` | cameras:write | cameras | update camera |
| GET | `/api/v1/cameras/{camera_id}/snapshot` | cameras:read | cameras | snapshot |
| POST | `/api/v1/cameras/{camera_id}/test` | cameras:write | cameras | Prueba de conectividad directa. En USB puede fallar si el worker ya tiene el dispositivo abierto. |
| GET | `/api/v1/cameras/{camera_id}/zones` | cameras:read | rules | list zones |
| POST | `/api/v1/cameras/{camera_id}/zones` | zones:write | rules | create zone |
| GET | `/api/v1/dashboard/series` | incidents:read | dashboard | series |
| GET | `/api/v1/dashboard/summary` | incidents:read | dashboard | summary |
| GET | `/api/v1/incidents` | incidents:read | incidents | list incidents |
| GET | `/api/v1/incidents/{incident_id}` | incidents:read | incidents | get incident |
| POST | `/api/v1/incidents/{incident_id}/comments` | incidents:review | incidents | add comment |
| PATCH | `/api/v1/incidents/{incident_id}/status` | incidents:review | incidents | change status |
| POST | `/api/v1/me/password` | sesión | users | Cambia la contraseña propia. Cierra TODAS las sesiones del usuario (también la actual). |
| GET | `/api/v1/models` | cameras:read | admin | list models |
| PUT | `/api/v1/models/active` | models:write | admin | activate model |
| GET | `/api/v1/reports/{period}` | reports:read | reports | report |
| GET | `/api/v1/roles` | roles:read | users | list roles |
| GET | `/api/v1/security-profiles` | cameras:read | rules | list profiles |
| POST | `/api/v1/security-profiles` | rules:write | rules | create profile |
| GET | `/api/v1/security-profiles/catalog` | cameras:read | rules | catalog |
| DELETE | `/api/v1/security-profiles/{profile_id}` | rules:write | rules | delete profile |
| PATCH | `/api/v1/security-profiles/{profile_id}` | rules:write | rules | update profile |
| GET | `/api/v1/users` | users:read | users | list users |
| POST | `/api/v1/users` | users:write | users | create user |
| GET | `/api/v1/users/{user_id}` | users:read | users | get user |
| PATCH | `/api/v1/users/{user_id}` | users:write | users | update user |
| POST | `/api/v1/users/{user_id}/password` | users:write | users | reset password |
| PUT | `/api/v1/users/{user_id}/roles` | users:write | users | set roles |
| DELETE | `/api/v1/zones/{zone_id}` | zones:write | rules | delete zone |
| PATCH | `/api/v1/zones/{zone_id}` | zones:write | rules | update zone |
| GET | `/health/live` | pública | system | live |
| GET | `/health/ready` | pública | system | ready |
