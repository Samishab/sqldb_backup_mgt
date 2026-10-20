const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const TYPES = { full: 'كاملة', diff: 'تفاضلية', log: 'سجل العمليات' };
const CONN = { sqlserver: 'SQL Server', sqlite: 'SQLite', mysql: 'MySQL / MariaDB', postgres: 'PostgreSQL' };
const DAYS = [['sun', 'الأحد'], ['mon', 'الإثنين'], ['tue', 'الثلاثاء'], ['wed', 'الأربعاء'], ['thu', 'الخميس'], ['fri', 'الجمعة'], ['sat', 'السبت']];
const NAV = [['dashboard', '📊', 'الرئيسية'], ['schedules', '⏰', 'الجدولة'], ['connections', '🔌', 'الاتصالات'], ['destinations', '☁️', 'الوجهات'],
['history', '📜', 'السجل'], ['restore', '♻️', 'الاسترجاع'], ['settings', '⚙️', 'الإعدادات'], ['audit', '🛡️', 'التدقيق']];
let timer = null, cache = {};

async function api(path, method = 'GET', body) {
  const r = await fetch('/api' + path, { method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
  if (r.status === 401 && !path.startsWith('/auth/')) { boot(); throw new Error('انتهت الجلسة'); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : r.statusText);
  return j;
}
function toast(m, err) { const t = $('#toast'); t.textContent = m; t.className = 'toast show' + (err ? ' err' : ''); clearTimeout(t._t); t._t = setTimeout(() => t.className = 'toast', 4000); }
const guard = fn => async (...a) => { try { return await fn(...a); } catch (e) { toast(e.message, true); } };

// ---------- formatters
function fmtSize(b) { b = +b || 0; const u = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0; while (b >= 1024 && i < 4) { b /= 1024; i++; } return b.toFixed(i > 1 ? 2 : 0) + ' ' + u[i]; }
function fmtDur(s) { s = +s || 0; if (s < 60) return s + ' ث'; if (s < 3600) return Math.floor(s / 60) + ' د ' + (s % 60) + ' ث'; return Math.floor(s / 3600) + ' س ' + Math.floor(s % 3600 / 60) + ' د'; }
function fmtDate(d) { if (!d) return '—'; const x = new Date(d); return x.toLocaleDateString('en-GB') + ' ' + x.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }); }
function ago(d) { if (!d) return 'لا يوجد'; const s = (Date.now() - new Date(d)) / 1000; if (s < 90) return 'الآن'; if (s < 3600) return `قبل ${Math.round(s / 60)} د`; if (s < 86400) return `قبل ${Math.round(s / 3600)} س`; return `قبل ${Math.round(s / 86400)} يوم`; }
const typeBadge = t => `<span class="badge b-${t === 'restore' ? 'restore' : t}">${TYPES[t] || (t === 'restore' ? 'استرجاع' : t)}</span>`;
const statusBadge = s => s === 'success' ? '<span class="badge b-ok">✔ ناجح</span>' : s === 'failed' ? '<span class="badge b-bad">✖ فشل</span>' : '<span class="badge b-run"><i class="run-dot"></i> قيد التنفيذ</span>';
function trigText(t) {
  const tm = t.time || '02:00';
  if (t.mode === 'interval') return `كل ${t.every} ${{ minutes: 'دقيقة', hours: 'ساعة', days: 'يوم' }[t.unit]}`;
  if (t.mode === 'daily') return `يوميًا ${tm}`;
  if (t.mode === 'weekly') return `أسبوعيًا (${(t.days || []).map(d => DAYS.find(x => x[0] === d)?.[1]).join('، ')}) ${tm}`;
  if (t.mode === 'monthly') return `شهريًا يوم ${t.day} ${tm}`;
  return `Cron: ${t.expr}`;
}

// ---------- modal
function openModal(title, html, buttons) {
  $('#mTitle').textContent = title; $('#mBody').innerHTML = html;
  const f = $('#mFoot'); f.innerHTML = '';
  buttons.forEach(([label, cls, fn]) => { const b = document.createElement('button'); b.className = 'btn ' + cls; b.textContent = label; b.onclick = guard(async () => { b.disabled = true; try { await fn(b); } finally { b.disabled = false; } }); f.appendChild(b); });
  $('#modal').classList.remove('hidden');
}
function closeModal() { $('#modal').classList.add('hidden'); }
const val = id => $('#' + id)?.value;
const chk = id => $('#' + id)?.checked;

// ---------- auth + router
async function boot() {
  const s = await fetch('/api/auth/status').then(r => r.json());
  if (s.authed) { $('#login').classList.add('hidden'); $('#app').classList.remove('hidden'); $('#nav').innerHTML = NAV.map(n => `<a data-v="${n[0]}" href="#${n[0]}"><i>${n[1]}</i>${n[2]}</a>`).join(''); route(); return; }
  $('#app').classList.add('hidden'); const l = $('#login'); l.classList.remove('hidden');
  l.innerHTML = `<div class="card"><div class="logo" style="margin:0 auto 12px">⛁</div><h2 style="margin:0 0 4px">BackupHub</h2>
  <p class="mut">${s.configured ? 'سجّل الدخول للمتابعة' : 'أول تشغيل: عيّن كلمة مرور للوحة'}</p>
  <label class="f"><input type="password" id="pw" placeholder="كلمة المرور" onkeydown="if(event.key==='Enter')doLogin(${s.configured})"></label>
  <button class="btn" style="width:100%" onclick="doLogin(${s.configured})">${s.configured ? 'دخول' : 'حفظ ودخول'}</button></div>`;
}
const doLogin = guard(async configured => { await api(configured ? '/auth/login' : '/auth/setup', 'POST', { password: val('pw') }); boot(); });
const logout = guard(async () => { await api('/auth/logout', 'POST'); boot(); });
window.addEventListener('hashchange', () => { if (!$('#app').classList.contains('hidden')) route(); });

