/**
 * 桌宠 Electron 主进程
 *
 * 职责：
 *  - 创建透明、无边框、置顶、跳过任务栏的窗口（1280x720）
 *  - 加载 renderer/index.html（PixiJS / Live2D / WebSocket 均在渲染进程内完成）
 *  - 托盘图标占位（当前使用 nativeImage.createEmpty 的空图占位，后续替换为真实图标）
 *
 * 注意：
 *  - 脚手架阶段 webPreferences 简化开启了 nodeIntegration / 关闭 contextIsolation，
 *    仅为方便渲染进程直接 require pixi.js 等本地模块；生产环境必须开启
 *    contextIsolation 并使用 preload 暴露受控 API。
 */

const { app, BrowserWindow, Tray, nativeImage } = require('electron');
const path = require('path');

// ---------------------------------------------------------------------------
// 常量区（所有魔法数字集中于此，方便后续调整）
// ---------------------------------------------------------------------------

/** 窗口尺寸 */
const WINDOW_WIDTH = 1280;
const WINDOW_HEIGHT = 720;

/**
 * Live2D 模型地址（预留常量，Phase 4 暂未使用）
 * TODO(Phase 5): 后续指向本地 models/ 目录（如 file:// 相对路径）
 *                或远程 URL（如 https://example.com/models/model3.json）
 */
const MODEL_URL = ''; // 例如: path.join(__dirname, 'models', 'model3.json')

/** 渲染进程入口页面 */
const INDEX_HTML = path.join(__dirname, 'renderer', 'index.html');

// ---------------------------------------------------------------------------
// 窗口创建
// ---------------------------------------------------------------------------

/** 主窗口引用（防止被垃圾回收导致窗口关闭） */
let mainWindow = null;

/** 托盘引用（必须保持全局引用，否则托盘图标会被 GC 回收消失） */
let tray = null;

/**
 * 创建桌宠主窗口
 *  - transparent: 背景透明，配合 CSS 实现"无背景"桌宠
 *  - frame: false  去掉系统边框
 *  - alwaysOnTop  始终置顶（桌宠常态行为）
 *  - skipTaskbar  不在任务栏显示
 *  - resizable: false  固定尺寸，避免渲染层被拉伸错位
 */
function createWindow() {
  mainWindow = new BrowserWindow({
    width: WINDOW_WIDTH,
    height: WINDOW_HEIGHT,
    transparent: true,             // 窗口背景透明
    frame: false,                  // 无系统边框
    alwaysOnTop: true,             // 置顶显示
    skipTaskbar: true,             // 跳过任务栏
    resizable: false,              // 禁止用户调整尺寸
    hasShadow: false,              // 透明窗口不需要阴影
    webPreferences: {
      // 脚手架阶段简化：允许渲染进程直接 require 本地模块（pixi.js 等）
      // 警告：生产环境应改为 contextIsolation: true 并配合 preload 脚本
      contextIsolation: false,
      nodeIntegration: true,
      // 渲染进程文件加载自本地文件，无远程内容，devTools 按需开启
      devTools: true
    }
  });

  // 加载桌宠页面
  mainWindow.loadFile(INDEX_HTML);

  // 窗口关闭时置空引用（应用退出逻辑见 app.on('window-all-closed')）
  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// ---------------------------------------------------------------------------
// 托盘占位
// ---------------------------------------------------------------------------

/**
 * 创建系统托盘图标（占位实现）
 *  - 当前使用 nativeImage.createEmpty() 空图像，仅占住托盘位
 *  - 后续替换为真实图标文件（如 resources/tray.ico / tray.png）
 */
function createTray() {
  // 占位空图标：createEmpty 不会显示可见图标，但可保证托盘对象存在
  const emptyIcon = nativeImage.createEmpty();
  tray = new Tray(emptyIcon);
  // 占位标题
  tray.setToolTip('角色桌宠');
}

// ---------------------------------------------------------------------------
// 应用生命周期
// ---------------------------------------------------------------------------

app.whenReady().then(() => {
  createWindow();
  createTray(); // 托盘占位（图标为空，后续接入真实资源）

  // macOS 惯例：点击 Dock 图标且无窗口时重新创建窗口
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

// 除 macOS 外，所有窗口关闭即退出应用
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

// 进程退出前清理（预留：可在此断开 WebSocket、销毁 Live2D 资源等）
app.on('before-quit', () => {
  // TODO: 通知渲染进程优雅关闭 WebSocket 连接
});
