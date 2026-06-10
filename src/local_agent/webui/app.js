/* Local Agent Web UI */

const API = "/api/v1";
const THEME_KEY = "local-agent-theme";

function getStoredTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  return saved === "light" || saved === "dark" ? saved : "dark";
}

function updateThemeToggleButton(theme) {
  const btn = document.getElementById("btn-theme");
  if (!btn) return;
  if (theme === "light") {
    btn.textContent = "🌙";
    btn.title = "切换到深色主题";
    btn.setAttribute("aria-label", "切换到深色主题");
  } else {
    btn.textContent = "☀️";
    btn.title = "切换到浅色主题";
    btn.setAttribute("aria-label", "切换到浅色主题");
  }
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem(THEME_KEY, theme);
  updateThemeToggleButton(theme);
}

function toggleTheme() {
  const current = document.documentElement.dataset.theme === "light" ? "light" : "dark";
  applyTheme(current === "light" ? "dark" : "light");
}

applyTheme(getStoredTheme());

const state = {
  agentId: null,
  threadId: null,
  threads: [],
  messages: [],
  hasMore: false,
  loadingOlder: false,
  streaming: false,
  artifacts: [],
  allSkills: [],
  skillDetail: null,
  skillDetailView: "markdown",
  artifactPanelCollapsed: true,
  pendingAttachments: [],
  sessionAgentDefaults: null,
};

// Per-thread stream state survives sidebar thread switches.
const streamSessions = new Map();

function createStreamSession(threadId, userMessage) {
  const session = {
    threadId,
    userMessage,
    segments: [],
    currentThinking: "",
    currentContent: "",
    waiting: true,
    active: true,
    stopping: false,
    abortController: null,
  };
  streamSessions.set(threadId, session);
  return session;
}

function getStreamSession(threadId) {
  return streamSessions.get(threadId);
}

function isThreadStreaming(threadId) {
  const session = streamSessions.get(threadId);
  return Boolean(session?.active);
}

function flushStreamSegments(session) {
  if (session.currentThinking) {
    session.segments.push({ type: "thinking", text: session.currentThinking });
    session.currentThinking = "";
    clearLiveStreamEl(session, "thinking");
  }
  if (session.currentContent) {
    session.segments.push({ type: "content", text: session.currentContent });
    session.currentContent = "";
    clearLiveStreamEl(session, "content");
  }
}

function resetStreamOverlayRefs(session) {
  if (!session) return;
  if (session._rafId) {
    cancelAnimationFrame(session._rafId);
    session._rafId = null;
  }
  session._renderPending = false;
  session.overlayEl = null;
  session.renderedSegmentCount = 0;
  session.liveThinkingEl = null;
  session.liveThinkingBodyEl = null;
  session.liveContentEl = null;
  session.liveContentBodyEl = null;
  session.toolEls = new Map();
  session.toolRenderState = new Map();
  session.userMsgEl = null;
}

function clearLiveStreamEl(session, type) {
  const elKey = type === "thinking" ? "liveThinkingEl" : "liveContentEl";
  const bodyKey = type === "thinking" ? "liveThinkingBodyEl" : "liveContentBodyEl";
  session[elKey]?.remove();
  session[elKey] = null;
  session[bodyKey] = null;
}

function scheduleStreamUIUpdate(threadId) {
  const session = getStreamSession(threadId);
  if (!session?.active || state.threadId !== threadId) return;
  if (session._renderPending) return;
  session._renderPending = true;
  session._rafId = requestAnimationFrame(() => {
    session._renderPending = false;
    session._rafId = null;
    updateStreamUI(session);
  });
}

function applyStreamEvent(session, event, parsed) {
  switch (event) {
    case "thinking":
      session.waiting = false;
      session.currentThinking += parsed.text || "";
      break;
    case "content":
      session.waiting = false;
      session.currentContent += parsed.text || "";
      break;
    case "tool_start":
      session.waiting = false;
      flushStreamSegments(session);
      session.segments.push({
        type: "tool",
        name: parsed.name,
        args: parsed.arguments || "{}",
        result: "",
        done: false,
      });
      break;
    case "tool_end": {
      const tool = [...session.segments]
        .reverse()
        .find((seg) => seg.type === "tool" && seg.name === parsed.name && !seg.done);
      if (tool) {
        tool.result = parsed.result || "";
        tool.done = true;
      }
      break;
    }
    case "done":
      session.waiting = false;
      if (parsed.content) {
        session.currentContent = parsed.content;
      }
      flushStreamSegments(session);
      session.active = false;
      break;
    case "cancelled":
      session.waiting = false;
      flushStreamSegments(session);
      session.segments.push({ type: "cancelled", text: "任务已停止" });
      session.active = false;
      restoreDraftOnStop(session);
      break;
    default:
      break;
  }
}

function endStreamSession(threadId) {
  const session = streamSessions.get(threadId);
  if (session) {
    session.overlayEl?.remove();
    resetStreamOverlayRefs(session);
  }
  streamSessions.delete(threadId);
  updateComposerForCurrentThread();
}

function updateComposerForCurrentThread() {
  setComposerBusy(isThreadStreaming(state.threadId));
}

function migrateStreamSession(oldThreadId, newThreadId) {
  if (!oldThreadId || oldThreadId === newThreadId) return newThreadId;
  const session = streamSessions.get(oldThreadId);
  if (!session) return newThreadId;
  streamSessions.delete(oldThreadId);
  session.threadId = newThreadId;
  streamSessions.set(newThreadId, session);
  return newThreadId;
}

// ── API helpers ──────────────────────────────────────────────

async function api(path, options = {}) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  if (res.status === 204) return null;
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || res.statusText || "请求失败");
  }
  return res.json();
}

async function apiUpload(path, formData) {
  const res = await fetch(API + path, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || res.statusText || "上传失败");
  }
  return res.json();
}

// ── Agent bootstrap ──────────────────────────────────────────

async function ensureAgent() {
  let agent = null;
  try {
    agent = await api("/agents/default");
  } catch {
    agent = null;
  }
  if (!agent) {
    agent = await api("/agents", {
      method: "POST",
      body: JSON.stringify({ name: "默认助手" }),
    });
  }
  state.agentId = agent.id;
}

// ── Threads ──────────────────────────────────────────────────

async function loadThreads() {
  await ensureAgent();
  state.threads = await api("/threads");
  renderThreadList();
}

function formatLocalDatetime(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("zh-CN", { hour12: false });
  } catch {
    return iso;
  }
}

function formatArtifactSummary(count, names) {
  if (!count) return "";
  if (!names?.length) return `${count} 个文件`;
  let label = names.join("、");
  if (count > names.length) label += ` 等 ${count} 个`;
  return label;
}

function renderThreadList() {
  const el = document.getElementById("thread-list");
  if (!state.threads.length) {
    el.innerHTML = '<div class="empty-state">暂无会话</div>';
    return;
  }
  el.innerHTML = state.threads
    .map(
      (t, i) => `
    <div class="thread-item ${t.id === state.threadId ? "active" : ""}" data-id="${t.id}" data-agent-id="${t.agent_id}">
      <button class="thread-delete" data-delete="${t.id}" title="删除会话">&times;</button>
      <div class="thread-title"><span class="thread-index">#${i + 1}</span> ${esc(t.title || "未命名会话")}</div>
      ${t.agent_name ? `<div class="thread-agent">${esc(t.agent_name)}</div>` : ""}
      <div class="thread-preview">${esc(t.preview || "（暂无对话）")}</div>
      <div class="thread-meta">
        <span>${t.turn_count || 0} 轮</span>
        <span>${formatLocalDatetime(t.last_active || t.updated_at)}</span>
        ${t.artifact_count ? `<span>文件: ${esc(formatArtifactSummary(t.artifact_count, t.artifact_names))}</span>` : ""}
      </div>
    </div>`
    )
    .join("");
}

async function selectThread(threadId) {
  const thread = state.threads.find((t) => t.id === threadId);
  state.threadId = threadId;
  clearPendingAttachments();
  if (thread?.agent_id) {
    state.agentId = thread.agent_id;
  }
  state.messages = [];
  state.hasMore = false;
  renderThreadList();
  document.getElementById("chat-empty")?.remove();
  await loadMessages();
  await loadArtifacts();
  await syncSessionJobsForPolling();
  updateComposerForCurrentThread();
  if (!document.getElementById("settings-modal").classList.contains("hidden")) {
    const activeTab = document.querySelector(".tabs .tab.active")?.dataset.tab;
    if (activeTab === "session-config") {
      await loadSessionConfigForm();
    } else if (activeTab === "scheduler-jobs") {
      await loadSessionJobs();
    }
  }
}

async function createThread() {
  const thread = await api(`/agents/${state.agentId}/threads`, {
    method: "POST",
    body: JSON.stringify({ title: "新会话" }),
  });
  await loadThreads();
  selectThread(thread.id);
}

async function deleteThread(threadId) {
  if (!confirm("确定删除此会话？关联的会话文件也将被删除。")) return;
  await api(`/threads/${threadId}`, { method: "DELETE" });
  endStreamSession(threadId);
  if (state.threadId === threadId) {
    state.threadId = null;
    state.messages = [];
    document.getElementById("messages").innerHTML =
      '<div class="empty-state" id="chat-empty">选择或创建一个会话开始对话</div>';
    document.getElementById("artifact-list").innerHTML =
      '<div class="empty-state">暂无会话文件</div>';
    setArtifactPanelCollapsed(true);
    closeArtifactModal();
  }
  await loadThreads();
}

// ── Messages (scroll-up pagination) ──────────────────────────

const MESSAGE_PAGE_SIZE = 50;
const SCROLL_STICK_THRESHOLD = 80;

