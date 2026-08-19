/**
 * 桌宠渲染进程（renderer/main.js）
 *
 * 职责：
 *  1. 初始化 PixiJS（透明渲染器，挂载到 #canvas）
 *  2. 预留 Live2D 模型加载接口 loadLive2DModel()
 *     —— 后续接入 pixi-live2d-display-lipsyncpatch + live2dcubismcore.min.js
 *  3. WebSocket 客户端：连接 ws://127.0.0.1:8765，处理后端消息
 *     text / emotion / audio / state（error 一并兜底）
 *  4. 断线自动重连（每 3 秒重试，最多 10 次）
 *  5. 音量条占位：预留 AnalyserNode 分析器，后续驱动嘴型参数 ParamMouthOpenY
 *
 * 注意：本文件运行于 Node.js 环境（nodeIntegration: true），
 * 因此可直接 require('pixi.js') 与 ws（若以 CDN 方式引入则改用 import/script 标签）。
 */

// ---------------------------------------------------------------------------
// 依赖引入（脚手架阶段使用本地模块；后续可切换为 CDN script 标签引入）
// ---------------------------------------------------------------------------
const { Application } = require('pixi.js');

// ---------------------------------------------------------------------------
// 常量区
// ---------------------------------------------------------------------------

/** 后端 WebSocket 地址（GPT-SoVITS api/main.py 桌宠通道，见 README 协议说明） */
const WS_URL = 'ws://127.0.0.1:8765';

/** 断线重连间隔（毫秒） */
const RECONNECT_INTERVAL_MS = 3000;

/** 断线重连最大次数（达到后停止重连，等待用户手动刷新） */
const MAX_RECONNECT_ATTEMPTS = 10;

/** 画布宽高（与 Electron 窗口一致） */
const STAGE_WIDTH = 1280;
const STAGE_HEIGHT = 720;

/**
 * Live2D 模型配置地址（预留，Phase 4 暂未使用）
 * TODO: 后续与主进程 MODEL_URL 保持一致，或改为从配置读取；
 *       可指向本地 models/ 目录下的 .model3.json 或远程 URL。
 */
const MODEL_URL = '';

// ---------------------------------------------------------------------------
// 全局状态
// ---------------------------------------------------------------------------

/** PixiJS 应用实例 */
let app = null;

/** 当前情感状态（供 updateEmotion 写入、状态栏展示） */
let currentEmotion = '平静';

/** 当前情感强度 0.0 ~ 1.0 */
let currentIntensity = 0.0;

/** 当前后端状态（thinking / speaking / idle） */
let currentState = 'idle';

/** WebSocket 实例 */
let ws = null;

/** 重连相关计数与标志 */
let reconnectAttempts = 0;   // 已重连次数
let reconnectTimer = null;   // 重连定时器句柄
let manuallyClosed = false;  // 是否主动关闭（主动关闭不再重连）

// ---------------------------------------------------------------------------
// DOM 引用
// ---------------------------------------------------------------------------
const loadingEl = document.getElementById('loading');   // 加载状态提示
const errorEl = document.getElementById('error');       // 错误提示
const statusLabelEl = document.getElementById('status-label'); // 状态栏左侧（状态）
const emotionLabelEl = document.getElementById('emotion-label'); // 状态栏右侧（情感）

// ---------------------------------------------------------------------------
// PixiJS 初始化
// ---------------------------------------------------------------------------

/**
 * 初始化 PixiJS 渲染器
 *  - 透明背景：alpha 与 transparent 保证页面 CSS 透明背景透出
 *  - 挂载到 #canvas 容器
 */
async function initPixi() {
  showLoading('正在初始化渲染器…');

  app = new Application({
    width: STAGE_WIDTH,
    height: STAGE_HEIGHT,
    backgroundColor: 0x000000,
    backgroundAlpha: 0,        // 画布全透明
    transparent: true,         // 允许透明背景（旧版兼容写法）
    antialias: true,           // 抗锯齿（Live2D 边缘更平滑）
    resolution: window.devicePixelRatio || 1,
    autoDensity: true
  });

  // 把 PixiJS 画布挂载到 #canvas 容器
  const canvasContainer = document.getElementById('canvas');
  canvasContainer.appendChild(app.view);

  // TODO(Phase 5): 加载 Live2D 模型
  // await loadLive2DModel(MODEL_URL);

  hideLoading();
}

// ---------------------------------------------------------------------------
// Live2D 模型加载接口（预留）
// ---------------------------------------------------------------------------

