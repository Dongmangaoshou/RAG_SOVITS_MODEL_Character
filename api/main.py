"""FastAPI 统一服务 —— 低延迟对话链路 HTTP / WebSocket 出口。

路由一览：
- POST  /v1/chat                    同步对话  {"character","text"} -> {"response","emotion","memory_injected"}
- POST  /v1/chat/stream             SSE 流式对话（text/event-stream），逐 token 推 {"token": "..."}，结束推 {"done": true}
- GET   /v1/memory/{character}                   列出记忆事件
- DELETE /v1/memory/{character}/{event_id}       删除记忆事件
- GET   /v1/emotion/{character}                  情感状态机当前状态（若可用）
- WS    /ws/pet                                  桌宠 WebSocket 通道

WebSocket 消息协议：
- 后端 → 桌宠: {"type":"text","content":str}
                {"type":"emotion","emotion":str,"intensity":float}
                {"type":"state","state":"thinking"|"speaking"|"idle"}
                {"type":"audio","path":str,"seq":int}
                {"type":"error","content":str}
- 桌宠 → 后端: {"type":"chat","text":str}   （可选携带 "character" 指定角色）
                {"type":"interrupt"}

依赖说明：
- fastapi / uvicorn 缺失时模块仍可导入（app=None），启动入口给出安装提示；
- 项目核心类缺失时所有路由统一返回 503 {"error": str}；
- EmotionFSM / SemanticDetector 为可选类（当前代码库可能不存在），缺失时自动降级。
"""

# 延迟求值所有类型注解：核心类缺失时模块仍可导入（注解只在 get_type_hints 时求值）
from __future__ import annotations

import asyncio
import json
import sys
import threading
from pathlib import Path

# ---- 项目根路径注入（支持 `python api/main.py` 与 `python -m api.main` 两种启动）-----
_THIS_DIR = Path(__file__).resolve().parent          # .../api
_PROJECT_ROOT = _THIS_DIR.parent                      # 项目根目录
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---- 可选依赖：FastAPI / uvicorn（缺失则降级提示） ------------------
try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, StreamingResponse
    import uvicorn
    _FASTAPI_AVAILABLE = True
    _FASTAPI_IMPORT_ERROR = ""
except ImportError as _e:
    _FASTAPI_AVAILABLE = False
    _FASTAPI_IMPORT_ERROR = str(_e)

# ---- 项目核心类（缺失则能力不可用，路由返回 503） --------------------
try:
    from core.config import CONFIG, SCRIPT_DIR, CHARACTER_DB
    from core.character_profile import CharacterProfile
    from core.character_system import AdvancedCharacterSystem
    from core.speech_synthesizer import SpeechSynthesizer
    from core.rag_manager import RagManager
    from core.memory import MemoryV2
    from core.tts.cache import TTSCache
    from core.tts.pipeline import SentencePipeline
    _CORE_AVAILABLE = True
    _CORE_IMPORT_ERROR = ""
except ImportError as _e:
    _CORE_AVAILABLE = False
    _CORE_IMPORT_ERROR = str(_e)

# ---- 可选类：EmotionFSM / SemanticDetector / EmotionAudioMatcher（EI v2 包） --
try:
    from core.emotion import SemanticDetector, EmotionFSM, EmotionAudioMatcher
    _EMOTION_V2_AVAILABLE = True
except ImportError:
    SemanticDetector = None
    EmotionFSM = None
    EmotionAudioMatcher = None
    _EMOTION_V2_AVAILABLE = False
    try:
        from core.emotion_engine import EmotionEngine
    except ImportError:
        EmotionEngine = None
    else:
        EmotionEngine = EmotionEngine  # 兼容旧关键词引擎


