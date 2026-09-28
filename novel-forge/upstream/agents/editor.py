#!/usr/bin/env python3
"""Editor：按裁决修订正文，只改被点名处。"""
from __future__ import annotations

import json
from typing import Any

from ..llm import LLMClient, LLMError
from .base import strip_fences


EDITOR_SYSTEM = """你是「小说创作引擎」的编辑（Editor）。

# 你的唯一职责
按给定的「问题清单 + 裁决意见」修订章节正文。

# 你必须遵守的纪律
1. 只改被点名的地方——其余逐字保留
2. 不改剧情、不改人物、不改设定
3. 不改文风、不改语调、不改节奏
4. 修改要最小化：能改一句话就不改一段，能改一个词就不改一句
5. 修订后正文的段落结构应尽量与原正文保持一致

# 你绝对不能做的事
- 不添加新场景
- 不删减场景
- 不重新组织段落
- 不"顺手"润色未被点名的段落
- 不在正文末尾添加任何说明、注释、致谢

# 输出格式
只输出修订后的完整正文 Markdown。
不要任何前言、后记、解释。
不要用代码块包裹。
"""


class EditorAgent:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def revise(
        self,
        chapter_no: int,
        body: str,
        issues: list[dict],
        verdicts: list[dict],
        contract: dict,
    ) -> str:
        # 只处理 fix_text 的
        fix_items = []
        by_code = {v.get("issue_code"): v for v in verdicts}
        for it in issues:
            v = by_code.get(it.get("code"))
            if not v:
                continue
            if v.get("action") != "fix_text":
                continue
            fix_items.append({
                "code": it.get("code"),
                "title": it.get("title"),
                "detail": it.get("detail", ""),
                "evidence": it.get("evidence", []),
                "paragraph_idx": [
                    e["paragraph_idx"]
                    for e in (it.get("evidence") or [])
                    if isinstance(e, dict) and e.get("paragraph_idx") is not None
                ],
                "suggestion": it.get("suggestion", ""),
                "reason": v.get("reason", ""),
                "target": v.get("target", ""),
            })

        if not fix_items:
            return body

        user = f"""# 章节
第 {chapter_no} 章

# 合同摘要
标题：{contract.get('title', '')}
POV：{contract.get('pov_character_id', '')}
调性：{contract.get('tone', '')[:200]}

# 需要修订的问题（共 {len(fix_items)} 条）
{json.dumps(fix_items, ensure_ascii=False, indent=2)[:5000]}

# 定位规则
每条问题都附了 paragraph_idx（段落号，从 0 开始，以空行分段）。
修订时**先定位到这些段落**，只改这几段的对应句子。
如果 evidence 里的原文片段找不到，跳过该条，不要重写其他段落。

# 当前正文
{body}

---

请按 System Prompt 输出修订后的完整正文。"""
        max_out = max(
            len(body) * 2,
            contract.get("word_target", 3500) * 3,
        )
        messages = [
            {"role": "system", "content": EDITOR_SYSTEM},
            {"role": "user", "content": user},
        ]
        try:
            revised = self.llm.call(
                messages=messages,
                model_role="editor",
                temperature=0.3,
                max_tokens=max_out,
                chapter_no=chapter_no,
                max_retries=2,
            )
        except LLMError:
            # 修订失败返回原稿
            return body
        cleaned = strip_fences(revised) or body
        # 修订后短于原文 50% = 异常，返回原稿
        if len(cleaned) < len(body) * 0.5:
            return body
        return cleaned