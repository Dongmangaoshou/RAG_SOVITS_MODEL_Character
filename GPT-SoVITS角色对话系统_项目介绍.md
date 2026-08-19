# GPT-SoVITS 智能角色对话系统

**基于 RAG + LLM + 情感计算 + 语音合成的多模态虚拟角色交互平台**

> 技术栈：Python · LangChain · DeepSeek · FAISS · Gradio · GPT-SoVITS · VLC · ffmpeg

---

## 一、项目概述

本项目构建了一个完整的智能角色对话系统，用户可以通过文本或语音与动漫/游戏角色进行实时对话。系统深度融合了检索增强生成（RAG）、大语言模型（LLM）、情感检测、情感自适应语音合成（TTS）以及 Web 交互界面等技术，实现了从用户输入到角色语音回复的端到端智能化流程。

### 核心能力

- **多角色支持**：可扩展的角色数据库，包含性格、背景故事、经典台词、语音模型等完整人设
- **智能对话**：基于 DeepSeek 大模型的角色扮演对话，严格保持角色设定和语言风格
- **知识增强**：RAG 技术从角色知识库中检索相关设定，确保回复的准确性和一致性
- **情感感知**：检测用户情绪（开心/悲伤/愤怒/焦虑/平静），自动调整回复语气
- **情感自适应语音**：根据检测到的用户情绪，自动选择匹配的参考音频进行语音合成
- **多模态交互**：支持文本输入和语音输入双模式，Web 界面 + 命令行双端

### 应用场景

- 虚拟角色陪伴与心理支持
- 二次元角色互动娱乐
- 语音助手个性化定制
- 语言学习对话伙伴

---

## 二、系统架构设计

系统采用分层模块化架构，各层职责清晰、耦合度低，便于扩展和维护。

```
┌─────────────────────────────────────────────────────────┐
│                    表示层 (Presentation)                  │
│   webui.py (Gradio)  ·  webui_test02.py  ·  main.py     │
│   角色选择 · 文本/语音输入 · 对话展示 · 历史管理          │
├─────────────────────────────────────────────────────────┤
│                 业务逻辑层 (Business Logic)                │
│   AdvancedCharacterSystem (角色系统门面)                   │
│   ├── EmotionEngine         情感检测与提示生成            │
│   ├── RelationshipTracker   用户关系管理                  │
│   ├── CharacterProfile      角色数据与情感→音频映射       │
│   └── SpeechSynthesizer     TTS合成 + ffmpeg + VLC播放  │
├─────────────────────────────────────────────────────────┤
│                  数据访问层 (Data Access)                  │
│   RagManager (FAISS向量检索)  ·  MemoryManager (对话记忆) │
│   character_database.json  ·  config.yaml  ·  .env       │
├─────────────────────────────────────────────────────────┤
│                  外部服务层 (External APIs)                │
│   DeepSeek API (LLM)  ·  GPT-SoVITS API (语音合成)       │
│   SpeechRecognition (语音识别)  ·  VLC (音频播放)         │
└─────────────────────────────────────────────────────────┘
```

### 数据流

```
用户输入文本
  → EmotionEngine 检测情绪
  → RagManager 检索角色知识
  → 构建 Prompt（角色人设 + RAG上下文 + 情感提示 + 对话历史）
  → DeepSeek LLM 生成回复
  → 情感 → 参考音频映射
  → GPT-SoVITS 语音合成
  → ffmpeg 格式标准化
  → VLC 播放
  → MemoryManager 保存对话
```

---

## 三、核心技术详解

### 3.1 检索增强生成（RAG）

RAG 是本系统的知识底座。每个角色拥有独立的向量知识库，包含背景故事、世界观设定和经典台词等文本。当用户发起对话时，系统对用户输入进行语义检索，从角色知识库中找到最相关的设定片段，作为上下文注入 LLM Prompt，确保角色回复不会偏离原作设定。

**技术选型：**

| 组件 | 选型 | 说明 |
|------|------|------|
| 嵌入模型 | sentence-transformers/all-mpnet-base-v2 | 420MB，768维稠密向量 |
| 向量数据库 | FAISS | Facebook AI Similarity Search |
| 文本分割 | RecursiveCharacterTextSplitter | chunk_size=200, overlap=20 |
| 检索策略 | 相似度 Top-K | K=3，自动拼接为上下文 |

**核心代码：**

```python
# RagManager (core/rag_manager.py)
class RagManager:
    def __init__(self):
        self.embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-mpnet-base-v2"
        )
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=200, chunk_overlap=20
        )
        self.dbs = {}  # character_name → FAISS

    def build(self, profile):
        documents = self.text_splitter.create_documents(profile.all_texts())
        self.dbs[profile.name] = FAISS.from_documents(documents, self.embeddings)

    def retrieve_as_context(self, character_name, query, k=3):
        fragments = self.retrieve(character_name, query, k)
        return "\n".join(f"- {f}" for f in fragments)
```

