# GPT-SoVITS Character Dialogue System

基于 LangChain + GPT-SoVITS + FAISS 的虚拟角色对话系统，支持文本/语音双模态交互。

## 功能特性

- **角色扮演对话**：基于 LLM 的角色扮演，配合 RAG 检索增强回复一致性
- **语音合成与识别**：GPT-SoVITS 语音合成 + Google/Whisper 语音识别
- **情感感知**：自动检测用户情绪并调整回复风格
- **关系系统**：好感度随对话动态变化，影响角色语气
- **对话持久化**：自动保存/恢复对话历史
- **模块化架构**：Provider 可替换（LLM/TTS），便于二次开发

## 快速开始

### 1. 环境准备

- Python 3.10+
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

角色数据位于 `character_database.json`。每个角色需要以下字段：

| 字段 | 说明 |
|------|------|
| `source` | 作品来源 |
| `personality` | 角色性格描述 |
| `style` | 说话风格 |
| `gpt_path` | GPT 模型权重路径 |
| `sovits_path` | SoVITS 模型权重路径 |
| `refer_wav_path` | 参考音频路径 |
| `prompt_text` | 参考音频文本 |
| `catchphrases` | 口头禅列表 |
| `visual_elements` | 颜文字/表情列表 |
| `backstory` | 角色背景故事 |
| `story_setting` | 故事设定片段 |
| `lines_library` | 经典台词库 |

> 提示：将 `character_database.example.json` 复制为 `character_database.json` 可快速上手。

### 5. 运行

```bash
# 交互模式
python main.py

# 直接指定角色
python main.py -c 雷姆

# 纯文本模式（无需启动 SoVITS）
python main.py -c 雷姆 --text-only

# 列出所有角色
python main.py -l

# 加载最近对话
python main.py -c 雷姆 --load latest
```

### 6. 配置文件

编辑 `config.yaml` 可覆盖默认参数（所有配置项均为可选，未设置则使用系统默认值）。

## 项目结构

```
GPT-SoVITS-Character/
├── main.py                       # 入口脚本
├── config.yaml                   # 用户配置文件
├── requirements.txt              # Python 依赖
├── character_database.json       # 角色数据库（需自行创建）
├── character_database.example.json  # 角色数据库示例
├── .env.example                  # 环境变量模板
├── .gitignore
└── core/                         # 核心模块
    ├── config.py                 # 配置加载
    ├── character_profile.py      # 角色数据管理
    ├── rag_manager.py            # RAG 检索
    ├── emotion_engine.py         # 情感检测
    ├── relationship_tracker.py   # 关系管理
    ├── memory_manager.py         # 对话记忆
    ├── speech_synthesizer.py     # 语音合成
    ├── audio_player.py           # 音频播放
    └── character_system.py       # 系统门面
```

## 可选组件

- **离线语音识别**：安装 `pip install faster-whisper` 可获得本地 ASR 能力
- **其他 LLM Provider**：修改 `config.yaml` 中的 `llm.provider` 和 `llm.base_url` 可对接 OpenAI / Ollama 等

## License

MIT
