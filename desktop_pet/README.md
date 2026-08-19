# character-desktop-pet（角色桌宠脚手架）

GPT-SoVITS 角色对话系统（Phase 4）的桌宠前端脚手架：**Electron 透明窗口 + PixiJS 渲染 + Live2D 预留 + WebSocket 对接后端**。

当前为"可运行的骨架"：窗口与渲染链路完整，Live2D 动画、语音播放/嘴型同步为后续阶段（Phase 5 / 6）接入，本阶段只提供接口占位。

## 目录结构

```
desktop_pet/
├── package.json        # npm 工程配置（name=character-desktop-pet, main=main.js, start=electron .）
├── main.js             # Electron 主进程：透明/无边框/置顶/skipTaskbar 窗口 + 托盘占位 + MODEL_URL 预留
├── renderer/
│   ├── index.html      # 页面骨架：#canvas 容器、加载提示、错误提示、底部状态栏
│   ├── main.js         # 渲染进程：PixiJS 初始化 + Live2D 加载接口预留 + WebSocket 客户端 + 音量条占位
│   └── style.css       # 样式：全透明背景容器、半透明状态栏
└── README.md           # 本文档
```

## 依赖安装

```bash
cd desktop_pet
npm install electron pixi.js
```

> 说明：本脚手架 `package.json` 中未声明依赖，请按上面命令安装。`node_modules` 生成后可执行 `npm start` 启动桌宠。

### Live2D 渲染依赖（Phase 5 接入时安装）

```bash
npm install pixi-live2d-display-lipsyncpatch
```

并将 Cubism 核心运行时 `live2dcubismcore.min.js` 放入 `renderer/`（或通过 script 标签引入），供 `pixi-live2d-display-lipsyncpatch` 使用。

## 启动方式

```bash
npm start            # 等价于 electron .
```

启动后会出现一个 1280x720 的全透明置顶窗口，底部状态栏显示连接状态；后端未启动时每 3 秒自动重连（最多 10 次）。

## 与 Python 后端（api/main.py）的 WebSocket 对接

后端 FastAPI 服务已提供桌宠专用 WebSocket 通道（见 `api/main.py` 顶部注释与 `/ws/pet` 路由），协议如下：

### 后端 → 桌宠（`ws://127.0.0.1:8765` 或 `ws://127.0.0.1:<port>/ws/pet`）

| type | 字段 | 说明 |
| --- | --- | --- |
| `text` | `content: str` | 回复文本（完整一段） |
| `emotion` | `emotion: str`, `intensity: float` | 情感名 + 强度 0.0~1.0 |
| `state` | `state: "thinking" \| "speaking" \| "idle"` | 对话阶段状态 |
| `audio` | `path: str`, `seq: int` | 一句语音的音频文件路径与序号（逐句推送） |
| `error` | `content: str` | 错误信息 |

典型一轮对话的推送顺序（`_ws_handle_chat`）：

```
state=thinking → text → emotion → state=speaking → audio(seq=1..n) → state=idle
```

### 桌宠 → 后端

| type | 字段 | 说明 |
| --- | --- | --- |
| `chat` | `text: str`（可选 `character: str` 指定角色） | 发送用户输入，触发一轮对话 |
| `interrupt` | — | 中断当前合成/播放，后端会立刻回 `state=idle` |

### 端口对齐（重要）

- 渲染进程默认连接 `ws://127.0.0.1:8765`（见 `renderer/main.js` 顶部 `WS_URL` 常量）；
- 后端 `api/main.py` 默认端口为 **8000**，WebSocket 路径为 `/ws/pet`（`DEFAULT_PORT = 8000`）。

两者不一致时二选一：

1. 启动后端时把端口配成 8765（后端从 config 读取 host/port，或修改 `api/main.py` 的 `DEFAULT_PORT`）；
2. 或修改 `renderer/main.js` 中 `WS_URL` 为 `ws://127.0.0.1:8000/ws/pet`。

### 断线重连

渲染进程内置自动重连：连接断开后每 3 秒重试一次，最多 10 次；达到上限后停止并在页面上提示，需确认后端已启动后刷新页面（或重启桌宠）恢复。

## 预留接口与 TODO（后续阶段）

| 位置 | 预留 | 阶段 |
| --- | --- | --- |
| `main.js` 顶部 `MODEL_URL` | Live2D 模型地址（本地 `models/` 或远程 URL） | Phase 5 |
| `renderer/main.js` `loadLive2DModel()` | 模型加载入口（fetch 配置 + `Live2DModel.from`） | Phase 5 |
| `renderer/main.js` `updateEmotion()` | 情感 → Live2D 表情/参数映射 | Phase 5 |
| `renderer/main.js` `setupAudioAnalyser()` | AnalyserNode 音量分析 → `ParamMouthOpenY` 嘴型 | Phase 6 |
| `renderer/main.js` `handleMessage()` 的 `audio` 分支 | 音频播放与嘴型同步 | Phase 6 |

## 安全说明

脚手架阶段为方便起见，`main.js` 中 `webPreferences` 使用了 `nodeIntegration: true` 与 `contextIsolation: false`。**生产环境必须改为 `contextIsolation: true`，并通过 preload 脚本暴露受控 API**（参见 `main.js` 内注释）。
