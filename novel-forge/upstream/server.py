#!/usr/bin/env python3
"""
novel-forge upstream HTTP 服务。

- 只听 HELLOME_UPSTREAM_PORT（别名 PORT），绑 127.0.0.1
- env 为空或非法 → 启动失败（非 0 退出）
- 数据只写 HELLOME_SKILL_DATA_DIR
- 保留路径不要占用：/api/health /api/meta /api/presence* /api/lifecycle/flush
- 业务路由全部带 /api 前缀（adapter 原样转发，不剥前缀）
- 禁止打印 *_READY url= 行
- 长任务立刻返回 task_id，前端轮询 /api/jobs/<id>
"""
from __future__ import annotations

import json
import os
import re
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import mimetypes

# ---------------------------------------------------------------- 路径准备
HERE = Path(__file__).resolve().parent
PKG_ROOT = HERE.parent
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

# ---------------------------------------------------------------- 环境校验（先于 import store）
def _port() -> int:
    raw = (os.environ.get("HELLOME_UPSTREAM_PORT")
           or os.environ.get("PORT") or "").strip()
    if not raw:
        raise SystemExit("SKILL_BOOT_ERROR HELLOME_UPSTREAM_PORT is required")
    try:
        port = int(raw)
    except ValueError:
        raise SystemExit("SKILL_BOOT_ERROR HELLOME_UPSTREAM_PORT is required")
    if port < 1024 or port > 65535:
        raise SystemExit("SKILL_BOOT_ERROR HELLOME_UPSTREAM_PORT is required")
    return port


def _data_dir() -> Path:
    raw = (os.environ.get("HELLOME_SKILL_DATA_DIR") or "").strip()
    if not raw:
        raise SystemExit("SKILL_BOOT_ERROR HELLOME_SKILL_DATA_DIR is required")
    p = Path(raw)
    p.mkdir(parents=True, exist_ok=True)
    return p


PORT = _port()
DATA_DIR = _data_dir()

# ---- 开发模式（本地调试用：让 upstream 顺带供 web/，省去再开一个 http.server）
DEV_STATIC = bool(os.environ.get("NOVEL_FORGE_DEV_STATIC"))
DEV_WEB_DIR = Path(__file__).resolve().parent.parent / "web"
if DEV_STATIC:
    print(f"[novel-forge] DEV_STATIC enabled, serving {DEV_WEB_DIR}", flush=True)

# ---------------------------------------------------------------- 业务 import
from upstream import store as S                          # noqa: E402
from upstream.llm import LLMClient, LLMError             # noqa: E402
from upstream import orchestrator as ORCH                # noqa: E402


# ---------------------------------------------------------------- 启动初始化
def _bootstrap():
    counts = S.bootstrap_from_seed()
    print(f"[novel-forge] bootstrap: {counts}", flush=True)


LLM = LLMClient(timeout=300)


