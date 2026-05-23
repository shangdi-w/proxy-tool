// ══════════════════════════════════════
// Proxy Pool Dashboard — App Logic
// ══════════════════════════════════════

let refreshTimer = null;
let rotatorTimer = null;
let autoScrapeTimer = null;

const STATUS_MAP = { alive: '存活', dead: '失效', unknown: '未知' };
const ANONYMITY_MAP = { elite: '高匿', anonymous: '匿名', transparent: '透明' };
const SOURCE_MAP = { 'proxyscrape': 'ProxyScrape', 'geonode': 'GeoNode', 'free-proxy-list': 'FreeProxyList', 'proxy-list.download': 'ProxyDL', 'github-speedx': 'SpeedX', 'openproxy': 'OpenProxy', 'kuaidaili': '快代理', '89ip': '89ip', 'ihuan': '小幻', 'fate0': 'fate0', 'aliilapro': 'AliiLaPro', 'monosans': 'monosans', 'roosterkid': 'Rooster', 'hookzof': 'Hookzof', 'speedx-socks': 'SpeedX-SOCKS', 'jetkai': 'JetKai', 'sunny9577': 'Sunny', 'mmpx12': 'mmpx12', 'pubproxy': 'PubProxy', 'proxifly': 'ProxiFly', 'muhamed77': 'Muhamed', 'clarketm': 'Clarke', 'hyperreality': 'Hyper', 'themiralay': 'MiRALAY' };

// ── API helper ──
function api(path, opts = {}) {
  return fetch(path, opts).then(r => r.json()).catch(e => {
    console.error('API:', e);
    return null;
  });
}

