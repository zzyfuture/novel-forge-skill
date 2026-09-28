#!/usr/bin/env python3
"""
novel-forge 单章生产流水线。

- 所有步骤结果落库，可中断恢复
- 三条主流水线：write_chapter / accept_chapter / recheck_chapter
- 上下文组装在此完成（不从 writer 引入）
"""
from __future__ import annotations

import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import store
from .agents.writer import WriterAgent
from .agents.extractor import extract_with_cache
from .agents.continuity import run_all_layers
from .agents.arbiter import ArbiterAgent
from .agents.editor import EditorAgent
from .agents.curator import CuratorAgent
from .agents.storyboard_artist import StoryboardArtist, DEFAULT_STYLE
from .agents.director import DirectorAgent


MAX_ROUNDS = 2
_executor = ThreadPoolExecutor(max_workers=2)


class OrchestratorError(Exception):
    pass


# ============================================================
# 风格配置加载
# ============================================================
def _load_genre_profile() -> dict:
    """优先读数据目录，回退到 seed。用户可以覆盖。"""
    data_dir = (os.environ.get("HELLOME_SKILL_DATA_DIR") or "").strip()
    if data_dir:
        p = Path(data_dir) / "genre_profile.json"
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass

    seed = Path(__file__).parent / "seed" / "genre_profile.json"
    if seed.is_file():
        try:
            return json.loads(seed.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


# ============================================================
# 上下文组装
# ============================================================
def build_context_bundle(
    chapter_no: int,
    contract: dict,
    db,
    domain_kb,
) -> dict:
    """为 Writer 组装上下文。"""
    characters = db.characters_list()
    locations = db.locations_list()
    rules = db.world_rules_list()
    active_schemes = db.schemes_active_at(chapter_no)
    open_foreshadows = db.foreshadows_open_before(chapter_no)
    prev_states = db.character_state_latest_before(chapter_no)

    prev_summaries: list[str] = []
    for n in range(max(1, chapter_no - 3), chapter_no):
        ch = db.chapter_get(n)
        if ch and ch.get("summary"):
            prev_summaries.append(ch["summary"])

    prev_tail = _tail_of_previous_chapter(chapter_no, db, chars=200)

    domain_ctx = {
        "terms": _relevant_terms(contract.get("domain_inject", []), domain_kb),
        "stages": _relevant_stages(contract.get("domain_inject", []), domain_kb),
        "era_facts": domain_kb.era_for_year(contract.get("year", 2010)),
    }

    return {
        "contract": contract,
        "characters": characters,
        "locations": locations,
        "rules": rules,
        "active_schemes": active_schemes,
        "open_foreshadows": open_foreshadows,
        "prev_states": prev_states,
        "prev_summaries": prev_summaries,
        "prev_tail": prev_tail,
        "domain_ctx": domain_ctx,
        "genre_profile": _load_genre_profile(),
    }


def _tail_of_previous_chapter(chapter_no: int, db, chars: int = 200) -> str:
    if chapter_no <= 1:
        return ""
    prev = db.chapter_get(chapter_no - 1)
    if not prev or not prev.get("body_md"):
        return ""
    return prev["body_md"][-chars:]


def _relevant_terms(inject: list, domain_kb) -> list[dict]:
    all_terms = domain_kb.all_terms()
    out = []
    for item in inject:
        for t in all_terms:
            if item in t["term"] or t["term"] in item:
                out.append(t)
                break
    return out


def _relevant_stages(inject: list, domain_kb) -> list[dict]:
    all_stages = domain_kb.stages_all()
    out = []
    for item in inject:
        for s in all_stages:
            if item in s["name"] or s["name"] in item:
                out.append(s)
                break
    return out


# ============================================================
# 单章生产
# ============================================================
def write_chapter(chapter_no: int, job_id: str, llm) -> dict:
    """完整单章流水线。可中断恢复。"""
    store.init_db()
    job = store.JobDAO.get(job_id) or {}
    start_step = job.get("step") or "init"

    def tick(progress, step, message):
        store.JobDAO.update(job_id, progress=progress, step=step, message=message)

    # 0. 冻结合同
    contract = store.ContractDAO.get_frozen(chapter_no)
    if not contract:
        raise OrchestratorError(f"第 {chapter_no} 章没有冻结合同，先冻结合同再写")

    # 1. 组装上下文
    tick(5, "context", "组装上下文")
    bundle = build_context_bundle(
        chapter_no, contract, _db_adapter(), _domain_adapter()
    )

    # 2. 生成初稿
    if _step_lt(start_step, "draft"):
        tick(15, "draft", "生成初稿")
        writer = WriterAgent(llm)
        body = writer.write(chapter_no, bundle)
        store.ChapterDAO.save(
            chapter_no, body, contract_id=contract["id"],
            title=contract.get("title"),
        )
    else:
        body = (store.ChapterDAO.get(chapter_no) or {}).get("body_md", "")
        if not body:
            raise OrchestratorError("恢复失败：找不到已生成的初稿")

    # 3. 审校循环
    rounds = 0
    final_issues: list[dict] = []
    paused_human = False
    extracted: dict | None = None

    while rounds < MAX_ROUNDS:
        rounds += 1
        tick(30 + rounds * 10, f"review_r{rounds}", f"第 {rounds} 轮审校")

        store.IssueDAO.clear_chapter(chapter_no)

        # 3b. 抽取
        tick(32, "review_r1_extract", f"第 {rounds} 轮：抽取事实（1–2 分钟）")
        extracted = extract_with_cache(
            chapter_no, body, contract,
            _build_extractor_ctx(chapter_no, contract),
            llm,
        )
        store.FactDAO.add_many(chapter_no, extracted.get("facts", []))

        # 3c. 四层审校
        tick(38, "review_r1_continuity", f"第 {rounds} 轮：语义审校（30–60 秒）")
        issues = run_all_layers(
            chapter_no, contract, extracted,
            _build_continuity_ctx(chapter_no, contract),
            _db_adapter(), llm=llm,
        )
        for it in issues:
            store.IssueDAO.add(
                chapter_no, it["severity"], it["code"], it["title"],
                it.get("detail", ""), it.get("evidence", []),
                it.get("suggestion", ""),
            )
        final_issues = issues

        blockers = [i for i in issues if i["severity"] == "blocker"]
        if not blockers:
            break

        # 3d. 裁决
        tick(60 + rounds * 5, f"arbitrate_r{rounds}", f"第 {rounds} 轮裁决")
        arbiter = ArbiterAgent(llm)
        verdicts = arbiter.arbitrate(
            chapter_no, issues, contract, _build_bible_snapshot()
        )

        if any(v.get("action") == "need_human" for v in verdicts):
            paused_human = True
            store.ChapterDAO.set_status(chapter_no, "blocked")
            tick(90, "paused_human", "存在需要人工裁决的问题，已暂停")
            break

        # 3e. 修订
        tick(70 + rounds * 5, f"edit_r{rounds}", f"第 {rounds} 轮修订")
        editor = EditorAgent(llm)
        body = editor.revise(chapter_no, body, issues, verdicts, contract)
        store.ChapterDAO.save(
            chapter_no, body, contract_id=contract["id"],
            title=contract.get("title"),
        )

    # 4. 落最终状态
    if paused_human:
        return {
            "chapter_no": chapter_no, "status": "blocked",
            "rounds": rounds, "issues_count": len(final_issues),
        }

    tick(92, "summarize", "生成摘要")
    if extracted is None:
        extracted = extract_with_cache(
            chapter_no, body, contract,
            _build_extractor_ctx(chapter_no, contract),
            llm,
        )

    summary_text = ""
    if isinstance(extracted.get("summary"), dict):
        summary_text = extracted["summary"].get("text", "") or ""
    tension = extracted.get("tension")

    store.ChapterDAO.save(
        chapter_no, body, contract_id=contract["id"],
        title=contract.get("title"),
        summary=summary_text,
        tension=tension,
    )
    # 存最后一次抽取结果，供验收复用，避免重跑 60–150 秒
    if extracted:
        import hashlib
        body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        store.ChapterDAO.save_extracted(chapter_no, extracted, body_hash)

    store.ChapterDAO.set_status(chapter_no, "reviewing")
    tick(95, "done", "待人工验收")
    return {
        "chapter_no": chapter_no, "status": "reviewing",
        "rounds": rounds, "issues_count": len(final_issues),
    }


# ============================================================
# 验收
# ============================================================
def accept_chapter(chapter_no: int, llm) -> dict:
    """验收：跑 Curator，更新权威状态。"""
    store.init_db()

    running_job = store._conn().execute(
        "SELECT id FROM job WHERE kind='accept_chapter' AND chapter_no=? "
        "AND status='running' ORDER BY created_at DESC LIMIT 1",
        (chapter_no,),
    ).fetchone()
    job_id = running_job["id"] if running_job else None

    def tick(progress, step, message):
        if job_id:
            store.JobDAO.update(job_id, progress=progress, step=step, message=message)

    if store.IssueDAO.count_open_blockers(chapter_no) > 0:
        raise OrchestratorError("仍有未处理的 blocker，不能验收")

    chapter = store.ChapterDAO.get(chapter_no)
    if not chapter:
        raise OrchestratorError("章节不存在")

    contract = store.ContractDAO.get_frozen(chapter_no)
    if not contract:
        raise OrchestratorError("章节没有冻结合同")

    tick(20, "extract", "抽取事实")
    # 先看 write_chapter 留下的结果 —— body 没改过就直接复用
    extracted = store.ChapterDAO.get_extracted(chapter_no, chapter["body_md"])
    if extracted:
        tick(25, "extract", "复用已有抽取结果")
    else:
        # body 改过或首次验收 —— 老实跑 extractor
        extracted = extract_with_cache(
            chapter_no, chapter["body_md"], contract,
            _build_extractor_ctx(chapter_no, contract),
            llm,
        )

    tick(60, "curate", "更新权威状态")
    curator = CuratorAgent(llm)
    curator.update(
        chapter_no=chapter_no,
        extracted=extracted,
        contract=contract,
        db=_db_adapter(),
    )

    tick(95, "finalize", "标记验收")
    store.ChapterDAO.set_status(chapter_no, "accepted")

    return {"chapter_no": chapter_no, "status": "accepted"}


# ============================================================
# 只重跑审校（不重跑 Writer）
# ============================================================
def recheck_chapter(chapter_no: int, job_id: str, llm) -> dict:
    store.init_db()

    def tick(progress, step, message):
        store.JobDAO.update(job_id, progress=progress, step=step, message=message)

    chapter = store.ChapterDAO.get(chapter_no)
    if not chapter or not chapter.get("body_md"):
        raise OrchestratorError(f"第 {chapter_no} 章没有正文，先「生成草稿」")

    contract = (store.ContractDAO.get_frozen(chapter_no)
                or store.ContractDAO.get_draft(chapter_no))
    if not contract:
        raise OrchestratorError(f"第 {chapter_no} 章没有合同")

    body = chapter["body_md"]

    tick(15, "clear", "清空旧问题")
    store.IssueDAO.clear_chapter(chapter_no)

    tick(40, "extract", "抽取事实")
    extracted = extract_with_cache(
        chapter_no, body, contract,
        _build_extractor_ctx(chapter_no, contract),
        llm,
    )
    store.FactDAO.add_many(chapter_no, extracted.get("facts", []))

    tick(70, "review", "四层审校")
    issues = run_all_layers(
        chapter_no, contract, extracted,
        _build_continuity_ctx(chapter_no, contract),
        _db_adapter(), llm=llm,
    )
    for it in issues:
        store.IssueDAO.add(
            chapter_no, it["severity"], it["code"], it["title"],
            it.get("detail", ""), it.get("evidence", []),
            it.get("suggestion", ""),
        )

    tick(95, "done", f"审校完成 · {len(issues)} 条")
    return {"chapter_no": chapter_no, "issues_count": len(issues)}


# ============================================================
# 异步封装
# ============================================================
def submit_write_chapter(chapter_no: int, llm) -> str:
    job_id = uuid.uuid4().hex[:16]
    store.JobDAO.create(job_id, "write_chapter", chapter_no)

    def run():
        try:
            result = write_chapter(chapter_no, job_id, llm)
            store.JobDAO.update(
                job_id, progress=100, status="done",
                step="done", result=result,
            )
        except Exception as e:
            store.JobDAO.update(
                job_id, status="failed", error=f"{type(e).__name__}: {e}",
            )

    _executor.submit(run)
    return job_id


def submit_accept_chapter(chapter_no: int, llm) -> str:
    job_id = uuid.uuid4().hex[:16]
    store.JobDAO.create(job_id, "accept_chapter", chapter_no)

    def run():
        try:
            result = accept_chapter(chapter_no, llm)
            store.JobDAO.update(job_id, progress=100, status="done", result=result)
        except Exception as e:
            store.JobDAO.update(
                job_id, status="failed", error=f"{type(e).__name__}: {e}",
            )

    _executor.submit(run)
    return job_id


def submit_recheck_chapter(chapter_no: int, llm) -> str:
    job_id = uuid.uuid4().hex[:16]
    store.JobDAO.create(job_id, "recheck_chapter", chapter_no)

    def run():
        try:
            result = recheck_chapter(chapter_no, job_id, llm)
            store.JobDAO.update(job_id, progress=100, status="done", result=result)
        except Exception as e:
            store.JobDAO.update(
                job_id, status="failed", error=f"{type(e).__name__}: {e}",
            )

    _executor.submit(run)
    return job_id


# ============================================================
# 内部工具
# ============================================================
def _step_lt(current: str, target: str) -> bool:
    order = ["init", "context", "draft",
             "review_r1", "edit_r1",
             "review_r2", "edit_r2",
             "review_r3", "edit_r3",
             "curate", "done", "paused_human"]
    try:
        return order.index(current) < order.index(target)
    except ValueError:
        return True


# ============================================================
# 适配器：把 DAO 包成 pipeline 需要的形状
# ============================================================
class _DBAdapter:
    def get_character_state_latest_before(self, name, chapter_no):
        c = store.CharacterDAO.by_name(name)
        if not c:
            return None
        return store.CharacterStateDAO.at_chapter(c["id"], chapter_no)

    def character_by_name(self, name):
        return store.CharacterDAO.by_name(name)

    def timeline_last_before(self, chapter_no):
        return store.TimelineDAO.last_before(chapter_no)

    def characters_list(self):
        return store.CharacterDAO.list_all()

    def locations_list(self):
        return store.LocationDAO.list_all()

    def world_rules_list(self):
        return store.WorldRuleDAO.list_all()

    def schemes_active_at(self, chapter_no):
        return store.SchemeDAO.active_at(chapter_no)

    def foreshadows_open_before(self, chapter_no):
        return store.ForeshadowDAO.open_before(chapter_no)

    def character_state_latest_before(self, chapter_no):
        return store.CharacterStateDAO.latest_before(chapter_no)

    def character_state_get(self, name, chapter_no):
        c = store.CharacterDAO.by_name(name)
        if not c:
            return None
        return store.CharacterStateDAO.at_chapter(c["id"], chapter_no)

    def chapter_get(self, chapter_no):
        return store.ChapterDAO.get(chapter_no)

    def character_state_upsert(self, character_id, chapter_no, **fields):
        return store.CharacterStateDAO.upsert(character_id, chapter_no, **fields)

    def timeline_add(self, chapter_no, summary, story_time, precision, actors):
        return store.TimelineDAO.add(chapter_no, summary, story_time, precision, actors)


class _DomainAdapter:
    def all_terms(self):
        return store.DomainDAO.all_terms()

    def stages_all(self):
        return store.DomainDAO.stages_all()

    def era_for_year(self, year):
        return store.DomainDAO.era_for_year(year)


_db_adapter_singleton = _DBAdapter()
_domain_adapter_singleton = _DomainAdapter()


def _db_adapter():
    return _db_adapter_singleton


def _domain_adapter():
    return _domain_adapter_singleton


# ============================================================
# 内部上下文构造
# ============================================================
def _build_extractor_ctx(chapter_no: int, contract: dict) -> dict:
    return {
        "characters": store.CharacterDAO.list_all(),
        "locations": store.LocationDAO.list_all(),
        "active_schemes": store.SchemeDAO.active_at(chapter_no),
        "domain_terms": store.DomainDAO.terms_for_chapter(chapter_no),
        "era_facts": store.DomainDAO.era_for_year(contract.get("year", 2010)),
        "prev_chapter_summary": (
            store.ChapterDAO.get(chapter_no - 1) or {}
        ).get("summary", ""),
    }


def _build_continuity_ctx(chapter_no: int, contract: dict) -> dict:
    return {
        "contract": contract,
        "characters": store.CharacterDAO.list_all(),
        "bible": {
            "rules": store.WorldRuleDAO.list_all(),
            "characters": store.CharacterDAO.list_all(),
            "locations": store.LocationDAO.list_all(),
        },
        "domain_ctx": {
            "terms": store.DomainDAO.terms_for_chapter(chapter_no),
            "stages": store.DomainDAO.stages_all(),
            "era": store.DomainDAO.era_for_year(contract.get("year", 2010)),
        },
        "prev_summaries": [
            (store.ChapterDAO.get(n) or {}).get("summary", "")
            for n in range(max(1, chapter_no - 3), chapter_no)
        ],
    }


def _build_bible_snapshot() -> dict:
    return {
        "rules": store.WorldRuleDAO.list_all(),
        "characters": store.CharacterDAO.list_all(),
        "locations": store.LocationDAO.list_all(),
        "schemes": store.SchemeDAO.list_all(),
    }

# ============================================================
# 分镜生成
# ============================================================
def generate_storyboard(chapter_no: int, job_id: str, llm,
                        force_rerun: bool = False,
                        shot_count: int = 8) -> dict:
    """完整分镜流水线：拆镜头 → 逐张生图。可中断恢复。"""
    store.init_db()

    def tick(progress, step, message):
        store.JobDAO.update(job_id, progress=progress, step=step, message=message)

    chapter = store.ChapterDAO.get(chapter_no)
    if not chapter or not chapter.get("body_md"):
        raise OrchestratorError(f"第 {chapter_no} 章没有正文，先「生成草稿」")

    contract = (store.ContractDAO.get_frozen(chapter_no)
                or store.ContractDAO.get_draft(chapter_no))
    if not contract:
        raise OrchestratorError(f"第 {chapter_no} 章没有合同")

    body = chapter["body_md"]

    # --- 1. 拆镜头 ---
    sb = store.StoryboardDAO.get(chapter_no)
    shots = store.StoryboardShotDAO.list_by_chapter(chapter_no)

    if not shots or (sb and sb.get("status") in ("draft", "failed")):
        tick(5, "direct", "拆镜头")
        bible = _build_bible_snapshot()
        director = DirectorAgent(llm)
        try:
            result = director.storyboard(chapter_no, body, contract, bible,
                                          shot_count=shot_count)
        except Exception as e:
            store.StoryboardDAO.upsert(
                chapter_no, status="failed", error=str(e)[:500],
            )
            raise OrchestratorError(f"拆镜头失败：{e}")

        # 清理旧镜头，重写
        store.StoryboardDAO.delete_shots(chapter_no)
        style = _load_storyboard_style()
        store.StoryboardDAO.upsert(
            chapter_no,
            total_shots=len(result.get("shots", [])),
            estimated_duration_sec=result.get("estimated_duration_sec"),
            style=style,
            status="draft",
            error=None,
        )
        for sh in result.get("shots", []):
            store.StoryboardShotDAO.upsert(
                chapter_no, sh["shot_id"],
                scene_idx=sh.get("scene_idx"),
                duration_sec=sh.get("duration_sec"),
                shot_type=sh.get("shot_type"),
                characters=sh.get("characters", []),
                location=sh.get("location"),
                time_of_day=sh.get("time_of_day"),
                action=sh.get("action"),
                dialogue=sh.get("dialogue"),
                emotion=sh.get("emotion"),
                camera_movement=sh.get("camera_movement"),
                text_ref=sh.get("text_ref"),
                props=sh.get("props", []),
                status="pending",
            )
        shots = store.StoryboardShotDAO.list_by_chapter(chapter_no)

    if not shots:
        raise OrchestratorError("拆镜头后没有生成任何镜头")

    # --- 2. 逐张生图 ---
    bible_full = store.CharacterDAO.list_all()
    locations_full = store.LocationDAO.list_all()
    props_full = store.PropDAO.list_all()
    char_map = {c["name"]: c for c in bible_full}
    loc_map = {l["name"]: l for l in locations_full}
    prop_map = {p["name"]: p for p in props_full}

    style = _load_storyboard_style()
    artist = StoryboardArtist()

    total = len(shots)
    done = sum(1 for s in shots if s.get("status") == "done" and s.get("image_path"))

    for sh in shots:
        sid = sh["shot_id"]
        if not force_rerun and sh.get("status") == "done" and sh.get("image_path"):
            continue
        progress = 10 + int((done / total) * 85) if total else 50
        tick(progress, f"shot_{sid:02d}",
             f"生成镜头 {sid}/{total}（{sh.get('shot_type', '')}）")

        # 无论成功失败，先把 prompt 拼出来
        prompt_used = ""
        try:
            style_full = {**DEFAULT_STYLE, **(style or {})}
            prompt_used = artist._build_prompt(
                sh, char_map, loc_map, prop_map, style_full
            )
        except Exception:
            prompt_used = ""

        try:
            img_path, prompt_used_ret = artist.render_shot(
                chapter_no=chapter_no,
                shot=sh,
                characters_bible=char_map,
                locations_bible=loc_map,
                props_bible=prop_map,
                style=style,
            )
            store.StoryboardShotDAO.upsert(
                chapter_no, sid,
                image_path=img_path,
                prompt_used=prompt_used_ret,
                status="done",
                error=None,
            )
            done += 1
        except Exception as e:
            store.StoryboardShotDAO.upsert(
                chapter_no, sid,
                prompt_used=prompt_used,
                status="text_only",
                error=str(e)[:500],
            )

    # --- 3. 结束 ---
    final_shots = store.StoryboardShotDAO.list_by_chapter(chapter_no)
    success = sum(1 for s in final_shots if s.get("status") == "done")
    text_only = sum(1 for s in final_shots if s.get("status") == "text_only")
    failed = sum(1 for s in final_shots if s.get("status") == "failed")
    if success == len(final_shots) and len(final_shots) > 0:
        final_status = "generated"
    elif success > 0:
        final_status = "partial"
    elif text_only > 0:
        final_status = "text_only"
    else:
        final_status = "failed"

    store.StoryboardDAO.upsert(
        chapter_no,
        total_shots=len(final_shots),
        style=style,
        status=final_status,
        error=None,
    )
    tick(100, "done",
         f"完成 · 出图 {success} · 仅文字 {text_only} · 失败 {failed}")
    return {
        "chapter_no": chapter_no,
        "total_shots": len(final_shots),
        "success": success,
        "text_only": text_only,
        "failed": failed,
    }


def _load_storyboard_style() -> dict:
    """从 genre_profile 读 storyboard_style，回退默认。"""
    profile = _load_genre_profile()
    return profile.get("storyboard_style") or {}


def submit_storyboard_chapter(chapter_no: int, llm,
                              force_rerun: bool = False,
                              shot_count: int = 8) -> str:
    job_id = uuid.uuid4().hex[:16]
    store.JobDAO.create(job_id, "storyboard_chapter", chapter_no)

    def run():
        try:
            result = generate_storyboard(chapter_no, job_id, llm,
                                          force_rerun=force_rerun,
                                          shot_count=shot_count)
            store.JobDAO.update(
                job_id, progress=100, status="done",
                step="done", result=result,
            )
        except Exception as e:
            store.JobDAO.update(
                job_id, status="failed", error=f"{type(e).__name__}: {e}",
            )

    _executor.submit(run)
    return job_id