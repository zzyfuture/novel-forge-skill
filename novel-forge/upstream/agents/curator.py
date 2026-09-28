#!/usr/bin/env python3
"""Curator：验收后更新权威状态。唯一写 character_state/timeline 的地方。"""
from __future__ import annotations

import json
from typing import Any

from .. import store
from ..llm import LLMClient, LLMError


CURATOR_SYSTEM = """你是「小说一致性引擎」的台账管理员（Curator）。

# 你的唯一职责
从已验收的章节抽取结果里，整理出需要写回权威状态库的条目。

# 你要输出什么
1. character_updates：每个出场角色的最新状态
2. timeline_entries：本章发生的关键事件（按时间顺序）
3. foreshadow_updates：本章新埋的伏笔、本章回收的伏笔
4. scheme_updates：本章涉及 Scheme 的状态推进
5. domain_additions：本章出现的、不在 Domain KB 里的新行业细节

# 你绝对不做的事
- 不修改正文
- 不推断设定
- 只整理已验收章节里明确出现的内容

# 输出格式
只输出 JSON。不要任何解释。

# 输出 Schema
{
  "character_updates": [
    {
      "name": "角色名",
      "alive": true,
      "location": "地点名或null",
      "power_level": 55,
      "stance": "进攻",
      "inner_state": "一句话",
      "knowledge_added": ["..."],
      "relations_delta": {"江屹": {"trust": 60}},
      "arc_note": "一句话"
    }
  ],
  "timeline_entries": [
    {
      "story_time": "2010-09",
      "precision": "month",
      "event": "华晟项目立项",
      "actors": ["沈砺"]
    }
  ],
  "foreshadow_updates": {
    "planted": [
      {"summary": "...", "due_chapter": 9}
    ],
    "paid": [
      {"planted_chapter": 3, "summary_hint": "青铜罗盘"}
    ]
  },
  "scheme_updates": [
    {
      "scheme_id": "S2",
      "new_status": "armed",
      "evidence_text": "第4章暗版报价只告诉陆舟",
      "chapter_no": 4
    }
  ],
  "domain_additions": [
    {"category": "term", "term": "...", "definition": "..."}
  ]
}
"""

CURATOR_SCHEMA = {
    "type": "object",
    "properties": {
        "character_updates": {"type": "array", "items": {"type": "object"}},
        "timeline_entries": {"type": "array", "items": {"type": "object"}},
        "foreshadow_updates": {"type": "object"},
        "scheme_updates": {"type": "array", "items": {"type": "object"}},
        "domain_additions": {"type": "array", "items": {"type": "object"}},
    },
}


