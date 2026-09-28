#!/usr/bin/env python3
"""Arbiter：对每条 issue 给处置意见。"""
from __future__ import annotations

import json
from typing import Any

from ..llm import LLMClient, LLMError


ARBITER_SYSTEM = """你是「小说一致性引擎」的裁决器（Arbiter）。

# 你的唯一职责
对每条一致性问题，给出处置意见。

# 你可以给出的处置
- fix_text：问题在正文，需要修订正文
- amend_bible：问题在设定，需要修改设定卡（角色/规则/地点）
- need_human：无法自动裁决，需要人工介入

# 你的裁决原则
1. 优先 fix_text——大多数问题是正文写错
2. 只有正文明显正确、设定明显过时，才 amend_bible
3. blocker 级问题在无法判断时倾向 need_human
4. warning 级问题尽量 fix_text
5. info 级问题可以忽略（action 写 "ignore"）

# 输出格式
只输出 JSON。每条必须带 issue_code（与输入对应）+ action + reason。

# 输出 Schema
{
  "verdicts": [
    {
      "issue_code": "DEAD_ACTING",
      "issue_title": "...",
      "action": "fix_text | amend_bible | need_human | ignore",
      "reason": "一句话说明为什么",
      "target": "修改位置（段落号/角色名/设定项）"
    }
  ]
}
"""

ARBITER_SCHEMA = {
    "type": "object",
    "required": ["verdicts"],
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["issue_code", "action", "reason"],
                "properties": {
                    "issue_code": {"type": "string"},
                    "issue_title": {"type": "string"},
                    "action": {"type": "string",
                               "enum": ["fix_text", "amend_bible",
                                        "need_human", "ignore"]},
                    "reason": {"type": "string"},
                    "target": {"type": "string"},
                },
            },
        },
    },
}


class ArbiterAgent:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def arbitrate(self, chapter_no: int, issues: list[dict],
                  contract: dict, bible: dict) -> list[dict]:
        if not issues:
            return []

        user = f"""# 章节
第 {chapter_no} 章

# 合同
{json.dumps(contract, ensure_ascii=False, indent=2)[:2000]}

# 设定库
{json.dumps(bible, ensure_ascii=False, indent=2)[:3000]}

# 待裁决的问题（共 {len(issues)} 条）
{json.dumps(issues, ensure_ascii=False, indent=2)[:6000]}

---

请对每条问题给出处置意见。"""

        messages = [
            {"role": "system", "content": ARBITER_SYSTEM},
            {"role": "user", "content": user},
        ]
        try:
            raw = self.llm.call_with_schema(
                messages=messages, schema=ARBITER_SCHEMA,
                model_role="arbiter", temperature=0.2,
                chapter_no=chapter_no, max_retries=2,
            )
        except LLMError:
            # 裁决失败，默认全 need_human（保守）
            return [
                {"issue_code": it.get("code", ""),
                 "action": "need_human", "reason": "裁决器调用失败"}
                for it in issues
            ]

        # 对齐：缺失的 issue 补 need_human
        by_code = {v["issue_code"]: v for v in raw.get("verdicts", [])}
        out = []
        for it in issues:
            v = by_code.get(it.get("code"))
            if not v:
                v = {"issue_code": it.get("code"),
                     "action": "need_human",
                     "reason": "裁决器未覆盖此条，保守处理"}
            out.append(v)
        return out