**设计考量：** 考虑到每个角色当前数据量较小（约14条文本片段），未来可优化为轻量级 TF-IDF 检索或直接全量注入 Prompt，以消除 420MB 嵌入模型的加载开销。但当前架构已预留扩展空间，当角色知识库增长到数百条时可无缝承载。

---

### 3.2 情感检测与自适应系统

系统实现了完整的情感感知闭环：检测用户情绪 → 调整 LLM 回复策略 → 选择匹配的参考音频 → 合成情感一致的语音输出。这是本项目区别于普通聊天机器人的核心创新点。

**情感规范化映射（4+1 分类体系）：**

```python
# EmotionEngine (core/emotion_engine.py)
emotion_keywords = {
    "开心": ["开心","高兴","快乐","兴奋","愉快","幸福","哈哈","太棒了"],
    "悲伤": ["伤心","难过","抑郁","悲伤","失落","痛苦","郁闷","想哭"],
    "愤怒": ["生气","愤怒","烦躁","不爽","恼火","讨厌","可恶","混蛋"],
    "焦虑": ["焦虑","紧张","担心","害怕","不安","忧虑","恐惧","忐忑"],
}
# 未匹配 → "平静"（默认）

def get_context_hint(self, emotion: str) -> str:
    hints = {
        "开心": "用户情绪愉快，可以适当分享喜悦",
        "悲伤": "用户情绪低落，需要温柔鼓励和陪伴",
        "愤怒": "用户比较生气，需要平静安慰和理解",
        "焦虑": "用户感到焦虑不安，需要安抚和引导",
    }
    return hints.get(emotion, "")
```

**情感→参考音频动态选择链路：**

这是系统最具创新性的技术点。传统 TTS 系统使用固定的参考音频，而本系统根据检测到的用户情绪，从角色的情感音频库中自动选择匹配的参考音频。例如检测到用户"悲伤"，系统从参考音频目录中随机选取【悲郁】或【叹气】标签的音频，使得合成语音的情感色彩与对话语境自然契合。

```python
# CharacterProfile 情感音频解析 (core/character_profile.py)
def resolve_emotion_audio(self, emotion: str) -> tuple[str, str]:
    """
    emotion = "悲伤"
      → emotion_audio_map["悲伤"]
      → ["【悲郁】ずっと、1人が...mp3", "【叹气】あんたって、...mp3"]
      → random.choice → 【悲郁】ずっと、1人が当たり前なのに、...mp3
      → 提取 prompt_text: "ずっと、1人が当たり前なのに、..."
      → return (
           "custom_refs/Asuka参考音频/【悲郁】ずっと、...mp3",
           "ずっと、1人が当たり前なのに、..."
         )
    """
    audio_map = self.emotion_audio_map
    base_dir = self._audio_base_dir()  # 从 refer_wav_path 模板推导
    candidates = audio_map.get(emotion) or audio_map.get("平静", [])
    filename = random.choice(candidates)
    full_path = str(Path(base_dir) / filename)
    prompt = re.sub(r'^【[^】]*】', '', filename)  # 去情绪标签
    prompt = re.sub(r'\.[^.]+$', '', prompt)       # 去扩展名
    return full_path, prompt
```

**情感传递全链路：**

```
用户输入 "感觉好难过..."
  → EmotionEngine.detect() → "悲伤"
  → get_context_hint("悲伤") → 注入 Prompt → LLM 生成安慰性回复
  → resolve_emotion_audio("悲伤") → 选择【悲郁】或【叹气】参考音频
  → SpeechSynthesizer(refer_wav_path=".../【悲郁】...mp3",
                       prompt_text="ずっと、1人が...")
  → GPT-SoVITS API → 情感匹配的语音输出
```

---

### 3.3 大语言模型集成

系统基于 LangChain 框架集成 DeepSeek 大模型，采用流式输出 + 多轮对话记忆 + 指数退避重试的生产级方案。

```python
# Prompt 模板结构 (core/character_system.py)
prompt = f"""
你正在扮演{source}中的{name}。
角色背景故事: {backstory}
角色性格: {personality}
说话风格: {style}

重要规则:
1. 严格保持角色设定和语言风格
2. 在回复中自然融入角色经典台词
3. 每2-3句话添加一个颜文字或表情符号
4. 作为心理支持角色，要理解用户情绪并提供支持
5. 如果用户表现出负面情绪，先表达同理心再引导积极思考

当前对话历史: {history}
角色相关上下文(RAG): {rag_context}
用户: {input}
"""
```

