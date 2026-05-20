"""Codegen for ``roco/generated/weather_decoders.py``.

Hand-curates two tiny tables — pak ``effect_param[0]`` → kernel
``WeatherType`` and the kernel's per-type default initial turn count —
then walks ``EFFECT_CONF.json`` for every weather-setter row
(``effect_order=28`` ``type=3``) and emits a dispatch table the
classifier can consume.

The default-turns table is **kernel policy**, not pak schema: the first
end-of-turn tick decrements once, so a value of 8 here matches the
canonical 7-turns-remaining state the kernel tests assert.  See
``_docs/phase4_dataization_boundaries.md`` for why this lives in code
rather than JSONL.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PAK_DATA = ROOT / "pak-public-kit" / "output" / "data" / "BinData"
GEN_DIR = ROOT / "roco" / "generated"
WEATHER_DECODERS_PATH = GEN_DIR / "weather_decoders.py"


# pak ``effect_param[0]`` weather code → kernel ``WeatherType`` enum value.
# Hand-curated because pak ships no machine-readable cross-reference; keeping
# it as a tight 4-entry table here (instead of in JSONL) is the smallest
# version of "data, not Python source" — anybody touching weather decoding
# updates this table once and ``write_weather_decoders`` does the rest.
_PAK_WEATHER_TO_KERNEL = {
    1: "NONE",       # 晴天 (clears weather)
    3: "RAIN",       # 求雨
    5: "SNOW",       # 暴风雪
    6: "SANDSTORM",  # 沙暴
}

# Default initial turn count per kernel ``WeatherType`` when pak supplies 0.
# The first end-of-turn tick decrements once, so a value of 8 here matches
# the canonical 7-turns-remaining state the kernel tests assert.
_WEATHER_DEFAULT_TURNS = {
    "NONE": 0,
    "RAIN": 8,
    "SNOW": 8,
    "SANDSTORM": 8,
}


def load_weather_decoders(pak_data_dir: Path = PAK_DATA) -> list[tuple[int, str, int, int]]:
    """Scan ``EFFECT_CONF`` for weather-setter rows.

    Returns ``[(effect_id, kernel_name, kernel_value, default_turns), ...]``
    sorted by ``effect_id``.  Rows with an unmapped pak weather code are
    skipped — they surface as audit gaps until the pak→kernel table
    grows an entry.
    """
    from roco.common.enums import WeatherType

    rows = json.loads((pak_data_dir / "EFFECT_CONF.json").read_text(encoding="utf-8"))
    pak_effects = rows.get("RocoDataRows", rows)

    decoded: list[tuple[int, str, int, int]] = []
    for eid_str, rec in pak_effects.items():
        if rec.get("effect_order") != 28 or rec.get("type") != 3:
            continue
        params = rec.get("effect_param") or []
        if not params or not isinstance(params[0], dict):
            continue
        inner = params[0].get("params") or []
        if not inner:
            continue
        try:
            pak_code = int(inner[0])
        except (TypeError, ValueError):
            continue
        kernel_name = _PAK_WEATHER_TO_KERNEL.get(pak_code)
        if kernel_name is None:
            continue
        kernel_value = int(getattr(WeatherType, kernel_name).value)
        default_turns = _WEATHER_DEFAULT_TURNS.get(kernel_name, 0)
        decoded.append((int(eid_str), kernel_name, kernel_value, default_turns))

    decoded.sort()
    return decoded


def render(decoded: list[tuple[int, str, int, int]]) -> str:
    lines = [
        "# Auto-generated from EFFECT_CONF.json — do not edit.",
        "# Regenerate with: uv run python -m roco.compiler.gen_prefix_map",
        "",
        "from roco.generated.handler_indices import H_WEATHER",
        "",
        "# ``effect_id -> (handler_idx, weather_kernel_id, default_turns, 0, 0, timing_override)``",
        "WEATHER_EFFECT_DECODERS: dict[int, tuple[int, int, int, int, int, int]] = {",
    ]
    for eid, kernel_name, kernel_value, default_turns in decoded:
        lines.append(
            f"    {eid}: (H_WEATHER, {kernel_value}, {default_turns}, 0, 0, 0),  # pak {kernel_name}"
        )
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def write_weather_decoders(pak_data_dir: Path = PAK_DATA) -> int:
    decoded = load_weather_decoders(pak_data_dir)
    WEATHER_DECODERS_PATH.write_text(render(decoded), encoding="utf-8")
    return len(decoded)
