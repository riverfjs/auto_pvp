"""Codegen for ``roco/generated/buff_immunity_table.py``.

Renders the IMMUNITY_* flag constants and the
``BUFF_IMMUNITY_TABLE: dict[int, int]`` produced by
:func:`load_buff_immunity_table`.  Kept in its own module so
``gen_prefix_map.py`` can thin-call :func:`write_buff_immunity_table`
without growing further.

Output ordering:

* IMMUNITY_* constants follow :data:`IMMUNITY_SPECS` declaration order.
* ``BUFF_IMMUNITY_TABLE`` keys are sorted by ``buff_id`` ascending.
* Each value's OR expression lists const names in :data:`IMMUNITY_SPECS`
  order so a buff that adds a new immunity gets a stable, reviewable diff.
"""

from __future__ import annotations

from pathlib import Path

from roco.compiler.effect_codegen.buff_immunity_decoders import (
    IMMUNITY_SPECS,
    load_buff_immunity_table,
)


DEFAULT_OUTPUT_PATH = (
    Path(__file__).resolve().parents[2]
    / "generated"
    / "buff_immunity_table.py"
)


_HEADER = (
    '"""Auto-generated from rules/buff_immunity.jsonl — do not edit.\n'
    "\n"
    "Flag bits, names, and ordering come from\n"
    ":data:`roco.compiler.effect_codegen.buff_immunity_decoders.IMMUNITY_SPECS`.\n"
    '"""\n'
    "\n"
    "from __future__ import annotations\n"
    "\n"
)


def render(table: dict[int, int]) -> str:
    """Render the generated module text for ``table``.

    Pure function — no I/O.  Used by both the writer and the drift test.
    """
    lines: list[str] = []
    lines.append(_HEADER)
    # IMMUNITY_FORCE_SWITCH = 0x01 ...
    max_name_len = max(len(s.const_name) for s in IMMUNITY_SPECS)
    for spec in IMMUNITY_SPECS:
        pad = " " * (max_name_len - len(spec.const_name))
        lines.append(f"{spec.const_name}{pad} = 0x{spec.bit:02X}\n")
    lines.append("\n")
    lines.append("BUFF_IMMUNITY_TABLE: dict[int, int] = {\n")
    for buff_id in sorted(table):
        flags = table[buff_id]
        used = [s for s in IMMUNITY_SPECS if flags & s.bit]
        expr = " | ".join(s.const_name for s in used) if used else "0"
        lines.append(f"    {buff_id}: {expr},\n")
    lines.append("}\n")
    return "".join(lines)


def write_buff_immunity_table(
    output_path: Path | None = None,
    table: dict[int, int] | None = None,
) -> Path:
    """Render and write ``buff_immunity_table.py``.

    ``output_path`` defaults to :data:`DEFAULT_OUTPUT_PATH`; tests pass
    ``tmp_path / "buff_immunity_table.py"`` to compare without touching
    the real artifact.  ``table`` defaults to a fresh
    :func:`load_buff_immunity_table` call against the real rules + pak.
    """
    out = output_path if output_path is not None else DEFAULT_OUTPUT_PATH
    data = table if table is not None else load_buff_immunity_table()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(data), encoding="utf-8")
    return out