# ---- 模块级常量（所有魔法数字集中于此） --------------------------------
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
SSE_MEDIA_TYPE = "text/event-stream"
MEMORY_LIST_LIMIT = 50
MEMORY_LIST_LIMIT_MAX = 200
DEFAULT_EMOTION = "平静"
EMOTION_NEUTRAL_INTENSITY = 0.0
EMOTION_ACTIVE_INTENSITY = 0.5
WS_STATE_THINKING = "thinking"
WS_STATE_SPEAKING = "speaking"
WS_STATE_IDLE = "idle"
WS_MSG_TEXT = "text"
WS_MSG_EMOTION = "emotion"
WS_MSG_STATE = "state"
WS_MSG_AUDIO = "audio"
WS_MSG_ERROR = "error"
WS_MSG_CHAT = "chat"
WS_MSG_INTERRUPT = "interrupt"
DEFAULT_CHARACTER = "明日香"
CACHE_MAX_ENTRIES = 1000
MAX_SENTENCE_LEN = 30


def _latency_cfg(key: str, default):
    """读取 CONFIG["latency"] 分区（可后补），CONFIG 不可用时返回默认值"""
    try:
        return CONFIG.get("latency", {}).get(key, default)
    except Exception:
        return default


# 读取 latency 分区配置（存在则覆盖上方默认常量）
DEFAULT_CHARACTER = str(_latency_cfg("default_character", DEFAULT_CHARACTER))
CACHE_MAX_ENTRIES = int(_latency_cfg("cache_max_entries", CACHE_MAX_ENTRIES))
MAX_SENTENCE_LEN = int(_latency_cfg("max_sentence_len", MAX_SENTENCE_LEN))


# ---- 全局单例（惰性初始化，失败抛 ServiceUnavailableError → 503） -------
class ServiceUnavailableError(Exception):
    """服务初始化失败（路由返回 503）"""


_systems: dict = {}
_systems_lock = threading.Lock()
_rag: RagManager | None = None
_rag_lock = threading.Lock()
_memories: dict = {}
_memories_lock = threading.Lock()
_emotion_fsms: dict = {}
_emotion_fsms_lock = threading.Lock()
_pipeline: SentencePipeline | None = None
_pipeline_lock = threading.Lock()
_cache: TTSCache | None = None
_cache_lock = threading.Lock()
_tts: SpeechSynthesizer | None = None
_tts_lock = threading.Lock()


def _get_rag() -> RagManager:
    """RagManager 全局单例"""
    global _rag
    if _rag is None:
        with _rag_lock:
            if _rag is None:
                try:
                    _rag = RagManager()
                except Exception as e:
                    raise ServiceUnavailableError(f"RagManager 初始化失败: {e}") from e
    return _rag


def _get_system(character: str) -> AdvancedCharacterSystem:
    """按角色缓存的 AdvancedCharacterSystem 单例（惰性初始化）"""
    sys = _systems.get(character)
    if sys is None:
        with _systems_lock:
            sys = _systems.get(character)
            if sys is None:
                try:
                    rag = _get_rag()
                    # 只为当前角色构建向量库，避免全量加载 embedding 模型
                    rag.build(CharacterProfile(character))
                    sys = AdvancedCharacterSystem(character, rag)
                    _systems[character] = sys
                except Exception as e:
                    raise ServiceUnavailableError(
                        f"角色系统初始化失败 ({character}): {e}"
                    ) from e
    return sys


def _get_memory(character: str) -> MemoryV2:
    """按角色缓存的 MemoryV2 单例（惰性初始化）"""
    mem = _memories.get(character)
    if mem is None:
        with _memories_lock:
            mem = _memories.get(character)
            if mem is None:
                try:
                    mem = MemoryV2(character)
                    _memories[character] = mem
                except Exception as e:
                    raise ServiceUnavailableError(
                        f"记忆系统初始化失败 ({character}): {e}"
                    ) from e
    return mem


def _get_emotion_fsm(character: str):
    """EmotionFSM 单例；类不存在或初始化失败返回 None"""
    if EmotionFSM is None:
        return None
    fsm = _emotion_fsms.get(character)
    if fsm is None:
        with _emotion_fsms_lock:
            fsm = _emotion_fsms.get(character)
            if fsm is None:
                try:
                    # EmotionFSM 签名: __init__(state="平静", intensity=0.0)
                    fsm = EmotionFSM()
                except Exception:
                    return None
                _emotion_fsms[character] = fsm
    return fsm


