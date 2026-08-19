# GPT-SoVITS 虚拟角色对话系统 V2 · 可执行实施方案

> 版本：v1.0 ｜ 制定日期：2026-08-19 ｜ 基线：`D:\Works\Sovits\GPT-SoVITS-0617-cu124`
> 本文件是后续全部开发工作的**唯一参考基线**，HTML 完整版见工作区 `character-v2-implementation-plan.html`。

## 一、四条主线

| 主线 | 目标 | 成功标准 |
|------|------|----------|
| 1 长期记忆 | 跨会话记得用户的事实/偏好/情绪事件/承诺 | 10 组召回测试 ≥8 命中 |
| 2 情感检测与表达 | 语义情感识别 + 角色情感状态机 + 情感化语音 | 准确率 ≥85%，状态转移 ≥90% |
| 3 桌面虚拟角色 | Live2D 桌宠，表情/口型/动作随情感联动 | 6 态表情 + 口型随音量 |
| 4 低延迟对话 | 句级流水线，边生成边合成边播放 | 首句语音响应 ≤1.5s |

## 二、GitHub 仓库确认（2026-08-19）

远端 `RAG_SOVITS_MODEL_Character` **不完整**，与本地差异：

- 缺失：`webui.py`、`webui_test02.py`、`.env.example`、目录内 `README.md`（被删除）、`.gitignore`
- 旧版：`core/character_system.py`（6.6KB vs 本地 9.3KB）、`speech_synthesizer.py`（2.2KB vs 5.8KB）
- 数据不完整：`character_database.json` 仅 1.7KB（示例版），本地完整版 12.8KB
- 误传：`__pycache__/*.pyc`、`conversations/*.json`（个人对话）
- 处置：Phase 0 重新整理上传；模型权重与参考音频一律不入库

## 三、目标架构

```
前端层:  Gradio WebUI(保留) / Vue Web(gsvi_ui) / Electron 桌宠(Live2D)
  ↓
统一服务: FastAPI /v1/chat /v1/emotion /v1/memory /v1/tts  +  WS /ws/pet
  ↓
业务核心: AdvancedCharacterSystem(门面)
  ├─ MemoryV2 三层记忆(窗口摘要/情景事件/语义画像)  ← Phase 1
  ├─ SemanticDetector + EmotionFSM 情感智能          ← Phase 2
  ├─ RelationshipV2 三维关系(好感/信任/熟悉)          ← Phase 1
  ├─ RagManager FAISS(持久化+懒加载)                 ← Phase 3
  └─ SpeechSynthesizer TTS(句级流水线+缓存)          ← Phase 3
  ↓
数据层:  SQLite(记忆) / FAISS(向量) / character_database.json / conversations
外部:    DeepSeek LLM / GPT-SoVITS:9880 / SenseVoice(可选)
```

## 四、阶段划分与任务清单

### Phase 0 · 基线整理与仓库重构（0.5 周）

- [ ] 整理目录：自研工程独立成仓库，引擎/权重/音频 .gitignore 排除
- [ ] 补齐远端缺失文件，清理 .pyc 与对话存档，上传完整角色库
- [ ] 编写模型权重下载脚本

### Phase 1 · 长期记忆系统 LTM-2（1.5 周）

- [ ] 1.1 SQLite schema：events / profile / relationship / summaries
- [ ] 1.2 RollingSummarizer 滚动摘要（每 5 轮增量压缩 ≤200 字）
- [ ] 1.3 EventExtractor 事件提取器（fact/preference/emotion/promise/chat，JSON，失败降级）
- [ ] 1.4 EpisodicMemory 情景记忆（SQLite + FAISS + 遗忘曲线 `sim×importance×exp(-λΔt)`）
- [ ] 1.5 SemanticMemory 用户画像聚合（偏好/回避/性格/关心）
- [ ] 1.6 RelationshipV2 三维关系（0-100，兼容旧字段）
- [ ] 1.7 MemoryInjectionPolicy Prompt 注入预算（≤1000 token）
- [ ] 1.8 MemoryV2 门面接入 AdvancedCharacterSystem
- [ ] 1.9 `/v1/memory` REST 接口

验收：跨会话召回 ≥80%；30 轮后记忆注入 ≤1000 token；旧存档可加载；记忆面板可删除。

### Phase 2 · 情感智能升级 EI v2（1.5 周）

- [ ] 2.1 SemanticDetector（LLM JSON 8 类情感 + 关键词兜底 + 与事件提取合并调用）
- [ ] 2.2 EmotionFSM（状态转移表 YAML 可配，强度衰减 ×0.85/轮）
- [ ] 2.3 角色 JSON 增加 `emotion_style`（4 角色填充）
- [ ] 2.4 EmotionAudioMatcher（状态+强度+亲密度确定性选取，替代随机）
- [ ] 2.5 情感标签写入记忆事件 emotion_tag
- [ ] 2.6 EmotionLog 埋点 + `/v1/emotion` 诊断接口
- [ ] 2.7 TTS 链路接入新匹配器（保留旧接口兼容）

