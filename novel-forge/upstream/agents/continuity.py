#!/usr/bin/env python3
"""L4 语义审校 + 统一入口 run_all_layers。"""
from __future__ import annotations

import json
from typing import Any

from ..llm import LLMClient, LLMError
from ..consistency import rules, graph, contract_check


SEVERITY = {"blocker": 0, "warning": 1, "info": 2}


# ---------------------------------------------------------------- System
CONTINUITY_SYSTEM = """你是「小说一致性引擎」的语义审校器（Continuity）。
你只报告问题，不修改、不裁决。

# 你能报告的问题类型
- VOICE_DRIFT：角色声口/语气/用词偏离角色卡
- MOTIVE_JUMP：动机突变，缺少铺垫
- EMOTION_BREAK：情绪线断裂
- SETTING_SOFT_VIOLATION：设定被"软性"违背（不是硬规则能抓的）
- POV_LEAK：视角角色知道了它不可能知道的信息
- DIALOGUE_FLAT：对话是信息交换式，缺少潜台词
- DOMAIN_MISUSE：行业术语使用方式不符合从业者习惯
- ANACHRONISM：年代错误

# 你不做的事
- 不修改正文
- 不裁决冲突
- 不报告硬规则已经抓到的（DEAD_ACTING / TIME_REGRESS / LOCATION_CONFLICT 等）
- 不报告合同兑现问题（contract_check 已经抓了）

# 输出格式
只输出 JSON。每条问题必须带 evidence（原文片段 + 段落号）。

# 输出 Schema
{
  "issues": [
    {
      "severity": "blocker | warning | info",
      "code": "VOICE_DRIFT | ...",
      "title": "一句话",
      "detail": "解释",
      "evidence": [{"paragraph_idx": N, "text": "原文片段"}],
      "suggestion": "修改方向"
    }
  ]
}
"""

CONTINUITY_SCHEMA = {
    "type": "object",
    "required": ["issues"],
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["severity", "code", "title"],
                "properties": {
                    "severity": {"type": "string",
                                 "enum": ["blocker", "warning", "info"]},
                    "code": {"type": "string"},
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "paragraph_idx": {"type": "integer"},
                                "text": {"type": "string"},
                            },
                        },
                    },
                    "suggestion": {"type": "string"},
                },
            },
        },
    },
}


def build_continuity_user_prompt(
    chapter_no: int,
    contract: dict,
    extracted: dict,
    bible: dict,
    domain_ctx: dict,
    prev_summaries: list[str],
) -> str:
    # 精简 extracted：去掉 _paragraphs 之外的冗余
    ex_brief = {k: v for k, v in extracted.items() if k != "_paragraphs"}
    return f"""# 章节
第 {chapter_no} 章

# 合同
{json.dumps(contract, ensure_ascii=False, indent=2)[:2500]}

# Extractor 抽取结果
{json.dumps(ex_brief, ensure_ascii=False, indent=2)[:5000]}

# 设定库（相关子集）
{json.dumps(bible, ensure_ascii=False, indent=2)[:4000]}

# 行业约束（术语 + 流程 + 年代）
{json.dumps(domain_ctx, ensure_ascii=False, indent=2)[:3000]}

# 前情摘要（最近 3 章）
{chr(10).join(f'- 第{i}章：{s}' for i, s in enumerate(prev_summaries[-3:]) if s) or '（无）'}

---

请按 System Prompt 的 Schema 输出 JSON。"""


# ---------------------------------------------------------------- Agent
class ContinuityAgent:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def review(
        self,
        chapter_no: int,
        contract: dict,
        extracted: dict,
        bible: dict,
        domain_ctx: dict,
        prev_summaries: list[str],
    ) -> list[dict]:
        messages = [
            {"role": "system", "content": CONTINUITY_SYSTEM},
            {"role": "user", "content": build_continuity_user_prompt(
                chapter_no, contract, extracted, bible, domain_ctx, prev_summaries
            )},
        ]
        try:
            raw = self.llm.call_with_schema(
                messages=messages,
                schema=CONTINUITY_SCHEMA,
                model_role="continuity",
                temperature=0.2,
                chapter_no=chapter_no,
                max_retries=2,
            )
        except LLMError:
            # 语义审校失败不阻断流水线
            return []
        return _normalize_issues(raw.get("issues", []))


def _normalize_issues(issues: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for it in issues:
        key = (it.get("code"), it.get("title"))
        if key in seen:
            continue
        seen.add(key)
        sev = it.get("severity", "warning")
        if sev not in SEVERITY:
            sev = "warning"
        it["severity"] = sev
        if not isinstance(it.get("evidence"), list):
            it["evidence"] = []
        out.append(it)
    return out


# ---------------------------------------------------------------- 统一入口
def run_all_layers(
    chapter_no: int,
    contract: dict,
    extracted: dict,
    ctx: dict,
    db,
    llm: LLMClient | None = None,
) -> list[dict]:
    """四层审校。返回所有问题，按 severity 排序。"""
    all_issues: list[dict] = []

    # L1 硬规则
    all_issues += rules.check_hard_rules(extracted, ctx, db)

    # L2 关系图谱
    all_issues += graph.check_relationship_graph(db)
    all_issues += graph.check_location_hierarchy(db)
    all_issues += graph.check_timeline_monotonic(db)

    # L3 合同兑现
    all_issues += contract_check.check_contract_fulfillment(extracted, contract)

    # L4 语义审校
    if llm is not None:
        agent = ContinuityAgent(llm)
        all_issues += agent.review(
            chapter_no, contract, extracted,
            ctx.get("bible", {}), ctx.get("domain_ctx", {}),
            ctx.get("prev_summaries", []),
        )

    all_issues.sort(key=lambda i: SEVERITY.get(i["severity"], 2))
    return all_issues