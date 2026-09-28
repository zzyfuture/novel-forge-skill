#!/usr/bin/env python3
"""L2 关系图谱：确定性校验。"""
from __future__ import annotations


def _issue(severity, code, title, detail="", evidence=None, suggestion=""):
    return {"severity": severity, "code": code, "title": title,
            "detail": detail, "evidence": evidence or [],
            "suggestion": suggestion}


def check_relationship_graph(db) -> list[dict]:
    """关系对称性：A 是 B 的父 → B 是 A 的子。"""
    issues = []
    chars = db.characters_list()
    name_to_rels = {c["name"]: (c.get("relations") or {}) for c in chars}
    symmetric_pairs = [
        ("parent", "child"),
        ("superior", "subordinate"),
        ("spouse", "spouse"),
        ("sibling", "sibling"),
    ]
    for src, rels in name_to_rels.items():
        for dst, dims in rels.items():
            if dst not in name_to_rels:
                continue
            rev = name_to_rels[dst].get(src, {})
            if not isinstance(dims, dict) or not isinstance(rev, dict):
                continue
            for a, b in symmetric_pairs:
                if a in dims and b not in rev:
                    issues.append(_issue(
                        "warning", "RELATION_ASYMMETRY",
                        f"{src} → {dst} 是 {a}，但 {dst} → {src} 没有 {b}",
                        suggestion="补齐反向关系",
                    ))
    return issues


def check_location_hierarchy(db) -> list[dict]:
    """地点层级：子地点必须有父地点。"""
    issues = []
    locs = db.locations_list()
    for l in locs:
        traits = l.get("traits") or []
        # 简单约定：region 为空的顶级地点必须有 region
        # 这个规则先留空，按实际使用再补
    return issues


def check_timeline_monotonic(db) -> list[dict]:
    """全书时间线单调。"""
    issues = []
    # 由 timeline_event 表逐章检查
    # 这里不查 db，交由 orchestrator 单独处理
    return issues