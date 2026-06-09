// ══════════════════════════════════════════════════
// THEME TOGGLE (Light / Dark)
// ══════════════════════════════════════════════════
(function initTheme() {
  const saved = localStorage.getItem('dashboard-theme');
  if (saved === 'light') {
    document.documentElement.classList.add('light');
  }
})();

function toggleTheme() {
  const html = document.documentElement;
  const isLight = html.classList.toggle('light');
  localStorage.setItem('dashboard-theme', isLight ? 'light' : 'dark');
  updateThemeLabel();
  
  try {
    if (typeof Chart !== 'undefined') {
      Object.values(Chart.instances || {}).forEach(chart => {
        const gridColor = isLight ? 'rgba(183,201,245,0.5)' : 'rgba(42,50,72,0.5)';
        const textColor = isLight ? '#ffffff' : '#7b86a0';
        
        if (chart.options.scales?.y) {
          chart.options.scales.y.grid.color = gridColor;
          chart.options.scales.y.ticks.color = textColor;
        }
        if (chart.options.scales?.x) {
          chart.options.scales.x.ticks.color = textColor;
        }
        chart.update('none');
      });
    }
  } catch(e) {
    console.warn('Chart theme update skipped:', e);
  }
}

function updateThemeLabel() {
  const el = document.getElementById('theme-label');
  if (!el) return;
  const isLight = document.documentElement.classList.contains('light');
  el.textContent = isLight ? '🌙 تم تاریک' : '☀️ تم روشن';
}

// ─── Topbar Dropdown Menu ────────────────────────
function toggleTopbarMenu() {
  const el = document.getElementById('topbar-more');
  if (el) el.classList.toggle('open');
}
function closeTopbarMenu() {
  const el = document.getElementById('topbar-more');
  if (el) el.classList.remove('open');
}
document.addEventListener('click', function(e) {
  const el = document.getElementById('topbar-more');
  if (el && !el.contains(e.target)) el.classList.remove('open');
});

// ══════════════════════════════════════════════════
// UTILITIES
// ══════════════════════════════════════════════════
function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/[&<>]/g, function(m) {
    if (m === '&') return '&amp;';
    if (m === '<') return '&lt;';
    if (m === '>') return '&gt;';
    return m;
  });
}

// ══════════════════════════════════════════════════
// GLOBAL VARIABLES
// ══════════════════════════════════════════════════
let allData     = [];
let allEvents   = [];
let countdown   = POLL_INT;
let countTimer  = null;
let isFirst     = true;
let serverInfo  = {};

const PAGE_SIZE = 20;
const _pgState  = {};

let chartInstance = null;
const printerChartInstances = {};

const USER_ROLE = document.body?.dataset?.currentUserRole || 'viewer';
const USER_VERIFIED = document.body?.dataset?.currentUserVerified === '1';
let USER_ALLOWED_MODULES = [];
try {
  USER_ALLOWED_MODULES = JSON.parse(document.body?.dataset?.currentUserModules || '[]');
  if (!Array.isArray(USER_ALLOWED_MODULES)) USER_ALLOWED_MODULES = [];
} catch (e) {
  USER_ALLOWED_MODULES = [];
}

function canAccessModule(moduleName) {
  return USER_ROLE === 'admin' || !USER_ALLOWED_MODULES.length || USER_ALLOWED_MODULES.includes(moduleName);
}

function canAdmin() {
  return USER_VERIFIED && USER_ROLE === 'admin';
}

function canManage() {
  return USER_VERIFIED && (USER_ROLE === 'admin' || USER_ROLE === 'manager') && canAccessModule('excel');
}

function canViewLogs() {
  return USER_VERIFIED && canAccessModule('logs');
}

function canEditPrinters() {
  return canAdmin() && canAccessModule('printers');
}

function canManualEvents() {
  return canAdmin() && canAccessModule('logs');
}

const OFFICE_GROUPS = [
  { id: 'imamat',   name: 'دفتر امامت',  subnet: '172.16.25', icon: '🏢', color: 'cyan'    },
  { id: 'soroush',  name: 'دفتر سروش',   subnet: '172.16.24', icon: '🏢', color: 'green'   },
  { id: 'falestin', name: 'دفتر فلسطین', subnet: '172.16.0',  icon: '🏢', color: 'yellow'  },
  { id: 'elahiye',  name: 'دفتر الهیه',  subnet: '172.16.32', icon: '🏢', color: 'magenta' },
  { id: 'other',    name: 'سایر',         subnet: null,        icon: '🖨',  color: 'orange'  },
];

const _groupOpen = {};

let sortableInstance = null;
let currentPrinters = [];
const STORAGE_KEY = 'printer_order';
let swapPluginMounted = false;

function getDefaultPrinterOrder(printers) {
  const groups = {};
  for (const p of printers) {
    const parts = p.ip.split('.');
    const subnet = parts.slice(0, 3).join('.');
    if (!groups[subnet]) groups[subnet] = [];
    groups[subnet].push(p);
  }
  for (const subnet in groups) {
    groups[subnet].sort((a, b) => {
      const aParts = a.ip.split('.').map(Number);
      const bParts = b.ip.split('.').map(Number);
      for (let i = 0; i < 4; i++) {
        if (aParts[i] !== bParts[i]) return aParts[i] - bParts[i];
      }
      return 0;
    });
  }
  const sortedSubnets = Object.keys(groups).sort((a, b) => {
    const aParts = a.split('.').map(Number);
    const bParts = b.split('.').map(Number);
    for (let i = 0; i < 3; i++) {
      if (aParts[i] !== bParts[i]) return aParts[i] - bParts[i];
    }
    return 0;
  });
  const order = [];
  for (const subnet of sortedSubnets) {
    for (const p of groups[subnet]) {
      order.push(p.ip);
    }
  }
  return order;
}

function getPrinterOrder(printers) {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored) {
    try {
      const order = JSON.parse(stored);
      const currentIps = new Set(printers.map(p => p.ip));
      const validOrder = order.filter(ip => currentIps.has(ip));
      const newIps = printers.filter(p => !validOrder.includes(p.ip)).map(p => p.ip);
      const finalOrder = [...validOrder, ...newIps];
      if (finalOrder.length !== order.length) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(finalOrder));
      }
      return finalOrder;
    } catch(e) {}
  }
  return getDefaultPrinterOrder(printers);
}

function sortPrintersForDisplay(printers) {
  const order = getPrinterOrder(printers);
  return [...printers].sort((a, b) => {
    const aSensor = a.device_type === 'sensor' ? 0 : 1;
    const bSensor = b.device_type === 'sensor' ? 0 : 1;
    if (aSensor !== bSensor) return aSensor - bSensor;

    const aIndex = order.indexOf(a.ip);
    const bIndex = order.indexOf(b.ip);
    if (aIndex !== bIndex) return aIndex - bIndex;

    return a.ip.localeCompare(b.ip, undefined, { numeric: true });
  });
}

function savePrinterOrder(order) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(order));
}

function resetPrinterOrder() {
  if (!canAdmin()) { toast('دسترسی ندارید', 'e'); return; }
  localStorage.removeItem(STORAGE_KEY);
  toast('ترتیب به حالت پیش‌فرض برگشت', 's');
  fetchData();
}

function renderPrinterCard(p) {
  const online = p.online;
  const deviceType = p.device_type || 'unknown';
  const badgeStyle = 'display:inline-block;padding:2px 8px;border-radius:10px;font-size:9px;margin-right:6px;font-weight:bold;color:#fff;vertical-align:middle;';

  // ═══ کارت مخصوص دماسنج ═══
  if (deviceType === 'sensor') {
    const c = p.counters || {};
    const temp1 = c.temp1 ?? '—';
    const temp2 = c.temp2;  // ممکنه undefined باشه
    const hum1  = c.hum1 ?? '—';
    const hum2  = c.hum2;
    const displayName = p.nickname ? `${escapeHtml(p.nickname)} (${escapeHtml(p.name)})` : escapeHtml(p.name);

    let officeName = '';
    for (const g of OFFICE_GROUPS) {
      if (g.subnet && p.ip.startsWith(g.subnet + '.')) { officeName = g.name; break; }
    }
    if (!officeName) officeName = 'سایر';

    const sensorRows = [];
    sensorRows.push(`
      <div style="display:flex; justify-content:space-between; align-items:center; padding:5px 0; border-bottom:1px solid rgba(255,255,255,0.05)">
        <span style="font-size:10px; color:var(--text3)">🌡️ دما پورت ۱</span>
        <span style="font-weight:700; font-size:16px; color:var(--cyan)">${temp1}°C</span>
      </div>`);

    if (temp2 !== null && temp2 !== undefined) {
      sensorRows.push(`
      <div style="display:flex; justify-content:space-between; align-items:center; padding:5px 0; border-bottom:1px solid rgba(255,255,255,0.05)">
        <span style="font-size:10px; color:var(--text3)">🌡️ دما پورت ۲</span>
        <span style="font-weight:700; font-size:16px; color:var(--cyan)">${temp2}°C</span>
      </div>`);
    }

    sensorRows.push(`
      <div style="display:flex; justify-content:space-between; align-items:center; padding:5px 0; border-bottom:1px solid rgba(255,255,255,0.05)">
        <span style="font-size:10px; color:var(--text3)">💧 رطوبت پورت ۱</span>
        <span style="font-weight:700; font-size:16px; color:var(--blue)">${hum1}%</span>
      </div>`);

    if (hum2 !== null && hum2 !== undefined) {
      sensorRows.push(`
      <div style="display:flex; justify-content:space-between; align-items:center; padding:5px 0;">
        <span style="font-size:10px; color:var(--text3)">💧 رطوبت پورت ۲</span>
        <span style="font-weight:700; font-size:16px; color:var(--blue)">${hum2}%</span>
      </div>`);
    }

    return `
      <div class="overview-card oc-online sensor-banner" data-ip="${p.ip}" onclick="switchTab('${p.ip}')" style="border-top:2px solid var(--orange)">
        <div class="oc-header">
          <div>
            <div class="oc-ip" style="color:var(--orange)">${p.ip} <span style="${badgeStyle}background:#ff9800;">دماسنج</span></div>
            <div class="oc-name">${displayName}</div>
            <div class="oc-model">ECS100G · ${officeName}</div>
          </div>
          ${online === true
            ? `<div class="oc-pill pill-on"><span class="pill-dot" style="background:var(--green);box-shadow:0 0 5px var(--green)"></span>ONLINE</div>`
            : online === false
            ? `<div class="oc-pill pill-off"><span class="pill-dot" style="background:var(--red)"></span>OFFLINE</div>`
            : `<div class="oc-pill" style="border:1px solid var(--border);color:var(--text3)">—</div>`}
        </div>
        <div class="oc-sensor-data" style="margin-top:8px">
          ${sensorRows.join('')}
        </div>
        ${p.alerts?.length ? `<div class="oc-alert">⚠ ${p.alerts.map(a=>a.message).join(' | ')}</div>` : ''}
      </div>`;
  }

  // ═══ کارت پرینتر (کد قبلی) ═══
  const c = p.counters || {};
  const total = c.total || 0;
  const fc = c.full_color || 0;
  const bw = c.black_white || 0;
  const toners = p.toners || {};

  const cyanLevel = toners.cyan?.level;
  const magentaLevel = toners.magenta?.level;
  const yellowLevel = toners.yellow?.level;
  const blackLevel = toners.black?.level;

  // ✅ باگ #7: تشخیص صحیح وضعیت undefined برای نوارهای تونر
  const cyanHasData = cyanLevel !== null && cyanLevel !== undefined;
  const magentaHasData = magentaLevel !== null && magentaLevel !== undefined;
  const yellowHasData = yellowLevel !== null && yellowLevel !== undefined;
  const blackHasData = blackLevel !== null && blackLevel !== undefined;

  const cls = online === true ? 'oc-online' : (online === false ? 'oc-offline' : '');
  const warnCls = (p.alerts?.length) ? 'oc-warn' : cls;
  const displayName = p.nickname ? `${escapeHtml(p.nickname)} (${escapeHtml(p.name)})` : escapeHtml(p.name);
  
  let typeBadge = '';
  if (deviceType === 'color') {
    typeBadge = `<span style="${badgeStyle}background:#e91e63;">رنگی</span>`;
  } else if (deviceType === 'mono') {
    typeBadge = `<span style="${badgeStyle}background:#607d8b;">تک‌رنگ</span>`;
  } else if (deviceType === 'sensor') {
    typeBadge = `<span style="${badgeStyle}background:#ff9800;">دماسنج</span>`;
  } else {
    typeBadge = `<span style="${badgeStyle}background:#3a3a3a;">ناشناخته</span>`;
  }
  
  let officeName = '';
  for (const g of OFFICE_GROUPS) {
    if (g.subnet && p.ip.startsWith(g.subnet + '.')) {
      officeName = g.name;
      break;
    }
  }
  if (!officeName) officeName = 'سایر';

  // ✅ باگ #7: نمایش صحیح تونرهای نامشخص (جلوگیری از نمایش 0% وقتی مقدار null است)
  // ✅ باگ #7: نمایش صحیح تونرهای نامشخص (جلوگیری از نمایش 0% وقتی مقدار null است)
  const colorTonersHtml = `
    <div class="oc-toner-group">
      <div class="oc-toner-item">
        <div class="oc-toner-bar" style="width: ${cyanHasData ? cyanLevel : 0}%; background: ${cyanHasData ? '#00d4ff' : '#555'};"></div>
      </div>
      <div class="oc-toner-item">
        <div class="oc-toner-bar" style="width: ${magentaHasData ? magentaLevel : 0}%; background: ${magentaHasData ? '#ea80fc' : '#555'};"></div>
      </div>
      <div class="oc-toner-item">
        <div class="oc-toner-bar" style="width: ${yellowHasData ? yellowLevel : 0}%; background: ${yellowHasData ? '#ffd740' : '#555'};"></div>
      </div>
    </div>
  `;

  const blackTonerHtml = `
    <div class="oc-toner-item">
      <div class="oc-toner-bar" style="width: ${blackHasData ? blackLevel : 0}%; background: ${blackHasData ? '#9e9e9e' : '#555'};"></div>
    </div>
  `;

  return `
    <div class="overview-card ${warnCls}" data-ip="${p.ip}" onclick="switchTab('${p.ip}')">
      <div class="oc-header">
        <div>
          <div class="oc-ip">${p.ip} ${typeBadge}</div>
          <div class="oc-name">${displayName}</div>
          <div class="oc-model">${p.device?.model || 'TOSHIBA'} · ${officeName}</div>
        </div>
        ${online === true
          ? `<div class="oc-pill pill-on"><span class="pill-dot" style="background:var(--green);box-shadow:0 0 5px var(--green)"></span>ONLINE</div>`
          : online === false
          ? `<div class="oc-pill pill-off"><span class="pill-dot" style="background:var(--red)"></span>OFFLINE</div>`
          : `<div class="oc-pill" style="border:1px solid var(--border);color:var(--text3)">—</div>`}
      </div>

      <div class="oc-stat-row">
        <div class="oc-counter">
          <span class="oc-counter-val">${fmtN(total)}</span>
          <span class="oc-counter-label">کل</span>
        </div>
        <div class="oc-toner-placeholder"></div>
      </div>

      <div class="oc-stat-row">
        <div class="oc-counter">
          <span class="oc-counter-val" style="color:var(--cyan)">${fmtN(fc)}</span>
          <span class="oc-counter-label">رنگی</span>
        </div>
        <div class="oc-toner-area">${colorTonersHtml}</div>
      </div>

      <div class="oc-stat-row">
        <div class="oc-counter">
          <span class="oc-counter-val" style="color:var(--text2)">${fmtN(bw)}</span>
          <span class="oc-counter-label">BW</span>
        </div>
        <div class="oc-toner-area">${blackTonerHtml}</div>
      </div>

      ${p.alerts?.length ? `<div class="oc-alert">⚠ ${p.alerts.map(a=>a.message).join(' | ')}</div>` : ''}
    </div>
  `;
}

