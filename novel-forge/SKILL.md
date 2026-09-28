---
name: novel-forge
description: 织章 · 多 Agent 一致性写作引擎——本机 AI 长篇小说创作工作台。给一份世界框架，六个 Agent（写手 / 审校 / 抽取 / 裁决 / 编辑 / 台账）分工写章节，四层一致性闸门把关，可选生成章节分镜图。用户要创作、续写、检查设定冲突、给章节配分镜时使用。
version: 1.0.1
compatibility: hellome-host/1
metadata:
  hellome-adapter: "static"
  hellome-base-port: "43810"
  hellome-open-browser: "true"
  hellome-health-url: "/"
  hellome-health-type: "http"
  hellome-auto-shutdown: "presence"
  hellome-hermes-min: "3.2.1"
  hellome-start-budget-sec: "60"
---

# 织章 · 多 Agent 一致性写作引擎

**织章** 是一个跑在用户本机的 AI 长篇小说创作工作台。用户给一份世界框架，它用六个 Agent 分工把整本小说写完，每一章都过四层一致性闸门；不一致的地方会被拦下来，在网页里一条条呈现给用户。可选为每一章生成分镜草稿图（需要图片模型）。

数据只落本机 `HELLOME_SKILL_DATA_DIR`。不采集任何 API Key。

## 这是什么

一份世界框架进去，一本前后一致的小说出来。

六个 Agent 分工协作：

- **写手**：按「章节合同」出初稿
- **抽取**：把正文里的事实结构化，落进台账
- **审校**：抓声口漂移、视角越界、行业术语误用、年代错误
- **裁决**：对每条一致性问题给处置意见
- **编辑**：按裁决修订正文
- **台账**：验收后把角色状态、时间线、伏笔、局全部写回权威状态库

每一章过**四层一致性闸门**：

1. **硬规则**（确定性）：死人不能出场、时间不能倒流、同场景不能两地、合同禁止项
2. **关系图谱**（确定性）：关系对称性、地点层级、时间线单调
3. **合同兑现**（结构化）：Scheme 证据齐不齐、必须推进点落实、节奏、篇幅
4. **LLM 语义审校**：声口漂移、动机突变、视角越界、行业术语误用、年代错误

不一致的地方会被拦下来，在「一致性中心」里一条条呈现，用户逐条处理。

**可选：分镜**。开启后，每章可以生成 5–15 张手绘漫画风的分镜草稿图。图片模型不可用时，仍然输出结构化的分镜脚本（JSON + 每张图的完整 prompt），用户可以复制到其它工具生图。

**内置资产**：

- 36 章黄金样本合同（三幕：破局 / 弈局 / 终局）
- 14 个局（Scheme），从 S1 到 S14
- 行业知识库（术语 / 流程 / 年代细节）
- 世界规则 + 10 个角色卡 + 7 个地点 + 4 个道具
- 36 章大纲 + 每章标题
- 本书风格指南（基调 / 叙事规则 / 全局禁止 / 文风样本）

写手用强模型，抽取 / 台账用便宜模型；账号和模型在设置页按角色独立选。

## 何时使用

- 用户要创作长篇（中篇）小说，或给一份世界框架让 AI 按章节产出
- 用户要检查已有小说的设定冲突、时间线错误、伏笔回收
- 用户要续写、重写某一章，或调整某一章的合同
- 用户要给某一章配分镜草稿图，或导出分镜脚本
- 被 HelloMe / FDE「启动」唤起时

不要在无关闲聊时主动拉起。

## 怎么做

1. 用户点 HelloMe / FDE「启动」，平台按 metadata 确定性启动。不要猜安装目录，不要写死端口。
2. 平台打开 READY URL；不要自开系统浏览器。
3. 用户在页面里操作：
   - **总览**：看进度、LLM 状态、活跃的局、待处理问题
   - **设定圣经**：维护世界规则、角色卡、地点、道具（含每个角色的**外观描述**和地点**视觉描述**，分镜会用）
   - **大纲**：看 36 章骨架和每章意图
   - **章节工作台**：冻结合同 → 生成草稿 → 处理一致性问题 → 验收；顶部 `[正文] [分镜]` 切换
   - **一致性中心**：查看和处理四层闸门报出的问题
   - **设置**：为每个角色（写手 / 审校 / 抽取 / 裁决 / 编辑 / 台账 / 导演）选账号 + 模型
4. 一章的完整流程：
   - 冻结该章合同（冻结后不可修改）
   - 点「生成草稿」，多 Agent 流水线开始跑（写手 → 抽取 → 硬规则 → 语义审校 → 裁决 → 修订），2–6 分钟
   - 完成后看右侧「一致性」区域，处理 blocker 和 warning
   - 全部处理完点「验收本章」，Curator 更新权威状态
5. **分镜（可选）**：
   - 点章节工作台顶部的 `[分镜]` tab
   - 选择镜头数（5 / 8 / 12 / 15），点「生成分镜」
   - 每张图 5–20 秒；生成完点击图片可全屏查看
   - 「重新生成全部」会先确认，已成功的图默认不重跑（省钱）
   - 「单张重画」只重跑那一张
6. 关页停服：最后一个标签离开约 2.5s 后本机服务退出。长任务进度落库，下次打开从断点续。

## 输出契约（强制）

