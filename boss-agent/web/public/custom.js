// OfferBot — Chainlit 自定义 JS
// 双向主题同步：父页面 ↔ Chainlit iframe

// 1. 监听父页面的主题切换消息 → 同步到 Chainlit
window.addEventListener('message', (e) => {
  if (e.data && e.data.type === 'themeChange') {
    applyTheme(e.data.dark);
  }
});

function applyTheme(dark) {
  localStorage.setItem('colorMode', dark ? 'dark' : 'light');
  // Chainlit 用 data-theme 和 class 控制主题
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
}

// 2. 监听 Chainlit 自己的主题变化 → 通知父页面
// 通过 MutationObserver 监听 DOM 变化
const observer = new MutationObserver(() => {
  const theme = document.documentElement.getAttribute('data-theme') ||
                document.documentElement.classList.contains('dark') ? 'dark' : 'light';
  const isDark = theme === 'dark';
  // 通知父页面
  if (window.parent !== window) {
    window.parent.postMessage({ type: 'chainlitThemeChange', dark: isDark }, '*');
  }
});

// 监听 html 元素的 class 和 data-theme 属性变化
observer.observe(document.documentElement, {
  attributes: true,
  attributeFilter: ['class', 'data-theme', 'style'],
});

// 也监听 localStorage 变化（Chainlit 内部切换时会写 localStorage）
window.addEventListener('storage', (e) => {
  if (e.key === 'colorMode' && e.newValue) {
    const isDark = e.newValue === 'dark';
    if (window.parent !== window) {
      window.parent.postMessage({ type: 'chainlitThemeChange', dark: isDark }, '*');
    }
  }
});

// 3. 初始化：从 localStorage 读取主题
(function() {
  const saved = localStorage.getItem('offerbot-theme') || localStorage.getItem('colorMode');
  if (saved) {
    applyTheme(saved === 'dark');
  }
})();

// 4. 拦截 Chainlit header 导航链接 → postMessage 通知父页面切标签
// Chainlit header_links 在 iframe 内点击会导航到错误路径，需要拦截
(function() {
  const TAB_MAP = {
    '/page/jobs': 'jobs',
    '/graph': 'graph',
    '/page/interviews': 'interviews',
    '/page/overview': 'overview',
    '/page/memory': 'memory',
    '/page/settings': 'settings',
  };

  document.addEventListener('click', (e) => {
    const a = e.target.closest('a[href]');
    if (!a) return;
    const href = a.getAttribute('href');
    const tab = TAB_MAP[href];
    if (tab && window.parent !== window) {
      e.preventDefault();
      e.stopPropagation();
      window.parent.postMessage({ type: 'switchTab', tab }, '*');
    }
  }, true);
})();
