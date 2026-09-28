#!/usr/bin/env python3
"""L1 硬规则：确定性校验，零 LLM。"""
from __future__ import annotations

import re
from typing import Any


SEVERITY = {"blocker": 0, "warning": 1, "info": 2}


def _issue(severity: str, code: str, title: str,
           detail: str = "", evidence: list | None = None,
           suggestion: str = "") -> dict:
    return {
        "severity": severity, "code": code, "title": title,
        "detail": detail, "evidence": evidence or [],
        "suggestion": suggestion,
    }


# ---------------------------------------------------------------- 入口
def check_hard_rules(extracted: dict, ctx: dict, db) -> list[dict]:
    chapter_no = extracted.get("chapter_no", 0)
    out: list[dict] = []
    out += _check_dead_acting(extracted, chapter_no, db)
    out += _check_time_regress(extracted, chapter_no, db)
    out += _check_location_conflict(extracted)
    out += _check_ability_overflow(extracted, db)
    out += _check_alias_mismatch(extracted, ctx)
    out += _check_relation_asymmetry(extracted, chapter_no, db)
    out += _check_forbid_hit(extracted, ctx.get("contract", {}))
    return out


# ---------------------------------------------------------------- 各规则
def _check_dead_acting(extracted, chapter_no, db):
    issues = []
    for cs in extracted.get("character_states", []):
        name = cs.get("character")
        if not name:
            continue
        if cs.get("alive") is False:
            continue
        prev = db.get_character_state_latest_before(name, chapter_no)
        if prev and not prev.get("alive"):
            issues.append(_issue(
                "blocker", "DEAD_ACTING",
                f"角色「{name}」已死亡，本章仍出场",
                evidence=cs.get("evidence", []),
                suggestion="删除该角色本章所有出场，或改为假死并补台词",
            ))
    return issues


def _check_time_regress(extracted, chapter_no, db):
    """只在明确日期回退时报警。同一天内的时间描述不比较。"""
    issues = []
    last = db.timeline_last_before(chapter_no)
    if not last:
        return issues
    last_time = _parse_iso_date(last.get("story_time"))

    for ev in extracted.get("timeline_events", []):
        cur = _parse_iso_date(ev.get("story_time"))
        # 两边都必须是 YYYY-MM-DD 或 YYYY-MM 这种可比较日期
        if not last_time or not cur:
            continue
        # 只有精度到日/月时才比
        precision = ev.get("story_time_precision", "vague")
        if precision not in ("day", "month", "year"):
            continue
        if cur < last_time:
            issues.append(_issue(
                "blocker", "TIME_REGRESS",
                f"事件时间 {ev.get('story_time')} 早于已发生事件 {last.get('story_time')}",
                evidence=[ev.get("evidence", "")],
                suggestion="调整本章时间标记，或改为倒叙并明确标注",
            ))
    return issues


