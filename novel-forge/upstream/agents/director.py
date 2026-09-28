#!/usr/bin/env python3
"""Director：把一章正文拆成分镜脚本。"""
from __future__ import annotations

import json

from ..llm import LLMClient, LLMError


DIRECTOR_SYSTEM = """你是「小说视觉化引擎」的导演（Director）。

# 你的职责
把一章小说正文拆成 N 个分镜镜头（storyboard shots）。

# 拆镜头原则
1. 用户会在 prompt 里指定**目标镜头数**（如 8 个），你必须严格贴近这个数字（±1）
2. 在目标镜头数约束下，优先抓「有画面感」的句子——动作、对话、表情、物件特写
3. 一个镜头 = 一个视觉场景 + 一个动作 + 一句（可选的）台词
4. 纯心理描写、回忆、背景说明——合并进相邻镜头，不单独成镜
5. 每个镜头必须绑定原文片段（text_ref），不脱离文本

# 镜头类型（shot_type）
- extreme_wide：远景（建立环境）
- wide：全景（人物全身 + 环境）
- medium：中景（人物半身）
- close_up：特写（脸部 / 物件）
- extreme_close_up：大特写（眼神 / 细节）

# 镜头运动（camera_movement）
- static：固定机位
- pan_left / pan_right：横摇
- zoom_in / zoom_out：推拉
- dolly：跟随移动

# 时长
- 有台词：3–5 秒
- 无台词纯动作：2–3 秒
- 建立镜头（远景）：3–4 秒

# 输出格式
只输出 JSON，不要解释。

# Schema
{
  "chapter_no": 1,
  "total_shots": 12,
  "estimated_duration_sec": 40,
  "shots": [
    {
      "shot_id": 1,
      "scene_idx": 1,
      "duration_sec": 3,
      "shot_type": "close_up",
      "characters": ["沈砺"],
      "location": "星途南区办公室",
      "time_of_day": "下午",
      "action": "沈砺合上文件，抬眼看向门口",
      "dialogue": null,
      "emotion": "克制、专注",
      "camera_movement": "static",
      "text_ref": "沈砺把回款表的最后两行填完的时候，陆舟没敲门就进来了。",
      "props": []
    }
  ]
}
"""


DIRECTOR_SCHEMA = {
    "type": "object",
    "required": ["chapter_no", "total_shots", "shots"],
    "properties": {
        "chapter_no": {"type": "integer"},
        "total_shots": {"type": "integer"},
        "estimated_duration_sec": {"type": "integer"},
        "shots": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["shot_id", "duration_sec", "shot_type",
                             "action", "text_ref"],
                "properties": {
                    "shot_id": {"type": "integer"},
                    "scene_idx": {"type": "integer"},
                    "duration_sec": {"type": "number"},
                    "shot_type": {
                        "type": "string",
                        "enum": ["extreme_wide", "wide", "medium",
                                 "close_up", "extreme_close_up"]
                    },
                    "characters": {"type": "array", "items": {"type": "string"}},
                    "location": {"type": "string"},
                    "time_of_day": {"type": "string"},
                    "action": {"type": "string"},
                    "dialogue": {"type": ["string", "null"]},
                    "emotion": {"type": "string"},
                    "camera_movement": {
                        "type": "string",
                        "enum": ["static", "pan_left", "pan_right",
                                 "zoom_in", "zoom_out", "dolly"]
                    },
                    "text_ref": {"type": "string"},
                    "props": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}


class DirectorAgent:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def storyboard(
        self,
        chapter_no: int,
        body_md: str,
        contract: dict,
        bible: dict,
        shot_count: int = 8,
    ) -> dict:
        # 只传主要角色和地点，避免 prompt 太长
        main_chars = [
            {"name": c["name"], "role": c.get("role", ""),
             "voice": c.get("voice", "")}
            for c in bible.get("characters", [])[:12]
        ]
        locations = [
            {"name": l["name"], "region": l.get("region", "")}
            for l in bible.get("locations", [])[:10]
        ]
        props = [
            {"name": p["name"], "notes": (p.get("notes") or "")[:60]}
            for p in bible.get("props", [])[:8]
        ]

        user = f"""# 章节
第 {chapter_no} 章

# 目标镜头数
**{shot_count}** 个镜头（±1）。请严格控制在这个数量附近。

# 合同
标题：{contract.get('title', '')}
POV：{contract.get('pov_character_id', '')}
场景：
{json.dumps(contract.get('scenes', []), ensure_ascii=False, indent=2)}

# 主要角色
{json.dumps(main_chars, ensure_ascii=False, indent=2)}

# 主要地点
{json.dumps(locations, ensure_ascii=False, indent=2)}

# 可选道具
{json.dumps(props, ensure_ascii=False, indent=2)}

# 正文（{len(body_md)} 字）
{body_md}

---

请把这章正文拆成分镜脚本。"""

        try:
            raw = self.llm.call_with_schema(
                messages=[
                    {"role": "system", "content": DIRECTOR_SYSTEM},
                    {"role": "user", "content": user},
                ],
                schema=DIRECTOR_SCHEMA,
                model_role="director",
                temperature=0.3,
                chapter_no=chapter_no,
                max_retries=2,
            )
        except LLMError as e:
            raise RuntimeError(f"导演 Agent 调用失败：{e}")

        raw["chapter_no"] = chapter_no
        return raw