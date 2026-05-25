"""Static (no-DB) cross-checks for pak-derived ability flags."""

from __future__ import annotations

from roco.data.ability_flag_rules import AbilityFlagRule


def _validate_ability_flag_rules(
    rules: dict[int, AbilityFlagRule],
    effect_conf: dict[int, dict],
    buff_conf: dict[int, dict],
    consumer_index: dict[int, list[dict]],
) -> None:
    """Pak + canonical static cross-check for the ability-flag table.

    Does **not** query SQLite — keep ``build_effect_families`` a pure
    static audit over pak tables and canonical records.  Raises
    ``RuntimeError`` on:

    * Any rule effect_id missing from both ``EFFECT_CONF`` and
      direct ``BUFF_CONF`` (defence in depth against loader-side bugs /
      stub overrides).
    * Any rule effect_id whose recorded consumers include something
      other than an ability (skill / weather / mark / bloodline_magic).
      This keeps ability-flag data-layer rules from silently applying to
      non-ability consumers.
    """
    for effect_id in sorted(rules):
        if effect_id not in effect_conf and effect_id not in buff_conf:
            raise RuntimeError(
                f"ability flag effect_id {effect_id} is "
                f"missing from EFFECT_CONF.json and BUFF_CONF.json "
                f"(loader override?)"
            )
        for consumer in consumer_index.get(effect_id, []):
            kind = str(consumer.get("kind", ""))
            if kind != "ability":
                source_id = consumer.get("source_id")
                name = consumer.get("name")
                raise RuntimeError(
                    f"effect_id {effect_id} is mapped as ability_flag but "
                    f"consumed by kind={kind!r} source={source_id} name={name!r}; "
                    f"ability_flag outcome must not silently apply to non-ability "
                    f"consumers."
                )
