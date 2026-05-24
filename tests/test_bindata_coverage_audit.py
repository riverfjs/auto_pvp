from __future__ import annotations

from roco.compiler_v2.bindata_coverage_audit import build_audit, main


def test_bindata_coverage_audit_tracks_core_battle_tables():
    audit = build_audit()
    by_table = {row["table"]: row for row in audit["tables"]}

    assert by_table["SKILL_CONF"]["coverage"] == "generator_or_importer_referenced"
    assert by_table["EFFECT_CONF"]["coverage"] == "generator_or_importer_referenced"
    assert by_table["BUFF_CONF"]["coverage"] == "generator_or_importer_referenced"
    assert by_table["BUFFBASE_CONF"]["coverage"] == "generator_or_importer_referenced"
    assert by_table["BATTLE_GLOBAL_CONFIG"]["coverage"] == "generator_or_importer_referenced"
    assert by_table["TYPE_DICTIONARY"]["coverage"] == "generator_or_importer_referenced"
    assert by_table["PET_BLOOD_CONF"]["coverage"] == "generator_or_importer_referenced"
    assert by_table["PLAYER_MAGIC_CONF"]["coverage"] == "generator_or_importer_referenced"
    assert by_table["BAG_ITEM_CONF"]["coverage"] == "generator_or_importer_referenced"

    missing = set(audit["core_unreferenced_tables"])
    assert "WEATHER_CONF" not in missing
    assert "PET_BLOOD_CONF" not in missing
    assert "PLAYER_MAGIC_CONF" not in missing
    assert "MAGIC_BASE_CONF" not in missing


def test_bindata_coverage_audit_flags_manual_kernel_debt():
    audit = build_audit()
    constants = {row["name"] for row in audit["manual_kernel_constants"]}
    bindings = {row["symbol"] for row in audit["manual_semantic_bindings"]}

    assert "STARTING_ENERGY" in constants
    assert "BURN_DAMAGE_BPS" in constants
    assert "MAGIC_WILLPOWER" not in constants
    assert "BLOODLINE_LEADER" not in constants
    assert "IMMUNITY_SPECS" in bindings
    assert "MARK_NOTE_BY_IDX" not in bindings


def test_bindata_coverage_audit_generated_file_is_current():
    assert main(["--check"]) == 0