def _parse_iso_date(s):
    """只解析 YYYY-MM-DD / YYYY-MM / YYYY 这种字符串，其他返回 None。"""
    if not s:
        return None
    import re
    m = re.match(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", str(s).strip())
    if not m:
        return None
    y = int(m.group(1))
    mo = int(m.group(2) or 1)
    d = int(m.group(3) or 1)
    return (y, mo, d)


def _check_location_conflict(extracted):
    """只在同一段落（paragraph_idx）内出现两地才报。多场景分别出现是正常的。"""
    per_char_per_para: dict[str, dict[int, set]] = {}
    for le in extracted.get("location_events", []):
        loc = le.get("location")
        para_idx = le.get("paragraph_idx", 0)
        if not loc:
            continue
        for ch in le.get("characters_present", []):
            per_char_per_para.setdefault(ch, {}).setdefault(para_idx, set()).add(loc)
    issues = []
    for ch, per_para in per_char_per_para.items():
        for para_idx, locs in per_para.items():
            if len(locs) > 1:
                issues.append(_issue(
                    "blocker", "LOCATION_CONFLICT",
                    f"角色「{ch}」在同一段落 {para_idx} 出现在多个地点：{sorted(locs)}",
                    suggestion="确认是否为转场，若是需明确写出移动过程",
                ))
    return issues


def _check_ability_overflow(extracted, db):
    issues = []
    for fact in extracted.get("facts", []):
        if fact.get("kind") != "action":
            continue
        subj = fact.get("subject")
        obj = fact.get("object") or ""
        if not subj or not obj:
            continue
        char = db.character_by_name(subj)
        if not char:
            continue
        abilities = char.get("abilities") or []
        if abilities and _uses_unowned_ability(obj, abilities):
            issues.append(_issue(
                "warning", "ABILITY_OVERFLOW",
                f"角色「{subj}」使用未登记能力",
                detail=obj,
                evidence=[fact.get("evidence", "")],
                suggestion="补充能力到角色卡，或修改动作",
            ))
    return issues


def _uses_unowned_ability(obj: str, owned: list) -> bool:
    verbs = ("使用", "施展", "发动", "调用")
    if not any(v in obj for v in verbs):
        return False
    return not any(a in obj for a in owned)


def _check_alias_mismatch(extracted, ctx):
    issues = []
    char_index: dict[str, str] = {}
    for c in ctx.get("characters", []):
        char_index[c["name"]] = c["name"]
        for a in c.get("aliases", []):
            char_index[a] = c["name"]

    # 过滤：项目名/方案名/系统名 不该走 alias 检查
    NON_PERSON_SUFFIX = (
        "项目", "方案", "系统", "计划", "通知", "合同",
        "部门", "公司", "集团", "厂商", "平台",
    )

    for fact in extracted.get("facts", []):
        subj = fact.get("subject")
        if not subj:
            continue
        if any(subj.endswith(suf) for suf in NON_PERSON_SUFFIX):
            continue
        if subj not in char_index:
            issues.append(_issue(
                "warning", "ALIAS_MISMATCH",
                f"称谓「{subj}」不在角色卡或别名列表中",
                evidence=[fact.get("evidence", "")],
                suggestion="在角色卡补别名，或统一称谓",
            ))
    return issues


def _check_relation_asymmetry(extracted, chapter_no, db):
    issues = []
    for cs in extracted.get("character_states", []):
        me = cs.get("character")
        for rel in cs.get("relationship_changes", []):
            target = rel.get("target")
            dim = rel.get("dimension")
            if not target or not dim:
                continue
            rev = db.character_state_get(target, chapter_no)
            if not rev:
                continue
            rels = rev.get("relations") or {}
            my_rel = rels.get(me, {})
            if dim == "parent" and "child" not in my_rel:
                issues.append(_issue(
                    "warning", "RELATION_ASYMMETRY",
                    f"{me} → {target} 关系不对称（parent/child）",
                    suggestion="补齐反向关系",
                ))
            elif dim == "subordinate" and "superior" not in my_rel:
                issues.append(_issue(
                    "warning", "RELATION_ASYMMETRY",
                    f"{me} → {target} 关系不对称（subordinate/superior）",
                    suggestion="补齐反向关系",
                ))
    return issues


def _check_forbid_hit(extracted, contract):
    issues = []
    forbids = contract.get("forbid", []) or []
    paragraphs = extracted.get("_paragraphs", []) or []
    for f in forbids:
        keywords = _extract_forbid_keywords(f)
        if not keywords:
            continue
        for idx, p in enumerate(paragraphs):
            if all(k in p for k in keywords):
                issues.append(_issue(
                    "warning", "FORBID_VIOLATION",
                    f"疑似违反合同禁止项：{f}",
                    evidence=[p[:120]],
                    suggestion="人工复核，或修改正文",
                ))
                break
    return issues


def _extract_forbid_keywords(forbid: str) -> list[str]:
    quoted = re.findall(r"[\"'「『](.+?)[\"'」』]", forbid)
    if quoted:
        return quoted
    # 提取"不能出现X"里的X
    m = re.search(r"不能(?:出现|写|有)(.+)", forbid)
    if m:
        return [m.group(1).strip()[:20]]
    return []