"""Path constants shared across the effect_families modules."""

from __future__ import annotations

from pathlib import Path


# Package is at roco/compiler/effect_families/, so parents[3] is the repo root.
ROOT = Path(__file__).resolve().parents[3]
PAK_DATA = ROOT / "pak-public-kit" / "output" / "data"
EXACT_RULES_PATH = ROOT / "roco" / "compiler" / "rules" / "exact_effects.jsonl"
CATALOG_JSONL = ROOT / "roco" / "compiler" / "rules" / "effect_families.jsonl"
CATALOG_MD = ROOT / "_docs" / "effect_family_audit.md"
CANONICAL_DIR = ROOT / "_data" / "canonical"