// ── Toast notifications ──
function toast(msg, type = 'info', duration = 3000) {
  const container = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className = `toast-msg ${type}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => {
    el.classList.add('toast-out');
    setTimeout(() => el.remove(), 200);
  }, duration);
}

// ── Stats cards with history ──
let statsHistory = { total: [], alive: [], dead: [], latency: [] };

async function loadStats() {
  const data = await api('/api/stats');
  if (!data) return;
  updateStat('stat-total', data.total || 0);
  updateStat('stat-alive', data.alive || 0);
  updateStat('stat-dead', data.dead || 0);
  updateStat('stat-elite', data.elite_count ?? '-');
  updateStat('stat-connect', data.connect_count ?? '-');

  // Latency with color warning
  const lat = data.avg_latency || 0;
  const latEl = document.getElementById('stat-latency');
  latEl.textContent = lat > 0 ? lat.toFixed(0) + 'ms' : '-';
  latEl.style.color = lat > 2000 ? 'var(--danger)' : lat > 1000 ? 'var(--warning)' : 'var(--text-primary)';

  // Track history (last 20 points)
  const now = Date.now();
  ['total', 'alive', 'dead', 'latency'].forEach(k => {
    statsHistory[k].push({ t: now, v: data[k] || data['avg_latency'] || 0 });
    if (statsHistory[k].length > 20) statsHistory[k].shift();
  });

  // Render sparklines
  renderSparklines();
}

function renderSparklines() {
  const keys = ['total', 'alive', 'dead'];
  keys.forEach(k => {
    const el = document.getElementById('spark-' + k);
    if (!el) return;
    const vals = statsHistory[k].map(p => p.v);
    const max = Math.max(...vals, 1);
    el.innerHTML = vals.map(v => {
      const h = Math.max(2, (v / max) * 100);
      return `<span class="bar" style="height:${h}%"></span>`;
    }).join('');
  });
}

function updateStat(id, val) {
  document.getElementById(id).textContent = val;
}

// ── Countries ──
async function loadCountries() {
  const data = await api('/api/countries');
  if (!data) return;
  const pairs = [['filter-country', '全部'], ['rotator-country', '不限'], ['group-country', '不限']];
  pairs.forEach(([selId, first]) => {
    const sel = document.getElementById(selId);
    const cur = sel.value;
    sel.innerHTML = `<option value="">${first}</option>`;
    data.forEach(c => { sel.innerHTML += `<option value="${c}">${c}</option>`; });
    sel.value = cur;
  });
}

// ── Active filter tags ──
let activeTags = {};

function setTag(key, label, value) {
  activeTags[key] = { label, value, key };
  renderActiveTags();
}

function removeTag(key) {
  delete activeTags[key];
  // Reset the corresponding filter
  if (key === 'protocol') document.getElementById('filter-protocol').value = '';
  if (key === 'country') document.getElementById('filter-country').value = '';
  if (key === 'status') document.getElementById('filter-status').value = 'alive';
  if (key === 'latency') document.getElementById('filter-latency').value = '0';
  if (key === 'anonymity') { /* handled via quickFilter */ }
  if (key === 'quick') { /* clear all */ }
  if (key === 'scene') { /* clear all */ }
  renderActiveTags();
  loadProxies();
}

function clearAllFilters() {
  activeTags = {};
  document.getElementById('filter-protocol').value = '';
  document.getElementById('filter-country').value = '';
  document.getElementById('filter-status').value = 'alive';
  document.getElementById('filter-latency').value = '0';
  document.getElementById('filter-sort').value = 'latency';
  document.getElementById('filter-limit').value = '200';
  renderActiveTags();
  loadProxies();
}

function renderActiveTags() {
  const container = document.getElementById('active-filters');
  const entries = Object.values(activeTags);
  if (!entries.length) {
    container.innerHTML = '';
    return;
  }
  container.innerHTML = entries.map(t =>
    `<span class="filter-tag">${t.label}<span class="tag-close" onclick="removeTag('${t.key}')">&times;</span></span>`
  ).join('');
}

// ── Proxy list ──
async function loadProxies() {
  const maxLatency = document.getElementById('filter-latency').value;
  const params = new URLSearchParams({
    protocol: document.getElementById('filter-protocol').value,
    country: document.getElementById('filter-country').value,
    status: document.getElementById('filter-status').value,
    sort_by: document.getElementById('filter-sort').value,
    limit: document.getElementById('filter-limit').value
  });
  if (maxLatency > 0) params.set('max_latency', maxLatency);
  const data = await api('/api/proxies?' + params);
  renderProxyTable(data);
}

function copyProxy(str) {
  navigator.clipboard.writeText(str).then(() => toast('已复制: ' + str, 'success'));
}

// ── Table rendering ──
function renderProxyTable(data) {
  const tbody = document.getElementById('proxy-tbody');
  const statusDiv = document.getElementById('table-status');

  if (!data || !data.length) {
    tbody.innerHTML = '<tr><td colspan="10" class="text-center py-4" style="color:var(--text-disabled)">没有找到代理</td></tr>';
    statusDiv.textContent = '0 条结果';
    return;
  }

  const vis = getColumnVisibility();

  tbody.innerHTML = data.map(p => {
    const isDead = p.status === 'dead';
    const rowClass = isDead ? 'dead-row' : '';

    const protoBadge = (p.protocol || 'http').toUpperCase();
    const protoColor = p.protocol === 'socks5' ? 'bg-primary' : p.protocol === 'socks4' ? 'bg-info' : 'bg-secondary';
    const proxyStr = p.ip + ':' + p.port;

    // Latency with thresholds
    const latVal = p.latency > 0 ? p.latency.toFixed(0) + 'ms' : '-';
    let latClass = 'latency-ok';
    if (p.latency > 1000) latClass = 'latency-high';
    else if (p.latency > 500) latClass = 'latency-warn';

    // Score
    const score = p.score || 0;
    let scoreClass = 'score-high';
    if (score < 40) scoreClass = 'score-low';
    else if (score < 70) scoreClass = 'score-mid';

    const anonText = ANONYMITY_MAP[p.anonymity] || p.anonymity || '-';
    const statusText = STATUS_MAP[p.status] || p.status;
    const statusClass = p.status === 'alive' ? 'badge-alive' : p.status === 'dead' ? 'badge-dead' : 'badge-unknown';
    const sourceText = SOURCE_MAP[p.source] || p.source || '-';
    const proxyUrl = (p.protocol === 'socks5' ? 'socks5h://' : p.protocol + '://') + p.ip + ':' + p.port;

    return `<tr class="${rowClass}" data-proxy-id="${p.id}" data-proxy-addr="${proxyStr}" data-proxy-url="${proxyUrl}">
      <td><input type="checkbox" class="proxy-check" data-id="${p.id}" onchange="updateBatchBar()" onclick="event.stopPropagation()"></td>
      <td><code style="font-size:0.8rem">${proxyStr}</code></td>
      <td class="col-protocol"${vis.protocol ? '' : ' style="display:none"'}>
        <span class="badge ${protoColor}">${protoBadge}</span></td>
      <td class="col-country"${vis.country ? '' : ' style="display:none"'}>${p.country || '-'}</td>
      <td class="${latClass}">${latVal}</td>
      <td class="${scoreClass} fw-bold">${score.toFixed(0)}</td>
      <td class="col-anonymity"${vis.anonymity ? '' : ' style="display:none"'}>
        ${p.anonymity === 'elite' ? '<span class="badge badge-elite">高匿</span>' : anonText}</td>
      <td><span class="badge ${statusClass}">${statusText}</span></td>
      <td class="col-source"${vis.source ? '' : ' style="display:none"'}><small>${sourceText}</small></td>
      <td>
        <i class="bi ${p.favorite ? 'bi-star-fill' : 'bi-star'} copy-btn me-1" title="收藏" onclick="event.stopPropagation(); toggleFavorite(${p.id})" style="color:${p.favorite ? '#F59E0B' : ''}"></i>
        <i class="bi bi-copy copy-btn me-1" title="复制" onclick="event.stopPropagation(); copyProxy('${proxyStr}')"></i>
        <i class="bi bi-pin-angle copy-btn" title="固定" onclick="event.stopPropagation(); pinProxy(${p.id}, '${proxyStr}')" style="color:var(--danger)"></i>
      </td>
    </tr>`;
  }).join('');

  statusDiv.textContent = data.length + ' 条结果';
  updateBatchBar();
}

// ── Column visibility ──
function getColumnVisibility() {
  try {
    return JSON.parse(localStorage.getItem('proxyColumns') || '{"protocol":true,"country":true,"anonymity":true,"source":true}');
  } catch (e) { return { protocol: true, country: true, anonymity: true, source: true }; }
}

function saveColumnVisibility(vis) {
  localStorage.setItem('proxyColumns', JSON.stringify(vis));
}

function toggleColumn(col) {
  const vis = getColumnVisibility();
  vis[col] = !vis[col];
  saveColumnVisibility(vis);
  refreshColumnMenu();
  loadProxies();
}

function toggleColumnMenu() {
  const menu = document.getElementById('col-menu');
  if (menu.classList.contains('d-none')) {
    refreshColumnMenu();
    menu.classList.remove('d-none');
  } else {
    menu.classList.add('d-none');
  }
}

function refreshColumnMenu() {
  const menu = document.getElementById('col-menu');
  const vis = getColumnVisibility();
  const cols = [
    { key: 'protocol', label: '协议' },
    { key: 'country', label: '国家' },
    { key: 'anonymity', label: '匿名度' },
    { key: 'source', label: '来源' },
  ];
  menu.innerHTML = cols.map(c =>
    `<div class="col-toggle-item" onclick="toggleColumn('${c.key}')">
      <i class="bi ${vis[c.key] ? 'bi-check-square' : 'bi-square'}"></i> ${c.label}
    </div>`
  ).join('');

  // Position near the button
  menu.style.top = '48px';
  menu.style.right = '16px';
}

document.addEventListener('click', (e) => {
  const menu = document.getElementById('col-menu');
  if (menu && !e.target.closest('#col-menu') && !e.target.closest('[onclick*="toggleColumnMenu"]')) {
    menu.classList.add('d-none');
  }
});

// ── Batch operations ──
function getSelectedIds() {
  return [...document.querySelectorAll('.proxy-check:checked')].map(cb => parseInt(cb.dataset.id));
}

function updateBatchBar() {
  const ids = getSelectedIds();
  const bar = document.getElementById('batch-bar');
  if (ids.length > 0) {
    bar.classList.remove('d-none');
    document.getElementById('batch-count').textContent = ids.length;
  } else {
    bar.classList.add('d-none');
    document.getElementById('select-all').checked = false;
  }
  updateGroupButtons();
}

function toggleSelectAll(cb) {
  document.querySelectorAll('.proxy-check').forEach(chk => chk.checked = cb.checked);
  updateBatchBar();
}

function clearSelection() {
  document.querySelectorAll('.proxy-check').forEach(chk => chk.checked = false);
  document.getElementById('select-all').checked = false;
  updateBatchBar();
}

async function batchExport(fmt) {
  const ids = getSelectedIds();
  if (!ids.length) { toast('请先选择代理', 'error'); return; }
  const resp = await fetch('/api/export?format=' + fmt, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids })
  });
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  const extMap = { json: 'json', csv: 'csv', txt: 'txt', proxychains: 'conf' };
  a.download = 'proxies.' + (extMap[fmt] || fmt);
  a.click();
  URL.revokeObjectURL(url);
  toast(`已导出 ${ids.length} 个代理`, 'success');
}

async function batchAction(action) {
  const ids = getSelectedIds();
  if (!ids.length) { toast('请先选择代理', 'error'); return; }
  if (action === 'delete' && !confirm(`确认删除 ${ids.length} 个代理？`)) return;
  await api('/api/proxies/batch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids, action })
  });
  clearSelection();
  loadProxies();
  loadStats();
  toast(`${action === 'delete' ? '已删除' : '验证完成'} ${ids.length} 个代理`, 'success');
}

// ── Scene filters ──
function sceneFilter(scene) {
  clearAllFilters();
  if (scene === 'crawler') {
    document.getElementById('filter-protocol').value = 'socks5';
    document.getElementById('filter-latency').value = '2000';
    document.getElementById('filter-sort').value = 'latency';
    document.getElementById('filter-limit').value = '500';
    setTag('scene', '爬虫场景', 'crawler');
  } else if (scene === 'api') {
    document.getElementById('filter-protocol').value = 'http';
    document.getElementById('filter-latency').value = '1000';
    document.getElementById('filter-sort').value = 'score';
    setTag('scene', 'API场景', 'api');
  } else if (scene === 'streaming') {
    document.getElementById('filter-protocol').value = 'socks5';
    document.getElementById('filter-sort').value = 'score';
    document.getElementById('filter-limit').value = '300';
    setTag('scene', '流媒体场景', 'streaming');
    loadProxiesWithFilter({ anonymity: 'elite' });
    return;
  } else if (scene === 'stealth') {
    document.getElementById('filter-protocol').value = 'socks5';
    document.getElementById('filter-latency').value = '3000';
    document.getElementById('filter-sort').value = 'score';
    setTag('scene', '隐身场景', 'stealth');
    loadProxiesWithFilter({ anonymity: 'elite' });
    return;
  }
  loadProxies();
}

// ── Quick filters ──
function quickFilter(tag) {
  clearAllFilters();
  if (tag === 'favorites') {
    setTag('quick', '收藏', 'favorites');
    loadFavoriteProxies();
    return;
  } else if (tag === 'low_latency') {
    document.getElementById('filter-latency').value = '500';
    document.getElementById('filter-sort').value = 'latency';
    setTag('latency', '延迟<500ms', 'low_latency');
  } else if (tag === 'elite') {
    document.getElementById('filter-limit').value = '500';
    setTag('anonymity', '仅高匿', 'elite');
    loadProxiesWithFilter({ anonymity: 'elite' });
    return;
  } else if (tag === 'US' || tag === 'CN') {
    document.getElementById('filter-country').value = tag;
    setTag('country', tag, tag);
  } else if (tag === 'socks5') {
    document.getElementById('filter-protocol').value = 'socks5';
    setTag('protocol', 'SOCKS5', 'socks5');
  }
  loadProxies();
}

async function loadProxiesWithFilter(extra) {
  const maxLatency = document.getElementById('filter-latency').value;
  const params = new URLSearchParams({
    protocol: document.getElementById('filter-protocol').value,
    country: document.getElementById('filter-country').value,
    status: document.getElementById('filter-status').value,
    sort_by: document.getElementById('filter-sort').value,
    limit: document.getElementById('filter-limit').value
  });
  if (maxLatency > 0) params.set('max_latency', maxLatency);
  const data = await api('/api/proxies?' + params);
  if (!data) return;
  let filtered = data;
  if (extra && extra.anonymity) {
    filtered = data.filter(p => p.anonymity === extra.anonymity);
  }
  renderProxyTable(filtered);
}

async function loadFavoriteProxies() {
  const data = await api('/api/favorites');
  if (!data) return;
  renderProxyTable(data);
}

async function toggleFavorite(id) {
  const data = await api('/api/proxies/' + id + '/favorite', { method: 'POST' });
  if (data) {
    toast(data.favorite ? '已收藏' : '已取消收藏', 'info');
    loadProxies();
  }
}

// ── Manual actions ──
async function triggerScrape() {
  const btn = event.target.closest('button');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> 抓取中';
  await api('/api/scrape', { method: 'POST' });
  btn.disabled = false;
  btn.innerHTML = '<i class="bi bi-cloud-download"></i> 抓取';
  toast('抓取完成', 'success');
  loadStats(); loadProxies(); loadCountries();
}

async function triggerValidate() {
  const btn = event.target.closest('button');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> 验证中';
  const data = await api('/api/validate', { method: 'POST' });
  btn.disabled = false;
  btn.innerHTML = '<i class="bi bi-check-circle"></i> 验证';
  toast(`验证完成，共 ${data ? data.validated : 0} 个`, 'success');
  loadStats(); loadProxies();
}

async function triggerConnectCheck() {
  const btn = event.target.closest('button');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> 检测中';
  await api('/api/validate-connect', { method: 'POST' });
  btn.disabled = false;
  btn.innerHTML = '<i class="bi bi-diagram-3"></i> CONNECT';
  toast('CONNECT检测完成', 'success');
  loadStats(); loadProxies();
}

async function triggerAnonymityCheck() {
  const btn = event.target.closest('button');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> 检测中';
  const data = await api('/api/verify-anonymity', { method: 'POST' });
  btn.disabled = false;
  btn.innerHTML = '<i class="bi bi-eye"></i> 匿名度';
  if (data) {
    toast(`匿名度检测完成 — 高匿:${data.elite} 匿名:${data.anonymous} 透明:${data.transparent}`, 'success');
  }
  loadStats(); loadProxies();
}

async function cleanDead() {
  if (!confirm('确定删除所有失效代理吗？')) return;
  const data = await api('/api/proxies?status=dead', { method: 'DELETE' });
  toast(`已清理 ${data ? data.deleted : 0} 个失效代理`, 'success');
  loadStats(); loadProxies();
}

// ── Rotator ──
async function startRotator() {
  const config = {
    interval: parseInt(document.getElementById('rotator-interval').value) || 60,
    protocol: document.getElementById('rotator-protocol').value,
    country: document.getElementById('rotator-country').value,
    max_latency: parseFloat(document.getElementById('rotator-latency').value) || 0
  };
  const data = await api('/api/rotator/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config)
  });
  if (data && data.running) {
    updateRotatorUI(data);
    startRotatorPolling();
    toast('轮换服务已启动', 'success');
  }
}

async function stopRotator() {
  await api('/api/rotator/stop', { method: 'POST' });
  const proxyStatus = await api('/api/system-proxy/status');
  if (proxyStatus && proxyStatus.enabled) {
    await api('/api/system-proxy/disable', { method: 'POST' });
    updateSysProxyUI(false);
  }
  updateRotatorUI({ running: false });
  stopRotatorPolling();
  toast('轮换服务已停止', 'info');
}

async function rotateNow() {
  const data = await api('/api/rotator/rotate', { method: 'POST' });
  if (data && data.current_proxy) {
    toast('已切换出口IP: ' + data.current_proxy.ip + ':' + data.current_proxy.port, 'success');
  }
}

async function pollRotatorStatus() {
  const data = await api('/api/rotator/status');
  if (!data) return;
  updateRotatorUI(data);
  if (!data.running) stopRotatorPolling();
}

function updateRotatorUI(data) {
  const badge = document.getElementById('rotator-badge');
  const btnStart = document.getElementById('btn-rotator-start');
  const btnStop = document.getElementById('btn-rotator-stop');
  const btnRotate = document.getElementById('btn-rotate-now');
  const btnUnpin = document.getElementById('btn-unpin');
  const btnSysProxy = document.getElementById('btn-system-proxy');
  const countdownEl = document.getElementById('rotator-countdown');
  const countEl = document.getElementById('rotator-count');
  const proxyCard = document.getElementById('current-proxy-display');
  const statsRow = document.getElementById('rotator-stats');
  const countdownBar = document.getElementById('countdown-bar');

  if (data.running) {
    if (data.pinned) {
      badge.innerHTML = '<span class="pulse-dot" style="background:var(--warning)"></span>已固定';
      badge.style.background = 'rgba(245,158,11,0.15)';
      badge.style.color = 'var(--warning)';
      countdownEl.textContent = '手动模式';
      btnUnpin.classList.remove('d-none');
      countdownBar.classList.add('d-none');
    } else {
      badge.innerHTML = '<span class="pulse-dot"></span>运行中';
      badge.style.background = 'rgba(16,185,129,0.15)';
      badge.style.color = 'var(--success)';
      if (data.next_rotate_in > 0) {
        const total = data.interval || 60;
        const pct = Math.max(0, 100 - (data.next_rotate_in / total * 100));
        countdownEl.textContent = data.next_rotate_in + '秒';
        countdownBar.classList.remove('d-none');
        document.getElementById('countdown-bar-fill').style.width = pct + '%';
      }
      btnUnpin.classList.add('d-none');
    }
    btnStart.classList.add('d-none');
    btnStop.classList.remove('d-none');
    btnRotate.disabled = data.pinned;
    btnSysProxy.disabled = false;
    countEl.textContent = data.rotate_count || 0;

    if (data.current_proxy) {
      proxyCard.classList.remove('d-none');
      statsRow.classList.remove('d-none');
      renderCurrentProxy(data.current_proxy);
    } else {
      proxyCard.classList.add('d-none');
    }
    // Sync verified-only toggle
    if (data.config && data.config.use_verified_only !== undefined) {
      document.getElementById('rotator-verified-only').checked = data.config.use_verified_only;
    }
    if (data.config && data.config.verified_count !== undefined) {
      document.getElementById('verified-count-badge').textContent = data.config.verified_count;
    }
  } else {
    badge.innerHTML = '未启动';
    badge.style.background = 'var(--text-disabled)';
    badge.style.color = '#fff';
    btnStart.classList.remove('d-none');
    btnStop.classList.add('d-none');
    btnRotate.disabled = true;
    btnUnpin.classList.add('d-none');
    btnSysProxy.disabled = true;
    countdownEl.textContent = '-';
    countdownBar.classList.add('d-none');
    proxyCard.classList.add('d-none');
  }
}

function renderCurrentProxy(p) {
  document.getElementById('rotator-current-addr').textContent = p.ip + ':' + p.port;
  const protoColors = { socks5: 'bg-primary', socks4: 'bg-info', http: 'bg-secondary', https: 'bg-secondary' };
  document.getElementById('rotator-current-badge').innerHTML =
    `<span class="badge ${protoColors[p.protocol] || 'bg-secondary'}">${(p.protocol || 'http').toUpperCase()}</span>`;
  document.getElementById('rotator-current-country').textContent = p.country || '-';

  const latEl = document.getElementById('rotator-current-latency');
  const lat = p.latency;
  if (lat > 0) {
    let cls = 'latency-ok';
    if (lat > 1000) cls = 'latency-danger';
    else if (lat > 500) cls = 'latency-warn';
    latEl.innerHTML = `<span class="${cls} fw-bold">${lat.toFixed(0)}ms</span>`;
  } else {
    latEl.innerHTML = '<span style="color:var(--text-disabled)">-</span>';
  }
  const anonMap = { elite: '高匿', anonymous: '匿名', transparent: '透明' };
  document.getElementById('rotator-current-anonymity').textContent = anonMap[p.anonymity] || p.anonymity || '-';
  document.getElementById('rotator-current-source').textContent = SOURCE_MAP[p.source] || p.source || '-';
}

function startRotatorPolling() {
  if (rotatorTimer) clearInterval(rotatorTimer);
  rotatorTimer = setInterval(pollRotatorStatus, 3000);
}
function stopRotatorPolling() {
  if (rotatorTimer) { clearInterval(rotatorTimer); rotatorTimer = null; }
}

// ── Pin proxy ──
async function pinProxy(id, addr) {
  if (!confirm(`固定使用代理 ${addr}？\n固定后将停止自动轮换。`)) return;
  const data = await api('/api/rotator/pin', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ proxy_id: id })
  });
  if (data && data.pinned) {
    updateRotatorUI({ running: true, pinned: true, current_proxy: data.current_proxy });
    toast('已固定: ' + addr, 'info');
  } else if (data && data.error) {
    toast('固定失败: ' + data.error, 'error');
  } else {
    toast('固定失败: 请先启动轮换服务', 'error');
  }
}

async function unpinProxy() {
  const data = await api('/api/rotator/unpin', { method: 'POST' });
  if (data) {
    pollRotatorStatus();
    toast('已取消固定，恢复轮换', 'info');
  }
}

// ── System proxy ──
async function toggleSystemProxy() {
  const status = await api('/api/system-proxy/status');
  if (!status) return;
  if (status.enabled) {
    await api('/api/system-proxy/disable', { method: 'POST' });
    updateSysProxyUI(false);
    toast('系统代理已关闭', 'info');
  } else {
    await api('/api/system-proxy/enable', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ addr: '127.0.0.1:5000' })
    });
    updateSysProxyUI(true);
    toast('系统代理已开启 → 127.0.0.1:5000', 'success');
  }
}

function updateSysProxyUI(enabled) {
  const btn = document.getElementById('btn-system-proxy');
  const text = document.getElementById('btn-system-proxy-text');
  if (enabled) {
    btn.className = 'btn btn-outline-danger btn-sm';
    text.textContent = '关闭系统代理';
  } else {
    btn.className = 'btn btn-outline-warning btn-sm';
    text.textContent = '开启系统代理';
  }
}

async function checkSystemProxy() {
  const data = await api('/api/system-proxy/status');
  if (data) updateSysProxyUI(data.enabled);
}

// ── Groups ──
async function loadGroups() {
  const data = await api('/api/groups');
  if (!data) return;
  const sel = document.getElementById('group-select');
  const current = sel.value;
  sel.innerHTML = '<option value="">全部代理</option>';
  data.forEach(g => {
    const count = g.proxy_count || 0;
    sel.innerHTML += `<option value="${g.id}">${g.name} (${count})</option>`;
  });
  sel.value = current;
  updateGroupButtons();
}

function updateGroupButtons() {
  const gid = document.getElementById('group-select').value;
  document.getElementById('btn-delete-group').classList.toggle('d-none', !gid);
  document.getElementById('btn-refresh-group').classList.toggle('d-none', !gid);
  document.getElementById('btn-add-to-group').classList.toggle('d-none', !gid || getSelectedIds().length === 0);
}

async function selectGroup() {
  const gid = document.getElementById('group-select').value;
  updateGroupButtons();
  if (!gid) { loadProxies(); return; }
  const data = await api('/api/groups/' + gid + '/proxies');
  renderProxyTable(data);
}

async function addSelectedToGroup() {
  const gid = document.getElementById('group-select').value;
  const ids = getSelectedIds();
  if (!gid || !ids.length) { toast('请先选择代理和分组', 'error'); return; }
  const data = await api('/api/groups/' + gid + '/proxies', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids })
  });
  if (data) {
    toast(`已添加 ${data.added} 个代理到分组`, 'success');
    loadGroups();
    clearSelection();
  }
}

async function refreshGroup() {
  const gid = document.getElementById('group-select').value;
  if (!gid) return;
  const data = await api('/api/groups/' + gid + '/populate', { method: 'POST' });
  if (data) {
    toast(`分组已刷新，匹配 ${data.populated} 个代理`, 'success');
    loadGroups();
    selectGroup();
  }
}

function showCreateGroup() { new bootstrap.Modal(document.getElementById('groupModal')).show(); }

async function createProxyGroup() {
  const name = document.getElementById('group-name').value.trim();
  if (!name) return;
  await api('/api/groups', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name,
      protocol: document.getElementById('group-protocol').value,
      country: document.getElementById('group-country').value,
      max_latency: parseFloat(document.getElementById('group-latency').value) || 0,
      anonymity: document.getElementById('group-anonymity').value,
      sort_by: 'latency'
    })
  });
  bootstrap.Modal.getInstance(document.getElementById('groupModal')).hide();
  loadGroups();
  toast('分组已创建: ' + name, 'success');
}

async function deleteCurrentGroup() {
  const gid = document.getElementById('group-select').value;
  if (!gid) return;
  if (!confirm('删除此分组？分组内代理不会被删除。')) return;
  await api('/api/groups/' + gid, { method: 'DELETE' });
  document.getElementById('group-select').value = '';
  loadGroups(); loadProxies();
  toast('分组已删除', 'info');
}

// ── Tool templates ──
async function showToolTemplates() {
  const data = await api('/api/tool-templates');
  if (!data) return;
  const body = document.getElementById('tool-modal-body');
  body.innerHTML = Object.entries(data).map(([key, t]) => `
    <div class="mb-3">
      <h6 style="color:var(--accent)">${t.name}</h6>
      <pre style="background:var(--bg-primary);color:var(--text-primary);padding:10px;border-radius:4px;font-size:0.78rem;position:relative;white-space:pre-wrap">${escapeHtml(t.config)}<button class="btn btn-outline-info btn-sm position-absolute top-0 end-0 m-2" onclick="navigator.clipboard.writeText('${escapeHtml(t.config).replace(/'/g, "\\'")}'); toast('已复制','success')"><i class="bi bi-clipboard"></i></button></pre>
    </div>`).join('');
  new bootstrap.Modal(document.getElementById('toolModal')).show();
}

function escapeHtml(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

// ── Auto-scrape ──
async function pollAutoScrapeStatus() {
  const data = await api('/api/auto-scrape/status');
  if (!data) return;
  updateAutoScrapeUI(data);
}

function updateAutoScrapeUI(data) {
  const btnStart = document.getElementById('btn-auto-scrape-start');
  const btnStop = document.getElementById('btn-auto-scrape-stop');
  const statusEl = document.getElementById('auto-scrape-status');
  const intervalInput = document.getElementById('auto-scrape-interval');

  if (data.interval && parseInt(intervalInput.value) !== data.interval) {
    intervalInput.value = data.interval;
  }

  if (data.running) {
    btnStart.classList.add('d-none');
    btnStop.classList.remove('d-none');
    intervalInput.disabled = false;

    if (data.last_scrape_time > 0) {
      const elapsed = (Date.now() / 1000) - data.last_scrape_time;
      const remaining = Math.max(0, data.interval - elapsed);
      const min = Math.floor(remaining / 60);
      const sec = Math.floor(remaining % 60);
      statusEl.textContent = `${min}分${sec}秒`;
      statusEl.style.color = 'var(--warning)';
    } else {
      statusEl.textContent = '等待中...';
      statusEl.style.color = 'var(--text-disabled)';
    }
  } else {
    btnStart.classList.remove('d-none');
    btnStop.classList.add('d-none');
    intervalInput.disabled = true;
    statusEl.textContent = '已停止';
    statusEl.style.color = 'var(--text-disabled)';
  }
}

async function startAutoScrape() {
  const interval = parseInt(document.getElementById('auto-scrape-interval').value) || 1800;
  await api('/api/auto-scrape/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ interval })
  });
  pollAutoScrapeStatus();
  toast(`自动抓取已启动 (${interval}秒)`, 'success');
}

async function stopAutoScrape() {
  await api('/api/auto-scrape/stop', { method: 'POST' });
  pollAutoScrapeStatus();
  toast('自动抓取已停止', 'info');
}

// ── Rotation test (BP test) ──
let _testPollTimer = null;

function showRotationTest() {
  new bootstrap.Modal(document.getElementById('rotateTestModal')).show();
}

function onTestTargetChange() {
  const sel = document.getElementById('test-target');
  const custom = document.getElementById('test-target-custom');
  if (sel.value === '__custom__') {
    custom.classList.remove('d-none');
    custom.focus();
  } else {
    custom.classList.add('d-none');
  }
}

function getTestTargetUrl() {
  const sel = document.getElementById('test-target');
  if (sel.value === '__custom__') {
    return document.getElementById('test-target-custom').value.trim() || '';
  }
  return sel.value;
}

async function startRotationTest() {
  const duration = parseInt(document.getElementById('test-duration').value);
  const interval = parseInt(document.getElementById('test-interval').value);
  const target = getTestTargetUrl();
  if (!target) { toast('请选择或输入检测URL', 'error'); return; }

  const data = await api('/api/rotation-test/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ duration, interval, target_url: target })
  });
  if (!data) return;

  document.getElementById('btn-test-start').classList.add('d-none');
  document.getElementById('btn-test-stop').classList.remove('d-none');
  document.getElementById('btn-test-clear').classList.add('d-none');
  document.getElementById('test-results').classList.remove('d-none');
  document.getElementById('test-status-text').textContent = `测试运行中... ${duration}秒 每${interval}秒`;

  _testPollTimer = setInterval(pollTestStatus, 2000);
  toast('轮换测试已启动', 'success');
}

async function stopRotationTest() {
  await api('/api/rotation-test/stop', { method: 'POST' });
  document.getElementById('btn-test-start').classList.remove('d-none');
  document.getElementById('btn-test-stop').classList.add('d-none');
  document.getElementById('btn-test-clear').classList.remove('d-none');
  document.getElementById('test-status-text').textContent = '测试已停止';
  if (_testPollTimer) { clearInterval(_testPollTimer); _testPollTimer = null; }
  toast('测试已停止', 'info');
}

async function clearTestRecords() {
  if (_testAllTimer) { clearInterval(_testAllTimer); _testAllTimer = null; }
  if (_testPollTimer) { clearInterval(_testPollTimer); _testPollTimer = null; }
  await api('/api/rotation-test/clear', { method: 'DELETE' });
  document.getElementById('test-results').classList.add('d-none');
  document.getElementById('btn-test-clear').classList.add('d-none');
  document.getElementById('btn-test-all').classList.remove('d-none');
  document.getElementById('test-status-text').textContent = '';
  toast('测试记录已清除', 'info');
}

async function pollTestStatus() {
  const data = await api('/api/rotation-test/status');
  if (!data) return;

  if (!data.running) {
    document.getElementById('btn-test-start').classList.remove('d-none');
    document.getElementById('btn-test-stop').classList.add('d-none');
    document.getElementById('btn-test-clear').classList.remove('d-none');
    document.getElementById('test-status-text').textContent = '测试完成';
    if (_testPollTimer) { clearInterval(_testPollTimer); _testPollTimer = null; }
  }

  // Stats
  document.getElementById('test-stats').innerHTML = `
    <div class="col-2"><div class="card p-2 text-center"><small style="color:var(--text-disabled)">请求数</small><h6>${data.total_requests}</h6></div></div>
    <div class="col-2"><div class="card p-2 text-center"><small style="color:var(--text-disabled)">成功</small><h6 style="color:var(--success)">${data.success_count}</h6></div></div>
    <div class="col-2"><div class="card p-2 text-center"><small style="color:var(--text-disabled)">失败</small><h6 style="color:var(--danger)">${data.fail_count}</h6></div></div>
    <div class="col-2"><div class="card p-2 text-center"><small style="color:var(--text-disabled)">唯一IP</small><h6 style="color:var(--accent)">${data.unique_ips}</h6></div></div>
    <div class="col-2"><div class="card p-2 text-center"><small style="color:var(--text-disabled)">轮换次数</small><h6 style="color:var(--warning)">${data.rotate_count}</h6></div></div>
    <div class="col-2"><div class="card p-2 text-center"><small style="color:var(--text-disabled)">当前IP</small><h6 style="font-size:0.75rem">${data.current_ip || '-'}</h6></div></div>
  `;

  // Log table
  const tbody = document.getElementById('test-log-body');
  const requests = data.requests || [];
  tbody.innerHTML = requests.slice().reverse().map((r, i) => {
    const cls = r.success ? '' : 'dead-row';
    const statusBadge = r.success
      ? '<span class="badge badge-alive">成功</span>'
      : '<span class="badge badge-dead">失败</span>';
    const ipColor = i > 0 && r.ip !== (requests[requests.length - 1 - i + 1] || {}).ip
      ? 'style="color:var(--warning);font-weight:600"' : '';
    return `<tr class="${cls}">
      <td>${requests.length - i}</td>
      <td><small>${(r.time || '').toString().substr(11, 8)}</small></td>
      <td><code ${ipColor}>${r.ip || '-'}</code></td>
      <td>${r.latency_ms > 0 ? r.latency_ms.toFixed(0) + 'ms' : '-'}</td>
      <td>${statusBadge}</td>
      <td><small style="color:var(--danger)">${r.error || ''}</small></td>
    </tr>`;
  }).join('');
}

// ── Test all proxies ──
let _testAllTimer = null;

async function startTestAllProxies() {
  const target = getTestTargetUrl();
  if (!target) { toast('请选择或输入检测URL', 'error'); return; }

  const data = await api('/api/rotation-test/test-all', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target_url: target })
  });
  if (!data) return;

  document.getElementById('btn-test-start').classList.add('d-none');
  document.getElementById('btn-test-all').classList.add('d-none');
  document.getElementById('btn-test-stop').classList.remove('d-none');
  document.getElementById('btn-test-clear').classList.add('d-none');
  document.getElementById('test-results').classList.remove('d-none');
  document.getElementById('test-status-text').textContent =
    `全量测试中... 共 ${data.total_proxies} 个代理`;

  _testAllTimer = setInterval(pollTestAllStatus, 2000);
  toast('全量代理测试已启动', 'success');
}

async function pollTestAllStatus() {
  const data = await api('/api/rotation-test/status');
  if (!data) return;

  const tested = data.total_requests || 0;
  const total = data.total_to_test || 0;
  const progress = total > 0 ? Math.round(tested / total * 100) : 0;

  if (!data.running && tested > 0) {
    document.getElementById('btn-test-start').classList.remove('d-none');
    document.getElementById('btn-test-all').classList.remove('d-none');
    document.getElementById('btn-test-stop').classList.add('d-none');
    document.getElementById('btn-test-clear').classList.remove('d-none');
    document.getElementById('test-status-text').textContent =
      `全量测试完成 — ${tested}/${total} 通过:${data.success_count} 失败:${data.fail_count} 已验证:${data.verified_count || 0}`;
    if (_testAllTimer) { clearInterval(_testAllTimer); _testAllTimer = null; }
  } else if (data.running) {
    document.getElementById('test-status-text').textContent =
      `全量测试中... ${tested}/${total} (${progress}%) 通过:${data.success_count} 失败:${data.fail_count}`;
  }

  // Stats
  document.getElementById('test-stats').innerHTML = `
    <div class="col-2"><div class="card p-2 text-center"><small style="color:var(--text-disabled)">进度</small><h6>${tested}/${total}</h6></div></div>
    <div class="col-2"><div class="card p-2 text-center"><small style="color:var(--text-disabled)">成功</small><h6 style="color:var(--success)">${data.success_count}</h6></div></div>
    <div class="col-2"><div class="card p-2 text-center"><small style="color:var(--text-disabled)">失败</small><h6 style="color:var(--danger)">${data.fail_count}</h6></div></div>
    <div class="col-2"><div class="card p-2 text-center"><small style="color:var(--text-disabled)">已验证</small><h6 style="color:var(--accent)">${data.verified_count || 0}</h6></div></div>
  `;

  // Log table
  const tbody = document.getElementById('test-log-body');
  const requests = data.requests || [];
  tbody.innerHTML = requests.slice().reverse().map((r, i) => {
    const cls = r.success ? '' : 'dead-row';
    const statusBadge = r.success
      ? '<span class="badge badge-alive">成功</span>'
      : '<span class="badge badge-dead">失败</span>';
    return `<tr class="${cls}">
      <td>${requests.length - i}</td>
      <td><small>${(r.time || '').toString().substr(11, 8)}</small></td>
      <td><code>${r.proxy_addr || r.ip || '-'}</code></td>
      <td>${r.latency_ms > 0 ? r.latency_ms.toFixed(0) + 'ms' : '-'}</td>
      <td>${statusBadge}</td>
      <td><small style="color:var(--danger)">${r.error || ''}</small></td>
    </tr>`;
  }).join('');

  // Update verified count
  if (data.verified_count !== undefined) {
    document.getElementById('verified-count-badge').textContent = data.verified_count;
  }
}

// ── Verified-only toggle ──
async function toggleVerifiedOnly() {
  const checked = document.getElementById('rotator-verified-only').checked;
  await api('/api/rotator/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ use_verified_only: checked })
  });
  toast(checked ? '已启用仅验证IP模式' : '已恢复全池模式', 'info');
}

// Stop test also clears test-all timer
const _origStop = stopRotationTest;
stopRotationTest = async function() {
  if (_testAllTimer) { clearInterval(_testAllTimer); _testAllTimer = null; }
  document.getElementById('btn-test-all').classList.remove('d-none');
  document.getElementById('btn-test-clear').classList.remove('d-none');
  await _origStop();
};

// ── Nmap scan ──
async function checkNmapAvailable() {
  const data = await api('/api/nmap/check');
  if (!data) return;
  const el = document.getElementById('nmap-available-status');
  if (data.available) {
    el.innerHTML = `<small style="color:var(--success)"><i class="bi bi-check-circle"></i> nmap 已就绪 (${data.path})</small>`;
  } else {
    el.innerHTML = `<small style="color:var(--danger)"><i class="bi bi-exclamation-triangle"></i> nmap 未安装，请先从 <a href="https://nmap.org/download.html" target="_blank" style="color:var(--info)">nmap.org</a> 下载</small>`;
  }
}

function showNmapModal() {
  checkNmapAvailable();
  new bootstrap.Modal(document.getElementById('nmapModal')).show();
}

async function startNmapScan() {
  const btn = document.getElementById('btn-nmap-scan');
  const targets = document.getElementById('nmap-targets').value.trim();
  if (!targets) { toast('请输入扫描目标', 'error'); return; }

  btn.disabled = true;
  document.getElementById('btn-nmap-quick').disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> 扫描中...';
  document.getElementById('nmap-status').textContent = '正在扫描，请稍候...';
  document.getElementById('nmap-results').classList.add('d-none');

  const portsStr = document.getElementById('nmap-ports').value.trim();
  const ports = portsStr ? portsStr.split(',').map(p => parseInt(p.trim())).filter(p => !isNaN(p)) : [];
  const rate = parseInt(document.getElementById('nmap-rate').value);

  const data = await api('/api/nmap/scan', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ targets, ports: ports.length ? ports : null, rate })
  });

  btn.disabled = false;
  document.getElementById('btn-nmap-quick').disabled = false;
  btn.innerHTML = '<i class="bi bi-search"></i> 开始扫描';
  document.getElementById('nmap-status').textContent = '';

  if (data) {
    document.getElementById('nmap-results').classList.remove('d-none');
    document.getElementById('nmap-result-text').textContent =
      `发现 ${data.discovered} 个代理，已自动存入数据库`;
    if (data.discovered > 0) {
      toast(`发现 ${data.discovered} 个代理`, 'success');
      loadStats(); loadProxies();
    }
  }
}

async function startNmapQuickScan() {
  const btn = document.getElementById('btn-nmap-quick');
  btn.disabled = true;
  document.getElementById('btn-nmap-scan').disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> 一键扫描中...';
  document.getElementById('nmap-status').textContent = '正在扫描公网VPS段，约需1-2分钟...';
  document.getElementById('nmap-results').classList.add('d-none');

  const rate = parseInt(document.getElementById('nmap-rate').value);

  const data = await api('/api/nmap/quick-scan', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ip_count: 200, rate })
  });

  btn.disabled = false;
  document.getElementById('btn-nmap-scan').disabled = false;
  btn.innerHTML = '<i class="bi bi-lightning-charge-fill"></i> 一键扫描公网';
  document.getElementById('nmap-status').textContent = '';

  if (data) {
    document.getElementById('nmap-results').classList.remove('d-none');
    document.getElementById('nmap-result-text').textContent =
      `扫描 ${data.scanned_ips} 个IP，发现 ${data.discovered} 个代理，已自动存入数据库`;
    if (data.discovered > 0) {
      toast(`发现 ${data.discovered} 个代理`, 'success');
      loadStats(); loadProxies();
    } else {
      toast('未发现代理，可重试或手动输入IP段', 'info');
    }
  }
}

// ── Context menu ──
let _ctxProxy = null;

function ctxShow(e) {
  const tr = e.target.closest('tr[data-proxy-id]');
  if (!tr) return;
  _ctxProxy = { id: parseInt(tr.dataset.proxyId), addr: tr.dataset.proxyAddr, url: tr.dataset.proxyUrl };
  const menu = document.getElementById('context-menu');
  menu.style.display = 'block';
  menu.style.left = Math.min(e.clientX, window.innerWidth - 200) + 'px';
  menu.style.top = Math.min(e.clientY, window.innerHeight - 180) + 'px';
}
function ctxHide() { _ctxProxy = null; document.getElementById('context-menu').style.display = 'none'; }
function ctxPin() { if (_ctxProxy) pinProxy(_ctxProxy.id, _ctxProxy.addr); ctxHide(); }
function ctxCopyAddr() { if (_ctxProxy) copyProxy(_ctxProxy.addr); ctxHide(); }
function ctxCopyUrl() { if (_ctxProxy) copyProxy(_ctxProxy.url); ctxHide(); }
function ctxTestLatency() {
  if (_ctxProxy) toast('延迟测试功能: ' + _ctxProxy.addr, 'info');
  ctxHide();
}

document.addEventListener('click', (e) => { if (!e.target.closest('#context-menu')) ctxHide(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { ctxHide(); document.getElementById('col-menu').classList.add('d-none'); } });

// ── History data ──
async function loadHistory() {
  const data = await api('/api/history?days=7');
  if (!data || data.error) {
    document.getElementById('history-tbody').innerHTML =
      '<tr><td colspan="6" class="text-center" style="color:var(--text-disabled)">仅 MySQL 存储支持历史数据</td></tr>';
    return;
  }
  const dates = Object.keys(data).sort().reverse();
  let totalAlive = 0, totalAll = 0;
  const rows = dates.map(dt => {
    const d = data[dt];
    const rate = d.total > 0 ? ((d.alive || 0) / d.total * 100).toFixed(0) : 0;
    totalAlive += d.alive || 0;
    totalAll += d.total || 0;
    const rateColor = rate >= 50 ? 'var(--success)' : rate >= 20 ? 'var(--warning)' : 'var(--danger)';
    return `<tr>
      <td>${dt}</td>
      <td>${d.total}</td>
      <td style="color:var(--success)">${d.alive || 0}</td>
      <td style="color:var(--danger)">${d.dead || 0}</td>
      <td style="color:var(--text-disabled)">${d.unknown || 0}</td>
      <td style="color:${rateColor};font-weight:600">${rate}%</td>
    </tr>`;
  }).join('');

  document.getElementById('history-tbody').innerHTML = rows;
  const overallRate = totalAll > 0 ? (totalAlive / totalAll * 100).toFixed(0) : 0;
  document.getElementById('history-stats').innerHTML = `
    <div class="col-3"><div class="card p-2 text-center"><small style="color:var(--text-secondary)">累计抓取</small><h6>${totalAll}</h6></div></div>
    <div class="col-3"><div class="card p-2 text-center"><small style="color:var(--text-secondary)">累计存活</small><h6 style="color:var(--success)">${totalAlive}</h6></div></div>
    <div class="col-3"><div class="card p-2 text-center"><small style="color:var(--text-secondary)">整体存活率</small><h6 style="color:${overallRate >= 50 ? 'var(--success)' : 'var(--warning)'}">${overallRate}%</h6></div></div>
    <div class="col-3"><div class="card p-2 text-center"><small style="color:var(--text-secondary)">统计天数</small><h6>${dates.length}</h6></div></div>
  `;
}

// ── Init ──
function startAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(() => { loadStats(); loadProxies(); }, 10000);
}

document.addEventListener('DOMContentLoaded', () => {
  const tbody = document.getElementById('proxy-tbody');
  tbody.addEventListener('contextmenu', (e) => { e.preventDefault(); ctxShow(e); });
  loadStats(); loadProxies(); loadCountries(); loadGroups(); loadHistory();
  startAutoRefresh();
  checkSystemProxy();
  pollAutoScrapeStatus();
  autoScrapeTimer = setInterval(pollAutoScrapeStatus, 3000);
  pollRotatorStatus().then(() => {
    const badge = document.getElementById('rotator-badge');
    if (badge.textContent.includes('运行中')) startRotatorPolling();
  });
});