def _get_tts() -> SpeechSynthesizer:
    """SpeechSynthesizer 全局单例"""
    global _tts
    if _tts is None:
        with _tts_lock:
            if _tts is None:
                try:
                    _tts = SpeechSynthesizer()
                except Exception as e:
                    raise ServiceUnavailableError(f"TTS 初始化失败: {e}") from e
    return _tts


def _get_pipeline() -> SentencePipeline:
    """SentencePipeline 全局单例"""
    global _pipeline
    if _pipeline is None:
        with _pipeline_lock:
            if _pipeline is None:
                try:
                    _pipeline = SentencePipeline(max_len=MAX_SENTENCE_LEN)
                except Exception as e:
                    raise ServiceUnavailableError(f"合成流水线初始化失败: {e}") from e
    return _pipeline


def _get_cache() -> TTSCache | None:
    """TTSCache 全局单例；CONFIG["latency"]["cache_enabled"]=False 时禁用（返回 None）"""
    global _cache
    if _cache is None:
        with _cache_lock:
            if _cache is None:
                if not _latency_cfg("cache_enabled", True):
                    return None
                try:
                    _cache = TTSCache(max_entries=CACHE_MAX_ENTRIES)
                except Exception as e:
                    raise ServiceUnavailableError(f"磁盘缓存初始化失败: {e}") from e
    return _cache


# ---- 情感 / 记忆辅助 ------------------------------------------------
_detectors: dict = {}
_detectors_lock = threading.Lock()


def _get_detector() -> SemanticDetector | None:
    """SemanticDetector 全局单例；EI v2 不可用返回 None"""
    if not _EMOTION_V2_AVAILABLE:
        return None
    global _detectors
    det = _detectors.get("__singleton__")
    if det is None:
        with _detectors_lock:
            det = _detectors.get("__singleton__")
            if det is None:
                try:
                    det = SemanticDetector()
                    _detectors["__singleton__"] = det
                except Exception:
                    return None
    return det


def _detect_emotion(character: str, text: str) -> tuple[str, float]:
    """情感检测（EI v2）：SemanticDetector 语义识别 → EmotionFSM 状态转移。
    返回 (角色状态, 强度)。EI v2 不可用时回退关键词引擎。"""
    fsm = _get_emotion_fsm(character)
    det = _get_detector()
    if fsm is not None and det is not None:
        try:
            det_result = det.detect(text, llm=None)
            user_emotion = str(det_result.get("emotion", DEFAULT_EMOTION))
            user_intensity = float(det_result.get("intensity", 0.0))
            fsm.update(user_emotion, user_intensity, text)
            state = getattr(fsm, "state", None) or DEFAULT_EMOTION
            intensity = float(getattr(fsm, "intensity", 0.0) or 0.0)
            return str(state), intensity
        except Exception:
            pass
    # 兜底：旧关键词引擎（仅状态，无强度）
    if EmotionEngine is not None:
        try:
            emotion = EmotionEngine().detect(text)
        except Exception:
            emotion = DEFAULT_EMOTION
        intensity = EMOTION_ACTIVE_INTENSITY if emotion != DEFAULT_EMOTION else EMOTION_NEUTRAL_INTENSITY
        return emotion, intensity
    return DEFAULT_EMOTION, EMOTION_NEUTRAL_INTENSITY


def _resolve_emotion_audio(character: str, profile, emotion: str, intensity: float) -> tuple[str, str]:
    """情感→参考音频：优先 EmotionAudioMatcher（状态+强度匹配），回退 profile 原逻辑"""
    if _EMOTION_V2_AVAILABLE and EmotionAudioMatcher is not None:
        try:
            matcher = EmotionAudioMatcher()
            intimacy = "熟人"
            try:
                mem = _get_memory(character)
                intimacy = mem.relationship.intimacy_level
            except Exception:
                pass
            return matcher.resolve(profile, emotion, intensity, intimacy)
        except Exception:
            pass
    # 回退：profile 原逻辑（按用户情感取音频）
    try:
        return profile.resolve_emotion_audio(emotion)
    except Exception:
        return profile.resolve_emotion_audio(DEFAULT_EMOTION)


