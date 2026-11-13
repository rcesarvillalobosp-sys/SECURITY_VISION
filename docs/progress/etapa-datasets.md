# Etapa: descubrimiento, adquisición y auditoría de datasets EPP — resultados

Fecha: 2026-11-12. Informe completo generado por la herramienta: `ml/datasets/reports/AUDITORIA.md` (no versionado; regenerar con `uv run svds audit`).

## Verificación de licencias

| Fuente | Licencia | Cómo se verificó | Decisión |
|---|---|---|---|
| Ultralytics Construction-PPE | CC BY 4.0 | Documentación oficial + `LICENSE.txt` y `README.md` dentro del zip | ✅ Autorizada (entrenamiento, evaluación, investigación) con atribución. **Descargada.** |
| HF cognisightlabs/PPE_Detection | CC BY 4.0 *declarada* | Tarjeta del dataset: es duplicado de `51ddhesh/PPE_Detection`, que no documenta el origen de las imágenes | ⛔ Bloqueada hasta conocer el origen de las imágenes. No descargada. |
| Roboflow gimuuniud/ppe_sheperd_v0 | Desconocida | La página responde HTTP 403 a la consulta automática | ⛔ Bloqueada: requiere verificación manual por el usuario. No descargada. |
| SH17 | CC BY-NC-SA 4.0 | README del repositorio oficial | ❌ Excluida del producto (no comercial + share-alike; imágenes de Pexels). No descargada. |

## Resultados medidos — Ultralytics Construction-PPE

- 1.000 imágenes (800 train / 200 val), 14.863 cajas, 12 clases. Integridad: los 1.000 sha256 coinciden con el `manifest.jsonl` del publicador.
- Resolución: 956 imágenes con lado menor ≥ 1080 px, 44 entre 720 y 1079 px. Ninguna por debajo de 320 px.
- Calidad automática: 0 errores. 95 avisos: 59 `ppe_without_person` (EPP fuera de cualquier caja de persona) y 36 `tiny_box`.
- Duplicados: 0 exactos. **1 par casi idéntico repartido entre el train y el val oficiales** (fuga en la partición original). Nuestras particiones lo agrupan.
- Por el nombre de archivo hay dos familias: `source-*` (293) y `ultralytics-ppe-nov2026-*` (707). **Hipótesis no confirmada:** podrían corresponder a imágenes recolectadas y generadas. El publicador no lo documenta, así que no se usa para nada hasta confirmarlo.
- Hoy solo **19 de 1.000** imágenes son utilizables para entrenar. El resto contiene cajas `vest`, `boots` o `no_boots`, que están pendientes de revisión visual.

## Revisión visual preliminar (64 recortes por clase; la decisión la toma el usuario)

| Clase | Observación | Propuesta |
|---|---|---|
| `vest` → `safety_vest` | Los 64 recortes son chalecos con bandas reflectantes (naranja/amarillo y uno turquesa). Muchas imágenes parecen generadas. | Aprobar. |
| `boots` → `safety_boot` | Mayoría de botas de trabajo con suela de tacos y varias botas de goma. Unas 8 de 64 están demasiado borrosas para juzgar. **Ninguna imagen permite verificar la puntera de protección**: visualmente solo se distingue "bota de trabajo", no "calzado certificado". | Aprobar con una semántica explícita: `safety_boot` = "calzado de trabajo tipo bota visible", nunca "calzado certificado". Revisar las cajas borrosas en CVAT. |
| `no_boots` → `no_safety_boot` | Mayoría de zapatillas o calzado de lona (coherente), pero unas 4 de 64 parecen botas o calzado de trabajo. | Aprobar solo tras re-etiquetar los casos dudosos, o aceptar el ruido de forma documentada. |

## Decisiones tomadas (2026-11-12)

- `safety_boot` significa "calzado de trabajo tipo bota visible, sin certificar protección" (`CLASS_DEFINITIONS` en `core/domain/taxonomy.py`). `boots` queda aprobado.
- `vest` queda aprobado.
- `no_boots` queda aprobado **solo tras re-etiquetarlo** (corrección `no_boots_relabel_v1`). El paquete para CVAT tiene 315 imágenes y 747 cajas `no_boots`; está pendiente.
- Efecto medido: las imágenes utilizables pasan de 19 a 130 y luego a **685 de 1.000**. Las 315 restantes son exactamente las que esperan la corrección.

## Lo que queda pendiente antes de entrenar

1. Re-etiquetar `no_boots` en CVAT siguiendo `ml/datasets/exports/review/no_boots_relabel_v1/INSTRUCCIONES.md`.
2. Verificar manualmente la licencia de Roboflow y contactar al publicador del dataset de Hugging Face (opcional).
3. Conseguir imágenes y vídeos **propios y reales** (CVAT) para el conjunto de test final. Sin ellos no se puede cumplir "evaluación final con imágenes reales no vistas".
4. 1.000 imágenes de un solo publicador, en gran parte posiblemente sintéticas y de dominio construcción, **no bastan** para un modelo de producción: hay que ampliar con datos propios.