function isNearBottom(container, threshold = SCROLL_STICK_THRESHOLD) {
  if (!container) return true;
  return container.scrollHeight - container.scrollTop - container.clientHeight < threshold;
}

function scrollMessagesContainer(container, { force = false } = {}) {
  if (!container) return;
  if (force || isNearBottom(container)) {
    container.scrollTop = container.scrollHeight;
  }
}

function messageAnchorId(msg) {
  const id = msg?.id;
  if (!id || String(id).startsWith("temp-")) return null;
  return id;
}

function mergeOlderMessages(existing, incoming) {
  const seen = new Set(existing.map((m) => m.id).filter(Boolean));
  const fresh = incoming.filter((m) => m.id && !seen.has(m.id));
  return [...fresh, ...existing];
}

async function loadMessages(older = false) {
  if (!state.threadId) return;
  if (older && (!state.hasMore || state.loadingOlder)) return;

  state.loadingOlder = true;
  const container = document.getElementById("messages");
  const prevHeight = container.scrollHeight;
  const prevTop = container.scrollTop;

  const params = new URLSearchParams({ limit: String(MESSAGE_PAGE_SIZE) });
  if (older) {
    const anchorId = state.messages.map(messageAnchorId).find(Boolean);
    if (!anchorId) {
      state.loadingOlder = false;
      return;
    }
    params.set("before_id", anchorId);
  }

  try {
    const page = await api(`/threads/${state.threadId}/messages?${params}`);
    state.hasMore = page.has_more;

    if (older) {
      const merged = mergeOlderMessages(state.messages, page.messages);
      if (merged.length === state.messages.length && page.has_more) {
        // Cursor advanced but nothing new merged — retry once with the page anchor.
        const fallbackId = messageAnchorId(page.messages[0]);
        if (fallbackId && fallbackId !== params.get("before_id")) {
          params.set("before_id", fallbackId);
          const retry = await api(`/threads/${state.threadId}/messages?${params}`);
          state.hasMore = retry.has_more;
          state.messages = mergeOlderMessages(state.messages, retry.messages);
        }
      } else {
        state.messages = merged;
      }
    } else {
      state.messages = page.messages;
    }

    renderMessages();

    if (older) {
      container.scrollTop = container.scrollHeight - prevHeight + prevTop;
      // Near top with more history — keep loading until content fills the viewport.
      if (state.hasMore && container.scrollTop < 120) {
        state.loadingOlder = false;
        await loadMessages(true);
        return;
      }
    } else {
      container.scrollTop = container.scrollHeight;
    }
  } finally {
    state.loadingOlder = false;
  }
}

function renderMessages() {
  const container = document.getElementById("messages");
  const parts = [];

  if (state.hasMore) {
    parts.push(
      '<button type="button" class="load-more" id="load-more-hint">↑ 加载更早消息</button>'
    );
  }

  for (const msg of state.messages) {
    parts.push(renderMessage(msg));
  }

  container.innerHTML = parts.join("") || '<div class="empty-state">开始对话吧</div>';
  renderStreamOverlayFromSession(getStreamSession(state.threadId));
}

function renderStreamSegmentHtml(seg, { streaming = false, expandDetails = false } = {}) {
  const detailsOpen = streaming || expandDetails;
  if (seg.type === "thinking") {
    return `<div class="msg assistant thinking-block${streaming ? " streaming" : ""}">
      <div class="msg-role">${streaming ? "思考中" : "助手"}</div>
      <div class="msg-body">${renderThinking(seg.text, { open: detailsOpen })}</div>
    </div>`;
  }
  if (seg.type === "content") {
    let body = "";
    try {
      body = marked.parse(seg.text);
    } catch {
      body = esc(seg.text);
    }
    const cursorClass = streaming ? " streaming-cursor" : "";
    return `<div class="msg assistant${streaming ? " streaming" : ""}">
      <div class="msg-role">助手</div>
      <div class="msg-body${cursorClass}">${body}</div>
    </div>`;
  }
  if (seg.type === "cancelled") {
    return `<div class="msg assistant cancelled-notice">
      <div class="msg-body">${esc(seg.text || "任务已停止")}</div>
    </div>`;
  }
  if (seg.type === "tool") {
    let argsText = seg.args || "{}";
    try {
      argsText = JSON.stringify(JSON.parse(argsText), null, 2);
    } catch {
      /* keep raw */
    }
    const text = seg.done ? (seg.result || "") : argsText;
    const status = seg.done ? "完成" : "执行中…";
    const streamingClass = seg.done ? "" : " streaming-tool";
    return `<div class="msg tool${streamingClass}" data-tool-name="${esc(seg.name)}">
      <div class="msg-role">工具 · ${esc(seg.name)}</div>
      <div class="msg-body">${renderToolMessage(text, status, { open: detailsOpen })}</div>
    </div>`;
  }
  return "";
}

function getOrCreateStreamOverlay(session) {
  const container = document.getElementById("messages");
  if (session.overlayEl && !session.overlayEl.isConnected) {
    resetStreamOverlayRefs(session);
  }
  if (!session.overlayEl) {
    session.overlayEl = document.createElement("div");
    session.overlayEl.className = "stream-overlay";
    container.appendChild(session.overlayEl);
    session.renderedSegmentCount = 0;
    session.toolEls = new Map();
    session.toolRenderState = new Map();
  }
  return session.overlayEl;
}

function appendStreamSegmentToOverlay(overlay, session, seg, index) {
  if (seg.type === "tool") {
    const wrap = document.createElement("div");
    wrap.innerHTML = renderStreamSegmentHtml(seg, { expandDetails: true });
    const el = wrap.firstElementChild;
    overlay.appendChild(el);
    session.toolEls.set(index, el);
    return;
  }
  overlay.insertAdjacentHTML("beforeend", renderStreamSegmentHtml(seg, { expandDetails: true }));
}

function updateToolSegmentDOM(session, seg, index) {
  const el = session.toolEls.get(index);
  if (!el) return;
  const stateKey = `${seg.done}|${seg.result || ""}|${seg.args || ""}`;
  if (session.toolRenderState.get(index) === stateKey) return;
  session.toolRenderState.set(index, stateKey);
  const bodyEl = el.querySelector(".msg-body");
  if (!bodyEl) return;
  const text = seg.done ? (seg.result || "") : (seg.args || "{}");
  const status = seg.done ? "完成" : "执行中…";
  bodyEl.innerHTML = renderToolMessage(text, status, { open: true });
  el.classList.toggle("streaming-tool", !seg.done);
}

function updateLiveThinking(overlay, session, text) {
  if (!text) {
    clearLiveStreamEl(session, "thinking");
    return;
  }
  if (!session.liveThinkingEl) {
    const el = document.createElement("div");
    el.className = "msg assistant thinking-block streaming";
    el.innerHTML =
      '<div class="msg-role">思考中</div><div class="msg-body"><details class="thinking-collapsible" open><summary>思考过程</summary><div class="thinking-content"></div></details></div>';
    overlay.appendChild(el);
    session.liveThinkingEl = el;
    session.liveThinkingBodyEl = el.querySelector(".thinking-content");
  }
  session.liveThinkingBodyEl.textContent = text;
}

function updateLiveContent(overlay, session, text) {
  if (!text) {
    clearLiveStreamEl(session, "content");
    return;
  }
  if (!session.liveContentEl) {
    const el = document.createElement("div");
    el.className = "msg assistant streaming";
    el.innerHTML = '<div class="msg-role">助手</div><div class="msg-body streaming-cursor stream-plaintext"></div>';
    overlay.appendChild(el);
    session.liveContentEl = el;
    session.liveContentBodyEl = el.querySelector(".msg-body");
  }
  session.liveContentBodyEl.textContent = text;
}

function updateStreamUI(session) {
  if (!session?.active || state.threadId !== session.threadId) return;
  const container = document.getElementById("messages");
  const stickToBottom = isNearBottom(container);

  if (session.userMessage) {
    const alreadyShown = state.messages.some(
      (m) =>
        m.role === "user" &&
        (m.id === session.userMessage.id || m.content === session.userMessage.content)
    );
    if (!alreadyShown && !session.userMsgEl) {
      container.insertAdjacentHTML("beforeend", renderMessage(session.userMessage));
      session.userMsgEl = container.lastElementChild;
    }
  }

  const overlay = getOrCreateStreamOverlay(session);

  if (
    session.waiting &&
    !session.segments.length &&
    !session.currentThinking &&
    !session.currentContent
  ) {
    if (!overlay.querySelector(".streaming-waiting")) {
      overlay.innerHTML = `<div class="msg assistant streaming streaming-waiting">
        <div class="msg-role">助手</div>
        <div class="msg-body"><span class="working-dots">正在思考</span></div>
      </div>`;
    }
    scrollMessagesContainer(container, { force: stickToBottom });
    return;
  }

  overlay.querySelector(".streaming-waiting")?.remove();

  while (session.renderedSegmentCount < session.segments.length) {
    const index = session.renderedSegmentCount;
    appendStreamSegmentToOverlay(overlay, session, session.segments[index], index);
    session.renderedSegmentCount += 1;
  }

  for (let i = 0; i < session.segments.length; i += 1) {
    const seg = session.segments[i];
    if (seg.type === "tool" && session.toolEls.has(i)) {
      updateToolSegmentDOM(session, seg, i);
    }
  }

  updateLiveThinking(overlay, session, session.currentThinking);
  updateLiveContent(overlay, session, session.currentContent);
  scrollMessagesContainer(container, { force: stickToBottom });
}

function renderStreamOverlayFromSession(session) {
  if (!session?.active) return;
  resetStreamOverlayRefs(session);
  updateStreamUI(session);
}

