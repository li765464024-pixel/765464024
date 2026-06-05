/**
 * 复盘工具 — 前端交互逻辑
 * 动态从后端 API 加载数据，渲染各版块
 */
const API_BASE = 'http://localhost:5000/api';

// ════════════════════════════════════════════
// 工具函数
// ════════════════════════════════════════════

async function apiGet(path) {
  const resp = await fetch(`${API_BASE}${path}`);
  return resp.json();
}

function q(sel) { return document.querySelector(sel); }
function qa(sel) { return document.querySelectorAll(sel); }
function esc(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function fmtPercent(v) {
  v = parseFloat(v);
  return isNaN(v) ? '-' : v.toFixed(1) + '%';
}

function fmtMoney(v) {
  v = parseFloat(v);
  if (isNaN(v)) return '-';
  if (Math.abs(v) >= 1) return v.toFixed(2) + '亿';
  return (v * 10000).toFixed(0) + '万';
}

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
// 初始化 & 加载所有数据
// ════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', async function() {
  // 并行加载各板块数据
  try {
    const [market, sectorsRes, boardSummary, boardOne, boardTwo, boardThree, boardHigher, postsTg, postsJy] = await Promise.all([
      apiGet('/market/today'),
      apiGet('/sectors/hot'),
      apiGet('/board/summary'),
      apiGet('/board/list?board=1'),
      apiGet('/board/list?board=2'),
      apiGet('/board/list?board=3'),
      apiGet('/board/higher'),
      apiGet('/posts?platform=taoguba'),
      apiGet('/posts?platform=jy'),
    ]);

    if (market.ok) renderMarket(market.data);
    if (sectorsRes.ok) renderSectors(sectorsRes.data);
    if (boardSummary.ok) renderBoardSummary(boardSummary.data);
    if (boardOne.ok) renderBoardTable('board-one', boardOne.data, '一板');
    if (boardTwo.ok) renderBoardTable('board-two', boardTwo.data, '二板');
    if (boardThree.ok) renderBoardTable('board-three', boardThree.data, '三板');
    if (boardHigher.ok) renderBoardTable('board-higher', boardHigher.data, '更高');
    if (postsTg.ok) renderPosts(postsTg.data, 'taoguba');
    if (postsJy.ok) renderPosts(postsJy.data, 'jy');

    // Attach board tab switching
    setupBoardTabs();
    // Attach table sorting
    setupTableSorting();

  } catch(e) {
    console.error('数据加载失败:', e);
    qa('.section').forEach(s => {
      if (!s.querySelector('.card')) {
        s.innerHTML += '<div class="error-msg">⚠️ 加载失败，请确认后端已启动</div>';
      }
    });
  }
});

// ════════════════════════════════════════════
// 大盘概况 (s1)
// ════════════════════════════════════════════

function renderMarket(data) {
  const s1 = document.getElementById('s1');
  if (!s1) return;
  s1.innerHTML = `
    <h2>📈 大盘概况 <span style="font-size:11px;color:var(--muted);font-weight:normal">${data.date || ''}</span></h2>
    <div class="grid2">
      <div class="stat"><div class="v" style="color:var(--gold)">${esc(data.sentiment || '—')}</div><div class="l">市场情绪</div></div>
      <div class="stat"><div class="v" style="color:var(--red)">${data.zt_count || 0}</div><div class="l">涨停家数</div></div>
      <div class="stat"><div class="v" style="color:var(--green)">${data.dt_count || 0}</div><div class="l">跌停家数</div></div>
      <div class="stat"><div class="v" style="color:var(--green)">${esc(data.main_inflow || '-')}</div><div class="l">主力净额</div></div>
      <div class="stat"><div class="v" style="color:var(--blue)">${data.max_board || 0}板</div><div class="l">连板高度</div></div>
      <div class="stat"><div class="v" style="color:var(--gold)">${fmtPercent(data.seal_rate)}</div><div class="l">封板率</div></div>
      <div class="stat"><div class="v" style="color:var(--red)">${data.up_count || 0}</div><div class="l">上涨家数</div></div>
      <div class="stat"><div class="v" style="color:var(--green)">${data.down_count || 0}</div><div class="l">下跌家数</div></div>
    </div>
    <div class="bl-blue" style="margin-top:12px;font-size:12px">
      <strong>📌 最高板：</strong>${esc(data.max_board_stocks || '—')} | 成交额：${esc(data.volume || '—')} | 温度：${data.temperature || '—'}
    </div>
  `;
}

// ════════════════════════════════════════════
// 板块热度 (s2)
// ════════════════════════════════════════════

function renderSectors(data) {
  const s2 = document.getElementById('s2');
  if (!s2) return;
  let rows = data.map(s => `
    <tr>
      <td><span class="chip chip-up">${esc(s.name)}</span></td>
      <td><strong>${s.zt_count || 0}</strong></td>
      <td style="font-size:11px">${esc(s.core_logic || '')}</td>
      <td><span class="tag r">${esc(s.stage || '')}</span></td>
      <td>${esc(s.leader || '')}</td>
    </tr>
  `).join('');

  s2.innerHTML = `
    <h2>🔥 板块热度 <span style="font-size:11px;color:var(--muted);font-weight:normal">同花顺实时数据</span></h2>
    <div class="card">
      <h3>板块全景</h3>
      <table>
        <tr><th>板块</th><th>涨停数</th><th>核心逻辑</th><th>阶段</th><th>龙头</th></tr>
        ${rows}
      </table>
    </div>
  `;
}

// ════════════════════════════════════════════
// 连板晋级率 (s7 - 顶部)
// ════════════════════════════════════════════

