"""Build the pak effect family catalog (thin CLI shell).

Produces two artifacts:

* ``roco/compiler/rules/effect_families.jsonl`` — one JSON line per family
  (``(pak_type, pak_effect_order)`` for EFFECT_CONF references; buff-prefix
  bucket for direct BUFF_CONF references in skill_result).  Schema doc lives
  in the project plan.
* ``_docs/effect_family_audit.md`` — same content rendered for human review.

The catalog is **not** a rule file — it has no ``handler`` field.  Its job is
to document, per family, the pak evidence (parameter shapes, cross-refs,
sample consumers, decoder-path coverage breakdown) that future kernel work
needs.  Every string field is sourced from pak/Lua data tables or the
project's own rule files — no speculation, no ``likely`` / ``would`` /
``probably`` / ``possibly``.

Run::

    uv run python -m roco.compiler.build_effect_families         # write
    uv run python -m roco.compiler.build_effect_families --check # CI gate

The actual building / rendering logic lives in the ``effect_families``
package (``classify`` / ``consumers`` / ``family_builder`` / ``io`` /
``render`` / ``validation``).  This module is intentionally thin so the
entry point and the four backwards-compat re-exports
(``COVERAGE_STATUSES`` / ``_buff_family_key`` for tests, plus
``build_families`` / ``render_*`` for downstream importers) stay in one
file at the original module path.
"""

from __future__ import annotations

import argparse
import sys

from roco.compiler.effect_families.classify import (  # re-exports for tests / downstream
    COVERAGE_STATUSES,
    _buff_family_key,
)
from roco.compiler.effect_families.family_builder import build_families
from roco.compiler.effect_families.paths import CATALOG_JSONL, CATALOG_MD
from roco.compiler.effect_families.render import (
    _build_ack_payload,
    _check,
    render_jsonl,
    render_markdown,
)


__all__ = (
    "COVERAGE_STATUSES",
    "_buff_family_key",
    "build_families",
    "render_jsonl",
    "render_markdown",
    "main",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if on-disk catalog differs from a fresh build "
        "or acknowledgements fail loader/schema validation",
    )
    args = parser.parse_args(argv)

    families = build_families()
    new_jsonl = render_jsonl(families)

    # Acknowledgements are validated unconditionally — any schema error or
    # direct-reference mismatch surfaces before either write or --check.
    try:
        acks = _build_ack_payload(families)
    except RuntimeError as exc:
        sys.stderr.write(f"acknowledgements failed validation: {exc}\n")
        return 1
    new_md = render_markdown(families, acks)

    if args.check:
        return _check(new_jsonl, new_md)
    CATALOG_JSONL.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_MD.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_JSONL.write_text(new_jsonl, encoding="utf-8")
    CATALOG_MD.write_text(new_md, encoding="utf-8")
    print(f"effect_families.jsonl: {len(families)} families -> {CATALOG_JSONL}")
    print(f"effect_family_audit.md -> {CATALOG_MD}")
    print(f"acknowledgements: {len(acks)} rows validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