1. 平台终态打印：NOVEL_FORGE_READY url=http://127.0.0.1:<port>/
2. 若有复用：HELLOME_SKILL_REUSED skill=<key>
3. 业务进程禁止打印 READY 行

## 能力与限制

- 本机 HTTP，只绑 127.0.0.1
- 业务数据只写 `HELLOME_SKILL_DATA_DIR`（默认落 `novel.db`）
- 长任务（写一章 2–6 分钟、生一章分镜 2–5 分钟）以 task_id 轮询；**关页后任务中断，进度已落库**，下次打开可续
- 分镜图**可选**：图片模型不可用时会输出结构化分镜脚本（含 prompt），用户可复制到其它工具生图
- 不支持：多人协作、云端同步、非中文小说优先优化

## 注意

- 不得写入技能安装目录（包括 `__pycache__`）
- 端口只读 `HELLOME_UPSTREAM_PORT`（为空就退出）
- 调 LLM 建议优先走 HelloMe 下发配置（回退 Hermes 词元），Key 不得打进包、不得在技能页采集
- 数据目录是 `novel.db` 及其 WAL 文件；卸载时按 `hellome-data-policy` 处理

## 词元

1. HelloMe 下发的多供应商配置（词元 / 百炼 / 火山 / 自定义），词元是其中一家 + `.env` 回退。优先读 `{HERMES_HOME}/hellome_skills_llm_config.yml`（helper `list_*` / `resolve` / `resolve_default`），没有再回退 Hermes `{HERMES_HOME}/.env` 的 AGENTSYUN_API_KEY。视觉理解走 text；出图走 image。
2. 技能页不采集、不展示 API Key。有设置页时先选账号再选模型，选中对 `{account_id, model_id}` 记在 HELLOME_SKILL_DATA_DIR。
3. 未下发 ≠ 报错。设置页按 `source=yaml/env/none` 画状态：完全无文件写「使用桌面词元（未下发 HelloMe 账号）」；有文件但当前 kind 没有写「当前能力尚未下发到本机」。仅文本 + 桌面词元允许生成；图/视频 env 禁用 helper 生成。只有 Key 也没有时才提示去 HelloMe 下发或在 Hermes 配词元。不要引导去 OpenAI / 火山控制台贴 Key。
4. 有设置页：列表以 `list_models` 为准（现读 YAML，不缓存）；`list_providers()` 空不是失败。无 YAML 才回退词元 GET /models，目录失败只改 hint。无设置页用 `resolve_default(kind)`：该 kind 下优先词元（`ciyuan`），否则 `account_id` 较小者。
5. 本 skill 按角色分流：**写手 / 审校 / 裁决 / 编辑 / 导演**用强模型；**抽取 / 台账**可用便宜模型。用户可在设置页为每个角色独立选账号 + 模型。
6. **分镜出图**：优先 `kind=image` 的 `resolve()`；如词元工场的豆包 Seedream 走 `/image/stellar/generations`（代码会自动 fallback）。图片模型不可用时，`storyboard_artist` 输出结构化 prompt，不报错。

## 内置数据说明

首次启动时从 `upstream/seed/` 导入以下数据到 `HELLOME_SKILL_DATA_DIR/novel.db`：

- `contracts.json`：36 章合同（含 POV、场景、must_advance、plant、payoff、forbid、tone、domain_inject）
- `schemes.json`：14 个 Scheme 的埋 / 武装 / 触发 / 收束节点和证据链
- `domain_terms.json`：行业术语（含禁用写法）
- `process_stages.json`：项目流程节点（参与方、产物、陷阱）
- `era_details.json`：年代细节（含禁止出现的后世事物）
- `bible.json`：世界规则 + 角色卡（含 `appearance_prompt`）+ 地点（含 `visual_prompt`）+ 道具（`props`）
- `outline.json`：三幕 + 36 章标题和意图
- `genre_profile.json`：本书风格指南（基调 / 叙事规则 / 全局禁止 / 文风样本 / **分镜风格**）

导入是**幂等**的：表非空时跳过，不覆盖用户已有数据。用户可以：
- 在 UI 里改世界规则、角色卡、地点、道具
- 手工编辑 `genre_profile.json`（放 `HELLOME_SKILL_DATA_DIR/genre_profile.json` 会覆盖 seed）

## 换书流程

**当前版本**：改 seed 文件 → 删 `novel.db` → 重启。**下一版**会加项目切换器。

**换一本新书**：

1. 备份旧项目的 `HELLOME_SKILL_DATA_DIR`
2. 清空数据目录
3. 替换 `upstream/seed/` 下的 8 个 JSON（合同 / 局 / 术语 / 年代 / 圣经 / 大纲 / 风格 / 流程）
4. 重启服务

**只改风格不改内容**：把新 `genre_profile.json` 放到 `HELLOME_SKILL_DATA_DIR/genre_profile.json`，重启。seed 里的同名文件会被覆盖。

## 不要做

- 自建起服 / 写死端口 / 自开浏览器 / 只提供 .bat
- 业务进程打印平台就绪标记
- 把用户数据写进安装树
- 把真实 Key 打进包；可执行代码把 openai.com 写成默认基址
- 删除或改写页面里的 presence 脚本
- 把用户的正文或分镜图上传到任何公网服务（除用户主动配置的 LLM provider）