def _memory_injected(character: str, text: str) -> bool:
    """判断记忆是否已注入（能构建出非空上下文即视为注入）"""
    try:
        mem = _get_memory(character)
        ctx = mem.build_context(text)
        return bool(ctx and ctx.strip())
    except Exception:
        return False


# ---- SSE 辅助 ------------------------------------------------------
def _sse(data: str) -> str:
    """把 JSON 字符串包装成 SSE 事件帧"""
    return f"data: {data}\n\n"


def _sse_generator(system: AdvancedCharacterSystem, text: str):
    """把 generate_response_stream 的累积文本转成 SSE token 增量事件。

    说明：generate_response_stream 每轮 yield 的是"累积文本"，这里取增量；
    末尾可能带角色元素注入（与已推送文本不构成前缀关系），此时跳过该轮，
    避免 token 重复。结束推 {"done": true}，异常推 {"error": str}。
    """
    prev = ""
    it = iter(system.generate_response_stream(text))
    try:
        while True:
            try:
                raw, _audio_path, _status = next(it)
            except StopIteration:
                break
            if raw != prev:
                delta = raw[len(prev):] if raw.startswith(prev) else ""
                if delta:
                    yield _sse(json.dumps({"token": delta}, ensure_ascii=False))
                prev = raw
        yield _sse(json.dumps({"done": True}))
    except Exception as e:
        yield _sse(json.dumps({"error": str(e)}, ensure_ascii=False))


# ---- FastAPI 应用与路由（仅当 fastapi 可用时注册） ----------------------
app = None  # type: ignore

