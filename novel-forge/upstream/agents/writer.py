#!/usr/bin/env python3
"""Writer：按合同写章节正文。

本文件只负责：
- System Prompt（通用写作方法论）
- User Prompt 模板
- 各上下文块的格式化
- WriterAgent 调用封装

上下文组装（角色卡、地点、规则、活跃 Scheme、前 3 章摘要、上一章结尾、行业约束、
genre_profile）由 orchestrator.build_context_bundle 完成，本文件只做格式化与拼装。
"""
from __future__ import annotations

import json

from ..llm import LLMClient
from .base import strip_fences


# ============================================================
# System Prompt（通用，不含具体书籍内容）
# ============================================================
WRITER_SYSTEM = """你是「小说创作引擎」的写手（Writer）。你的任务不是把合同"翻译"成文字，而是把一个故事讲得让读者放不下。

# 核心原则：每场戏必须是一次博弈

每场戏（scene）必须包含：
1. **某人想要什么**（具体、可执行、有代价）
2. **谁在阻止**（不是抽象阻力，是具体的人或具体的时限）
3. **张力出现**（读者能感到"事情不对"）
4. **反转或升级**（局面在中途变化：想要的变得更重要，或得到的方式变了）
5. **收尾留钩**（不是解决问题，是让问题变复杂）

如果合同里的 goal 太抽象（如"展示某某的专业"），你必须自己拆成 3–5 个具体 beat。**不要用形容词填充，要用动作和对话推进**。

# 事件密度

每 400 字必须发生以下之一：
- **信息揭露**：读者或角色知道了一件此前不知道的事
- **权力转换**：场面上的主动权换手
- **意外**：某个角色的行为超出了预期
- **代价出现**：某人为之前的选择付出代价

连续 400 字都在"描述、铺垫、叙述" = 写崩了，重写。

# 闲笔纪律（关键）

每 800 字必须有 1 处"看起来跟情节无关"的细节：
- 天气、堵车、季节的体感
- 某个角色的怪癖、口头禅、习惯动作
- 一个行业内或生活中的类比、自嘲
- 一个没头没尾的回忆碎片

闲笔要**短**（1–3 句），要**具体**（有物件、有时间、有身体感），
**不要**抒情、**不要**评价、**不要**跟主线硬扯关系。

范例：
> 八月的北京，简直就是一个火炉，盼了好多天的雨，一直像是在和人们逗着玩儿。
> 男人的腰简直就是不可再生的宝贵资源，挣钱的时候要用，花钱的时候也要用。

# 视角纪律

- **允许**记录性内心：'他想起刚才不该吃那顿饭'、'脑子里有个声音说太顺了'
- **禁止**解释性独白：'他明白自己错了'、'他意识到这是个圈套'、'他心里想着'
- 区别：记录是让读者自己得出结论，解释是把结论塞给读者

# 对话的唯一标准：潜台词

- 每句台词必须有**两层**：字面意思 + 真实意图
- 职业高手的话永远**不直说**：他问"你那边的报价准备好了吗"，实际在试探对方的底价区间
- 对话必须**短**：一句能说完的别用两句。三句以上连续台词必须打断
- 禁止"信息交换式"对话（A 问 → B 答 → A 再问 → B 再答，纯粹传递信息）

反面例子（禁止）：
> "这个项目的预算多少？"沈砺问。
> "大约一千万。"客户说。
> "那周期呢？"
> "半年。"

正面例子：
> "你们预算定了吗？"沈砺问。
> 客户笑了一下，端起茶杯。"沈经理，你们是不是都这么急？"

# 场景纪律（硬约束）

合同 scenes 列表里的**每个场景必须在本章出现**，不得跳过。
每场至少 600 字，全部场景合计必须达到 word_target 的 85% 以上。

# 篇幅纪律

word_target 是**下限**，不是上限。
字数不足目标 80% = 写崩了。加戏不加字——让对话多一轮试探、让动作更具体、让配角的反应更明确。
**绝不用环境描写和形容词填充**。

# 文字纪律

**必须做**：
- 场景开头用**具体动作或对话**切入，不铺垫环境
- 每个角色做动作前先有**动机**（哪怕只是"想看看对方反应"）
- 场面温度通过**细节**体现（桌上没喝完的茶、会议室玻璃的反光、谁先动筷子）
- 结尾停在**动作或画面上**，不解释、不总结

**禁止做**：
- 不用"多年以后""此时此刻""命运的齿轮"这类总结式表达
- 不写"他心里想着""他明白""他意识到"
- 不用"我们""他们"这类作者代言
- 不写角色突然变聪明或变蠢
- 不用形容词代替情节

# 上下文用法

- 合同 must_advance / plant / payoff 是**最低要求**，不是内容上限
- 合同 forbid 是**硬边界**，绝对不越
- 合同 tone 是**基调**
- **本书风格指南**里的 tone_keywords / narrative_rules / forbid_global 是**全局约束**
- **本书风格指南**里的 few_shot 是**文风样本**，学节奏和手法，**不抄情节**
- domain_inject 是**专业纹理**，自然融入，不堆砌
- 前情摘要 + 上一章结尾是**承接**，不要重复叙述
- 活跃 Scheme 是**暗线**，读者第一遍不能明显察觉

# 输出格式

只输出正文 Markdown。标题用 `## 第 N 章 · 标题`。
不要任何解释、前言、后记。不要用代码块包裹。
"""


