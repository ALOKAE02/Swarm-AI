// SwarmQA web app: landing (/) and the app (/swarm). One tab, no build step.

const COLORS = ['#d9363e', '#2563eb', '#0f7f58', '#b45309', '#7c3aed', '#0e7490', '#be185d', '#4d7c0f'];
const TITLES = {
  console_error: 'Crash', unhandled_promise: 'Unhandled promise', layout_overflow: 'Layout overflow',
  network_error: 'Server error', broken_resource: 'Broken file', blank_screen: 'Blank screen',
  unresponsive: 'Page froze', xss: 'Script injection', broken_link: 'Broken link',
};
const SEV = { high: 'High', medium: 'Medium', low: 'Low' };
const PAYLOAD = {
  $XSS: 'a script-injection probe', $XSS2: 'a script-injection probe', $SQL: 'an SQL fragment',
  $LONG: '5,000 characters', $EMOJI: 'a wall of emoji', $EMPTY: 'nothing', $SPACES: 'only spaces',
  $NUM: 'a huge negative number', $ZERO: '0', $NULL: '"null"', $UNDEF: '"undefined"',
  $UNICODE: 'mixed-script text', $PATH: 'a file path', $TEMPLATE: 'template code', $DATE: 'an impossible date',
  $JSON: 'a __proto__ payload', $EMAIL: 'an email address',
};
const KEYS = { Escape: 'Esc', ' ': 'Space', ArrowDown: 'Down arrow', ArrowUp: 'Up arrow' };

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
};
const mmss = (s) => { s = Math.max(0, Math.round(s || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
const route = (u) => { try { const x = new URL(u); return x.pathname + x.hash; } catch { return u || ''; } };
const host = (u) => { try { return new URL(u).host; } catch { return u; } };
const unpayload = (t) => String(t || '').replace(/\$[A-Z0-9]+/g, (k) => PAYLOAD[k] || k);
document.documentElement.classList.add('js');

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

// ---------------------------------------------------------------- words

function what(s, live) {
  const label = s.label ? `“${s.label.length > 34 ? s.label.slice(0, 33) + '…' : s.label}”` : 'an element';
  const text = s.text in PAYLOAD ? PAYLOAD[s.text] : s.text ? `“${String(s.text).slice(0, 24)}”` : 'nothing';
  const L = live;
  switch (s.action) {
    case 'click': case 'check': return `${L ? 'Clicking' : 'Click'} ${label}`;
    case 'rage_click': return `${L ? 'Rage-clicking' : 'Rage-click'} ${label}${L ? '' : ` ${s.times || 6} times`}`;
    case 'dblclick': return `${L ? 'Double-clicking' : 'Double-click'} ${label}`;
    case 'hover': return `${L ? 'Hovering over' : 'Hover over'} ${label}`;
    case 'type': return `${L ? 'Typing' : 'Type'} ${text} into ${label}${s.submit ? (L ? ' and pressing Enter' : ', then press Enter') : ''}`;
    case 'select': return `${L ? 'Picking' : 'Pick'} an option in ${label}`;
    case 'press': return `${L ? 'Pressing' : 'Press'} ${KEYS[s.key] || s.key}`;
    case 'scroll': return `${L ? 'Scrolling' : 'Scroll'} ${s.dy < 0 ? 'up' : 'down'} ${Math.abs(s.dy)}px`;
    case 'resize': return `${L ? 'Resizing to' : 'Resize to'} ${s.width}px wide`;
    case 'set_viewport': return `Use a ${s.width} × ${s.height} screen`;
    case 'throttle': return { offline: L ? 'Going offline' : 'Go offline', slow: L ? 'Slowing the network to a crawl' : 'Slow the network to a crawl', online: L ? 'Coming back online' : 'Come back online' }[s.mode] || 'Changing the network';
    case 'goto': return `${L ? 'Opening' : 'Open'} ${route(s.url) || s.url}`;
    case 'back': return L ? 'Pressing Back' : 'Press Back';
    case 'forward': return L ? 'Pressing Forward' : 'Press Forward';
    case 'reload': return L ? 'Reloading' : 'Reload the page';
    case 'wait': return L ? 'Waiting a moment' : `Wait ${((s.ms || 400) / 1000).toFixed(1)}s`;
    default: return s.action || '';
  }
}


// ---------------------------------------------------------------- landing

function drawMotif() {
  const svg = $('#swarm-motif');
  if (!svg || svg.childElementCount) return;
  let seed = 7;
  const rnd = () => { seed = (seed * 9301 + 49297) % 233280; return seed / 233280; };
  const ns = 'http://www.w3.org/2000/svg';
  const el = (tag, attrs, parent = svg) => { const e = document.createElementNS(ns, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); parent.appendChild(e); return e; };
  // the page under attack
  el('rect', { class: 'page', x: 250, y: 92, width: 240, height: 268, rx: 16 });
  el('rect', { class: 'page-line', x: 270, y: 116, width: 96, height: 10, rx: 5 });
  [150, 172, 194].forEach((y, i) => el('rect', { class: 'page-line', x: 270, y, width: [200, 168, 184][i], height: 8, rx: 4 }));
  el('rect', { class: 'page-line', x: 270, y: 226, width: 92, height: 72, rx: 8 });
  el('rect', { class: 'page-line', x: 378, y: 226, width: 92, height: 72, rx: 8 });
  el('rect', { x: 270, y: 314, width: 110, height: 26, rx: 8, fill: '#1E4A38', opacity: 0.85 });
  // the swarm: clusters drifting toward the page
  const groups = [el('g', { class: 'drift' }), el('g', { class: 'drift b' }), el('g', { class: 'drift c' })];
  const pts = [];
  for (let i = 0; i < 46; i++) {
    const a = rnd() * Math.PI * 2, r = Math.sqrt(rnd());
    const x = 150 + Math.cos(a) * 150 * r + (rnd() - 0.5) * 30, y = 225 + Math.sin(a) * 170 * r;
    if (x > 238 && y > 80 && y < 372) continue;
    pts.push([x, y, 1.8 + rnd() * 3.2, i % 3]);
  }
  pts.forEach(([x, y, , g], i) => pts.slice(i + 1).forEach(([x2, y2, , g2]) => {
    if (g === g2 && Math.hypot(x - x2, y - y2) < 56) el('line', { class: 'edge', x1: x, y1: y, x2, y2 }, groups[g]);
  }));
  pts.forEach(([x, y, r, g]) => el('circle', { class: 'node', cx: x, cy: y, r, opacity: (0.18 + r / 9).toFixed(2) }, groups[g]));
  // a few agent cursors already on the page, one bug flagged
  [[318, 248, 1], [430, 170, 0.75], [338, 323, 0.9], [452, 268, 0.6]].forEach(([x, y, o]) =>
    el('path', { d: 'M0 0v16l4-3.8 2.9 6.6 2.7-1.2-2.8-6.3h5.6z', transform: `translate(${x} ${y})`, fill: '#1E4A38', stroke: '#fff', 'stroke-width': 1.3, 'stroke-linejoin': 'round', opacity: o }));
  el('circle', { class: 'bugmark', cx: 470, cy: 112, r: 7 });
  el('path', { d: 'M466.5 112h7M470 108.5v7', stroke: '#fff', 'stroke-width': 1.6, 'stroke-linecap': 'round', transform: 'rotate(45 470 112)' });
}

let revealObs = null;
function revealOnScroll() {
  if (revealObs) return;
  if (!('IntersectionObserver' in window)) { document.querySelectorAll('.reveal').forEach((e) => e.classList.add('in')); return; }
  revealObs = new IntersectionObserver((entries) => entries.forEach((en) => {
    if (en.isIntersecting) { en.target.classList.add('in'); revealObs.unobserve(en.target); }
  }), { threshold: 0.12 });
  document.querySelectorAll('.reveal').forEach((e) => revealObs.observe(e));
}

window.addEventListener('scroll', () => $('#nav').classList.toggle('scrolled', scrollY > 8), { passive: true });

// ---------------------------------------------------------------- status + chips

let STATUS = { nebius_key: false, mock_ultra: false };
async function loadStatus() {
  try { STATUS = await api('/api/status'); } catch { /* server restarting */ }
  const el = $('#model-status');
  const tav = STATUS.tavily && STATUS.tavily.enabled ? ', research: <b>Tavily</b>' : '';
  if (STATUS.nebius_key) el.innerHTML = `Agents: <b>Nemotron Nano</b>. Fixes: <b>Nemotron 3 Ultra</b>${tav}`;
  else if (STATUS.mock_ultra) el.innerHTML = `No API key: offline agents, <b>mock</b> fixes${tav}`;
  else el.textContent = 'No API key: offline agents only';
  if (STATUS.public) setupPublic();
  if (!STATUS.nebius_key) {
    const nano = $('.chips[data-name=planner] [data-value=nano]');
    nano.disabled = true; nano.title = 'Add NEBIUS_API_KEY to engine/.env to use Nemotron Nano';
    setChip('planner', 'offline');
  }
}

function setupPublic() {
  const targets = STATUS.targets || [];
  const url = $('#url');
  url.readOnly = true;
  url.setAttribute('aria-describedby', 'public-note');
  if (!targets.some((t) => t.url === url.value)) url.value = targets[0]?.url || '';
  $('#source-box').hidden = true;
  $('.demo-row').hidden = true;
  const L = STATUS.limits || {};
  document.querySelectorAll('.chips[data-name=agents] .chip').forEach((c) => { if (+c.dataset.value > (L.agents || 8)) c.disabled = true; });
  document.querySelectorAll('.chips[data-name=minutes] .chip').forEach((c) => { if (+c.dataset.value > (L.minutes || 10)) c.disabled = true; });
  if (+chip('agents') > (L.agents || 8)) setChip('agents', L.agents);
  if (+chip('minutes') > (L.minutes || 10)) setChip('minutes', L.minutes);
  if (!$('#public-row')) {
    $('.url-row').insertAdjacentHTML('afterend', `
      <div class="chip-row" id="public-row">
        <span class="label" id="lbl-target">Demo site</span>
        <div class="chips" role="group" aria-labelledby="lbl-target" data-name="target">
          ${targets.map((t) => `<button type="button" class="chip" data-value="${esc(t.url)}" aria-pressed="${t.url === url.value}">${esc(t.label)}</button>`).join('')}
        </div>
      </div>
      <p class="hint" id="public-note">This public demo runs on our own demo sites only, so nobody's site gets attacked by accident. Run SwarmQA on your computer to test any URL.</p>`);
    $('.chips[data-name=target]').addEventListener('click', (e) => {
      const c = e.target.closest('.chip'); if (!c) return;
      setChip('target', c.dataset.value); url.value = c.dataset.value;
    });
  }
}

function setChip(name, value) {
  document.querySelectorAll(`.chips[data-name=${name}] .chip`).forEach((c) => c.setAttribute('aria-pressed', String(c.dataset.value === String(value))));
}
function chip(name) { return $(`.chips[data-name=${name}] .chip[aria-pressed=true]`)?.dataset.value; }
document.querySelectorAll('.chips').forEach((g) => g.addEventListener('click', (e) => {
  const c = e.target.closest('.chip');
  if (c && !c.disabled) setChip(g.dataset.name, c.dataset.value);
}));

// ---------------------------------------------------------------- swarm page

function initSwarmPage() {
  const last = store.get('last', {});
  if (!STATUS.public) {
    if (last.url && !$('#url').value) $('#url').value = last.url;
    if (last.repo && !$('#repo').value) { $('#repo').value = last.repo; $('#source-box').open = true; }
  }
  if (last.agents) setChip('agents', last.agents);
  if (last.minutes) setChip('minutes', last.minutes);
}

async function loadHistory() {
  let runs = [];
  try { runs = await api('/api/runs'); } catch { return; }
  const list = $('#history-list');
  list.innerHTML = '';
  $('#history').hidden = !runs.length;
  for (const r of runs.slice(0, 8)) {
    const li = document.createElement('li');
    const bugs = r.findings === 1 ? '1 bug' : `${r.findings} bugs`;
    const when = new Date(r.started * 1000).toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
    li.innerHTML = `<a href="/swarm?run=${esc(r.id)}" data-nav><span class="h-url">${esc(host(r.url))}${esc(route(r.url) === '/' ? '' : route(r.url))}</span>
      <span class="h-bugs">${r.status === 'running' ? 'running' : bugs}</span><span class="h-when">${esc(when)}</span></a>`;
    list.appendChild(li);
  }
}

function setStartBusy(busy, label) {
  const b = $('#start-btn');
  b.disabled = busy; b.textContent = label || 'Start swarm';
}

$('#start-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const body = { url: $('#url').value.trim(), agents: +chip('agents'), minutes: +chip('minutes'), planner: chip('planner'), repo: $('#repo').value.trim() };
  const err = $('#start-error');
  if (!body.url) { err.textContent = 'Enter the address of the site to test.'; err.hidden = false; $('#url').focus(); return; }
  setStartBusy(true, 'Checking the site…'); err.hidden = true;
  try {
    const run = await api('/api/runs', body);
    store.set('last', { url: body.url, repo: body.repo, agents: body.agents, minutes: body.minutes });
    go(`/swarm?run=${run.id}`, true);
  } catch (ex) {
    err.textContent = ex.message; err.hidden = false; setStartBusy(false);
  }
});

document.querySelectorAll('[data-demo]').forEach((b) => b.addEventListener('click', () => {
  $('#url').value = b.dataset.demo;
  const known = store.get('repos', {})[b.dataset.demo];
  if (known) { $('#repo').value = known; $('#source-box').open = true; }
  $('#url').focus();
}));
$('#repo').addEventListener('change', () => {
  const repos = store.get('repos', {}); repos[$('#url').value.trim()] = $('#repo').value.trim(); store.set('repos', repos);
});

// ---------------------------------------------------------------- live run

let SOURCE = null;
let RUN = null;

function clearRun() {
  if (SOURCE) { SOURCE.close(); SOURCE = null; }
  RUN = null;
  $('#run').hidden = true; $('#empty').hidden = false;
  $('#start-form').classList.remove('compact');
  setStartBusy(false);
  loadHistory();
}

function showRun(id) {
  if (RUN && RUN.id === id) return;
  if (SOURCE) SOURCE.close();
  $('#empty').hidden = true; $('#run').hidden = false;
  $('#tiles').innerHTML = ''; $('#bug-list').innerHTML = ''; $('#stats').innerHTML = '';
  $('#bugs-empty').hidden = false; $('#run-banner').hidden = true;
  RUN = { id, meta: null, tiles: new Map(), findings: new Map(), patches: {}, actions: 0, pages: new Set(),
          clock: { t: 0, at: performance.now() }, status: 'running', minutes: 2, ended: false };
  SOURCE = new EventSource(`/api/runs/${id}/stream`);
  SOURCE.onmessage = (m) => { try { onEvent(JSON.parse(m.data)); } catch (err) { console.error(err); } };
  SOURCE.onerror = () => { if (RUN && RUN.ended && SOURCE) SOURCE.close(); };
  api(`/api/runs/${id}`).then((r) => { RUN.patches = r.patches || {}; Object.keys(RUN.patches).forEach(markFixed); })
    .catch(() => { banner('That run no longer exists.', 'bad'); });
}

function elapsed() { return RUN.clock.t + (RUN.ended ? 0 : (performance.now() - RUN.clock.at) / 1000); }

function renderHead() {
  const m = RUN.meta; if (!m) return;
  const st = RUN.status;
  const left = Math.max(0, RUN.minutes * 60 - elapsed());
  $('#run-url').textContent = m.url; $('#run-url').title = m.url;
  const pill = $('#run-pill');
  pill.className = `pill ${st === 'running' ? 'live' : st === 'error' ? 'bad' : ''}`;
  pill.textContent = st === 'running' ? `Live, ${mmss(left)} left` : st === 'stopping' ? 'Stopping…'
    : st === 'error' ? 'Stopped with an error' : `Finished in ${mmss(RUN.summary?.seconds ?? elapsed())}`;
  if (RUN.headStatus === st) return;
  RUN.headStatus = st;
  $('#start-form').classList.add('compact');
  setStartBusy(st === 'running' || st === 'stopping', st === 'running' || st === 'stopping' ? 'Swarm running…' : 'Start swarm');
  $('#run-actions').innerHTML = st === 'running' || st === 'stopping' ? '<button class="btn btn-ghost" id="stop-btn">Stop</button>'
    : `<a class="btn btn-ghost" href="/api/runs/${RUN.id}/report.md" download>Download report</a><a class="btn btn-ghost" href="/swarm" data-nav>New swarm</a>`;
  const s = $('#stop-btn');
  if (s) s.onclick = async () => { s.disabled = true; RUN.status = 'stopping'; renderHead(); await api(`/api/runs/${RUN.id}/stop`, {}).catch(() => {}); };
}

function renderStats() {
  const bugs = RUN.findings.size;
  const high = [...RUN.findings.values()].filter((f) => f.severity === 'high').length;
  $('#stats').innerHTML = [
    [RUN.tiles.size, 'Agents'], [RUN.actions, 'Actions'], [RUN.pages.size || 0, 'Pages'],
    [bugs, high ? `Bugs, ${high} high` : 'Bugs'], [mmss(elapsed()), 'Elapsed'],
  ].map(([n, l]) => `<div class="stat"><b>${esc(n)}</b><span>${esc(l)}</span></div>`).join('');
  $('#bugs-count').textContent = bugs;
}

function tile(i) {
  let t = RUN.tiles.get(i);
  if (t) return t;
  const el = $('#tile-tpl').content.firstElementChild.cloneNode(true);
  el.querySelector('.dot').style.background = COLORS[i % COLORS.length];
  el.querySelector('.name').textContent = `Agent ${i + 1}`;
  el.setAttribute('aria-label', `Agent ${i + 1}: see what it did`);
  el.addEventListener('click', () => openAgent(i));
  t = { el, img: el.querySelector('img'), wait: el.querySelector('.screen-wait') };
  RUN.tiles.set(i, t);
  [...RUN.tiles.entries()].sort((a, b) => a[0] - b[0]).forEach(([, v]) => $('#tiles').appendChild(v.el));
  return t;
}

function onEvent(ev) {
  if (!RUN) return;
  if (ev.t !== undefined && !RUN.ended) RUN.clock = { t: ev.t, at: performance.now() };
  switch (ev.kind) {
    case 'hello':
      RUN.meta = ev.run; RUN.minutes = ev.run.opts?.minutes || 2; RUN.status = ev.run.status;
      document.title = `SwarmQA: ${host(ev.run.url)}`;
      if (ev.run.status !== 'running' && ev.run.ended) { RUN.ended = true; RUN.clock = { t: ev.run.ended - ev.run.started, at: performance.now() }; }
      renderHead(); break;
    case 'run_start': (ev.personas || []).forEach((_, i) => tile(i)); break;
    case 'agent_start': {
      const t = tile(ev.agent);
      t.el.querySelector('.name').textContent = ev.tag || ev.persona;
      t.el.dataset.tag = ev.tag || ev.persona;
      t.el.setAttribute('aria-label', `${ev.tag || ev.persona}: see what it did`); break;
    }
    case 'frame': {
      const t = tile(ev.agent);
      t.img.src = `data:image/jpeg;base64,${ev.data}`;
      t.wait.hidden = true; return;
    }
    case 'plan': if (ev.thought) tile(ev.agent).el.querySelector('.thinking').textContent = unpayload(ev.thought); break;
    case 'action': {
      RUN.actions += 1;
      const t = tile(ev.agent);
      if (ev.step) t.el.querySelector('.doing').textContent = what(ev.step, true);
      if (ev.page) { t.el.querySelector('.where').textContent = ev.page; RUN.pages.add(ev.page.includes('#/') ? ev.page : ev.page.split('#')[0]); }
      break;
    }
    case 'finding': addFinding(ev.finding, !ev.replay); break;
    case 'patch': RUN.patches[ev.patch.finding_id] = ev.patch; markFixed(ev.patch.finding_id); break;
    case 'agent_error': banner(`Agent ${ev.agent + 1} couldn't keep going: ${ev.error}`, 'bad'); break;
    case 'agent_done': tile(ev.agent).el.classList.add('done'); break;
    case 'run_error': banner(ev.error, 'bad'); break;
    case 'run_finished': {
      RUN.status = ev.status; RUN.ended = true; RUN.summary = ev.summary || null;
      RUN.tiles.forEach((t) => t.el.classList.add('done'));
      const n = RUN.findings.size, s = ev.summary || {};
      if (!s.actions && !n) banner('No agent could use the site. Check that the address opens in a browser on this computer.', 'bad');
      else banner(`${n ? `Found ${n} ${n === 1 ? 'bug' : 'bugs'}` : 'No bugs found'} in ${mmss(s.seconds || elapsed())}, across ${s.pages_visited || RUN.pages.size} ${(s.pages_visited || RUN.pages.size) === 1 ? 'page' : 'pages'} and ${s.actions || RUN.actions} actions. ${n ? 'Open a bug for the steps and a fix, or ' : ''}click an agent to hear what it tried.`);
      renderHead(); break;
    }
  }
  renderStats();
}

function banner(text, kind) {
  const b = $('#run-banner');
  b.className = `banner ${kind || ''}`; b.textContent = text; b.hidden = false;
}

function addFinding(f, live) {
  if (RUN.findings.has(f.id)) return;
  RUN.findings.set(f.id, f);
  $('#bugs-empty').hidden = true;
  const li = document.createElement('li');
  const color = COLORS[(f.agent >= 0 ? f.agent : 0) % COLORS.length];
  const when = RUN.meta ? mmss(Date.parse(f.ts) / 1000 - RUN.meta.started) : '';
  li.innerHTML = `<button class="bug" data-id="${esc(f.id)}">
      <span class="bug-top"><span class="sev ${esc(f.severity)}">${esc(SEV[f.severity] || f.severity)}</span>
        <span class="bug-title">${esc(TITLES[f.bug_type] || f.bug_type)}</span><span class="bug-fixed" hidden>Fix ready</span></span>
      <span class="bug-msg">${esc(plain(f))}</span>
      <span class="bug-meta"><i class="dot" style="background:${color}"></i>${esc(tagOf(f))}, <span class="mono">${esc(route(f.page_url) || '/')}</span>${when ? `, <span class="mono">${when}</span>` : ''}</span>
      ${f.shot_url ? `<img class="bug-thumb" src="${esc(f.shot_url)}" alt="" loading="lazy">` : ''}
    </button>`;
  li.querySelector('button').onclick = () => openFinding(f.id);
  $('#bug-list').prepend(li);
  if (RUN.patches[f.id]) markFixed(f.id);
  if (live && f.agent >= 0) {
    const t = RUN.tiles.get(f.agent);
    if (t) { t.el.classList.add('hit'); setTimeout(() => t.el.classList.remove('hit'), 2600); }
  }
}

function tagOf(f) {
  const t = RUN.tiles.get(f.agent);
  return (t && t.el.dataset.tag) || f.persona || '';
}

function markFixed(id) {
  const b = document.querySelector(`.bug[data-id="${CSS.escape(id)}"] .bug-fixed`);
  const p = RUN.patches[id];
  if (b && p && !p.error) b.hidden = false;
}

// ---------------------------------------------------------------- drawers

let lastFocus = null;
function openDrawer(html) {
  if ($('#drawer').hidden) lastFocus = document.activeElement;
  $('#drawer-inner').innerHTML = html;
  $('#scrim').hidden = false; $('#drawer').hidden = false;
  $('#drawer').scrollTop = 0;
  $('#d-close').onclick = closeDrawer; $('#d-close').focus();
}
function closeDrawer() {
  $('#drawer').hidden = true; $('#scrim').hidden = true;
  if (lastFocus && lastFocus.focus) lastFocus.focus();
}
$('#scrim').addEventListener('click', closeDrawer);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('#drawer').hidden) closeDrawer(); });

