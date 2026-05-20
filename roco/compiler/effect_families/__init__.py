"""Effect-family catalog package.

Module layout:

* :mod:`.paths`           — shared filesystem path constants.
* :mod:`.io`              — pak / canonical JSONL / exact_effects loaders.
* :mod:`.consumers`       — reverse-consumer + team-used indexing.
* :mod:`.classify`        — coverage bucketing and family-key derivation.
* :mod:`.family_builder`  — per-family record assembly and the top-level
                            :func:`.family_builder.build_families` driver.
* :mod:`.validation`      — pak + canonical cross-checks (no DB access).
* :mod:`.render`          — JSONL / markdown rendering + check helpers.

The thin CLI entry point lives at :mod:`roco.compiler.build_effect_families`
and stays at its original module path so ``python -m
roco.compiler.build_effect_families`` remains unchanged.
"""
