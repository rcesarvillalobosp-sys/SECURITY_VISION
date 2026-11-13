"""Taxonomía canónica de clases de seguridad.

Es el contrato común entre datasets, modelos y el motor de reglas. Los modelos y
datasets de terceros se traducen a estas clases mediante mapeos explícitos; nunca
se asume equivalencia por similitud de nombre.
"""

from __future__ import annotations

from enum import StrEnum


class CanonicalClass(StrEnum):
    PERSON = "person"
    HELMET = "helmet"
    NO_HELMET = "no_helmet"
    SAFETY_VEST = "safety_vest"
    NO_VEST = "no_vest"
    SAFETY_BOOT = "safety_boot"
    NO_SAFETY_BOOT = "no_safety_boot"
    GLOVES = "gloves"
    NO_GLOVES = "no_gloves"
    GOGGLES = "goggles"
    NO_GOGGLES = "no_goggles"


# Orden estable: define los índices de clase en las exportaciones de entrenamiento.
CANONICAL_ORDER: tuple[CanonicalClass, ...] = tuple(CanonicalClass)

# Pares EPP presente / ausente. Las clases "no_*" son señales auxiliares de un
# detector, nunca prueba única de incumplimiento (ver motor de reglas).
PPE_PAIRS: dict[CanonicalClass, CanonicalClass] = {
    CanonicalClass.HELMET: CanonicalClass.NO_HELMET,
    CanonicalClass.SAFETY_VEST: CanonicalClass.NO_VEST,
    CanonicalClass.SAFETY_BOOT: CanonicalClass.NO_SAFETY_BOOT,
    CanonicalClass.GLOVES: CanonicalClass.NO_GLOVES,
    CanonicalClass.GOGGLES: CanonicalClass.NO_GOGGLES,
}

NEGATIVE_TO_POSITIVE: dict[CanonicalClass, CanonicalClass] = {v: k for k, v in PPE_PAIRS.items()}

# Semántica operativa de cada clase: lo que una cámara puede constatar visualmente.
# Se muestra en la UI y en los reportes para no sobreafirmar (p. ej. una cámara no
# puede certificar la puntera de seguridad de un calzado).
CLASS_DEFINITIONS: dict[CanonicalClass, str] = {
    CanonicalClass.PERSON: "Persona visible (total o parcialmente).",
    CanonicalClass.HELMET: "Casco de seguridad puesto en la cabeza.",
    CanonicalClass.NO_HELMET: "Cabeza visible sin casco de seguridad.",
    CanonicalClass.SAFETY_VEST: "Chaleco de alta visibilidad con bandas reflectantes, puesto.",
    CanonicalClass.NO_VEST: "Torso visible sin chaleco de alta visibilidad.",
    CanonicalClass.SAFETY_BOOT: (
        "Calzado de trabajo tipo bota visible (bota de trabajo o de goma). NO certifica "
        "protección: la puntera o la norma del calzado no son verificables por imagen."
    ),
    CanonicalClass.NO_SAFETY_BOOT: (
        "Pie visible con calzado que no es bota de trabajo (zapatillas, calzado de lona, sandalias) o descalzo."
    ),
    CanonicalClass.GLOVES: "Guantes puestos en manos visibles.",
    CanonicalClass.NO_GLOVES: "Mano visible sin guante.",
    CanonicalClass.GOGGLES: "Gafas o anteojos de protección puestos.",
    CanonicalClass.NO_GOGGLES: "Ojos visibles sin protección ocular.",
}


def class_index(cls: CanonicalClass) -> int:
    return CANONICAL_ORDER.index(cls)