class CuratorAgent:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def update(
        self,
        chapter_no: int,
        extracted: dict,
        contract: dict,
        db,
    ) -> None:
        # 先走确定性路径（不依赖 LLM）
        self._write_character_states(chapter_no, extracted, db)
        self._write_timeline(chapter_no, extracted, db)
        self._write_scheme_evidence(chapter_no, extracted, db)
        self._absorb_domain_details(extracted)

        # LLM 补充：新伏笔 + 新术语
        self._llm_supplement(chapter_no, extracted, contract)

    # ------------------------------------------------------------ 确定性路径
    def _write_character_states(self, chapter_no, extracted, db):
        for cs in extracted.get("character_states", []):
            name = cs.get("character")
            if not name:
                continue
            ch = store.CharacterDAO.by_name(name)
            if not ch:
                # 新角色：建卡
                cid = store.CharacterDAO.upsert(name, role="auto")
            else:
                cid = ch["id"]

            # 地点
            loc_id = None
            loc_name = cs.get("location")
            if loc_name:
                loc_id = store.LocationDAO.upsert(loc_name)

            # 关系增量合并
            prev = store.CharacterStateDAO.at_chapter(cid, chapter_no) or {}
            rels = dict(prev.get("relations") or {})
            for rc in cs.get("relationship_changes", []):
                tgt = rc.get("target")
                if not tgt:
                    continue
                rels.setdefault(tgt, {})
                if rc.get("to") is not None:
                    rels[tgt][rc.get("dimension", "trust")] = rc["to"]
                elif rc.get("direction") == "down":
                    cur = rels[tgt].get(rc.get("dimension", "trust"), 50)
                    rels[tgt][rc.get("dimension", "trust")] = max(0, cur - 10)
                elif rc.get("direction") == "up":
                    cur = rels[tgt].get(rc.get("dimension", "trust"), 50)
                    rels[tgt][rc.get("dimension", "trust")] = min(100, cur + 10)

            # 知识合并
            kn = list(prev.get("knowledge") or [])
            for k in cs.get("knowledge_gained", []) or []:
                if k not in kn:
                    kn.append(k)

            store.CharacterStateDAO.upsert(
                cid, chapter_no,
                alive=1 if cs.get("alive", True) else 0,
                location_id=loc_id,
                power_level=cs.get("power_level"),
                stance=cs.get("stance"),
                inner_state=cs.get("inner_state"),
                knowledge=kn,
                relations=rels,
                arc_note=cs.get("arc_note"),
            )

    def _write_timeline(self, chapter_no, extracted, db):
        for ev in extracted.get("timeline_events", []):
            db.timeline_add(
                chapter_no=chapter_no,
                summary=ev.get("event", ""),
                story_time=ev.get("story_time"),
                precision=ev.get("story_time_precision", "vague"),
                actors=ev.get("actors", []) or [],
            )

    def _write_scheme_evidence(self, chapter_no, extracted, db):
        for se in extracted.get("scheme_evidence", []):
            sid = se.get("scheme_id")
            if not sid:
                continue
            s = store.SchemeDAO.get(sid)
            if not s:
                continue
            ev = s.get("evidence") or []
            for m in se.get("matched_evidence", []):
                ev.append({
                    "chapter": chapter_no,
                    "kind": se.get("contract_expectation", ""),
                    "text": m.get("text", ""),
                })
            # 状态推进：如果本章是 plant/arm/trigger/resolve 之一
            expectation = se.get("contract_expectation")
            new_status = s.get("status", "planted")
            if expectation == "plant":
                new_status = "planted"
            elif expectation == "arm":
                new_status = "armed"
            elif expectation == "trigger":
                new_status = "triggered"
            elif expectation == "resolve":
                new_status = "resolved"
            payload = {k: v for k, v in s.items() if k != "id"}
            payload["evidence"] = ev
            payload["status"] = new_status
            store.SchemeDAO.upsert(sid, **payload)

    def _absorb_domain_details(self, extracted):
        for d in extracted.get("domain_details", []):
            if d.get("new_or_known") not in ("new", "possible_new"):
                continue
            if d.get("category") == "term":
                store.DomainDAO.add_term(
                    term=d.get("text", "")[:80],
                    category="自动补充",
                    definition=d.get("context", "")[:300],
                    source_chapters=[],
                )
            elif d.get("category") == "era":
                year = d.get("era_year")
                if year:
                    store.DomainDAO.add_era(
                        year=int(year),
                        category="自动补充",
                        fact=d.get("context", "")[:300],
                        forbidden=[],
                        source_chapters=[],
                    )

    # ------------------------------------------------------------ LLM 补充
    def _llm_supplement(self, chapter_no, extracted, contract):
        # 精简输入
        payload = {
            "chapter_no": chapter_no,
            "summary": extracted.get("summary", {}),
            "character_states": extracted.get("character_states", []),
            "scheme_evidence": [
                {"scheme_id": se.get("scheme_id"),
                 "contract_expectation": se.get("contract_expectation"),
                 "matched": [m.get("text") for m in se.get("matched_evidence", [])]}
                for se in extracted.get("scheme_evidence", [])
            ],
            "domain_details": extracted.get("domain_details", []),
        }
        user = (
            f"# 章节 {chapter_no}\n\n"
            f"# 抽取结果\n{json.dumps(payload, ensure_ascii=False, indent=2)[:6000]}\n\n"
            "请输出需要写回权威状态库的条目。"
        )
        messages = [
            {"role": "system", "content": CURATOR_SYSTEM},
            {"role": "user", "content": user},
        ]
        try:
            raw = self.llm.call_with_schema(
                messages=messages, schema=CURATOR_SCHEMA,
                model_role="curator", temperature=0.2,
                chapter_no=chapter_no, max_retries=2,
            )
        except LLMError:
            return

        # 新伏笔
        fu = raw.get("foreshadow_updates", {}) or {}
        for p in fu.get("planted", []) or []:
            store.ForeshadowDAO.add(
                planted_chapter=chapter_no,
                summary=p.get("summary", "")[:200],
                due_chapter=p.get("due_chapter"),
            )
        for paid in fu.get("paid", []) or []:
            # 找最匹配的未回收伏笔
            open_fs = store.ForeshadowDAO.open_before(chapter_no + 1)
            hint = paid.get("summary_hint", "")
            for f in open_fs:
                if hint and hint in f.get("summary", ""):
                    store.ForeshadowDAO.mark_paid(f["id"], chapter_no)
                    break