const stepsHtml = (steps) => steps.map((s) => `<li>${esc(what(s, false)).replace(/“(.*?)”/g, '<b>$1</b>')}</li>`).join('');

function openFinding(id) {
  const f = RUN.findings.get(id); if (!f) return;
  const when = RUN.meta ? mmss(Date.parse(f.ts) / 1000 - RUN.meta.started) : '';
  openDrawer(`
    <div class="d-head">
      <h2 id="d-title">${esc(TITLES[f.bug_type] || f.bug_type)}</h2>
      <span class="sev ${esc(f.severity)}">${esc(SEV[f.severity] || '')}</span>
      <button class="d-close" id="d-close" aria-label="Close">×</button>
    </div>
    <p class="d-msg">${esc(plain(f))}</p>
    ${plain(f) !== f.message ? `<p class="d-tech">${esc(f.message)}</p>` : ''}
    <dl class="facts">
      <div><dt>Found by</dt><dd><button class="link" id="by-agent">${esc(tagOf(f))}</button></dd></div>
      <div><dt>Page</dt><dd class="mono" style="font-size:15px">${esc(route(f.page_url) || '/')}</dd></div>
      <div><dt>Screen</dt><dd class="mono" style="font-size:15px">${esc(f.viewport.replace('x', ' × '))}</dd></div>
      ${when ? `<div><dt>Into the run</dt><dd class="mono" style="font-size:15px">${when}</dd></div>` : ''}
    </dl>
    ${f.shot_url ? `<figure><img class="d-shot" src="${esc(f.shot_url)}" alt="The page when the bug happened"><figcaption>The agent's screen at the moment it broke.</figcaption></figure>` : ''}
    ${(f.repro || []).length ? `<section class="d-section"><p class="label">Steps to reproduce</p><ol class="repro steps">${stepsHtml(f.repro)}</ol>
      <div class="row"><button class="btn btn-ghost" id="replay-btn">Replay these steps</button>
        ${(f.repro || []).length > 3 ? '<button class="btn btn-ghost" id="shorten-btn">Shorten the steps</button>' : ''}
        <span class="result" id="replay-result"></span></div></section>` : ''}
    <div class="row"><button class="btn btn-ghost" id="issue-btn">Copy as GitHub issue</button><span class="result" id="issue-result"></span></div>
    ${f.stack ? `<details class="stack"><summary>Stack trace</summary><pre>${esc(f.stack)}</pre></details>` : ''}
    <section class="d-section" id="fix-section"></section>`);
  $('#by-agent').onclick = () => openAgent(f.agent);
  $('#issue-btn').onclick = async () => {
    const out = $('#issue-result');
    try {
      const res = await fetch(`/api/runs/${RUN.id}/report.md?finding=${encodeURIComponent(f.id)}`);
      const md = await res.text();
      try { await navigator.clipboard.writeText(md); out.className = 'result ok'; out.textContent = 'Copied. Paste it into a new GitHub issue.'; }
      catch {
        out.className = 'result wait'; out.textContent = 'Your browser blocked the clipboard. Select the text below and copy it.';
        if (!$('#issue-text')) out.parentElement.insertAdjacentHTML('afterend', `<pre class="plain" id="issue-text">${esc(md)}</pre>`);
      }
    } catch (e) { out.className = 'result bad'; out.textContent = e.message; }
  };
  const rb = $('#replay-btn');
  if (rb) rb.onclick = () => replay(f, $('#replay-result'), rb, false);
  const sb = $('#shorten-btn');
  if (sb) sb.onclick = async () => {
    const out = $('#replay-result');
    sb.disabled = true; out.className = 'result wait'; out.textContent = 'Removing steps one at a time and replaying each version…';
    try {
      const r = await api(`/api/runs/${RUN.id}/findings/${f.id}/minimize`, {});
      if (r.steps && r.steps.length < (f.repro || []).length) {
        const before = f.repro.length;
        f.repro = r.steps; $('.steps').innerHTML = stepsHtml(r.steps);
        out.className = 'result ok'; out.textContent = `Down from ${before} steps to ${r.steps.length}.`;
        sb.remove();
      } else { out.className = 'result wait'; out.textContent = r.error || 'Every step is needed.'; sb.disabled = false; }
    } catch (e) { out.className = 'result bad'; out.textContent = e.message; sb.disabled = false; }
  };
  renderFix(f);
}

async function openAgent(i) {
  if (!RUN || i < 0) return;
  const t = RUN.tiles.get(i);
  const tag = (t && t.el.dataset.tag) || `Agent ${i + 1}`;
  const color = COLORS[i % COLORS.length];
  openDrawer(`
    <div class="d-head">
      <h2 id="d-title"><i class="dot" style="background:${color};width:14px;height:14px;margin-right:10px;vertical-align:middle"></i>${esc(tag)}<span class="sub">Agent ${i + 1}</span></h2>
      <button class="d-close" id="d-close" aria-label="Close">×</button>
    </div>
    <div id="agent-body"><p class="wait-note"><span class="spinner"></span>Reading this agent's log…</p></div>`);
  let story;
  try { story = await api(`/api/runs/${RUN.id}/agents/${i}`); } catch (e) {
    $('#agent-body').innerHTML = `<p class="result bad">${esc(e.message)}</p>`; return;
  }
  if ($('#drawer').hidden || !$('#agent-body')) return;
  const s = story.stats;
  const shot = t && t.img.getAttribute('src');
  const tl = story.timeline.map((b) => `<li>
      <span class="t">${mmss(b.t)}</span>
      <span class="plan">${esc(b.thought || 'Look around')}<span class="by">${b.source === 'nano' ? 'Nano' : b.source === 'heuristic' ? 'Rules' : ''}</span></span>
      <ul>${b.actions.map((a) => `<li class="${a.ok ? '' : 'miss'}">${esc(a.say)}<span class="pg">${esc(a.page || '/')}</span></li>`).join('')}</ul>
    </li>`);
  story.findings.forEach((f) => {
    const at = story.timeline.findIndex((b) => b.t > (f.t ?? 1e9));
    const line = `<li class="bugline"><span class="t">${f.t != null ? mmss(f.t) : ''}</span><span class="plan">Found ${esc((TITLES[f.bug_type] || f.bug_type).toLowerCase())} on <span class="mono">${esc(f.page)}</span></span></li>`;
    if (at < 0) tl.push(line); else tl.splice(at + (tl.length - story.timeline.length), 0, line);
  });
  $('#agent-body').innerHTML = `
    <div class="d-section">
      <p class="intent">${esc(story.intent || story.brief)}</p>
      <div class="voice" aria-live="polite">
        <p class="label">In its own words</p>
        <p class="say" id="agent-say"><span class="wait-note"><span class="spinner"></span>${STATUS.nebius_key ? 'Nemotron Nano is turning the log into plain words…' : 'Summarising the log…'}</span></p>
        <p class="src" id="agent-src"></p>
      </div>
    </div>
    <dl class="facts">
      <div><dt>Moves</dt><dd class="mono">${s.actions}</dd></div>
      <div><dt>Pages</dt><dd class="mono">${s.pages.length}</dd></div>
      <div><dt>Bugs found</dt><dd class="mono">${story.findings.length}</dd></div>
      <div><dt>Didn't land</dt><dd class="mono">${s.failed}</dd></div>
    </dl>
    ${shot ? `<figure><img class="d-shot live" src="${shot}" alt="This agent's latest screen"><figcaption>${story.done ? 'Its last screen.' : 'Its screen right now.'}</figcaption></figure>` : ''}
    ${story.findings.length ? `<section class="d-section"><p class="label">Bugs it found</p><ul class="agent-bugs">${story.findings.map((f) => `<li><button data-fid="${esc(f.id)}"><span class="sev ${esc(f.severity)}">${esc(SEV[f.severity] || '')}</span><b>${esc(TITLES[f.bug_type] || f.bug_type)}</b><span class="m">${esc(f.message)}</span></button></li>`).join('')}</ul></section>` : ''}
    <section class="d-section"><p class="label">Everything it did${story.done ? '' : ' so far'}</p>
      ${tl.length ? `<ol class="timeline">${tl.join('')}</ol>` : '<p class="hint">Nothing yet. It is still opening the page.</p>'}
      ${story.done ? '' : '<div class="row"><button class="btn btn-ghost" id="agent-refresh">Refresh</button></div>'}
    </section>`;
  document.querySelectorAll('.agent-bugs [data-fid]').forEach((b) => { b.onclick = () => openFinding(b.dataset.fid); });
  const rf = $('#agent-refresh'); if (rf) rf.onclick = () => openAgent(i);
  try {
    const ex = await api(`/api/runs/${RUN.id}/agents/${i}/explain`, {});
    if (!$('#agent-say')) return;
    $('#agent-say').textContent = ex.text;
    $('#agent-src').textContent = ex.source === 'nano' ? `Written by Nemotron Nano from this agent's log of ${ex.actions} moves.`
      : `Summary built from this agent's log of ${ex.actions} moves.`;
  } catch (e) {
    if ($('#agent-say')) $('#agent-say').textContent = `Couldn't explain: ${e.message}`;
  }
}

async function replay(f, out, btn, afterFix) {
  btn.disabled = true;
  out.className = 'result wait'; out.textContent = 'Replaying in a fresh browser…';
  try {
    const r = await api(`/api/runs/${RUN.id}/findings/${f.id}/replay`, {});
    if (afterFix) {
      out.className = `result ${r.reproduced ? 'bad' : 'ok'}`;
      out.textContent = r.reproduced ? 'Still breaks with the same steps.' : 'Fixed: the same steps no longer break the page.';
    } else {
      out.className = `result ${r.reproduced ? 'ok' : 'wait'}`;
      out.textContent = r.reproduced ? 'Reproduced: it breaks every time.' : 'Didn’t break this time. It may depend on timing.';
    }
  } catch (e) { out.className = 'result bad'; out.textContent = e.message; }
  btn.disabled = false;
}

function renderFix(f) {
  const box = $('#fix-section');
  const p = RUN.patches[f.id];
  const canFix = STATUS.nebius_key || STATUS.mock_ultra;
  const repo = (p && p.repo) || RUN.meta?.repo || store.get('repos', {})[RUN.meta?.url] || '';
  if (!p) {
    box.innerHTML = `<p class="label">Suggested fix</p>
      <div class="fix">
        <p class="fix-why">${repo ? `Ultra will read the files behind this bug in <code>${esc(repo)}</code> and write a patch.`
          : 'Ultra will suggest a fix from what the page showed. Add the source folder for a real code patch.'}</p>
        ${STATUS.public ? '' : `<label class="label" for="fix-repo">Project folder (optional)</label>
        <input id="fix-repo" class="input mono" type="text" value="${esc(repo)}" placeholder="C:\\Users\\you\\projects\\my-site">`}
        ${STATUS.tavily?.enabled ? '<p class="hint">First, Tavily searches the docs and known issues for this error, and Ultra reads what it finds.</p>' : ''}
        <div class="row"><button class="btn btn-primary" id="fix-btn" ${canFix ? '' : 'disabled'}>Suggest a fix with Nemotron 3 Ultra</button></div>
        ${canFix ? '' : '<p class="hint">Add NEBIUS_API_KEY to engine/.env and restart to get fixes.</p>'}
      </div>`;
    const btn = $('#fix-btn');
    if (btn) btn.onclick = async () => {
      const r = $('#fix-repo') ? $('#fix-repo').value.trim() : '';
      if (r) { const repos = store.get('repos', {}); repos[RUN.meta.url] = r; store.set('repos', repos); }
      btn.disabled = true;
      box.querySelector('.fix').insertAdjacentHTML('beforeend',
        '<p class="wait-note" id="fix-wait"><span class="spinner"></span><span id="fix-stage"></span></p>');
      const stages = STATUS.tavily?.enabled
        ? [[0, 'Searching docs and known issues with Tavily…'], [2500, 'Nemotron 3 Ultra is reading the evidence, the code and the sources…'], [25000, 'Still thinking. Ultra reasons before it answers; this can take a minute.']]
        : [[0, 'Nemotron 3 Ultra is reading the evidence and the code…'], [25000, 'Still thinking. Ultra reasons before it answers; this can take a minute.']];
      const timers = stages.map(([ms, txt]) => setTimeout(() => { const el = $('#fix-stage'); if (el) el.textContent = txt; }, ms));
      try {
        const patch = await api(`/api/runs/${RUN.id}/findings/${f.id}/fix`, { repo: r });
        RUN.patches[f.id] = patch; markFixed(f.id);
      } catch (e) {
        RUN.patches[f.id] = { error: e.message, finding_id: f.id };
      }
      timers.forEach(clearTimeout);
      renderFix(f);
    };
    return;
  }
  if (p.error && !p.summary) {
    box.innerHTML = `<p class="label">Suggested fix</p><div class="fix"><p class="result bad">${esc(p.error)}</p>
      <div class="row"><button class="btn btn-ghost" id="retry-fix">Try again</button></div></div>`;
    $('#retry-fix').onclick = () => { delete RUN.patches[f.id]; renderFix(f); };
    return;
  }
  const conf = Math.round((p.confidence || 0) * 100);
  const model = /mock/.test(p.model || '') ? 'Offline stand-in for Ultra (mock answer)' : `Nemotron 3 Ultra, ${(p.latency_ms / 1000).toFixed(1)}s`;
  const sources = (p.sources || []).map((s) => `<li><code>${esc(s.file)}</code>: ${esc(s.why)}</li>`).join('');
  const rs = p.research || null;
  const used = new Set(p.references || []);
  const web = rs && rs.sources && rs.sources.length ? `
      <div class="web">
        <p class="label">Researched with Tavily</p>
        <p class="hint">Searched: <span class="mono">${esc(rs.query)}</span></p>
        <ol class="web-list">${rs.sources.map((s) => `<li class="${used.has(s.n) ? 'used' : ''}">
          <a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a>
          <span class="dom mono">${esc(s.domain)}</span>${used.has(s.n) ? '<span class="cite">Used in this fix</span>' : ''}
          ${s.snippet ? `<span class="snip">${esc(s.snippet.slice(0, 220))}${s.snippet.length > 220 ? '…' : ''}</span>` : ''}</li>`).join('')}</ol>
        <p class="model-line">${rs.cached ? 'From the research cache, no credits used.' : `${rs.credits || 1} Tavily credit used.`} ${STATUS.tavily ? `${STATUS.tavily.used_this_month + (rs.cached ? 0 : (rs.credits || 1))} of ${STATUS.tavily.cap} used this month.` : ''}</p>
      </div>` : rs && rs.error ? `<p class="hint">Web research skipped: ${esc(rs.error)}</p>` : '';
  const body = p.diff ? `<pre class="diff">${diffHtml(p.diff)}</pre>`
    : p.code ? `<p class="fix-why"><b>Where:</b> ${esc(p.where || 'see explanation')}</p><pre class="plain">${esc(p.code)}</pre>` : '';
  box.innerHTML = `<p class="label">Suggested fix</p>
    <div class="fix">
      <p class="fix-summary">${esc(p.summary)}</p>
      <p class="fix-why">${esc(p.explanation)}</p>
      <div class="conf"><span class="conf-bar"><i style="width:${conf}%"></i></span>${conf}% confident${p.diff ? '' : ', page-level suggestion'}</div>
      ${p.note ? `<p class="hint">${esc(p.note)}</p>` : ''}
      ${web}
      ${sources ? `<ul class="sources">${sources}</ul>` : ''}
      ${body}
      <div class="row">
        ${p.diff && p.repo ? `<button class="btn btn-primary" id="apply-btn" ${p.applied ? 'disabled' : ''}>${p.applied ? 'Applied' : 'Apply to the source'}</button>` : ''}
        ${!p.diff && p.code ? '<button class="btn btn-ghost" id="copy-btn">Copy code</button>' : ''}
        ${p.diff && p.applied ? '<button class="btn btn-ghost" id="verify-btn">Replay to verify</button>' : ''}
        <span class="result" id="fix-result"></span>
      </div>
      ${p.applied ? `<p class="hint">Applied with a backup. <button class="link" id="undo-btn">Undo all applied fixes</button></p>` : ''}
      <p class="model-line">${esc(model)}. Suggested patch: review before you ship it.</p>
    </div>`;
  const ab = $('#apply-btn');
  if (ab && !p.applied) ab.onclick = async () => {
    ab.disabled = true;
    try {
      const r = await api(`/api/runs/${RUN.id}/findings/${f.id}/apply`, { repo: p.repo });
      p.applied = true; renderFix(f);
      const out = $('#fix-result'); out.className = 'result ok';
      out.textContent = `Changed ${r.files.join(', ')}. If your dev server is running it has reloaded.`;
    } catch (e) { ab.disabled = false; const out = $('#fix-result'); out.className = 'result bad'; out.textContent = e.message; }
  };
  const vb = $('#verify-btn');
  if (vb) vb.onclick = () => replay(f, $('#fix-result'), vb, true);
  const cb = $('#copy-btn');
  if (cb) cb.onclick = async () => { try { await navigator.clipboard.writeText(p.code); cb.textContent = 'Copied'; } catch { cb.textContent = 'Select and copy'; } };
  const ub = $('#undo-btn');
  if (ub) ub.onclick = async () => {
    try {
      const r = await api('/api/revert', { repo: p.repo, run: RUN.id });
      Object.values(RUN.patches).forEach((x) => { if (x.repo === p.repo) x.applied = false; });
      renderFix(f);
      const out = $('#fix-result'); out.className = 'result ok';
      out.textContent = r.restored.length ? `Restored ${r.restored.join(', ')}.` : 'Nothing to undo.';
    } catch (e) { const out = $('#fix-result'); out.className = 'result bad'; out.textContent = e.message; }
  };
}

function diffHtml(diff) {
  return diff.replace(/\n$/, '').split('\n').map((l) => {
    const cls = l.startsWith('+++') || l.startsWith('---') ? 'file' : l.startsWith('@@') ? 'hunk' : l.startsWith('+') ? 'add' : l.startsWith('-') ? 'del' : 'ctx';
    return `<span class="${cls}">${esc(l)}</span>`;
  }).join('');
}

// Plain-language version of an engine message (the raw one stays in the drawer).
function plain(f) {
  const m = String(f.message || '').replace(/^Uncaught\s+/, '');
  if (f.bug_type === 'layout_overflow') {
    const x = m.match(/(\d+)px wide in a (\d+)px/);
    const c = (f.dom || '').match(/class="([\w-]+)/);
    if (x) return `The page is ${x[1]}px wide on a ${x[2]}px screen, so it scrolls sideways${c ? `. Cause: ${c[1].replace(/[-_]/g, ' ')}` : ''}.`;
  }
  if (f.bug_type === 'unhandled_promise') return `A request failed and nothing handled it: ${m}`;
  if (f.bug_type === 'blank_screen') return 'The page went white and no error was thrown.';
  if (f.bug_type === 'broken_link') {
    const x = m.match(/Page not found: (\S+) returns (\d+)(?:, linked from (\S+))?/);
    if (x) return `The site links to ${x[1]}, but that page doesn't exist (${x[2]})${x[3] ? `. The link is on ${x[3]}` : ''}.`;
  }
  if (f.bug_type === 'xss') return 'Text typed into the page ran as a script.';
  if (f.bug_type === 'unresponsive') return m.replace(/: the page froze and ignored input/, '. The page ignored every click meanwhile.');
  return m;
}


// ---------------------------------------------------------------- routing (same tab, always)

function go(path, replace) {
  if (replace) history.replaceState({}, '', path); else history.pushState({}, '', path);
  render();
}

function render() {
  let path = location.pathname;
  const legacy = path.match(/^\/run\/([\w-]+)/);
  if (legacy) { history.replaceState({}, '', `/swarm?run=${legacy[1]}`); path = '/swarm'; }
  const app = path.startsWith('/swarm');
  $('#view-home').hidden = app; $('#view-swarm').hidden = !app;
  $('#nav-home').hidden = app; $('#nav-app').hidden = !app;
  closeDrawer();
  if (!app) {
    document.title = 'SwarmQA';
    if (SOURCE) { SOURCE.close(); SOURCE = null; RUN = null; }
    drawMotif(); revealOnScroll();
    if (location.hash) $(location.hash)?.scrollIntoView(); else scrollTo(0, 0);
    return;
  }
  initSwarmPage();
  const id = new URLSearchParams(location.search).get('run');
  if (id) showRun(id); else { document.title = 'SwarmQA: new swarm'; clearRun(); }
}

document.addEventListener('click', (e) => {
  const a = e.target.closest('a[data-nav]');
  if (!a || e.metaKey || e.ctrlKey || e.shiftKey) return;
  e.preventDefault();
  const href = a.getAttribute('href');
  if (href === location.pathname + location.search) { scrollTo({ top: 0, behavior: 'smooth' }); return; }
  go(href);
  if (!href.includes('#')) scrollTo(0, 0);
});
window.addEventListener('popstate', render);
setInterval(() => { if (RUN && !$('#run').hidden && RUN.meta) { renderHead(); renderStats(); } }, 500);

loadStatus().then(render);
