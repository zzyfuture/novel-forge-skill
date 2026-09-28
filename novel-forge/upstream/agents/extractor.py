#!/usr/bin/env python3
"""Extractor：从章节正文抽取结构化事实。"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from .. import store
from ..llm import LLMClient, LLMError, parse_json_lenient


class ExtractorError(Exception):
    pass


# ---------------------------------------------------------------- Schema
EXTRACTOR_SCHEMA = {
    "type": "object",
    "required": ["chapter_no", "summary", "facts"],
    "properties": {
        "chapter_no": {"type": "integer"},
        "confidence_overall": {"type": "number"},
        "summary": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "key_events": {"type": "array", "items": {"type": "string"}},
                "emotional_arc": {"type": "string"},
                "tension": {"type": "integer"},
                "word_count": {"type": "integer"},
            },
            "required": ["text"],
        },
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string",
                             "enum": ["action", "state", "relationship",
                                      "knowledge", "possession"]},
                    "subject": {"type": "string"},
                    "predicate": {"type": "string"},
                    "object": {"type": "string"},
                    "chapter_no": {"type": "integer"},
                    "paragraph_idx": {"type": "integer"},
                    "evidence": {"type": "string"},
                    "confidence": {"type": "number"},
                    "new_or_update": {"type": "string", "enum": ["new", "update"]},
                },
                "required": ["kind", "subject", "predicate", "object",
                             "evidence", "confidence"],
            },
        },
        "character_states": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "character": {"type": "string"},
                    "alive": {"type": "boolean"},
                    "location": {"type": "string"},
                    "power_level": {"type": ["integer", "null"]},
                    "stance": {"type": ["string", "null"]},
                    "inner_state": {"type": ["string", "null"]},
                    "knowledge_gained": {"type": "array", "items": {"type": "string"}},
                    "knowledge_lost": {"type": "array", "items": {"type": "string"}},
                    "relationship_changes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "target": {"type": "string"},
                                "dimension": {"type": "string"},
                                "from": {"type": ["number", "null"]},
                                "to": {"type": ["number", "null"]},
                                "direction": {"type": "string",
                                              "enum": ["up", "down", "stable"]},
                                "reason": {"type": "string"},
                            },
                            "required": ["target", "dimension"],
                        },
                    },
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["character", "alive"],
            },
        },
        "location_events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "location": {"type": "string"},
                    "event": {"type": "string"},
                    "characters_present": {"type": "array", "items": {"type": "string"}},
                    "paragraph_idx": {"type": "integer"},
                },
                "required": ["location"],
            },
        },
        "timeline_events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "story_time": {"type": ["string", "null"]},
                    "story_time_precision": {"type": "string",
                                             "enum": ["day", "month", "year", "vague"]},
                    "event": {"type": "string"},
                    "actors": {"type": "array", "items": {"type": "string"}},
                    "paragraph_idx": {"type": "integer"},
                    "evidence": {"type": "string"},
                    "relative_to_prev": {"type": "string"},
                },
                "required": ["event"],
            },
        },
        "scheme_evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "scheme_id": {"type": "string"},
                    "scheme_name": {"type": "string"},
                    "contract_expectation": {"type": "string"},
                    "matched_evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "paragraph_idx": {"type": "integer"},
                                "text": {"type": "string"},
                                "match_strength": {"type": "string",
                                                   "enum": ["strong", "medium", "weak"]},
                                "reason": {"type": "string"},
                            },
                        },
                    },
                    "additional_evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "paragraph_idx": {"type": "integer"},
                                "text": {"type": "string"},
                                "match_strength": {"type": "string"},
                                "reason": {"type": "string"},
                            },
                        },
                    },
                    "missing": {"type": "boolean"},
                    "miss_reason": {"type": ["string", "null"]},
                },
                "required": ["scheme_id", "missing"],
            },
        },
        "domain_details": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string",
                                 "enum": ["term", "process", "era"]},
                    "text": {"type": "string"},
                    "context": {"type": "string"},
                    "paragraph_idx": {"type": "integer"},
                    "is_known": {"type": "boolean"},
                    "known_id": {"type": ["integer", "null"]},
                    "era_year": {"type": ["integer", "null"]},
                    "new_or_known": {"type": "string",
                                     "enum": ["known", "new", "possible_new"]},
                    "note": {"type": "string"},
                },
                "required": ["category", "text"],
            },
        },
        "anachronism_candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "paragraph_idx": {"type": "integer"},
                    "suspected_year": {"type": "integer"},
                    "suspected_issue": {"type": "string"},
                    "evidence_rule": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["text"],
            },
        },
        "extraction_warnings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string"},
                    "message": {"type": "string"},
                    "paragraph_idx": {"type": ["integer", "null"]},
                },
                "required": ["kind", "message"],
            },
        },
    },
}


# ---------------------------------------------------------------- Input
@dataclass
class ExtractorContext:
    characters: list[dict] = field(default_factory=list)
    locations: list[dict] = field(default_factory=list)
    active_schemes: list[dict] = field(default_factory=list)
    domain_terms: list[dict] = field(default_factory=list)
    era_facts: list[dict] = field(default_factory=list)
    prev_chapter_summary: str = ""


# ---------------------------------------------------------------- System
SYSTEM_PROMPT = """你是「小说一致性引擎」的事实抽取器（Extractor）。