# ============================================================
# User Prompt 模板
# ============================================================
WRITER_USER_TMPL = """# 本章合同
{contract_json}

# 设定约束
## 世界规则
{rules_block}

## 相关角色卡
{characters_block}

## 相关地点
{locations_block}

# 角色当前状态（本章之前）
{prev_states_block}

# 活跃中的局（Scheme）
{active_schemes_block}

# 未回收伏笔
{open_foreshadows_block}

# 前情摘要（最近 3 章）
{prev_summaries_block}

# 上一章结尾
{prev_tail}

# 行业约束
## 术语（用对，不要用错）
{terms_block}

## 流程（顺序不能乱）
{stages_block}

## 年代细节（不能出现后世事物）
{era_block}

---

按 System Prompt 写第 {chapter_no} 章正文。
标题：## 第 {chapter_no} 章 · {title}
"""


# ============================================================
# 格式化辅助
# ============================================================
def _fmt_rules(rules: list[dict]) -> str:
    return "\n".join(
        f"- [{'硬' if r.get('hard') else '软'}] {r.get('statement', '')}"
        for r in rules
    ) or "（无）"


def _fmt_characters(chars: list[dict]) -> str:
    lines = []
    for c in chars:
        aliases = "/".join(c.get("aliases", [])) or "无"
        lines.append(
            f"- {c.get('name', '')}（别名：{aliases}）｜{c.get('role', '')}"
            f"｜声口：{c.get('voice', '')}"
        )
    return "\n".join(lines) or "（无）"


def _fmt_locations(locs: list[dict]) -> str:
    return "\n".join(
        f"- {l.get('name', '')}｜{l.get('region', '')}"
        for l in locs
    ) or "（无）"


def _fmt_prev_states(states: list[dict]) -> str:
    lines = []
    for s in states:
        lines.append(
            f"- 角色 {s.get('character_id')}：{'存活' if s.get('alive') else '已故'}"
            f"｜地点 {s.get('location_id') or '—'}"
            f"｜立场 {s.get('stance') or '—'}"
            f"｜内在 {s.get('inner_state') or '—'}"
        )
    return "\n".join(lines) or "（本章是开局）"


def _fmt_schemes(schemes: list[dict]) -> str:
    lines = []
    for s in schemes:
        lines.append(
            f"- [{s.get('id', '')}] {s.get('name', '')}（{s.get('kind', '')}）"
            f"｜status={s.get('status', '')}"
            f"｜信息差：{s.get('information_gap') or '—'}"
            f"｜机制：{s.get('mechanism') or '—'}"
        )
    return "\n".join(lines) or "（无）"


def _fmt_foreshadows(fs: list[dict]) -> str:
    return "\n".join(
        f"- 第{f.get('planted_chapter')}章埋：{f.get('summary', '')}"
        + (f"（到期第{f.get('due_chapter')}章）" if f.get("due_chapter") else "")
        for f in fs
    ) or "（无）"


def _fmt_terms(terms: list[dict]) -> str:
    lines = []
    for t in terms:
        definition = (t.get("definition") or "")[:80]
        lines.append(f"- {t.get('term', '')}：{definition}")
        misuse = t.get("misuse_examples") or []
        if misuse:
            lines.append(f"  禁用写法：{'；'.join(misuse[:2])}")
    return "\n".join(lines) or "（无）"


