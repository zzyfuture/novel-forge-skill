#!/usr/bin/env python3
"""L3 合同兑现：结构化比对，零 LLM。"""
from __future__ import annotations

import re


def _issue(severity, code, title, detail="", evidence=None, suggestion=""):
    return {"severity": severity, "code": code, "title": title,
            "detail": detail, "evidence": evidence or [],
            "suggestion": suggestion}


def check_contract_fulfillment(extracted: dict, contract: dict) -> list[dict]:
    issues = []

    # 1. Scheme 证据是否齐
    for se in extracted.get("scheme_evidence", []):
        if se.get("missing"):
            issues.append(_issue(
                "blocker", "SCHEME_EVIDENCE_MISSING",
                f"合同要求 {se.get('scheme_id')} {se.get('contract_expectation')}，正文未出现",
                detail=se.get("miss_reason") or "",
                suggestion="补写对应证据，或修改合同",
            ))

    # 2. must_advance 是否落实（降级为 info，extractor 抽不准时不误导）
    for ma in contract.get("must_advance", []):
        if not _any_fact_covers(ma, extracted.get("facts", [])):
            issues.append(_issue(
                "info", "CONTRACT_MISS",
                f"合同要求推进：{ma}，正文未找到对应事实（可能是抽取遗漏）",
                suggestion="人工确认，或修改合同",
            ))

    # 3. 节奏
    tension = extracted.get("tension")
    expected = contract.get("tension_expected")
    if tension is not None and expected is not None:
        if abs(int(tension) - int(expected)) > 15:
            issues.append(_issue(
                "warning", "PACING_DRIFT",
                f"本章张力 {tension} 偏离预期 {expected} 超过 15",
                suggestion="重写高潮段，或调低/调高冲突强度",
            ))

    # 4. 篇幅
    word_count = extracted.get("word_count")
    target = contract.get("word_target")
    if word_count and target:
        ratio = word_count / target
        if ratio < 0.8:
            issues.append(_issue(
                "warning", "LENGTH_SHORT",
                f"本章 {word_count} 字，目标 {target} 字，完成度 {ratio:.0%}",
                suggestion="补写场景或扩写对话",
            ))
        elif ratio > 1.3:
            issues.append(_issue(
                "info", "LENGTH_LONG",
                f"本章 {word_count} 字，目标 {target} 字，超出 {ratio:.0%}",
                suggestion="考虑拆分或压缩",
            ))

    return issues


def _any_fact_covers(ma: str, facts: list[dict]) -> bool:
    tokens = [t for t in re.split(r"[，。、；\s]+", ma) if len(t) >= 2]
    if not tokens:
        return True
    for f in facts:
        blob = f"{f.get('subject','')}{f.get('predicate','')}{f.get('object','')}"
        if any(t in blob for t in tokens):
            return True
    return False