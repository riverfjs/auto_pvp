"""Effect-family catalog package.

Module layout (sorted by responsibility, leaf → root):

* :mod:`.paths`           — shared filesystem path constants.
* :mod:`.io`              — pak / canonical record loaders.
* :mod:`.consumers`       — reverse-consumer + team-used indexing.
* :mod:`.params`          — ``effect_param`` shape decoding.
* :mod:`.refs`            — cross-reference + desc-note extraction.
* :mod:`.classify`        — coverage bucketing + family-key derivation.
* :mod:`.validation`      — pak + canonical cross-checks (no DB access).
* :mod:`.family_builder`  — per-family record assembly and the top-level
                            :func:`.family_builder.build_families` driver.
* :mod:`.render`          — JSONL / markdown rendering + drift check.

The CLI entry point lives at :mod:`roco.compiler_v2.build_effect_families`
and stays at its original module path so ``python -m
roco.compiler_v2.build_effect_families`` remains unchanged.  That module
imports from this package — it does **not** re-export internals; tests
and downstream code must import from the appropriate sub-module.
"""