function renderToolCalls(toolCalls) {
  if (!toolCalls?.length) return "";
  const items = toolCalls
    .map((tc) => {
      const fn = tc.function || {};
      const name = fn.name || tc.name || "unknown";
      let args = fn.arguments || "{}";
      try {
        args = JSON.stringify(JSON.parse(args), null, 2);
      } catch {
        /* keep raw */
      }
      return `<details class="tool-call-collapsible"><summary>🔧 ${esc(name)}</summary><pre>${esc(args)}</pre></details>`;
    })
    .join("");
  return `<div class="tool-calls">${items}</div>`;
}

function renderToolMessage(content, status, { open = false } = {}) {
  const text = (content || "").slice(0, 3000);
  const summaryLabel = status === "执行中…" ? "参数" : "结果";
  const statusHtml = status
    ? `<div class="tool-call-status">${esc(status)}</div>`
    : "";
  const openAttr = open ? " open" : "";
  return `<details class="tool-call-collapsible"${openAttr}>
    <summary>${esc(summaryLabel)}</summary>
    ${statusHtml}
    <pre>${esc(text)}</pre>
  </details>`;
}

function renderThinking(thinking, { open = false } = {}) {
  if (!thinking && !open) return "";
  const openAttr = open ? " open" : "";
  return `<details class="thinking-collapsible"${openAttr}>
    <summary>思考过程</summary>
    <div class="thinking-content">${esc(thinking)}</div>
  </details>`;
}

function renderMessage(msg) {
  const role = msg.role;
  const roleLabel = { user: "你", assistant: "助手", tool: `工具 · ${msg.name || ""}` }[role] || role;
  let body = "";

  if (role === "assistant") {
    if (msg.thinking) {
      body += renderThinking(msg.thinking);
    }
    if (msg.content) {
      body += marked.parse(msg.content);
    }
    body += renderToolCalls(msg.tool_calls);
  } else if (role === "tool") {
    body = renderToolMessage(msg.content);
  } else {
    body = esc(msg.content || "");
    if (msg.attachments?.length) {
      const chips = msg.attachments
        .map(
          (a) =>
            `<span class="msg-attachment-chip" data-artifact-id="${esc(a.id || "")}" title="${esc(a.name || "")}">📎 ${esc(a.name || "附件")}</span>`
        )
        .join("");
      body = `${body}${body ? "<br>" : ""}<div class="msg-attachments">${chips}</div>`;
    }
  }

  return `<div class="msg ${role}" data-id="${msg.id || ""}">
    <div class="msg-role">${roleLabel}</div>
    <div class="msg-body">${body || '<span class="text-muted">（无内容）</span>'}</div>
  </div>`;
}

function refreshThreadViewIfActive(threadId) {
  if (state.threadId !== threadId) return;
  const session = getStreamSession(threadId);
  if (session?.active) {
    scheduleStreamUIUpdate(threadId);
    return;
  }
  const container = document.getElementById("messages");
  const prevScrollTop = container.scrollTop;
  const stickToBottom = isNearBottom(container);
  renderMessages();
  if (stickToBottom) {
    container.scrollTop = container.scrollHeight;
  } else {
    container.scrollTop = prevScrollTop;
  }
}

function setComposerBusy(busy) {
  state.streaming = busy;
  const composer = document.querySelector(".composer");
  const input = document.getElementById("input");
  const btn = document.getElementById("btn-send");
  const attachBtn = document.getElementById("btn-attach");
  const session = getStreamSession(state.threadId);
  const stopping = Boolean(session?.stopping);
  composer?.classList.toggle("busy", busy);
  input.disabled = busy;
  if (attachBtn) attachBtn.disabled = busy;
  btn.disabled = false;
  btn.classList.toggle("working", busy && !stopping);
  btn.classList.toggle("stop-mode", busy);
  btn.classList.toggle("btn-primary", !busy);
  if (!busy) btn.classList.remove("stop-mode");
  btn.title = busy ? "停止当前任务" : "";
  btn.textContent = busy ? (stopping ? "停止中…" : "停止") : "发送";
  if (busy) hideMentionPicker();
}

function restoreDraftOnStop(session) {
  const input = document.getElementById("input");
  const draft = session?.userMessage?.content;
  if (input && typeof draft === "string" && draft.trim()) {
    input.value = draft;
  }
}

async function stopCurrentTask() {
  const threadId = state.threadId;
  const session = getStreamSession(threadId);
  if (!session?.active || session.stopping) return;

  session.stopping = true;
  restoreDraftOnStop(session);
  updateComposerForCurrentThread();

  try {
    await api(`/threads/${threadId}/chat/cancel`, { method: "POST" });
  } catch {
    // Fallback: client abort still closes the SSE connection.
  }
  session.abortController?.abort();
}

function clearPendingAttachments() {
  state.pendingAttachments = [];
  renderAttachmentChips();
  hideMentionPicker();
}

function renderAttachmentChips() {
  const container = document.getElementById("attachment-chips");
  if (!container) return;
  if (!state.pendingAttachments.length) {
    container.hidden = true;
    container.innerHTML = "";
    return;
  }
  container.hidden = false;
  container.innerHTML = state.pendingAttachments
    .map(
      (item) => `<span class="attachment-chip" data-id="${esc(item.id)}">
        <span class="attachment-chip-name" title="${esc(item.name)}">📎 ${esc(item.name)}</span>
        <button type="button" data-remove-attachment="${esc(item.id)}" title="移除">×</button>
      </span>`
    )
    .join("");
}

function extractFilesFromClipboard(clipboardData) {
  if (!clipboardData) return [];

  const files = [];
  for (const item of clipboardData.items || []) {
    if (item.kind === "file") {
      const file = item.getAsFile();
      if (file) files.push(file);
    }
  }
  if (!files.length && clipboardData.files?.length) {
    files.push(...clipboardData.files);
  }
  return files;
}

function normalizePastedFile(file) {
  if (file.name && !/^image\.(png|jpe?g|gif|webp)$/i.test(file.name)) return file;
  const rawExt = file.type?.split("/")[1] || "png";
  const ext = rawExt === "jpeg" ? "jpg" : rawExt;
  return new File([file], `paste-${Date.now()}.${ext}`, { type: file.type || `image/${ext}` });
}

function handleComposerPaste(e) {
  const files = extractFilesFromClipboard(e.clipboardData).map(normalizePastedFile);
  if (!files.length) return;
  e.preventDefault();
  uploadFiles(files);
}

async function uploadFiles(fileList) {
  if (!fileList?.length) return;
  if (isThreadStreaming(state.threadId)) return;

  try {
    if (!state.agentId) await ensureAgent();
    if (!state.threadId) await createThread();

    for (const file of fileList) {
      const form = new FormData();
      form.append("file", file);
      const artifact = await apiUpload(`/threads/${state.threadId}/uploads`, form);
      state.pendingAttachments.push(artifact);
    }
    renderAttachmentChips();
    toast(`已添加 ${fileList.length} 个附件`);
  } catch (e) {
    toast(e.message || "上传失败", true);
  }
}

function renderMessageAttachments(attachments) {
  if (!attachments?.length) return "";
  const tags = attachments
    .map((item) => `<span class="msg-attachment-tag">📎 ${esc(item.name)}</span>`)
    .join("");
  return `<div class="msg-attachments">${tags}</div>`;
}

// ── @ mention (session files) ────────────────────────────────

function artifactDisplayName(filename) {
  const m = String(filename).match(/^[a-f0-9]{8}_(.+)$/i);
  return m ? m[1] : filename;
}

function resolveReferenceIds(text) {
  const ids = new Set();
  const pattern = /@([^\s@]+)/g;
  let match;
  while ((match = pattern.exec(text)) !== null) {
    const token = match[1].toLowerCase();
    for (const artifact of state.artifacts) {
      const name = artifact.name.toLowerCase();
      const display = artifactDisplayName(artifact.name).toLowerCase();
      if (token === name || token === display) {
        ids.add(artifact.id);
        break;
      }
    }
  }
  return [...ids];
}

const mentionState = {
  active: false,
  start: 0,
  query: "",
  selectedIndex: 0,
  candidates: [],
};

function hideMentionPicker() {
  mentionState.active = false;
  mentionState.candidates = [];
  mentionState.selectedIndex = 0;
  const picker = document.getElementById("mention-picker");
  if (picker) {
    picker.classList.add("hidden");
    picker.innerHTML = "";
  }
}

function getMentionContext(input) {
  const cursor = input.selectionStart ?? 0;
  const text = input.value.slice(0, cursor);
  const match = text.match(/(?:^|[\s\n])@([^\s@]*)$/);
  if (!match) return null;
  const query = match[1];
  const atIndex = text.length - query.length - 1;
  return { start: atIndex, query };
}

function getMentionCandidates(query) {
  const q = query.toLowerCase();
  const items = [];
  for (const artifact of state.artifacts) {
    if (!artifact?.id) continue;
    if (!q || artifact.name.toLowerCase().includes(q) ||
        artifactDisplayName(artifact.name).toLowerCase().includes(q)) {
      items.push(artifact);
    }
  }
  return items.slice(0, 30);
}

function renderMentionPicker(candidates) {
  const picker = document.getElementById("mention-picker");
  if (!picker) return;

  if (!candidates.length) {
    picker.innerHTML =
      '<div class="mention-picker-empty">暂无匹配的会话文件</div>';
    picker.classList.remove("hidden");
    return;
  }

  picker.innerHTML = candidates
    .map((item, index) => {
      const active = index === mentionState.selectedIndex ? " active" : "";
      const meta = `${formatSize(item.size_bytes)} · ${formatPreviewKind(item.preview_kind)}`;
      const label = artifactDisplayName(item.name);
      return `<div class="mention-item${active}" role="option" data-mention-id="${esc(item.id)}" data-index="${index}">
        <span class="mention-item-name">@${esc(label)}</span>
        <span class="mention-item-meta">${esc(meta)}</span>
      </div>`;
    })
    .join("");
  picker.classList.remove("hidden");

  const activeEl = picker.querySelector(".mention-item.active");
  activeEl?.scrollIntoView({ block: "nearest" });
}