const VIEWS = { dashboard: vDashboard, schedules: vSchedules, connections: vConnections, destinations: vDestinations, history: vHistory, restore: vRestore, settings: vSettings, audit: vAudit };
async function route() {
  clearInterval(timer);
  const v = (location.hash.slice(1) || 'dashboard'); const fn = VIEWS[v] || vDashboard;
  document.querySelectorAll('nav a').forEach(a => a.classList.toggle('on', a.dataset.v === v));
  $('#title').textContent = NAV.find(n => n[0] === v)?.[2] || ''; $('#topActions').innerHTML = '';
  try { await fn(); } catch (e) { toast(e.message, true); }
  if (['dashboard', 'history', 'restore'].includes(v)) timer = setInterval(() => fn().catch(() => { }), 5000);
}

// ---------- dashboard
async function vDashboard() {
  const d = await api('/dashboard'); const pill = $('#runningPill');
  pill.classList.toggle('hidden', !d.running.length); pill.innerHTML = `<i class="run-dot"></i> ${d.running.length} عملية قيد التنفيذ`;
  $('#topActions').innerHTML = `<button class="btn ok" onclick="backupNow()">⚡ انسخ الآن</button>`;
  const l = d.last_ok, du = d.disk, used = du.total - du.free, pct = Math.round(used / du.total * 100);
  const mx = Math.max(1, ...d.days.map(x => x.ok + x.failed));
  $('#view').innerHTML = `
  ${d.stale.length ? `<div class="alert bad">⚠️ لا توجد نسخة ناجحة حديثة لـ: <b>${d.stale.map(s => esc(s.db)).join('، ')}</b> (تجاوزت الحد المسموح)</div>` : ''}
  ${d.last && d.last.status === 'failed' ? `<div class="alert bad">❌ آخر عملية فشلت: ${esc(d.last.db)} - ${esc(d.last.error)}</div>` : ''}
  <div class="grid g4">
    <div class="card stat ${l ? 'ok' : 'warn'}"><div class="lbl">آخر نسخة ناجحة</div><div class="val">${l ? ago(l.started) : '—'}</div><div class="sub">${l ? `${esc(l.db)} · ${fmtSize(l.size)} · ${fmtDur(l.duration)}` : 'لم تتم أي نسخة بعد'}</div></div>
    <div class="card stat blue"><div class="lbl">حجم النسخ المحفوظة</div><div class="val">${fmtSize(d.stored.size)}</div><div class="sub">${d.stored.count} ملف نسخة</div></div>
    <div class="card stat ${d.success_rate >= 95 ? 'ok' : 'warn'}"><div class="lbl">نسبة النجاح (آخر 100)</div><div class="val">${d.success_rate}%</div><div class="sub">${d.counts.schedules} جدول · ${d.counts.connections} اتصال</div></div>
    <div class="card stat ${pct > 85 ? 'bad' : ''}"><div class="lbl">المساحة المتبقية محليًا</div><div class="val">${fmtSize(du.free)}</div><div class="meter"><i style="width:${pct}%"></i></div><div class="sub" style="direction:ltr;text-align:right">${esc(du.dir)}</div></div>
  </div>
  <div class="grid g2" style="margin-top:16px">
    <div class="card"><h3>نشاط آخر 14 يوم</h3><div class="chart">${d.days.map(x => { const t = x.ok + x.failed; return `<div class="col" title="${x.day}: ${x.ok} ناجح / ${x.failed} فاشل · ${fmtSize(x.size)}"><div class="bar ${t ? '' : 'empty'}${x.failed ? ' f' : ''}" style="height:${t ? Math.max(8, t / mx * 100) : 3}%"></div><small>${x.day.slice(8)}</small></div>`; }).join('')}</div></div>
    <div class="card"><h3>العمليات القادمة</h3>${d.next.length ? `<table>${d.next.map(n => `<tr><td>${esc(n.name)}</td><td class="mut">${fmtDate(n.next)}</td></tr>`).join('')}</table>` : '<div class="empty-state">لا توجد جداول فعّالة. <a href="#schedules" style="color:var(--pri2)">أنشئ جدولًا</a></div>'}</div>
  </div>
  <div class="card" style="margin-top:16px"><h3>حالة القواعد</h3>${d.databases.length ? `<div class="tw"><table><tr><th>القاعدة</th><th>الاتصال</th><th>آخر نسخة ناجحة</th><th>الحالة الأخيرة</th><th>النسخ المحفوظة</th><th>الحجم</th></tr>${d.databases.map(x => `<tr><td><b>${esc(x.db)}</b></td><td class="mut">${esc(x.connection)}</td><td>${ago(x.last_ok)}</td><td>${statusBadge(x.last_status)}</td><td>${x.count}</td><td>${fmtSize(x.total_size)}</td></tr>`).join('')}</table></div>` : '<div class="empty-state">لا توجد نسخ بعد - ابدأ بإضافة اتصال ثم اضغط «انسخ الآن»</div>'}</div>`;
}

