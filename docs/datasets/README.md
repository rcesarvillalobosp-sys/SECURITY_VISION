# Gestión de datasets EPP

Módulo: `src/security_vision_ml/datasets/` (no forma parte del runtime del producto; `import-linter` lo garantiza).
CLI: `uv run svds <comando>`.

## Flujo

```
manifiesto YAML ──► svds acquire ──► raw/<id>/<ver>/   (original + PROVENANCE.json + extracted/, solo lectura)
                                         │
                       svds audit ───────┼─► work/<id>/<ver>/index.jsonl + labels/ (copia de trabajo normalizada)
                                         └─► reports/AUDITORIA.md, auditoria.json, samples/, review/
revisión visual (hojas de recortes) ──► se registra en `reviews:` del manifiesto ──► svds audit (de nuevo)
                       svds split ──────► work/splits/<nombre>.json   (sin fugas; holdout → test)
                       svds export ─────► exports/<nombre>/ (YOLO canónico + data.yaml + ATTRIBUTION.md)
```

## Reglas que el código hace cumplir

| Requisito | Mecanismo |
|---|---|
| Solo se descarga lo autorizado | `allowed_purposes` del manifiesto; un manifiesto con licencia no verificada o no comercial **no puede** declarar usos comerciales (falla la validación). |
| Procedencia | `PROVENANCE.json` con URL final, fecha, sha256, tamaño y copia de la licencia en el momento de la descarga. |
| Originales intactos | Archivo y extracción en solo lectura; extracción protegida contra *zip-slip*; verificación de sha256 contra el `manifest.jsonl` del publicador cuando existe. |
| Copia de trabajo | `work/`: índice y etiquetas normalizadas. Las imágenes se referencian (la normalización no toca píxeles); cualquier transformación de imagen futura escribirá archivos nuevos en `work/`. |
| No mezclar licencias incompatibles | `check_combination`: todas las fuentes deben autorizar el mismo uso; share-alike nunca se combina automáticamente en uso comercial. |
| `shoes`/`boots` ≠ `safety_boot` | Esos mapeos quedan en `needs_visual_review`; las imágenes que los contienen **no** se exportan hasta registrar una revisión `approved`/`rejected` basada en la hoja de recortes (`reports/review/<fuente>/<clase>.jpg`). |
| Duplicados | sha256 (exactos) + pHash 64 bits (casi idénticos), dentro y entre fuentes. |
| Etiquetas incorrectas | Líneas malformadas, clase desconocida, cajas degeneradas o fuera de rango, cajas duplicadas, etiquetas contradictorias (`helmet` vs `no_helmet` en la misma región), EPP fuera de cualquier persona, relaciones de aspecto extremas, etiquetas huérfanas. |
| Resolución insuficiente | Lado menor < 320 px (configurable) y cajas < 8 px. |
| Sin fuga entre particiones | Agrupación por duplicados, casi-duplicados, copias aumentadas de Roboflow y patrón de secuencia de vídeo (`--sequence-pattern`); cada grupo va entero a una partición; `find_leakage` verifica y `export` se niega si hay fugas. |
| Evaluación final con datos reales no vistos | `--holdout <fuente_propia>`: esas fuentes van íntegras a `test`. |

## Revisión visual de una clase

1. Abrir `ml/datasets/reports/review/<fuente>/<clase>.jpg` (64 recortes aleatorios).
2. Decidir si la clase corresponde realmente a la clase canónica (p. ej. ¿son botas de seguridad?).
3. Registrar la decisión en el manifiesto:

```yaml
reviews:
  - source_class: boots
    decision: approved        # o rejected
    reviewer: "<nombre>"
    reviewed_on: 2026-11-13
    sample_size: 64
    notes: "Se observan botas con puntera; 3/64 son zapatillas → re-etiquetar"
```

Una aprobación con excepciones significa re-etiquetar esas instancias en CVAT, no aceptarlas tal cual. Para eso:

1. Registrar la revisión con `requires_correction: <id>`. La aprobación solo valdrá para las imágenes corregidas.
2. `uv run svds review-export <fuente> --source-class <clase> --correction-id <id>` genera en `ml/datasets/exports/review/<id>/` las imágenes, `anotaciones_coco.zip` (todas las cajas de esas imágenes, como contexto), `labels_cvat.json` e `INSTRUCCIONES.md`. También registra la corrección como `pending` en `ml/datasets/corrections/<fuente>/<id>/`.
3. Corregir en CVAT, exportar en COCO 1.0 sin imágenes y dejar `instances_default.json` en la carpeta de la corrección. Después marcar `status: completed` en `correction.yaml`.
4. `svds audit` sustituye las cajas de esas imágenes por las corregidas, tras verificar que el sha256 de cada imagen coincide con el del paquete. Los originales no se tocan, y las correcciones (solo JSON/YAML) se versionan en git.

## Imágenes propias con CVAT

1. Crear un proyecto en CVAT e importar las etiquetas desde `ml/datasets/cvat/labels_taxonomia_canonica.json` (Constructor → Raw).
2. Anotar con la guía: marcar `no_*` **solo** cuando la región del cuerpo es visible y el EPP falta claramente; si está ocluida, no anotar nada (es *no verificable*, no ausencia).
3. Exportar en formato **COCO 1.0** con imágenes.
4. Copiar `ml/datasets/sources/_plantilla_datos_propios.yaml.example` como `own_<sitio>.yaml`, completarlo y colocar la exportación en `ml/datasets/raw/own_<sitio>/<version>/extracted/`.
5. `svds audit`, y para la evaluación final: `svds split --name v1 --sources ultralytics_construction_ppe --holdout own_<sitio>`.
