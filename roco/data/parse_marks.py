"""Parse raw 印记 wikitext into canonical JSONL.

印记 pages use a section-based format (not {{模板}}):
  == 湿润印记 ==
  '''湿润印记''' 是...中的一种[[印记]]，属于[[印记|正面印记]]。
  === 基础效果 ===
  * 效果描述：全技能能耗-1。
  === 机制说明 ===
  * 属于[[印记|正面印记]]...
  === 可施加该印记的技能 ===
  * [[打湿]]：自己获得1层湿润印记。

Output: _data/canonical/marks.jsonl

Usage:
    python scripts/parse_marks.py
"""

import re
from roco.data.utils import CANONICAL_DIR, RAW_DIR, iter_jsonl, write_jsonl

# Extract section text between a heading and the next heading
SECTION_RE = re.compile(r"===?\s*(.+?)\s*===?\s*\n(.*?)(?=\n===|\Z)", re.DOTALL)
# Extract [[skill_name]]：description
SKILL_LINK_RE = re.compile(r"\[\[([^\]]+?)\]\]\s*[：:]\s*(.+?)(?=\n|$)")

MARK_DEFS = {
    "湿润印记": ("moisture", 0, "positive"),
    "龙噬印记": ("dragon", 1, "positive"),
    "蓄势印记": ("momentum", 2, "positive"),
    "风起印记": ("wind", 3, "positive"),
    "蓄电印记": ("charge", 4, "positive"),
    "光合印记": ("solar", 5, "positive"),
    "攻击印记": ("attack", 6, "positive"),
    "减速印记": ("slow", 7, "negative"),
    "降灵印记": ("spirit", 8, "negative"),
    "星陨印记": ("meteor", 9, "negative"),
    "中毒印记": ("poison", 10, "negative"),
    "棘刺印记": ("thorn", 11, "negative"),
    "荆刺印记": ("thorn", 11, "negative"),
}

TAG_TO_MARK_NAME = {
    "POISON_MARK": "中毒印记",
    "MOISTURE_MARK": "湿润印记",
    "DRAGON_MARK": "龙噬印记",
    "WIND_MARK": "风起印记",
    "CHARGE_MARK": "蓄电印记",
    "SOLAR_MARK": "光合印记",
    "ATTACK_MARK": "攻击印记",
    "SLOW_MARK": "减速印记",
    "SLUGGISH_MARK": "迟缓印记",
    "SPIRIT_MARK": "降灵印记",
    "METEOR_MARK": "星陨印记",
    "THORN_MARK": "棘刺印记",
    "MOMENTUM_MARK": "蓄势印记",
}


def parse_one(name: str, text: str) -> dict | None:
    code, packed_index, default_polarity = MARK_DEFS.get(name, ("", -1, ""))
    result: dict = {
        "kind": "mark",
        "code": code,
        "name": name,
        "polarity": default_polarity,
        "packed_index": packed_index,
        "stacking": "stack_same_mark_replace_same_polarity",
        "effect_text": None,
        "effects": [],
        "mechanism": [],
        "source_skills": [],
    }

    # Determine type from the intro paragraph
    if "正面印记" in text[:500]:
        result["polarity"] = "positive"
    elif "负面印记" in text[:500]:
        result["polarity"] = "negative"

    # Parse sections
    for sec_match in SECTION_RE.finditer(text):
        heading = sec_match.group(1).strip()
        body = sec_match.group(2).strip()

        if "基础效果" in heading:
            ef = body.strip("* ").strip()
            result["effect_text"] = ef
        elif "机制说明" in heading:
            items = [li.strip("* ").strip() for li in body.split("\n") if li.strip().startswith("*")]
            result["mechanism"] = items
        elif "可施加" in heading and "技能" in heading:
            for sk_match in SKILL_LINK_RE.finditer(body):
                sk_name = sk_match.group(1).strip()
                sk_desc = sk_match.group(2).strip()
                result["source_skills"].append({"skill": sk_name, "description": sk_desc})

    if not result["effect_text"]:
        return None

    return result


def _empty_mark(name: str) -> dict:
    code, packed_index, polarity = MARK_DEFS[name]
    return {
        "kind": "mark",
        "code": code,
        "name": name,
        "polarity": polarity,
        "packed_index": packed_index,
        "stacking": "stack_same_mark_replace_same_polarity",
        "effect_text": "",
        "effects": [],
        "mechanism": [],
        "source_skills": [],
    }


def _augment_sources_from_skills(marks: list[dict]) -> list[dict]:
    skills_path = CANONICAL_DIR / "skills.jsonl"
    if not skills_path.exists():
        return marks
    by_name = {str(mark["name"]): mark for mark in marks}
    seen = {
        (str(mark["name"]), str(source.get("skill", "")))
        for mark in marks
        for source in mark.get("source_skills", ()) or ()
    }
    for skill in iter_jsonl(skills_path):
        skill_name = str(skill.get("name", ""))
        effect_text = str(skill.get("effect_text", ""))
        for effect in skill.get("effects", ()) or ():
            mark_name = TAG_TO_MARK_NAME.get(str(effect.get("tag", "")))
            if not mark_name:
                continue
            mark = by_name.setdefault(mark_name, _empty_mark(mark_name))
            key = (mark_name, skill_name)
            if key in seen:
                continue
            mark["source_skills"].append({"skill": skill_name, "description": effect_text})
            seen.add(key)
    return sorted(by_name.values(), key=lambda row: int(row.get("packed_index", 99)))


def main() -> None:
    raw_path = RAW_DIR / "marks_raw.jsonl"
    if not raw_path.exists():
        print(f"Missing {raw_path}. Run fetch_details.py marks first.")
        return

    marks: list[dict] = []
    errors: list[str] = []

    for row in iter_jsonl(raw_path):
        name = str(row.get("name", ""))
        yj = parse_one(name, str(row.get("raw_text", "")))
        if yj is None:
            errors.append(name)
        else:
            marks.append(yj)

    marks = _augment_sources_from_skills(marks)

    out_path = CANONICAL_DIR / "marks.jsonl"
    count = write_jsonl(marks, out_path)
    print(f"Parsed {count} 印记 -> {out_path}")
    if errors:
        print(f"Skipped ({len(errors)}): {', '.join(errors)}")


if __name__ == "__main__":
    main()
