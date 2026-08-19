# GPT-SoVITS Intelligent Character Dialogue System

**A Multi-Modal Virtual Character Interaction Platform Integrating RAG, LLM, Emotion AI, and Speech Synthesis**

---

## 1. Project Overview

A full-stack dialogue system enabling real-time conversation with anime/game characters via text or voice input. The system combines Retrieval-Augmented Generation (RAG) for character knowledge grounding, DeepSeek LLM for role-consistent response generation, and emotion-aware speech synthesis that dynamically selects reference audio based on detected user sentiment. The project demonstrates end-to-end integration of NLP, vector search, emotion computing, and speech technologies into a production-grade application with both Web and CLI interfaces.

---

## 2. Core Design

**Layered Architecture (4 tiers):**

- **Presentation Layer:** Gradio WebUI + CLI (character selection, text/voice dual-input, streaming chat, conversation history)
- **Business Logic Layer:** `AdvancedCharacterSystem` (Facade) orchestrating EmotionEngine, CharacterProfile, SpeechSynthesizer
- **Data Access Layer:** `RagManager` (FAISS vector search) + `MemoryManager` (sliding-window conversation memory with JSON persistence)
- **External Services Layer:** DeepSeek API, GPT-SoVITS API, SpeechRecognition, VLC

**Key Design Decisions:**
- Facade pattern for subsystem decoupling
- Deep-merge configuration (defaults + YAML overrides + .env)
- JSON-driven character database enabling zero-code character addition
- Graceful degradation chains (VLC→pygame, TTS→text-only)

---

## 3. System Flowchart

```
┌──────────────┐
│  User Input  │ (text / voice via SpeechRecognition)
└──────┬───────┘
       ▼
┌──────────────────┐
│ EmotionEngine    │  detect() → "sad"/"happy"/"angry"/"anxious"/"calm"
│ (keyword + norm) │
└──────┬───────────┘
       ▼
┌──────────────────┐
│ RagManager       │  FAISS.similarity_search(k=3)
│ (all-mpnet-base  │  → character lore fragments as context
│  + FAISS index)  │
└──────┬───────────┘
       ▼
┌──────────────────────────────┐
│ Prompt Construction          │
│  persona + RAG context       │  → LLMChain.invoke()
│  + emotion hint + history    │
└──────┬───────────────────────┘
       ▼
┌──────────────────┐
│ DeepSeek LLM     │  streaming tokens via Queue + Thread
│ (LangChain)      │  exponential backoff retry (max 3)
└──────┬───────────┘
       ▼
┌──────────────────────────────┐
│ CharacterProfile             │
│  resolve_emotion_audio()     │  emotion → random pick from
│   "sad" → "【悲郁】...mp3"   │  emotion_audio_map
│  auto-extract prompt_text    │  regex strip 【tag】+ ext
└──────┬───────────────────────┘
       ▼
┌──────────────────────────────┐
│ SpeechSynthesizer            │
│  GPT-SoVITS API call         │
│  → ffmpeg pcm_s16le fix      │
│  → VLC playback              │
└──────────────────────────────┘

Total pipeline latency: tracked per-round via time.time()
(LLM generation + TTS synthesis, displayed in CLI)
```

**Core Technologies Applied:**
RAG (FAISS + sentence-transformers) · Emotion Detection & Normalization · LangChain Prompt Engineering · Streaming Generation (Queue+Thread) · Emotion-Aware Dynamic Audio Selection · GPT-SoVITS API Integration · ffmpeg Audio Post-Processing · VLC/pygame Playback Chain · Conversation Memory Management & Persistence · Gradio WebUI with Server-Sent Events

---

## 4. Results & Demonstration

**Functional Achievements:**

- Supports 4 characters (Rem, Asuka, Yuuka, Ram) with rich persona profiles (15+ fields each), expandable via JSON
- Emotion detection across 5 categories (happy/sad/angry/anxious/calm), with 12+ synonyms per category normalized to standard labels
- Emotion-driven TTS: each dialogue round dynamically selects a matching reference audio from the character's emotional audio library (e.g., selecting a "melancholy" tone when detecting sadness)
- Dual-mode input: text keyboard entry + voice input via microphone with Google ASR
- Streaming display: LLM tokens appear in real-time, eliminating perceived latency
- Full conversation lifecycle: save/load/clear with JSON persistence, performance timing per round

**System Output Sample (CLI):**

```
[关系等级: 3/10]

Asuka: あんたバカ？こんなことで落ち込んでるの？...
  [3.2s LLM] [4.1s TTS ✓] [总计 7.5s]

[ref_wav]: custom_refs/Asuka参考音频/【生气】あんたバカ？肝心なときにいないなんて、なんて無自覚。.mp3
[prompt]:  あんたバカ？肝心なときにいないなんて、なんて無自覚。
```

**Technical Metrics:**
| Metric | Value |
|--------|-------|
| Codebase | ~2,500 lines Python across 12 modules |
| LLM Latency | 2–5s per response (DeepSeek) |
| TTS Latency | 3–6s per synthesis (GPT-SoVITS) |
| Emotion Accuracy | ~85% (keyword-based, 50+ terms) |
| Max History Window | 10 turns (configurable) |

---

> **Author's Note:** This project demonstrates proficiency in Python system architecture, multi-modal AI integration (LLM + RAG + TTS + ASR), API orchestration with fault-tolerance, real-time streaming design, and full-stack development from core logic to Web UI.