验收：30 条无语义样本准确率 ≥85%；10 轮情绪剧本转移符合 ≥90%；20 次合成音频选择稳定不重复；LLM 挂时降级关键词。

### Phase 3 · 低延迟对话链路（1 周）

- [ ] 3.1 分句器 + 句级 TTS 流水线（播放队列按 seq 排序）
- [ ] 3.2 TTS LRU 磁盘缓存 `(角色, 情感, 文本hash)`
- [ ] 3.3 预处理并行化（情感+记忆+关系 asyncio/线程池）
- [ ] 3.4 播放器抽象，迁移 miniaudio/sounddevice（VLC 降级保留）
- [ ] 3.5 FAISS 索引持久化 + 嵌入模型懒加载
- [ ] 3.6 FastAPI 统一服务 + SSE/WS 流式对话
- [ ] 3.7 延迟埋点（LLM 首 token / TTS 首帧 / 总耗时）

验收：首句语音 ≤1.5s；缓存命中 ≤0.6s；50 轮无丢帧乱序。

### Phase 4 · 桌面虚拟角色 Live2D 桌宠（2-3 周）

技术栈：Electron 33+（透明/置顶/托盘）+ PixiJS 7 + pixi-live2d-display-lipsyncpatch + Cubism 5 Core + Vue 3 + FastAPI/WS。

- [ ] 4.1 Electron 脚手架 + Python 子进程（spawn + 随机端口 + 就绪探测）
- [ ] 4.2 PixiJS + Live2D 渲染（先用公开模型跑通）
- [ ] 4.3 口型：AnalyserNode 音量 → ParamMouthOpenY（渲染进程内，避免 WS 延迟）
- [ ] 4.4 WS 协议：text/emotion/audio/state 全链路联调
- [ ] 4.5 情感→表情/动作映射（默认 6 态：喜悦/低落/愤怒/焦虑/平静/兴奋）
- [ ] 4.6 角色专属 Live2D 模型（独立子任务分批）
- [ ] 4.7 音画同步（播放时序联动）
- [ ] 4.8 打断机制（interrupt 消息）
- [ ] 4.9 打包（electron-builder + PyInstaller）

WS 消息协议：

```json
后端→桌宠: {"type":"text","content":"..."} | {"type":"emotion","emotion":"喜悦","intensity":0.7}
           {"type":"audio","path":"...","seq":1} | {"type":"state","state":"speaking"}
桌宠→后端: {"type":"chat","text":"..."} | {"type":"interrupt"}
```

### Phase 5 · 评测体系与集成收尾（1 周）

- [ ] 5.1 评测集（一致性30/情感30/记忆20/多样性20）+ `scripts/evaluate.py`
- [ ] 5.2 全链路日志与指标汇总（memory/emotion/latency）
- [ ] 5.3 WebUI 集成（记忆面板/情感状态/延迟显示）
- [ ] 5.4 CLI/Web/桌宠三端统一走 FastAPI
- [ ] 5.5 docs/ 文档（README/架构/API/部署）
- [ ] 5.6 对照第一章成功标准端到端验收

## 五、里程碑

| 里程碑 | 时间 | 检查点 |
|--------|------|--------|
| M0 基线就绪 | 第 1 周初 | 仓库规范、远端对齐 |
| M1 记忆可用 | 第 2 周末 | 跨会话召回通过 |
| M2 情感可用 | 第 4 周初 | 准确率 ≥85% |
| M3 低延迟达标 | 第 5 周末 | 首句 ≤1.5s |
| M4 桌宠可用 | 第 8 周初 | 表情/口型联动 |
| M5 评测通过 | 第 9 周末 | 全部指标达标 |

## 六、风险预案（摘要）

| 风险 | 预案 |
|------|------|
| LLM 额外调用成本/延迟 | 情感+事件合并一次调用；异步执行；失败降级 |
| 记忆噪声导致离题 | 遗忘曲线+Top-K；记忆注入开关；评测回归 |
| 桌宠模型制作耗时 | 先用公开模型跑通链路；角色模型分批 |
| 句级 TTS 乱序 | 播放队列按 seq 严格排序；超时跳过 |
| Cubism Core 许可 | 发布前核对条款，必要时限制模型来源 |

## 七、迭代机制

1. 每次改动 → 跑该阶段验收清单 → 全量评测回归 → 提交
2. 里程碑 M0-M5 打 tag（v2.0-m1 … v2.0-m5），最终 v2.0
3. 新需求先更新本文件再开发，本文件始终为唯一基线
4. 远期（v2.1）：实时语音对话（VAD+流式ASR）、多角色同屏、情绪曲线可视化

---

开始条件：方案评审通过后，从 **Phase 0** 开始执行。