// ══════════════════════════════════════════════════
// FETCH & UPDATE
// ══════════════════════════════════════════════════
async function fetchData() {
  setDot('fetch');
  try {
    const [pr, st, lg] = await Promise.all([
      fetch(`${API}/api/printers`,{cache:'no-store'}).then(r=>r.json()),
      fetch(`${API}/api/status`,{cache:'no-store'}).then(r=>r.json()),
      fetch(`${API}/api/logs/all`,{cache:'no-store'}).then(r=>r.json()),
    ]);
    allData   = pr.printers || [];
    allEvents = lg.events   || [];
    serverInfo = st;
    updateMeta(pr.meta, st);
    rebuildTabs(allData);
    renderOverviewCards(allData);
    renderGlobalLog(allEvents);
    renderAllPrinterPanels(allData);
    renderAccessPanel(st);
    populatePrinterSelect();
    setDot('on');
    if (!isFirst) toast('آپدیت شد','s');
    isFirst = false;
    resetCountdown();
  } catch(e) {
    console.error(e);
    setDot('err');
    toast('خطا در اتصال به سرور','e');
  }
}

// Toner Reset Modal and handlers
let _tonerResetTargetIp = null;
function openTonerResetModal(ip) {
  _tonerResetTargetIp = ip;
  const p = (allData || []).find(x=>x.ip===ip) || {};
  const toners = p.toners || {};
  const colors = ['black','cyan','magenta','yellow'].filter(c => !!(toners[c] && (toners[c].level !== undefined || toners[c].name)) );
  if (!colors.length) { toast('هیچ اطلاعات تونری برای این دستگاه وجود ندارد','e'); return; }
  const modal = document.getElementById('modal-toner-reset');
  if (!modal) return;
  const sel = modal.querySelector('#toner-reset-color');
  const lvl = modal.querySelector('#toner-reset-level');
  sel.innerHTML = colors.map(c=>`<option value="${c}">${({black:'مشکی',cyan:'سیان',magenta:'مژنتا',yellow:'زرد'}[c])}</option>`).join('');
  lvl.value = 100;
  modal.style.display = 'block';
}

function closeTonerResetModal() {
  const modal = document.getElementById('modal-toner-reset');
  if (modal) modal.style.display = 'none';
  _tonerResetTargetIp = null;
}

async function submitTonerReset() {
  const modal = document.getElementById('modal-toner-reset');
  if (!modal) return;
  const color = modal.querySelector('#toner-reset-color').value;
  let new_level = parseInt(modal.querySelector('#toner-reset-level').value || '100');
  if (isNaN(new_level)) new_level = 100;
  new_level = Math.max(0, Math.min(100, new_level));
  if (!_tonerResetTargetIp) { toast('هدف نامشخص است','e'); return; }
  try {
    const r = await fetch(`${API}/api/printer/${encodeURIComponent(_tonerResetTargetIp)}/toner_reset`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ color, new_level })
    });
    const j = await r.json();
    if (r.ok) {
      toast('مقدار تونر به‌روزرسانی شد','s');
      closeTonerResetModal();
      fetchData();
    } else {
      toast(j.error || 'خطا در به‌روزرسانی', 'e');
    }
  } catch(e) {
    console.error(e);
    toast('خطا در اتصال', 'e');
  }
}

function updateMeta(meta, st) {
  document.getElementById('m-on').textContent  = meta?.online  ?? '—';
  document.getElementById('m-off').textContent = meta?.offline ?? '—';
  document.getElementById('m-poll').textContent = meta?.poll_count ? `#${meta.poll_count}` : '—';
  const lp = meta?.last_poll;
  document.getElementById('m-time').textContent = lp ? new Date(lp).toLocaleTimeString('fa-IR') : '—';
  const userEl = document.getElementById('m-user');
  if (userEl) {
    userEl.textContent = window.currentUsername || 'میهمان';
  }
}

// ══════════════════════════════════════════════════
// SIDEBAR & TABS
// ══════════════════════════════════════════════════
let activeTab = 'overview';

function getOfficeGroup(ip) {
  for (const g of OFFICE_GROUPS) {
    if (g.subnet && ip.startsWith(g.subnet + '.')) return g.id;
  }
  return 'other';
}

function rebuildTabs(printers) {
  const container = document.getElementById('sidebar-groups');
  if (!container) return;

  const totalOnline  = printers.filter(p => p.online === true).length;
  const totalOffline = printers.filter(p => p.online === false).length;
  const badge = document.getElementById('sb-ov-badge');
  if (badge) badge.textContent = totalOnline + '▲ ' + totalOffline + '▼';

  const grouped = {};
  OFFICE_GROUPS.forEach(g => { grouped[g.id] = []; });
  printers.forEach(p => { grouped[getOfficeGroup(p.ip)].push(p); });

  const order = getPrinterOrder(printers);

  container.innerHTML = '';

  OFFICE_GROUPS.forEach(g => {
    let members = grouped[g.id];
    if (!members.length) return;

    members.sort((a, b) => order.indexOf(a.ip) - order.indexOf(b.ip));

    const onCnt    = members.filter(p => p.online === true).length;
    const offCnt   = members.filter(p => p.online === false).length;
    const hasAlert = members.some(p => p.alerts && p.alerts.length > 0);

    if (_groupOpen[g.id] === undefined) {
      _groupOpen[g.id] = members.some(p => p.ip === activeTab) || g.id === 'imamat';
    }

    const groupEl = document.createElement('div');
    groupEl.className = 'sb-group' + (_groupOpen[g.id] ? ' open' : '');
    groupEl.dataset.color = g.color;
    groupEl.id = 'sbg-' + g.id;

    const metaHtml = `
      <div class="sb-meta-group">
        ${onCnt ? `
          <div class="sb-meta-item">
            <span class="sb-meta-dot online"></span>
            <span class="sb-meta-count">${onCnt}</span>
          </div>
        ` : ''}
        ${offCnt ? `
          <div class="sb-meta-item">
            <span class="sb-meta-dot offline"></span>
            <span class="sb-meta-count">${offCnt}</span>
          </div>
        ` : ''}
      </div>
    `;

    const itemsHtml = members.map(p => {
      const dotCls    = p.online === true ? 'online' : (p.online === false ? 'offline' : 'unknown');
      const hasAl     = p.alerts && p.alerts.length;
      const alertIcon = hasAl ? '<span class="sb-alert-icon">⚠</span>' : '';
      const alertCls  = hasAl ? ' has-alert' : '';
      const activeCls = activeTab === p.ip ? ' active' : '';
      const displayName = p.nickname ? `${escapeHtml(p.nickname)} (${escapeHtml(p.name)})` : escapeHtml(p.name);
      return '<div class="sb-item' + activeCls + alertCls +
             '" data-tab="' + p.ip + '" onclick="switchTab(\'' + p.ip + '\',this)">' +
               '<span class="sb-dot ' + dotCls + '"></span>' +
               '<span class="sb-item-name">' + displayName + '</span>' +
               alertIcon +
             '</div>';
    }).join('');

    groupEl.innerHTML =
      '<div class="sb-group-hdr' + (hasAlert ? ' has-alert' : '') +
      '" onclick="toggleSbGroup(\'' + g.id + '\')">' +
        '<span class="sb-arrow">▶</span>' +
        '<span class="sb-group-icon">' + g.icon + '</span>' +
        '<span class="sb-group-name">' + g.name + '</span>' +
        '<span class="sb-group-meta">' + metaHtml + '</span>' +
      '</div>' +
      '<div class="sb-group-body">' + itemsHtml + '</div>';

    container.appendChild(groupEl);
  });

  const ovBtn = document.querySelector('.sb-overview');
  if (ovBtn) ovBtn.classList.toggle('active', activeTab === 'overview');
}

function toggleSbGroup(id) {
  _groupOpen[id] = !_groupOpen[id];
  const el = document.getElementById('sbg-' + id);
  if (el) el.classList.toggle('open', _groupOpen[id]);
}