if _FASTAPI_AVAILABLE:
    app = FastAPI(title="GPT-SoVITS 低延迟对话 API", version="0.1.0")

    # CORS 全开
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -- 同步对话 -------------------------------------------------
    @app.post("/v1/chat")
    async def chat(payload: dict):
        """同步对话：{"character","text"} -> {"response","emotion","memory_injected"}"""
        try:
            character = payload.get("character") or DEFAULT_CHARACTER
            text = str(payload.get("text") or "").strip()
            if not text:
                return JSONResponse({"error": "缺少 text 字段"}, status_code=400)
            if not _CORE_AVAILABLE:
                return JSONResponse(
                    {"error": f"核心模块导入失败: {_CORE_IMPORT_ERROR}"}, status_code=503
                )
            system = await asyncio.to_thread(_get_system, character)
            response = await asyncio.to_thread(system.generate_response, text)
            emotion, _intensity = _detect_emotion(character, text)
            return {
                "response": response,
                "emotion": emotion,
                "memory_injected": _memory_injected(character, text),
            }
        except ServiceUnavailableError as e:
            return JSONResponse({"error": str(e)}, status_code=503)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # -- SSE 流式对话 ---------------------------------------------
    @app.post("/v1/chat/stream")
    async def chat_stream(payload: dict):
        """SSE 流式对话：逐 token 推 {"token": "..."}，结束推 {"done": true}"""
        try:
            character = payload.get("character") or DEFAULT_CHARACTER
            text = str(payload.get("text") or "").strip()
            if not text:
                return JSONResponse({"error": "缺少 text 字段"}, status_code=400)
            if not _CORE_AVAILABLE:
                return JSONResponse(
                    {"error": f"核心模块导入失败: {_CORE_IMPORT_ERROR}"}, status_code=503
                )
            system = await asyncio.to_thread(_get_system, character)
            return StreamingResponse(
                _sse_generator(system, text),
                media_type=SSE_MEDIA_TYPE,
            )
        except ServiceUnavailableError as e:
            return JSONResponse({"error": str(e)}, status_code=503)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # -- 记忆：列出 / 删除 -----------------------------------------
    @app.get("/v1/memory/{character}")
    async def list_memory(character: str, limit: int = MEMORY_LIST_LIMIT):
        """列出指定角色的记忆事件（含关系状态）"""
        try:
            if not _CORE_AVAILABLE:
                return JSONResponse(
                    {"error": f"核心模块导入失败: {_CORE_IMPORT_ERROR}"}, status_code=503
                )
            mem = await asyncio.to_thread(_get_memory, character)
            limit = max(1, min(int(limit), MEMORY_LIST_LIMIT_MAX))
            events = await asyncio.to_thread(mem.list_events, limit)
            relationship = None
            try:
                relationship = mem.get_relationship()
            except Exception:
                pass
            return {"character": character, "events": events,
                    "relationship": relationship}
        except ServiceUnavailableError as e:
            return JSONResponse({"error": str(e)}, status_code=503)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.delete("/v1/memory/{character}/{event_id}")
    async def delete_memory(character: str, event_id: int):
        """删除指定角色的某条记忆事件"""
        try:
            if not _CORE_AVAILABLE:
                return JSONResponse(
                    {"error": f"核心模块导入失败: {_CORE_IMPORT_ERROR}"}, status_code=503
                )
            mem = await asyncio.to_thread(_get_memory, character)
            await asyncio.to_thread(mem.delete_event, event_id)
            return {"deleted": event_id, "character": character}
        except ServiceUnavailableError as e:
            return JSONResponse({"error": str(e)}, status_code=503)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # -- 情感状态机 -----------------------------------------------
    @app.get("/v1/emotion/{character}")
    async def get_emotion(character: str):
        """返回情感状态机当前状态（EmotionFSM 不可用时返回 503）"""
        try:
            fsm = _get_emotion_fsm(character)
            if fsm is None:
                return JSONResponse(
                    {"error": "EmotionFSM 不可用（未安装或初始化失败）"}, status_code=503
                )
            state = (
                getattr(fsm, "current_state", None)
                or getattr(fsm, "state", None)
                or DEFAULT_EMOTION
            )
            intensity = float(getattr(fsm, "intensity", 0.0) or 0.0)
            # EI v2 输出表情名（Live2D 用）
            expression = ""
            try:
                expression = str(getattr(fsm, "state", "") or "")
            except Exception:
                pass
            hint = ""
            try:
                res = fsm._result()
                expression = res.get("expression", "")
                hint = res.get("hint", "")
            except Exception:
                pass
            return {"character": character, "emotion": state,
                    "intensity": intensity, "expression": expression,
                    "hint": hint}
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # -- 桌宠 WebSocket 通道 --------------------------------------
    @app.websocket("/ws/pet")
    async def ws_pet(websocket: WebSocket):
        """桌宠通道：收 chat / interrupt，回 text / emotion / state / audio / error"""
        await websocket.accept()
        interrupt = threading.Event()
        try:
            while True:
                msg = await websocket.receive_json()
                mtype = msg.get("type")
                if mtype == WS_MSG_CHAT:
                    await _ws_handle_chat(websocket, msg, interrupt)
                elif mtype == WS_MSG_INTERRUPT:
                    interrupt.set()
                    await websocket.send_json({WS_MSG_STATE: WS_STATE_IDLE})
                else:
                    await websocket.send_json({
                        WS_MSG_ERROR: f"未知消息类型: {mtype}"
                    })
        except WebSocketDisconnect:
            pass
        except Exception as e:
            try:
                await websocket.send_json({WS_MSG_ERROR: str(e)})
            except Exception:
                pass


