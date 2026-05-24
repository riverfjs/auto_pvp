"""Effect-row primitives for damage, modifiers, and lifecycle.

Split by topic — see the individual submodules:

* :mod:`.damage` — base damage and damage-mod operators.
* :mod:`.buffs` — buff/debuff application, cleanse, dispel, conditional
  buffs (super-effective / element / bloodline / contract / team synergy).
* :mod:`.skill` — skill-level mods, power tuning, transfer/exchange.
* :mod:`.combat` — counters, interrupts, hit counts, forced switches,
  cost mods, devotion.

``roco.engine.kernel.gen_runtime_artifacts`` scans engine op modules and emits
``handler_table.py`` with one ``from ... import ...`` per op function, so the
static HANDLERS tuple stays the only runtime dispatch table.  This
``__init__`` is intentionally light.
"""
