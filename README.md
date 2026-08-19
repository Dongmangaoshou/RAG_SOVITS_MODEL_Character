# GPT-SoVITS Character Dialogue System (V2)

基于 LangChain + GPT-SoVITS + FAISS 的虚拟角色对话系统，支持文本/语音双模态交互。

> V2 版本新增：长期记忆（LTM-2）、情感智能（EI v2）、低延迟对话链路、Live2D 桌宠脚手架。完整实施方案见 [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)。

## 功能特性

- **角色扮演对话**：基于 LLM 的角色扮演，配合 RAG 检索增强回复一致性
- **长期记忆（V2）**：三层记忆（滚动摘要 / 情景事件 + 遗忘曲线 / 用户画像 + 三维关系），跨会话"角色记得你"
- **情感智能（V2）**：语义情感识别（8 类）+ 角色情感状态机 + 情感化 TTS 参考音频确定性匹配
- **低延迟链路（V2）**：句级流水线（分句即合成、边生成边播放）+ TTS 缓存 + 并行预处理，首句响应 ≤1.5s
- **桌面虚拟角色（V2 脚手架）**：Electron + PixiJS + Live2D 桌宠，表情/口型/动作随情感联动
- **语音合成与识别**：GPT-SoVITS 语音合成 + Google/Whisper 语音识别
- **情感感知**：自动检测用户情绪并调整回复风格
- **关系系统**：好感/信任/熟悉三维度动态变化，影响角色语气
- **对话持久化**：自动保存/恢复对话历史
- **统一 API**：FastAPI 服务（`/v1/chat`、`/v1/memory`、`/v1/emotion`、`/ws/pet`）

## 快速开始

### 1. 环境准备

- Python 3.10+（推荐 3.12，项目依赖 langchain / faiss / sentence-transformers）
- [GPT-SoVITS 服务](https://github.com/RVC-Boss/GPT-SoVITS) 运行在 `127.0.0.1:9880`（如需语音合成）

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置 API Key

```bash
cp .env.example .env
# 编辑 .env 填入你的 DEEPSEEK_API_KEY
```

### 4. 配置角色

角色数据位于 `character_database.json`（含 雷姆 / 明日香 / 早濑优香 / 拉姆 四角色完整配置）。

### 5. 运行

```bash
# 交互模式
python main.py

# 直接指定角色
python main.py -c 雷姆

# 纯文本模式（无需启动 SoVITS）
python main.py -c 雷姆 --text-only

# 启动统一 API 服务（低延迟对话 + 记忆 + 情感 + 桌宠 WS）
python api/main.py
```

### 6. 配置文件

编辑 `config.yaml` 可覆盖默认参数（含 V2 分区：`memory` / `emotion` / `latency` / `pet`）。

## 项目结构（V2）

```
├── core/                      # 业务核心
│   ├── character_system.py    # 角色系统门面（V2 集成）
│   ├── memory/                # 长期记忆（三层：working/episodic/semantic）
│   ├── emotion/               # 情感智能（detector/fsm/audio_matcher）
│   ├── tts/                   # 低延迟 TTS（sentence_splitter/cache/pipeline）
│   ├── rag_manager.py         # RAG 检索（FAISS）
│   └── ...
├── api/                       # FastAPI 统一服务（REST + WebSocket）
├── desktop_pet/               # Live2D 桌宠（Electron + PixiJS，脚手架）
├── scripts/                   # 工具脚本（tts_demo 等）
├── character_database.json    # 角色数据库
├── config.yaml                # 用户配置
├── .env.example               # 环境变量模板
└── IMPLEMENTATION_PLAN.md     # V2 实施方案（唯一参考基线）
```

## 桌宠（Phase 4 脚手架）

```bash
cd desktop_pet
npm install electron pixi.js
npm start
```

桌宠通过 WebSocket 连接 Python 后端 `/ws/pet`，协议见 `desktop_pet/README.md`。

## 可选组件

- **离线语音识别**：`pip install faster-whisper`
- **语音情感第二通道**：SenseVoice（funasr）
- **其他 LLM Provider**：修改 `config.yaml` 中的 `llm.provider` 和 `llm.base_url`

## License

MIT
