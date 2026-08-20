/* ===== 虚拟角色对话系统 V2 · 前端逻辑 =====
 * 对接 FastAPI 后端（api/main.py）
 * - POST /v1/chat          同步对话
 * - GET  /v1/memory/{char} 记忆列表
 * - DELETE /v1/memory/{char}/{id}
 * - GET  /v1/emotion/{char} 情感状态
 */
(function () {
  "use strict";

  const API_BASE = "";  // 同源部署时留空；跨域可填 http://127.0.0.1:8000

  const CHAR_NAMES = ["明日香", "雷姆", "早濑优香", "拉姆"];

  const el = {
    charSelect: document.getElementById("charSelect"),
    charInfo: document.getElementById("charInfo"),
    emotionState: document.getElementById("emotionState"),
    emotionBar: document.getElementById("emotionBar"),
    relState: document.getElementById("relState"),
    exprState: document.getElementById("exprState"),
    memList: document.getElementById("memList"),
    chatWindow: document.getElementById("chatWindow"),
    inputBox: document.getElementById("inputBox"),
    sendBtn: document.getElementById("sendBtn"),
    connState: document.getElementById("connState"),
  };

  let currentChar = CHAR_NAMES[0];
  let sending = false;
  let pollTimer = null;

  /* ---------- 初始化 ---------- */
  function init() {
    CHAR_NAMES.forEach((n) => {
      const opt = document.createElement("option");
      opt.value = n;
      opt.textContent = n;
      el.charSelect.appendChild(opt);
    });
    el.charSelect.value = currentChar;

    addMsg("system", `已连接后端。选择角色后即可开始对话。`);
    checkConn();
    refreshAll();

    el.charSelect.addEventListener("change", onCharChange);
    el.sendBtn.addEventListener("click", onSend);
    el.inputBox.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        onSend();
      }
    });

    // 每 5 秒刷新角色状态
    pollTimer = setInterval(refreshState, 5000);
  }

  /* ---------- 连接检测 ---------- */
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
      // 关系从记忆侧读取（若可用）
      try {
        const mr = await fetch(`${API_BASE}/v1/memory/${encodeURIComponent(currentChar)}`);
        if (mr.ok) {
          const md = await mr.json();
          if (md.relationship) {
            const rel = md.relationship;
            el.relState.textContent = `${rel.intimacy || "—"} (${rel.affinity ?? "?"}/${rel.trust ?? "?"}/${rel.familiarity ?? "?"})`;
          }
        }
      } catch { /* ignore */ }
    } catch { /* 后端未启动时静默 */ }
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

  /* ---------- 对话 ---------- */
  async function onSend() {
    const text = el.inputBox.value.trim();
    if (!text || sending) return;

    el.inputBox.value = "";
    autoGrow();
    addMsg("user", text);
    sending = true;
    el.sendBtn.disabled = true;

    // 先尝试 SSE 流式；失败则回退同步
    const ok = await streamChat(text);
    if (!ok) await syncChat(text);

    sending = false;
    el.sendBtn.disabled = false;
    refreshAll();
  }

  async function streamChat(text) {
    try {
      const r = await fetch(`${API_BASE}/v1/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ character: currentChar, text }),
      });
      if (!r.ok) return false;
      if (!r.body) return false;

      const aiMsg = addMsg("ai", "");
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
      return true;
    } catch {
      return false;
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
      addMsg("ai", d.response || "（空回复）");
      if (d.emotion) {
        el.emotionState.textContent = d.emotion;
      }
    } catch {
      addMsg("system", "无法连接后端，请先运行 python api/main.py");
    }
    scrollBottom();
  }

  /* ---------- 消息渲染 ---------- */
  function addMsg(role, content) {
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
    } else if (role === "user") {
      div.textContent = content;
    } else {
      div.textContent = content;
    }

    el.chatWindow.appendChild(div);
    scrollBottom();
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