function renderBoardSummary(data) {
  const summaryDiv = document.getElementById('board-summary-data');
  if (!summaryDiv) return;
  let rows = data.map(s => {
    let cls = (s.promotion_rate || 0) < 20 ? 'dn' : (s.promotion_rate || 0) > 50 ? 'up' : 'ne';
    return `<div class="rate-stat"><span class="rate-value">${fmtPercent(s.promotion_rate)}</span><span class="rate-detail">${s.board_num}进${s.board_num+1}</span></div>`;
  }).join('');
  summaryDiv.innerHTML = rows;
}

// ════════════════════════════════════════════
// 连板个股表 (s7 - board tables)
// ════════════════════════════════════════════

function renderBoardTable(containerId, stocks, label) {
  const container = document.getElementById(containerId);
  if (!container) return;
  
  if (!stocks || stocks.length === 0) {
    container.innerHTML = '<div class="empty-msg">暂无数据</div>';
    return;
  }

  container.innerHTML = `
    <table class="sortable">
      <thead><tr>
        <th data-sort="none" style="min-width:100px">股票名称</th>
        <th data-sort="price" class="sort-header">价格 <span class="sort-icon">↕</span></th>
        <th data-sort="time" class="sort-header">涨停时间 <span class="sort-icon">↕</span></th>
        <th data-sort="reason" class="sort-header">涨停原因 <span class="sort-icon">↕</span></th>
        <th data-sort="limit" class="sort-header">封单 <span class="sort-icon">↕</span></th>
        <th data-sort="sector" class="sort-header">板块 <span class="sort-icon">↕</span></th>
        <th data-sort="turnover" class="sort-header">换手 <span class="sort-icon">↕</span></th>
      </tr></thead>
      <tbody>
        ${stocks.map(s => {
          let tag = s.board_tag || (s.board_num + '板');
          return `<tr data-sort-price="${s.price||0}" data-sort-time="${s.seal_time||''}" 
                       data-sort-limit="${s.seal_amount||0}" data-sort-sector="${esc(s.sector||'')}"
                       data-sort-turnover="${s.turnovers||0}" data-sort-reason="${esc(s.reason||'')}">
            <td>${esc(s.name)}<br><span class="board-days-tag">${tag}</span></td>
            <td>${s.price || '-'}</td>
            <td>${s.seal_time||''}</td>
            <td style="font-size:11px">${esc(s.reason||'')}</td>
            <td>${fmtMoney(s.seal_amount)}</td>
            <td>${esc(s.sector||'')}</td>
            <td>${s.turnovers ? s.turnovers + '%' : '-'}</td>
          </tr>`;
        }).join('')}
      </tbody>
    </table>
  `;
}

// ════════════════════════════════════════════
// 社区帖子 (s5 taoguba, s6 jy)
// ════════════════════════════════════════════

function renderPosts(posts, platform) {
  const prefix = platform === 'taoguba' ? 's5' : 's6';
  const container = document.getElementById(prefix);
  if (!container) return;

  const dirCounts = {看多:0, 看空:0, 中性:0};
  posts.forEach(p => { if (dirCounts[p.direction] !== undefined) dirCounts[p.direction]++; });

  let cards = posts.map(p => {
    let dirClass = p.direction === '看多' ? 'r' : p.direction === '看空' ? 'g' : 'b';
    return `<div class="card">
      <h3>${esc(p.title)} <span class="tag ${dirClass}">${esc(p.direction)}</span></h3>
      ${p.content ? `<div class="bl-gold" style="font-size:12px">${esc(p.content)}</div>` : ''}
      ${p.author ? `<div style="font-size:11px;color:var(--muted);margin-top:6px">✍️ ${esc(p.author)}</div>` : ''}
    </div>`;
  }).join('');

  const platformName = platform === 'taoguba' ? '淘股吧' : '韭研公社';
  container.innerHTML = `
    <h2>${platform === 'taoguba' ? '🐂' : '🔬'} ${platformName}视角 <span style="font-size:11px;color:var(--muted);font-weight:normal">共${posts.length}帖</span></h2>
    <div class="grid2" style="margin-bottom:12px">
      <div class="stat"><div class="v" style="color:var(--red)">${dirCounts.看多}看多</div></div>
      <div class="stat"><div class="v" style="color:var(--green)">${dirCounts.看空}看空</div></div>
      <div class="stat"><div class="v" style="color:var(--blue)">${dirCounts.中性}中性</div></div>
    </div>
    ${cards}
  `;
}

// ════════════════════════════════════════════
// Board Tab 切换
// ════════════════════════════════════════════

function setupBoardTabs() {
  qa('.board-tab').forEach(tab => {
    tab.addEventListener('click', function() {
      qa('.board-tab').forEach(t => t.classList.remove('active'));
      qa('.board-table-wrap').forEach(w => w.style.display = 'none');
      this.classList.add('active');
      var target = document.getElementById('board-' + this.getAttribute('data-board'));
      if (target) target.style.display = 'block';
    });
  });
}

// ════════════════════════════════════════════
// 表格排序
// ════════════════════════════════════════════

function setupTableSorting() {
  qa('.board-table-wrap table').forEach(table => {
    var headers = table.querySelectorAll('.sort-header');
    headers.forEach(header => {
      header.addEventListener('click', function() {
        var col = this.getAttribute('data-sort');
        if (col === 'none') return;
        var tbody = table.querySelector('tbody');
        if (!tbody) return;
        var rows = Array.from(tbody.querySelectorAll('tr'));
        if (rows.length === 0) return;
        
        var isAsc = this.classList.contains('asc');
        headers.forEach(h => h.classList.remove('asc', 'desc'));
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
        rows.forEach(r => tbody.appendChild(r));
      });
    });
  });
}