/**
 * 加载 Live2D 模型（占位实现）
 *
 * TODO(Phase 5) 接入步骤：
 *  1. npm install pixi-live2d-display-lipsyncpatch
 *  2. 将 live2dcubismcore.min.js 放入 renderer/ 并 <script> 引入（或 require）
 *  3. 注册 Live2D 插件：
 *       const { Live2DModel } = require('pixi-live2d-display-lipsyncpatch');
 *       window.PIXI = PIXI;            // 插件需要全局 PIXI
 *       Live2DModel.registerTicker(app.ticker);
 *  4. 加载模型：
 *       const model = await Live2DModel.from(modelUrl, { autoInteract: false });
 *       model.scale.set(0.2);
 *       model.anchor.set(0.5, 0.5);
 *       model.x = STAGE_WIDTH / 2;
 *       model.y = STAGE_HEIGHT / 2;
 *       app.stage.addChild(model);
 *
 * @param {string} modelUrl 模型配置地址（.model3.json）
 */
async function loadLive2DModel(modelUrl) {
  if (!modelUrl) {
    console.warn('[桌宠] MODEL_URL 未配置，跳过 Live2D 模型加载');
    return null;
  }

  // 占位：预留 fetch 流程（读取模型配置，后续交给 pixi-live2d-display）
  showLoading('正在加载 Live2D 模型…');
  try {
    const resp = await fetch(modelUrl);
    if (!resp.ok) {
      throw new Error(`模型配置请求失败: HTTP ${resp.status}`);
    }
    const modelConfig = await resp.json();
    console.log('[桌宠] Live2D 模型配置:', modelConfig);

    // TODO(Phase 5): 在此调用 Live2DModel.from(...) 并挂载到 app.stage
    return modelConfig;
  } catch (err) {
    showError(`Live2D 模型加载失败: ${err.message}`);
    return null;
  } finally {
    hideLoading();
  }
}

// ---------------------------------------------------------------------------
// WebSocket 客户端
// ---------------------------------------------------------------------------

/**
 * 建立 WebSocket 连接
 *  - 连接成功：清空重连计数，注册消息处理
 *  - 连接关闭：若非主动关闭且未超最大次数，3 秒后自动重连
 */
function connectWebSocket() {
  // 清理上一次重连定时器（防止并发重连）
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }

  showLoading(`正在连接后端 (${WS_URL})…`);

  try {
    ws = new WebSocket(WS_URL);
  } catch (err) {
    // 构造 WebSocket 即抛异常（如非法 URL），走统一重连逻辑
    scheduleReconnect();
    return;
  }

  // ---- 连接建立 ----
  ws.onopen = () => {
    reconnectAttempts = 0; // 成功连接后重置重连次数
    hideLoading();
    console.log('[桌宠] WebSocket 已连接:', WS_URL);
    // 连接成功后，把"未读"状态补发？——无需，状态以服务端推送为准
  };

  // ---- 收到消息：按 type 分发 ----
  ws.onmessage = (event) => {
    handleMessage(event.data);
  };

  // ---- 连接异常（网络错误等） ----
  ws.onerror = (err) => {
    console.error('[桌宠] WebSocket 错误:', err);
    // onclose 会随后触发，重连逻辑统一放在 onclose 中
  };

  // ---- 连接关闭 ----
  ws.onclose = () => {
    console.warn('[桌宠] WebSocket 连接关闭');
    if (!manuallyClosed) {
      scheduleReconnect();
    }
  };
}

/**
 * 安排一次自动重连（每 3 秒一次，最多 MAX_RECONNECT_ATTEMPTS 次）
 */
function scheduleReconnect() {
  if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
    showError(`后端连接失败（已重试 ${MAX_RECONNECT_ATTEMPTS} 次），请确认 api/main.py 已启动`);
    return;
  }

  reconnectAttempts += 1;
  showLoading(
    `后端连接断开，${RECONNECT_INTERVAL_MS / 1000} 秒后重连 ` +
    `(${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})…`
  );

  reconnectTimer = setTimeout(() => {
    connectWebSocket();
  }, RECONNECT_INTERVAL_MS);
}

/**
 * 主动关闭连接（后续点击退出等场景调用；主动关闭后不再自动重连）
 */
function disconnectWebSocket() {
  manuallyClosed = true;
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (ws) {
    ws.close();
    ws = null;
  }
}

// ---------------------------------------------------------------------------
// 消息处理（后端 → 桌宠）
// ---------------------------------------------------------------------------

/**
 * 分发后端消息（协议见 README.md / api/main.py 顶部注释）
 *   {"type":"text","content":str}
 *   {"type":"emotion","emotion":str,"intensity":float}
 *   {"type":"state","state":"thinking"|"speaking"|"idle"}
 *   {"type":"audio","path":str,"seq":int}
 *   {"type":"error","content":str}
 *
 * @param {string} raw 原始 JSON 字符串
 */
