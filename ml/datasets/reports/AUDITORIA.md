# Informe de auditoría de datasets EPP

Generado: 2026-11-13 00:28 UTC. Todas las cifras proceden del análisis automático de los archivos descargados; las fuentes no descargadas no tienen cifras propias.

## Autorización por uso

| Fuente | Licencia | Estado licencia | Comercial | Entrenamiento (producto) | Evaluación (producto) | Investigación | Descargada |
|---|---|---|---|---|---|---|---|
| Hugging Face cognisightlabs/PPE_Detection | CC-BY-4.0 | unclear_provenance | unknown | ❌ | ❌ | ❌ | no |
| Roboflow Universe gimuuniud/ppe_sheperd_v0 | Desconocida | unverified | unknown | ❌ | ❌ | ❌ | no |
| SH17 — Safety and Health PPE dataset | CC-BY-NC-SA-4.0 | verified | forbidden | ❌ | ❌ | ❌ | no |
| Ultralytics Construction-PPE | CC-BY-4.0 | verified | allowed | ✅ | ✅ | ✅ | sí |

## Hugging Face cognisightlabs/PPE_Detection

- **Procedencia:** cognisightlabs (Hugging Face) — https://huggingface.co/datasets/cognisightlabs/PPE_Detection
- **Fuentes aguas arriba:** https://huggingface.co/datasets/51ddhesh/PPE_Detection
- **Origen de imágenes:** no documentado
- **Licencia:** Creative Commons Attribution 4.0 International (declarada) (https://creativecommons.org/licenses/by/4.0/); evidencia: https://huggingface.co/datasets/cognisightlabs/PPE_Detection; verificada: 2026-11-12
- **Notas de licencia:** La tarjeta declara cc-by-4.0, pero indica que es un duplicado de 51ddhesh/PPE_Detection, que tampoco documenta el origen de las imágenes. Un tercero no puede licenciar imágenes de las que no es titular: hasta conocer el origen, el uso comercial es incierto.

### Posibles problemas de derechos

- Licencia en estado `unclear_provenance`: no utilizable hasta resolverlo.
- Uso comercial: `unknown`.
- Requiere atribución (se incluye en ATTRIBUTION.md de cada exportación).
- Origen de las imágenes no documentado.

### Mapeo a la taxonomía canónica

| Clase original | Destino | Estado efectivo | Motivo |
|---|---|---|---|
| Vest | safety_vest | needs_visual_review | Verificar que son chalecos de alta visibilidad. |
| Safety Shoe | safety_boot | needs_visual_review | Verificar visualmente que es calzado de protección. |
| Mask | — | excluded | Mascarilla: fuera de la taxonomía inicial. |
| Helmet | helmet | direct |  |
| Goggles | goggles | direct |  |
| Gloves | gloves | direct |  |
### Limitaciones

- No anota personas: no sirve para asociar EPP a persona sin re-etiquetado.
- Sin clases negativas (no_*).
- Procedencia de imágenes desconocida: BLOQUEADO hasta aclararla con el publicador.

## Roboflow Universe gimuuniud/ppe_sheperd_v0

- **Procedencia:** gimuuniud (Roboflow Universe) — https://universe.roboflow.com/gimuuniud/ppe_sheperd_v0
- **Origen de imágenes:** no documentado
- **Licencia:** Desconocida (s/u); evidencia: https://universe.roboflow.com/gimuuniud/ppe_sheperd_v0; verificada: no
- **Notas de licencia:** La página devolvió HTTP 403 a la consulta automática y no fue posible leer la licencia (2026-11-12). En Roboflow Universe la licencia la elige quien sube el proyecto y las imágenes pueden proceder de terceros. Verificación manual pendiente.

### Posibles problemas de derechos

- Licencia en estado `unverified`: no utilizable hasta resolverlo.
- Uso comercial: `unknown`.
- Requiere atribución (se incluye en ATTRIBUTION.md de cada exportación).
- Origen de las imágenes no documentado.

### Mapeo a la taxonomía canónica

| Clase original | Destino | Estado efectivo | Motivo |
|---|---|---|---|
### Limitaciones

- Licencia, clases y volumen sin verificar.
- La descarga desde Roboflow requiere cuenta/API key: la realiza el usuario, no el sistema.

## SH17 — Safety and Health PPE dataset

- **Procedencia:** Hafiz Mughees Ahmad, Afshin Rahimi — https://github.com/ahmadmughees/SH17dataset
- **Fuentes aguas arriba:** https://www.kaggle.com/datasets/mugheesahmad/sh17-dataset-for-ppe-detection, https://www.pexels.com
- **Origen de imágenes:** Pexels
- **Licencia:** Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (https://creativecommons.org/licenses/by-nc-sa/4.0/); evidencia: https://github.com/ahmadmughees/SH17dataset; verificada: 2026-11-12
- **Atribución:** H. M. Ahmad and A. Rahimi, "SH17: A dataset for human safety and personal protective equipment detection in manufacturing industry", Journal of Safety Science and Resilience, 2024, doi:10.1016/j.jnlssr.2024.09.002
- **Notas de licencia:** No comercial y share-alike. El README limita el uso a fines educativos, de investigación y análisis. Las imágenes provienen de Pexels, cuyos términos también aplican.

### Posibles problemas de derechos

- Uso comercial: `forbidden`.
- Cláusula share-alike: obligaciones sobre obras derivadas; no se combina automáticamente.
- Requiere atribución (se incluye en ATTRIBUTION.md de cada exportación).

### Mapeo a la taxonomía canónica

| Clase original | Destino | Estado efectivo | Motivo |
|---|---|---|---|
| Person | person | direct |  |
| Helmet | helmet | direct |  |
| Safety-vest | safety_vest | direct |  |
| Gloves | gloves | direct |  |
| Glasses | goggles | needs_visual_review | Incluye gafas comunes; no equivalen a gafas de protección. |
| Shoes | — | excluded | Calzado genérico: NO equivale a safety_boot. |
| Foot | — | excluded | Parte del cuerpo, no EPP. |
| Head | — | excluded | Parte del cuerpo. |
| Face | — | excluded | Parte del cuerpo; dato biométrico sensible. |
| Ear | — | excluded | Parte del cuerpo. |
| Hands | — | excluded | Parte del cuerpo. |
| Earmuffs | — | excluded | Fuera de la taxonomía inicial. |
| Face-mask-medical | — | excluded | Fuera de la taxonomía inicial. |
| Face-guard | — | excluded | Fuera de la taxonomía inicial. |
| Tools | — | excluded | No es EPP. |
| Medical-suit | — | excluded | Fuera de la taxonomía inicial. |
| Safety-suit | — | excluded | Fuera de la taxonomía inicial. |
### Limitaciones

- Licencia no comercial: EXCLUIDO del producto.
- La clase 'Shoes' no distingue calzado de protección.

## Ultralytics Construction-PPE

- **Procedencia:** Ultralytics — https://docs.ultralytics.com/datasets/detect/construction-ppe/
- **Origen de imágenes:** Imágenes recolectadas por personas e imágenes generadas (sintéticas), según la documentación
- **Licencia:** Creative Commons Attribution 4.0 International (https://creativecommons.org/licenses/by/4.0/); evidencia: https://docs.ultralytics.com/datasets/detect/construction-ppe/; verificada: 2026-11-12
- **Atribución:** Ultralytics Construction-PPE Dataset, Ultralytics team, November 2026, CC BY 4.0
- **Notas de licencia:** Licencia leída en la documentación oficial y confirmada el 2026-11-12 en el LICENSE.txt (texto CC BY 4.0) y el README.md incluidos en el zip descargado. La licencia del dataset es independiente de la de la librería ultralytics (AGPL-3.0), que NO se usa.

### Posibles problemas de derechos

- Requiere atribución (se incluye en ATTRIBUTION.md de cada exportación).
- Incluye imágenes generadas: la titularidad y el realismo deben considerarse.
- Contiene personas identificables potencialmente: tratar como datos personales (minimización, acceso restringido, no usar para identificación).

### Mapeo a la taxonomía canónica

| Clase original | Destino | Estado efectivo | Motivo |
|---|---|---|---|
| helmet | helmet | direct |  |
| gloves | gloves | direct |  |
| vest | safety_vest | direct | aprobado tras revisión |
| boots | safety_boot | direct | aprobado tras revisión |
| goggles | goggles | direct |  |
| Person | person | direct |  |
| no_helmet | no_helmet | direct |  |
| no_goggle | no_goggles | direct |  |
| no_gloves | no_gloves | direct |  |
| no_boots | no_safety_boot | needs_visual_review | aprobado solo tras la corrección 'no_boots_relabel_v1' (pendiente en esta imagen) |
| forklift | — | excluded | Fuera de la taxonomía de EPP. |
| no_vest | no_vest | direct |  |

### Volumen

- Imágenes: **1000** · Objetos: **14863** · Imágenes sin cajas: 0 · Cajas/imagen: media 14.9, máx 76
- Particiones originales: {'train': 800, 'val': 200}

#### Objetos por clase original

| Clase | Objetos |
|---|---:|
| boots | 2484 |
| Person | 2443 |
| gloves | 1929 |
| vest | 1816 |
| helmet | 1576 |
| no_gloves | 1042 |
| no_helmet | 813 |
| goggles | 751 |
| no_boots | 747 |
| no_vest | 567 |
| forklift | 348 |
| no_goggle | 347 |

#### Objetos por clase canónica (todas las cajas mapeadas, incl. pendientes de revisión)

| Clase | Objetos |
|---|---:|
| safety_boot | 2484 |
| person | 2443 |
| gloves | 1929 |
| safety_vest | 1816 |
| helmet | 1576 |
| no_gloves | 1042 |
| no_helmet | 813 |
| goggles | 751 |
| no_safety_boot | 747 |
| no_vest | 567 |
| no_goggles | 347 |

#### Imágenes que contienen cada clase canónica

| Clase | Imágenes |
|---|---:|
| person | 991 |
| safety_vest | 801 |
| helmet | 759 |
| safety_boot | 731 |
| gloves | 682 |
| goggles | 539 |
| no_gloves | 434 |
| no_helmet | 428 |
| no_vest | 384 |
| no_safety_boot | 315 |
| no_goggles | 283 |

#### Estado de mapeo de las cajas

| Estado | Cajas |
|---|---:|
| direct | 13768 |
| excluded | 348 |
| needs_visual_review | 747 |

#### Distribución de resolución (lado menor, px)

| Rango | Imágenes |
|---|---:|
| 720-1079 | 44 |
| >=1080 | 956 |

#### Tamaño de objetos (área en px, criterio COCO)

| Tamaño | Cajas |
|---|---:|
| medium(<96²) | 4017 |
| small(<32²) | 2564 |
| large | 8282 |

#### Calidad de anotaciones (problemas detectados automáticamente)

| Problema | Ocurrencias |
|---|---:|
| ppe_without_person | 59 |
| tiny_box | 36 |

Por severidad: {'warning': 95}

#### Hojas de revisión visual pendientes

- `no_boots` → `ml/datasets/reports/review/ultralytics_construction_ppe/no_boots.jpg`

Muestras anotadas: 60 imágenes en `ml\datasets\reports\samples\ultralytics_construction_ppe`

### Limitaciones

- Solo 1.000 imágenes: insuficiente por sí solo para un modelo de producción.
- Contiene imágenes generadas (sintéticas); su proporción no está documentada. Riesgo de sesgo de dominio.
- Parte de las anotaciones es auto-anotación por IA: requiere control de calidad.
- Sin partición de test oficial (solo train/val 80/20).
- Dominio construcción; puede no representar fábricas, almacenes u otras instalaciones.
- Integridad contra `manifest.jsonl` del publicador: 1000 entradas, 0 sha256 distintos, 0 archivos ausentes.
- Corrección `no_boots_relabel_v1` (no_boots) PENDIENTE de re-etiquetado en CVAT.
- Imágenes utilizables para entrenamiento hoy (sin errores ni cajas pendientes de revisión): 685 de 1000.

## Duplicados

- Grupos de duplicados exactos (sha256): 0 (0 imágenes)
- Entre fuentes distintas: 0
- Pares casi idénticos (pHash): 1
  - `ultralytics_construction_ppe::construction-ppe/images/train/source-efc23273c04e007083114c0f217335f0.jpg` ≈ `ultralytics_construction_ppe::construction-ppe/images/val/source-9e10b0409f922546c35b276eb5a5756e.jpg` (distancia 6)

## Conclusión operativa

El entrenamiento solo puede usar fuentes con ✅ en *Entrenamiento (producto)*, y solo las imágenes sin cajas pendientes de revisión visual ni errores de anotación. Las clases en `needs_visual_review` deben revisarse con las hojas de recortes y registrarse en el manifiesto (`reviews`) antes de exportar.