function switchTab(id, el) {
  activeTab = id;
  document.querySelectorAll('.sb-item, .sb-overview').forEach(t => t.classList.remove('active'));
  if (el) {
    el.classList.add('active');
  } else {
    const found = document.querySelector('[data-tab="' + id + '"]');
    if (found) found.classList.add('active');
  }
  if (id !== 'overview') {
    const gid = getOfficeGroup(id);
    if (!_groupOpen[gid]) {
      _groupOpen[gid] = true;
      const gEl = document.getElementById('sbg-' + gid);
      if (gEl) gEl.classList.add('open');
    }
  }
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  const panel = document.getElementById('panel-' + id.replace(/\./g, '-'));
  if (panel) {
    panel.classList.add('active');
    const chartCanvas = panel.querySelector('.printer-daily-chart-canvas');
    if (chartCanvas && !chartCanvas.dataset.dailyChartLoaded && !chartCanvas.dataset.dailyChartLoading) {
      chartCanvas.dataset.dailyChartLoading = '1';
      setTimeout(() => {
        loadPrinterDailyChart(id)
          .then(() => {
            chartCanvas.dataset.dailyChartLoaded = '1';
            delete chartCanvas.dataset.dailyChartLoading;
          })
          .catch(err => {
            delete chartCanvas.dataset.dailyChartLoading;
            console.error('Printer chart load failed:', err);
          });
      }, 50);
    }
  }
}

// ══════════════════════════════════════════════════
// OVERVIEW CARDS
// ══════════════════════════════════════════════════
function renderOverviewCards(printers) {
  const grid = document.getElementById('overview-grid');
  if (!printers.length) {
    grid.innerHTML = '<div style="padding:60px;text-align:center;color:var(--text3);font-family:var(--mono)">پرینتری تعریف نشده</div>';
    if (sortableInstance) {
      try {
        sortableInstance.destroy();
      } catch(e) {}
      sortableInstance = null;
    }
    return;
  }

  currentPrinters = printers;
  const orderedPrinters = sortPrintersForDisplay(printers);

  grid.innerHTML = orderedPrinters.map(p => renderPrinterCard(p)).join('');

  if (sortableInstance) {
    try {
      sortableInstance.destroy();
    } catch(e) {
      console.warn("Sortable destroy error:", e);
    }
    sortableInstance = null;
  }

  sortableInstance = new Sortable(grid, {
    animation: 400,
    easing: 'cubic-bezier(0.22, 1, 0.36, 1)',
    sort: true,
    swap: true,
    swapThreshold: 0.65,
    fallbackTolerance: 5,
    delay: 0,
    // class names applied by Sortable for styling
    chosenClass: 'sortable-chosen',
    ghostClass: 'sortable-ghost',
    dragClass: 'sortable-drag',
    // smooth callbacks to update ordering
    onChoose: function(evt) {
      document.body.classList.add('is-dragging');
    },
    onUnchoose: function(evt) {
      document.body.classList.remove('is-dragging');
    },
    onEnd: function(evt) {
      document.body.classList.remove('is-dragging');
      const items = grid.querySelectorAll('.overview-card');
      const newOrder = Array.from(items).map(card => card.getAttribute('data-ip'));
      savePrinterOrder(newOrder);
      setTimeout(() => rebuildTabs(currentPrinters), 50);
    }
  });
}

// ══════════════════════════════════════════════════
// PRINTER DETAIL & SENSOR DETAIL PANELS
// ══════════════════════════════════════════════════
function renderAllPrinterPanels(printers) {
  sortPrintersForDisplay(printers).forEach(p => {
    const id = 'panel-' + p.ip.replace(/\./g,'-');
    let panel = document.getElementById(id);
    if (!panel) {
      panel = document.createElement('div');
      panel.id = id;
      panel.className = 'tab-panel';
      document.querySelector('.main').appendChild(panel);
    }
    
    // تشخیص نوع دستگاه
    if (p.device_type === 'sensor') {
      panel.innerHTML = buildSensorDetail(p);
    } else {
      panel.innerHTML = buildPrinterDetail(p);
    }
    
    const logId = 'plog-' + p.ip.replace(/\./g,'-');
    const printerEvents = allEvents.filter(e => e.printer_ip === p.ip);
    renderLogTable(printerEvents, logId, logId+'-count');
  });
}

