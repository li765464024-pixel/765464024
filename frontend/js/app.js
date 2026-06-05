/**
 * 复盘工具 — 前端交互逻辑
 * 数据来源: 静态分析(section_html) + 实时爬虫(API)
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

function switchBoardTab(tab) {
  qa('.board-tab').forEach(function(t) { t.classList.remove('active'); });
  qa('.board-table-wrap').forEach(function(t) { t.style.display = 'none'; });
  var tabEl = q('.board-tab[data-board="' + tab + '"]');
  if (tabEl) tabEl.classList.add('active');
  var boardEl = document.getElementById('board-' + tab);
  if (boardEl) boardEl.style.display = 'block';
  
  // 更新晋级率显示
  updateRateDisplay(tabEl);
}

function updateRateDisplay(tabEl) {
  var display = document.getElementById('rate-display');
  if (!display || !tabEl) return;
  
  var from = parseInt(tabEl.getAttribute('data-rate-from'));
  var to = parseInt(tabEl.getAttribute('data-rate-to'));
  var pct = parseFloat(tabEl.getAttribute('data-rate-pct'));
  var label = tabEl.getAttribute('data-rate-label');
  if (!label) { display.textContent = ''; return; }
  
  var nextMap = {'一':'二','二':'三','三':'四','四':'五','五':'六'};
  var nextLabel = nextMap[label] || '';
  
  if (from <= 0) {
    display.textContent = label + '→' + nextLabel + ': -';
  } else {
    display.textContent = label + '→' + nextLabel + ': ' + to + '/' + from + '=' + pct.toFixed(1) + '%';
  }
}

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
          av = parseFloat(av) || 0; bv = parseFloat(bv) || 0;
          return isAsc ? av - bv : bv - av;
        });
        tbody.innerHTML = '';
        rows.forEach(function(r) { tbody.appendChild(r); });
      });
    });
  });
}

// ════════════════════════════════════════════
// 刷新数据按钮
// ════════════════════════════════════════════

function refreshData() {
  q('#refresh-btn').textContent = '⏳ 刷新中...';
  q('#refresh-btn').disabled = true;
  fetch(API_BASE + '/market/refresh', {method: 'POST'})
    .then(r => r.json())
    .then(d => {
      if (d.ok) {
        q('#refresh-btn').textContent = '✅ ' + d.message;
        setTimeout(function() {
          q('#refresh-btn').textContent = '🔄 刷新数据';
          q('#refresh-btn').disabled = false;
          location.reload();
        }, 1500);
      } else {
        q('#refresh-btn').textContent = '❌ 刷新失败';
        setTimeout(function() {
          q('#refresh-btn').textContent = '🔄 刷新数据';
          q('#refresh-btn').disabled = false;
        }, 2000);
      }
    })
    .catch(function() {
      q('#refresh-btn').textContent = '❌ 请求失败';
      setTimeout(function() {
        q('#refresh-btn').textContent = '🔄 刷新数据';
        q('#refresh-btn').disabled = false;
      }, 2000);
    });
}

// ════════════════════════════════════════════
// 初始化
// ════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', async function() {
  try {
    // 1. Header
    var marketRes = await apiGet('/market/today');
    var todayStr = '';
    if (marketRes.ok) {
      todayStr = marketRes.data.date || '';
      q('#header-date').textContent = todayStr;
      var meta = q('#header-meta');
      if (meta) {
        meta.innerHTML = todayStr + ' 收盘数据 | 涨停' + marketRes.data.zt_count + ' · 跌停' + marketRes.data.dt_count + ' | 点击🔄刷新实时爬取';
      }
    }

    // 2. 加载 section HTML (静态分析页面)
    var sectionsRes = await apiGet('/sections/all');
    var loadedCount = 0;
    if (sectionsRes.ok && sectionsRes.data) {
      Object.keys(sectionsRes.data).forEach(function(sid) {
        var sec = sectionsRes.data[sid];
        var el = document.getElementById(sid);
        if (el && sec.html) {
          el.innerHTML = sec.html;
          loadedCount++;
        }
      });
    }
    console.log('已加载 ' + loadedCount + ' 个板块 (静态分析)');

    // 3. 重新绑定排序
    setupTableSorting();
    
    // 4. 初始化晋级率显示 (默认一板)
    var defaultTab = q('.board-tab.active');
    if (defaultTab) {
      updateRateDisplay(defaultTab);
    }

    // 4. 更新 header 显示最新数据日期
    var versionsRes = await apiGet('/data/versions');
    if (versionsRes.ok && versionsRes.data) {
      var dates = versionsRes.data;
      if (dates.length > 0) {
        q('#header-date').textContent = dates[0];
      }
    }

  } catch (e) {
    console.error('加载失败:', e);
    qa('.section').forEach(function(s) {
      if (s.innerHTML.indexOf('loading') >= 0 || s.innerHTML.indexOf('spinner') >= 0) {
        s.innerHTML = '<div class="card"><div class="error-msg">⚠️ 加载失败，请确认后端已启动</div></div>';
      }
    });
  }
});
