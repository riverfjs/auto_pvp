"""Codegen for ``roco/generated/mark_groups.py``.

Derives mark cover groups from pak ``buff_groupsigns``: two mark
handlers belong to the same cover group when at least one BUFF_CONF row
classified to each handler shares a non-zero ``buff_groupsigns`` entry.
Pak puts wind/moisture/meteor on ``groupsign=26``; setting any of them
clears the others.

Emits ``MARK_COVER_GROUPS`` — ``op_marks._op_mark`` consumes it at
runtime to enforce cover-group exclusivity.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PAK_DATA = ROOT / "pak-public-kit" / "output" / "data" / "BinData"
GEN_DIR = ROOT / "roco" / "generated"
MARK_GROUPS_PATH = GEN_DIR / "mark_groups.py"


def build_cover_groups(
    handler_indices: dict[str, int],
    prefix_result: dict,
    pak_data_dir: Path = PAK_DATA,
) -> tuple[tuple[str, ...], ...]:
    """Return cover groups as tuples of MarkIdx **name** strings.

    Returns ``()`` if the kernel's mark handler range is undefined
    (handler indices haven't been registered yet — a defensive guard
    for bootstrap scenarios).
    """
    h_poison_mark = handler_indices.get("H_POISON_MARK")
    h_momentum_mark = handler_indices.get("H_MOMENTUM_MARK")
    if h_poison_mark is None or h_momentum_mark is None:
        return ()
    mark_range = set(range(h_poison_mark, h_momentum_mark + 1))

    base_id_map = {int(k): v for k, v in prefix_result["base_id_map"].items()}
    prefix_map = {int(k): v for k, v in prefix_result["prefix_map"].items()}

    buff_path = pak_data_dir / "BUFF_CONF.json"
    rows = json.loads(buff_path.read_text(encoding="utf-8")).get("RocoDataRows", {})

    groups: dict[int, set[int]] = {}
    for rec in rows.values():
        base_ids = rec.get("buff_base_ids") or []
        handler = 0
        for bid in base_ids:
            if not bid:
                continue
            if bid in base_id_map and base_id_map[bid] in mark_range:
                handler = base_id_map[bid]
                break
            pfx = bid // 1000
            if pfx in prefix_map and prefix_map[pfx] in mark_range:
                handler = prefix_map[pfx]
                break
        if handler == 0:
            continue
        for sign in rec.get("buff_groupsigns") or []:
            if sign:
                groups.setdefault(int(sign), set()).add(handler)

    handler_to_mark = {
        handler_indices[k]: k.removeprefix("H_").removesuffix("_MARK")
        for k in handler_indices
        if k.endswith("_MARK") and k != "H_POISON_MARK_END"
    }

    cover_groups: list[tuple[str, ...]] = []
    for sign, handlers in sorted(groups.items()):
        if len(handlers) < 2:
            continue
        names = tuple(sorted(handler_to_mark[h] for h in handlers if h in handler_to_mark))
        if len(names) >= 2:
            cover_groups.append(names)
    return tuple(cover_groups)


def render(cover_groups: tuple[tuple[str, ...], ...]) -> str:
    lines = [
        "# Auto-generated from BUFF_CONF.buff_groupsigns — do not edit.",
        "# Regenerate with: uv run python -m roco.compiler.gen_prefix_map",
        "",
        "from roco.common.packing import MarkIdx",
        "",
        "MARK_COVER_GROUPS: tuple[tuple[MarkIdx, ...], ...] = (",
    ]
    for names in cover_groups:
        body = ", ".join(f"MarkIdx.{n}" for n in names)
        lines.append(f"    ({body}),")
    lines.append(")")
    lines.append("")
    return "\n".join(lines)


def _render_empty() -> str:
    """Render the defensive-empty fallback used when handler indices aren't
    registered yet (bootstrap-time only)."""
    return (
        "# Auto-generated — do not edit. Regenerate with gen_prefix_map.\n"
        "from roco.common.packing import MarkIdx  # noqa: F401\n"
        "MARK_COVER_GROUPS: tuple = ()\n"
    )


def write_mark_groups(
    handler_indices: dict[str, int],
    prefix_result: dict,
    pak_data_dir: Path = PAK_DATA,
) -> tuple[tuple[str, ...], ...]:
    if (
        handler_indices.get("H_POISON_MARK") is None
        or handler_indices.get("H_MOMENTUM_MARK") is None
    ):
        MARK_GROUPS_PATH.write_text(_render_empty(), encoding="utf-8")
        return ()
    cover_groups = build_cover_groups(handler_indices, prefix_result, pak_data_dir)
    MARK_GROUPS_PATH.write_text(render(cover_groups), encoding="utf-8")
    return cover_groups
