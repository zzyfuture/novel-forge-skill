#!/usr/bin/env python3
"""agents 公共工具。"""
from __future__ import annotations

from typing import Any

from ..llm import LLMClient, LLMError, parse_json_lenient


__all__ = ["LLMClient", "LLMError", "parse_json_lenient", "strip_fences"]


def strip_fences(text: str) -> str:
    """去掉 markdown 代码块包裹。"""
    import re
    t = (text or "").strip()
    m = re.match(r"^```(?:markdown|md|json|text)?\s*\n(.*?)\n```$", t, re.DOTALL)
    return m.group(1).strip() if m else t