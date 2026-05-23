"""Visual-only / ignored-candidate family detection.

Identifies families whose every source row's ``editor_name`` matches a
visual-only keyword (动效 / 飘字 / 动画 / 特效).  Surfaces individual
per-row hits separately so a mixed family (one visual row alongside
real blockers) does not get incorrectly flagged at the family level.

Phase 1 only **flags** these — it does NOT promote them to ignored rules.
"""

from __future__ import annotations


# Editor-name keywords that mark a pak effect as visual-only candidate.
VISUAL_KEYWORDS = ("动效", "飘字", "动画", "特效")


def _has_visual_keyword(text: str) -> str | None:
    for kw in VISUAL_KEYWORDS:
        if kw in text:
            return kw
    return None


def _ignored_candidate(
    source_ids: list[int],
    record_lookup: dict[int, dict],
) -> tuple[bool, str, list[dict]]:
    """Determine ignored-candidate status at family granularity.

    Returns ``(family_level_flag, reason, per_source_hits)``.

    * ``family_level_flag`` is ``True`` only when **every** source_id in
      the family has a visual-only keyword in its ``editor_name``.  This
      avoids the prior false-positive where a single ``月牙雪熊飘字用``
      row marked the whole ``buff_conf_direct:prefix_2040`` family
      (which also contains 天光 / 月光合奏 / 击鼓传花 real blockers).
    * ``per_source_hits`` lists every individual source_id whose
      editor_name matched a visual keyword — those are real
      ignored-rule candidates that future audit work should review.
    """
    hits: list[dict] = []
    for sid in source_ids:
        rec = record_lookup.get(sid) or {}
        name = str(rec.get("editor_name") or rec.get("name") or "")
        kw = _has_visual_keyword(name)
        if kw:
            hits.append({"source_id": sid, "editor_name": name, "keyword": kw})
    hits.sort(key=lambda h: h["source_id"])
    family_flag = bool(hits) and len(hits) == len(source_ids)
    if family_flag:
        reason = (
            f"all {len(hits)} source ids carry visual-only keywords "
            f"({', '.join(sorted({h['keyword'] for h in hits}))})"
        )
    else:
        reason = ""
    return family_flag, reason, hits