**工程特性：**

- **流式生成**：Web 端实时逐 token 展示（基于 Queue + Thread），CLI 端逐字打印
- **容错重试**：API 异常自动指数退避重试（max 3次，base_delay 2s）
- **对话记忆**：ConversationBufferWindowMemory，滑动窗口（默认10轮）
- **对话持久化**：JSON 序列化保存/恢复，含关系等级和完整消息历史

---

### 3.4 语音合成与播放

语音合成模块封装了 GPT-SoVITS API 调用、ffmpeg 音频格式修复和 VLC 播放器三层逻辑。

```python
# SpeechSynthesizer 核心链 (core/speech_synthesizer.py)
def synthesize(self, profile, text, refer_wav_path="", prompt_text=""):
    # 1. API 请求
    resp = requests.post(TTS_API_URL, json={
        "sovits_path": profile.sovits_path,
        "gpt_path": profile.gpt_path,
        "refer_wav_path": ref_path,     # 由情感模块动态传入
        "prompt_text": ref_text,        # 由情感模块动态传入
        "text": text,
    })
    # 2. 保存原始音频
    audio_path.write_bytes(resp.content)
    # 3. ffmpeg 格式修复 (pcm_s16le)
    self._fix_audio(audio_path)
    # 4. 播放 (VLC → pygame 降级)
    self._play_audio(audio_path)
```

**播放器降级链：** `python-vlc (VLC) → pygame.mixer (fallback)`

**ffmpeg 自动修复：** 每次合成后自动执行 `ffmpeg -y -i raw.wav -acodec pcm_s16le output.wav`，确保音频格式兼容所有播放器。

---

## 四、核心模块设计

### 4.1 角色配置系统

角色数据采用 JSON 结构化存储，每个角色包含 15+ 个属性字段。支持按需扩展，新增角色只需添加 JSON 配置，无需修改代码。

```json
{
  "明日香": {
    "source": "《新世纪福音战士》",
    "personality": "极度骄傲自负，用攻击性态度掩饰内心的脆弱...",
    "style": "毒舌傲娇，短句为主，情绪激动时切换德语...",
    "backstory": "EVA二号机驾驶员，德日混血天才少女...",
    "story_setting": ["NERV的EVA驾驶员", "与真嗣、丽是同学..."],
    "lines_library": ["我可是天才！", "Anta baka?..."],
    "catchphrases": ["你是笨蛋吗？", "无路赛！"],
    "visual_elements": ["🔥", "(￣へ￣)", ">_<"],
    "refer_wav_path": "custom_refs/Asuka参考音频/{emotion}",
    "emotion_audio_map": {
      "开心": ["【开心】なんだか楽になったわ、...mp3"],
      "悲伤": ["【悲郁】ずっと、1人が...mp3", "【叹气】あんたって、...mp3"],
      "愤怒": ["【生气】あんたバカ？...mp3", "【激动】親の言いつけ...wav"],
      "焦虑": ["【疑问】ところでさ、...mp3"],
      "平静": ["【说话】他人と合わせて...mp3", "【释然】そっか、私笑えるんだ。.mp3"]
    }
  }
}
```

### 4.2 门面模式设计

`AdvancedCharacterSystem` 采用门面模式（Facade Pattern），将 EmotionEngine、RagManager、MemoryManager、SpeechSynthesizer 等子模块封装为统一接口。

```
AdvancedCharacterSystem
  ├── CharacterProfile      # 角色数据 + 情感→音频映射
  ├── RagManager            # FAISS 向量检索
  ├── EmotionEngine         # 情感检测
  ├── RelationshipTracker   # 关系等级追踪
  ├── MemoryManager         # 对话记忆 + 持久化
  └── SpeechSynthesizer     # TTS + ffmpeg + VLC
```

外部调用者只需 `system.generate_response(user_input)` 即可完成整个对话流程。

### 4.3 配置管理

采用 **默认配置（_DEFAULTS）+ 用户配置（config.yaml）深度合并** 策略。用户只需覆盖需要修改的项，未覆盖项自动使用默认值。API Key 通过 `.env` 文件注入。

---

## 五、Web 交互界面

基于 Gradio 框架构建响应式 Web 对话界面，两个版本适配不同场景：

| 功能 | webui.py（基础版） | webui_test02.py（精简版） |
|------|:--:|:--:|
| 角色下拉选择 | ✓ | ✓ |
| 角色信息展示 | ✓ | ✓ |
| 文本/语音切换 | ✓ | ✓ |
| 流式对话 | ✓ | ✓ |
| 历史对话管理 | ✓ | ✓ |
| 保存/加载 | ✓ | ✓ |

