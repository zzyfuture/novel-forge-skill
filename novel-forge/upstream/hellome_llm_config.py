"""HelloMe 下发的技能 LLM 配置（无 PyYAML）。

优先读 {HERMES_HOME}/hellome_skills_llm_config.yml；没有或种类不匹配再回退 .env。
给页面用 list_providers / list_models（不含 api_key）；resolve 只给本机 upstream。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

CONFIG_FILENAME = "hellome_skills_llm_config.yml"
CIYUAN_SENTINEL = "ciyuan-relay"
BASE_PROD = "https://api.agentsyun.com/relay/v1"
BASE_SIT = "http://api.sit.agentsyun.com/relay/v1"

_HOME_ENVS = (
    "HERMES_HOME",
    "HUIZHI_HERMES_HOME",
    "HERMES_HOME_DIR",
    "HELLOME_HERMES_HOME",
)

_TEXT_OPS = frozenset({"chat", "responses"})
_IMAGE_OPS = frozenset({"image_generate", "image_edit"})
_VIDEO_OPS = frozenset({"video_generate"})
_IMAGE_TAGS = frozenset({"image-generation", "image"})
_VIDEO_TAGS = frozenset({"video-generation", "video"})


def hermes_home() -> Path:
    for name in _HOME_ENVS:
        raw = (os.environ.get(name) or "").strip()
        if raw:
            return Path(raw).expanduser()
    try:
        from hermes_constants import get_hermes_home  # type: ignore

        return Path(get_hermes_home())
    except Exception:
        if os.name == "nt" and (os.environ.get("LOCALAPPDATA") or "").strip():
            return Path(os.environ["LOCALAPPDATA"]) / "hz-hermes"
        return Path.home() / ".hz-hermes"


def _unquote(raw: str) -> Any:
    s = raw.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        inner = s[1:-1]
        return inner.replace("\\\\", "\\").replace("\\n", "\n").replace('\\"', '"')
    if s in ("true", "True"):
        return True
    if s in ("false", "False"):
        return False
    if s in ("null", "~", ""):
        return None
    if s == "[]":
        return []
    if s == "{}":
        return {}
    if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
        return int(s)
    return s


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def parse_yaml_subset(text: str) -> dict[str, Any]:
    lines = [
        ln.rstrip()
        for ln in text.splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    value, _ = _parse_map(lines, 0, 0)
    return value if isinstance(value, dict) else {}


def _parse_map(lines: list[str], start: int, min_indent: int) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    i = start
    while i < len(lines):
        line = lines[i]
        ind = _indent(line)
        if ind < min_indent:
            break
        stripped = line.strip()
        if stripped.startswith("- "):
            break
        if ind > min_indent and i != start:
            break
        key, sep, rest = stripped.partition(":")
        if not sep:
            i += 1
            continue
        key = key.strip()
        rest = rest.strip()
        if rest:
            result[key] = _unquote(rest)
            i += 1
            continue
        if i + 1 >= len(lines):
            result[key] = {}
            i += 1
            continue
        nxt = lines[i + 1]
        if nxt.strip().startswith("- "):
            child, i = _parse_list(lines, i + 1, _indent(nxt))
            result[key] = child
        else:
            child, i = _parse_map(lines, i + 1, _indent(nxt))
            result[key] = child
    return result, i


def _parse_list(lines: list[str], start: int, min_indent: int) -> tuple[list[Any], int]:
    items: list[Any] = []
    i = start
    while i < len(lines):
        line = lines[i]
        ind = _indent(line)
        if ind < min_indent:
            break
        stripped = line.strip()
        if not stripped.startswith("- "):
            break
        rest = stripped[2:].strip()
        if rest and ":" in rest:
            key, _, val = rest.partition(":")
            item: dict[str, Any] = {key.strip(): _unquote(val)}
            nested, i = _parse_map(lines, i + 1, min_indent + 2)
            item.update(nested)
            items.append(item)
        elif rest:
            items.append(_unquote(rest))
            i += 1
        else:
            nested, i = _parse_map(lines, i + 1, min_indent + 2)
            items.append(nested)
    return items, i


def _read_config() -> dict[str, Any] | None:
    path = hermes_home() / CONFIG_FILENAME
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    parsed = parse_yaml_subset(text)
    return parsed if parsed.get("accounts") is not None else parsed


def _env_file() -> dict[str, str]:
    out: dict[str, str] = {}
    path = hermes_home() / ".env"
    if not path.is_file():
        return out
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        return out
    return out


def env_relay() -> str:
    file_env = _env_file()
    explicit = (file_env.get("AGENTSYUN_API_BASE") or os.environ.get("AGENTSYUN_API_BASE") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    env_name = (file_env.get("HERMES_UPDATE_ENV") or os.environ.get("HERMES_UPDATE_ENV") or "").strip().lower()
    if env_name == "sit":
        return BASE_SIT
    return BASE_PROD


def env_key() -> str:
    file_env = _env_file()
    return (file_env.get("AGENTSYUN_API_KEY") or os.environ.get("AGENTSYUN_API_KEY") or "").strip()


def env_model() -> str:
    file_env = _env_file()
    return (file_env.get("AGENTSYUN_MODEL") or os.environ.get("AGENTSYUN_MODEL") or "").strip()


def resolve_ciyuan_base(base_url: str | None) -> str:
    raw = (base_url or "").strip()
    if not raw or raw == CIYUAN_SENTINEL:
        return env_relay()
    return raw.rstrip("/")


def join_url(base_url: str, invoke_path: str) -> str:
    base = resolve_ciyuan_base(base_url)
    path = (invoke_path or "").strip() or "/chat/completions"
    return base.rstrip("/") + "/" + path.lstrip("/")


def _ops(model: dict[str, Any]) -> list[str]:
    routes = model.get("routes") or []
    out: list[str] = []
    if isinstance(routes, list):
        for route in routes:
            if isinstance(route, dict):
                op = str(route.get("operation") or "").strip()
                if op:
                    out.append(op)
    return out


def _tags(model: dict[str, Any]) -> set[str]:
    tags = model.get("tags") or []
    if isinstance(tags, list):
        return {str(t).strip().lower() for t in tags}
    return set()


def model_matches_type(model: dict[str, Any], kind: str) -> bool:
    kind = (kind or "text").strip().lower()
    ops = set(_ops(model))
    tags = _tags(model)
    model_type = str(model.get("type") or model.get("model_type") or "").strip().lower()
    if kind == "text":
        if ops:
            return bool(ops & _TEXT_OPS)
        if tags:
            return bool(tags & {"text", "text-generation"})
        return model_type in {"text", "multimodal", ""}
    if kind == "image":
        if ops:
            return bool(ops & _IMAGE_OPS)
        return bool(tags & _IMAGE_TAGS) or model_type == "image"
    if kind == "video":
        if ops:
            return bool(ops & _VIDEO_OPS)
        return bool(tags & _VIDEO_TAGS) or model_type == "video"
    if ops:
        return kind in ops or kind in tags
    return model_type == kind or kind in tags


def _pick_route(model: dict[str, Any], kind: str) -> dict[str, Any] | None:
    routes = model.get("routes") if isinstance(model.get("routes"), list) else []
    typed = [r for r in routes if isinstance(r, dict)]
    if not typed:
        if (kind or "text") == "text":
            return {"operation": "chat", "protocol": "openai_chat", "invoke_path": "/chat/completions", "default": True}
        return None
    kind = (kind or "text").strip().lower()
    wanted = _TEXT_OPS if kind == "text" else _IMAGE_OPS if kind == "image" else _VIDEO_OPS if kind == "video" else {kind}
    matching = [r for r in typed if str(r.get("operation") or "") in wanted]
    pool = matching or typed
    for r in pool:
        if r.get("default") is True:
            if str(r.get("operation") or "") == "chat" or kind != "text":
                return r
    for r in pool:
        if str(r.get("operation") or "") == "chat":
            return r
    return pool[0]


def _account_rows(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, str) and raw.strip() in {"", "[]", "{}"}:
        return []
    if not isinstance(raw, list):
        return []
    return raw


def _accounts() -> list[dict[str, Any]]:
    cfg = _read_config()
    if not cfg:
        return []
    out = []
    for item in _account_rows(cfg.get("accounts")):
        if isinstance(item, dict) and item.get("enabled", True) is not False:
            out.append(item)
    out.sort(key=lambda a: int(a.get("account_id") or 0))
    return out


def list_providers() -> list[dict[str, Any]]:
    rows = []
    for acc in _accounts():
        rows.append(
            {
                "account_id": acc.get("account_id"),
                "account_name": acc.get("account_name") or "",
                "provider_code": acc.get("provider_code") or "",
                "provider_name": acc.get("provider_name") or "",
            }
        )
    return rows


def list_models(account_id: Any, kind: str) -> list[dict[str, Any]]:
    for acc in _accounts():
        if str(acc.get("account_id")) != str(account_id):
            continue
        models = acc.get("models") if isinstance(acc.get("models"), list) else []
        rows = []
        for model in models:
            if not isinstance(model, dict) or model.get("enabled", True) is False:
                continue
            if not model_matches_type(model, kind):
                continue
            rows.append(
                {
                    "id": model.get("id") or model.get("model_code") or "",
                    "name": model.get("name") or model.get("id") or "",
                    "type": model.get("type") or "",
                }
            )
        rows.sort(key=lambda m: str(m.get("id") or ""))
        return rows
    return []


def _resolved(acc: dict[str, Any], model: dict[str, Any], kind: str) -> dict[str, Any] | None:
    route = _pick_route(model, kind)
    if route is None:
        return None
    invoke = str(route.get("invoke_path") or route.get("invokePath") or "/chat/completions")
    protocol = str(route.get("protocol") or "openai_chat")
    base = resolve_ciyuan_base(str(acc.get("base_url") or ""))
    return {
        "account_id": acc.get("account_id"),
        "provider": acc.get("provider_code") or "",
        "base_url": base,
        "api_key": acc.get("api_key") or "",
        "model": model.get("id") or model.get("model_code") or "",
        "type": kind,
        "protocol": protocol,
        "invoke_path": invoke,
        "source": "yaml",
        "url": join_url(base, invoke),
    }


def resolve(account_id: Any, model_id: str, kind: str = "text") -> dict[str, Any] | None:
    for acc in _accounts():
        if str(acc.get("account_id")) != str(account_id):
            continue
        models = acc.get("models") if isinstance(acc.get("models"), list) else []
        for model in models:
            if not isinstance(model, dict):
                continue
            mid = str(model.get("id") or model.get("model_code") or "")
            if mid != str(model_id):
                continue
            if model.get("enabled", True) is False:
                return None
            return _resolved(acc, model, kind)
    return None


def resolve_default(kind: str = "text") -> dict[str, Any] | None:
    kind = (kind or "text").strip().lower()
    candidates: list[tuple[int, str, dict[str, Any], dict[str, Any]]] = []
    for acc in _accounts():
        models = acc.get("models") if isinstance(acc.get("models"), list) else []
        for model in models:
            if not isinstance(model, dict) or model.get("enabled", True) is False:
                continue
            if not model_matches_type(model, kind):
                continue
            mid = str(model.get("id") or "")
            candidates.append((int(acc.get("account_id") or 0), mid, acc, model))
    candidates.sort(
        key=lambda row: (0 if (row[2].get("provider_code") or "") == "ciyuan" else 1, row[0], row[1])
    )
    for _aid, _mid, acc, model in candidates:
        got = _resolved(acc, model, kind)
        if got:
            return got
    return env_fallback(kind)


def env_fallback(kind: str = "text") -> dict[str, Any] | None:
    key = env_key()
    if not key:
        return None
    kind = (kind or "text").strip().lower()
    if kind not in {"text", "image", "video"}:
        return None
    model = env_model()
    base = env_relay()
    return {
        "account_id": None,
        "provider": "ciyuan",
        "base_url": base,
        "api_key": key,
        "model": model,
        "type": kind,
        "protocol": "openai_chat",
        "invoke_path": "/chat/completions",
        "source": "env",
        "url": join_url(base, "/chat/completions"),
    }