# ---------------------------------------------------------------- 工具
def _json_response(handler, status: int, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _text_response(handler, status: int, text: str, ctype: str = "text/plain; charset=utf-8"):
    body = text.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_json_body(handler) -> dict:
    length = int(handler.headers.get("Content-Length") or "0")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return {}


def _query(handler) -> dict:
    return {k: v[0] if len(v) == 1 else v
            for k, v in parse_qs(urlparse(handler.path).query).items()}


# ================================================================ 路由表
ROUTES: list[tuple[str, re.Pattern, str]] = [
    ("GET",    re.compile(r"^/$"),                                    "index"),
    ("GET",    re.compile(r"^/health$"),                              "health"),
    ("GET",    re.compile(r"^/api/hello$"),                           "hello"),

    ("GET",    re.compile(r"^/api/project$"),                         "project_get"),
    ("PUT",    re.compile(r"^/api/project$"),                         "project_put"),

    ("GET",    re.compile(r"^/api/bible$"),                           "bible_get"),
    ("PUT",    re.compile(r"^/api/bible$"),                           "bible_put"),

    ("GET",    re.compile(r"^/api/outline$"),                         "outline_list"),

    ("GET",    re.compile(r"^/api/chapters$"),                        "chapter_list"),
    ("GET",    re.compile(r"^/api/chapters/(\d+)$"),                  "chapter_get"),
    ("PUT",    re.compile(r"^/api/chapters/(\d+)$"),                  "chapter_save"),
    ("GET",    re.compile(r"^/api/chapters/(\d+)/contract$"),         "contract_get"),
    ("POST",   re.compile(r"^/api/chapters/(\d+)/contract$"),         "contract_save"),
    ("POST",   re.compile(r"^/api/chapters/(\d+)/contract/freeze$"),  "contract_freeze"),
    ("POST",   re.compile(r"^/api/chapters/(\d+)/contract/unfreeze$"),"contract_unfreeze"),
    ("POST",   re.compile(r"^/api/chapters/(\d+)/write$"),            "chapter_write"),
    ("POST",   re.compile(r"^/api/chapters/(\d+)/recheck$"),          "chapter_recheck"),
    ("POST",   re.compile(r"^/api/chapters/(\d+)/accept$"),           "chapter_accept"),
    ("GET",    re.compile(r"^/api/chapters/(\d+)/issues$"),           "chapter_issues"),
    ("POST",   re.compile(r"^/api/chapters/(\d+)/storyboard$"),       "storyboard_generate"),
    ("GET",    re.compile(r"^/api/chapters/(\d+)/storyboard$"),       "storyboard_get"),
    ("POST",   re.compile(r"^/api/chapters/(\d+)/storyboard/(\d+)/retry$"), "storyboard_retry"),
    ("GET",    re.compile(r"^/api/storyboards/(\d+)/shot/(\d+)\.png$"), "storyboard_image"),

    ("GET",    re.compile(r"^/api/jobs/([A-Za-z0-9_-]+)$"),           "job_get"),

    ("POST",   re.compile(r"^/api/issues/(\d+)/resolve$"),            "issue_resolve"),

    ("GET",    re.compile(r"^/api/schemes$"),                         "schemes_list"),
    ("GET",    re.compile(r"^/api/domain$"),                          "domain_get"),

    ("GET",    re.compile(r"^/api/llm/options$"),                     "llm_options"),
    ("GET",    re.compile(r"^/api/llm/models$"),                      "llm_models"),
    ("PUT",    re.compile(r"^/api/settings/llm$"),                    "settings_llm_put"),
    ("GET",    re.compile(r"^/api/settings/llm$"),                    "settings_llm_get"),

    ("POST",   re.compile(r"^/api/export$"),                          "export"),
]


# ================================================================ Handlers
def h_index(handler, m, q):
    # 开发模式下伺服 web/index.html
    if DEV_STATIC:
        if handler._serve_static("/index.html"):
            return
    _text_response(handler, 200, "ok")

def h_health(handler, m, q):
    _text_response(handler, 200, "ok")


def h_hello(handler, m, q):
    _json_response(handler, 200, {"ok": True, "message": "hello from novel-forge"})


def h_project_get(handler, m, q):
    _json_response(handler, 200, {"ok": True, "project": S.ProjectDAO.get()})


def h_project_put(handler, m, q):
    body = _read_json_body(handler)
    S.ProjectDAO.update(**body)
    _json_response(handler, 200, {"ok": True, "project": S.ProjectDAO.get()})


def h_bible_get(handler, m, q):
    _json_response(handler, 200, {
        "ok": True,
        "rules": S.WorldRuleDAO.list_all(),
        "characters": S.CharacterDAO.list_all(),
        "locations": S.LocationDAO.list_all(),
    })


def h_bible_put(handler, m, q):
    body = _read_json_body(handler)
    with S.tx() as c:
        c.execute("DELETE FROM world_rule")
        c.execute("DELETE FROM character")
        c.execute("DELETE FROM location")
    for r in body.get("rules", []):
        S.WorldRuleDAO.add(
            category=r.get("category", "规则"),
            statement=r.get("statement", ""),
            hard=1 if r.get("hard", True) else 0,
        )
    for ch in body.get("characters", []):
        S.CharacterDAO.upsert(
            ch["name"],
            aliases=ch.get("aliases", []),
            role=ch.get("role"),
            voice=ch.get("voice"),
            traits=ch.get("traits", []),
            relations=ch.get("relations", {}),
            abilities=ch.get("abilities", []),
            status=ch.get("status", "alive"),
        )
    for lc in body.get("locations", []):
        S.LocationDAO.upsert(
            lc["name"],
            aliases=lc.get("aliases", []),
            region=lc.get("region"),
            traits=lc.get("traits", []),
        )
    _json_response(handler, 200, {"ok": True})


def h_outline_list(handler, m, q):
    _json_response(handler, 200, {"ok": True, "outline": S.OutlineDAO.list_all()})


def h_chapter_list(handler, m, q):
    # 以 36 章为骨架，融合 chapter 表状态 + outline 标题
    chapters = {c["chapter_no"]: c for c in S.ChapterDAO.list_all()}
    outline = {o["chapter_no"]: o for o in S.OutlineDAO.list_all()}
    merged = []
    for n in range(1, 37):
        ch = chapters.get(n, {})
        ol = outline.get(n, {})
        merged.append({
            "chapter_no": n,
            "title": (ch.get("title")
                      or ol.get("notes")
                      or (ol.get("intent", "") or "")[:20]
                      or ""),
            "word_count": ch.get("word_count", 0),
            "status": ch.get("status", "pending"),
            "tension": ch.get("tension"),
            "accepted_at": ch.get("accepted_at"),
            "updated_at": ch.get("updated_at"),
        })
    _json_response(handler, 200, {"ok": True, "chapters": merged})


def h_chapter_get(handler, m, q):
    n = int(m.group(1))
    chapter = S.ChapterDAO.get(n) or {"chapter_no": n}
    # title 兜底：从 outline 拿
    if not chapter.get("title"):
        ol = S.OutlineDAO.get(n)
        if ol and ol.get("notes"):
            chapter["title"] = ol["notes"]
    contract = S.ContractDAO.get_frozen(n) or S.ContractDAO.get_draft(n)
    _json_response(handler, 200, {
        "ok": True,
        "chapter": chapter,
        "contract": contract,
    })


def h_chapter_save(handler, m, q):
    n = int(m.group(1))
    body_data = _read_json_body(handler)
    body_md = body_data.get("body_md")
    if body_md is None:
        _json_response(handler, 200, {"ok": False, "error": "body_md required"})
        return
    existing = S.ChapterDAO.get(n)
    if not existing:
        _json_response(handler, 200, {"ok": False, "error": "chapter not found"})
        return
    if existing.get("status") == "accepted":
        _json_response(handler, 200, {
            "ok": False, "error": "已验收的章节不可修改，请先取消验收",
        })
        return
    S.ChapterDAO.save(
        n, body_md, contract_id=existing.get("contract_id"),
        title=existing.get("title"),
        summary=existing.get("summary"),
        tension=existing.get("tension"),
    )
    _json_response(handler, 200, {"ok": True, "word_count": len(body_md.replace(" ", "").replace("\n", ""))})


def h_contract_get(handler, m, q):
    n = int(m.group(1))
    frozen = S.ContractDAO.get_frozen(n)
    draft = S.ContractDAO.get_draft(n)
    _json_response(handler, 200, {"ok": True, "frozen": frozen, "draft": draft})


def h_contract_save(handler, m, q):
    n = int(m.group(1))
    body = _read_json_body(handler)
    cid = S.ContractDAO.save_draft(n, body)
    _json_response(handler, 200, {"ok": True, "contract_id": cid})


def h_contract_unfreeze(handler, m, q):
    n = int(m.group(1))
    S.ContractDAO.unfreeze(n)
    _json_response(handler, 200, {"ok": True})


def h_contract_freeze(handler, m, q):
    n = int(m.group(1))
    body = _read_json_body(handler)
    version = int(body.get("version") or 1)
    content_hash = str(body.get("hash") or "")
    S.ContractDAO.freeze(n, version, content_hash)
    _json_response(handler, 200, {"ok": True})


def h_chapter_write(handler, m, q):
    n = int(m.group(1))
    try:
        job_id = ORCH.submit_write_chapter(n, LLM)
    except ORCH.OrchestratorError as e:
        _json_response(handler, 200, {"ok": False, "error": str(e)})
        return
    _json_response(handler, 200, {"ok": True, "task_id": job_id})


def h_chapter_recheck(handler, m, q):
    n = int(m.group(1))
    try:
        job_id = ORCH.submit_recheck_chapter(n, LLM)
    except ORCH.OrchestratorError as e:
        _json_response(handler, 200, {"ok": False, "error": str(e)})
        return
    _json_response(handler, 200, {"ok": True, "task_id": job_id})


def h_chapter_accept(handler, m, q):
    n = int(m.group(1))
    try:
        job_id = ORCH.submit_accept_chapter(n, LLM)
    except ORCH.OrchestratorError as e:
        _json_response(handler, 200, {"ok": False, "error": str(e)})
        return
    _json_response(handler, 200, {"ok": True, "task_id": job_id})


def h_chapter_issues(handler, m, q):
    n = int(m.group(1))
    _json_response(handler, 200, {
        "ok": True,
        "issues": S.IssueDAO.list_by_chapter(n),
    })

def h_storyboard_generate(handler, m, q):
    n = int(m.group(1))
    body = _read_json_body(handler)
    shot_count = int(body.get("shot_count") or 8)
    force_rerun = bool(body.get("force_rerun") or False)
    # 限制范围，避免用户瞎填
    shot_count = max(4, min(20, shot_count))
    try:
        job_id = ORCH.submit_storyboard_chapter(
            n, LLM, force_rerun=force_rerun, shot_count=shot_count,
        )
    except ORCH.OrchestratorError as e:
        _json_response(handler, 200, {"ok": False, "error": str(e)})
        return
    _json_response(handler, 200, {"ok": True, "task_id": job_id})

def h_storyboard_get(handler, m, q):
    n = int(m.group(1))
    sb = S.StoryboardDAO.get(n)
    shots = S.StoryboardShotDAO.list_by_chapter(n)
    # 拼出前端可访问的 image_url
    for s in shots:
        if s.get("image_path") and s.get("status") == "done":
            s["image_url"] = f"/api/storyboards/{n}/shot/{s['shot_id']}.png"
        else:
            s["image_url"] = None
    _json_response(handler, 200, {
        "ok": True,
        "storyboard": sb,
        "shots": shots,
    })


def h_storyboard_retry(handler, m, q):
    n = int(m.group(1))
    shot_id = int(m.group(2))
    shot = S.StoryboardShotDAO.get(n, shot_id)
    if not shot:
        _json_response(handler, 200, {"ok": False, "error": "镜头不存在"})
        return

    # 同步重画一张（单张很快，不用异步）
    from upstream.agents.storyboard_artist import StoryboardArtist
    from upstream import orchestrator as _O

    bible_chars = {c["name"]: c for c in S.CharacterDAO.list_all()}
    bible_locs = {l["name"]: l for l in S.LocationDAO.list_all()}
    bible_props = {p["name"]: p for p in S.PropDAO.list_all()}
    style = _O._load_storyboard_style()

    artist = StoryboardArtist()
    try:
        img_path, prompt_used = artist.render_shot(
            chapter_no=n,
            shot=shot,
            characters_bible=bible_chars,
            locations_bible=bible_locs,
            props_bible=bible_props,
            style=style,
        )
        S.StoryboardShotDAO.upsert(
            n, shot_id,
            image_path=img_path,
            prompt_used=prompt_used,
            status="done",
            error=None,
        )
        _json_response(handler, 200, {
            "ok": True,
            "image_url": f"/api/storyboards/{n}/shot/{shot_id}.png",
        })
    except Exception as e:
        S.StoryboardShotDAO.upsert(
            n, shot_id, status="failed", error=str(e)[:500],
        )
        _json_response(handler, 200, {"ok": False, "error": str(e)[:500]})


def h_storyboard_image(handler, m, q):
    n = int(m.group(1))
    shot_id = int(m.group(2))
    shot = S.StoryboardShotDAO.get(n, shot_id)
    if not shot or not shot.get("image_path"):
        _json_response(handler, 404, {"ok": False, "error": "image not found"})
        return
    p = Path(shot["image_path"])
    if not p.is_file():
        _json_response(handler, 404, {"ok": False, "error": "file not found"})
        return
    body = p.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", "image/png")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def h_job_get(handler, m, q):
    job_id = m.group(1)
    job = S.JobDAO.get(job_id)
    if not job:
        _json_response(handler, 200, {"ok": False, "error": "job not found"})
        return
    _json_response(handler, 200, {"ok": True, "job": job})


def h_issue_resolve(handler, m, q):
    issue_id = int(m.group(1))
    body = _read_json_body(handler)
    resolved_by = body.get("resolved_by") or "manual"
    S.IssueDAO.resolve(issue_id, resolved_by)
    _json_response(handler, 200, {"ok": True})


def h_schemes_list(handler, m, q):
    _json_response(handler, 200, {"ok": True, "schemes": S.SchemeDAO.list_all()})


def h_domain_get(handler, m, q):
    _json_response(handler, 200, {
        "ok": True,
        "terms": S.DomainDAO.all_terms(),
        "stages": S.DomainDAO.stages_all(),
        "era": S.DomainDAO.era_for_year(int(q.get("year") or 2010)),
    })


def h_llm_options(handler, m, q):
    kind = q.get("kind") or "text"
    try:
        import upstream.hellome_llm_config as hlc
        providers = hlc.list_providers() or []
        any_yaml = bool(providers)
        accounts = []
        for acc in providers:
            models = hlc.list_models(acc.get("account_id"), kind) or []
            if models:
                accounts.append(acc)
        fb = hlc.resolve_default(kind)
        if accounts:
            src = "yaml"
            hint = "已下发"
        elif fb and fb.get("api_key") and fb.get("source") == "env":
            if kind in ("image", "video"):
                src = "env"
                hint = ("当前能力尚未下发到本机" if any_yaml
                        else "请到 HelloMe 下发带该能力的模型")
            else:
                src = "env"
                hint = ("当前能力尚未下发到本机，暂用桌面词元" if any_yaml
                        else "使用桌面词元（未下发 HelloMe 账号）")
        else:
            src = "none"
            hint = "请到 HelloMe → 模型 API 添加账号并下发到本机"
        _json_response(handler, 200, {
            "ok": True,
            "source": src,
            "hint": hint,
            "configured": src != "none",
            "accounts": accounts,
            "models": [],
        })
    except Exception as e:
        _json_response(handler, 200, {
            "ok": True, "source": "none",
            "hint": "请到 HelloMe → 模型 API 添加账号并下发到本机",
            "configured": False, "accounts": [], "models": [],
            "debug": str(e)[:200],
        })


def h_llm_models(handler, m, q):
    kind = q.get("kind") or "text"
    account_id = q.get("account_id")
    try:
        import upstream.hellome_llm_config as hlc
        models = hlc.list_models(account_id, kind) or []
        _json_response(handler, 200, {"ok": True, "models": models})
    except Exception as e:
        _json_response(handler, 200, {"ok": True, "models": [],
                                       "debug": str(e)[:200]})


def h_settings_llm_get(handler, m, q):
    keys = ("writer", "continuity", "extractor",
            "arbiter", "editor", "curator", "architect")
    out = {k: S.SettingDAO.get(f"llm.{k}") or {} for k in keys}
    _json_response(handler, 200, {"ok": True, "settings": out})


def h_settings_llm_put(handler, m, q):
    body = _read_json_body(handler)
    role = body.get("role") or "writer"
    S.SettingDAO.set(f"llm.{role}", {
        "account_id": body.get("account_id"),
        "model_id": body.get("model_id"),
    })
    _json_response(handler, 200, {"ok": True})


def h_export(handler, m, q):
    body = _read_json_body(handler)
    fmt = body.get("format") or "md"
    chapters = []
    for row in S.ChapterDAO.list_all():
        ch = S.ChapterDAO.get(row["chapter_no"])
        if not ch:
            continue
        chapters.append(ch)
    sep = "\n\n" if fmt == "txt" else "\n\n---\n\n"
    text = sep.join((c.get("body_md") or "") for c in chapters)
    _json_response(handler, 200, {"ok": True, "text": text, "count": len(chapters)})


# ================================================================ 分发
_HANDLERS = {
    "index": h_index,
    "health": h_health,
    "hello": h_hello,
    "project_get": h_project_get,
    "project_put": h_project_put,
    "bible_get": h_bible_get,
    "bible_put": h_bible_put,
    "outline_list": h_outline_list,
    "chapter_list": h_chapter_list,
    "chapter_get": h_chapter_get,
    "chapter_save": h_chapter_save,
    "contract_get": h_contract_get,
    "contract_save": h_contract_save,
    "contract_freeze": h_contract_freeze,
    "contract_unfreeze": h_contract_unfreeze,
    "chapter_write": h_chapter_write,
    "chapter_recheck": h_chapter_recheck,
    "chapter_accept": h_chapter_accept,
    "chapter_issues": h_chapter_issues,
    "storyboard_generate": h_storyboard_generate,
    "storyboard_get": h_storyboard_get,
    "storyboard_retry": h_storyboard_retry,
    "storyboard_image": h_storyboard_image,
    "job_get": h_job_get,
    "issue_resolve": h_issue_resolve,
    "schemes_list": h_schemes_list,
    "domain_get": h_domain_get,
    "llm_options": h_llm_options,
    "llm_models": h_llm_models,
    "settings_llm_get": h_settings_llm_get,
    "settings_llm_put": h_settings_llm_put,
    "export": h_export,
}


# ================================================================ HTTP Handler
class Handler(BaseHTTPRequestHandler):
    server_version = "novel-forge/0.1"

    def log_message(self, fmt, *args):
        return

    def _dispatch(self, method: str):
        path = urlparse(self.path).path

        # DEV 模式：本机没有 adapter，presence 给假成功
        if DEV_STATIC and path.startswith("/api/presence"):
            _json_response(self, 200, {
                "ok": True, "clients": 1, "everHadClient": True,
            })
            return

        # 1. 业务路由
        for route_method, pattern, name in ROUTES:
            if route_method != method:
                continue
            m = pattern.match(path)
            if not m:
                continue
            func = _HANDLERS.get(name)
            if not func:
                _json_response(self, 500, {"ok": False, "error": "handler missing"})
                return
            try:
                func(self, m, _query(self))
            except Exception as e:
                tb = traceback.format_exc()
                print(f"[novel-forge] handler error {name}: {e}\n{tb}",
                      file=sys.stderr, flush=True)
                try:
                    _json_response(self, 200, {"ok": False, "error": str(e)[:500]})
                except Exception:
                    pass
            return

        # 2. 开发模式：静态伺服 web/
        if DEV_STATIC and method == "GET" and not path.startswith("/api/"):
            if self._serve_static(path):
                return

        # 3. 404
        _json_response(self, 404, {"ok": False, "error": "not found"})

    def _serve_static(self, path: str) -> bool:
        # 本地调试时给 /api/presence 一个假成功（生产由 adapter 处理）
        if path.startswith("/api/presence"):
            _json_response(self, 200, {
                "ok": True, "clients": 1, "everHadClient": True,
            })
            return True

        rel = path.lstrip("/") or "index.html"
        if ".." in rel.split("/"):
            return False
        try:
            target = (DEV_WEB_DIR / rel).resolve()
            target.relative_to(DEV_WEB_DIR.resolve())
        except (ValueError, OSError):
            return False

        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            return False

        if target.suffix == ".js":
            ctype = "application/javascript; charset=utf-8"
        elif target.suffix == ".css":
            ctype = "text/css; charset=utf-8"
        elif target.suffix in (".html", ".htm"):
            ctype = "text/html; charset=utf-8"
        elif target.suffix == ".json":
            ctype = "application/json; charset=utf-8"
        else:
            ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"

        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return True

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def do_HEAD(self):
        self._dispatch("GET")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Allow", "GET,POST,PUT,DELETE,HEAD,OPTIONS")
        self.end_headers()


# ================================================================ main
def main():
    _bootstrap()
    host = (os.environ.get("HELLOME_UPSTREAM_HOST")
            or os.environ.get("HOST")
            or "127.0.0.1")
    httpd = ThreadingHTTPServer((host, PORT), Handler)
    print(f"[novel-forge] listening on {host}:{PORT}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()