# 你的唯一职责
从给定的章节正文中，抽取结构化事实。你是一台照相机，不是裁判。

# 你绝对不做的事
- 不判断事实是否符合设定
- 不修改正文
- 不裁决冲突
- 不推断、不补充、不脑补
- 不输出"可能""大概""似乎"这类词（confidence 字段除外）

# 你输出什么
严格按 JSON Schema 输出。每个事实必须带：
- 章节号
- 段落号
- 原文证据（逐字引用）
- confidence（0–1 之间的数字）

# 你怎么处理不确定
不确定时：
- 如果只是记不清，用 confidence < 0.7 标记
- 如果完全无法判断，标 missing，不要编
- 如果出现歧义（如"老周"可能是某角色的别名），写入 extraction_warnings

# 你怎么处理合同要求
输入里会有 active_schemes，包含本章合同要求埋/收的方案证据。
你要：
- 对照每个 Scheme 的 plant_evidence / payoff_evidence，在正文里找对应句子
- 找到就写 matched_evidence，标注 match_strength
- 找不到就写 missing: true，不要编

# 你怎么处理行业细节
输入里会有 domain_terms 和 era_facts。
你要：
- 在正文里识别"这是行业细节/年代细节"的句子
- 标注 new_or_known（在 Domain KB 里能找到 = known，找不到 = new）
- 不做"这个细节对不对"的判断
- 但如果识别出疑似年代错误（如 2010 年出现二维码支付），写入 anachronism_candidates

# 你怎么处理关系变化
relationship_changes 是本系统最重要的输出之一。
当某角色对另一角色的信任、恐惧、利用价值发生明显变化时，必须记录：
- from / to（如果正文给了明确数值）
- 或者 direction（up / down / stable，如果正文只给了方向）
- reason（必须来自正文，不能推断）

# 输出格式
只输出一个 JSON 对象，不要任何解释文字。
"""


# ---------------------------------------------------------------- User prompt
def build_user_prompt(chapter_no: int, body_md: str, contract: dict,
                      ctx: ExtractorContext) -> str:
    return f"""# 本章信息
章节号：{chapter_no}
POV 角色：{contract.get('pov_character_id', '—')}
目标字数：{contract.get('word_target', 3500)}

# 本章合同
{json.dumps(contract, ensure_ascii=False, indent=2)[:3000]}

# 已有角色名单
{json.dumps([{'name': c['name'], 'aliases': c.get('aliases', [])} for c in ctx.characters],
            ensure_ascii=False)}

# 已有地点名单
{json.dumps([{'name': l['name']} for l in ctx.locations], ensure_ascii=False)}

# 本章应涉及的 Scheme
{json.dumps([{
    'id': s['id'], 'name': s['name'],
    'chapter_planted': s.get('chapter_planted'),
    'chapter_armed': s.get('chapter_armed'),
    'chapter_triggered': s.get('chapter_triggered'),
    'chapter_resolved': s.get('chapter_resolved'),
    'information_gap': s.get('information_gap'),
} for s in ctx.active_schemes], ensure_ascii=False, indent=2)}

# 本章对应的行业术语（如正文出现请识别）
{json.dumps([t['term'] for t in ctx.domain_terms[:20]], ensure_ascii=False)}

# 本章对应年份的年代事实
{json.dumps([{'year': e['year'], 'category': e['category'],
              'forbidden': e.get('forbidden_anachronism', [])}
             for e in ctx.era_facts], ensure_ascii=False)}

# 上一章摘要
{ctx.prev_chapter_summary or '（无）'}

# 本章正文
{body_md}

---