const backupNow = guard(async () => {
  const conns = await api('/connections'), dests = await api('/destinations');
  if (!conns.length) { toast('أضف اتصالًا أولًا', true); location.hash = 'connections'; return; }
  openModal('نسخ احتياطي فوري', `<label class="f"><span>الاتصال</span><select id="bnConn" onchange="loadDbChips('bn')">${conns.map(c => `<option value="${c.id}">${esc(c.name)} (${CONN[c.type]})</option>`).join('')}</select></label>
  ${dbPicker('bn')}
  <div class="seg">${Object.entries(TYPES).map(([k, v], i) => `<label><input type="radio" name="bnType" value="${k}" ${i ? '' : 'checked'}><span>${v}</span></label>`).join('')}</div>
  <div class="f"><span class="mut sm">الوجهات الإضافية (بالإضافة للمجلد المحلي)</span><br>${dests.map(x => `<label class="chk"><input type="checkbox" class="bnDest" value="${x.id}" checked>${esc(x.name)}</label>`).join('') || '<span class="mut">لا توجد وجهات</span>'}</div>
  <label class="chk"><input type="checkbox" id="bnVerify" checked> التحقق من النسخة بعد الإنشاء</label>`,
    [['ابدأ النسخ', 'ok', async () => {
      const dbs = getDbs('bn'); if (!dbs.length) throw new Error('اختر قاعدة واحدة على الأقل');
      await api('/backup', 'POST', { connection_id: +val('bnConn'), databases: dbs, type: document.querySelector('input[name=bnType]:checked').value, destinations: [...document.querySelectorAll('.bnDest:checked')].map(x => +x.value), verify: chk('bnVerify') });
      closeModal(); toast('بدأت العملية'); route();
    }], ['إلغاء', 'ghost', closeModal]]);
  loadDbChips('bn');
});

// database picker (chips + free text)
const dbPicker = p => `<div class="f"><span class="mut sm">القواعد</span><div class="chips" id="${p}Chips"><span class="mut sm">جارٍ التحميل...</span></div><input type="text" id="${p}Dbs" placeholder="أو اكتب الأسماء مفصولة بفاصلة"></div>`;
const getDbs = p => val(p + 'Dbs').split(',').map(s => s.trim()).filter(Boolean);
async function loadDbChips(p, selected) {
  const box = $('#' + p + 'Chips'); if (selected) $('#' + p + 'Dbs').value = selected.join(', ');
  try {
    const list = await api(`/connections/${val(p + 'Conn')}/databases`);
    box.innerHTML = list.length ? list.map(x => `<span class="chip" data-n="${esc(x.name)}" onclick="toggleChip('${p}',this)" title="${x.recovery || ''} ${x.size_mb}MB">${esc(x.name)}${x.recovery ? ` <small class="mut">${x.recovery[0]}</small>` : ''}</span>`).join('') : '<span class="mut sm">اكتب اسم القاعدة يدويًا</span>';
    syncChips(p);
  } catch (e) { box.innerHTML = `<span class="mut sm">تعذر جلب القواعد: ${esc(e.message)}</span>`; }
  $('#' + p + 'Dbs').oninput = () => syncChips(p);
}
function toggleChip(p, el) { const s = new Set(getDbs(p)); s.has(el.dataset.n) ? s.delete(el.dataset.n) : s.add(el.dataset.n); $('#' + p + 'Dbs').value = [...s].join(', '); syncChips(p); }
function syncChips(p) { const s = new Set(getDbs(p)); document.querySelectorAll(`#${p}Chips .chip`).forEach(c => c.classList.toggle('on', s.has(c.dataset.n))); }

// ---------- generic list helpers
const crud = (kind, id) => guard(async () => { if (!confirm('تأكيد الحذف؟')) return; await api(`/${kind}/${id}`, 'DELETE'); route(); });