function updateMentionPickerFromInput() {
  const input = document.getElementById("input");
  if (!input || input.disabled) {
    hideMentionPicker();
    return;
  }

  const ctx = getMentionContext(input);
  if (!ctx) {
    hideMentionPicker();
    return;
  }

  const prevQuery = mentionState.query;
  mentionState.active = true;
  mentionState.start = ctx.start;
  mentionState.query = ctx.query;
  const candidates = getMentionCandidates(ctx.query);
  if (prevQuery !== ctx.query) {
    mentionState.selectedIndex = 0;
  } else if (mentionState.selectedIndex >= candidates.length) {
    mentionState.selectedIndex = Math.max(0, candidates.length - 1);
  }
  mentionState.candidates = candidates;
  renderMentionPicker(candidates);
}

function selectMentionByIndex(index) {
  const artifact = mentionState.candidates[index];
  if (!artifact) return;

  const input = document.getElementById("input");
  if (!input) return;

  const cursor = input.selectionStart ?? input.value.length;
  const before = input.value.slice(0, mentionState.start);
  const after = input.value.slice(cursor);
  const insert = `@${artifactDisplayName(artifact.name)} `;
  input.value = before + insert + after;
  const pos = before.length + insert.length;
  input.setSelectionRange(pos, pos);

  hideMentionPicker();
  input.focus();
}

function handleMentionKeydown(e) {
  if (!mentionState.active) return false;

  if (e.key === "Backspace") {
    hideMentionPicker();
    return false;
  }

  if (e.key === "Escape") {
    e.preventDefault();
    hideMentionPicker();
    return true;
  }

  if (!mentionState.candidates.length) return false;

  if (e.key === "ArrowDown") {
    e.preventDefault();
    mentionState.selectedIndex =
      (mentionState.selectedIndex + 1) % mentionState.candidates.length;
    renderMentionPicker(mentionState.candidates);
    return true;
  }

  if (e.key === "ArrowUp") {
    e.preventDefault();
    mentionState.selectedIndex =
      (mentionState.selectedIndex - 1 + mentionState.candidates.length) %
      mentionState.candidates.length;
    renderMentionPicker(mentionState.candidates);
    return true;
  }

  if (e.key === "Enter" || e.key === "Tab") {
    e.preventDefault();
    selectMentionByIndex(mentionState.selectedIndex);
    return true;
  }

  return false;
}



// ── Chat / SSE ───────────────────────────────────────────────

async function sendMessage() {
  const input = document.getElementById("input");
  const text = input.value.trim();
  const attachments = [...state.pendingAttachments];
  const referenceIds = resolveReferenceIds(text);
  if ((!text && !attachments.length && !referenceIds.length) ||
      isThreadStreaming(state.threadId)) return;

  let streamThreadId = null;

  try {
    if (!state.threadId) {
      await createThread();
    }

    const thread = state.threads.find((t) => t.id === state.threadId);
    if (thread?.agent_id) {
      state.agentId = thread.agent_id;
    }
    if (!state.agentId) {
      await ensureAgent();
    }
    const agentIdForChat = thread?.agent_id || state.agentId;

    input.value = "";
    hideMentionPicker();
    state.pendingAttachments = [];
    renderAttachmentChips();

    const userMessage = {
      role: "user",
      content: text,
      attachments: attachments.map((a) => ({ id: a.id, name: a.name })),
      id: "temp-" + Date.now(),
    };
    streamThreadId = state.threadId;
    const session = createStreamSession(streamThreadId, userMessage);
    session.abortController = new AbortController();
    updateComposerForCurrentThread();

    state.messages.push(userMessage);
    renderMessages();
    scrollMessagesContainer(document.getElementById("messages"), { force: true });

    let responseDone = false;

    const res = await fetch(`${API}/agents/${agentIdForChat}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: session.abortController?.signal,
      body: JSON.stringify({
        message: text,
        thread_id: streamThreadId,
        stream: true,
        attachment_ids: attachments.map((a) => a.id),
        reference_ids: referenceIds,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || res.statusText || "请求失败");
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop();

      for (const chunk of chunks) {
        const lines = chunk.split("\n");
        let event = "message";
        let data = "";
        for (const line of lines) {
          if (line.startsWith("event: ")) event = line.slice(7).trim();
          if (line.startsWith("data: ")) data = line.slice(6);
        }
        if (!data) continue;
        const parsed = JSON.parse(data);

        if (event === "meta" && parsed.thread_id) {
          streamThreadId = migrateStreamSession(streamThreadId, parsed.thread_id);
        } else if (event === "thread_title" && parsed.title) {
          const t = state.threads.find((x) => x.id === streamThreadId);
          if (t) t.title = parsed.title;
          renderThreadList();
        } else if (event === "error") {
          toast(parsed.message || "对话出错", true);
          session.active = false;
        } else if (event === "cancelled") {
          applyStreamEvent(session, event, parsed);
          refreshThreadViewIfActive(streamThreadId);
        } else if (session) {
          applyStreamEvent(session, event, parsed);
          if (event === "done") {
            responseDone = true;
          }
          refreshThreadViewIfActive(streamThreadId);
        }
      }
    }

    if (!responseDone && session.active) {
      session.active = false;
      flushStreamSegments(session);
    }

    endStreamSession(streamThreadId);
    await loadThreads();
    if (state.threadId === streamThreadId) {
      await Promise.all([loadMessages(), loadArtifacts(), syncSessionJobsForPolling()]);
    }
  } catch (e) {
    const session = streamThreadId ? getStreamSession(streamThreadId) : null;
    const userStopped = e.name === "AbortError" || session?.stopping;
    if (userStopped) {
      if (session) {
        if (!session.segments.some((s) => s.type === "cancelled")) {
          session.segments.push({ type: "cancelled", text: "任务已停止" });
        }
        session.active = false;
        flushStreamSegments(session);
        refreshThreadViewIfActive(streamThreadId);
      }
      if (streamThreadId) {
        endStreamSession(streamThreadId);
        try {
          await loadMessages();
        } catch {
          /* ignore reload errors after stop */
        }
      }
    } else {
      toast(e.message, true);
      if (streamThreadId) {
        endStreamSession(streamThreadId);
        refreshThreadViewIfActive(streamThreadId);
      }
    }
  } finally {
    updateComposerForCurrentThread();
  }
}

// ── Artifacts ────────────────────────────────────────────────

async function loadArtifacts() {
  if (!state.threadId) return;
  state.artifacts = await api(`/threads/${state.threadId}/artifacts`);
  renderArtifactList();
}

function setArtifactPanelCollapsed(collapsed) {
  state.artifactPanelCollapsed = collapsed;
  const panel = document.getElementById("artifact-panel");
  const btn = document.getElementById("btn-artifact-toggle");
  const app = document.querySelector(".app");
  if (!panel || !btn || !app) return;
  panel.classList.toggle("collapsed", collapsed);
  app.classList.toggle("artifact-collapsed", collapsed);
  btn.textContent = collapsed ? "▶" : "◀";
  btn.title = collapsed ? "展开会话文件区" : "收起会话文件区";
}

function renderArtifactList() {
  const el = document.getElementById("artifact-list");
  document.getElementById("artifact-panel")?.classList.remove("hidden-panel");
  if (!state.artifacts.length) {
    el.innerHTML = '<div class="empty-state">暂无会话文件</div>';
    setArtifactPanelCollapsed(true);
    return;
  }
  setArtifactPanelCollapsed(false);
  el.innerHTML = state.artifacts
    .map(
      (a) => `
    <div class="artifact-item" data-id="${a.id}">
      <div class="artifact-name">${esc(a.name)}</div>
      <div class="artifact-size">${formatSize(a.size_bytes)} · ${formatPreviewKind(a.preview_kind)}</div>
    </div>`
    )
    .join("");
}

function formatPreviewKind(kind) {
  const labels = {
    text: "文本",
    image: "图片",
    spreadsheet: "Excel",
    table: "表格",
    pdf: "PDF",
    docx: "Word",
    html: "网页",
    binary: "二进制",
  };
  return labels[kind] || kind || "文件";
}

const PDFJS_VERSION = "4.10.38";
const DOCX_PREVIEW_VERSION = "0.3.5";
let pdfjsLibPromise = null;
let docxPreviewPromise = null;

function getPdfjsLib() {
  if (!pdfjsLibPromise) {
    pdfjsLibPromise = import(
      `https://cdn.jsdelivr.net/npm/pdfjs-dist@${PDFJS_VERSION}/+esm`
    ).then((lib) => {
      lib.GlobalWorkerOptions.workerSrc =
        `https://cdn.jsdelivr.net/npm/pdfjs-dist@${PDFJS_VERSION}/build/pdf.worker.min.mjs`;
      return lib;
    });
  }
  return pdfjsLibPromise;
}

function getDocxPreview() {
  if (!docxPreviewPromise) {
    docxPreviewPromise = import(
      `https://cdn.jsdelivr.net/npm/docx-preview@${DOCX_PREVIEW_VERSION}/+esm`
    );
  }
  return docxPreviewPromise;
}

async function fetchArtifactBlob(artifactId) {
  const res = await fetch(`${API}/artifacts/${artifactId}/download`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || res.statusText || "文件加载失败");
  }
  return res.blob();
}

function closeArtifactModal() {
  const dialog = document.getElementById("artifact-modal-dialog");
  if (document.fullscreenElement) {
    document.exitFullscreen().catch(() => {});
  }
  dialog?.classList.remove("is-fullscreen");
  document.getElementById("artifact-modal").classList.add("hidden");
}

