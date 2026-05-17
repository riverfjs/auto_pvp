"""Version-checked access to the fixed-kernel hot catalog artifact."""

from __future__ import annotations

EXPECTED_CATALOG_VERSION = 1
EXPECTED_SCHEMA_VERSION = "kernel-v1"


def validate_catalog(catalog) -> None:
    if catalog.CATALOG_VERSION != EXPECTED_CATALOG_VERSION:
        raise RuntimeError("kernel catalog version mismatch")
    if catalog.SCHEMA_VERSION != EXPECTED_SCHEMA_VERSION:
        raise RuntimeError("kernel catalog schema mismatch")
    if not catalog.SOURCE_HASH:
        raise RuntimeError("kernel catalog source hash is empty")


def load_hot_catalog():
    from roco.engine import catalog_hot

    validate_catalog(catalog_hot)
    return catalog_hot
