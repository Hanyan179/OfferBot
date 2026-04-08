/**
 * TaskPanel — 固定在 Chainlit 右侧的任务面板。
 *
 * 通过 send_window_message 推送任务数据，不污染对话流。
 * 消息协议：
 *   { "type": "task_panel_update", "tasks": [...] }
 *   { "type": "task_panel_open" }
 *   { "type": "task_panel_close" }
 */
(function () {
  const HEADER_H = 60;   // Chainlit header 高度
  const PANEL_W = 300;

  let tasks = [];
  let panelOpen = false;
  let panelEl = null;
  let toggleBtn = null;

  // ---- 样式注入 ----
  const style = document.createElement('style');
  style.textContent = `
    #task-panel-toggle {
      position: fixed;
      right: 0;
      top: ${HEADER_H + 16}px;
      z-index: 9999;
      width: 36px;
      height: 36px;
      border: 1px solid hsl(var(--border));
      border-right: none;
      border-radius: 8px 0 0 8px;
      background: hsl(var(--card));
      color: hsl(var(--foreground));
      cursor: pointer;
      font-size: 15px;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: -2px 2px 8px hsl(var(--foreground) / 0.06);
      transition: right 0.25s ease;
    }
    #task-panel-toggle:hover {
      background: hsl(var(--accent));
    }
    #task-panel-toggle .badge {
      position: absolute;
      top: -4px;
      left: -4px;
      min-width: 16px;
      height: 16px;
      border-radius: 8px;
      background: hsl(var(--primary));
      color: hsl(var(--primary-foreground));
      font-size: 10px;
      font-weight: 600;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 0 4px;
    }
    #task-panel {
      position: fixed;
      right: -${PANEL_W}px;
      top: ${HEADER_H}px;
      width: ${PANEL_W}px;
      height: calc(100vh - ${HEADER_H}px);
      z-index: 9998;
      background: hsl(var(--card));
      border-left: 1px solid hsl(var(--border));
      box-shadow: -4px 0 16px hsl(var(--foreground) / 0.06);
      transition: right 0.25s ease;
      display: flex;
      flex-direction: column;
      font-family: var(--font-sans, system-ui, sans-serif);
    }
    #task-panel.open { right: 0; }
    #task-panel-toggle.shifted { right: ${PANEL_W}px; }

    #task-panel .tp-header {
      padding: 12px 14px;
      border-bottom: 1px solid hsl(var(--border));
      display: flex;
      align-items: center;
    }
    #task-panel .tp-header-title {
      flex: 1;
      font-size: 13px;
      font-weight: 600;
      color: hsl(var(--foreground));
    }
    #task-panel .tp-close {
      background: none;
      border: none;
      cursor: pointer;
      color: hsl(var(--muted-foreground));
      font-size: 16px;
      padding: 2px 4px;
      border-radius: 4px;
    }
    #task-panel .tp-close:hover {
      background: hsl(var(--accent));
    }
    #task-panel .tp-body {
      flex: 1;
      overflow-y: auto;
      padding: 8px 14px;
    }
    #task-panel .tp-empty {
      text-align: center;
      color: hsl(var(--muted-foreground));
      font-size: 12px;
      margin-top: 48px;
    }
    #task-panel .tp-task {
      padding: 10px 0;
    }
    #task-panel .tp-task + .tp-task {
      border-top: 1px solid hsl(var(--border));
    }
    #task-panel .tp-task-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    #task-panel .tp-task-name {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
      font-weight: 500;
      color: hsl(var(--foreground));
    }
    #task-panel .tp-task-name .icon { font-size: 13px; }
    #task-panel .tp-stop-btn {
      background: none;
      border: 1px solid hsl(var(--border));
      border-radius: 4px;
      cursor: pointer;
      font-size: 10px;
      padding: 1px 6px;
      color: hsl(var(--muted-foreground));
    }
    #task-panel .tp-stop-btn:hover {
      background: hsl(var(--accent));
      color: hsl(var(--destructive));
    }
    #task-panel .tp-progress-bar {
      margin-top: 6px;
      height: 3px;
      background: hsl(var(--muted));
      border-radius: 2px;
      overflow: hidden;
    }
    #task-panel .tp-progress-fill {
      height: 100%;
      border-radius: 2px;
      transition: width 0.5s ease;
    }
    #task-panel .tp-meta {
      display: flex;
      justify-content: space-between;
      margin-top: 4px;
      font-size: 11px;
      color: hsl(var(--muted-foreground));
    }
    #task-panel .tp-footer {
      padding: 8px 14px;
      border-top: 1px solid hsl(var(--border));
    }
    #task-panel .tp-footer p {
      font-size: 10px;
      color: hsl(var(--muted-foreground));
      margin: 0;
    }
    #task-panel .tp-footer a {
      color: hsl(var(--muted-foreground));
      text-decoration: underline;
    }
  `;
  document.head.appendChild(style);

  // ---- DOM ----
  function createPanel() {
    toggleBtn = document.createElement('button');
    toggleBtn.id = 'task-panel-toggle';
    toggleBtn.innerHTML = '📋';
    toggleBtn.title = '任务面板';
    toggleBtn.addEventListener('click', togglePanel);
    document.body.appendChild(toggleBtn);

    panelEl = document.createElement('div');
    panelEl.id = 'task-panel';
    panelEl.innerHTML = `
      <div class="tp-header">
        <span class="tp-header-title">📋 任务面板</span>
        <button class="tp-close" title="关闭">✕</button>
      </div>
      <div class="tp-body"></div>
      <div class="tp-footer">
        <p>数据采集由 <a href="https://github.com/loks666/get_jobs" target="_blank">get_jobs</a> 提供支持 · 猎聘</p>
      </div>
    `;
    document.body.appendChild(panelEl);
    panelEl.querySelector('.tp-close').addEventListener('click', closePanel);
  }

  function togglePanel() { panelOpen ? closePanel() : openPanel(); }

  function openPanel() {
    panelOpen = true;
    panelEl.classList.add('open');
    toggleBtn.classList.add('shifted');
    renderTasks();
  }

  function closePanel() {
    panelOpen = false;
    panelEl.classList.remove('open');
    toggleBtn.classList.remove('shifted');
  }

  // ---- 渲染 ----
  const ST = {
    running:   { icon: '⏳', color: 'hsl(var(--primary))', label: '运行中' },
    completed: { icon: '✅', color: '#16a34a', label: '已完成' },
    failed:    { icon: '❌', color: 'hsl(var(--destructive))', label: '失败' },
    timeout:   { icon: '⏰', color: '#d97706', label: '超时' },
  };

  function fmtTime(s) {
    if (!s) return '0s';
    return s < 60 ? s + 's' : Math.floor(s / 60) + 'm' + (s % 60) + 's';
  }

  function parsePct(text) {
    if (!text) return 0;
    const m = text.match(/^(\d+)\s*\/\s*(\d+)/);
    return m ? Math.round((parseInt(m[1]) / parseInt(m[2])) * 100) : 0;
  }

  function renderTasks() {
    const body = panelEl.querySelector('.tp-body');
    if (!body) return;

    if (tasks.length === 0) {
      body.innerHTML = '<p class="tp-empty">暂无运行中的任务</p>';
      return;
    }

    body.innerHTML = tasks.map(t => {
      const st = ST[t.status] || ST.running;
      const pct = parsePct(t.progress_text);
      const isRunning = t.status === 'running';
      return `
        <div class="tp-task">
          <div class="tp-task-row">
            <div class="tp-task-name"><span class="icon">${st.icon}</span>${t.name}</div>
            ${isRunning ? `<button class="tp-stop-btn" onclick="window._tpStop('${t.task_id}','${t.platform}')">停止</button>` : ''}
          </div>
          ${isRunning && pct > 0 ? `<div class="tp-progress-bar"><div class="tp-progress-fill" style="width:${pct}%;background:${st.color};"></div></div>` : ''}
          <div class="tp-meta"><span>${t.progress_text || st.label}</span><span>${fmtTime(t.elapsed_s)}</span></div>
        </div>
      `;
    }).join('');
  }

  window._tpStop = function (taskId, platform) {
    fetch('/api/tasks/' + platform + '/stop', { method: 'POST' }).then(() => {
      const t = tasks.find(x => x.task_id === taskId);
      if (t) { t.status = 'failed'; t.progress_text = '已停止'; }
      renderTasks();
    }).catch(() => {});
  };

  // ---- 消息监听 ----
  window.addEventListener('message', (e) => {
    let d;
    try { d = typeof e.data === 'string' ? JSON.parse(e.data) : e.data; } catch { return; }

    if (d.type === 'task_panel_update') {
      tasks = d.tasks || [];
      renderTasks();
      if (tasks.some(t => t.status === 'running') && !panelOpen) openPanel();
      const n = tasks.filter(t => t.status === 'running').length;
      toggleBtn.innerHTML = n > 0 ? `📋<span class="badge">${n}</span>` : '📋';
    } else if (d.type === 'task_panel_open') {
      openPanel();
    } else if (d.type === 'task_panel_close') {
      closePanel();
    }
  });

  // ---- 初始化 ----
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', createPanel);
  } else {
    createPanel();
  }
})();
