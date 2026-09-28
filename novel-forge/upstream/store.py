#!/usr/bin/env python3
"""
SQLite 状态库。所有表落 HELLOME_SKILL_DATA_DIR/novel.db。
标准库 sqlite3。零第三方依赖。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


# ---------------------------------------------------------------- 连接管理
_local = threading.local()


def _db_path() -> Path:
    raw = (os.environ.get("HELLOME_SKILL_DATA_DIR") or "").strip()
    if not raw:
        raise SystemExit("SKILL_BOOT_ERROR HELLOME_SKILL_DATA_DIR is required")
    p = Path(raw)
    p.mkdir(parents=True, exist_ok=True)
    return p / "novel.db"


def _conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        c = sqlite3.connect(
            str(_db_path()),
            isolation_level=None,
            timeout=30.0,             # ← Python 层：连接等锁最长 30 秒
        )
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA busy_timeout=30000")   # ← SQLite 层：等锁 30 秒
        _local.conn = c
    return c


@contextmanager
def tx():
    c = _conn()
    c.execute("BEGIN IMMEDIATE")
    try:
        yield c
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- Schema
SCHEMA = """
CREATE TABLE IF NOT EXISTS project (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  title TEXT NOT NULL,
  genre TEXT,
  premise TEXT,
  pov_mode TEXT DEFAULT 'third_limited',
  target_chapters INTEGER DEFAULT 36,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS world_rule (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  category TEXT NOT NULL,
  statement TEXT NOT NULL,
  hard INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS character (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  aliases_json TEXT NOT NULL DEFAULT '[]',
  role TEXT,
  voice TEXT,
  traits_json TEXT NOT NULL DEFAULT '[]',
  relations_json TEXT NOT NULL DEFAULT '{}',
  abilities_json TEXT NOT NULL DEFAULT '[]',
  status TEXT DEFAULT 'alive',
  appearance_prompt TEXT,
  appearance_notes TEXT,
  reference_images_json TEXT NOT NULL DEFAULT '[]',
  costumes_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS location (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  aliases_json TEXT NOT NULL DEFAULT '[]',
  region TEXT,
  traits_json TEXT NOT NULL DEFAULT '[]',
  status TEXT DEFAULT 'active',
  visual_prompt TEXT,
  lighting_notes TEXT,
  reference_images_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS timeline_event (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  story_time TEXT,
  precision TEXT DEFAULT 'vague',
  chapter_no INTEGER NOT NULL,
  summary TEXT NOT NULL,
  actors_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_timeline_chapter ON timeline_event(chapter_no);

CREATE TABLE IF NOT EXISTS character_state (
  character_id INTEGER NOT NULL,
  chapter_no INTEGER NOT NULL,
  alive INTEGER NOT NULL DEFAULT 1,
  location_id INTEGER,
  power_level INTEGER,
  stance TEXT,
  inner_state TEXT,
  knowledge_json TEXT NOT NULL DEFAULT '[]',
  relations_json TEXT NOT NULL DEFAULT '{}',
  arc_note TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (character_id, chapter_no),
  FOREIGN KEY (character_id) REFERENCES character(id)
);

CREATE TABLE IF NOT EXISTS foreshadow (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  planted_chapter INTEGER NOT NULL,
  due_chapter INTEGER,
  payoff_chapter INTEGER,
  summary TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  evidence_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scheme (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  architect TEXT,
  target TEXT,
  chapter_planted INTEGER,
  chapter_armed INTEGER,
  chapter_triggered INTEGER,
  chapter_resolved INTEGER,
  information_gap TEXT,
  mechanism TEXT,
  countermeasure TEXT,
  status TEXT NOT NULL DEFAULT 'planted',
  evidence_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS arc (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  idx INTEGER NOT NULL,
  title TEXT NOT NULL,
  summary TEXT,
  chapter_from INTEGER NOT NULL,
  chapter_to INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS outline_node (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  arc_id INTEGER,
  chapter_no INTEGER NOT NULL UNIQUE,
  intent TEXT NOT NULL,
  must_advance_json TEXT NOT NULL DEFAULT '[]',
  notes TEXT,
  FOREIGN KEY (arc_id) REFERENCES arc(id)
);

CREATE TABLE IF NOT EXISTS contract (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chapter_no INTEGER NOT NULL,
  version INTEGER NOT NULL,
  frozen_at TEXT,
  hash TEXT,
  pov_character_id TEXT,
  scenes_json TEXT NOT NULL,
  must_advance_json TEXT NOT NULL DEFAULT '[]',
  plant_json TEXT NOT NULL DEFAULT '[]',
  payoff_json TEXT NOT NULL DEFAULT '[]',
  forbid_json TEXT NOT NULL DEFAULT '[]',
  tone TEXT,
  word_target INTEGER DEFAULT 3500,
  domain_inject_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TEXT NOT NULL,
  UNIQUE(chapter_no, version)
);
CREATE INDEX IF NOT EXISTS idx_contract_chapter ON contract(chapter_no, status);

CREATE TABLE IF NOT EXISTS chapter (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chapter_no INTEGER NOT NULL UNIQUE,
  contract_id INTEGER,
  title TEXT,
  body_md TEXT,
  word_count INTEGER DEFAULT 0,
  summary TEXT,
  tension INTEGER,
  status TEXT NOT NULL DEFAULT 'draft',
  accepted_at TEXT,
  latest_extracted_json TEXT,
  latest_extracted_body_hash TEXT,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (contract_id) REFERENCES contract(id)
);

CREATE TABLE IF NOT EXISTS fact_ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chapter_no INTEGER NOT NULL,
  kind TEXT NOT NULL,
  subject TEXT,
  predicate TEXT,
  object TEXT,
  confidence REAL,
  evidence TEXT,
  paragraph_idx INTEGER,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fact_chapter ON fact_ledger(chapter_no);
CREATE INDEX IF NOT EXISTS idx_fact_subject ON fact_ledger(subject);

CREATE TABLE IF NOT EXISTS issue (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chapter_no INTEGER NOT NULL,
  severity TEXT NOT NULL,
  code TEXT NOT NULL,
  title TEXT NOT NULL,
  detail TEXT,
  evidence_json TEXT NOT NULL DEFAULT '[]',
  suggestion TEXT,
  status TEXT NOT NULL DEFAULT 'open',
  resolved_by TEXT,
  resolved_at TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_issue_chapter ON issue(chapter_no, status);

CREATE TABLE IF NOT EXISTS job (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  chapter_no INTEGER,
  status TEXT NOT NULL,
  progress INTEGER DEFAULT 0,
  step TEXT,
  message TEXT,
  result_json TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_job_status ON job(status, updated_at);

CREATE TABLE IF NOT EXISTS setting (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS domain_term (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  term TEXT NOT NULL UNIQUE,
  category TEXT NOT NULL,
  definition TEXT NOT NULL,
  era_from INTEGER,
  era_to INTEGER,
  misuse_examples TEXT NOT NULL DEFAULT '[]',
  source_chapters TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS process_stage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  stage_order INTEGER NOT NULL,
  actors TEXT NOT NULL DEFAULT '[]',
  artifacts TEXT NOT NULL DEFAULT '[]',
  traps TEXT NOT NULL DEFAULT '[]',
  source_chapters TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS era_detail (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  year INTEGER NOT NULL,
  category TEXT NOT NULL,
  fact TEXT NOT NULL,
  forbidden_anachronism TEXT NOT NULL DEFAULT '[]',
  source_chapters TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_era_year ON era_detail(year, category);

CREATE TABLE IF NOT EXISTS extractor_cache (
  key TEXT PRIMARY KEY,
  chapter_no INTEGER NOT NULL,
  output_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_call_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent TEXT NOT NULL,
  chapter_no INTEGER,
  model TEXT,
  prompt_tokens INTEGER,
  completion_tokens INTEGER,
  latency_ms INTEGER,
  ok INTEGER,
  error TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_llm_log_chapter ON llm_call_log(chapter_no, agent);

CREATE TABLE IF NOT EXISTS prop (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  aliases_json TEXT NOT NULL DEFAULT '[]',
  visual_prompt TEXT,
  reference_images_json TEXT NOT NULL DEFAULT '[]',
  first_chapter INTEGER,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS storyboard (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chapter_no INTEGER NOT NULL UNIQUE,
  total_shots INTEGER NOT NULL DEFAULT 0,
  estimated_duration_sec INTEGER,
  style_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'draft',
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS storyboard_shot (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chapter_no INTEGER NOT NULL,
  shot_id INTEGER NOT NULL,
  scene_idx INTEGER,
  duration_sec REAL,
  shot_type TEXT,
  characters_json TEXT NOT NULL DEFAULT '[]',
  location TEXT,
  time_of_day TEXT,
  action TEXT,
  dialogue TEXT,
  emotion TEXT,
  camera_movement TEXT,
  text_ref TEXT,
  props_json TEXT NOT NULL DEFAULT '[]',
  image_path TEXT,
  prompt_used TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(chapter_no, shot_id)
);
CREATE INDEX IF NOT EXISTS idx_storyboard_chapter ON storyboard_shot(chapter_no, shot_id);
"""


def init_db() -> None:
    c = _conn()
    c.executescript(SCHEMA)
    _migrate_db(c)                     # ← 加这一行
    row = c.execute("SELECT id FROM project WHERE id=1").fetchone()
    if not row:
        c.execute(
            "INSERT INTO project (id, title, created_at, updated_at) VALUES (1, ?, ?, ?)",
            ("未命名作品", now(), now()),
        )


def _migrate_db(c: sqlite3.Connection) -> None:
    """幂等迁移：老库补齐新字段。已有字段跳过。"""
    _add_cols_if_missing(c, "character", [
        ("appearance_prompt", "TEXT"),
        ("appearance_notes", "TEXT"),
        ("reference_images_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("costumes_json", "TEXT NOT NULL DEFAULT '[]'"),
    ])
    _add_cols_if_missing(c, "location", [
        ("visual_prompt", "TEXT"),
        ("lighting_notes", "TEXT"),
        ("reference_images_json", "TEXT NOT NULL DEFAULT '[]'"),
    ])
    _add_cols_if_missing(c, "chapter", [
        ("latest_extracted_json", "TEXT"),
        ("latest_extracted_body_hash", "TEXT"),
    ])


def _add_cols_if_missing(c, table: str, cols: list[tuple[str, str]]) -> None:
    existing = {row[1] for row in c.execute(f"PRAGMA table_info({table})")}
    for name, typ in cols:
        if name in existing:
            continue
        c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")


# ---------------------------------------------------------------- 通用辅助
def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return dict(row)


def _rows_to_list(rows: Iterable[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rows]


def _j(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


def _pj(v: str | None, default: Any = None) -> Any:
    if v is None:
        return default
    try:
        return json.loads(v)
    except (json.JSONDecodeError, TypeError):
        return default


# ---------------------------------------------------------------- Project DAO
class ProjectDAO:
    @staticmethod
    def get() -> dict:
        c = _conn()
        row = c.execute("SELECT * FROM project WHERE id=1").fetchone()
        return _row_to_dict(row) or {}

    @staticmethod
    def update(**fields) -> None:
        allowed = {"title", "genre", "premise", "pov_mode", "target_chapters"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        updates["updated_at"] = now()
        cols = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values())
        with tx() as c:
            c.execute(f"UPDATE project SET {cols} WHERE id=1", vals)


# ---------------------------------------------------------------- Bible DAO
class WorldRuleDAO:
    @staticmethod
    def list_all() -> list[dict]:
        return _rows_to_list(_conn().execute(
            "SELECT * FROM world_rule ORDER BY hard DESC, id"
        ).fetchall())

    @staticmethod
    def add(category: str, statement: str, hard: int = 1) -> int:
        with tx() as c:
            cur = c.execute(
                "INSERT INTO world_rule (category, statement, hard, created_at) VALUES (?,?,?,?)",
                (category, statement, hard, now()),
            )
            return cur.lastrowid


class CharacterDAO:
    @staticmethod
    def list_all() -> list[dict]:
        rows = _rows_to_list(_conn().execute("SELECT * FROM character ORDER BY id").fetchall())
        for r in rows:
            r["aliases"] = _pj(r.pop("aliases_json"), [])
            r["traits"] = _pj(r.pop("traits_json"), [])
            r["relations"] = _pj(r.pop("relations_json"), {})
            r["abilities"] = _pj(r.pop("abilities_json"), [])
            r["reference_images"] = _pj(r.pop("reference_images_json", "[]"), [])
            r["costumes"] = _pj(r.pop("costumes_json", "[]"), [])
        return rows

    @staticmethod
    def by_name(name: str) -> dict | None:
        row = _conn().execute("SELECT * FROM character WHERE name=?", (name,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["aliases"] = _pj(d.pop("aliases_json"), [])
        d["traits"] = _pj(d.pop("traits_json"), [])
        d["relations"] = _pj(d.pop("relations_json"), {})
        d["abilities"] = _pj(d.pop("abilities_json"), [])
        d["reference_images"] = _pj(d.pop("reference_images_json", "[]"), [])
        d["costumes"] = _pj(d.pop("costumes_json", "[]"), [])
        return d

    @staticmethod
    def upsert(name: str, **fields) -> int:
        existing = CharacterDAO.by_name(name)
        with tx() as c:
            if existing:
                sets, vals = [], []
                for k, v in fields.items():
                    if k in {"aliases", "traits", "relations", "abilities",
                             "reference_images", "costumes"}:
                        sets.append(f"{k}_json=?")
                        vals.append(_j(v))
                    elif k in {"role", "voice", "status",
                               "appearance_prompt", "appearance_notes"}:
                        sets.append(f"{k}=?")
                        vals.append(v)
                if sets:
                    vals.append(existing["id"])
                    c.execute(f"UPDATE character SET {', '.join(sets)} WHERE id=?", vals)
                return existing["id"]
            cur = c.execute(
                """INSERT INTO character
                   (name, aliases_json, role, voice, traits_json, relations_json,
                    abilities_json, status, appearance_prompt, appearance_notes,
                    reference_images_json, costumes_json, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (name, _j(fields.get("aliases", [])), fields.get("role"),
                 fields.get("voice"), _j(fields.get("traits", [])),
                 _j(fields.get("relations", {})), _j(fields.get("abilities", [])),
                 fields.get("status", "alive"),
                 fields.get("appearance_prompt"),
                 fields.get("appearance_notes"),
                 _j(fields.get("reference_images", [])),
                 _j(fields.get("costumes", [])),
                 now()),
            )
            return cur.lastrowid


class LocationDAO:
    @staticmethod
    def list_all() -> list[dict]:
        rows = _rows_to_list(_conn().execute("SELECT * FROM location ORDER BY id").fetchall())
        for r in rows:
            r["aliases"] = _pj(r.pop("aliases_json"), [])
            r["traits"] = _pj(r.pop("traits_json"), [])
            r["reference_images"] = _pj(r.pop("reference_images_json", "[]"), [])
        return rows

    @staticmethod
    def upsert(name: str, **fields) -> int:
        row = _conn().execute("SELECT id FROM location WHERE name=?", (name,)).fetchone()
        with tx() as c:
            if row:
                sets, vals = [], []
                for k, v in fields.items():
                    if k in {"aliases", "traits", "reference_images"}:
                        sets.append(f"{k}_json=?")
                        vals.append(_j(v))
                    elif k in {"region", "status", "visual_prompt", "lighting_notes"}:
                        sets.append(f"{k}=?")
                        vals.append(v)
                if sets:
                    vals.append(row["id"])
                    c.execute(f"UPDATE location SET {', '.join(sets)} WHERE id=?", vals)
                return row["id"]
            cur = c.execute(
                """INSERT INTO location
                   (name, aliases_json, region, traits_json, status,
                    visual_prompt, lighting_notes, reference_images_json)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (name, _j(fields.get("aliases", [])), fields.get("region"),
                 _j(fields.get("traits", [])), fields.get("status", "active"),
                 fields.get("visual_prompt"), fields.get("lighting_notes"),
                 _j(fields.get("reference_images", []))),
            )
            return cur.lastrowid


class TimelineDAO:
    @staticmethod
    def list_by_chapter(chapter_no: int) -> list[dict]:
        rows = _rows_to_list(_conn().execute(
            "SELECT * FROM timeline_event WHERE chapter_no=? ORDER BY id", (chapter_no,)
        ).fetchall())
        for r in rows:
            r["actors"] = _pj(r.pop("actors_json"), [])
        return rows

    @staticmethod
    def last_before(chapter_no: int) -> dict | None:
        row = _conn().execute(
            "SELECT * FROM timeline_event WHERE chapter_no < ? ORDER BY chapter_no DESC, id DESC LIMIT 1",
            (chapter_no,),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["actors"] = _pj(d.pop("actors_json"), [])
        return d

    @staticmethod
    def add(chapter_no: int, summary: str, story_time: str | None,
            precision: str, actors: list[str]) -> int:
        with tx() as c:
            cur = c.execute(
                """INSERT INTO timeline_event
                   (story_time, precision, chapter_no, summary, actors_json, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (story_time, precision, chapter_no, summary, _j(actors), now()),
            )
            return cur.lastrowid


# ---------------------------------------------------------------- State DAO
class CharacterStateDAO:
    @staticmethod
    def at_chapter(character_id: int, chapter_no: int) -> dict | None:
        row = _conn().execute(
            "SELECT * FROM character_state WHERE character_id=? AND chapter_no<=? ORDER BY chapter_no DESC LIMIT 1",
            (character_id, chapter_no),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["knowledge"] = _pj(d.pop("knowledge_json"), [])
        d["relations"] = _pj(d.pop("relations_json"), {})
        return d

    @staticmethod
    def latest_before(chapter_no: int) -> list[dict]:
        """每个角色在 chapter_no 之前的最新状态。"""
        rows = _conn().execute(
            """SELECT cs.* FROM character_state cs
               INNER JOIN (
                 SELECT character_id, MAX(chapter_no) AS mx
                 FROM character_state WHERE chapter_no < ?
                 GROUP BY character_id
               ) t ON cs.character_id=t.character_id AND cs.chapter_no=t.mx""",
            (chapter_no,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["knowledge"] = _pj(d.pop("knowledge_json"), [])
            d["relations"] = _pj(d.pop("relations_json"), {})
            out.append(d)
        return out

    @staticmethod
    def upsert(character_id: int, chapter_no: int, **fields) -> None:
        existing = _conn().execute(
            "SELECT 1 FROM character_state WHERE character_id=? AND chapter_no=?",
            (character_id, chapter_no),
        ).fetchone()
        payload = {
            "alive": fields.get("alive", 1),
            "location_id": fields.get("location_id"),
            "power_level": fields.get("power_level"),
            "stance": fields.get("stance"),
            "inner_state": fields.get("inner_state"),
            "knowledge": fields.get("knowledge", []),
            "relations": fields.get("relations", {}),
            "arc_note": fields.get("arc_note"),
        }
        with tx() as c:
            if existing:
                c.execute(
                    """UPDATE character_state SET alive=?, location_id=?, power_level=?,
                       stance=?, inner_state=?, knowledge_json=?, relations_json=?,
                       arc_note=?, updated_at=? WHERE character_id=? AND chapter_no=?""",
                    (payload["alive"], payload["location_id"], payload["power_level"],
                     payload["stance"], payload["inner_state"],
                     _j(payload["knowledge"]), _j(payload["relations"]),
                     payload["arc_note"], now(), character_id, chapter_no),
                )
            else:
                c.execute(
                    """INSERT INTO character_state
                       (character_id, chapter_no, alive, location_id, power_level, stance,
                        inner_state, knowledge_json, relations_json, arc_note, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (character_id, chapter_no, payload["alive"], payload["location_id"],
                     payload["power_level"], payload["stance"], payload["inner_state"],
                     _j(payload["knowledge"]), _j(payload["relations"]),
                     payload["arc_note"], now()),
                )


# ---------------------------------------------------------------- Foreshadow / Scheme
class ForeshadowDAO:
    @staticmethod
    def open_before(chapter_no: int) -> list[dict]:
        rows = _rows_to_list(_conn().execute(
            "SELECT * FROM foreshadow WHERE status='open' AND planted_chapter < ? ORDER BY planted_chapter",
            (chapter_no,),
        ).fetchall())
        for r in rows:
            r["evidence"] = _pj(r.pop("evidence_json"), [])
        return rows

    @staticmethod
    def overdue(chapter_no: int) -> list[dict]:
        rows = _rows_to_list(_conn().execute(
            "SELECT * FROM foreshadow WHERE status='open' AND due_chapter IS NOT NULL AND due_chapter <= ?",
            (chapter_no,),
        ).fetchall())
        for r in rows:
            r["evidence"] = _pj(r.pop("evidence_json"), [])
        return rows

    @staticmethod
    def add(planted_chapter: int, summary: str, due_chapter: int | None = None) -> int:
        with tx() as c:
            cur = c.execute(
                "INSERT INTO foreshadow (planted_chapter, due_chapter, summary, evidence_json, created_at) VALUES (?,?,?,?,?)",
                (planted_chapter, due_chapter, summary, "[]", now()),
            )
            return cur.lastrowid

    @staticmethod
    def mark_paid(foreshadow_id: int, chapter_no: int) -> None:
        with tx() as c:
            c.execute(
                "UPDATE foreshadow SET status='paid', payoff_chapter=? WHERE id=?",
                (chapter_no, foreshadow_id),
            )


class SchemeDAO:
    @staticmethod
    def list_all() -> list[dict]:
        rows = _rows_to_list(_conn().execute("SELECT * FROM scheme ORDER BY chapter_planted").fetchall())
        for r in rows:
            r["evidence"] = _pj(r.pop("evidence_json"), [])
        return rows

    @staticmethod
    def get(scheme_id: str) -> dict | None:
        row = _conn().execute("SELECT * FROM scheme WHERE id=?", (scheme_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["evidence"] = _pj(d.pop("evidence_json"), [])
        return d

    @staticmethod
    def active_at(chapter_no: int) -> list[dict]:
        """本章应该涉及的 Scheme：已埋未收。"""
        rows = _rows_to_list(_conn().execute(
            """SELECT * FROM scheme
               WHERE chapter_planted <= ?
                 AND (chapter_resolved IS NULL OR chapter_resolved >= ?)
               ORDER BY chapter_planted""",
            (chapter_no, chapter_no),
        ).fetchall())
        for r in rows:
            r["evidence"] = _pj(r.pop("evidence_json"), [])
        return rows

    @staticmethod
    def upsert(scheme_id: str, **fields) -> None:
        existing = SchemeDAO.get(scheme_id)
        payload = {
            "name": fields.get("name", ""),
            "kind": fields.get("kind", ""),
            "architect": fields.get("architect"),
            "target": fields.get("target"),
            "chapter_planted": fields.get("chapter_planted"),
            "chapter_armed": fields.get("chapter_armed"),
            "chapter_triggered": fields.get("chapter_triggered"),
            "chapter_resolved": fields.get("chapter_resolved"),
            "information_gap": fields.get("information_gap"),
            "mechanism": fields.get("mechanism"),
            "countermeasure": fields.get("countermeasure"),
            "status": fields.get("status", "planted"),
            "evidence": fields.get("evidence", []),
        }
        with tx() as c:
            if existing:
                c.execute(
                    """UPDATE scheme SET name=?, kind=?, architect=?, target=?,
                       chapter_planted=?, chapter_armed=?, chapter_triggered=?,
                       chapter_resolved=?, information_gap=?, mechanism=?,
                       countermeasure=?, status=?, evidence_json=?, updated_at=?
                       WHERE id=?""",
                    (payload["name"], payload["kind"], payload["architect"], payload["target"],
                     payload["chapter_planted"], payload["chapter_armed"], payload["chapter_triggered"],
                     payload["chapter_resolved"], payload["information_gap"], payload["mechanism"],
                     payload["countermeasure"], payload["status"], _j(payload["evidence"]),
                     now(), scheme_id),
                )
            else:
                c.execute(
                    """INSERT INTO scheme
                       (id, name, kind, architect, target, chapter_planted, chapter_armed,
                        chapter_triggered, chapter_resolved, information_gap, mechanism,
                        countermeasure, status, evidence_json, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (scheme_id, payload["name"], payload["kind"], payload["architect"],
                     payload["target"], payload["chapter_planted"], payload["chapter_armed"],
                     payload["chapter_triggered"], payload["chapter_resolved"],
                     payload["information_gap"], payload["mechanism"], payload["countermeasure"],
                     payload["status"], _j(payload["evidence"]), now(), now()),
                )


# ---------------------------------------------------------------- Outline / Contract
class OutlineDAO:
    @staticmethod
    def list_all() -> list[dict]:
        rows = _rows_to_list(_conn().execute(
            "SELECT * FROM outline_node ORDER BY chapter_no"
        ).fetchall())
        for r in rows:
            r["must_advance"] = _pj(r.pop("must_advance_json"), [])
        return rows

    @staticmethod
    def get(chapter_no: int) -> dict | None:
        row = _conn().execute(
            "SELECT * FROM outline_node WHERE chapter_no=?", (chapter_no,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["must_advance"] = _pj(d.pop("must_advance_json"), [])
        return d

    @staticmethod
    def upsert(chapter_no: int, intent: str, must_advance: list[str],
               arc_id: int | None = None, notes: str | None = None) -> None:
        existing = OutlineDAO.get(chapter_no)
        with tx() as c:
            if existing:
                c.execute(
                    "UPDATE outline_node SET intent=?, must_advance_json=?, arc_id=?, notes=? WHERE chapter_no=?",
                    (intent, _j(must_advance), arc_id, notes, chapter_no),
                )
            else:
                c.execute(
                    "INSERT INTO outline_node (arc_id, chapter_no, intent, must_advance_json, notes) VALUES (?,?,?,?,?)",
                    (arc_id, chapter_no, intent, _j(must_advance), notes),
                )


class ContractDAO:
    @staticmethod
    def get_frozen(chapter_no: int) -> dict | None:
        row = _conn().execute(
            "SELECT * FROM contract WHERE chapter_no=? AND status='frozen' ORDER BY version DESC LIMIT 1",
            (chapter_no,),
        ).fetchone()
        return ContractDAO._hydrate(row)

    @staticmethod
    def get_draft(chapter_no: int) -> dict | None:
        row = _conn().execute(
            "SELECT * FROM contract WHERE chapter_no=? AND status='draft' ORDER BY version DESC LIMIT 1",
            (chapter_no,),
        ).fetchone()
        return ContractDAO._hydrate(row)

    @staticmethod
    def _hydrate(row: sqlite3.Row | None) -> dict | None:
        if not row:
            return None
        d = dict(row)
        d["scenes"] = _pj(d.pop("scenes_json"), [])
        d["must_advance"] = _pj(d.pop("must_advance_json"), [])
        d["plant"] = _pj(d.pop("plant_json"), [])
        d["payoff"] = _pj(d.pop("payoff_json"), [])
        d["forbid"] = _pj(d.pop("forbid_json"), [])
        d["domain_inject"] = _pj(d.pop("domain_inject_json"), [])
        # 从 outline 补 title
        if not d.get("title"):
            oln = _conn().execute(
                "SELECT notes FROM outline_node WHERE chapter_no=?",
                (d["chapter_no"],),
            ).fetchone()
            if oln and oln["notes"]:
                d["title"] = oln["notes"]
        return d

    @staticmethod
    def save_draft(chapter_no: int, payload: dict) -> int:
        """保存草稿合同，version 自增。"""
        with tx() as c:
            cur = c.execute(
                "SELECT COALESCE(MAX(version),0) AS v FROM contract WHERE chapter_no=?",
                (chapter_no,),
            )
            next_v = (cur.fetchone()["v"] or 0) + 1
            c.execute(
                """INSERT INTO contract
                   (chapter_no, version, pov_character_id, scenes_json, must_advance_json,
                    plant_json, payoff_json, forbid_json, tone, word_target,
                    domain_inject_json, status, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (chapter_no, next_v, payload.get("pov_character_id"),
                 _j(payload.get("scenes", [])), _j(payload.get("must_advance", [])),
                 _j(payload.get("plant", [])), _j(payload.get("payoff", [])),
                 _j(payload.get("forbid", [])), payload.get("tone"),
                 payload.get("word_target", 3500), _j(payload.get("domain_inject", [])),
                 "draft", now()),
            )
            return cur.lastrowid

    @staticmethod
    def freeze(chapter_no: int, version: int, content_hash: str) -> None:
        with tx() as c:
            c.execute(
                "UPDATE contract SET status='superseded' WHERE chapter_no=? AND status='frozen'",
                (chapter_no,),
            )
            c.execute(
                "UPDATE contract SET status='frozen', frozen_at=?, hash=? WHERE chapter_no=? AND version=?",
                (now(), content_hash, chapter_no, version),
            )

    @staticmethod
    def unfreeze(chapter_no: int) -> None:
        """把当前 frozen 合同退回 draft，允许重编。"""
        with tx() as c:
            c.execute(
                "UPDATE contract SET status='draft', frozen_at=NULL, hash=NULL "
                "WHERE chapter_no=? AND status='frozen'",
                (chapter_no,),
            )

    @staticmethod
    def update_draft(chapter_no: int, payload: dict) -> int:
        """更新当前 draft（不新增版本）；没有 draft 就新建。"""
        row = _conn().execute(
            "SELECT id FROM contract WHERE chapter_no=? AND status='draft' "
            "ORDER BY version DESC LIMIT 1",
            (chapter_no,),
        ).fetchone()
        if not row:
            return ContractDAO.save_draft(chapter_no, payload)
        with tx() as c:
            c.execute(
                """UPDATE contract SET
                   pov_character_id=?, scenes_json=?, must_advance_json=?,
                   plant_json=?, payoff_json=?, forbid_json=?, tone=?,
                   word_target=?, domain_inject_json=?
                   WHERE id=?""",
                (
                    payload.get("pov_character_id"),
                    _j(payload.get("scenes", [])),
                    _j(payload.get("must_advance", [])),
                    _j(payload.get("plant", [])),
                    _j(payload.get("payoff", [])),
                    _j(payload.get("forbid", [])),
                    payload.get("tone"),
                    payload.get("word_target", 3500),
                    _j(payload.get("domain_inject", [])),
                    row["id"],
                ),
            )
        return row["id"]


# ---------------------------------------------------------------- Chapter / Issue
class ChapterDAO:
    @staticmethod
    def list_all() -> list[dict]:
        return _rows_to_list(_conn().execute(
            "SELECT chapter_no, title, word_count, status, tension, accepted_at, updated_at "
            "FROM chapter ORDER BY chapter_no"
        ).fetchall())

    @staticmethod
    def get(chapter_no: int) -> dict | None:
        return _row_to_dict(_conn().execute(
            "SELECT * FROM chapter WHERE chapter_no=?", (chapter_no,)
        ).fetchone())

    @staticmethod
    def save(chapter_no: int, body_md: str, contract_id: int | None,
             title: str | None = None, summary: str | None = None,
             tension: int | None = None) -> None:
        # 保护：拒绝空正文覆盖已有正文
        if not body_md or len(body_md.strip()) < 100:
            existing = _conn().execute(
                "SELECT LENGTH(body_md) AS n FROM chapter WHERE chapter_no=?",
                (chapter_no,),
            ).fetchone()
            if existing and (existing["n"] or 0) > 0:
                raise ValueError(
                    f"拒绝空正文覆盖第 {chapter_no} 章（原有 {existing['n']} 字符）"
                )
        wc = len(body_md.replace(" ", "").replace("\n", ""))
        existing = ChapterDAO.get(chapter_no)
        # 若没传 title，从 outline 里兜底
        if not title:
            row = _conn().execute(
                "SELECT notes FROM outline_node WHERE chapter_no=?", (chapter_no,)
            ).fetchone()
            if row and row["notes"]:
                title = row["notes"]
        with tx() as c:
            if existing:
                c.execute(
                    """UPDATE chapter SET contract_id=?, title=?, body_md=?, word_count=?,
                       summary=?, tension=?, updated_at=? WHERE chapter_no=?""",
                    (contract_id, title or existing.get("title"), body_md, wc,
                     summary, tension, now(), chapter_no),
                )
            else:
                c.execute(
                    """INSERT INTO chapter
                       (chapter_no, contract_id, title, body_md, word_count,
                        summary, tension, status, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (chapter_no, contract_id, title, body_md, wc, summary, tension,
                     "draft", now()),
                )

    @staticmethod
    def set_status(chapter_no: int, status: str) -> None:
        with tx() as c:
            if status == "accepted":
                c.execute(
                    "UPDATE chapter SET status=?, accepted_at=?, updated_at=? WHERE chapter_no=?",
                    (status, now(), now(), chapter_no),
                )
            else:
                c.execute(
                    "UPDATE chapter SET status=?, updated_at=? WHERE chapter_no=?",
                    (status, now(), chapter_no),
                )

    @staticmethod
    def save_extracted(chapter_no: int, extracted: dict, body_hash: str) -> None:
        """存 write_chapter 最后的抽取结果，供验收复用。"""
        with tx() as c:
            c.execute(
                "UPDATE chapter SET latest_extracted_json=?, latest_extracted_body_hash=? "
                "WHERE chapter_no=?",
                (_j(extracted), body_hash, chapter_no),
            )

    @staticmethod
    def get_extracted(chapter_no: int, current_body: str) -> dict | None:
        """读缓存的抽取结果；body 变过就返回 None。"""
        import hashlib
        row = _conn().execute(
            "SELECT latest_extracted_json, latest_extracted_body_hash "
            "FROM chapter WHERE chapter_no=?",
            (chapter_no,),
        ).fetchone()
        if not row or not row["latest_extracted_json"]:
            return None
        body_hash = hashlib.sha256(current_body.encode("utf-8")).hexdigest()
        if row["latest_extracted_body_hash"] != body_hash:
            return None   # body 变了，缓存过期
        return _pj(row["latest_extracted_json"], None)


class IssueDAO:
    @staticmethod
    def list_by_chapter(chapter_no: int, status: str | None = None) -> list[dict]:
        if status:
            rows = _rows_to_list(_conn().execute(
                "SELECT * FROM issue WHERE chapter_no=? AND status=? ORDER BY severity, id",
                (chapter_no, status),
            ).fetchall())
        else:
            rows = _rows_to_list(_conn().execute(
                "SELECT * FROM issue WHERE chapter_no=? ORDER BY severity, id",
                (chapter_no,),
            ).fetchall())
        for r in rows:
            r["evidence"] = _pj(r.pop("evidence_json"), [])
        return rows

    @staticmethod
    def count_open_blockers(chapter_no: int) -> int:
        row = _conn().execute(
            "SELECT COUNT(*) AS n FROM issue WHERE chapter_no=? AND severity='blocker' AND status='open'",
            (chapter_no,),
        ).fetchone()
        return row["n"] if row else 0

    @staticmethod
    def add(chapter_no: int, severity: str, code: str, title: str,
            detail: str = "", evidence: list | None = None,
            suggestion: str = "") -> int:
        with tx() as c:
            cur = c.execute(
                """INSERT INTO issue
                   (chapter_no, severity, code, title, detail, evidence_json,
                    suggestion, status, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (chapter_no, severity, code, title, detail, _j(evidence or []),
                 suggestion, "open", now()),
            )
            return cur.lastrowid

    @staticmethod
    def resolve(issue_id: int, resolved_by: str) -> None:
        with tx() as c:
            c.execute(
                "UPDATE issue SET status='resolved', resolved_by=?, resolved_at=? WHERE id=?",
                (resolved_by, now(), issue_id),
            )

    @staticmethod
    def clear_chapter(chapter_no: int) -> None:
        """重跑前清掉本章上一轮自动报出的问题（保留人工豁免）。"""
        with tx() as c:
            c.execute(
                "DELETE FROM issue WHERE chapter_no=? AND resolved_by IS NULL",
                (chapter_no,),
            )


# ---------------------------------------------------------------- Fact / Job / Setting
class FactDAO:
    @staticmethod
    def list_by_chapter(chapter_no: int) -> list[dict]:
        return _rows_to_list(_conn().execute(
            "SELECT * FROM fact_ledger WHERE chapter_no=? ORDER BY id", (chapter_no,)
        ).fetchall())

    @staticmethod
    def find(subject: str | None = None, predicate: str | None = None,
             kind: str | None = None) -> list[dict]:
        where, vals = [], []
        if subject:
            where.append("subject=?"); vals.append(subject)
        if predicate:
            where.append("predicate=?"); vals.append(predicate)
        if kind:
            where.append("kind=?"); vals.append(kind)
        sql = "SELECT * FROM fact_ledger"
        if where:
            sql += " WHERE " + " AND ".join(where)
        return _rows_to_list(_conn().execute(sql, vals).fetchall())

    @staticmethod
    def add_many(chapter_no: int, facts: list[dict]) -> None:
        with tx() as c:
            for f in facts:
                c.execute(
                    """INSERT INTO fact_ledger
                       (chapter_no, kind, subject, predicate, object, confidence,
                        evidence, paragraph_idx, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (chapter_no, f.get("kind"), f.get("subject"), f.get("predicate"),
                     f.get("object"), f.get("confidence"), f.get("evidence"),
                     f.get("paragraph_idx"), now()),
                )


class JobDAO:
    @staticmethod
    def create(job_id: str, kind: str, chapter_no: int | None) -> None:
        with tx() as c:
            c.execute(
                """INSERT INTO job (id, kind, chapter_no, status, progress, step, message,
                   created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                (job_id, kind, chapter_no, "running", 0, "init", "初始化", now(), now()),
            )

    @staticmethod
    def get(job_id: str) -> dict | None:
        row = _conn().execute("SELECT * FROM job WHERE id=?", (job_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["result"] = _pj(d.pop("result_json"), None)
        return d

    @staticmethod
    def update(job_id: str, *, progress: int | None = None, step: str | None = None,
               message: str | None = None, status: str | None = None,
               result: dict | None = None, error: str | None = None) -> None:
        sets, vals = ["updated_at=?"], [now()]
        if progress is not None: sets.append("progress=?"); vals.append(progress)
        if step is not None: sets.append("step=?"); vals.append(step)
        if message is not None: sets.append("message=?"); vals.append(message)
        if status is not None: sets.append("status=?"); vals.append(status)
        if result is not None: sets.append("result_json=?"); vals.append(_j(result))
        if error is not None: sets.append("error=?"); vals.append(error)
        vals.append(job_id)
        with tx() as c:
            c.execute(f"UPDATE job SET {', '.join(sets)} WHERE id=?", vals)


class SettingDAO:
    @staticmethod
    def get(key: str, default: Any = None) -> Any:
        row = _conn().execute("SELECT value_json FROM setting WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        return _pj(row["value_json"], default)

    @staticmethod
    def set(key: str, value: Any) -> None:
        with tx() as c:
            c.execute(
                """INSERT INTO setting (key, value_json, updated_at) VALUES (?,?,?)
                   ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,
                                                  updated_at=excluded.updated_at""",
                (key, _j(value), now()),
            )


# ---------------------------------------------------------------- Domain KB
class DomainDAO:
    @staticmethod
    def terms_for_chapter(chapter_no: int) -> list[dict]:
        """优先按合同 domain_inject 过滤；无匹配则返回全部。"""
        contract = ContractDAO.get_frozen(chapter_no) or ContractDAO.get_draft(chapter_no)
        rows = _rows_to_list(_conn().execute("SELECT * FROM domain_term").fetchall())
        for r in rows:
            r["misuse_examples"] = _pj(r.pop("misuse_examples"), [])
            r["source_chapters"] = _pj(r.pop("source_chapters"), [])
        if not contract:
            return rows
        inject = contract.get("domain_inject") or []
        if not inject:
            return rows
        out = []
        for item in inject:
            for t in rows:
                if item in t["term"] or t["term"] in item:
                    out.append(t)
                    break
        return out or rows

    @staticmethod
    def stage_by_name(name: str) -> dict | None:
        row = _conn().execute("SELECT * FROM process_stage WHERE name=?", (name,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["actors"] = _pj(d.pop("actors"), [])
        d["artifacts"] = _pj(d.pop("artifacts"), [])
        d["traps"] = _pj(d.pop("traps"), [])
        return d

    @staticmethod
    def stages_all() -> list[dict]:
        rows = _rows_to_list(_conn().execute("SELECT * FROM process_stage ORDER BY stage_order").fetchall())
        for r in rows:
            r["actors"] = _pj(r.pop("actors"), [])
            r["artifacts"] = _pj(r.pop("artifacts"), [])
            r["traps"] = _pj(r.pop("traps"), [])
        return rows

    @staticmethod
    def era_for_year(year: int) -> list[dict]:
        rows = _rows_to_list(_conn().execute(
            "SELECT * FROM era_detail WHERE year=?", (year,)
        ).fetchall())
        for r in rows:
            r["forbidden_anachronism"] = _pj(r.pop("forbidden_anachronism"), [])
        return rows

    @staticmethod
    def all_terms() -> list[dict]:
        return _rows_to_list(_conn().execute("SELECT * FROM domain_term ORDER BY term").fetchall())

    @staticmethod
    def add_term(term: str, category: str, definition: str,
                 era_from: int | None = None, era_to: int | None = None,
                 misuse_examples: list[str] | None = None,
                 source_chapters: list | None = None) -> int:
        with tx() as c:
            try:
                cur = c.execute(
                    """INSERT INTO domain_term
                       (term, category, definition, era_from, era_to, misuse_examples, source_chapters)
                       VALUES (?,?,?,?,?,?,?)""",
                    (term, category, definition, era_from, era_to,
                     _j(misuse_examples or []), _j(source_chapters or [])),
                )
                return cur.lastrowid
            except sqlite3.IntegrityError:
                return -1

    @staticmethod
    def add_era(year: int, category: str, fact: str,
                forbidden_anachronism: list[str] | None = None,
                source_chapters: list | None = None) -> int:
        with tx() as c:
            cur = c.execute(
                """INSERT INTO era_detail (year, category, fact, forbidden_anachronism, source_chapters)
                   VALUES (?,?,?,?,?)""",
                (year, category, fact, _j(forbidden_anachronism or []), _j(source_chapters or [])),
            )
            return cur.lastrowid

    @staticmethod
    def add_stage(name: str, stage_order: int, actors: list, artifacts: list,
                  traps: list, source_chapters: list) -> int:
        with tx() as c:
            try:
                cur = c.execute(
                    """INSERT INTO process_stage
                       (name, stage_order, actors, artifacts, traps, source_chapters)
                       VALUES (?,?,?,?,?,?)""",
                    (name, stage_order, _j(actors), _j(artifacts),
                     _j(traps), _j(source_chapters)),
                )
                return cur.lastrowid
            except sqlite3.IntegrityError:
                return -1

# ---------------------------------------------------------------- Extractor cache / LLM log
class ExtractorCacheDAO:
    @staticmethod
    def get(key: str) -> dict | None:
        row = _conn().execute(
            "SELECT output_json FROM extractor_cache WHERE key=?", (key,)
        ).fetchone()
        if not row:
            return None
        return _pj(row["output_json"], None)

    @staticmethod
    def put(key: str, chapter_no: int, output: dict) -> None:
        with tx() as c:
            c.execute(
                """INSERT OR REPLACE INTO extractor_cache (key, chapter_no, output_json, created_at)
                   VALUES (?,?,?,?)""",
                (key, chapter_no, _j(output), now()),
            )


class LLMLogDAO:
    @staticmethod
    def log(agent: str, chapter_no: int | None, model: str | None,
            prompt_tokens: int | None, completion_tokens: int | None,
            latency_ms: int | None, ok: bool, error: str | None = None) -> None:
        with tx() as c:
            c.execute(
                """INSERT INTO llm_call_log
                   (agent, chapter_no, model, prompt_tokens, completion_tokens,
                    latency_ms, ok, error, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (agent, chapter_no, model, prompt_tokens, completion_tokens,
                 latency_ms, 1 if ok else 0, error, now()),
            )


# ---------------------------------------------------------------- 初始化入口
# def bootstrap_from_contracts(contracts: list[dict]) -> None:
#     """从 36 章合同批量初始化。"""
#     init_db()
#     for c in contracts:
#         ContractDAO.save_draft(c["chapter_no"], c)
#     for s in schemes:
#         payload = {k: v for k, v in s.items() if k != "id"}
#         SchemeDAO.upsert(s["id"], **payload)
#     for t in _DOMAIN_TERM_SEED:
#         DomainDAO.add_term(**t)
#     for e in _ERA_DETAIL_SEED:
#         DomainDAO.add_era(**e)


SEED_DIR = Path(__file__).parent / "seed"

# ---------------------------------------------------------------- Prop DAO
class PropDAO:
    @staticmethod
    def list_all() -> list[dict]:
        rows = _rows_to_list(_conn().execute("SELECT * FROM prop ORDER BY id").fetchall())
        for r in rows:
            r["aliases"] = _pj(r.pop("aliases_json"), [])
            r["reference_images"] = _pj(r.pop("reference_images_json", "[]"), [])
        return rows

    @staticmethod
    def by_name(name: str) -> dict | None:
        row = _conn().execute("SELECT * FROM prop WHERE name=?", (name,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["aliases"] = _pj(d.pop("aliases_json"), [])
        d["reference_images"] = _pj(d.pop("reference_images_json", "[]"), [])
        return d

    @staticmethod
    def upsert(name: str, **fields) -> int:
        existing = PropDAO.by_name(name)
        with tx() as c:
            if existing:
                sets, vals = [], []
                for k, v in fields.items():
                    if k in {"aliases", "reference_images"}:
                        sets.append(f"{k}_json=?")
                        vals.append(_j(v))
                    elif k in {"visual_prompt", "first_chapter", "notes"}:
                        sets.append(f"{k}=?")
                        vals.append(v)
                if sets:
                    vals.append(existing["id"])
                    c.execute(f"UPDATE prop SET {', '.join(sets)} WHERE id=?", vals)
                return existing["id"]
            cur = c.execute(
                """INSERT INTO prop
                   (name, aliases_json, visual_prompt, reference_images_json,
                    first_chapter, notes)
                   VALUES (?,?,?,?,?,?)""",
                (name, _j(fields.get("aliases", [])),
                 fields.get("visual_prompt"),
                 _j(fields.get("reference_images", [])),
                 fields.get("first_chapter"), fields.get("notes")),
            )
            return cur.lastrowid


# ---------------------------------------------------------------- Storyboard DAO
class StoryboardDAO:
    @staticmethod
    def get(chapter_no: int) -> dict | None:
        row = _conn().execute(
            "SELECT * FROM storyboard WHERE chapter_no=?", (chapter_no,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["style"] = _pj(d.pop("style_json", "{}"), {})
        return d

    @staticmethod
    def upsert(chapter_no: int, **fields) -> None:
        existing = StoryboardDAO.get(chapter_no)
        payload = {
            "total_shots": fields.get("total_shots", 0),
            "estimated_duration_sec": fields.get("estimated_duration_sec"),
            "style": fields.get("style", {}),
            "status": fields.get("status", "draft"),
            "error": fields.get("error"),
        }
        with tx() as c:
            if existing:
                c.execute(
                    """UPDATE storyboard SET total_shots=?, estimated_duration_sec=?,
                       style_json=?, status=?, error=?, updated_at=?
                       WHERE chapter_no=?""",
                    (payload["total_shots"], payload["estimated_duration_sec"],
                     _j(payload["style"]), payload["status"], payload["error"],
                     now(), chapter_no),
                )
            else:
                c.execute(
                    """INSERT INTO storyboard
                       (chapter_no, total_shots, estimated_duration_sec,
                        style_json, status, error, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (chapter_no, payload["total_shots"],
                     payload["estimated_duration_sec"], _j(payload["style"]),
                     payload["status"], payload["error"], now(), now()),
                )

    @staticmethod
    def delete_shots(chapter_no: int) -> None:
        with tx() as c:
            c.execute("DELETE FROM storyboard_shot WHERE chapter_no=?", (chapter_no,))


class StoryboardShotDAO:
    @staticmethod
    def list_by_chapter(chapter_no: int) -> list[dict]:
        rows = _rows_to_list(_conn().execute(
            "SELECT * FROM storyboard_shot WHERE chapter_no=? ORDER BY shot_id",
            (chapter_no,),
        ).fetchall())
        for r in rows:
            r["characters"] = _pj(r.pop("characters_json"), [])
            r["props"] = _pj(r.pop("props_json"), [])
        return rows

    @staticmethod
    def get(chapter_no: int, shot_id: int) -> dict | None:
        row = _conn().execute(
            "SELECT * FROM storyboard_shot WHERE chapter_no=? AND shot_id=?",
            (chapter_no, shot_id),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["characters"] = _pj(d.pop("characters_json"), [])
        d["props"] = _pj(d.pop("props_json"), [])
        return d

    @staticmethod
    def upsert(chapter_no: int, shot_id: int, **fields) -> int:
        existing = StoryboardShotDAO.get(chapter_no, shot_id)

        # 已存在：只更新传入的字段，未传的保留原值
        if existing:
            sets, vals = [], []
            for k, v in fields.items():
                if k in {"characters", "props"}:
                    sets.append(f"{k}_json=?")
                    vals.append(_j(v))
                elif k in {"scene_idx", "duration_sec", "shot_type", "location",
                           "time_of_day", "action", "dialogue", "emotion",
                           "camera_movement", "text_ref", "image_path",
                           "prompt_used", "status", "error"}:
                    sets.append(f"{k}=?")
                    vals.append(v)
            if sets:
                sets.append("updated_at=?")
                vals.append(now())
                vals.append(chapter_no)
                vals.append(shot_id)
                with tx() as c:
                    c.execute(
                        f"UPDATE storyboard_shot SET {', '.join(sets)} "
                        f"WHERE chapter_no=? AND shot_id=?",
                        vals,
                    )
            return existing["id"]

        # 新建：用传入字段 + 默认值
        payload = {
            "scene_idx": fields.get("scene_idx"),
            "duration_sec": fields.get("duration_sec"),
            "shot_type": fields.get("shot_type"),
            "characters": fields.get("characters", []),
            "location": fields.get("location"),
            "time_of_day": fields.get("time_of_day"),
            "action": fields.get("action"),
            "dialogue": fields.get("dialogue"),
            "emotion": fields.get("emotion"),
            "camera_movement": fields.get("camera_movement"),
            "text_ref": fields.get("text_ref"),
            "props": fields.get("props", []),
            "image_path": fields.get("image_path"),
            "prompt_used": fields.get("prompt_used"),
            "status": fields.get("status", "pending"),
            "error": fields.get("error"),
        }
        with tx() as c:
            cur = c.execute(
                """INSERT INTO storyboard_shot
                   (chapter_no, shot_id, scene_idx, duration_sec, shot_type,
                    characters_json, location, time_of_day, action, dialogue,
                    emotion, camera_movement, text_ref, props_json,
                    image_path, prompt_used, status, error,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (chapter_no, shot_id, payload["scene_idx"], payload["duration_sec"],
                 payload["shot_type"], _j(payload["characters"]), payload["location"],
                 payload["time_of_day"], payload["action"], payload["dialogue"],
                 payload["emotion"], payload["camera_movement"], payload["text_ref"],
                 _j(payload["props"]), payload["image_path"], payload["prompt_used"],
                 payload["status"], payload["error"], now(), now()),
            )
            return cur.lastrowid


def bootstrap_from_seed() -> dict:
    """首次启动时调用。幂等：已导入过就跳过。返回各表条数。"""
    init_db()
    conn = _conn()
    counts: dict[str, int] = {}

    # contracts
    n = conn.execute("SELECT COUNT(*) AS n FROM contract").fetchone()["n"]
    if n == 0:
        data = json.loads((SEED_DIR / "contracts.json").read_text(encoding="utf-8"))
        for c in data["contracts"]:
            ContractDAO.save_draft(c["chapter_no"], c)
    counts["contract"] = conn.execute(
        "SELECT COUNT(*) AS n FROM contract").fetchone()["n"]

    # schemes
    n = conn.execute("SELECT COUNT(*) AS n FROM scheme").fetchone()["n"]
    if n == 0:
        schemes = json.loads((SEED_DIR / "schemes.json").read_text(encoding="utf-8"))
        for s in schemes:
            payload = {k: v for k, v in s.items() if k != "id"}
            SchemeDAO.upsert(s["id"], **payload)
    counts["scheme"] = conn.execute(
        "SELECT COUNT(*) AS n FROM scheme").fetchone()["n"]

    # domain_terms
    n = conn.execute("SELECT COUNT(*) AS n FROM domain_term").fetchone()["n"]
    if n == 0:
        terms = json.loads((SEED_DIR / "domain_terms.json").read_text(encoding="utf-8"))
        for t in terms:
            DomainDAO.add_term(**t)
    counts["domain_term"] = conn.execute(
        "SELECT COUNT(*) AS n FROM domain_term").fetchone()["n"]

    # process_stages
    n = conn.execute("SELECT COUNT(*) AS n FROM process_stage").fetchone()["n"]
    if n == 0:
        stages = json.loads((SEED_DIR / "process_stages.json").read_text(encoding="utf-8"))
        for s in stages:
            DomainDAO.add_stage(**s)
    counts["process_stage"] = conn.execute(
        "SELECT COUNT(*) AS n FROM process_stage").fetchone()["n"]

    # era_details
    n = conn.execute("SELECT COUNT(*) AS n FROM era_detail").fetchone()["n"]
    if n == 0:
        eras = json.loads((SEED_DIR / "era_details.json").read_text(encoding="utf-8"))
        for e in eras:
            DomainDAO.add_era(**e)
    counts["era_detail"] = conn.execute(
        "SELECT COUNT(*) AS n FROM era_detail").fetchone()["n"]

    # bible（世界规则 + 角色 + 地点）
    n = conn.execute("SELECT COUNT(*) AS n FROM character").fetchone()["n"]
    if n == 0:
        bible = json.loads((SEED_DIR / "bible.json").read_text(encoding="utf-8"))
        for r in bible.get("rules", []):
            WorldRuleDAO.add(
                category=r.get("category", "规则"),
                statement=r["statement"],
                hard=1 if r.get("hard", True) else 0,
            )
        for ch in bible.get("characters", []):
            CharacterDAO.upsert(
                ch["name"],
                aliases=ch.get("aliases", []),
                role=ch.get("role"),
                voice=ch.get("voice"),
                traits=ch.get("traits", []),
                relations=ch.get("relations", {}),
                abilities=ch.get("abilities", []),
                status=ch.get("status", "alive"),
                appearance_prompt=ch.get("appearance_prompt"),
                appearance_notes=ch.get("appearance_notes"),
                reference_images=ch.get("reference_images", []),
                costumes=ch.get("costumes", []),
            )
        for lc in bible.get("locations", []):
            LocationDAO.upsert(
                lc["name"],
                aliases=lc.get("aliases", []),
                region=lc.get("region"),
                traits=lc.get("traits", []),
                visual_prompt=lc.get("visual_prompt"),
                lighting_notes=lc.get("lighting_notes"),
                reference_images=lc.get("reference_images", []),
            )
    counts["character"] = conn.execute(
        "SELECT COUNT(*) AS n FROM character").fetchone()["n"]

    # outline（部 + 每章标题 + 意图）
    n = conn.execute("SELECT COUNT(*) AS n FROM outline_node").fetchone()["n"]
    if n == 0:
        ol = json.loads((SEED_DIR / "outline.json").read_text(encoding="utf-8"))
        arc_id_by_idx: dict[int, int] = {}
        for arc in ol.get("arcs", []):
            with tx() as c:
                cur = c.execute(
                    """INSERT INTO arc (idx, title, summary, chapter_from, chapter_to)
                       VALUES (?,?,?,?,?)""",
                    (arc["idx"], arc["title"], arc.get("summary"),
                     arc["chapter_from"], arc["chapter_to"]),
                )
                arc_id_by_idx[arc["idx"]] = cur.lastrowid
        for node in ol.get("outline", []):
            OutlineDAO.upsert(
                chapter_no=node["chapter_no"],
                intent=node.get("intent", ""),
                must_advance=[],  # 由合同表提供
                arc_id=arc_id_by_idx.get(node.get("arc_idx")),
                notes=node.get("title", ""),   # title 暂存在 notes 里
            )
    counts["outline_node"] = conn.execute(
        "SELECT COUNT(*) AS n FROM outline_node").fetchone()["n"]

    # props（可选，从 bible.json 的 props 字段读）
    n = conn.execute("SELECT COUNT(*) AS n FROM prop").fetchone()["n"]
    if n == 0:
        try:
            bible = json.loads((SEED_DIR / "bible.json").read_text(encoding="utf-8"))
            for p in bible.get("props", []) or []:
                PropDAO.upsert(
                    p["name"],
                    aliases=p.get("aliases", []),
                    visual_prompt=p.get("visual_prompt"),
                    first_chapter=p.get("first_chapter"),
                    notes=p.get("notes"),
                )
        except Exception:
            pass
    counts["prop"] = conn.execute("SELECT COUNT(*) AS n FROM prop").fetchone()["n"]
    
    return counts