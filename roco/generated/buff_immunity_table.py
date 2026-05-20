"""Auto-generated from rules/buff_immunity.jsonl — do not edit.

Flag bits, names, and ordering come from
:data:`roco.compiler.effect_codegen.buff_immunity_decoders.IMMUNITY_SPECS`.
"""

from __future__ import annotations

IMMUNITY_FORCE_SWITCH = 0x01
IMMUNITY_POISON       = 0x02
IMMUNITY_BURN         = 0x04
IMMUNITY_FREEZE       = 0x08
IMMUNITY_LEECH        = 0x10
IMMUNITY_ENERGY_DRAIN = 0x20

BUFF_IMMUNITY_TABLE: dict[int, int] = {
    20030010: IMMUNITY_FORCE_SWITCH,
    20030011: IMMUNITY_FORCE_SWITCH | IMMUNITY_POISON | IMMUNITY_BURN | IMMUNITY_FREEZE | IMMUNITY_LEECH,
}
