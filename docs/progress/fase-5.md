# Fase 5: motor de reglas de seguridad. Resultados

Fecha: 2026-11-13.

## Diseño (cómo se decide un incumplimiento)

1. **Observación por EPP, persona y fotograma** (`modules/security_rules/rules.py`). Puede ser:
   - `PRESENT`: el EPP está asignado a la persona sin ambigüedad.
   - `ABSENT` **explícita**: el detector vio `no_*`.
   - `ABSENT` **implícita**: la región era verificable y no se detectó nada.
   - `UNVERIFIABLE`, con motivo:
     - persona pequeña;
     - persona poco segura (posible oclusión);
     - región pequeña;
     - región cortada por el borde;
     - región tapada por otra persona más cercana;
     - asignación ambigua.
2. **Ventana deslizante** (6 s por defecto). Resulta en `DETECTED`, `MISSING`, `NOT_VERIFIABLE` (pocas observaciones verificables) o `UNCERTAIN`. La ausencia implícita **pesa la mitad** que la explícita; en guantes, 1/8, y en gafas, 1/4, porque esas regiones a menudo no se ven.
3. **Estados de la persona** (requisito 5):
   - `CUMPLIMIENTO`: todo `DETECTED`.
   - `EN_REVISION`: mezcla de detectados y no verificables o inciertos.
   - `NO_VERIFICABLE`: nada verificable, o ninguna regla aplica.
   - `POSIBLE_INCUMPLIMIENTO`: algún EPP `MISSING`.
   - `INCUMPLIMIENTO_CONFIRMADO`: se cumplen **todas** estas condiciones:
     - `MISSING` sostenido al menos `confirm_seconds` (5 s);
     - al menos 4 ausencias verificables;
     - **al menos 2 detecciones explícitas `no_*`**;
     - fuera del enfriamiento de 60 s.
4. **Cierre:**
   - `corrected`: `DETECTED` sostenido 4 s (histéresis).
   - `track_lost`: la persona desaparece más de 10 s.
5. **Zonas:** el punto de apoyo (pie) decide en qué zonas está la persona; los EPP exigidos son la **unión** de sus perfiles. Fuera de zonas se aplica el perfil por defecto de la cámara; sin perfil, la persona no se evalúa.

**Diferencia clave entre incumplimiento y ausencia de evidencia:** no ver el casco durante mucho tiempo, aunque la región sea visible, lleva como mucho a `POSIBLE_INCUMPLIMIENTO`, que es una revisión humana. Para **confirmar** hace falta evidencia positiva de ausencia (`no_helmet`). Se puede relajar por perfil (`min_explicit_absences_to_confirm: 0`), pero no se recomienda.

Todos los umbrales son configurables por perfil y se validan: no se admite decidir con menos de 2 observaciones, ni ratios incoherentes, ni umbrales desconocidos.

## Entregado

- Dominio: `RuleThresholds`, `SecurityProfile`, `ZoneRule`, `CameraRules`, `ObservationRecord` y `Violation` ampliado.
- `RuleBasedSecurityEvaluator`, con estado por cámara, detrás del puerto `SecurityEvaluator`.
- Persistencia y API:
  - `/api/v1/security-profiles` (CRUD y catálogo de EPP y umbrales);
  - `/api/v1/cameras/{id}/zones` y `/api/v1/zones/{id}`;
  - `default_profile_id` en las cámaras;
  - auditoría sin secretos;
  - evento `rules.changed.v1`.
- Bootstrap: perfil por defecto **"EPP básico (casco + chaleco)"**. Las botas no se exigen por defecto, porque `no_safety_boot` no está entrenada.
- Worker:
  - evaluación en cada fotograma analizado;
  - las reglas se recargan en caliente al cambiar perfiles o zonas, sin reiniciar la captura;
  - evento `person.compliance_changed.v1` en cada transición;
  - métricas `sv_camera_persons_by_status`, `sv_violations_confirmed_total{ppe}` y `sv_violations_closed_total{reason}`;
  - snapshot coloreado por estado.

## Verificación

- **24 tests de la máquina de estados**, entre ellos:
  - un fotograma nunca basta;
  - una caída de un fotograma no rompe el cumplimiento;
  - confirmación única y nunca antes de tiempo;
  - la ausencia solo implícita se queda en POSIBLE;
  - regiones no verificables (cortadas, pequeñas, ocluidas, ambiguas, persona poco segura) nunca generan incumplimiento;
  - **los dos ejemplos literales del requisito**: trabajador 001 → EN_REVISION y trabajador 002 → POSIBLE_INCUMPLIMIENTO;
  - parpadeo presente/ausente sin confirmación;
  - histéresis, enfriamiento, pérdida del track, zonas (unión de requisitos) y validación de umbrales.
- **2 tests de integración** de la API de reglas contra PostgreSQL real. En total pasan 18 tests de integración.
- **Prueba en vivo con el worker real** (vídeo de imágenes de test, 12 s por imagen, perfil "EPP básico"):
  - el trabajador sin casco (con gorra) pasa a POSIBLE a los 18 s y a CONFIRMADO a los 24 s, y lo marca `no_helmet`;
  - los dos trabajadores con casco siguen en CUMPLIMIENTO;
  - al cambiar de imagen, el incumplimiento se cierra como `track_lost`;
  - en 60 s hubo 3 confirmaciones (2 de casco y 1 de chaleco) y 0 errores.

  **Corrección posterior (Fase 6):** la confirmación de chaleco resultó ser un falso positivo (persona de ~35 px). Se corrigió el motor; ver docs/progress/fase-6.md.

## Limitaciones

- Los umbrales por defecto **no están calibrados con vídeo real**: son valores prudentes. Hará falta ajustarlos con grabaciones del sitio (tasa de falsos incumplimientos frente a incumplimientos perdidos).
- La calidad del motor depende del detector. Las clases `no_*` del piloto son débiles (AP50 entre 0,43 y 0,79), lo que se traduce en confirmaciones perdidas, no en confirmaciones falsas, por el requisito de evidencia explícita.
- Las zonas restringidas (permanencia) tienen el campo `kind` preparado, pero su regla no está implementada.
- Los incumplimientos aún **no se guardan como incidentes** ni capturan evidencia: eso es la Fase 6. Ahora mismo quedan en logs, eventos y métricas.
