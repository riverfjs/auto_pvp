"""Parse raw 印记 wikitext into structured JSON.

印记 pages use a section-based format (not {{模板}}):
  == 湿润印记 ==
  '''湿润印记''' 是...中的一种[[印记]]，属于[[印记|正面印记]]。
  === 基础效果 ===
  * 效果描述：全技能能耗-1。
  === 机制说明 ===
  * 属于[[印记|正面印记]]...
  === 可施加该印记的技能 ===
  * [[打湿]]：自己获得1层湿润印记。

Output: _data/parsed/yinji.json → {name: {type, effect, mechanism, source_skills}}

Usage:
    python scripts/parse_yinji.py
"""

import re
from roco.utils import RAW_DIR, PARSED_DIR, load_json, save_json

# Extract section text between a heading and the next heading
SECTION_RE = re.compile(r"===?\s*(.+?)\s*===?\s*\n(.*?)(?=\n===|\Z)", re.DOTALL)
# Extract [[skill_name]]：description
SKILL_LINK_RE = re.compile(r"\[\[([^\]]+?)\]\]\s*[：:]\s*(.+?)(?=\n|$)")


def parse_one(name: str, text: str) -> dict | None:
    result: dict = {
        "名称": name,
        "类型": None,
        "效果描述": None,
        "机制说明": [],
        "可施加技能": {},
    }

    # Determine type from the intro paragraph
    if "正面印记" in text[:500]:
        result["类型"] = "正面"
    elif "负面印记" in text[:500]:
        result["类型"] = "负面"

    # Parse sections
    for sec_match in SECTION_RE.finditer(text):
        heading = sec_match.group(1).strip()
        body = sec_match.group(2).strip()

        if "基础效果" in heading:
            ef = body.strip("* ").strip()
            result["效果描述"] = ef
        elif "机制说明" in heading:
            items = [li.strip("* ").strip() for li in body.split("\n") if li.strip().startswith("*")]
            result["机制说明"] = items
        elif "可施加" in heading and "技能" in heading:
            for sk_match in SKILL_LINK_RE.finditer(body):
                sk_name = sk_match.group(1).strip()
                sk_desc = sk_match.group(2).strip()
                result["可施加技能"][sk_name] = sk_desc

    if not result["效果描述"]:
        return None

    return result


def main() -> None:
    raw_path = RAW_DIR / "yinji_raw.json"
    if not raw_path.exists():
        print(f"Missing {raw_path}. Run fetch_details.py yinji first.")
        return

    raw: dict[str, str] = load_json(raw_path)
    yinji: dict[str, dict] = {}
    errors: list[str] = []

    for name, wikitext in raw.items():
        yj = parse_one(name, wikitext)
        if yj is None:
            errors.append(name)
        else:
            yinji[name] = yj

    out_path = PARSED_DIR / "yinji.json"
    save_json(yinji, out_path)
    print(f"Parsed {len(yinji)} 印记 → {out_path}")
    if errors:
        print(f"Skipped ({len(errors)}): {', '.join(errors)}")


if __name__ == "__main__":
    main()
