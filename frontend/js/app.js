/**
 * 复盘工具 — 前端交互逻辑
 * 从后端 API 加载原始 HTML 内容，1:1 渲染
 */
const API_BASE = 'http://localhost:5500/api';

// ════════════════════════════════════════════
// 工具函数
// ════════════════════════════════════════════

async function apiGet(path) {
  const resp = await fetch(`${API_BASE}${path}`);
  return resp.json();
}

function q(sel) { return document.querySelector(sel); }
function qa(sel) { return document.querySelectorAll(sel); }

// ════════════════════════════════════════════
// Tab 切换
// ════════════════════════════════════════════

function switchTab(id) {
  qa('.section').forEach(s => s.classList.remove('active'));
  qa('.tab').forEach(t => t.classList.remove('active'));
  var el = document.getElementById(id);
  if (el) el.classList.add('active');
  if (event && event.target) event.target.classList.add('active');
}

// ════════════════════════════════════════════
// Board Tab 切换 (需要重绑定时用)
// ════════════════════════════════════════════

function switchBoardTab(tab) {
  qa('.board-tab').forEach(function(t) { t.classList.remove('active'); });
  qa('.board-table-wrap').forEach(function(t) { t.style.display = 'none'; });
  var tabEl = q('.board-tab[data-board="' + tab + '"]');
  if (tabEl) tabEl.classList.add('active');
  var boardEl = document.getElementById('board-' + tab);
  if (boardEl) boardEl.style.display = 'block';
}

// ════════════════════════════════════════════
// 表格排序 (注入 HTML 后需要重新绑定)
// ════════════════════════════════════════════

function setupTableSorting() {
  qa('.board-table-wrap table').forEach(function(table) {
    var headers = table.querySelectorAll('.sort-header');
    headers.forEach(function(header) {
      header.addEventListener('click', function() {
        var col = this.getAttribute('data-sort');
        if (col === 'none') return;
        var tbody = table.querySelector('tbody');
        if (!tbody) return;
        var rows = Array.from(tbody.querySelectorAll('tr'));
        if (rows.length === 0) return;

        var isAsc = this.classList.contains('asc');
        headers.forEach(function(h) { h.classList.remove('asc', 'desc'); });
        this.classList.add(isAsc ? 'desc' : 'asc');

        rows.sort(function(a, b) {
          var av = (a.getAttribute('data-sort-' + col) || '').replace(/[^0-9.\-]/g, '');
          var bv = (b.getAttribute('data-sort-' + col) || '').replace(/[^0-9.\-]/g, '');
          if (col === 'reason' || col === 'sector' || col === 'time') {
            av = (a.getAttribute('data-sort-' + col) || '');
            bv = (b.getAttribute('data-sort-' + col) || '');
            return isAsc ? av.localeCompare(bv) : bv.localeCompare(av);
          }
          av = parseFloat(av) || 0;
          bv = parseFloat(bv) || 0;
          return isAsc ? av - bv : bv - av;
        });

        tbody.innerHTML = '';
        rows.forEach(function(r) { tbody.appendChild(r); });
      });
    });
  });
}

// ════════════════════════════════════════════
// 初始化：加载所有 section 的 HTML
// ════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', async function() {
  try {
    // 1. 获取 header 信息
    var marketRes = await apiGet('/market/today');
    if (marketRes.ok) {
      q('#header-date').textContent = marketRes.data.date || '';
      var meta = q('#header-meta');
      if (meta) {
        meta.innerHTML = marketRes.data.date + ' 收盘数据 | 涨停' + marketRes.data.zt_count + ' · 跌停' + marketRes.data.dt_count + ' | 数据来源：同花顺+东方财富+韭研公社+财联社';
      }
    }

    // 2. 加载所有 section HTML (1:1 还原)
    var sectionsRes = await apiGet('/sections/all');
    if (sectionsRes.ok && sectionsRes.data) {
      var count = 0;
      Object.keys(sectionsRes.data).forEach(function(sid) {
        var sec = sectionsRes.data[sid];
        var el = document.getElementById(sid);
        if (el && sec.html) {
          el.innerHTML = sec.html;
          count++;
        }
      });
      console.log('已加载 ' + count + ' 个板块 (1:1还原)');
    }

    // 3. 重新绑定排序（board 表格来自原始 HTML）
    setupTableSorting();

  } catch (e) {
    console.error('加载失败:', e);
    qa('.section').forEach(function(s) {
      if (s.innerHTML.indexOf('loading') >= 0 || s.innerHTML.indexOf('spinner') >= 0) {
        s.innerHTML = '<div class="card"><div class="error-msg">⚠️ 加载失败，请确认后端已启动</div></div>';
      }
    });
  }
});