def _fmt_stages(stages: list[dict]) -> str:
    return "\n".join(
        f"- 阶段{st.get('stage_order', '')} {st.get('name', '')}"
        f"｜参与方 {','.join(st.get('actors', []) or [])}"
        f"｜陷阱 {','.join((st.get('traps') or [])[:2])}"
        for st in stages
    ) or "（无）"


def _fmt_era(era: list[dict]) -> str:
    lines = []
    for e in era:
        fact = (e.get("fact") or "")[:100]
        lines.append(f"- {e.get('year', '')}·{e.get('category', '')}：{fact}")
        forbidden = e.get("forbidden_anachronism") or []
        if forbidden:
            lines.append(f"  禁止：{'、'.join(forbidden[:4])}")
    return "\n".join(lines) or "（无）"


def _fmt_genre_profile(profile: dict) -> str:
    """格式化本书风格指南（含 few-shot）。空则返回空串。"""
    if not profile:
        return ""

    lines = ["# 本书风格指南"]

    if profile.get("description"):
        lines.append(f"_{profile['description']}_")

    if profile.get("tone_keywords"):
        lines.append("\n**基调**：")
        lines.append(" / ".join(profile["tone_keywords"]))

    if profile.get("narrative_rules"):
        lines.append("\n**叙事规则**：")
        lines += [f"- {r}" for r in profile["narrative_rules"]]

    if profile.get("forbid_global"):
        lines.append("\n**全局禁止**：")
        lines += [f"- {r}" for r in profile["forbid_global"]]

    few_shot = profile.get("few_shot") or []
    if few_shot:
        lines.append("\n**文风示例**（学习节奏、内视角、闲笔方式，**不要照抄情节**）：")
        for i, fs in enumerate(few_shot, 1):
            title = fs.get("title") or f"示例 {i}"
            text = fs.get("text") or ""
            lines.append(f"\n## {title}")
            lines.append(text)

    return "\n".join(lines)


# ============================================================
# 主入口：拼 prompt
# ============================================================
def build_writer_prompt(chapter_no: int, bundle: dict) -> str:
    c = bundle.get("contract") or {}
    base = WRITER_USER_TMPL.format(
        chapter_no=chapter_no,
        title=c.get("title", "无题"),
        contract_json=json.dumps(c, ensure_ascii=False, indent=2),
        rules_block=_fmt_rules(bundle.get("rules", [])),
        characters_block=_fmt_characters(bundle.get("characters", [])),
        locations_block=_fmt_locations(bundle.get("locations", [])),
        prev_states_block=_fmt_prev_states(bundle.get("prev_states", [])),
        active_schemes_block=_fmt_schemes(bundle.get("active_schemes", [])),
        open_foreshadows_block=_fmt_foreshadows(bundle.get("open_foreshadows", [])),
        prev_summaries_block="\n".join(
            f"- {s}" for s in bundle.get("prev_summaries", [])
        ) or "（无）",
        prev_tail=bundle.get("prev_tail") or "（本章是第一章）",
        terms_block=_fmt_terms((bundle.get("domain_ctx") or {}).get("terms", [])),
        stages_block=_fmt_stages((bundle.get("domain_ctx") or {}).get("stages", [])),
        era_block=_fmt_era((bundle.get("domain_ctx") or {}).get("era_facts", [])),
    )

    # 拼接本书风格指南
    profile_block = _fmt_genre_profile(bundle.get("genre_profile") or {})
    if profile_block:
        return base + "\n\n" + profile_block
    return base


# ============================================================
# WriterAgent
# ============================================================
class WriterAgent:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def write(self, chapter_no: int, bundle: dict) -> str:
        messages = [
            {"role": "system", "content": WRITER_SYSTEM},
            {"role": "user", "content": build_writer_prompt(chapter_no, bundle)},
        ]

        # max_tokens：word_target 是中文数字，1 汉字 ≈ 1.5–2 token
        word_target = (bundle.get("contract") or {}).get("word_target", 3500)
        max_out = max(4000, int(word_target * 3))

        body = self.llm.call(
            messages=messages,
            model_role="writer",
            temperature=0.75,
            max_tokens=max_out,
            chapter_no=chapter_no,
            max_retries=2,
        )

        cleaned = strip_fences(body)
        if not cleaned or not cleaned.strip():
            raise RuntimeError(
                f"Writer 返回空正文（chapter_no={chapter_no}）"
            )
        return cleaned