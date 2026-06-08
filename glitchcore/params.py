"""Parameter descriptors used by effects so the GUI can auto-build controls."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class ParamSpec:
    """One tweakable knob on an effect.

    kind: "float" | "int" | "bool" | "choice"
    For "choice", `choices` holds the labels and the stored value is an index.
    """
    label: str
    min: float = 0.0
    max: float = 1.0
    default: float = 0.0
    step: float = 0.01
    kind: str = "float"
    choices: tuple = field(default_factory=tuple)
