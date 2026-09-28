#!/usr/bin/env python3
"""
LLM 调用封装。
- 底层走 hellome_llm_config（F.5 helper）
- 按 model_role 分别取账号/模型
- 支持 JSON schema 强约束 + 三层修复
- 失败重试，落 LLM 日志
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from . import store
from . import hellome_llm_config as llm_cfg

try:
    import urllib.request
    import urllib.error
except ImportError:
    pass


class LLMError(Exception):
    pass


# ---------------------------------------------------------------- 角色 → 配置
ROLE_FALLBACK = {
    "writer": "writer",
    "continuity": "continuity",
    "extractor": "extractor",
    "arbiter": "arbiter",
    "editor": "editor",
    "curator": "curator",
    "architect": "architect",
}
# 便宜的/贵的分组（用于 resolve_default 时的兜底）
CHEAP_ROLES = {"extractor", "curator"}
STRONG_ROLES = {"writer", "continuity", "arbiter", "editor", "architect"}


class LLMClient:
    def __init__(self, timeout: int = 300):
        self.timeout = timeout

    # ------------------------------------------------------------ 取配置
    def _resolve_for_role(self, role: str) -> dict:
        """
        优先级：
        1. setting: llm.<role>.{account_id, model_id}
        2. resolve_default("text")
        """
        s = store.SettingDAO.get(f"llm.{role}") or {}
        account_id = s.get("account_id")
        model_id = s.get("model_id")
        got = None
        if account_id is not None and model_id:
            got = llm_cfg.resolve(account_id, model_id, "text")
        if not got or not got.get("api_key"):
            got = llm_cfg.resolve_default("text")
        if not got or not got.get("api_key"):
            raise LLMError(
                "请到 HelloMe → 模型 API 添加账号并下发到本机，"
                "或在 Hermes 配置词元"
            )
        return got

    # ------------------------------------------------------------ 核心调用
    def _post(self, url: str, api_key: str, payload: dict,
              protocol: str = "openai_chat") -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            raise LLMError(f"HTTP {e.code}: {err_body}")
        except Exception as e:
            raise LLMError(f"{type(e).__name__}: {e}")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise LLMError(f"响应不是 JSON: {raw[:200]}")

    def _extract_text(self, data: dict, protocol: str) -> str:
        """兼容 chat 和 responses 两种协议。"""
        if protocol == "openai_responses":
            # OpenAI Responses API 结构
            try:
                parts = data["output"][0]["content"]
                texts = [p.get("text", "") for p in parts if p.get("type") == "output_text"]
                return "".join(texts)
            except (KeyError, IndexError, TypeError):
                pass
        # chat completions
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            pass
        # 兜底
        return json.dumps(data, ensure_ascii=False)

    # ------------------------------------------------------------ 对外 API
    def call(
        self,
        messages: list[dict],
        *,
        model_role: str = "writer",
        temperature: float = 0.7,
        max_tokens: int | None = None,
        chapter_no: int | None = None,
        max_retries: int = 2,
    ) -> str:
        got = self._resolve_for_role(model_role)
        protocol = got.get("protocol", "openai_chat")
        url = got["url"]
        api_key = got["api_key"]
        model = got.get("model") or ""

        if protocol == "openai_responses":
            payload: dict = {
                "model": model,
                "input": messages,
            }
        else:
            payload = {
                "model": model,
                "messages": messages,
            }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens:
            payload["max_tokens"] = max_tokens

        last_err: Exception | None = None
        for attempt in range(max_retries + 1):
            t0 = time.time()
            try:
                data = self._post(url, api_key, payload, protocol)
                text = self._extract_text(data, protocol)
                latency = int((time.time() - t0) * 1000)
                self._log(model_role, chapter_no, model, latency, ok=True)
                return text
            except LLMError as e:
                last_err = e
                latency = int((time.time() - t0) * 1000)
                self._log(model_role, chapter_no, model, latency, ok=False, error=str(e))
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
        raise LLMError(f"调用失败（{max_retries + 1} 次）：{last_err}")

    def call_with_schema(
        self,
        messages: list[dict],
        *,
        schema: dict,
        model_role: str = "extractor",
        temperature: float = 0.1,
        max_tokens: int | None = None,
        chapter_no: int | None = None,
        max_retries: int = 2,
    ) -> dict:
        """用 schema 约束输出，自动解析 + 修复 + 重试。"""
        # 把 schema 附加到 system
        schema_hint = (
            "\n\n# 输出 JSON Schema\n"
            "严格按以下 JSON Schema 输出，只输出 JSON 对象，"
            "不要任何解释文字，不要 Markdown 代码块包裹。\n"
            f"```json\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n```"
        )
        msgs = list(messages)
        if msgs and msgs[0]["role"] == "system":
            msgs[0] = {"role": "system", "content": msgs[0]["content"] + schema_hint}
        else:
            msgs.insert(0, {"role": "system", "content": schema_hint.strip()})

        last_err: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                text = self.call(
                    msgs,
                    model_role=model_role,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    chapter_no=chapter_no,
                    max_retries=0,   # 单次，重试由外层控制
                )
            except LLMError as e:
                last_err = e
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                raise LLMError(f"schema 调用失败（{max_retries + 1} 次）：{e}")

            try:
                return parse_json_lenient(text)
            except LLMError as e:
                last_err = e
                if attempt < max_retries:
                    # 把失败原因回灌
                    msgs = msgs + [
                        {"role": "assistant", "content": text[:500]},
                        {"role": "user", "content":
                            f"你上一次的输出不是合法 JSON（{e}）。"
                            "请只输出一个 JSON 对象，不要解释，不要代码块。"},
                    ]
                    continue
        raise LLMError(f"schema 输出解析失败（{max_retries + 1} 次）：{last_err}")

    # ------------------------------------------------------------ 日志
    def _log(self, agent, chapter_no, model, latency_ms, ok, error=None):
        try:
            store.LLMLogDAO.log(
                agent=agent, chapter_no=chapter_no, model=model,
                prompt_tokens=None, completion_tokens=None,
                latency_ms=latency_ms, ok=ok, error=error,
            )
        except Exception:
            pass


# ---------------------------------------------------------------- JSON 修复
_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_json_lenient(text: str) -> dict:
    """四层修复。"""
    if not text or not text.strip():
        raise LLMError("LLM 返回空")

    # 1. 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. 提取 ```json 块
    m = _FENCE_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 3. 找第一个 { 到最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        chunk = text[start:end + 1]
        try:
            return json.loads(chunk)
        except json.JSONDecodeError:
            chunk2 = _repair(chunk)
            try:
                return json.loads(chunk2)
            except json.JSONDecodeError:
                pass

    # 4. 全文修复
    repaired = _repair(text)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError as e:
        raise LLMError(f"无法解析 JSON: {e}；原文前 200 字符：{text[:200]}")


def _repair(s: str) -> str:
    """常见修复：中文引号、单引号、尾逗号、省略号。"""
    # 中文引号转英文
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    s = s.replace("\u2018", "'").replace("\u2019", "'")
    # 尾逗号
    s = re.sub(r",\s*([}\]])", r"\1", s)
    # 单引号 key/value（粗糙修复：成对替换）
    # 不动，避免误伤中文
    # 省略号
    s = s.replace("…", "...")
    return s