function toggleArtifactModalFullscreen() {
  const dialog = document.getElementById("artifact-modal-dialog");
  if (!dialog) return;
  if (document.fullscreenElement) {
    document.exitFullscreen().catch(() => {});
    dialog.classList.remove("is-fullscreen");
    return;
  }
  if (dialog.requestFullscreen) {
    dialog.requestFullscreen().catch(() => {
      dialog.classList.toggle("is-fullscreen");
    });
  } else {
    dialog.classList.toggle("is-fullscreen");
  }
}

function openArtifactModal(title, artifactId) {
  const modal = document.getElementById("artifact-modal");
  document.getElementById("artifact-modal-title").textContent = title || "文件预览";
  document.getElementById("artifact-modal-download").href =
    `${API}/artifacts/${artifactId}/download`;
  document.getElementById("artifact-modal-body").innerHTML =
    '<div class="empty-state">加载中…</div>';
  modal.classList.remove("hidden");
}

function renderSpreadsheetTable(rows) {
  if (!rows?.length) return '<div class="empty-state">（空表格）</div>';
  const head = rows[0]
    .map((cell) => `<th>${esc(cell)}</th>`)
    .join("");
  const body = rows
    .slice(1)
    .map(
      (row) =>
        `<tr>${row.map((cell) => `<td>${esc(cell)}</td>`).join("")}</tr>`
    )
    .join("");
  return `<div class="table-scroll"><table class="data-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function renderSpreadsheetPreview(data) {
  if (!data.sheets?.length) return '<div class="empty-state">（空工作簿）</div>';
  if (data.sheets.length === 1) {
    return renderSpreadsheetTable(data.sheets[0].rows);
  }
  return data.sheets
    .map(
      (sheet) => `
    <div class="sheet-block">
      <div class="sheet-name">${esc(sheet.name)}</div>
      ${renderSpreadsheetTable(sheet.rows)}
    </div>`
    )
    .join("");
}

function renderArtifactPreviewContent(data, artifactId, fileName) {
  const ext = (fileName || "").toLowerCase();
  let html = "";

  if (data.kind === "spreadsheet" || data.kind === "table") {
    const rows = data.kind === "table" ? data.rows : null;
    const table = rows ? renderSpreadsheetTable(rows) : renderSpreadsheetPreview(data);
    html = `<div class="preview-scroll">${table}</div>`;
  } else if (data.kind === "image") {
    html = `<div class="preview-scroll preview-center"><img src="data:${data.mime};base64,${data.data}" alt="preview" /></div>`;
  } else if (data.kind === "pdf") {
    html = '<div class="preview-fill pdf-preview-mount"><div class="empty-state">PDF 加载中…</div></div>';
  } else if (data.kind === "docx") {
    html = '<div class="preview-fill docx-preview-mount"><div class="empty-state">Word 文档加载中…</div></div>';
  } else if (data.kind === "html") {
    html = `<div class="preview-fill"><iframe class="preview-iframe preview-html-frame" title="HTML 预览" sandbox=""></iframe></div>`;
  } else if (data.kind === "text") {
    if (ext.endsWith(".md") || ext.endsWith(".markdown")) {
      html = `<div class="preview-scroll markdown-body">${marked.parse(data.content)}</div>`;
    } else if (ext.endsWith(".json")) {
      let formatted = data.content;
      try {
        formatted = JSON.stringify(JSON.parse(data.content), null, 2);
      } catch {
        /* keep raw */
      }
      html = `<div class="preview-scroll"><pre class="code-preview">${esc(formatted)}</pre></div>`;
    } else if (ext.endsWith(".csv") || ext.endsWith(".tsv")) {
      html = `<div class="preview-scroll">${renderSpreadsheetTable(parseDelimitedText(data.content, ext.endsWith(".tsv") ? "\t" : ","))}</div>`;
    } else {
      html = `<div class="preview-scroll"><pre class="code-preview">${esc(data.content)}</pre></div>`;
    }
  } else {
    html = `<div class="preview-scroll"><div class="empty-state">${esc(data.message || "不支持预览")}<br><a href="${API}/artifacts/${artifactId}/download" class="btn btn-sm" style="margin-top:12px;display:inline-block;">下载文件</a></div></div>`;
  }

  if (data.truncated) {
    html += '<p class="preview-truncated">内容已截断，完整内容请下载查看</p>';
  }
  return html;
}

async function renderPdfPages(mountEl, pdf, scale) {
  const pagesEl = mountEl.querySelector(".pdf-pages");
  if (!pagesEl) return;
  pagesEl.innerHTML = '<div class="empty-state">渲染中…</div>';
  pagesEl.innerHTML = "";
  for (let pageNum = 1; pageNum <= pdf.numPages; pageNum += 1) {
    const page = await pdf.getPage(pageNum);
    const viewport = page.getViewport({ scale });
    const canvas = document.createElement("canvas");
    canvas.className = "pdf-page-canvas";
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    await page.render({
      canvasContext: canvas.getContext("2d"),
      viewport,
    }).promise;
    pagesEl.appendChild(canvas);
  }
  const pageInfo = mountEl.querySelector(".pdf-page-info");
  if (pageInfo) pageInfo.textContent = `共 ${pdf.numPages} 页`;
  const zoomInfo = mountEl.querySelector(".pdf-zoom-info");
  if (zoomInfo) zoomInfo.textContent = `${Math.round(scale * 100)}%`;
}

async function renderPdfPreview(artifactId, mountEl) {
  const pdfjs = await getPdfjsLib();
  const blob = await fetchArtifactBlob(artifactId);
  const data = await blob.arrayBuffer();
  const pdf = await pdfjs.getDocument({ data }).promise;
  let scale = 1.25;

  mountEl.innerHTML = `
    <div class="pdf-preview">
      <div class="pdf-toolbar">
        <span class="pdf-page-info">共 ${pdf.numPages} 页</span>
        <span class="pdf-toolbar-spacer"></span>
        <button type="button" class="btn btn-sm pdf-zoom-out" title="缩小">−</button>
        <span class="pdf-zoom-info">125%</span>
        <button type="button" class="btn btn-sm pdf-zoom-in" title="放大">+</button>
      </div>
      <div class="pdf-pages"></div>
    </div>`;

  const rerender = async () => {
    mountEl.querySelector(".pdf-zoom-out").disabled = scale <= 0.5;
    mountEl.querySelector(".pdf-zoom-in").disabled = scale >= 3;
    await renderPdfPages(mountEl, pdf, scale);
  };

  mountEl.querySelector(".pdf-zoom-out").addEventListener("click", async () => {
    scale = Math.max(0.5, Math.round((scale - 0.25) * 100) / 100);
    await rerender();
  });
  mountEl.querySelector(".pdf-zoom-in").addEventListener("click", async () => {
    scale = Math.min(3, Math.round((scale + 0.25) * 100) / 100);
    await rerender();
  });

  await rerender();
}

async function renderDocxPreview(artifactId, mountEl) {
  const { renderAsync } = await getDocxPreview();
  const blob = await fetchArtifactBlob(artifactId);
  mountEl.innerHTML = '<div class="docx-preview"></div>';
  const container = mountEl.querySelector(".docx-preview");
  await renderAsync(blob, container, null, {
    className: "docx-preview-body",
    inWrapper: true,
    ignoreWidth: false,
    ignoreHeight: false,
    breakPages: true,
  });
}

function parseDelimitedText(text, delimiter) {
  return text
    .split(/\r?\n/)
    .filter((line) => line.length)
    .map((line) => {
      const cells = [];
      let current = "";
      let inQuotes = false;
      for (let i = 0; i < line.length; i += 1) {
        const ch = line[i];
        if (ch === '"') {
          inQuotes = !inQuotes;
          continue;
        }
        if (ch === delimiter && !inQuotes) {
          cells.push(current);
          current = "";
          continue;
        }
        current += ch;
      }
      cells.push(current);
      return cells;
    });
}

async function previewArtifact(artifactId) {
  document.querySelectorAll(".artifact-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.id === artifactId);
  });
  const artifact = state.artifacts.find((a) => a.id === artifactId);
  openArtifactModal(artifact?.name || "文件预览", artifactId);
  try {
    const data = await api(`/artifacts/${artifactId}/preview`);
    const body = document.getElementById("artifact-modal-body");
    body.innerHTML = renderArtifactPreviewContent(
      data,
      artifactId,
      artifact?.name || ""
    );
    if (data.kind === "html") {
      const frame = body.querySelector(".preview-html-frame");
      if (frame) frame.srcdoc = data.content || "";
    } else if (data.kind === "pdf") {
      const mount = body.querySelector(".pdf-preview-mount");
      if (mount) await renderPdfPreview(artifactId, mount);
    } else if (data.kind === "docx") {
      const mount = body.querySelector(".docx-preview-mount");
      if (mount) await renderDocxPreview(artifactId, mount);
    }
  } catch (e) {
    document.getElementById("artifact-modal-body").innerHTML =
      `<div class="empty-state">${esc(e.message)}</div>`;
  }
}

function toggleArtifactPanel() {
  setArtifactPanelCollapsed(!state.artifactPanelCollapsed);
}

// ── Config ───────────────────────────────────────────────────

let globalSettings = null;

async function openSettings() {
  document.getElementById("settings-modal").classList.remove("hidden");
  const cfg = await api("/config");
  globalSettings = cfg.settings;
  document.getElementById("cfg-llm-model").value = cfg.settings.llm?.model || "";
  document.getElementById("cfg-llm-api-base").value = cfg.settings.llm?.api_base || "";
  document.getElementById("cfg-llm-temperature").value = cfg.settings.llm?.temperature ?? 0.7;
  document.getElementById("cfg-agent-max-tool-rounds").value = cfg.settings.agent?.max_tool_rounds ?? 50;
  document.getElementById("cfg-memory-enabled").value = String(cfg.settings.memory?.enabled ?? true);
  document.getElementById("cfg-full-json").textContent = JSON.stringify(cfg.settings, null, 2);
  await loadSessionConfigForm();
}

async function saveGlobalConfig() {
  const updates = [
    { path: "llm.model", value: document.getElementById("cfg-llm-model").value },
    { path: "llm.api_base", value: document.getElementById("cfg-llm-api-base").value || null },
    { path: "llm.temperature", value: parseFloat(document.getElementById("cfg-llm-temperature").value) },
    { path: "agent.max_tool_rounds", value: parseInt(document.getElementById("cfg-agent-max-tool-rounds").value, 10) },
    { path: "memory.enabled", value: document.getElementById("cfg-memory-enabled").value === "true" },
  ];
  await api("/config", { method: "PATCH", body: JSON.stringify({ updates }) });
  toast("全局配置已保存");
  openSettings();
}

function resetSessionConfigForm() {
  document.getElementById("sess-title").value = "";
  document.getElementById("sess-persona-role").value = "";
  document.getElementById("sess-persona-tone").value = "";
  document.getElementById("sess-persona-instructions").value = "";
  document.querySelectorAll('input[name="sess-skill"]').forEach((cb) => {
    cb.checked = false;
  });
}

function updateSessionConfigHint(text) {
  const el = document.getElementById("sess-config-hint");
  if (el) el.textContent = text;
}

function setFieldDefaultHint(elId, text, overridden = false) {
  const hint = document.getElementById(`${elId}-hint`);
  if (!hint) return;
  hint.textContent = text;
  hint.classList.toggle("overridden", overridden);
}

function renderSessionDefaultsPanel(detail) {
  const panel = document.getElementById("sess-defaults-panel");
  if (!panel) return;
  const defaults = detail.agent_defaults;
  panel.classList.remove("hidden");
  panel.innerHTML = `
    <div><strong>Agent 默认人设</strong>（${esc(detail.agent_name)}）</div>
    <div>角色：${esc(defaults.role || "通用 AI 助手")}</div>
    <div>语气：${esc(defaults.tone || "简洁专业")}</div>
    <div>自定义指令：${esc(defaults.custom_instructions || "（无）")}</div>
    <div style="margin-top:6px;">
      默认技能：${
        detail.agent_skills?.length
          ? esc(detail.agent_skills.join("、"))
          : "全部已启用技能"
      }
    </div>`;
}

function renderSessionSystemSections(detail) {
  const directivesEl = document.getElementById("sess-system-directives");
  const previewEl = document.getElementById("sess-prompt-preview");
  if (directivesEl) {
    directivesEl.textContent = (detail.system_directives || []).join("\n\n");
  }
  if (previewEl) {
    previewEl.textContent = detail.system_prompt_preview || "";
  }
}

function applySessionSkillSelection(skillIds) {
  const boxes = document.querySelectorAll('input[name="sess-skill"]');
  if (!boxes.length) return;
  if (!skillIds) {
    boxes.forEach((cb) => {
      cb.checked = true;
    });
    return;
  }
  boxes.forEach((cb) => {
    cb.checked = skillIds.includes(cb.value);
  });
}

function sessionPersonaMatchesDefaults(role, tone, instructions) {
  const defaults = state.sessionAgentDefaults?.persona;
  if (!defaults) return false;
  return (
    role === (defaults.role || "") &&
    tone === (defaults.tone || "") &&
    instructions === (defaults.custom_instructions || "")
  );
}

function sessionSkillsMatchDefaults(selectedSkills) {
  const defaults = state.sessionAgentDefaults;
  const allSkillCount = document.querySelectorAll('input[name="sess-skill"]').length;
  if (!defaults?.skills?.length) {
    return selectedSkills.length === allSkillCount;
  }
  const defaultSet = new Set(defaults.skills);
  const selectedSet = new Set(selectedSkills);
  return (
    defaultSet.size === selectedSet.size &&
    [...defaultSet].every((id) => selectedSet.has(id))
  );
}

async function loadSessionConfigForm() {
  if (!state.allSkills.length) {
    state.allSkills = await api("/skills");
  }
  const skillsEl = document.getElementById("sess-skills");
  skillsEl.innerHTML = state.allSkills
    .filter((s) => s.enabled)
    .map(
      (s) => `
    <label class="skill-card">
      <input type="checkbox" name="sess-skill" value="${s.id}" />
      <div class="skill-card-info">
        <div class="skill-card-name">${esc(s.name)} <span style="color:var(--text-muted)">(${s.id})</span><a href="#" class="skill-doc-link" data-skill-id="${esc(s.id)}">SKILL.md</a></div>
        <div class="skill-card-desc">${esc(s.description)}</div>
      </div>
    </label>`
    )
    .join("");

  resetSessionConfigForm();
  state.sessionAgentDefaults = null;
  document.getElementById("sess-defaults-panel")?.classList.add("hidden");
  setFieldDefaultHint("sess-persona-role", "");
  setFieldDefaultHint("sess-persona-tone", "");
  setFieldDefaultHint("sess-persona-instructions", "");
  setFieldDefaultHint("sess-skills", "");
  document.getElementById("sess-system-directives").textContent = "";
  document.getElementById("sess-prompt-preview").textContent = "";

  if (!state.threadId) {
    updateSessionConfigHint("请先选择会话，再编辑本会话专属配置。");
    return;
  }

  const thread = state.threads.find((t) => t.id === state.threadId);
  const detail = await api(`/threads/${state.threadId}/config`);
  const agentDefaults = detail.agent_defaults || {};
  state.sessionAgentDefaults = {
    persona: {
      role: agentDefaults.role || "通用 AI 助手",
      tone: agentDefaults.tone || "简洁专业",
      custom_instructions: agentDefaults.custom_instructions || "",
    },
    skills: detail.agent_skills?.length ? [...detail.agent_skills] : null,
  };

  document.getElementById("sess-title").value = thread?.title || detail.title || "";
  const effective = detail.effective_persona || agentDefaults;
  document.getElementById("sess-persona-role").value = effective.role || "";
  document.getElementById("sess-persona-tone").value = effective.tone || "";
  document.getElementById("sess-persona-instructions").value =
    effective.custom_instructions || "";
  applySessionSkillSelection(detail.effective_skill_ids);

  renderSessionDefaultsPanel(detail);
  renderSessionSystemSections(detail);

  const roleDefault = agentDefaults.role || "通用 AI 助手";
  const toneDefault = agentDefaults.tone || "简洁专业";
  const instructionsDefault = agentDefaults.custom_instructions || "（无）";
  const personaOverridden = !!detail.has_persona_override;
  setFieldDefaultHint(
    "sess-persona-role",
    personaOverridden ? `已覆盖 · Agent 默认：${roleDefault}` : `继承 Agent 默认：${roleDefault}`,
    personaOverridden
  );
  setFieldDefaultHint(
    "sess-persona-tone",
    personaOverridden ? `已覆盖 · Agent 默认：${toneDefault}` : `继承 Agent 默认：${toneDefault}`,
    personaOverridden
  );
  setFieldDefaultHint(
    "sess-persona-instructions",
    personaOverridden
      ? `已覆盖 · Agent 默认：${instructionsDefault}`
      : `继承 Agent 默认：${instructionsDefault}`,
    personaOverridden
  );

  const skillsOverridden = !!detail.has_skills_override;
  const skillsDefaultLabel = detail.agent_skills?.length
    ? detail.agent_skills.join("、")
    : "全部已启用技能";
  setFieldDefaultHint(
    "sess-skills",
    skillsOverridden
      ? `已覆盖 · Agent 默认：${skillsDefaultLabel}`
      : `继承 Agent 默认：${skillsDefaultLabel}`,
    skillsOverridden
  );

  const threadLabel = thread?.title || `会话 ${state.threadId.slice(0, 8)}…`;
  const hasOverride = personaOverridden || skillsOverridden;
  updateSessionConfigHint(
    hasOverride
      ? `「${threadLabel}」使用独立配置（仅本会话生效）`
      : `「${threadLabel}」当前完全继承 Agent「${detail.agent_name}」默认配置`
  );
}

async function saveSessionConfig() {
  if (!state.threadId) {
    toast("请先选择会话", true);
    return;
  }
  if (!state.sessionAgentDefaults) {
    await loadSessionConfigForm();
  }
  const role = document.getElementById("sess-persona-role").value.trim();
  const tone = document.getElementById("sess-persona-tone").value.trim();
  const instructions = document.getElementById("sess-persona-instructions").value.trim();
  const selectedSkills = [...document.querySelectorAll('input[name="sess-skill"]:checked')].map(
    (cb) => cb.value
  );
  const defaults = state.sessionAgentDefaults;
  const body = {
    title: document.getElementById("sess-title").value.trim() || null,
    persona: sessionPersonaMatchesDefaults(role, tone, instructions)
      ? null
      : {
          role: role || defaults?.persona.role || "通用 AI 助手",
          tone: tone || defaults?.persona.tone || "简洁专业",
          constraints: [],
          custom_instructions: instructions,
        },
    skills: sessionSkillsMatchDefaults(selectedSkills) ? null : selectedSkills,
  };
  await api(`/threads/${state.threadId}/config`, { method: "PUT", body: JSON.stringify(body) });
  toast("会话配置已保存");
  await loadThreads();
  await loadSessionConfigForm();
}

async function resetSessionConfig() {
  if (!state.threadId) return;
  await api(`/threads/${state.threadId}/config`, {
    method: "PUT",
    body: JSON.stringify({ title: null, persona: null, skills: null, llm_override: null }),
  });
  toast("已重置为 Agent 默认");
  await loadSessionConfigForm();
}

// ── Session scheduler jobs ───────────────────────────────────

let sessionJobsRefreshTimer = null;
const sessionJobsExpanded = new Set();
const sessionJobStatuses = new Map();

const JOB_STATUS_LABELS = {
  pending: "等待中",
  running: "运行中",
  success: "成功",
  error: "失败",
  disabled: "已停用",
};

function formatJobSchedule(job) {
  if (job.schedule_type === "cron") {
    return `Cron: ${job.cron_expression || "—"}`;
  }
  if (job.schedule_type === "once") {
    return `单次: ${job.at_time || "—"}`;
  }
  if (job.schedule_type === "interval") {
    return `间隔: 每 ${job.interval_minutes} 分钟`;
  }
  return job.schedule_type;
}

function formatJobAction(job) {
  const p = job.action_payload || {};
  if (job.action_type === "script") {
    return `脚本: ${p.path || p.script_path || "—"}`;
  }
  if (job.action_type === "skill_tool") {
    return `技能工具: ${p.skill_id}.${p.tool_name}`;
  }
  if (job.action_type === "agent_prompt") {
    const prompt = p.prompt || "";
    return `Agent 提示: ${prompt.slice(0, 80)}${prompt.length > 80 ? "…" : ""}`;
  }
  return job.action_type;
}

function jobStatusBadgeHtml(status) {
  const s = status || "pending";
  const label = JOB_STATUS_LABELS[s] || s;
  return `<span class="job-badge status-${esc(s)}">${esc(label)}</span>`;
}

function renderJobRun(run) {
  const outputBlock = run.output
    ? `<pre class="job-run-output">${esc(run.output)}</pre>`
    : "";
  const errorBlock = run.error ? `<div class="job-error">${esc(run.error)}</div>` : "";
  const timeRange = run.finished_at
    ? `${esc(run.started_at)} → ${esc(run.finished_at)}`
    : `${esc(run.started_at)} → 进行中`;
  return `
    <div class="job-run-item">
      <div class="job-run-header">
        ${jobStatusBadgeHtml(run.status)}
        <span class="job-run-time">${timeRange}</span>
      </div>
      ${errorBlock}
      ${outputBlock}
    </div>`;
}

function renderJobCard(job) {
  const expanded = sessionJobsExpanded.has(job.id);
  const enabledBadge = job.enabled
    ? `<span class="job-badge">已启用</span>`
    : `<span class="job-badge enabled-off">已停用</span>`;
  const lastError = job.last_error
    ? `<div class="job-error">最近错误：${esc(job.last_error)}</div>`
    : "";
  return `
    <div class="job-card" data-job-id="${esc(job.id)}">
      <div class="job-card-header" data-toggle-job="${esc(job.id)}">
        <div>
          <div class="job-card-title">${esc(job.name || "未命名任务")}</div>
          <div class="job-card-id">${esc(job.id)}</div>
        </div>
        <div class="job-card-badges">
          ${jobStatusBadgeHtml(job.last_status)}
          ${enabledBadge}
        </div>
      </div>
      <div class="job-card-body ${expanded ? "" : "hidden"}" id="job-body-${esc(job.id)}">
        <div class="job-meta-grid">
          <div><strong>调度</strong><br>${esc(formatJobSchedule(job))}</div>
          <div><strong>动作</strong><br>${esc(formatJobAction(job))}</div>
          <div><strong>下次执行</strong><br>${esc(job.next_run_at || "—")}</div>
          <div><strong>上次执行</strong><br>${esc(job.last_run_at || "—")}</div>
          <div><strong>执行次数</strong><br>${job.run_count}${job.max_runs ? ` / ${job.max_runs}` : ""}</div>
          <div><strong>超时</strong><br>${job.timeout_secs}s</div>
        </div>
        ${lastError}
        <div class="job-runs-title">执行记录</div>
        <div class="job-runs" id="job-runs-${esc(job.id)}">
          <div class="job-runs-empty">${expanded ? "加载中…" : "展开后加载执行记录"}</div>
        </div>
      </div>
    </div>`;
}

async function loadJobRuns(jobId) {
  if (!state.threadId) return;
  const container = document.getElementById(`job-runs-${jobId}`);
  if (!container) return;
  try {
    const data = await api(`/threads/${state.threadId}/jobs/${jobId}/runs?limit=10`);
    if (!data.runs?.length) {
      container.innerHTML = `<div class="job-runs-empty">暂无执行记录</div>`;
      return;
    }
    container.innerHTML = data.runs.map(renderJobRun).join("");
  } catch (e) {
    container.innerHTML = `<div class="job-runs-empty">加载失败: ${esc(e.message)}</div>`;
  }
}

async function toggleJobExpand(jobId) {
  const body = document.getElementById(`job-body-${jobId}`);
  if (!body) return;
  const isHidden = body.classList.contains("hidden");
  if (isHidden) {
    body.classList.remove("hidden");
    if (!sessionJobsExpanded.has(jobId)) {
      sessionJobsExpanded.add(jobId);
      await loadJobRuns(jobId);
    }
  } else {
    body.classList.add("hidden");
  }
}

function resetSessionJobStatuses(jobs) {
  sessionJobStatuses.clear();
  for (const job of jobs) {
    sessionJobStatuses.set(job.id, job.last_status);
  }
}

function maybeRefreshArtifactsOnJobComplete(jobs) {
  let completed = false;
  for (const job of jobs) {
    const prev = sessionJobStatuses.get(job.id);
    const status = job.last_status;
    if (status === "success" && prev !== "success") {
      if (prev === "running" || prev === "pending") {
        completed = true;
      } else if (prev === undefined && job.last_run_at) {
        completed = true;
      }
    }
    sessionJobStatuses.set(job.id, status);
  }
  if (completed) {
    loadArtifacts();
  }
}

function stopSessionJobsAutoRefresh() {
  if (sessionJobsRefreshTimer) {
    clearInterval(sessionJobsRefreshTimer);
    sessionJobsRefreshTimer = null;
  }
}

function maybeStartSessionJobsAutoRefresh(jobs) {
  stopSessionJobsAutoRefresh();
  const hasRunning = jobs.some((j) => j.last_status === "running" && j.enabled);
  if (!hasRunning) return;
  sessionJobsRefreshTimer = setInterval(() => {
    loadSessionJobs({ silent: true });
  }, 8000);
}

async function syncSessionJobsForPolling() {
  if (!state.threadId) {
    sessionJobStatuses.clear();
    stopSessionJobsAutoRefresh();
    return;
  }
  try {
    const jobs = await api(`/threads/${state.threadId}/jobs`);
    resetSessionJobStatuses(jobs);
    maybeStartSessionJobsAutoRefresh(jobs);
  } catch {
    // ignore — polling is best-effort
  }
}

async function loadSessionJobs(opts = {}) {
  const listEl = document.getElementById("jobs-list");
  const metaEl = document.getElementById("jobs-meta");
  const hintEl = document.getElementById("jobs-hint");
  if (!listEl) return;

  if (!state.threadId) {
    listEl.innerHTML = `<div class="jobs-empty">请先选择会话</div>`;
    if (metaEl) metaEl.textContent = "";
    if (hintEl) hintEl.textContent = "请先在左侧选择会话，再查看该会话绑定的定时任务。";
    sessionJobStatuses.clear();
    stopSessionJobsAutoRefresh();
    return;
  }

  if (!opts.silent) {
    listEl.innerHTML = `<div class="jobs-empty">加载中…</div>`;
  }

  try {
    const jobs = await api(`/threads/${state.threadId}/jobs`);
    if (hintEl) {
      hintEl.textContent = jobs.length
        ? `共 ${jobs.length} 个任务绑定到当前会话。点击任务卡片展开可查看执行记录与输出。`
        : "当前会话暂无定时任务。可通过对话让 Agent 使用 job_scheduler 技能创建（会自动绑定当前会话）。";
    }
    if (metaEl) {
      metaEl.textContent = jobs.length ? `共 ${jobs.length} 项` : "";
    }
    if (!jobs.length) {
      listEl.innerHTML = `<div class="jobs-empty">暂无定时任务</div>`;
      sessionJobStatuses.clear();
      stopSessionJobsAutoRefresh();
      return;
    }
    if (opts.syncStatuses) {
      resetSessionJobStatuses(jobs);
    } else {
      maybeRefreshArtifactsOnJobComplete(jobs);
    }
    listEl.innerHTML = jobs.map(renderJobCard).join("");
    for (const jobId of [...sessionJobsExpanded]) {
      if (jobs.some((j) => j.id === jobId)) {
        loadJobRuns(jobId);
      } else {
        sessionJobsExpanded.delete(jobId);
      }
    }
    maybeStartSessionJobsAutoRefresh(jobs);
  } catch (e) {
    listEl.innerHTML = `<div class="jobs-empty">加载失败: ${esc(e.message)}</div>`;
    stopSessionJobsAutoRefresh();
  }
}

// ── Skills modal ─────────────────────────────────────────────

function skillDocLinkHtml(skillId) {
  return `<a href="#" class="skill-doc-link" data-skill-id="${esc(skillId)}">SKILL.md</a>`;
}

function renderSkillDetailBody() {
  const skill = state.skillDetail;
  const bodyEl = document.getElementById("skill-detail-body");
  const toggleBtn = document.getElementById("skill-detail-view-toggle");
  if (!skill || !bodyEl) return;

  if (state.skillDetailView === "source") {
    toggleBtn.textContent = "查看文档";
    bodyEl.innerHTML = `<div class="preview-scroll"><pre class="code-preview">${esc(skill.source)}</pre></div>`;
    return;
  }

  toggleBtn.textContent = "查看源码";
  const metaParts = [
    `版本 ${esc(skill.version)}`,
    skill.execution === "sandbox" ? "沙盒执行" : "宿主机执行",
    skill.enabled ? "已启用" : "已禁用",
  ];
  if (skill.author) metaParts.push(`作者 ${esc(skill.author)}`);
  if (skill.tools?.length) metaParts.push(`工具 ${esc(skill.tools.join(", "))}`);
  if (skill.tags?.length) metaParts.push(`标签 ${esc(skill.tags.join(", "))}`);
  if (skill.path) metaParts.push(esc(skill.path));

  bodyEl.innerHTML = `
    <div class="skill-detail-meta">${metaParts.map((part) => `<span>${part}</span>`).join("")}</div>
    <div class="preview-scroll markdown-body">${marked.parse(skill.markdown || "（无正文）")}</div>`;
}

async function openSkillDetail(skillId) {
  const modal = document.getElementById("skill-detail-modal");
  document.getElementById("skill-detail-title").textContent = "加载中…";
  document.getElementById("skill-detail-body").innerHTML =
    '<div class="empty-state">加载中…</div>';
  state.skillDetail = null;
  state.skillDetailView = "markdown";
  modal.classList.remove("hidden");

  try {
    const skill = await api(`/skills/detail/${encodeURIComponent(skillId)}`);
    state.skillDetail = skill;
    document.getElementById("skill-detail-title").textContent = `${skill.name} · SKILL.md`;
    renderSkillDetailBody();
  } catch (err) {
    document.getElementById("skill-detail-title").textContent = "技能文档";
    document.getElementById("skill-detail-body").innerHTML =
      `<div class="empty-state">加载失败：${esc(err.message || String(err))}</div>`;
  }
}

async function openSkills() {
  document.getElementById("skills-modal").classList.remove("hidden");
  await renderSkillsList();
}

async function renderSkillsList() {
  state.allSkills = await api("/skills");
  document.getElementById("skills-list").innerHTML = state.allSkills
    .map(
      (s) => `
    <div class="skill-card">
      <div class="skill-card-info">
        <div class="skill-card-name">${esc(s.name)} <span style="color:var(--text-muted)">v${esc(s.version)} · ${s.id}</span> ${skillDocLinkHtml(s.id)}</div>
        <div class="skill-card-desc">${esc(s.description)}</div>
        <div style="font-size:0.75rem;color:var(--text-muted);margin-top:4px;">
          工具: ${s.tools.join(", ") || "无"} · ${s.enabled ? "已启用" : "已禁用"}
        </div>
        <div style="font-size:0.72rem;color:var(--text-muted);margin-top:2px;">${esc(s.path || "")}</div>
      </div>
    </div>`
    )
    .join("");
}

async function scanSkills() {
  const result = await api("/skills/scan", { method: "POST" });
  toast(`已扫描 ${result.scanned} 个技能`);
  await renderSkillsList();
}

// ── Utilities ────────────────────────────────────────────────

function esc(s) {
  if (!s) return "";
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function formatSize(bytes) {
  if (!bytes) return "—";
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / 1048576).toFixed(1) + " MB";
}

function toast(msg, isError = false) {
  const el = document.createElement("div");
  el.className = "toast" + (isError ? " error" : "");
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3000);
}

// ── Event bindings ───────────────────────────────────────────

document.getElementById("btn-new-thread").addEventListener("click", createThread);
document.getElementById("btn-send").addEventListener("click", () => {
  if (isThreadStreaming(state.threadId)) {
    stopCurrentTask();
  } else {
    sendMessage();
  }
});
document.getElementById("btn-attach").addEventListener("click", () => {
  document.getElementById("file-input")?.click();
});
document.getElementById("file-input").addEventListener("change", (e) => {
  const files = [...(e.target.files || [])];
  e.target.value = "";
  uploadFiles(files);
});

const composerEl = document.querySelector(".composer");
if (composerEl) {
  composerEl.addEventListener("dragover", (e) => {
    e.preventDefault();
    composerEl.classList.add("drag-over");
  });
  composerEl.addEventListener("dragleave", (e) => {
    if (!composerEl.contains(e.relatedTarget)) {
      composerEl.classList.remove("drag-over");
    }
  });
  composerEl.addEventListener("drop", (e) => {
    e.preventDefault();
    composerEl.classList.remove("drag-over");
    const files = [...(e.dataTransfer?.files || [])];
    uploadFiles(files);
  });
}
document.getElementById("attachment-chips").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-remove-attachment]");
  if (!btn) return;
  const id = btn.dataset.removeAttachment;
  state.pendingAttachments = state.pendingAttachments.filter((item) => item.id !== id);
  renderAttachmentChips();
});
document.getElementById("btn-settings").addEventListener("click", openSettings);
document.getElementById("btn-theme").addEventListener("click", toggleTheme);
document.getElementById("btn-skills").addEventListener("click", openSkills);
document.getElementById("btn-save-global").addEventListener("click", saveGlobalConfig);
document.getElementById("btn-save-session").addEventListener("click", saveSessionConfig);
document.getElementById("btn-reset-session").addEventListener("click", resetSessionConfig);
document.getElementById("btn-refresh-jobs")?.addEventListener("click", () => loadSessionJobs());
document.getElementById("jobs-list")?.addEventListener("click", (e) => {
  const header = e.target.closest("[data-toggle-job]");
  if (header) toggleJobExpand(header.dataset.toggleJob);
});
document.getElementById("btn-scan-skills").addEventListener("click", scanSkills);
document.getElementById("skill-detail-view-toggle").addEventListener("click", () => {
  if (!state.skillDetail) return;
  state.skillDetailView = state.skillDetailView === "source" ? "markdown" : "source";
  renderSkillDetailBody();
});

function handleSkillDocLinkClick(e) {
  const link = e.target.closest(".skill-doc-link");
  if (!link) return;
  e.preventDefault();
  e.stopPropagation();
  const skillId = link.dataset.skillId;
  if (skillId) openSkillDetail(skillId);
}

document.getElementById("skills-list").addEventListener("click", handleSkillDocLinkClick);
document.getElementById("sess-skills").addEventListener("click", handleSkillDocLinkClick);

const composerInput = document.getElementById("input");
composerInput.addEventListener("paste", handleComposerPaste);
composerInput.addEventListener("input", () => {
  updateMentionPickerFromInput();
});
composerInput.addEventListener("keydown", (e) => {
  if (handleMentionKeydown(e)) return;
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});
composerInput.addEventListener("mousedown", () => {
  if (mentionState.active) {
    hideMentionPicker();
  }
});
composerInput.addEventListener("blur", () => {
  setTimeout(() => {
    const picker = document.getElementById("mention-picker");
    if (picker && !picker.matches(":hover") && document.activeElement !== picker) {
      hideMentionPicker();
    }
  }, 120);
});

document.getElementById("mention-picker").addEventListener("mousedown", (e) => {
  e.preventDefault();
  const item = e.target.closest(".mention-item");
  if (!item) return;
  const index = Number(item.dataset.index);
  if (!Number.isNaN(index)) {
    selectMentionByIndex(index);
  }
});

document.getElementById("thread-list").addEventListener("click", (e) => {
  const del = e.target.closest("[data-delete]");
  if (del) {
    e.stopPropagation();
    deleteThread(del.dataset.delete);
    return;
  }
  const item = e.target.closest(".thread-item");
  if (item) selectThread(item.dataset.id);
});

document.getElementById("messages").addEventListener("scroll", (e) => {
  if (e.target.scrollTop < 120 && state.hasMore && !state.loadingOlder) {
    loadMessages(true);
  }
});

document.getElementById("messages").addEventListener("click", (e) => {
  if (e.target.closest("#load-more-hint") && state.hasMore && !state.loadingOlder) {
    loadMessages(true);
  }
});

document.getElementById("btn-artifact-toggle").addEventListener("click", toggleArtifactPanel);

document.getElementById("artifact-list").addEventListener("click", (e) => {
  const item = e.target.closest(".artifact-item");
  if (item) previewArtifact(item.dataset.id);
});

document.getElementById("artifact-modal-fullscreen").addEventListener("click", toggleArtifactModalFullscreen);

document.getElementById("artifact-modal-dialog")?.addEventListener("fullscreenchange", () => {
  const dialog = document.getElementById("artifact-modal-dialog");
  if (!dialog) return;
  if (!document.fullscreenElement) {
    dialog.classList.remove("is-fullscreen");
  }
});

document.querySelectorAll(".modal-close").forEach((btn) => {
  btn.addEventListener("click", () => {
    const modalId = btn.dataset.close;
    if (modalId === "artifact-modal") {
      closeArtifactModal();
      return;
    }
    document.getElementById(modalId).classList.add("hidden");
  });
});

document.querySelectorAll(".modal-overlay").forEach((overlay) => {
  overlay.addEventListener("click", (e) => {
    if (e.target !== overlay) return;
    if (overlay.id === "artifact-modal") {
      closeArtifactModal();
      return;
    }
    overlay.classList.add("hidden");
  });
});

document.querySelectorAll(".tabs .tab").forEach((tab) => {
  tab.addEventListener("click", async () => {
    document.querySelectorAll(".tabs .tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.add("hidden"));
    document.getElementById(tab.dataset.tab).classList.remove("hidden");
    if (tab.dataset.tab === "session-config") {
      await loadSessionConfigForm();
    } else if (tab.dataset.tab === "scheduler-jobs") {
      await loadSessionJobs({ syncStatuses: true });
    }
  });
});

// Hide non-default tab panels initially
document.getElementById("session-config").classList.add("hidden");
document.getElementById("scheduler-jobs").classList.add("hidden");

marked.setOptions({ breaks: true, gfm: true });

// Boot
setArtifactPanelCollapsed(true);
loadThreads().catch((e) => toast(e.message, true));