function buildPrinterDetail(p) {
  if (!p.online && p.online !== null) return `
    <div class="offline-banner">
      <h2>🔌 آفلاین</h2>
      <div class="offline-message">${p.ip} — ${p.error || 'Device unreachable'}</div>
      <div style="margin-top:8px;font-size:11px;color:var(--red);font-family:var(--mono)">آخرین بررسی: ${p.last_poll ? new Date(p.last_poll).toLocaleTimeString('fa-IR') : '—'}</div>
      <button class="btn btn-cyan" style="margin-top:16px" onclick="removePrinter('${p.ip}','${p.name}')">× حذف پرینتر</button>
    </div>`;

  if (p.online === null) return `<div style="padding:60px;text-align:center;color:var(--text3);font-family:var(--mono)">در حال بررسی...</div>`;

  const c = p.counters || {}; const pz = p.paper_sizes || {};
  const toners = p.toners || {};
  const dev = p.device || {}; const alerts = p.alerts || [];
  const total = c.total || 0;
  const fc = c.full_color || 0;
  const bw = c.black_white || 0;
  const fcPct = total > 0 ? Math.round((fc / total) * 100) : 0;
  const bwPct = total > 0 ? Math.round((bw / total) * 100) : 0;
  const scan  = (c.scan_fc||0)+(c.scan_bw||0)+(c.scan_net_fc||0)+(c.scan_net_bw||0);

  const maxP = Math.max(...Object.values(pz).map(v=>v.total||0), 1);
  const PCOLS = {A4:{cls:'pb-a4',clr:'#00d4ff'},A3:{cls:'pb-a3',clr:'#ff7043'},A4R:{cls:'pb-a4r',clr:'#ffd740'},A5:{cls:'pb-a5',clr:'#00e676'},B4:{cls:'pb-b4',clr:'#ea80fc'}};
  const paperRows = Object.entries(pz).map(([size,d])=>{
    if (!d.total) return '';
    const pct = Math.round(d.total/maxP*100);
    const col = PCOLS[size]||PCOLS.A4;
    return `<div class="psize-row">
      <span class="pb ${col.cls}">${size}</span>
      <div class="pbar-wrap"><div class="pbar-fill" style="width:${pct}%;background:${col.clr}"></div></div>
      <div>
        <div class="pbar-count num">${fmtN(d.total)}</div>
        <div class="pbar-sub">FC:${fmtN(d.fc)} BW:${fmtN(d.bw)}</div>
      </div>
    </div>`;
  }).join('');

  // ═══ بخش جدید: کارتریج‌ها ─────────────────────────────────
  const cartridgeRows = ['black','cyan','magenta','yellow']
    .map(col => {
      const td = toners[col] || {};
      if (!td.name && !td.level) return ''; // نمایش نده اگر داده‌ای نیست
      const name = td.name || {black:'تونر سیاه',cyan:'تونر فیروزه‌ای',magenta:'تونر قرمز',yellow:'تونر زرد'}[col];
      const capacity = td.max ? `${fmtN(td.max)} صفحه` : 'نامشخص';
      const remaining = td.level !== undefined && td.level !== null ? `${td.level}%` : 'نامشخص';
      const status = td.status || 'unknown';
      const statusMap = {ok:'سالم', low:'کم', critical:'بحرانی', empty:'خالی', unknown:'نامشخص'};
      const statusText = statusMap[status] || status;
      const statusColor = {ok:'var(--green)', low:'var(--yellow)', critical:'var(--red)', empty:'var(--red)'}[status] || 'var(--text3)';
      
      const dotColor = {black:'#9e9e9e', cyan:'#00d4ff', magenta:'#ea80fc', yellow:'#ffd740'}[col] || '#9e9e9e';
      
      return `<div class="cartridge-card">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
          <div class="cartridge-dot" style="background:${dotColor};width:12px;height:12px;border-radius:50%;box-shadow:0 0 6px ${dotColor}40"></div>
          <span style="font-weight:600;color:var(--text)">${escapeHtml(name)}</span>
        </div>
        <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--text2);margin-bottom:6px">
          <span>ظرفیت: <strong>${capacity}</strong></span>
          <span>باقی: <strong style="color:${statusColor}">${remaining}</strong></span>
        </div>
        <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--text3)">
          <span>وضعیت: <strong style="color:${statusColor};text-transform:capitalize">${statusText}</strong></span>
        </div>
      </div>`;
    }).filter(row => row !== '').join('');

  const TCOLORS = {cyan:'#00d4ff',magenta:'#ea80fc',yellow:'#ffd740',black:'#9e9e9e'};
  const TGRADS  = {cyan:'#00d4ff,#0097a7',magenta:'#ea80fc,#ab47bc',yellow:'#ffd740,#f9a825',black:'#bdbdbd,#757575'};
  
  // ═══ تغییر: فقط تونرهایی که level > 0 دارند یا device_type == 'color' است ═══
  const isColorPrinter = (p.device_type === 'color');
  const tonerCards = ['cyan','magenta','yellow','black']
    .filter(col => {
      // تونر مشکی همیشه نمایش داده شود
      if (col === 'black') return true;
      // تونرهای رنگی فقط اگر پرینتر رنگی باشد
      if (!isColorPrinter) return false;
      // یا اگر level > 0 باشد
      const td = toners[col] || {};
      return (td.level || 0) > 0;
    })
    .map(col => {
      const td = toners[col] || {};
      const hasLevel = td.level !== undefined && td.level !== null;
      const lvl = hasLevel ? td.level : 0;
      const consumptionPct = hasLevel ? Math.min(100, Math.max(0, 100 - lvl)) : 0;
      const clr = TCOLORS[col];
      const sc = td.status || '?';
      const scCls = {ok:'ts-ok',low:'ts-low',critical:'ts-critical',empty:'ts-empty'}[sc] || 'ts-ok';
      const pctClr = lvl > 50 ? 'var(--green)' : lvl > 20 ? 'var(--yellow)' : 'var(--red)';
      const dots = td.usage || 0;
      const dotM = td.usage_m || 0;
      const dotsBar = total > 0 ? Math.min(100, Math.round(dots / Math.max(...Object.values(toners).map(t2 => t2.usage || 1)) * 100)) : 0;
      return `<div class="toner-card">
        <div class="toner-head">
          <div class="toner-name"><div class="toner-dot" style="background:${clr};box-shadow:0 0 6px ${clr}40"></div>${ {cyan:'Cyan',magenta:'Magenta',yellow:'Yellow',black:'Black'}[col] }</div>
          <span class="toner-status-badge ${scCls}">${sc.toUpperCase()}</span>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:6px">
          <span class="toner-pct-big num" style="color:${pctClr}">${lvl}%</span>
        </div>
        <div class="toner-bar-bg"><div class="toner-bar-fill" style="width:${lvl}%;background:linear-gradient(90deg,${TGRADS[col]})"></div></div>
        <div class="divider" style="margin:8px 0"></div>
        <div class="section-title" style="font-size:9px;margin-bottom:6px">📊 آمار مصرف</div>
        <div class="toner-stats">
          <div class="toner-stat"><span class="toner-stat-lbl">Dot Count</span><span class="toner-stat-val num">${fmtN(dots)}</span></div>
          <div class="toner-stat"><span class="toner-stat-lbl">Mega Dots</span><span class="toner-stat-val num">${dotM}M</span></div>
        </div>
        ${hasLevel ? `
        <div style="margin-top:8px">
          <div style="font-family:var(--mono);font-size:9px;color:var(--text3);margin-bottom:3px">تخمین مصرف</div>
          <div class="toner-bar-bg"><div class="toner-bar-fill" style="width:${consumptionPct}%;background:${clr}40;border:1px solid ${clr}60"></div></div>
        </div>
        ` : ''}
      </div>`;
    }).join('');

  const alertsHtml = alerts.length ? `<div class="section" style="margin-top:14px">
    <div class="section-title">🚨 هشدارهای فعال</div>
    ${alerts.map(a=>`<div class="alert-row"><span style="font-size:14px">⚠️</span><span class="alert-text">${a.message}</span><span class="alert-code">#${a.code}</span></div>`).join('')}
  </div>` : '';

  const ip = p.ip;
  const logId = 'plog-' + ip.replace(/\./g,'-');
  const displayName = p.nickname ? escapeHtml(p.nickname) : escapeHtml(p.name);
  const nicknameButtonHtml = canEditPrinters()
    ? `<button class="btn btn-sm" onclick="editNickname('${p.ip}', '${escapeHtml(p.nickname || '')}')" 
                 style="font-size:10px; margin-right:8px; padding:2px 6px;">✏️</button>`
    : '';
  const nameLine = p.nickname
    ? `<div style="font-size:16px;font-weight:700;margin-top:2px">
         ${displayName}
         ${nicknameButtonHtml}
       </div>
       <div style="font-family:var(--mono);font-size:10px;color:var(--text3);margin-top:2px">نام اصلی: ${escapeHtml(p.name)}</div>`
    : `<div style="font-size:16px;font-weight:700;margin-top:2px">
         ${displayName}
          ${nicknameButtonHtml}
       </div>`;

  // ✅ باگ #6: حذف دکمه حذف تکراری — فقط printerDeleteButtonHtml استفاده می‌شود
  const printerDeleteButtonHtml = canEditPrinters()
    ? `<button class="btn btn-sm btn-orange" onclick="removePrinter('${p.ip}','${escapeHtml(p.name)}')" style="font-size:9px">× حذف</button>`
    : '';

  const printerLogActionsHtml = canAdmin()
    ? `
        <button class="btn btn-cyan" onclick="openEvModal('${ip}','SERVICE')" style="font-size:11px">🔧 ثبت سرویس</button>
        <button class="btn btn-yellow" onclick="openEvModal('${ip}','REFILL')" style="font-size:11px">🖨 شارژ کارتریج</button>
        <input type="datetime-local" class="printer-log-start" data-ip="${ip}" style="width:auto; font-family:var(--mono); font-size:11px;" title="شروع بازه">
        <input type="datetime-local" class="printer-log-end" data-ip="${ip}" style="width:auto; font-family:var(--mono); font-size:11px;" title="پایان بازه">
        <button class="btn btn-cyan" onclick="applyDateFilter('${ip}')">🔍 اعمال فیلتر</button>
        <button class="btn btn-yellow" onclick="exportLogsWithRange('${ip}', 'excel')">↓ Excel (بازه)</button>
        <button class="btn btn-orange" onclick="exportLogsWithRange('${ip}', 'csv')">↓ CSV (بازه)</button>
        <button class="btn btn-yellow" onclick="exportPrinterLogExcel('${ip}')">↓ Excel</button>
        <button class="btn btn-orange" onclick="exportPrinterLogJSON('${ip}')">↓ JSON</button>
        <button class="btn" style="border-color:rgba(255,61,61,.3);color:var(--red);background:rgba(255,61,61,.06)" onclick="clearPrinterLog('${ip}')">× پاک</button>
      `
    : canManage()
      ? `
        <input type="datetime-local" class="printer-log-start" data-ip="${ip}" style="width:auto; font-family:var(--mono); font-size:11px;" title="شروع بازه">
        <input type="datetime-local" class="printer-log-end" data-ip="${ip}" style="width:auto; font-family:var(--mono); font-size:11px;" title="پایان بازه">
        <button class="btn btn-cyan" onclick="applyDateFilter('${ip}')">🔍 اعمال فیلتر</button>
        <button class="btn btn-yellow" onclick="exportLogsWithRange('${ip}', 'excel')">↓ Excel (بازه)</button>
        <button class="btn btn-yellow" onclick="exportPrinterLogExcel('${ip}')">↓ Excel</button>
      `
      : '';

  // ========== بخش جدید آمار با نوارهای افقی ==========
  const isColorDeviceType = (p.device_type === 'color');
  const statsCardHtml = `
    <div class="stats-card">
      <div class="stats-card-header">
        <span class="stats-icon">📊</span>
        <span class="stats-title">آمار کپی و چاپ</span>
        <span class="stats-badge">${new Date().toLocaleDateString('fa-IR')}</span>
      </div>
      <div class="stats-body">
        <div class="stat-total">
          <div class="stat-total-label">کل چاپ</div>
          <div class="stat-total-value">${fmtN(total)}</div>
          <div class="stat-total-divider"></div>
        </div>
        ${isColorDeviceType ? `
        <div class="stat-row">
          <div class="stat-label">
            <span class="stat-dot">🎨</span>
            <span>رنگی</span>
          </div>
          <div class="stat-bar-wrapper">
            <div class="stat-bar" style="width: ${fcPct}%; background: linear-gradient(90deg, var(--cyan), #0097a7);"></div>
          </div>
          <div class="stat-value">${fmtN(fc)} <span class="stat-percent">(${fcPct}%)</span></div>
        </div>
        ` : ''}
        <div class="stat-row">
          <div class="stat-label">
            <span class="stat-dot">⚫</span>
            <span>سیاه‌سفید</span>
          </div>
          <div class="stat-bar-wrapper">
            <div class="stat-bar" style="width: ${bwPct}%; background: linear-gradient(90deg, var(--text2), #757575);"></div>
          </div>
          <div class="stat-value">${fmtN(bw)} <span class="stat-percent">(${bwPct}%)</span></div>
        </div>
      </div>
      <div class="stats-footer">
        <div class="stats-note">آخرین به‌روزرسانی: ${new Date(p.last_poll).toLocaleTimeString('fa-IR')}</div>
      </div>
    </div>
  `;

  // بخش شمارنده‌های اضافی (پرینتر، کپی، فکس، اسکن) به صورت دو ستونی
  const extraCountersHtml = `
    <div class="detail-grid" style="margin-top:10px">
      <div style="display:flex;flex-direction:column;gap:6px">
        ${[['Printer',c.printer,'var(--text2)'],['Copy',c.copy ?? total,'var(--magenta)'],['Fax',c.fax,'var(--blue)'],['List',c.list ?? total,'var(--text3)']]
          .filter(([l,v,clr])=>{
            // Printer: همیشه نمایش داده شود
            if(l==='Printer') return true;
            // Copy: فقط اگر مقدار واقعی و متفاوت از total باشد
            if(l==='Copy') return (c.copy!==null && c.copy!==undefined && c.copy!==total);
            // List: فقط اگر مقدار واقعی و متفاوت از total باشد
            if(l==='List') return (c.list!==null && c.list!==undefined && c.list!==total);
            // Fax: فقط اگر مقدار واقعی (نه null/undefined نه 0) باشد
            if(l==='Fax') return (c.fax!==null && c.fax!==undefined && c.fax!==0);
            return false;
          })
          .map(([l,v,clr])=>`
          <div style="display:flex;justify-content:space-between;padding:5px 10px;background:var(--bg4);border-radius:5px;border:1px solid var(--border)">
            <span style="font-family:var(--mono);font-size:10px;color:var(--text3)">${l}</span>
            <span style="font-family:var(--mono);font-size:11px;font-weight:700;color:${clr}">${fmtN(v)}</span>
          </div>`).join('')}
      </div>
      <div style="display:flex;flex-direction:column;gap:6px">
        ${[['Scan FC',c.scan_fc,'var(--cyan)'],['Scan BW',c.scan_bw,'var(--text2)'],['Net Scan FC',c.scan_net_fc,'var(--cyan)'],['Net Scan BW',c.scan_net_bw,'var(--text2)']]
          .filter(([l,v,clr])=>v!==null && v!==undefined)
          .map(([l,v,clr])=>`
          <div style="display:flex;justify-content:space-between;padding:5px 10px;background:var(--bg4);border-radius:5px;border:1px solid var(--border)">
            <span style="font-family:var(--mono);font-size:10px;color:var(--text3)">${l}</span>
            <span style="font-family:var(--mono);font-size:11px;font-weight:700;color:${clr}">${fmtN(v)}</span>
          </div>`).join('')}
      </div>
    </div>
  `;

  return `
    <div class="section" style="margin-bottom:14px">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
        <div>
          <div style="font-family:var(--mono);font-size:12px;color:var(--cyan)">${p.ip}</div>
          ${nameLine}
          <div style="font-family:var(--mono);font-size:10px;color:var(--text3);margin-top:2px">${dev.model} · S/N: ${dev.serial} · FW: ${dev.firmware} · Uptime: ${dev.uptime_str}</div>
        </div>
        <div style="display:flex;gap:8px;align-items:center">
          <div style="text-align:center"><div style="font-family:var(--mono);font-size:9px;color:var(--text3)">Response</div><div style="font-family:var(--mono);font-size:13px;color:var(--cyan)">${p.poll_ms}ms</div></div>
          ${printerDeleteButtonHtml}
        </div>
      </div>
    </div>

    <div class="section" style="margin-bottom:14px">
      <div class="section-title">📊 کانترهای چاپ</div>
      ${statsCardHtml}
      ${extraCountersHtml}
    </div>

    <div class="detail-grid" style="margin-bottom:14px">
      <div class="section">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <div class="section-title">📦 کارتریج‌ها</div>
          ${canManage() ? `<button class="btn btn-cyan" onclick="openTonerResetModal('${ip}')" style="font-size:12px">تنظیم مجدد کارتریج</button>` : ''}
        </div>
        <div class="cartridge-rows">${cartridgeRows||'<span style="color:var(--text3);font-size:11px">اطلاعات موجود نیست</span>'}</div>
      </div>
      <div class="section"><div class="section-title">📈 نمودار مصرف روزانه (۳۰ روز اخیر)</div>
        <div style="position:relative;height:280px;">
          <canvas id="printer-daily-chart-${ip.replace(/\./g,'-')}" class="printer-daily-chart-canvas" style="width:100%;height:100%;"></canvas>
        </div>
      </div>
    </div>

    <div class="section" style="margin-bottom:14px">
      <div class="section-title">🎨 تونر — سطح و آمار مصرف</div>
      <div class="toner-grid">${tonerCards}</div>
    </div>

    ${alertsHtml}

    <div class="section" style="margin-top:14px">
      <div class="section-title">📋 رویدادهای این دستگاه</div>
      <div class="log-toolbar">
        <div class="log-filter" id="filter-${ip.replace(/\./g,'-')}">
          <button class="filter-btn" onclick="filterLog('all',this,'${logId}')">همه</button>
          <button class="filter-btn" onclick="filterLog('ALERT',this,'${logId}')">هشدار</button>
          <button class="filter-btn active" onclick="filterLog('PRINT',this,'${logId}')">چاپ</button>
          <button class="filter-btn" onclick="filterLog('STATUS',this,'${logId}')">وضعیت</button>
          <button class="filter-btn" onclick="filterLog('SERVICE',this,'${logId}')">🔧 سرویس</button>
          <button class="filter-btn" onclick="filterLog('REFILL',this,'${logId}')">🖨 شارژ</button>
        </div>
        <span class="log-count" id="${logId}-count"></span>
        <button class="btn btn-cyan" onclick="openEvModal('${ip}','SERVICE')" style="font-size:11px">🔧 ثبت سرویس</button>
        <button class="btn btn-yellow" onclick="openEvModal('${ip}','REFILL')" style="font-size:11px">🖨 شارژ کارتریج</button>
        <input type="datetime-local" class="printer-log-start" data-ip="${ip}" style="width:auto; font-family:var(--mono); font-size:11px;" title="شروع بازه">
        <input type="datetime-local" class="printer-log-end" data-ip="${ip}" style="width:auto; font-family:var(--mono); font-size:11px;" title="پایان بازه">
        <button class="btn btn-cyan" onclick="applyDateFilter('${ip}')">🔍 اعمال فیلتر</button>
        <button class="btn btn-yellow" onclick="exportLogsWithRange('${ip}', 'excel')">↓ Excel (بازه)</button>
        <button class="btn btn-orange" onclick="exportLogsWithRange('${ip}', 'csv')">↓ CSV (بازه)</button>
        <button class="btn btn-yellow" onclick="exportPrinterLogExcel('${ip}')">↓ Excel</button>
        <button class="btn btn-orange" onclick="exportPrinterLogJSON('${ip}')">↓ JSON</button>
        <button class="btn" style="border-color:rgba(255,61,61,.3);color:var(--red);background:rgba(255,61,61,.06)" onclick="clearPrinterLog('${ip}')">× پاک</button>
      </div>
      <div id="${logId}"></div>
    </div>`;
}

function buildSensorDetail(p) {
  if (!p.online && p.online !== null) return `
    <div class="offline-banner">
      <h2>🔴 آفلاین</h2>
      <div class="offline-message">${p.ip} — ${p.error || 'دستگاه در دسترس نیست'}</div>
      ${canEditPrinters() ? `<button class="btn btn-cyan" style="margin-top:16px" onclick="removePrinter('${p.ip}','${p.name}')">× حذف دستگاه</button>` : ''}
    </div>`;

  if (p.online === null) return `<div style="padding:60px;text-align:center">⏳ در حال بررسی...</div>`;

  const dev = p.device || {};
  const c = p.counters || {};
  const displayName = p.nickname ? `${p.nickname} (${p.name})` : p.name;
  const sensorDeleteButtonHtml = canEditPrinters()
    ? `<button class="btn btn-orange" onclick="removePrinter('${p.ip}','${p.name}')" style="font-size:10px">× حذف</button>`
    : '';
  const sensorLogActionsHtml = canAdmin()
    ? `
        <button class="btn btn-yellow" onclick="exportPrinterLogExcel('${p.ip}')">↓ Excel</button>
        <button class="btn btn-orange" onclick="exportPrinterLogJSON('${p.ip}')">↓ JSON</button>
        <button class="btn" style="border-color:red" onclick="clearPrinterLog('${p.ip}')">× پاک</button>
      `
    : canManage()
      ? `<button class="btn btn-yellow" onclick="exportPrinterLogExcel('${p.ip}')">↓ Excel</button>`
      : '';

  // Helper برای نمایش وضعیت سنسور
  const statusBadge = (status) => {
    if (status === 'active') return '<span style="color:var(--green); font-weight:700">⦿ فعال</span>';
    return '<span style="color:var(--text3)">⦾ غیرفعال</span>';
  };

  // ردیف یک سنسور (دما یا رطوبت)
  const sensorRow = (label, value, unit, status) => `
    <div class="sensor-row">
      <div class="sensor-row-left">
        <span class="sensor-icon">${unit === '°C' ? '🌡️' : '💧'}</span>
        <span class="sensor-label">${label}</span>
        <span class="sensor-status">${statusBadge(status)}</span>
      </div>
      <div class="sensor-value" style="color:${unit === '°C' ? 'var(--cyan)' : 'var(--blue)'}">
        ${value !== null && value !== undefined ? value + unit : '—'}
      </div>
    </div>
  `;

  return `
    <div class="section" style="margin-bottom:14px">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
        <div>
          <div style="font-family:var(--mono);font-size:12px;color:var(--orange)">${p.ip} 🌡️</div>
          <div style="font-size:18px;font-weight:700;margin-top:4px">${displayName}</div>
          <div style="font-family:var(--mono);font-size:10px;color:var(--text3)">
            ${dev.model || 'ECS100G'} · S/N: ${dev.serial || '—'} · FW: ${dev.firmware || '—'}
          </div>
        </div>
        <div style="display:flex;gap:8px;align-items:center">
          <div style="text-align:center"><div style="font-size:9px;color:var(--text3)">Response</div><div style="font-size:13px;color:var(--cyan)">${p.poll_ms}ms</div></div>
          ${sensorDeleteButtonHtml}
        </div>
      </div>
    </div>

    <!-- کارت‌های دما و رطوبت در یک detail-grid -->
    <div class="detail-grid" style="margin-bottom:14px">
      <div class="section">
        <div class="section-title">🌡️ دما</div>
        ${sensorRow('پورت ۱', c.temp1, '°C', c.temp1_status)}
        ${sensorRow('پورت ۲', c.temp2, '°C', c.temp2_status)}
      </div>
      <div class="section">
        <div class="section-title">💧 رطوبت</div>
        ${sensorRow('پورت ۱', c.hum1, '%', c.hum1_status)}
        ${sensorRow('پورت ۲', c.hum2, '%', c.hum2_status)}
      </div>
    </div>

    <!-- اطلاعات دستگاه -->
    <div class="section" style="margin-bottom:14px">
      <div class="section-title">📋 اطلاعات دستگاه</div>
      <div class="info-grid">
        ${[
          ['مدل', dev.model || 'ECS100G'],
          ['سریال', dev.serial || '—'],
          ['Firmware', dev.firmware || '—'],
          ['Uptime', dev.uptime_str || '—'],
          ['آخرین بروزرسانی', p.last_poll ? new Date(p.last_poll).toLocaleTimeString('fa-IR') : '—']
        ].map(([label, value]) => `
          <div class="info-item">
            <span class="info-label">${label}</span>
            <span class="info-value">${value}</span>
          </div>
        `).join('')}
      </div>
    </div>

    <!-- لاگ رویدادها -->
    <div class="section" style="margin-top:14px">
      <div class="section-title">📋 رویدادهای دستگاه</div>
      <div class="log-toolbar">
        <div class="log-filter" id="filter-${p.ip.replace(/\./g,'-')}">
          <button class="filter-btn active" onclick="filterLog('all',this,'plog-${p.ip.replace(/\./g,'-')}')">همه</button>
          <button class="filter-btn" onclick="filterLog('ALERT',this,'plog-${p.ip.replace(/\./g,'-')}')">هشدار</button>
        </div>
        <span class="log-count" id="plog-${p.ip.replace(/\./g,'-')}-count"></span>
        ${sensorLogActionsHtml}
      </div>
      <div id="plog-${p.ip.replace(/\./g,'-')}"></div>
    </div>`;
}

// ══════════════════════════════════════════════════
// LOG RENDER (بدون تغییر)
// ══════════════════════════════════════════════════
function _buildRows(events, hasPrinter, hasUser) {
  const SEV = {error:'sev-error',warning:'sev-warning',success:'sev-success',info:'sev-info'};
  return events.map(e => {
    const ts     = (e.timestamp || '').slice(0, 19).replace('T', ' ');
    const sev    = e.severity || 'info';
    const badge  = `<span class="sev-badge ${SEV[sev] || 'sev-info'}">${escapeHtml(sev.toUpperCase())}</span>`;
    const tbadge = `<span class="type-badge">${escapeHtml(e.type || '—')}</span>`;
    
    const pCell = hasPrinter
      ? `<td>${escapeHtml(e.printer_name || '—')}<br><span style="color:var(--text3);font-size:9px">${escapeHtml(e.printer_ip || '—')}</span></td>`
      : '';

    const uCell = hasUser
      ? `<td style="font-family:var(--mono);font-size:10px">${escapeHtml(e.username || '—')}</td>`
      : '';

    let message = e.message ? escapeHtml(e.message) : '—';
    let pages   = (e.pages !== undefined && e.pages !== null && e.pages !== '') ? escapeHtml(String(e.pages)) : '—';
    let color   = e.color ? escapeHtml(e.color) : '—';
    let code    = e.code ? escapeHtml(e.code) : '—';

    let pages_display = pages;
    if (e.type === 'PRINT' && pages !== '—' && !isNaN(parseInt(pages))) {
      if (e.paper_size && e.paper_size !== '') {
        pages_display = `${pages} (${e.paper_size})`;
      }
    }

    return `<tr data-type="${escapeHtml(e.type || '')}">
      <td style="direction:ltr">${escapeHtml(ts)}</td>
      ${pCell}
      <td>${tbadge}</td>
      <td style="color:var(--text)">${message}</td>
      <td class="num">${pages_display}</td>
      <td>${color}</td>
      ${uCell}
      <td>${code}</td>
      <td>${badge}</td>
    </tr>`;
  }).join('');
}
function _buildPagination(containerId, total, page, pageSize) {
  if (total <= pageSize) return '';
  const totalPages = Math.ceil(total / pageSize);
  if (totalPages <= 1) return '';

  const start = (page - 1) * pageSize + 1;
  const end   = Math.min(page * pageSize, total);

  const show = new Set([1, totalPages, page, page-1, page+1, page-2, page+2]
    .filter(p => p >= 1 && p <= totalPages));
  const pages = [...show].sort((a,b) => a-b);

  let btns = '';
  let prev = 0;
  for (const p of pages) {
    if (prev && p - prev > 1) btns += `<span class="pg-dots">…</span>`;
    btns += `<button class="pg-btn${p===page?' active':''}"
      onclick="_pgGoto('${containerId}',${p})">${p}</button>`;
    prev = p;
  }

  return `<div class="log-pagination">
    <button class="pg-btn pg-arrow" onclick="_pgGoto('${containerId}',${page-1})"
      ${page<=1?'disabled':''}>&#8249;</button>
    ${btns}
    <button class="pg-btn pg-arrow" onclick="_pgGoto('${containerId}',${page+1})"
      ${page>=totalPages?'disabled':''}>&#8250;</button>
    <span class="pg-info">${start}–${end} از ${total}</span>
  </div>`;
}

function _pgRender(containerId, counterId) {
  const st  = _pgState[containerId];
  const el  = document.getElementById(containerId);
  const cnt = document.getElementById(counterId);
  if (!st || !el) return;

  const filtered = st.filterType === 'all'
    ? st.events
    : st.events.filter(e => e.type === st.filterType);

  if (!filtered.length) {
    el.innerHTML = '<div class="log-empty">رویدادی یافت نشد</div>';
    if (cnt) cnt.textContent = '';
    return;
  }

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  if (st.page > totalPages) st.page = totalPages;

  const slice      = filtered.slice((st.page-1)*PAGE_SIZE, st.page*PAGE_SIZE);
  const hasPrinter = st.events.some(e => e.printer_name);
  const hasUser    = st.events.some(e => e.username);

  const tableHTML = `<table class="log-table"><thead><tr>
    <th>زمان</th>${hasPrinter?'<th>دستگاه</th>':''}
    <th>نوع</th><th>پیام</th><th>صفحات</th><th>رنگ</th>${hasUser?'<th>کاربر/سیستم</th>':''}<th>کد</th><th>اهمیت</th>
   </thead><tbody>${_buildRows(slice, hasPrinter, hasUser)}</tbody></table>`;

  const pgHTML = _buildPagination(containerId, filtered.length, st.page, PAGE_SIZE);

  el.innerHTML = tableHTML + pgHTML;
  if (cnt) cnt.textContent = `${filtered.length} رویداد — صفحه ${st.page} از ${Math.ceil(filtered.length/PAGE_SIZE)}`;
}

function _pgGoto(containerId, page) {
  const st = _pgState[containerId];
  if (!st) return;
  const filtered = st.filterType === 'all'
    ? st.events
    : st.events.filter(e => e.type === st.filterType);
  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  st.page = Math.max(1, Math.min(page, totalPages));
  const el = document.getElementById(containerId);
  if (el) el.scrollIntoView({behavior:'smooth', block:'nearest'});
  _pgRender(containerId, st.counterId);
}

function renderLogTable(events, containerId, counterId) {
  _pgState[containerId] = {
    events:     events,
    page:       1,
    filterType: _pgState[containerId]?.filterType || 'all',
    counterId:  counterId,
  };
  _pgRender(containerId, counterId);
}

function renderGlobalLog(events) {
  const curPage = _pgState['global-log']?.page || 1;
  _pgState['global-log'] = {
    events:     events,
    page:       curPage,
    filterType: _pgState['global-log']?.filterType || 'all',
    counterId:  'global-log-count',
  };
  _pgRender('global-log', 'global-log-count');
}

function filterLog(type, btn, containerId) {
  const parent = btn.closest('.log-filter');
  if (parent) {
    parent.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
  }
  const st = _pgState[containerId];
  if (!st) return;
  st.filterType = type;
  st.page       = 1;
  _pgRender(containerId, st.counterId);
}

// ══════════════════════════════════════════════════
// DATE FILTER
// ══════════════════════════════════════════════════
async function applyDateFilter(ip) {
  const { start, end } = getLogRange(ip);
  let url = `${API}/api/logs/all?limit=10000`;
  if (start) url += `&start=${encodeURIComponent(start)}`;
  if (end) url += `&end=${encodeURIComponent(end)}`;
  if (ip) url += `&ip=${encodeURIComponent(ip)}`;

  try {
    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) throw new Error('خطا در دریافت لاگ‌ها');
    const data = await response.json();
    const events = data.events || [];

    if (ip) {
      const logId = 'plog-' + ip.replace(/\./g,'-');
      renderLogTable(events, logId, logId+'-count');
    } else {
      renderLogTable(events, 'global-log', 'global-log-count');
    }
    if (_pgState['global-log']) _pgState['global-log'].page = 1;
    toast(`${events.length} رویداد یافت شد`, 's');
  } catch (e) {
    console.error(e);
    toast('خطا در اعمال فیلتر', 'e');
  }
}

// ══════════════════════════════════════════════════
// ACCESS PANEL
// ══════════════════════════════════════════════════
function renderAccessPanel(st) {
  const panel = document.getElementById('access-panel');
  const grid = document.getElementById('access-grid');
  if (!panel || !grid) return;

  // پاک کردن محتوای قبلی
  grid.innerHTML = '';

  // استفاده از آدرس فعلی صفحه (پروتکل + هاست) به جای IP ثابت
  const baseUrl = window.location.origin;   // مثال: https://khak-va-sazeh.ir یا http://172.16.25.82:5050

  const urls = [
    { title: 'داشبورد (همین صفحه)', url: baseUrl + '/' },
    { title: 'API — همه پرینترها', url: baseUrl + '/api/printers' },
    { title: 'API — رویدادها', url: baseUrl + '/api/logs/all' },
    { title: 'خروجی Excel', url: baseUrl + '/api/export/excel' },
  ];

  grid.innerHTML = urls.map(u => `
    <div class="access-card">
      <div class="access-card-title">${u.title}</div>
      <div class="access-url" onclick="copyURL(this,'${u.url}')" title="کلیک برای کپی">${u.url}</div>
      <div class="qr-hint">کلیک برای کپی آدرس</div>
    </div>
  `).join('');

  panel.style.display = 'block';
}

function copyURL(el, url) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(url).then(() => {
      el.classList.add('copied');
      el.textContent = '✓ کپی شد';
      setTimeout(() => { el.classList.remove('copied'); el.textContent = url; }, 2000);
      toast('آدرس کپی شد', 's');
    }).catch(() => {
      fallbackCopy(el, url);
    });
  } else {
    fallbackCopy(el, url);
  }
}

function fallbackCopy(el, url) {
  const textarea = document.createElement('textarea');
  textarea.value = url;
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  try {
    const successful = document.execCommand('copy');
    if (successful) {
      el.classList.add('copied');
      el.textContent = '✓ کپی شد';
      setTimeout(() => { el.classList.remove('copied'); el.textContent = url; }, 2000);
      toast('آدرس کپی شد', 's');
    } else {
      toast('کپی با شکست مواجه شد', 'e');
    }
  } catch (err) {
    toast('خطا در کپی', 'e');
  }
  document.body.removeChild(textarea);
}

// ══════════════════════════════════════════════════
// EXPORT FUNCTIONS
// ══════════════════════════════════════════════════
function exportExcel() {
  if (!canManage()) { toast('دسترسی ندارید', 'e'); return; }
  window.location.href = `${API}/api/export/excel`;
  toast('در حال آماده‌سازی فایل Excel...','s');
}
function exportLogExcel() {
  if (!canManage()) { toast('دسترسی ندارید', 'e'); return; }
  window.location.href = `${API}/api/export/excel`;
  toast('خروجی Excel رویدادها...','s');
}
function exportLogJSON() {
  if (!canAdmin()) { toast('دسترسی ندارید', 'e'); return; }
  const data = JSON.stringify({exported: new Date().toISOString(), events: allEvents}, null, 2);
  downloadFile(data, `toshiba_log_${dateStr()}.json`, 'application/json');
}
function exportPrinterLogExcel(ip) {
  if (!canManage()) { toast('دسترسی ندارید', 'e'); return; }
  window.location.href = `${API}/api/export/excel`;
}
function exportPrinterLogJSON(ip) {
  if (!canAdmin()) { toast('دسترسی ندارید', 'e'); return; }
  const events = allEvents.filter(e=>e.printer_ip===ip);
  const data = JSON.stringify({ip, exported:new Date().toISOString(), events}, null, 2);
  downloadFile(data, `log_${ip.replace(/\./g,'_')}_${dateStr()}.json`, 'application/json');
}
function exportJSON() {
  if (!canAdmin()) { toast('دسترسی ندارید', 'e'); return; }
  const data = JSON.stringify({exported: new Date().toISOString(), printers: allData, events: allEvents}, null, 2);
  downloadFile(data, `toshiba_report_${dateStr()}.json`, 'application/json');
}
function downloadFile(content, filename, type) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([content],{type}));
  a.download = filename; a.click();
  toast('فایل در حال دانلود...','s');
}
function dateStr() { return new Date().toISOString().slice(0,19).replace(/[T:]/g,'-'); }

// ══════════════════════════════════════════════════
// LOG RANGE
// ══════════════════════════════════════════════════
function getLogRange(ip) {
  let start, end;
  if (ip) {
    start = document.querySelector(`.printer-log-start[data-ip="${ip}"]`)?.value;
    end = document.querySelector(`.printer-log-end[data-ip="${ip}"]`)?.value;
  } else {
    start = document.getElementById('log-start')?.value;
    end = document.getElementById('log-end')?.value;
  }
  return { start: start || null, end: end || null };
}

async function exportLogsWithRange(ip, format) {
  if (format === 'csv' && !canAdmin()) { toast('دسترسی ندارید', 'e'); return; }
  if (format !== 'csv' && !canManage()) { toast('دسترسی ندارید', 'e'); return; }
  const { start, end } = getLogRange(ip);
  let url = `${API}/api/export/logs?format=${format}`;
  if (start) url += `&start=${encodeURIComponent(start)}`;
  if (end) url += `&end=${encodeURIComponent(end)}`;
  if (ip) url += `&ip=${encodeURIComponent(ip)}`;

  window.location.href = url;
  toast(`در حال دریافت خروجی ${format}...`, 's');
}

// ══════════════════════════════════════════════════
// PRINTER MANAGEMENT
// ══════════════════════════════════════════════════
function showAddModal() {
  if (!canAdmin()) { toast('دسترسی ندارید', 'e'); return; }
  document.getElementById('modal-add').classList.add('show');
  switchAddTab('single', document.querySelector('.modal-tab'));
  document.getElementById('add-ip').focus();
}
function closeModal() {
  document.getElementById('modal-add').classList.remove('show');
  document.getElementById('discover-results').innerHTML = '';
  document.getElementById('bulk-results').innerHTML = '';
  document.getElementById('bulk-submit-btn').style.display = 'none';
  document.getElementById('bulk-input').value = '';
}

function switchAddTab(name, el) {
  document.querySelectorAll('.modal-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.modal-pane').forEach(p => p.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('pane-' + name).classList.add('active');
}

async function doAddPrinter() {
  if (!canAdmin()) { toast('دسترسی ندارید', 'e'); return; }
  const ip        = document.getElementById('add-ip').value.trim();
  const name      = document.getElementById('add-name').value.trim();
  const community = document.getElementById('add-community-single').value.trim() || 'public';
  if (!ip) { toast('IP الزامی است','e'); return; }
  try {
    const r = await fetch(`${API}/api/printers/add`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ip, name, community})});
    const j = await r.json();
    if (!r.ok) { toast(j.error||'خطا','e'); return; }
    toast(`پرینتر ${ip} اضافه شد`,'s');
    closeModal();
    setTimeout(fetchData, 2000);
  } catch(e) { toast('خطا در اتصال','e'); }
}

function parseBulkInput() {
  const lines = document.getElementById('bulk-input').value.split('\n');
  const defaultComm = document.getElementById('add-community-bulk').value.trim() || 'public';
  const existingIPs = new Set(allData.map(p => p.ip));
  const items = [];

  for (let raw of lines) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    const parts = line.split(/\s+/);
    const ip        = parts[0] || '';
    const name      = parts.slice(1, parts.length > 2 ? -1 : undefined)
                           .join(' ')
                           .replace(/['"]/g,'').trim() || '';
    const community = (parts.length > 2 && !parts[parts.length-1].includes('.'))
                      ? parts[parts.length-1]
                      : defaultComm;
    if (!ip) continue;
    items.push({
      ip, name, community,
      exists: existingIPs.has(ip),
      valid: /^\d{1,3}(\.\d{1,3}){3}$/.test(ip),
    });
  }
  return items;
}

function doBulkPreview() {
  const items = parseBulkInput();
  const container = document.getElementById('bulk-results');
  const btn = document.getElementById('bulk-submit-btn');

  if (!items.length) {
    container.innerHTML = '<div style="color:var(--text3);font-family:var(--mono);font-size:11px;padding:8px">هیچ آیتمی پیدا نشد</div>';
    btn.style.display = 'none';
    return;
  }

  const newCount = items.filter(x => x.valid && !x.exists).length;
  container.innerHTML = items.map(it => {
    if (!it.valid)
      return `<div class="bulk-result-row err">✗ ${it.ip} &nbsp;<span style="color:var(--text3)">فرمت IP نامعتبر</span></div>`;
    if (it.exists)
      return `<div class="bulk-result-row skip">⏭ ${it.ip} &nbsp;<span style="color:var(--text3)">قبلاً موجود است</span></div>`;
    return `<div class="bulk-result-row ok">✓ ${it.ip} &nbsp;<span style="color:var(--text2)">${it.name||'—'}</span> &nbsp;<span style="color:var(--text3)">[${it.community}]</span></div>`;
  }).join('');

  btn.style.display = newCount ? 'inline-flex' : 'none';
  if (newCount) btn.textContent = `＋ افزودن ${newCount} پرینتر`;
}

async function doBulkAdd() {
  if (!canAdmin()) { toast('دسترسی ندارید', 'e'); return; }
  const items = parseBulkInput().filter(x => x.valid && !x.exists);
  if (!items.length) { toast('هیچ پرینتر جدیدی وجود ندارد','w'); return; }

  const btn = document.getElementById('bulk-submit-btn');
  btn.disabled = true; btn.textContent = '⏳ در حال افزودن...';

  try {
    const r = await fetch(`${API}/api/printers/bulk-add`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        printers: items.map(({ip,name,community}) => ({ip,name,community})),
        scan: true,
        skip_existing: true,
      })
    });
    const j = await r.json();
    const added   = j.total_added || 0;
    const skipped = (j.skipped || []).length;
    const failed  = (j.failed  || []).length;

    let msg = '';
    if (added)   msg += `${added} پرینتر اضافه شد `;
    if (skipped) msg += `| ${skipped} تکراری `;
    if (failed)  msg += `| ${failed} خطا`;
    toast(msg.trim() || 'انجام شد', added ? 's' : 'w');

    if (added) { closeModal(); setTimeout(fetchData, 3000); }
    else { btn.disabled = false; btn.textContent = `＋ افزودن (${items.length})`; }
  } catch(e) {
    toast('خطا در اتصال','e');
    btn.disabled = false;
  }
}

async function removePrinter(ip, name) {
  if (!canAdmin()) { toast('دسترسی ندارید', 'e'); return; }
  if (!confirm(`پرینتر ${name} (${ip}) حذف شود؟`)) return;
  try {
    const r = await fetch(`${API}/api/printers/remove`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ip})});
    if (r.ok) {
      toast(`پرینتر ${ip} حذف شد`,'w');
      const panel = document.getElementById('panel-' + ip.replace(/\./g,'-'));
      if (panel) panel.remove();
      const tab = document.querySelector(`[data-tab="${ip}"]`);
      switchTab('overview');
      setTimeout(fetchData, 500);
    }
  } catch(e) { toast('خطا','e'); }
}

function addDiscoveryRange() {
  const container = document.getElementById('discovery-ranges');
  const newRow = document.createElement('div');
  newRow.className = 'range-row';
  newRow.innerHTML = `
    <input class="form-input" name="subnet[]" placeholder="172.16.0" value="" style="flex:2">
    <input class="form-input" name="start[]" placeholder="1" value="1" style="flex:1;direction:ltr">
    <input class="form-input" name="end[]" placeholder="254" value="254" style="flex:1;direction:ltr">
    <button type="button" class="btn" style="padding:5px 8px;" onclick="this.parentElement.remove()">✖</button>
  `;
  container.appendChild(newRow);
}

async function doDiscover() {
  if (!canAdmin()) { toast('دسترسی ندارید', 'e'); return; }
  const community = document.getElementById('add-community-discover').value.trim() || 'public';
  const rangeRows = document.querySelectorAll('#discovery-ranges .range-row');
  const ranges = [];
  
  for (let row of rangeRows) {
    const subnet = row.querySelector('input[name="subnet[]"]').value.trim();
    const start = row.querySelector('input[name="start[]"]').value.trim();
    const end = row.querySelector('input[name="end[]"]').value.trim();
    if (subnet && start && end) {
      ranges.push({
        subnet: subnet,
        start: parseInt(start),
        end: parseInt(end)
      });
    }
  }
  
  if (ranges.length === 0) {
    toast('حداقل یک رنج وارد کنید', 'e');
    return;
  }

  const dr = document.getElementById('discover-results');
  dr.innerHTML = `<div style="text-align:center;padding:20px;color:var(--text3);font-family:var(--mono)">🔍 در حال جستجو در ${ranges.length} رنج...</div>`;

  try {
    const r = await fetch(`${API}/api/printers/discover`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ranges, community })
    });
    const j = await r.json();
    if (!j.found.length) {
      dr.innerHTML = '<div style="text-align:center;padding:16px;color:var(--text3);font-family:var(--mono)">هیچ دستگاهی پیدا نشد</div>';
      return;
    }
    const existingIPs = new Set(allData.map(p => p.ip));
    const newDevices  = j.found.filter(f => !existingIPs.has(f.ip));
    const existDevices= j.found.filter(f =>  existingIPs.has(f.ip));
    const allItems    = [...newDevices, ...existDevices];

    dr.innerHTML = allItems.map(f => {
      const isExist = existingIPs.has(f.ip);
      return `
      <div class="discover-item${isExist ? ' discover-existing' : ''}">
        <div>
          <div class="discover-ip">${escapeHtml(f.ip)}
            ${isExist ? '<span class="discover-badge">موجود</span>' : ''}
          </div>
          <div class="discover-model">${escapeHtml(f.model || '')}</div>
        </div>
        ${isExist
          ? '<span style="font-size:10px;color:var(--text3);font-family:var(--mono)">قبلاً اضافه شده</span>'
          : `<button class="btn btn-green" onclick="quickAdd(event, '${escapeHtml(f.ip)}','${escapeHtml((f.model||'').slice(0,20))}')">＋ افزودن</button>`
        }
      </div>`;
    }).join('');

    const msg = newDevices.length
      ? `${newDevices.length} دستگاه جدید یافت شد${existDevices.length ? ` (+${existDevices.length} موجود)` : ''}`
      : `هیچ دستگاه جدیدی یافت نشد (${existDevices.length} دستگاه موجود)`;
    toast(msg, newDevices.length ? 's' : 'w');
  } catch (e) {
    dr.innerHTML = '<div style="color:var(--red);padding:12px;font-family:var(--mono)">خطا در جستجو</div>';
  }
}

async function quickAdd(event, ip, model) {
  // جلوگیری از بسته شدن مودال
  event.stopPropagation();
  
  const community = document.getElementById('add-community-discover').value.trim() || 'public';
  const btn = event.target;  // دکمه‌ای که کلیک شده است
  
  // غیرفعال کردن دکمه در حین درخواست
  btn.disabled = true;
  btn.textContent = '⏳';
  
  try {
    const r = await fetch(`${API}/api/printers/add`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ip, name: model, community })
    });
    const j = await r.json();
    
    if (r.ok) {
      toast(`${ip} اضافه شد`, 's');
      // تغییر ظاهر دکمه به "موجود"
      btn.textContent = '✓ اضافه شد';
      btn.className = 'btn btn-orange';
      btn.disabled = true;
      
      // به‌روزرسانی داده‌ها در پس‌زمینه
      fetchData();
    } else {
      toast(j.error || 'خطا', 'e');
      btn.textContent = '＋ افزودن';
      btn.disabled = false;
    }
  } catch (e) {
    toast('خطا در اتصال', 'e');
    btn.textContent = '＋ افزودن';
    btn.disabled = false;
  }
}

async function clearLogs(ip) {
  if (!canAdmin()) { toast('دسترسی ندارید', 'e'); return; }
  if (!confirm('رویدادهای غیر از PRINT، SERVICE و REFILL پاک شوند؟\nاطلاعات PRINT، SERVICE و REFILL حفظ می‌مانند.')) return;
  const r = await fetch(`${API}/api/logs/clear`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(ip?{ip}:{})});
  if (r.ok) {
    const j = await r.json();
    toast(`${j.deleted || 0} رویداد پاک شد — PRINT، SERVICE و REFILL حفظ شد`, 'w');
    fetchData();
  }
}
async function clearPrinterLog(ip) { await clearLogs(ip); }

// ══════════════════════════════════════════════════
// NICKNAME EDITING
// ══════════════════════════════════════════════════
let _nicknameCallback = null;
let _nicknameIp = null;

function openNicknameModal(ip, currentNickname, callback) {
  _nicknameIp = ip;
  _nicknameCallback = callback;
  const input = document.getElementById('nickname-input');
  input.value = currentNickname || '';
  input.placeholder = 'نام مستعار جدید...';
  const modal = document.getElementById('modal-nickname');
  modal.classList.add('show');
  input.focus();
  input.select();
}

function closeNicknameModal() {
  document.getElementById('modal-nickname').classList.remove('show');
  _nicknameIp = null;
  _nicknameCallback = null;
}

function bindNicknameModalEvents() {
  const saveBtn = document.getElementById('nickname-save');
  const cancelBtn = document.getElementById('nickname-cancel');
  const modalOverlay = document.getElementById('modal-nickname');
  
  if (saveBtn) {
    saveBtn.onclick = () => {
      const newValue = document.getElementById('nickname-input').value.trim();
      if (_nicknameCallback) _nicknameCallback(_nicknameIp, newValue);
      closeNicknameModal();
    };
  }
  if (cancelBtn) {
    cancelBtn.onclick = () => closeNicknameModal();
  }
  if (modalOverlay) {
    modalOverlay.onclick = (e) => {
      if (e.target === modalOverlay) closeNicknameModal();
    };
  }
  const inputField = document.getElementById('nickname-input');
  if (inputField) {
    inputField.onkeypress = (e) => {
      if (e.key === 'Enter' && saveBtn) saveBtn.click();
    };
  }
}

async function editNickname(ip, currentNickname) {
  if (!canAdmin()) { toast('دسترسی ندارید', 'e'); return; }
  openNicknameModal(ip, currentNickname, async (ip, newNick) => {
    try {
      const r = await fetch(`${API}/api/printer/${ip}/rename`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nickname: newNick })
      });
      const j = await r.json();
      if (r.ok) {
        toast(newNick ? 'نام مستعار تغییر کرد' : 'نام مستعار حذف شد', 's');
        fetchData();
      } else {
        toast(j.error || 'خطا', 'e');
      }
    } catch(e) {
      toast('خطا در اتصال', 'e');
    }
  });
}

// ══════════════════════════════════════════════════
// MANUAL EVENT MODAL
// ══════════════════════════════════════════════════
const EV_CONFIG = {
  SERVICE:   { icon:'🔧', iconCls:'service',   title:'ثبت سرویس دستگاه',  color:'var(--cyan)',   btnCls:'btn-cyan',   placeholder:'مثال: تنظیم فیدر کاغذ، تمیزکاری لیزر، تعویض بلت...' },
  REFILL: { icon:'🖨', iconCls:'cartridge', title:'شارژ / تعویض کارتریج', color:'var(--yellow)', btnCls:'btn-yellow', placeholder:'مثال: تعویض تونر مشکی، شارژ سیان، تعویض درام...' },
};

function openEvModal(ip, type) {
  if (!canAdmin()) { toast('دسترسی ندارید', 'e'); return; }
  const cfg = EV_CONFIG[type];
  if (!cfg) return;
  const printer = allData.find(p => p.ip === ip);
  const printerLabel = printer ? `${printer.name} (${ip})` : ip;

  document.getElementById('ev-ip').value     = ip;
  document.getElementById('ev-type').value   = type;
  document.getElementById('ev-modal-icon').textContent  = cfg.icon;
  document.getElementById('ev-modal-icon').className    = `ev-modal-icon ${cfg.iconCls}`;
  document.getElementById('ev-modal-title').textContent = cfg.title;
  document.getElementById('ev-modal-sub').textContent   = printerLabel;
  document.getElementById('ev-notes').placeholder       = cfg.placeholder;
  document.getElementById('ev-notes').value             = '';
  document.getElementById('ev-tech').value              = '';

  const btn = document.getElementById('ev-submit-btn');
  btn.className = `btn ${cfg.btnCls}`;
  btn.textContent = '✓ ثبت رویداد';
  btn.disabled = false;

  document.getElementById('ev-modal').classList.add('show');
  setTimeout(() => document.getElementById('ev-notes').focus(), 100);
}

function closeEvModal() {
  document.getElementById('ev-modal').classList.remove('show');
}

async function submitManualEvent() {
  if (!canAdmin()) { toast('دسترسی ندارید', 'e'); return; }
  const ip    = document.getElementById('ev-ip').value;
  const type  = document.getElementById('ev-type').value;
  const notes = document.getElementById('ev-notes').value.trim();
  const tech  = document.getElementById('ev-tech').value.trim();

  if (!notes) {
    document.getElementById('ev-notes').focus();
    toast('توضیحات را وارد کنید', 'e');
    return;
  }

  let fullMessage = notes;
  if (tech) fullMessage += ` (تکنسین: ${tech})`;

  const btn = document.getElementById('ev-submit-btn');
  btn.disabled = true;
  btn.textContent = '⏳ در حال ثبت...';

  try {
    const r = await fetch(`${API}/api/events/manual`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ip, type, notes, technician: tech }),
    });
    const j = await r.json();
    if (!r.ok) {
      toast(j.error || 'خطا در ثبت رویداد', 'e');
      btn.disabled = false;
      btn.textContent = '✓ ثبت رویداد';
      return;
    }
    const label = type === 'SERVICE' ? 'سرویس' : 'شارژ کارتریج';
    toast(`✓ ${label} ثبت شد`, 's');
    closeEvModal();
    await fetchData();
    const logEl = document.getElementById('plog-' + ip.replace(/\./g,'-'));
    if (logEl) logEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  } catch(e) {
    toast('خطا در اتصال به سرور', 'e');
    btn.disabled = false;
    btn.textContent = '✓ ثبت رویداد';
  }
}

// ══════════════════════════════════════════════════
// POLL & COUNTDOWN
// ══════════════════════════════════════════════════
async function triggerPoll() {
  try {
    const res = await fetch(`${API}/api/poll/now`, { method: 'POST' });
    if (!res.ok) {
      const errBody = await res.text();
      throw new Error(`HTTP ${res.status}: ${errBody}`);
    }
    const data = await res.json();
    if (data.status !== 'started') {
      throw new Error(data.error || 'Unexpected response');
    }
    toast('Pull started', 's');
    setTimeout(fetchData, 2500);
  } catch (err) {
    console.error('Pull failed:', err);
    toast('خطا در شروع Pull', 'e');
  }
}

function resetCountdown() {
  countdown = 40;
  if (countTimer) clearInterval(countTimer);
  countTimer = setInterval(()=>{
    countdown = Math.max(0, countdown-1);
    document.getElementById('cfill').style.width = (countdown/40*100)+'%';
    if (countdown<=0) { clearInterval(countTimer); fetchData(); }
  },1000);
}

// ══════════════════════════════════════════════════
// UI HELPERS
// ══════════════════════════════════════════════════
function setDot(s) {
  const d = document.getElementById('dot');
  const t = document.getElementById('dot-txt');
  d.className = 'dot-live';
  if (s==='on')    { d.classList.add('on'); t.textContent='Live'; }
  else if(s==='fetch'){ d.classList.add('fetch'); t.textContent='Pulling...'; }
  else             { d.style.background='var(--red)'; t.textContent='Error'; }
}

let toastT;
function toast(msg, cls='') {
  const el=document.getElementById('toast'); el.textContent=msg; el.className=`show ${cls}`;
  clearTimeout(toastT); toastT=setTimeout(()=>el.className='',3000);
}

function fmtN(n) {
  if(n==null||n===undefined) return '—';
  return Number(n).toLocaleString('en');
}

// ══════════════════════════════════════════════════
// KEYBOARD SHORTCUTS
// ══════════════════════════════════════════════════
document.addEventListener('keydown',e=>{
  if(e.key==='Escape') { closeModal(); closeEvModal(); closeNicknameModal(); }
  if(e.key==='r'&&(e.ctrlKey||e.metaKey)&&!e.shiftKey){ e.preventDefault(); triggerPoll(); }
});
document.getElementById('modal-add').addEventListener('click',e=>{ if(e.target===document.getElementById('modal-add')) closeModal(); });
document.getElementById('ev-modal').addEventListener('click',e=>{ if(e.target===document.getElementById('ev-modal')) closeEvModal(); });

// ══════════════════════════════════════════════════
// DAILY CHART
// ══════════════════════════════════════════════════
function populatePrinterSelect() {
  const select = document.getElementById('chart-printer-select');
  if (!select) return;
  select.innerHTML = '<option value="">همه پرینترها</option>';
  allData.forEach(p => {
    select.innerHTML += `<option value="${p.ip}">${p.name} (${p.ip})</option>`;
  });
}

async function loadDailyChart() {
  const select = document.getElementById('chart-printer-select');
  const canvas = document.getElementById('dailyChart');
  
  if (!select || !canvas) {
    console.error('Chart elements not found');
    return;
  }
  
  const ip = select.value;
  let url = `${API}/api/stats/daily?days=30`;
  if (ip) url += `&ip=${encodeURIComponent(ip)}`;
  
  try {
    const res = await fetch(url, {cache: 'no-store'});
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    
    if (!data.dates || !data.totals || data.dates.length === 0) {
      toast('داده‌ای برای نمایش وجود ندارد', 'w');
      return;
    }
    
    if (chartInstance) {
      try {
        chartInstance.destroy();
      } catch (e) {
        console.warn('Chart destroy warning:', e);
      }
      chartInstance = null;
    }
    
    const persianDates = data.dates.map(d => {
      try {
        return new Date(d).toLocaleDateString('fa-IR', {
          month: 'short',
          day: 'numeric'
        });
      } catch {
        return d;
      }
    });
    
    const ctx = canvas.getContext('2d');
    chartInstance = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: persianDates,
        datasets: [{
          label: 'تعداد صفحات چاپ شده',
          data: data.totals,
          backgroundColor: 'rgba(0, 212, 255, 0.6)',
          borderColor: '#00d4ff',
          borderWidth: 2,
          borderRadius: 4,
          hoverBackgroundColor: 'rgba(0, 212, 255, 0.8)'
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            display: true,
            position: 'top',
            labels: {
              color: '#e4e8f0',
              font: {
                family: 'Noto Sans Arabic',
                size: 12
              }
            }
          },
          tooltip: {
            backgroundColor: 'rgba(20, 23, 32, 0.95)',
            titleColor: '#00d4ff',
            bodyColor: '#e4e8f0',
            borderColor: '#2a3248',
            borderWidth: 1,
            padding: 12,
            displayColors: false,
            callbacks: {
              label: function(context) {
                return `چاپ: ${context.parsed.y.toLocaleString('fa-IR')} صفحه`;
              }
            }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            grid: {
              color: 'rgba(42, 50, 72, 0.5)',
              drawBorder: false
            },
            ticks: {
              color: '#7b86a0',
              font: {
                family: 'JetBrains Mono',
                size: 10
              },
              callback: function(value) {
                return value.toLocaleString('fa-IR');
              }
            }
          },
          x: {
            grid: {
              display: false
            },
            ticks: {
              color: '#7b86a0',
              font: {
                family: 'Noto Sans Arabic',
                size: 10
              },
              maxRotation: 45,
              minRotation: 45
            }
          }
        },
        animation: {
          duration: 750,
          easing: 'easeInOutQuart'
        }
      }
    });
    
    toast(`نمودار ${data.dates.length} روز نمایش داده شد`, 's');
    
  } catch (e) {
    console.error('Chart error:', e);
    toast('خطا در بارگذاری نمودار: ' + e.message, 'e');
  }
}

async function loadPrinterDailyChart(ip) {
  if (!ip) {
    console.error('loadPrinterDailyChart called without ip');
    return;
  }

  let canvasId = `printer-daily-chart-${ip.replace(/\./g,'-')}`;
  let canvas = document.getElementById(canvasId);
  if (!canvas) {
    const panel = document.getElementById('panel-' + ip.replace(/\./g, '-'));
    if (!panel) {
      console.error('Printer detail panel not found for ip', ip);
      return;
    }
    const fallback = document.createElement('canvas');
    fallback.id = canvasId;
    fallback.className = 'printer-daily-chart-canvas';
    fallback.style.width = '100%';
    fallback.style.height = '300px';
    fallback.style.display = 'block';
    panel.appendChild(fallback);
    canvas = fallback;
  }

  if (!canvas || !canvas.parentElement) {
    console.error('Printer chart canvas missing or detached for ip', ip);
    return;
  }

  const container = canvas.parentElement;
  canvas.style.width = '100%';
  canvas.style.height = '300px';
  canvas.style.display = 'block';
  const oldMessage = container.querySelector('.printer-chart-empty');
  if (oldMessage) oldMessage.remove();

  const existing = printerChartInstances[ip];
  if (existing) {
    try {
      if (typeof existing.destroy === 'function') {
        existing.destroy();
      }
    } catch (e) {
      console.error('Printer chart destroy error:', e);
    }
    delete printerChartInstances[ip];
  }

  const url = `${API}/api/stats/daily?days=30&ip=${encodeURIComponent(ip)}`;
  console.debug('Loading printer daily chart from', url);

  try {
    const res = await fetch(url, {cache: 'no-store'});
    if (!res.ok) {
      const body = await res.text();
      console.error('Printer daily chart fetch error', res.status, body);
      throw new Error(`HTTP ${res.status}`);
    }

    const data = await res.json();
    console.debug('Printer daily chart response', data);

    if (!data || !Array.isArray(data.dates) || !Array.isArray(data.totals) || data.dates.length === 0 || data.totals.length === 0) {
      console.warn('Printer daily chart no data available for', ip, data);
      canvas.style.display = 'none';
      const message = document.createElement('div');
      message.className = 'printer-chart-empty';
      message.style.cssText = 'padding:18px 12px; color:var(--text3); font-size:13px; text-align:center; background:rgba(255,255,255,0.04); border:1px solid var(--border); border-radius:8px;';
      message.textContent = 'No data available';
      container.appendChild(message);
      return;
    }

    if (data.dates.length !== data.totals.length) {
      console.warn('Printer daily chart arrays length mismatch', {
        ip,
        dates: data.dates.length,
        totals: data.totals.length
      });
    }

    const persianDates = data.dates.map(d => {
      try {
        return new Date(d).toLocaleDateString('fa-IR', { month: 'short', day: 'numeric' });
      } catch {
        return d;
      }
    });

    const ctx = canvas.getContext('2d');
    if (!ctx) {
      console.error('Canvas context not available for ip', ip);
      return;
    }

    await new Promise(resolve => requestAnimationFrame(resolve));
    await new Promise(resolve => setTimeout(resolve, 20));
    canvas.style.display = 'block';
    canvas.style.width = '100%';
    canvas.style.height = '300px';
    canvas.style.backgroundColor = 'rgba(255,255,255,0.02)';
    canvas.style.border = '1px solid rgba(255,255,255,0.08)';
    canvas.style.borderRadius = '8px';
    canvas.style.boxSizing = 'border-box';
    canvas.width = canvas.clientWidth;
    canvas.height = canvas.clientHeight;
    console.debug('Creating Chart.js bar chart for ip', ip, 'canvas size', canvas.clientWidth, canvas.clientHeight, 'display', canvas.style.display);
    let chart;
    try {
      chart = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: persianDates,
          datasets: [{
            label: 'تعداد صفحات چاپ شده',
            data: data.totals,
            backgroundColor: 'rgba(0,212,255,0.6)',
            borderColor: '#00d4ff',
            borderWidth: 2,
            borderRadius: 6
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: 'rgba(20, 23, 32, 0.95)',
              titleColor: '#00d4ff',
              bodyColor: '#e4e8f0',
              borderColor: '#2a3248',
              borderWidth: 1,
              padding: 12,
              displayColors: false,
              callbacks: {
                label: function(context) {
                  return `چاپ: ${context.parsed.y.toLocaleString('fa-IR')} صفحه`;
                }
              }
            }
          },
          scales: {
            y: {
              beginAtZero: true,
              grid: {
                color: 'rgba(42, 50, 72, 0.45)',
                drawBorder: false
              },
              ticks: {
                color: '#7b86a0',
                font: { family: 'JetBrains Mono', size: 10 },
                callback: function(value) { return value.toLocaleString('fa-IR'); }
              }
            },
            x: {
              grid: { display: false },
              ticks: {
                color: '#7b86a0',
                font: { family: 'Noto Sans Arabic', size: 10 },
                maxRotation: 45,
                minRotation: 45
              }
            }
          },
          interaction: {
            intersect: false,
            mode: 'index'
          },
          animation: {
            duration: 750,
            easing: 'easeInOutQuart'
          }
        }
      });
      console.debug('Chart created for ip', ip, chart);
    } catch (chartErr) {
      console.error('Printer chart creation failed:', chartErr);
      if (container) {
        const oldMessage = container.querySelector('.printer-chart-empty');
        if (!oldMessage) {
          const message = document.createElement('div');
          message.className = 'printer-chart-empty';
          message.style.cssText = 'padding:18px 12px; color:var(--text3); font-size:13px; text-align:center; background:rgba(255,255,255,0.04); border:1px solid var(--border); border-radius:8px;';
          message.textContent = 'Chart render failed';
          container.appendChild(message);
        }
      }
      return;
    }

    chart.update();
    console.debug('Printer chart updated for ip', ip);
    requestAnimationFrame(() => {
      try {
        chart.update();
      } catch (err) {
        console.error('Printer chart second update failed:', err);
      }
    });
    printerChartInstances[ip] = chart;
  } catch (e) {
    console.error('Printer daily chart error:', e);
    if (container) {
      const oldMessage = container.querySelector('.printer-chart-empty');
      if (!oldMessage) {
        const message = document.createElement('div');
        message.className = 'printer-chart-empty';
        message.style.cssText = 'padding:18px 12px; color:var(--text3); font-size:13px; text-align:center; background:rgba(255,255,255,0.04); border:1px solid var(--border); border-radius:8px;';
        message.textContent = 'No data available';
        container.appendChild(message);
      }
      canvas.style.display = 'none';
    }
  }
}

// ══════════════════════════════════════════════════
// INIT
// ══════════════════════════════════════════════════
fetchData();
resetCountdown();
bindNicknameModalEvents();

setTimeout(() => {
  if (activeTab === 'overview') {
    loadDailyChart();
  }
}, 1000);