---

## 六、技术创新点

### 6.1 情感自适应语音合成

独创的情感→参考音频动态映射机制。传统 TTS 使用固定参考音频，本系统根据对话中检测到的用户情绪，自动从角色的情感音频库中选取匹配的参考音频和提示文本，使合成语音的情感色彩与对话语境自然契合。情感变量流经 **EmotionEngine → CharacterProfile → SpeechSynthesizer** 全链路。

### 6.2 RAG + 角色知识库深度融合

将 RAG 技术应用于虚拟角色扮演场景，每个角色拥有独立的 FAISS 向量知识库。检索结果与情感提示融合后注入 Prompt，确保 LLM 回复既符合角色设定又能感知用户情绪。

### 6.3 多层级配置与扩展体系

JSON 角色数据库 + YAML 用户配置 + .env 环境变量三层架构。新增角色只需添加 JSON 配置（含情感音频映射），无需修改任何业务代码。

### 6.4 工程化容错设计

- LLM API 指数退避重试（3次）
- TTS 失败自动降级纯文本模式
- VLC → pygame 播放器降级链
- ffmpeg 音频修复失败自动回滚原始文件

### 6.5 流式架构

WebUI 基于 Python 生成器（yield）实现流式推送，LLM 每生成一个 token 即刻推送到前端，用户无需等待完整回复即可开始阅读。

---

## 七、技术栈总览

| 技术领域 | 技术选型 | 用途 |
|----------|----------|------|
| LLM 大模型 | DeepSeek-V4-Pro / DeepSeek-Chat | 角色对话生成，流式输出 |
| LLM 框架 | LangChain + langchain-openai | Prompt、Chain、Callback |
| RAG 检索引擎 | FAISS + sentence-transformers | 向量检索、角色知识库 |
| 文本分割 | RecursiveCharacterTextSplitter | 角色文本分块 |
| 对话记忆 | ConversationBufferWindowMemory | 滑动窗口（10轮） |
| Web 界面 | Gradio 4.x | WebUI、流式推送 |
| 语音合成 | GPT-SoVITS API | 神经网络 TTS |
| 语音识别 | SpeechRecognition + Google ASR | 语音输入 |
| 音频播放 | python-vlc → pygame 降级 | 跨格式播放 |
| 音频处理 | ffmpeg (subprocess) | PCM 格式修复 |
| 情感检测 | 自研 EmotionEngine | 关键词 + 规范化 |
| 配置管理 | YAML + python-dotenv | 用户配置覆盖 |
| 数据存储 | JSON + 文件系统 | 角色库、对话持久化 |
| 开发语言 | Python 3.12 | 全部模块 |

---

## 八、项目文件结构

```
GPT-SoVITS-Character/
├── core/                          # 核心模块
│   ├── character_system.py        # 角色对话系统门面 (Facade)
│   ├── character_profile.py       # 角色数据 + 情感→音频动态映射
│   ├── rag_manager.py             # RAG 向量检索 (FAISS)
│   ├── emotion_engine.py          # 情感检测与规范化
│   ├── speech_synthesizer.py      # TTS + ffmpeg + VLC 播放
│   ├── memory_manager.py          # 对话记忆与持久化
│   ├── relationship_tracker.py    # 用户关系追踪
│   ├── config.py                  # 配置管理
│   └── audio_player.py            # 独立音频播放器
├── webui.py                       # WebUI 主界面 (Gradio)
├── webui_test02.py                # WebUI 精简版
├── main.py                        # 命令行对话入口
├── test02.py                      # CLI 测试脚本（含性能计时）
├── character_database.json        # 角色数据库
├── config.yaml                    # 用户配置文件
├── .env                           # 环境变量（API Key）
└── requirements.txt               # Python 依赖
```

---

## 九、项目总结

本项目从零构建了一个完整的智能角色对话系统，涵盖了从用户输入、情感感知、知识检索、大模型生成、到情感自适应语音合成的全链路技术实现。

**展现的核心能力：**

- **系统架构设计**：分层模块化、门面模式、配置驱动
- **多技术栈整合**：LLM、RAG、情感计算、语音合成、Web 前端
- **工程化实践**：错误处理、降级策略、流式架构、性能计时
- **创新方案设计**：情感自适应语音合成、动态参考音频选择
- **全栈实现**：Python 核心 → Web 前端 → CLI 工具

---

> 技术栈关键词：`Python` `LangChain` `DeepSeek` `GPT-SoVITS` `FAISS` `Sentence-Transformers` `Gradio` `VLC` `ffmpeg` `RAG` `Emotion AI` `TTS`