// ---------- connections
async function vConnections() {
  const list = await api('/connections'); cache.conns = list;
  $('#topActions').innerHTML = `<button class="btn" onclick="editConn()">＋ اتصال جديد</button>`;
  $('#view').innerHTML = `<div class="card tw">${list.length ? `<table><tr><th>الاسم</th><th>النوع</th><th>العنوان</th><th></th></tr>${list.map(c => `<tr><td><b>${esc(c.name)}</b></td><td><span class="badge b-diff">${CONN[c.type]}</span></td><td class="mut" style="direction:ltr;text-align:right">${esc(c.server || c.path || c.host)}</td><td style="text-align:left"><button class="btn ghost sm" onclick="editConn(${c.id})">تعديل</button> <button class="btn bad sm" onclick="crud('connections',${c.id})()">حذف</button></td></tr>`).join('')}</table>` : '<div class="empty-state">لا توجد اتصالات. أضف اتصالًا بقاعدة بياناتك (SQL Server / SQLite / MySQL / PostgreSQL).</div>'}</div>`;
}
window.crud = crud;
function connFields(t, c = {}) {
  if (t === 'sqlserver') return `<div class="two"><label class="f"><span>السيرفر / الـ Instance</span><input type="text" id="cServer" value="${esc(c.server || 'localhost')}" placeholder="localhost\\SQLEXPRESS"></label>
    <label class="f"><span>طريقة الدخول</span><select id="cAuth"><option value="windows" ${c.auth !== 'sql' ? 'selected' : ''}>Windows Authentication</option><option value="sql" ${c.auth === 'sql' ? 'selected' : ''}>SQL Login</option></select></label></div>
    <div class="two"><label class="f"><span>المستخدم</span><input type="text" id="cUser" value="${esc(c.user)}"></label><label class="f"><span>كلمة المرور</span><input type="password" id="cPass" value="${esc(c.password)}"></label></div>`;
  if (t === 'sqlite') return `<label class="f"><span>مسار ملف القاعدة</span><input type="text" id="cPath" value="${esc(c.path)}" style="direction:ltr" placeholder="D:\\data\\app.db"></label>`;
  return `<div class="two"><label class="f"><span>Host</span><input type="text" id="cHost" value="${esc(c.host || 'localhost')}"></label><label class="f"><span>Port</span><input type="text" id="cPort" value="${esc(c.port || (t === 'mysql' ? 3306 : 5432))}"></label></div>
    <div class="two"><label class="f"><span>المستخدم</span><input type="text" id="cUser" value="${esc(c.user)}"></label><label class="f"><span>كلمة المرور</span><input type="password" id="cPass" value="${esc(c.password)}"></label></div>
    <label class="f"><span>مجلد أدوات ${t === 'mysql' ? 'mysqldump' : 'pg_dump'} (اتركه فارغًا إذا كانت في PATH)</span><input type="text" id="cBin" value="${esc(c.bin_dir)}" style="direction:ltr"></label>`;
}
function readConn(t) {
  const o = { name: val('cName'), type: t };
  if (t === 'sqlserver') Object.assign(o, { server: val('cServer'), auth: val('cAuth'), user: val('cUser'), password: val('cPass') });
  else if (t === 'sqlite') o.path = val('cPath');
  else Object.assign(o, { host: val('cHost'), port: val('cPort'), user: val('cUser'), password: val('cPass'), bin_dir: val('cBin') });
  return o;
}
function editConn(id) {
  const c = id ? cache.conns.find(x => x.id === id) : { type: 'sqlserver' };
  const draw = t => { $('#cFields').innerHTML = connFields(t, t === c.type ? c : {}); };
  openModal(id ? 'تعديل اتصال' : 'اتصال جديد', `<label class="f"><span>اسم الاتصال</span><input type="text" id="cName" value="${esc(c.name)}" placeholder="مثال: سيرفر الشركة"></label>
  <label class="f"><span>نوع القاعدة</span><select id="cType">${Object.entries(CONN).map(([k, v]) => `<option value="${k}" ${k === c.type ? 'selected' : ''}>${v}</option>`).join('')}</select></label><div id="cFields"></div><div id="cResult"></div>`,
    [['حفظ', 'ok', async () => { const o = readConn(val('cType')); if (!o.name) throw new Error('الاسم مطلوب'); await api(id ? `/connections/${id}` : '/connections', id ? 'PUT' : 'POST', o); closeModal(); route(); }],
    ['اختبار الاتصال', '', async () => { const r = await api('/probe/connection', 'POST', readConn(val('cType'))); $('#cResult').innerHTML = r.ok ? `<div class="alert" style="color:var(--ok);border-color:#2fd59a55;background:#2fd59a1a">✔ ${esc(r.info)}${r.databases.length ? ` — ${r.databases.length} قاعدة` : ''}</div>` : `<div class="alert bad">${esc(r.error)}</div>`; }],
    ['إلغاء', 'ghost', closeModal]]);
  draw(c.type); $('#cType').onchange = e => draw(e.target.value);
}
window.editConn = editConn;

