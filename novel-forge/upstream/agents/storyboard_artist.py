#!/usr/bin/env python3
"""Storyboard Artist：把镜头描述渲染成故事板图。"""
from __future__ import annotations

import base64
import json
import os
import urllib.request
import urllib.error
from pathlib import Path

from .. import store
from .. import hellome_llm_config as llm_cfg


DEFAULT_STYLE = {
    "positive_suffix": (
        "storyboard sketch, hand-drawn line art, comic style, "
        "cinematic composition, monochrome with warm sepia tone, "
        "film noir mood, visible sketch lines, clean linework, "
        "flat coloring, professional film storyboard"
    ),
    "negative_suffix": (
        "photo, photorealistic, 3d render, blurry, low quality, "
        "watermark, text overlay, signature, distorted faces"
    ),
    "aspect_ratio": "16:9",
    "default_size": "2560x1440",
    "fallback_size": "2048x2048",
}


def _size_pixels(size: str) -> int:
    """'1024x576' → 589824。解析失败返回 0。"""
    try:
        w, h = size.lower().split("x")
        return int(w) * int(h)
    except Exception:
        return 0


# Seedream 等模型要求的最小像素数（3,686,400 = 1920×1920）
_MIN_PIXELS = 3686400


def _ensure_min_size(size: str) -> str:
    """把过小的尺寸升到最小像素数之上。已经是 16:9 的优先保持 16:9。"""
    if _size_pixels(size) >= _MIN_PIXELS:
        return size
    # 常见 16:9 候选，从最接近用户的开始
    for candidate in ("2560x1440", "3072x1728", "3840x2160", "2048x2048"):
        if _size_pixels(candidate) >= _MIN_PIXELS:
            return candidate
    return "2048x2048"