function handleMessage(raw) {
  let msg;
  try {
    msg = JSON.parse(raw);
  } catch (err) {
    console.warn('[桌宠] 收到非 JSON 消息，已忽略:', raw);
    return;
  }

  switch (msg.type) {
    case 'text':
      // 文本消息：Phase 4 仅打印到控制台，后续可接入字幕气泡
      console.log('[桌宠] 文本:', msg.content);
      break;

    case 'emotion':
      // 情感消息：更新状态栏情感显示，并驱动预留接口 updateEmotion
      currentEmotion = msg.emotion || '平静';
      currentIntensity = typeof msg.intensity === 'number' ? msg.intensity : 0.0;
      updateEmotion(currentEmotion, currentIntensity);
      break;

    case 'state':
      // 状态消息：thinking / speaking / idle
      currentState = msg.state || 'idle';
      updateStatusBar();
      break;

    case 'audio':
      // 音频消息：path 为后端合成的音频文件路径，seq 为句子序号
      // TODO(Phase 6): 调用 audio_player / 音量分析器驱动嘴型
      console.log(`[桌宠] 音频: path=${msg.path}, seq=${msg.seq}`);
      break;

    case 'error':
      // 后端错误消息：展示到错误提示条
      showError(`后端错误: ${msg.content || '未知错误'}`);
      break;

    default:
      console.warn('[桌宠] 未知消息类型:', msg.type);
  }
}

// ---------------------------------------------------------------------------
// 表情 / 状态更新接口
// ---------------------------------------------------------------------------

/**
 * 更新情感显示（预留接口）
 * TODO(Phase 5): 在此把 emotion 映射到 Live2D 表情参数
 *   （如 Expression 切换、EyeOpen / MouthForm 等参数插值），
 *   Phase 4 仅更新状态栏文字。
 *
 * @param {string} emotion  情感名（如 平静 / 开心 / 生气）
 * @param {number} intensity 情感强度 0.0 ~ 1.0
 */
function updateEmotion(emotion, intensity) {
  emotionLabelEl.textContent = `情感: ${emotion}`;
  console.log(`[桌宠] 情感更新: ${emotion} (强度 ${intensity})`);
}

/**
 * 刷新状态栏（thinking / speaking / idle）
 */
function updateStatusBar() {
  statusLabelEl.textContent = `状态: ${currentState}`;
}

// ---------------------------------------------------------------------------
// 音量分析器占位（AnalyserNode 预留）
// ---------------------------------------------------------------------------

/**
 * 音量分析器占位（Phase 4 仅预留结构，不做真实分析）
 *
 * TODO(Phase 6) 接入嘴型同步：
 *  1. 后端下发 audio 消息后，用 Web Audio API 播放音频：
 *       const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
 *       const analyser = audioCtx.createAnalyser();
 *       analyser.fftSize = 512;
 *       source.connect(analyser);
 *       analyser.connect(audioCtx.destination);
 *  2. 在 rAF 循环中读取音量：
 *       const data = new Uint8Array(analyser.frequencyBinCount);
 *       analyser.getByteFrequencyData(data);
 *       const volume = 音量归一化值(0~1);
 *  3. 用 volume 驱动 Live2D 嘴部参数：
 *       model.internalModel.motionManager.expressionManager.parameters
 *            .setValueById('ParamMouthOpenY', volume);
 */
function setupAudioAnalyser() {
  // 占位：Phase 4 无音频播放，仅注释说明后续实现
  // const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  // this.analyser = audioCtx.createAnalyser();
  console.log('[桌宠] 音频分析器占位（ParamMouthOpenY 待 Phase 6 接入）');
}

// ---------------------------------------------------------------------------
// UI 辅助函数
// ---------------------------------------------------------------------------

/** 显示加载状态 */
function showLoading(text) {
  if (text) {
    loadingEl.textContent = text;
  }
  loadingEl.classList.remove('hidden');
}

/** 隐藏加载状态 */
function hideLoading() {
  loadingEl.classList.add('hidden');
}

/** 显示错误提示（3 秒后自动隐藏） */
function showError(text) {
  errorEl.textContent = text;
  errorEl.classList.remove('hidden');
  setTimeout(() => {
    errorEl.classList.add('hidden');
  }, 3000);
}

// ---------------------------------------------------------------------------
// 启动入口
// ---------------------------------------------------------------------------

(async function main() {
  // 1. 初始化 PixiJS 渲染器
  await initPixi();

  // 2. 预留：加载 Live2D 模型（Phase 4 未配置 MODEL_URL，跳过）
  await loadLive2DModel(MODEL_URL);

  // 3. 预留：初始化音频分析器（Phase 4 占位）
  setupAudioAnalyser();

  // 4. 连接后端 WebSocket（断线自动重连）
  connectWebSocket();
})();
