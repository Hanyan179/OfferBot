/**
 * TaskPanel — 固定在 Chainlit 右侧的任务面板。
 * 
 * 通过 custom_js 注入，监听 window message 更新任务状态。
 * Python 端通过 cl.send_window_message(json) 推送任务数据。
 * 
 * 消息协议：
 *   { "type": "task_panel_update", "tasks": [...] }
 *   { "type": "task_panel_open" }
 *   { "type": "task_panel_close" }
 */

(function () {
  // ---- 状态 ----
  let tasks = [];
  let panelOpen = false;
  let panelEl = null;
  let toggleBtn = null;

  // ---- 创建 DOM ----
  function createPanel() {
    // 切换按钮（固定在右侧边缘）
    toggleBtn = document.createElement('button');
    toggleBtn.id = 'task-panel-toggle';
    toggleBtn.innerHTML = '📋';
    toggleBtn.title = '任务面板';
    Object.assign(toggleBtn.style, {
      position: 'fixed', right: '0', top: '50%', transform: 'translateY(-50%)',
      zIndex: '9999', width: '32px', height: '48px',
      border: '1px solid var(--border, #e5e7eb)', borderRight: 'none',
      borderRadius: '8px 0 0 8px',
      background: 'var(--card, #fff)', cursor: 'pointer',
      fontSize: '16px', display: 'flex', alignItems: 'center', justifyContent: 'center',
      boxShadow: '-2px 0 8px rgba(0,0,0,0.08)', transition: 'right 0.3s',
    });
    toggleBtn.addEventListener('click', () => togglePanel());
    document.body.appendChild(toggleBtn);

    // 面板
    panelEl = document.createElement('div');
    panelEl.id = 'task-panel';
    Object.assign(panelEl.style, {
      position: 'fixed', right: '-320px', top: '0', width: '320px', height: '100vh',
      zIndex: '9998', background: 'var(--card, #fff)',
      borderLeft: '1px solid var(--border, #e5e7eb)',
      boxShadow: '-4px 0 16px rgba(0,0,0,0.08)',
      transition: 'right 0.3s ease', overflow: 'hidden',
      display: 'flex', flexDirection: 'column',
    });
    panelEl.innerHTML = `
      <div style="padding:12px 16px;border-bottom:1px solid var(--border,#e5e7eb);display:flex;align-items:center;justify-content:between;">
        <span style="font-weight:600;font-size:14px;flex:1;">📋 任务面板</span>
        <button id="task-panel-close" style="background:none;border:none;cursor:pointer;font-size:18px;color:var(--muted-foreground,#6b7280);">✕</button>
      </div>
      <div id="task-panel-body" style="flex:1;overflow-y:auto;padding:12px 16px;"></div>
      <div style="padding:8px 16px;border-top:1px solid var(--border,#e5e7eb);">
        <p style="font-size:10px;color:var(--muted-foreground,#9ca3af);margin:0;">
          数据采集由 <a href="https://github.com/loks666/get_jobs" target="_blank" style="text-decoration:underline;">get_jobs</a> 提供支持 · 猎聘
        </p>
      </div>
    `;
    document.body.appendChild(panelEl);

    panelEl.querySelector('#task-panel-close').addEventListener('click', () => closePanel());
  }

  function togglePanel() {
    panelOpen ? closePanel() : openPanel();
  }

  function openPanel() {
    panelOpen = true;
    panelEl.style.right = '0';
    toggleBtn.style.right = '320px';
    renderTasks();
  }

  function closePanel() {
    panelOpen = false;
    panelEl.style.right = '-320px';
    toggleBtn.style.right = '0';
  }

  // ---- 渲染 ----
  const STATUS = {
    running:   { icon: '⏳', color: '#2563eb', label: '运行中' },
    completed: { icon: '✅', color: '#16a34a', label: '已完成' },
    failed:    { icon: '❌', color: '#dc2626', label: '失败' },
    timeout:   { icon: '⏰', color: '#d97706', label: '超时' },
  };

  function formatElapsed(s) {
    if (!s) return '0s';
    if (s < 60) return s + 's';
    return Math.floor(s / 60) + 'm' + (s % 60) + 's';
  }

  function parseProgress(text) {
    if (!text) return 0;
    const m = text.match(/^(\d+)\s*\/\s*(\d+)/);
    if (m) return Math.round((parseInt(m[1]) / parseInt(m[2])) * 100);
    return 0;
  }

  function renderTasks() {
    const body = document.getElementById('task-panel-body');
    if (!body) return;

    if (tasks.length === 0) {
      body.innerHTML = '<p style="text-align:center;color:var(--muted-foreground,#9ca3af);font-size:13px;margin-top:40px;">暂无运行中的任务</p>';
      return;
    }

    body.innerHTML = tasks.map((t, i) => {
      const st = STATUS[t.status] || STATUS.running;
      const pct = parseProgress(t.progress_text);
      const isRunning = t.status === 'running';

      return `
        <div style="padding:10px 0;${i > 0 ? 'border-top:1px solid var(--border,#e5e7eb);' : ''}">
          <div style="display:flex;align-items:center;justify-content:space-between;">
            <div style="display:flex;align-items:center;gap:6px;">
              <span style="font-size:13px;">${st.icon}</span>
              <span style="font-size:13px;font-weight:500;">${t.name}</span>
            </div>
            ${isRunning ? `<button onclick="window._taskPanelStop('${t.task_id}','${t.platform}')" style="background:none;border:1px solid var(--border,#e5e7eb);border-radius:4px;cursor:pointer;font-size:11px;padding:1px 6px;color:var(--muted-foreground,#6b7280);">停止</button>` : ''}
          </div>
          ${isRunning && pct > 0 ? `
            <div style="margin-top:6px;height:4px;background:var(--muted,#f3f4f6);border-radius:2px;overflow:hidden;">
              <div style="height:100%;width:${pct}%;background:${st.color};border-radius:2px;transition:width 0.5s;"></div>
            </div>
          ` : ''}
          <div style="display:flex;justify-content:space-between;margin-top:4px;font-size:11px;color:var(--muted-foreground,#9ca3af);">
            <span>${t.progress_text || st.label}</span>
            <span>${formatElapsed(t.elapsed_s)}</span>
          </div>
        </div>
      `;
    }).join('');
  }

  // 停止任务（通过 sendUserMessage 或 fetch API）
  window._taskPanelStop = function (taskId, platform) {
    fetch('/api/tasks/' + platform + '/stop', { method: 'POST' })
      .then(r => r.json())
      .then(() => {
        // 乐观更新
        const t = tasks.find(x => x.task_id === taskId);
        if (t) { t.status = 'failed'; t.progress_text = '已停止'; }
        renderTasks();
      })
      .catch(() => {});
  };

  // ---- 监听消息 ----
  window.addEventListener('message', (event) => {
    let data;
    try {
      data = typeof event.data === 'string' ? JSON.parse(event.data) : event.data;
    } catch { return; }

    if (data.type === 'task_panel_update') {
      tasks = data.tasks || [];
      renderTasks();
      // 有运行中的任务时自动展开
      if (tasks.some(t => t.status === 'running') && !panelOpen) {
        openPanel();
      }
      // 更新 toggle 按钮上的运行数
      const running = tasks.filter(t => t.status === 'running').length;
      toggleBtn.innerHTML = running > 0 ? `📋 ${running}` : '📋';
    } else if (data.type === 'task_panel_open') {
      openPanel();
    } else if (data.type === 'task_panel_close') {
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