// ---------- destinations
async function vDestinations() {
  const list = await api('/destinations'); cache.dests = list;
  $('#topActions').innerHTML = `<button class="btn" onclick="editDest()">＋ وجهة جديدة</button>`;
  $('#view').innerHTML = `<div class="alert" style="background:#7c5cff14;border-color:#7c5cff44;color:#c9bdff">💡 المجلد المحلي الأساسي: <b style="direction:ltr;unicode-bidi:embed">${esc((await api('/settings')).backup_dir)}</b> (يتغير من الإعدادات). الوجهات هنا هي نسخ إضافية: مجلد شبكة، قرص خارجي، أو Google Drive عبر rclone.</div>
  <div class="card tw">${list.length ? `<table><tr><th>الاسم</th><th>النوع</th><th>المسار</th><th>الحالة</th><th></th></tr>${list.map(d => `<tr><td><b>${esc(d.name)}</b></td><td><span class="badge b-diff">${d.type === 'local' ? 'مجلد / شبكة' : 'rclone (سحابة)'}</span></td><td class="mut" style="direction:ltr;text-align:right">${esc(d.path || d.remote)}</td><td>${d.enabled === false ? '<span class="badge b-warn">متوقف</span>' : '<span class="badge b-ok">فعّال</span>'}</td><td style="text-align:left"><button class="btn ghost sm" onclick="checkDest(${d.id})">فحص</button> <button class="btn ghost sm" onclick="editDest(${d.id})">تعديل</button> <button class="btn bad sm" onclick="crud('destinations',${d.id})()">حذف</button></td></tr>`).join('')}</table>` : '<div class="empty-state">لا توجد وجهات إضافية.</div>'}</div>`;
}
const checkDest = guard(async id => { const d = cache.dests.find(x => x.id === id); toast('جارٍ الفحص...'); const r = await api('/probe/destination', 'POST', d); toast(r.ok ? '✔ ' + r.info : r.error, !r.ok); });
window.checkDest = checkDest;
function editDest(id) {
  const d = id ? cache.dests.find(x => x.id === id) : { type: 'local', enabled: true };
  const draw = t => { $('#dFields').innerHTML = t === 'local' ? `<label class="f"><span>المسار (محلي أو UNC)</span><input type="text" id="dPath" style="direction:ltr" value="${esc(d.path)}" placeholder="\\\\NAS\\backups  أو  E:\\Backups"></label>`
    : `<label class="f"><span>Remote (من إعداد rclone)</span><input type="text" id="dRemote" style="direction:ltr" value="${esc(d.remote)}" placeholder="gdrive:SQLBackups"></label><label class="f"><span>خيارات rclone إضافية (اختياري)</span><input type="text" id="dFlags" style="direction:ltr" value="${esc(d.flags)}" placeholder="--drive-chunk-size 128M"></label>
    <div class="mut sm">أنشئ الـ remote مرة واحدة بالأمر <code>rclone config</code> (اختر Google Drive). للتشفير أنشئ remote من نوع crypt فوقه واستخدمه هنا.</div>`; };
  openModal(id ? 'تعديل وجهة' : 'وجهة جديدة', `<label class="f"><span>الاسم</span><input type="text" id="dName" value="${esc(d.name)}"></label><label class="f"><span>النوع</span><select id="dType"><option value="local" ${d.type === 'local' ? 'selected' : ''}>مجلد محلي / شبكة</option><option value="rclone" ${d.type === 'rclone' ? 'selected' : ''}>rclone (Google Drive وغيره)</option></select></label><div id="dFields"></div><label class="chk"><input type="checkbox" id="dEn" ${d.enabled === false ? '' : 'checked'}> فعّالة</label>`,
    [['حفظ', 'ok', async () => { const t = val('dType'); const o = { name: val('dName'), type: t, enabled: chk('dEn') }; if (t === 'local') o.path = val('dPath'); else { o.remote = val('dRemote'); o.flags = val('dFlags'); } if (!o.name || !(o.path || o.remote)) throw new Error('أكمل الحقول'); await api(id ? `/destinations/${id}` : '/destinations', id ? 'PUT' : 'POST', o); closeModal(); route(); }], ['إلغاء', 'ghost', closeModal]]);
  draw(d.type); $('#dType').onchange = e => draw(e.target.value);
}
window.editDest = editDest;