async def _ws_handle_chat(websocket: WebSocket, msg: dict, interrupt: threading.Event):
    """处理一轮桌宠对话：thinking → 文本 → 情感 → 记忆 → 逐句语音 → idle"""
    character = msg.get("character") or DEFAULT_CHARACTER
    text = str(msg.get("text") or "").strip()
    if not text:
        await websocket.send_json({WS_MSG_ERROR: "chat 消息缺少 text"})
        return
    if not _CORE_AVAILABLE:
        await websocket.send_json({
            WS_MSG_ERROR: f"核心模块导入失败: {_CORE_IMPORT_ERROR}"
        })
        return

    try:
        system = await asyncio.to_thread(_get_system, character)
    except Exception as e:
        await websocket.send_json({WS_MSG_ERROR: str(e)})
        return

    await websocket.send_json({WS_MSG_STATE: WS_STATE_THINKING})

    # 1) 生成回复（阻塞式 LLM 调用，放到线程池执行）
    try:
        response = await asyncio.to_thread(system.generate_response, text)
    except Exception as e:
        await websocket.send_json({WS_MSG_ERROR: f"生成回复失败: {e}"})
        await websocket.send_json({WS_MSG_STATE: WS_STATE_IDLE})
        return

    if interrupt.is_set():
        interrupt.clear()  # 本轮已被打断
        await websocket.send_json({WS_MSG_STATE: WS_STATE_IDLE})
        return

    await websocket.send_json({WS_MSG_TEXT: response})

    # 2) 情感状态
    emotion, intensity = _detect_emotion(character, text)
    await websocket.send_json({
        WS_MSG_EMOTION: emotion,
        "intensity": float(intensity),
    })

    # 3) 记忆写入（尽力而为，失败静默）
    try:
        mem = await asyncio.to_thread(_get_memory, character)
        await asyncio.to_thread(mem.save_turn, text, response, emotion, False, True)
    except Exception:
        pass

    # 4) 逐句语音合成（支持 interrupt 中断后续句子）
    await websocket.send_json({WS_MSG_STATE: WS_STATE_SPEAKING})
    interrupt.clear()  # 开始新一轮合成前清空旧中断标志
    try:
        tts = _get_tts()
        cache = _get_cache()
        pipeline = _get_pipeline()
        ref_path, ref_text = _resolve_emotion_audio(character, system.profile, emotion, intensity)
        paths = await asyncio.to_thread(
            pipeline.synthesize_sequence,
            system.profile, response,
            ref_path, ref_text,
            tts, cache,
            emotion=emotion,
            stop_event=interrupt,
        )
        for i, p in enumerate(paths, start=1):
            if interrupt.is_set():
                break
            await websocket.send_json({WS_MSG_AUDIO: p, "seq": i})
    except Exception as e:
        await websocket.send_json({WS_MSG_ERROR: f"语音合成失败: {e}"})

    interrupt.clear()
    await websocket.send_json({WS_MSG_STATE: WS_STATE_IDLE})


# ---- 前端静态页面挂载（必须在所有 API 路由注册之后，避免拦截 /v1/*） -----
if _FASTAPI_AVAILABLE and app is not None:
    try:
        from fastapi.staticfiles import StaticFiles
        from pathlib import Path as _Path
        _web_root = _Path(__file__).resolve().parent.parent / "webui_v2"
        if _web_root.is_dir():
            app.mount("/", StaticFiles(directory=str(_web_root), html=True), name="webui")
            print(f"[WEB] 前端目录: {_web_root}")
    except Exception as _e:
        print(f"[警告] 前端挂载失败: {_e}")


# ---- 启动入口 ------------------------------------------------------
if __name__ == "__main__":
    if not _FASTAPI_AVAILABLE:
        print("[错误] 未安装 fastapi / uvicorn，无法启动 API 服务。")
        print(f"      导入错误: {_FASTAPI_IMPORT_ERROR}")
        print('      请先安装: pip install "fastapi[standard]" uvicorn')
        raise SystemExit(1)
    if not _CORE_AVAILABLE:
        print(f"[警告] 核心模块导入失败: {_CORE_IMPORT_ERROR}")
    host = str(_latency_cfg("host", DEFAULT_HOST))
    port = int(_latency_cfg("port", DEFAULT_PORT))
    print(f"[API] 启动于 http://{host}:{port}   (接口文档: http://{host}:{port}/docs)")
    print(f"[WEB] 前端页面: http://{host}:{port}/")
    uvicorn.run(app, host=host, port=port)
