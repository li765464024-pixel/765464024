/**
 * 复盘工具 — 前端交互逻辑
 * 支持日期切换: header日期选择器切换历史数据
 */
const API_BASE = 'http://localhost:5500/api';
var currentDate = '';

async function apiGet(path) {
  const resp = await fetch(API_BASE + path);
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

// ════════════════════════════════════════════
// 表格排序
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
// 刷新数据
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
// 日期选择器
// ════════════════════════════════════════════

async function switchDate(dateStr) {
  if (!dateStr || dateStr === currentDate) return;
  currentDate = dateStr;
  q('#header-date').textContent = dateStr;
  
  // 显示加载状态（s3 除外，它自己加载）
  qa('.section').forEach(function(s) {
    if (s.id === 's3') return;
    s.innerHTML = '<div class="loading"><div class="spinner"></div><div>加载 ' + dateStr + ' 数据...</div></div>';
  });
  
  // 1. 加载该日期的 section HTML
  var sectionsRes = await apiGet('/sections/all?date=' + dateStr);
  if (sectionsRes.ok && sectionsRes.data) {
    var count = 0;
    Object.keys(sectionsRes.data).forEach(function(sid) {
      if (sid === 's3') return; // 跳过 s3，由 v2 API 渲染
      var sec = sectionsRes.data[sid];
      var el = document.getElementById(sid);
      if (el && sec.html) {
        el.innerHTML = sec.html;
        count++;
      }
    });
  }
  
  // 2. 更新header meta
  var marketRes = await apiGet('/market/today?date=' + dateStr);
  if (marketRes.ok) {
    var m = marketRes.data;
    var meta = q('#header-meta');
    if (meta) {
      meta.innerHTML = dateStr + ' | 涨停' + (m.zt_count || '?') + ' · 跌停' + (m.dt_count || '?') + ' | 历史数据查看';
    }
  }
  
  // 3. 重新绑定 + 刷新 s3 排行榜
  setupTableSorting();
  s3refreshRankings();
}

async function initDateSelector() {
  var sel = document.getElementById('date-selector');
  if (!sel) return;
  
  var versionsRes = await apiGet('/data/versions');
  if (versionsRes.ok && versionsRes.data) {
    sel.innerHTML = '';
    versionsRes.data.forEach(function(d) {
      var opt = document.createElement('option');
      opt.value = d;
      opt.textContent = d;
      sel.appendChild(opt);
    });
    // Select latest
    if (versionsRes.data.length > 0) {
      sel.value = versionsRes.data[0];
      currentDate = versionsRes.data[0];
    }
  }
}

// ════════════════════════════════════════════
// 热门题材与主线题材监控 — 三个排行榜
// ════════════════════════════════════════════

function s3stageColor(stage) {
  var map = {
    '孕育期/预热期': '#6b7280', '启动期': '#22c55e', '爆发期': '#059669',
    '分歧震荡期': '#f59e0b', '退潮期': '#ef4444', '余温反复/二波观察期': '#8b5cf6',
  };
  return map[stage] || '#6b7280';
}

function s3riskBadge(level) {
  if (level === 'critical') return '<span class="tag r">高危</span>';
  if (level === 'warning') return '<span class="tag y">警告</span>';
  return '<span class="tag b">正常</span>';
}

function s3formatPct(v) {
  if (v == null || v === 0) return '-';
  var s = v > 0 ? '+' : '';
  return s + Number(v).toFixed(1) + '%';
}

function s3formatNum(v) {
  if (v == null || v === 0) return '-';
  return Number(v).toFixed(1);
}

async function s3refreshRankings() {
  var btn = document.getElementById('s3-btn-refresh');
  var status = document.getElementById('s3-data-status');
  if (btn) { btn.textContent = '⏳ 刷新中...'; btn.disabled = true; }
  if (status) status.textContent = '正在获取排行榜数据...';
  
  var date = (document.getElementById('s3-filter-date') && document.getElementById('s3-filter-date').value) || new Date().toISOString().slice(0, 10);
  
  try {
    var res = await fetch(API_BASE + '/v2/hot-topics/rankings?date=' + date);
    var data = await res.json();
    
    if (data.ok && data.data) {
      renderHotRankings(data.data.hot_rankings || []);
      renderMainlineRankings(data.data.mainline_rankings || []);
      renderCombinedRankings(data.data.combined_rankings || []);
      if (status) status.textContent = '✅ 已更新 ' + date;
      if (btn) {
        btn.textContent = '✅ 完成';
        setTimeout(function() { btn.textContent = '🔄 刷新排行榜'; btn.disabled = false; }, 1500);
      }
    } else {
      if (status) status.textContent = '❌ ' + (data.error || '获取失败');
      if (btn) { btn.textContent = '❌ 失败'; setTimeout(function() { btn.textContent = '🔄 刷新排行榜'; btn.disabled = false; }, 2000); }
    }
  } catch (e) {
    if (status) status.textContent = '❌ 请求失败';
    if (btn) { btn.textContent = '❌ 失败'; setTimeout(function() { btn.textContent = '🔄 刷新排行榜'; btn.disabled = false; }, 2000); }
  }
}

function renderHotRankings(data) {
  var tbody = document.getElementById('s3-hot-tbody');
  if (!tbody) return;
  
  if (!data || data.length === 0) {
    tbody.innerHTML = '<tr><td colspan="9" class="empty-msg">暂无数据，请点击"刷新排行榜"</td></tr>';
    return;
  }
  
  var html = '';
  data.forEach(function(r) {
    var cls = r.rank <= 3 ? ' style="font-weight:700"' : '';
    html += '<tr' + cls + '>';
    html += '<td><span class="' + (r.rank <= 3 ? 'tag r' : '') + '">' + r.rank + '</span></td>';
    html += '<td><strong>' + (r.topic_name || '') + '</strong></td>';
    html += '<td><strong>' + (r.heat_score != null ? r.heat_score : '-') + '</strong></td>';
    html += '<td>' + (r.jygs_heat != null ? r.jygs_heat : '-') + '</td>';
    html += '<td>' + (r.xueqiu_heat != null ? r.xueqiu_heat : '-') + '</td>';
    html += '<td>' + (r.eastmoney_heat != null ? r.eastmoney_heat : '-') + '</td>';
    html += '<td>' + (r.ths_heat != null ? r.ths_heat : '-') + '</td>';
    html += '<td class="' + (r.heat_change_3d > 0 ? 'up' : (r.heat_change_3d < 0 ? 'dn' : '')) + '">' + s3formatPct(r.heat_change_3d) + '</td>';
    html += '<td>' + (r.representative_stocks || '-') + '</td>';
    html += '</tr>';
  });
  tbody.innerHTML = html;
}

function renderMainlineRankings(data) {
  var tbody = document.getElementById('s3-mainline-tbody');
  if (!tbody) return;
  
  if (!data || data.length === 0) {
    tbody.innerHTML = '<tr><td colspan="10" class="empty-msg">暂无数据，请点击"刷新排行榜"</td></tr>';
    return;
  }
  
  var html = '';
  data.forEach(function(r) {
    var color = s3stageColor(r.lifecycle_stage);
    html += '<tr>';
    html += '<td><span class="' + (r.rank <= 3 ? 'tag r' : '') + '">' + r.rank + '</span></td>';
    html += '<td><strong>' + (r.topic_name || '') + '</strong></td>';
    html += '<td><strong>' + (r.mainline_strength_score != null ? r.mainline_strength_score : '-') + '</strong></td>';
    html += '<td>' + s3formatPct(r.board_change_5d) + '</td>';
    html += '<td>' + s3formatPct(r.board_change_10d) + '</td>';
    html += '<td>' + s3formatNum(r.turnover_5d) + '亿</td>';
    html += '<td>' + (r.limit_up_count_5d || 0) + '</td>';
    html += '<td>' + (r.leader_stock || '-') + (r.leader_board ? '(' + r.leader_board + '板)' : '') + '</td>';
    html += '<td>' + (r.leader_board || 0) + '</td>';
    html += '<td><span class="stage-badge" style="background:' + color + '20;color:' + color + ';border:1px solid ' + color + ';font-size:11px">' + (r.lifecycle_stage || '未知') + '</span></td>';
    html += '</tr>';
  });
  tbody.innerHTML = html;
}

function renderCombinedRankings(data) {
  var tbody = document.getElementById('s3-combined-tbody');
  if (!tbody) return;
  
  if (!data || data.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" class="empty-msg">暂无数据，请点击"刷新排行榜"</td></tr>';
    return;
  }
  
  var html = '';
  data.forEach(function(r) {
    var color = s3stageColor(r.lifecycle_stage);
    html += '<tr onclick="window.open(\'/topic-detail.html?id=' + (r.topic_id || '') + '\',\'_blank\')" style="cursor:pointer">';
    html += '<td><span class="' + (r.rank <= 3 ? 'tag r' : '') + '">' + r.rank + '</span></td>';
    html += '<td><strong>' + (r.topic_name || '') + '</strong></td>';
    html += '<td><strong>' + (r.total_score != null ? r.total_score : '-') + '</strong></td>';
    html += '<td>' + (r.heat_score != null ? r.heat_score : '-') + '</td>';
    html += '<td>' + (r.mainline_strength_score != null ? r.mainline_strength_score : '-') + '</td>';
    html += '<td><span class="stage-badge" style="background:' + color + '20;color:' + color + ';border:1px solid ' + color + ';font-size:11px">' + (r.lifecycle_stage || '未知') + '</span></td>';
    html += '<td>' + s3riskBadge(r.risk_level || 'none') + '</td>';
    html += '<td>' + (r.leader_stock || '-') + '</td>';
    html += '</tr>';
  });
  tbody.innerHTML = html;
}

function closeTopicDetail() {
  var modal = document.getElementById('topic-detail-modal');
  if (modal) modal.style.display = 'none';
}
// ════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', async function() {
  try {
    // 1. 初始化日期选择器
    await initDateSelector();
    
    // 2. Header
    var marketRes = await apiGet('/market/today');
    if (marketRes.ok) {
      var m = marketRes.data;
      q('#header-date').textContent = m.date || currentDate;
      var meta = q('#header-meta');
      if (meta) {
        meta.innerHTML = (m.date || '') + ' | 涨停' + (m.zt_count || '?') + ' · 跌停' + (m.dt_count || '?') + ' | 点击🔄刷新实时爬取';
      }
    }

    // 3. 加载 section HTML（跳过 s3）
    var sectionsRes = await apiGet('/sections/all');
    var loadedCount = 0;
    if (sectionsRes.ok && sectionsRes.data) {
      Object.keys(sectionsRes.data).forEach(function(sid) {
        if (sid === 's3') return; // s3 由 v2 API 渲染
        var sec = sectionsRes.data[sid];
        var el = document.getElementById(sid);
        if (el && sec.html) {
          el.innerHTML = sec.html;
          loadedCount++;
        }
      });
    }

    // 4. 重新绑定排序 + 晋级率
    setupTableSorting();
    var defaultTab = q('.board-tab.active');
    if (defaultTab) updateRateDisplay(defaultTab);

    // 5. 初始化 s3 热门题材排行榜
    var dateInput = document.getElementById('s3-filter-date');
    if (dateInput) {
      dateInput.value = new Date().toISOString().slice(0, 10);
      dateInput.addEventListener('change', function() { s3refreshRankings(); });
    }
    
    s3refreshRankings();

  } catch (e) {
    console.error('加载失败:', e);
    qa('.section').forEach(function(s) {
      if (s.innerHTML.indexOf('loading') >= 0 || s.innerHTML.indexOf('spinner') >= 0) {
        s.innerHTML = '<div class="card"><div class="error-msg">⚠️ 加载失败，请确认后端已启动</div></div>';
      }
    });
  }
});
