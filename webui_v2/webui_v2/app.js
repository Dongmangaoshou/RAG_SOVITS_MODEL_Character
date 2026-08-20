/* ===== 虚拟角色对话系统 V2 · 前端逻辑 =====
 * 对接 FastAPI 后端（api/main.py）
 * 功能：对话(SSE+回退) / 语音输入(Web Speech API) / TTS 播放 / 记忆管理
 *       用户画像 / 角色详情 / 情感状态 / 会话管理(清空/导出)
 */
(function () {
  "use strict";

  const API_BASE = "";  // 同源部署留空；跨域填 http://127.0.0.1:8000

  const CHAR_NAMES = ["明日香", "雷姆", "早濑优香", "拉姆"];
  const STORAGE_KEY = "v2_chat_history";

  const el = {
    charSelect: document.getElementById("charSelect"),
    charInfo: document.getElementById("charInfo"),
    charDetailBtn: document.getElementById("charDetailBtn"),
    emotionState: document.getElementById("emotionState"),
    emotionBar: document.getElementById("emotionBar"),
    relState: document.getElementById("relState"),
    exprState: document.getElementById("exprState"),
    emotionHint: document.getElementById("emotionHint"),
    resetEmoBtn: document.getElementById("resetEmoBtn"),
    memList: document.getElementById("memList"),
    clearMemBtn: document.getElementById("clearMemBtn"),
    profileList: document.getElementById("profileList"),
    clearChatBtn: document.getElementById("clearChatBtn"),
    exportBtn: document.getElementById("exportBtn"),
    chatWindow: document.getElementById("chatWindow"),
    inputBox: document.getElementById("inputBox"),
    sendBtn: document.getElementById("sendBtn"),
    voiceBtn: document.getElementById("voiceBtn"),
    voiceState: document.getElementById("voiceState"),
    ttsToggle: document.getElementById("ttsToggle"),
    connState: document.getElementById("connState"),
    charModal: document.getElementById("charModal"),
    modalTitle: document.getElementById("modalTitle"),
    modalBody: document.getElementById("modalBody"),
    modalClose: document.getElementById("modalClose"),
  };

  let currentChar = CHAR_NAMES[0];
  let sending = false;
  let pollTimer = null;
  let autoTTS = false;
  let audioEl = null;

  /* ---------- 初始化 ---------- */
  function init() {
    CHAR_NAMES.forEach((n) => {
      const opt = document.createElement("option");
      opt.value = n;
      opt.textContent = n;
      el.charSelect.appendChild(opt);
    });
    el.charSelect.value = currentChar;

    // 恢复 TTS 偏好
    autoTTS = localStorage.getItem("v2_auto_tts") === "1";
    el.ttsToggle.checked = autoTTS;

    addMsg("system", `已连接后端。选择角色后即可开始对话。`);
    loadLocalHistory();
    checkConn();
    refreshAll();

    el.charSelect.addEventListener("change", onCharChange);
    el.charDetailBtn.addEventListener("click", showCharDetail);
    el.resetEmoBtn.addEventListener("click", resetEmotion);
    el.clearMemBtn.addEventListener("click", clearMemory);
    el.clearChatBtn.addEventListener("click", clearChat);
    el.exportBtn.addEventListener("click", exportChat);
    el.modalClose.addEventListener("click", () => el.charModal.classList.add("hidden"));
    el.charModal.addEventListener("click", (e) => {
      if (e.target === el.charModal) el.charModal.classList.add("hidden");
    });
    el.ttsToggle.addEventListener("change", () => {
      autoTTS = el.ttsToggle.checked;
      localStorage.setItem("v2_auto_tts", autoTTS ? "1" : "0");
      if (autoTTS) checkTTS();
    });
    el.voiceBtn.addEventListener("click", toggleVoiceInput);
    el.sendBtn.addEventListener("click", onSend);
    el.inputBox.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        onSend();
      }
    });

    pollTimer = setInterval(refreshState, 5000);
  }

  /* ---------- 连接与 TTS 检测 ---------- */
  async function checkConn() {
    try {
      const r = await fetch(`${API_BASE}/v1/emotion/${encodeURIComponent(currentChar)}`);
      el.connState.textContent = r.ok ? "后端已连接" : "后端未就绪";
      el.connState.className = "conn-badge " + (r.ok ? "ok" : "bad");
      return r.ok;
    } catch {
      el.connState.textContent = "后端未连接";
      el.connState.className = "conn-badge bad";
      return false;
    }
  }

  async function checkTTS() {
    // 尝试 TTS 接口：返回 503 即服务未运行
    try {
      const r = await fetch(`${API_BASE}/v1/tts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ character: currentChar, text: "测" }),
      });
      if (r.ok) {
        el.voiceState.textContent = "TTS 可用";
        el.voiceState.style.color = "var(--green)";
      } else {
        el.voiceState.textContent = "TTS 未运行";
        el.voiceState.style.color = "";
      }
    } catch {
      el.voiceState.textContent = "TTS 未运行";
      el.voiceState.style.color = "";
    }
  }

  /* ---------- 角色切换 ---------- */
  function onCharChange() {
    currentChar = el.charSelect.value;
    el.charInfo.textContent = "";
    addMsg("system", `已切换到角色：${currentChar}`);
    refreshAll();
  }

  /* ---------- 刷新全部面板 ---------- */
  async function refreshAll() {
    await refreshState();
    await refreshMemory();
    await refreshProfile();
    loadCharInfo();
    if (autoTTS) checkTTS();
  }

  /* ---------- 角色信息（侧栏摘要） ---------- */
  async function loadCharInfo() {
    try {
      const r = await fetch(`${API_BASE}/v1/character/${encodeURIComponent(currentChar)}`);
      if (!r.ok) return;
      const d = await r.json();
      el.charInfo.textContent =
        `${d.source || ""}\n${(d.personality || "").slice(0, 60)}…`;
    } catch { /* ignore */ }
  }

  /* ---------- 角色状态 ---------- */
  async function refreshState() {
    try {
      const r = await fetch(`${API_BASE}/v1/emotion/${encodeURIComponent(currentChar)}`);
      if (!r.ok) return;
      const d = await r.json();
      const emo = d.emotion || "平静";
      const it = d.intensity || 0;
      el.emotionState.textContent = emo;
      el.emotionBar.style.width = `${Math.min(100, it * 100)}%`;
      el.exprState.textContent = d.expression || "—";
      el.emotionHint.textContent = d.hint || "";
      try {
        const mr = await fetch(`${API_BASE}/v1/memory/${encodeURIComponent(currentChar)}`);
        if (mr.ok) {
          const md = await mr.json();
          if (md.relationship) {
            const rel = md.relationship;
            el.relState.textContent =
              `${rel.intimacy || "—"} (${rel.affinity ?? "?"}/${rel.trust ?? "?"}/${rel.familiarity ?? "?"})`;
          }
        }
      } catch { /* ignore */ }
    } catch { /* ignore */ }
  }

  /* ---------- 记忆面板 ---------- */
  async function refreshMemory() {
    try {
      const r = await fetch(`${API_BASE}/v1/memory/${encodeURIComponent(currentChar)}`);
      if (!r.ok) { el.memList.innerHTML = '<div class="mem-empty">后端未就绪</div>'; return; }
      const d = await r.json();
      const events = d.events || [];
      if (!events.length) {
        el.memList.innerHTML = '<div class="mem-empty">暂无记忆，聊起来吧</div>';
        return;
      }
      el.memList.innerHTML = "";
      events.forEach((ev) => {
        const div = document.createElement("div");
        div.className = "mem-item";
        const tagMap = { fact: "事实", preference: "偏好", emotion: "情绪", promise: "承诺", chat: "闲聊" };
        div.innerHTML =
          `<span class="mem-tag">${tagMap[ev.event_type] || ev.event_type}</span>` +
          `<span>${escapeHtml(ev.text)}</span>` +
          `<button class="mem-del" title="删除这条记忆">&times;</button>`;
        div.querySelector(".mem-del").addEventListener("click", () => delMemory(ev.id, div));
        el.memList.appendChild(div);
      });
    } catch { el.memList.innerHTML = '<div class="mem-empty">后端未连接</div>'; }
  }

  async function delMemory(id, node) {
    try {
      const r = await fetch(`${API_BASE}/v1/memory/${encodeURIComponent(currentChar)}/${id}`, { method: "DELETE" });
      if (r.ok) node.remove();
      if (!el.memList.children.length) el.memList.innerHTML = '<div class="mem-empty">暂无记忆</div>';
    } catch { /* ignore */ }
  }

  async function clearMemory() {
    if (!confirm("确定清空该角色的全部记忆？此操作不可撤销。")) return;
    try {
      await fetch(`${API_BASE}/v1/memory/${encodeURIComponent(currentChar)}/all`, { method: "DELETE" });
      refreshMemory();
      refreshProfile();
    } catch { /* ignore */ }
  }

  /* ---------- 用户画像 ---------- */
  async function refreshProfile() {
    try {
      const r = await fetch(`${API_BASE}/v1/memory/${encodeURIComponent(currentChar)}/profile`);
      if (!r.ok) { el.profileList.textContent = "不可用"; return; }
      const d = await r.json();
      const p = d.profile || {};
      const keys = [
        ["preferences", "偏好"],
        ["avoid_topics", "回避话题"],
        ["personality_notes", "性格观察"],
        ["concerns", "关心事项"],
      ];
      let html = "";
      let has = false;
      keys.forEach(([k, label]) => {
        const items = p[k] || [];
        if (items.length) {
          has = true;
          html += `<div class="pl-item"><span class="pl-key">${label}:</span>${escapeHtml(items.join("、"))}</div>`;
        }
      });
      el.profileList.innerHTML = has ? html : '<div class="pl-item">暂无画像数据</div>';
    } catch { el.profileList.textContent = "不可用"; }
  }

  /* ---------- 重置情感 ---------- */
  async function resetEmotion() {
    try {
      const r = await fetch(`${API_BASE}/v1/emotion/${encodeURIComponent(currentChar)}/reset`, { method: "POST" });
      if (r.ok) {
        el.emotionState.textContent = "平静";
        el.emotionBar.style.width = "0%";
        addMsg("system", "已重置角色情感状态");
      }
    } catch { /* ignore */ }
  }

  /* ---------- 角色详情弹窗 ---------- */
  async function showCharDetail() {
    try {
      const r = await fetch(`${API_BASE}/v1/character/${encodeURIComponent(currentChar)}`);
      if (!r.ok) return;
      const d = await r.json();
      el.modalTitle.textContent = `${currentChar} · 角色详情`;
      let html = "";
      if (d.source) html += `<h4>作品来源</h4><p>${escapeHtml(d.source)}</p>`;
      if (d.personality) html += `<h4>性格</h4><p>${escapeHtml(d.personality)}</p>`;
      if (d.style) html += `<h4>说话风格</h4><p>${escapeHtml(d.style)}</p>`;
      if (d.backstory) html += `<h4>背景故事</h4><p>${escapeHtml(d.backstory)}</p>`;
      if (d.catchphrases && d.catchphrases.length) {
        html += `<h4>口头禅</h4>`;
        d.catchphrases.forEach((c) => { html += `<div class="quote">${escapeHtml(c)}</div>`; });
      }
      el.modalBody.innerHTML = html || "<p>暂无详情</p>";
      el.charModal.classList.remove("hidden");
    } catch { /* ignore */ }
  }

  /* ---------- 对话 ---------- */
  async function onSend() {
    const text = el.inputBox.value.trim();
    if (!text || sending) return;

    el.inputBox.value = "";
    autoGrow();
    addMsg("user", text);
    sending = true;
    el.sendBtn.disabled = true;

    // 先尝试 SSE 流式；仅当完全未收到内容时才回退同步
    const result = await streamChat(text);
    if (result === "none") await syncChat(text);

    sending = false;
    el.sendBtn.disabled = false;
    refreshAll();
  }

  async function streamChat(text) {
    let gotToken = false;
    let aiMsg = null;
    try {
      const r = await fetch(`${API_BASE}/v1/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ character: currentChar, text }),
      });
      if (!r.ok) return "none";
      if (!r.body) return "none";

      aiMsg = addMsg("ai", "");
      const ta = aiMsg.querySelector(".content");
      const reader = r.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith("data:")) continue;
          const payload = trimmed.slice(5).trim();
          try {
            const obj = JSON.parse(payload);
            if (obj.token) {
              gotToken = true;
              ta.textContent += obj.token;
              aiMsg.classList.add("typing");
              scrollBottom();
            }
            if (obj.error) {
              addMsg("system", `流式错误: ${obj.error}`);
            }
          } catch { /* 不完整帧 */ }
        }
      }
      aiMsg.classList.remove("typing");
      scrollBottom();
      if (gotToken && autoTTS) playTTS(ta.textContent);
      saveLocalHistory();
      return gotToken ? "ok" : "none";
    } catch (e) {
      if (gotToken) {
        aiMsg && aiMsg.classList.remove("typing");
        addMsg("system", "流式连接中断，已保留已生成内容");
        if (autoTTS) playTTS(aiMsg && aiMsg.querySelector(".content") ? aiMsg.querySelector(".content").textContent : "");
        return "partial";
      }
      return "none";
    }
  }

  async function syncChat(text) {
    try {
      const r = await fetch(`${API_BASE}/v1/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ character: currentChar, text }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        addMsg("system", `后端错误: ${err.error || r.status}`);
        return;
      }
      const d = await r.json();
      const aiMsg = addMsg("ai", d.response || "（空回复）");
      if (d.emotion) el.emotionState.textContent = d.emotion;
      if (autoTTS) playTTS(d.response || "");
      saveLocalHistory();
    } catch {
      addMsg("system", "无法连接后端，请先运行 python api/main.py");
    }
    scrollBottom();
  }

  /* ---------- TTS 语音播放 ---------- */
  async function playTTS(text) {
    if (!text) return;
    try {
      const r = await fetch(`${API_BASE}/v1/tts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ character: currentChar, text: text.slice(0, 200) }),
      });
      if (!r.ok) {
        el.voiceState.textContent = "TTS 未运行";
        return;
      }
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      if (!audioEl) audioEl = new Audio();
      audioEl.src = url;
      audioEl.play().catch(() => {});
      el.voiceState.textContent = "播放中…";
      audioEl.onended = () => { el.voiceState.textContent = ""; };
    } catch { /* ignore */ }
  }

  /* ---------- 语音输入（Web Speech API） ---------- */
  let recognition = null;
  let recording = false;

  function toggleVoiceInput() {
    if (recording) { stopVoice(); return; }
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      el.voiceState.textContent = "浏览器不支持语音输入";
      return;
    }
    if (!recognition) {
      recognition = new SR();
      recognition.lang = "zh-CN";
      recognition.continuous = false;
      recognition.interimResults = false;
      recognition.onresult = (e) => {
        const transcript = e.results[0][0].transcript;
        el.inputBox.value = (el.inputBox.value + transcript).trim();
        autoGrow();
        el.voiceState.textContent = "识别完成";
        stopVoice();
      };
      recognition.onerror = (e) => {
        el.voiceState.textContent = `识别错误: ${e.error}`;
        stopVoice();
      };
      recognition.onend = () => { stopVoice(); };
    }
    el.voiceBtn.classList.add("recording");
    el.voiceState.textContent = "聆听中…";
    recording = true;
    try { recognition.start(); } catch { /* ignore */ }
  }

  function stopVoice() {
    recording = false;
    el.voiceBtn.classList.remove("recording");
    if (recognition) { try { recognition.stop(); } catch { /* ignore */ } }
    if (!el.voiceState.textContent.startsWith("识别")) el.voiceState.textContent = "";
  }

  /* ---------- 会话管理 ---------- */
  function loadLocalHistory() {
    try {
      const data = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
      const last = data[data.length - 1];
      if (last && last.character === currentChar) {
        // 仅恢复同角色最近的对话（上限 20 条避免刷屏）
        const recent = data.filter((m) => m.character === currentChar).slice(-20);
        recent.forEach((m) => addMsg(m.role, m.content, true));
        addMsg("system", "已恢复本地历史");
      }
    } catch { /* ignore */ }
  }

  function saveLocalHistory() {
    try {
      const existing = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
      const msgs = [];
      el.chatWindow.querySelectorAll(".msg.user, .msg.ai").forEach((node) => {
        const role = node.classList.contains("user") ? "user" : "ai";
        const content = role === "ai"
          ? (node.querySelector(".content") || {}).textContent || ""
          : node.textContent || "";
        if (content) msgs.push({ role, content, character: currentChar });
      });
      localStorage.setItem(STORAGE_KEY, JSON.stringify(msgs));
    } catch { /* ignore */ }
  }

  function clearChat() {
    if (!confirm("确定清空当前对话窗口？")) return;
    el.chatWindow.innerHTML = "";
    addMsg("system", "对话已清空");
    localStorage.removeItem(STORAGE_KEY);
  }

  function exportChat() {
    const msgs = [];
    el.chatWindow.querySelectorAll(".msg.user, .msg.ai").forEach((node) => {
      const role = node.classList.contains("user") ? "用户" : currentChar;
      const content = role === currentChar
        ? (node.querySelector(".content") || {}).textContent || ""
        : node.textContent || "";
      if (content) msgs.push(`[${role}] ${content}`);
    });
    if (!msgs.length) { alert("暂无对话可导出"); return; }
    const blob = new Blob([msgs.join("\n\n")], { type: "text/plain;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `对话记录_${currentChar}_${new Date().toISOString().slice(0, 10)}.txt`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  /* ---------- 消息渲染 ---------- */
  function addMsg(role, content, noSave) {
    const div = document.createElement("div");
    div.className = `msg ${role}`;

    if (role === "ai") {
      const meta = document.createElement("span");
      meta.className = "msg-meta";
      meta.textContent = currentChar;
      const body = document.createElement("span");
      body.className = "content";
      body.textContent = content;
      div.appendChild(meta);
      div.appendChild(body);
    } else {
      div.textContent = content;
    }

    el.chatWindow.appendChild(div);
    scrollBottom();
    if (!noSave) saveLocalHistory();
    return div;
  }

  function scrollBottom() {
    el.chatWindow.scrollTop = el.chatWindow.scrollHeight;
  }

  function autoGrow() {
    el.inputBox.style.height = "auto";
    el.inputBox.style.height = Math.min(el.inputBox.scrollHeight, 120) + "px";
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  init();
})();