请按 System Prompt 的 Schema 输出 JSON。"""


# ---------------------------------------------------------------- 抽取
def extract(chapter_no: int, body_md: str, contract: dict,
            ctx: ExtractorContext | dict, llm: LLMClient) -> dict:
    if isinstance(ctx, dict):
        ctx = ExtractorContext(**{k: ctx.get(k, []) for k in
                                  ("characters", "locations", "active_schemes",
                                   "domain_terms", "era_facts")}
                                | {"prev_chapter_summary":
                                   ctx.get("prev_chapter_summary", "")})

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(chapter_no, body_md, contract, ctx)},
    ]
    try:
        raw = llm.call_with_schema(
            messages=messages,
            schema=EXTRACTOR_SCHEMA,
            model_role="extractor",
            temperature=0.1,
            chapter_no=chapter_no,
            max_retries=2,
        )
    except LLMError as e:
        raise ExtractorError(f"LLM 抽取失败：{e}")

    # 补齐 chapter_no
    raw["chapter_no"] = chapter_no
    return post_process(raw, body_md, ctx)


# ---------------------------------------------------------------- 后处理
def post_process(raw: dict, body_md: str, ctx: ExtractorContext) -> dict:
    paragraphs = body_md.split("\n\n")
    warnings = raw.setdefault("extraction_warnings", [])

    # 1. evidence 回验
    for fact in raw.get("facts", []):
        ev = fact.get("evidence", "")
        if ev and not _evidence_exists(ev, paragraphs):
            fact["confidence"] = float(fact.get("confidence", 0.5)) * 0.5
            warnings.append({
                "kind": "evidence_not_found",
                "message": f"fact 的 evidence 在正文中找不到：{ev[:30]}...",
                "paragraph_idx": fact.get("paragraph_idx"),
            })

    # 2. paragraph_idx 校验
    max_idx = max(0, len(paragraphs) - 1)
    for block in ("facts", "character_states", "location_events",
                  "timeline_events", "scheme_evidence", "domain_details",
                  "anachronism_candidates"):
        for item in raw.get(block, []):
            idx = item.get("paragraph_idx")
            if idx is not None and not (0 <= idx <= max_idx):
                item["paragraph_idx"] = None
                warnings.append({
                    "kind": "invalid_paragraph_idx",
                    "message": f"paragraph_idx {idx} 越界",
                    "paragraph_idx": None,
                })

    # 3. character 校验
    known = {c["name"] for c in ctx.characters}
    known |= {a for c in ctx.characters for a in c.get("aliases", [])}
    for cs in raw.get("character_states", []):
        if cs.get("character") not in known:
            warnings.append({
                "kind": "unknown_character",
                "message": f"角色 {cs.get('character')} 不在已知名单里",
                "paragraph_idx": None,
            })

    # 4. scheme_id 校验
    known_schemes = {s["id"] for s in ctx.active_schemes}
    for se in raw.get("scheme_evidence", []):
        if se.get("scheme_id") not in known_schemes:
            warnings.append({
                "kind": "unknown_scheme",
                "message": f"scheme_id {se.get('scheme_id')} 不在本章 active_schemes 里",
                "paragraph_idx": None,
            })

    # 5. 综合 confidence
    confidences = [float(f.get("confidence", 0.5)) for f in raw.get("facts", [])]
    raw["confidence_overall"] = sum(confidences) / len(confidences) if confidences else 0.0

    # 6. 附上正文段落，供合同兑现校验用
    raw["_paragraphs"] = paragraphs
    raw["word_count"] = len(body_md.replace(" ", "").replace("\n", ""))

    # 7. 补 tension（从 summary 里取，或默认）
    if "summary" in raw and isinstance(raw["summary"], dict):
        raw["tension"] = raw["summary"].get("tension")
    if raw.get("tension") is None:
        raw["tension"] = 50

    return raw


def _evidence_exists(evidence: str, paragraphs: list[str]) -> bool:
    norm = _normalize(evidence)
    if not norm:
        return True
    return any(norm in _normalize(p) for p in paragraphs)


def _normalize(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").strip())


# ---------------------------------------------------------------- 带缓存
def extract_with_cache(chapter_no: int, body_md: str, contract: dict,
                       ctx: dict | ExtractorContext,
                       llm: LLMClient) -> dict:
    cache_key = hashlib.sha256(
        (body_md + json.dumps(contract, sort_keys=True, ensure_ascii=False)).encode("utf-8")
    ).hexdigest()
    cached = store.ExtractorCacheDAO.get(cache_key)
    if cached:
        # 缓存里没存 _paragraphs，重算
        cached["_paragraphs"] = body_md.split("\n\n")
        return cached
    result = extract(chapter_no, body_md, contract, ctx, llm)
    store.ExtractorCacheDAO.put(cache_key, chapter_no, result)
    return result