// ---------- schedules
async function vSchedules() {
  const [list, conns, dests] = await Promise.all([api('/schedules'), api('/connections'), api('/destinations')]); cache.scheds = list; cache.conns = conns; cache.dests = dests;
  $('#topActions').innerHTML = `<button class="btn" onclick="editSched()">＋ جدول جديد</button>`;
  $('#view').innerHTML = `<div class="grid">${list.map(s => { const c = conns.find(x => x.id === s.connection_id); const r = s.retention || {}; return `<div class="card"><div class="row"><div><b style="font-size:16px">${esc(s.name)}</b> ${typeBadge(s.type)} ${s.enabled === false ? '<span class="badge b-warn">متوقف</span>' : ''}</div><div class="sp"></div>
    <button class="btn ok sm" onclick="runSched(${s.id})">▶ تشغيل الآن</button><button class="btn ghost sm" onclick="editSched(${s.id})">تعديل</button><button class="btn bad sm" onclick="crud('schedules',${s.id})()">حذف</button></div>
    <div class="row mut" style="margin-top:10px;gap:22px"><span>🔌 ${esc(c?.name || '؟')}</span><span>🗄 ${(s.databases || []).map(esc).join('، ')}</span><span>⏰ ${trigText(s.trigger)}</span><span>☁️ ${(s.destinations || []).map(i => esc(dests.find(d => d.id === i)?.name || '؟')).join('، ') || 'محلي فقط'}</span></div>
    <div class="row mut sm" style="margin-top:6px;gap:22px"><span>التشغيل القادم: <b style="color:var(--tx)">${s.next ? fmtDate(s.next) : '—'}</b></span><span>الاحتفاظ: ${r.daily || 0} يومي / ${r.weekly || 0} أسبوعي / ${r.monthly || 0} شهري</span><span>${s.verify !== false ? '✔ تحقق تلقائي' : 'بدون تحقق'}</span></div></div>`; }).join('') || '<div class="card empty-state">لا توجد جداول. أنشئ جدولًا لتشغيل النسخ تلقائيًا (مثال: Full أسبوعيًا + Differential يوميًا + Log كل ساعة).</div>'}</div>`;
}
const runSched = guard(async id => { await api(`/schedules/${id}/run`, 'POST'); toast('بدأ التشغيل - تابع السجل'); });
window.runSched = runSched;
function trigFields(t) {
  const time = `<label class="f"><span>الوقت</span><input type="time" id="tTime" value="${t.time || '02:00'}"></label>`;
  const m = t.mode;
  $('#tFields').innerHTML = m === 'interval' ? `<div class="two"><label class="f"><span>كل</span><input type="number" id="tEvery" min="1" value="${t.every || 1}"></label><label class="f"><span>الوحدة</span><select id="tUnit">${[['minutes', 'دقيقة'], ['hours', 'ساعة'], ['days', 'يوم']].map(([k, v]) => `<option value="${k}" ${t.unit === k ? 'selected' : ''}>${v}</option>`).join('')}</select></label></div>`
    : m === 'daily' ? time : m === 'weekly' ? `<div class="f"><span class="mut sm">الأيام</span><div class="chips">${DAYS.map(([k, v]) => `<span class="chip ${(t.days || ['sun']).includes(k) ? 'on' : ''}" data-d="${k}" onclick="this.classList.toggle('on')">${v}</span>`).join('')}</div></div>${time}`
      : m === 'monthly' ? `<div class="two"><label class="f"><span>يوم الشهر</span><input type="number" id="tDay" min="1" max="28" value="${t.day || 1}"></label>${time}</div>`
        : `<label class="f"><span>تعبير Cron (دقيقة ساعة يوم شهر يوم-أسبوع)</span><input type="text" id="tExpr" style="direction:ltr" value="${esc(t.expr || '0 2 * * *')}"></label>`;
}
function readTrig() {
  const mode = document.querySelector('input[name=tMode]:checked').value, t = { mode };
  if (mode === 'interval') Object.assign(t, { every: +val('tEvery'), unit: val('tUnit') });
  if (mode === 'daily' || mode === 'weekly' || mode === 'monthly') t.time = val('tTime');
  if (mode === 'weekly') { t.days = [...document.querySelectorAll('#tFields .chip.on')].map(c => c.dataset.d); if (!t.days.length) throw new Error('اختر يومًا واحدًا على الأقل'); }
  if (mode === 'monthly') t.day = +val('tDay');
  if (mode === 'cron') t.expr = val('tExpr');
  return t;
}
function editSched(id) {
  const s = id ? cache.scheds.find(x => x.id === id) : { type: 'full', trigger: { mode: 'daily', time: '02:00' }, destinations: cache.dests.map(d => d.id), verify: true, enabled: true, retention: { daily: 7, weekly: 4, monthly: 6 }, databases: [] };
  if (!cache.conns.length) { toast('أضف اتصالًا أولًا', true); return; }
  const r = s.retention || {};
  openModal(id ? 'تعديل جدول' : 'جدول جديد', `<label class="f"><span>اسم الجدول</span><input type="text" id="sName" value="${esc(s.name)}" placeholder="مثال: Full أسبوعي"></label>
  <label class="f"><span>الاتصال</span><select id="sConn" onchange="loadDbChips('s')">${cache.conns.map(c => `<option value="${c.id}" ${c.id === s.connection_id ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}</select></label>${dbPicker('s')}
  <div class="f"><span class="mut sm">نوع النسخة</span><div class="seg" style="margin:4px 0 0">${Object.entries(TYPES).map(([k, v]) => `<label><input type="radio" name="sType" value="${k}" ${s.type === k ? 'checked' : ''}><span>${v}</span></label>`).join('')}</div><div class="mut sm">التفاضلية والسجل تحتاج نسخة كاملة سابقة، والسجل يتطلب Recovery Model = Full</div></div>
  <div class="f"><span class="mut sm">متى؟</span><div class="seg" style="margin:4px 0 0">${[['interval', 'كل فترة'], ['daily', 'يوميًا'], ['weekly', 'أسبوعيًا'], ['monthly', 'شهريًا'], ['cron', 'Cron']].map(([k, v]) => `<label><input type="radio" name="tMode" value="${k}" ${s.trigger.mode === k ? 'checked' : ''}><span>${v}</span></label>`).join('')}</div><div id="tFields"></div></div>
  <div class="f"><span class="mut sm">الوجهات الإضافية</span><br>${cache.dests.map(d => `<label class="chk"><input type="checkbox" class="sDest" value="${d.id}" ${(s.destinations || []).includes(d.id) ? 'checked' : ''}>${esc(d.name)}</label>`).join('') || '<span class="mut sm">لا توجد (النسخ تُحفظ محليًا فقط)</span>'}</div>
  <div class="f"><span class="mut sm">سياسة الاحتفاظ (0 = بدون) — للسجل: عدد الأيام فقط</span><div class="two" style="grid-template-columns:repeat(3,1fr)"><label class="f"><span>يومي</span><input type="number" min="0" id="rD" value="${r.daily ?? 7}"></label><label class="f"><span>أسبوعي</span><input type="number" min="0" id="rW" value="${r.weekly ?? 4}"></label><label class="f"><span>شهري</span><input type="number" min="0" id="rM" value="${r.monthly ?? 6}"></label></div></div>
  <label class="chk"><input type="checkbox" id="sVerify" ${s.verify !== false ? 'checked' : ''}> تحقق من النسخة بعد الإنشاء</label><label class="chk"><input type="checkbox" id="sEn" ${s.enabled !== false ? 'checked' : ''}> الجدول فعّال</label>`,
    [['حفظ', 'ok', async () => {
      const dbs = getDbs('s'); if (!val('sName') || !dbs.length) throw new Error('الاسم والقواعد مطلوبة');
      await api(id ? `/schedules/${id}` : '/schedules', id ? 'PUT' : 'POST', { name: val('sName'), connection_id: +val('sConn'), databases: dbs, type: document.querySelector('input[name=sType]:checked').value, trigger: readTrig(), destinations: [...document.querySelectorAll('.sDest:checked')].map(x => +x.value), retention: { daily: +val('rD'), weekly: +val('rW'), monthly: +val('rM') }, verify: chk('sVerify'), enabled: chk('sEn') });
      closeModal(); route();
    }], ['إلغاء', 'ghost', closeModal]]);
  trigFields(s.trigger); document.querySelectorAll('input[name=tMode]').forEach(r => r.onchange = () => trigFields({ mode: r.value }));
  loadDbChips('s', s.databases);
}
window.editSched = editSched;

// ---------- history
let hf = { status: '', rtype: '' };
async function vHistory() {
  const q = new URLSearchParams({ limit: 200, ...hf }); const rows = await api('/runs?' + q);
  $('#topActions').innerHTML = `<select onchange="hf.status=this.value;route()"><option value="">كل الحالات</option>${[['success', 'ناجح'], ['failed', 'فاشل'], ['running', 'قيد التنفيذ']].map(([k, v]) => `<option value="${k}" ${hf.status === k ? 'selected' : ''}>${v}</option>`).join('')}</select>
  <select onchange="hf.rtype=this.value;route()"><option value="">كل الأنواع</option>${[['full', 'كاملة'], ['diff', 'تفاضلية'], ['log', 'سجل'], ['restore', 'استرجاع']].map(([k, v]) => `<option value="${k}" ${hf.rtype === k ? 'selected' : ''}>${v}</option>`).join('')}</select>`;
  $('#topActions').querySelectorAll('select').forEach(s => s.style.width = 'auto');
  $('#view').innerHTML = `<div class="card tw">${rows.length ? `<table><tr><th>#</th><th>التاريخ</th><th>القاعدة</th><th>النوع</th><th>الجدول</th><th>الحالة</th><th>الحجم</th><th>المدة</th><th>تحقق</th><th>الرفع</th><th></th></tr>${rows.map(r => `<tr style="${r.deleted ? 'opacity:.45' : ''}"><td class="mut">${r.id}</td><td>${fmtDate(r.started)}</td><td><b>${esc(r.db)}</b></td><td>${typeBadge(r.type)}</td><td class="mut">${esc(r.schedule_name)}</td><td>${statusBadge(r.status)}</td><td>${r.size ? fmtSize(r.size) : '—'}</td><td>${fmtDur(r.duration)}</td><td>${r.verified ? '✔' : '—'}</td><td>${r.uploads.map(u => `<span class="badge ${u.status === 'ok' ? 'b-ok' : 'b-bad'}" title="${esc(u.error || u.path)}">${esc(u.name)}</span>`).join(' ') || '—'}</td><td style="text-align:left"><button class="btn ghost sm" onclick="showLog(${r.id})">السجل</button>${r.type !== 'restore' && !r.deleted && r.file_exists ? ` <button class="btn bad sm" onclick="delRun(${r.id})">حذف</button>` : ''}</td></tr>`).join('')}</table>` : '<div class="empty-state">لا توجد عمليات</div>'}</div>`;
}
const showLog = guard(async id => { const r = await api('/runs/' + id); openModal(`عملية #${id} - ${r.db}`, `${r.error ? `<div class="alert bad">${esc(r.error)}</div>` : ''}<div class="mut sm" style="direction:ltr;text-align:left;margin-bottom:8px">${esc(r.file || '')}</div><pre class="log">${esc(r.log || 'لا يوجد سجل')}</pre>`, [['إغلاق', 'ghost', closeModal]]); });
const delRun = guard(async id => { if (!confirm('حذف ملف هذه النسخة من القرص والوجهات؟')) return; await api('/runs/' + id, 'DELETE'); route(); });
Object.assign(window, { showLog, delRun, hf });

// ---------- restore
async function vRestore() {
  const rows = (await api('/runs?limit=300&status=success')).filter(r => r.type !== 'restore' && !r.deleted && r.file_exists);
  $('#view').innerHTML = `<div class="alert" style="background:#4cc9f014;border-color:#4cc9f044;color:#a5e8fa">♻️ الاسترجاع يتم دائمًا كقاعدة <b>جديدة</b> ولا يكتب فوق الأصلية. لنسخ السجل/التفاضلية يُبنى المسار تلقائيًا (كاملة ← تفاضلية ← سجلات). مدعوم حاليًا لـ SQL Server. «اختبار» يسترجع، يفحص CHECKDB، ثم يحذف القاعدة التجريبية.</div>
  <div class="card tw">${rows.length ? `<table><tr><th>التاريخ</th><th>القاعدة</th><th>النوع</th><th>الحجم</th><th></th></tr>${rows.map(r => `<tr><td>${fmtDate(r.started)}</td><td><b>${esc(r.db)}</b></td><td>${typeBadge(r.type)}</td><td>${fmtSize(r.size)}</td><td style="text-align:left"><button class="btn sm" onclick="askRestore(${r.id},'${esc(r.db)}',false)">استرجاع</button> <button class="btn ghost sm" onclick="askRestore(${r.id},'${esc(r.db)}',true)">اختبار</button></td></tr>`).join('')}</table>` : '<div class="empty-state">لا توجد نسخ متاحة للاسترجاع</div>'}</div>`;
}
function askRestore(id, name, test) {
  const def = test ? `zz_test_${name}` : `${name}_restored_${new Date().toISOString().slice(0, 10).replace(/-/g, '')}`;
  openModal(test ? 'اختبار استرجاع' : 'استرجاع نسخة', `<label class="f"><span>اسم القاعدة الجديدة</span><input type="text" id="rName" value="${esc(def)}" style="direction:ltr"></label><div class="mut sm">يجب أن يكون الاسم غير موجود على السيرفر.</div>`,
    [[test ? 'ابدأ الاختبار' : 'ابدأ الاسترجاع', 'ok', async () => { await api(`/runs/${id}/restore`, 'POST', { new_name: val('rName'), test }); closeModal(); toast('بدأت العملية - تابعها من السجل'); location.hash = 'history'; }], ['إلغاء', 'ghost', closeModal]]);
}
window.askRestore = askRestore;

// ---------- settings
async function vSettings() {
  const s = await api('/settings'); const f = (k, label, type = 'text', ph = '') => `<label class="f"><span>${label}</span><input type="${type}" id="st_${k}" value="${esc(s[k])}" placeholder="${ph}" style="direction:ltr"></label>`;
  $('#topActions').innerHTML = `<button class="btn ok" onclick="saveSettings()">💾 حفظ الإعدادات</button>`;
  $('#view').innerHTML = `<div class="grid g2">
  <div class="card"><h3>التخزين والمراقبة</h3>${f('backup_dir', 'المجلد المحلي الأساسي للنسخ (يجب أن يملك حساب خدمة SQL Server صلاحية الكتابة عليه)')}${f('rclone_path', 'مسار rclone', 'text', 'rclone')}${f('stale_hours', 'تنبيه إذا مرّ هذا العدد من الساعات بدون نسخة ناجحة', 'number')}</div>
  <div class="card"><h3>التنبيهات</h3><label class="f"><span>متى أُرسل؟</span><select id="st_notify_on">${[['failure', 'عند الفشل فقط'], ['all', 'عند كل عملية'], ['none', 'إيقاف']].map(([k, v]) => `<option value="${k}" ${s.notify_on === k ? 'selected' : ''}>${v}</option>`).join('')}</select></label>
  ${f('telegram_token', 'Telegram Bot Token')}${f('telegram_chat', 'Telegram Chat ID')}${f('webhook_url', 'Webhook URL (Slack / Teams / n8n ...)')}</div>
  <div class="card"><h3>البريد (SMTP)</h3><div class="two">${f('smtp_host', 'الخادم')}${f('smtp_port', 'المنفذ')}</div><div class="two">${f('smtp_user', 'المستخدم')}${f('smtp_pass', 'كلمة المرور', 'password')}</div>${f('smtp_from', 'من')}${f('smtp_to', 'إلى (افصل بفاصلة)')}<label class="chk"><input type="checkbox" id="st_smtp_tls" ${s.smtp_tls === '1' ? 'checked' : ''}> STARTTLS</label><br><br><button class="btn ghost" onclick="testAlerts()">إرسال تنبيه تجريبي</button></div>
  <div class="card"><h3>الأمان</h3><label class="f"><span>كلمة المرور الحالية</span><input type="password" id="pwOld"></label><label class="f"><span>كلمة المرور الجديدة</span><input type="password" id="pwNew"></label><button class="btn ghost" onclick="chPw()">تغيير كلمة المرور</button></div></div>`;
}
const KEYS = ['backup_dir', 'rclone_path', 'stale_hours', 'notify_on', 'telegram_token', 'telegram_chat', 'webhook_url', 'smtp_host', 'smtp_port', 'smtp_user', 'smtp_pass', 'smtp_from', 'smtp_to'];
const saveSettings = guard(async () => { const o = {}; KEYS.forEach(k => o[k] = val('st_' + k)); o.smtp_tls = chk('st_smtp_tls') ? '1' : '0'; await api('/settings', 'PUT', o); toast('تم الحفظ'); });
const testAlerts = guard(async () => { await saveSettings(); const r = await api('/alerts/test', 'POST'); toast(r.sent.length ? 'أُرسل عبر: ' + r.sent.join('، ') : (r.errors.join(' | ') || 'لا توجد قنوات مفعّلة'), !r.sent.length); });
const chPw = guard(async () => { await api('/auth/password', 'POST', { old: val('pwOld'), new: val('pwNew') }); toast('تم تغيير كلمة المرور'); });
Object.assign(window, { saveSettings, testAlerts, chPw });

// ---------- audit
async function vAudit() {
  const rows = await api('/audit/log');
  $('#view').innerHTML = `<div class="card tw"><table><tr><th>الوقت</th><th>الإجراء</th><th>التفاصيل</th></tr>${rows.map(r => `<tr><td class="mut">${fmtDate(r.ts)}</td><td><span class="badge b-restore">${esc(r.action)}</span></td><td>${esc(r.detail)}</td></tr>`).join('')}</table></div>`;
}

Object.assign(window, { doLogin, logout, closeModal, backupNow, loadDbChips, toggleChip });
boot();