class StoryboardArtist:
    """渲染单张分镜图。每张图独立调用，失败可单独重试。"""

    def __init__(self):
        pass

    # ------------------------------------------------------------ 对外 API
    def render_shot(
        self,
        chapter_no: int,
        shot: dict,
        characters_bible: dict[str, dict],
        locations_bible: dict[str, dict],
        props_bible: dict[str, dict],
        style: dict | None = None,
    ) -> tuple[str, str]:
        """
        渲染一个镜头。返回 (image_path, prompt_used)。
        失败抛 RuntimeError。
        """
        style = {**DEFAULT_STYLE, **(style or {})}
        prompt = self._build_prompt(
            shot, characters_bible, locations_bible, props_bible, style
        )

        out_dir = self._shots_dir(chapter_no)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"shot_{shot['shot_id']:02d}.png"

        got = self._resolve_image_config()
        if not got or not got.get("api_key"):
            raise RuntimeError(
                "未配置图片模型。请到 HelloMe → 模型 API 添加账号（带 image 能力）"
                "并下发到本机，或在设置页指定 image 模型。"
            )

        # 生成（先试 default_size，失败重试 fallback_size）
        try:
            self._generate(got, prompt, style.get("default_size", "1024x576"), out_path)
        except RuntimeError as e:
            fb = style.get("fallback_size")
            if fb and fb != style.get("default_size"):
                self._generate(got, prompt, fb, out_path)
            else:
                raise
        return str(out_path), prompt

    # ------------------------------------------------------------ 配置
    def _resolve_image_config(self) -> dict:
        s = store.SettingDAO.get("llm.image") or {}
        account_id = s.get("account_id")
        model_id = s.get("model_id")
        got = None
        if account_id is not None and model_id:
            got = llm_cfg.resolve(account_id, model_id, "image")
        if not got or not got.get("api_key"):
            got = llm_cfg.resolve_default("image") or {}
        return got

    # ------------------------------------------------------------ prompt 构造
    def _build_prompt(
        self,
        shot: dict,
        characters_bible: dict[str, dict],
        locations_bible: dict[str, dict],
        props_bible: dict[str, dict],
        style: dict,
    ) -> str:
        parts = []

        # 1. 镜头类型
        shot_type_en = {
            "extreme_wide": "extreme wide shot, establishing shot",
            "wide": "wide shot, full body",
            "medium": "medium shot, half body",
            "close_up": "close-up shot, face",
            "extreme_close_up": "extreme close-up, detail",
        }.get(shot.get("shot_type", "medium"), "medium shot")
        parts.append(shot_type_en)

        # 2. 出场角色 + 外观
        char_descs = []
        for name in shot.get("characters", []) or []:
            c = characters_bible.get(name)
            if c and c.get("appearance_prompt"):
                char_descs.append(c["appearance_prompt"])
            else:
                char_descs.append(f"a character named {name}")
        if char_descs:
            parts.append("; ".join(char_descs))

        # 3. 出场道具
        prop_descs = []
        for name in shot.get("props", []) or []:
            p = props_bible.get(name)
            if p and p.get("visual_prompt"):
                prop_descs.append(p["visual_prompt"])
        if prop_descs:
            parts.append("; ".join(prop_descs))

        # 4. 动作
        if shot.get("action"):
            parts.append(shot["action"])

        # 5. 地点
        loc_name = shot.get("location")
        if loc_name:
            lo = locations_bible.get(loc_name)
            if lo and lo.get("visual_prompt"):
                parts.append(f"setting: {lo['visual_prompt']}")
            else:
                parts.append(f"location: {loc_name}")

        # 6. 时间
        if shot.get("time_of_day"):
            parts.append(f"time: {shot['time_of_day']}")

        # 7. 情绪
        if shot.get("emotion"):
            parts.append(f"mood: {shot['emotion']}")

        # 8. 镜头运动
        movement = shot.get("camera_movement", "static")
        if movement != "static":
            parts.append(f"camera: {movement}")

        # 9. 风格后缀
        if style.get("positive_suffix"):
            parts.append(style["positive_suffix"])

        return ", ".join(p for p in parts if p)

    # ------------------------------------------------------------ 生图
    def _generate(
        self,
        got: dict,
        prompt: str,
        size: str,
        out_path: Path,
    ) -> None:
        """调生图。优先用 YAML 声明的 invoke_path；404 时 fallback 到已知可用路径。
        成功后写 PNG 到 out_path。"""
        api_key = got["api_key"]
        model = got.get("model") or ""
        protocol = got.get("protocol", "")
        base_url = (got.get("base_url") or "").rstrip("/")
        if not base_url:
            raise RuntimeError("生图账号缺少 base_url")

        SUPPORTED = {"image_generate", "openai_images", "openai_image", ""}
        if protocol and protocol not in SUPPORTED:
            raise RuntimeError(
                f"当前账号的生图协议 {protocol!r} 暂不支持。"
                f"请到 HelloMe 换一个支持图片生成的账号（当前支持：{sorted(SUPPORTED - {''})}）"
            )

        # 候选路径：YAML 声明的优先，已知 fallback 在后
        candidates: list[str] = []
        declared = (got.get("invoke_path") or "").strip()
        if declared:
            candidates.append(declared)
        # 标准 OpenAI 路径已知在词元工场不通时，加 stellar fallback
        if declared in ("/images/generations", "/v1/images/generations", ""):
            stellar = "/image/stellar/generations"
            if stellar not in candidates:
                candidates.append(stellar)
        # 兜底：什么都没声明时，直接试 stellar
        if not candidates:
            candidates.append("/image/stellar/generations")

        size = _ensure_min_size(size)
        payload = self._build_payload(model, prompt, size)

        last_err: RuntimeError | None = None
        for path in candidates:
            url = base_url + path
            try:
                data = self._post_json(url, api_key, payload)
                b64 = self._extract_b64(data)
                if not b64:
                    raise RuntimeError(f"生图响应里没有图片数据：{str(data)[:300]}")
                out_path.write_bytes(base64.b64decode(b64))
                return  # 成功
            except RuntimeError as e:
                last_err = e
                # 只有 404 才继续试下一个路径；其他错误立刻抛出
                if "HTTP 404" in str(e):
                    continue
                raise

        if last_err:
            raise RuntimeError(
                f"生图失败（已尝试 {len(candidates)} 条路径）\n"
                f"  base_url: {base_url}\n"
                f"  尝试路径: {candidates}\n"
                f"  最终错误: {str(last_err)[:300]}"
            )
        raise RuntimeError("生图失败：没有可用的候选路径")

    def _build_payload(self, model: str, prompt: str, size: str) -> dict:
        """构造生图请求体。url + watermark 是 OpenAI 兼容层通吃参数，
        未知字段大部分后端会忽略；豆包路径要求这两个字段。"""
        return {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "size": size,
            "response_format": "url",
            "watermark": False,
        }

    def _post_json(self, url: str, api_key: str, payload: dict) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err = ""
            try:
                err = e.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            raise RuntimeError(f"生图 HTTP {e.code}: {err}")
        except Exception as e:
            raise RuntimeError(f"生图调用失败：{type(e).__name__}: {e}")

    def _extract_b64(self, data: dict) -> str | None:
        """兼容两种响应：b64_json 直接返回；url 则下载后转 base64。"""
        if not isinstance(data.get("data"), list) or not data["data"]:
            return None
        item = data["data"][0]
        if not isinstance(item, dict):
            return None
        if item.get("b64_json"):
            return item["b64_json"]
        if item.get("url"):
            return self._download_as_b64(item["url"])
        return None

    def _download_as_b64(self, url: str) -> str | None:
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                return base64.b64encode(resp.read()).decode("ascii")
        except Exception:
            return None

    def _shots_dir(self, chapter_no: int) -> Path:
        data_dir = (os.environ.get("HELLOME_SKILL_DATA_DIR") or "").strip()
        if not data_dir:
            raise RuntimeError("HELLOME_SKILL_DATA_DIR 未设置")
        return Path(data_dir) / "storyboards" / f"ch{chapter_no:03d}"