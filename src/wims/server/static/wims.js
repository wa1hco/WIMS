// WIMS console — shared render layer for both pages (operate + status).
// One SSE feed (/events) carries the full JSON state contract; each page includes
// only the DOM containers for the panels it wants, and every render* function
// no-ops when its container is absent. The frontend is the disposable part; the
// state contract (server/state.py) is the durable boundary.

const $ = (id) => document.getElementById(id);
const age = (a) => a == null ? "-" : (a < 90 ? a.toFixed(0)+"s" : (a/60).toFixed(0)+"m");
const mhz = (hz) => hz ? (hz/1e6).toFixed(6) : "-";
const esc = (s) => (s||"").replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const sgn = (n) => (n>=0?'+':'')+n;

function renderHeader(s) {
  if ($("rx")) $("rx").textContent = `rx ${s.rx.wsjtx} WSJT-X / ${s.rx.n1mm} N1MM`;
  if ($("clock")) $("clock").textContent = new Date(s.now*1000).toLocaleTimeString();
}

// -- system status page ----------------------------------------------------- //

function renderSystem(s) {
  const el = $("sys");
  if (!el) return;
  const inst = s.instances || [];
  const by = (h) => inst.filter(n => n.health === h).length;
  const tx = inst.filter(n => n.transmitting).length;
  const quiet = inst.filter(n => n.quiet).length;
  el.innerHTML =
    `<span><span class="dot active"></span><b>WIMS server</b> · live</span>` +
    `<span><span class="k">WSJT-X:</span>${inst.length} (` +
      `<span class="ALIVE">${by("ALIVE")} alive</span>` +
      (by("STALE") ? ` · <span class="STALE">${by("STALE")} stale</span>` : ``) +
      (by("DEAD")  ? ` · <span class="DEAD">${by("DEAD")} dead</span>`   : ``) +
      (quiet ? ` · <span class="quiet">${quiet} quiet</span>` : ``) + `)</span>` +
    `<span><span class="k">transmitting:</span>${tx}</span>` +
    `<span><span class="k">N1MM loggers:</span>${(s.loggers||[]).length}</span>` +
    `<span><span class="k">rx:</span>${s.rx.wsjtx} WSJT-X / ${s.rx.n1mm} N1MM pkts</span>`;
}

function renderInstances(s) {
  const ib = $("inst-body");
  if (!ib) return;
  ib.innerHTML = "";
  $("inst-empty").style.display = s.instances.length ? "none" : "block";
  for (const n of s.instances) {
    const tr = document.createElement("tr");
    if (n.transmitting) tr.className = "tx";
    const health = n.health + (n.quiet ? " · QUIET" : "");
    const collide = n.id_collision ? ' <span class="warn">⚠ id</span>' : '';
    tr.innerHTML =
      `<td>${n.id}${collide}</td><td>${n.host||"-"}</td><td>${n.band||"-"}</td>` +
      `<td>${n.mode||"-"}</td><td class="num">${mhz(n.dial_hz)}</td>` +
      `<td class="state-${n.state}">${n.state}</td>` +
      `<td class="num ${n.quiet?'quiet':''}">${n.decodes_per_period.toFixed(1)}</td>` +
      `<td class="num">${age(n.last_decode_age)}</td>` +
      `<td class="num">${age(n.heartbeat_age)}</td>` +
      `<td class="${n.health}">${health}</td>`;
    ib.appendChild(tr);
  }
}

function renderLoggers(s) {
  const lb = $("log-body");
  if (!lb) return;
  lb.innerHTML = "";
  $("log-empty").style.display = s.loggers.length ? "none" : "block";
  for (const l of s.loggers) {
    const tr = document.createElement("tr");
    const fresh = l.last_seen_age != null && l.last_seen_age < 60;
    const seen = l.last_seen_age == null ? "-" : age(l.last_seen_age) + " ago";
    const lastq = l.last_qso_age == null ? "—"
      : `${l.last_call||""} ${l.last_band||""} (${age(l.last_qso_age)} ago)`;
    tr.innerHTML =
      `<td><span class="dot ${fresh?'active':'idle'}"></span>${l.kind} · ${l.id}</td>` +
      `<td>${l.host||"-"}</td><td>${l.mycall||"-"}</td>` +
      `<td>${seen}</td><td class="num">${l.qso_count}</td>` +
      `<td>${lastq}</td>`;
    lb.appendChild(tr);
  }
}

function snrColor(s) {
  if (s == null) return "transparent";
  const t = Math.max(0, Math.min(1, (s + 24) / 45));   // -24..+21 dB -> 0..1
  return `hsl(140 60% ${90 - t * 56}%)`;               // light=weak, dark green=strong
}

function renderActivity(list) {
  const wrap = $("amap-wrap");
  if (!wrap) return;
  $("amap-empty").style.display = (list && list.length) ? "none" : "block";
  if (!list) return;
  wrap.innerHTML = "";
  for (const a of list) {
    const div = document.createElement("div");
    div.className = "amap";
    let rows = "";
    for (const r of a.rows) {
      const cells = r.snr.map(s => `<span class="cell" style="background:${snrColor(s)}"></span>`).join("");
      rows += `<div class="row"><span class="rlabel">${r.label}</span>` +
              `<span class="cells">${cells}</span></div>`;
    }
    div.innerHTML =
      `<h3>${a.instance} <span class="meta">· ${a.count} decodes · ${a.period_s}s cycles</span></h3>` +
      `<div class="grid">${rows || '<div style="padding:6px;font-size:11px;color:var(--dim)">no decodes</div>'}</div>` +
      `<div class="axis">0 ──────── ${a.freq_max} Hz →</div>`;
    wrap.appendChild(div);
  }
}

function renderDecodes(list) {
  const body = $("dlog-body");
  if (!body) return;
  $("dlog-empty").style.display = (list && list.length) ? "none" : "block";
  if (!list) return;
  body.innerHTML = "";
  for (const e of list) {
    const tr = document.createElement("tr");
    if (e.is_cq) tr.className = "cqrow";
    tr.innerHTML =
      `<td>${new Date(e.ts*1000).toLocaleTimeString()}</td><td>${e.instance}</td>` +
      `<td class="num">${sgn(e.snr)}</td><td class="num">${e.df}</td>` +
      `<td>${esc(e.message)}</td>`;
    body.appendChild(tr);
  }
}

function renderSync(n) {
  if (!n || !$("n1mm-sync")) return;
  const label = {active:"active", idle:"quiet · N1MM has no heartbeat",
                 none:"none heard yet (broadcast not enabled?)"}[n.status];
  const feed = n.feed_age == null ? "none seen" : `${age(n.feed_age)} ago`;
  const lq = n.last_qso ? `${n.last_qso.call} ${n.last_qso.band} (${age(n.last_qso.age)} ago)` : "—";
  const seed = n.seed ? ` ✓ seeded from ${esc(n.seed.source)}` : "";
  $("n1mm-sync").innerHTML =
    `<span><span class="dot ${n.status}"></span><span class="k">live feed:</span><b>${label}</b></span>` +
    `<span><span class="k">last packet:</span>${feed}</span>` +
    `<span><span class="k">packets:</span>${n.packets}</span>` +
    `<span><span class="k">log copy:</span><b>${n.qso_count}</b> QSO${n.qso_count===1?'':'s'}${seed}</span>` +
    `<span><span class="k">last logged:</span>${lq}</span>`;
}

// -- operating page --------------------------------------------------------- //

function renderInterlock(il) {
  if (!il || !$("il-banner")) return;
  const banner = $("il-banner"), meta = $("il-meta");
  if (il.overlap_now) {
    banner.className = "banner alarm";
    banner.textContent = "⚠ TX OVERLAP — two transmitters in one group";
  } else if (il.tx_now.length) {
    banner.className = "banner tx";
    banner.textContent = `▲ ${il.tx_now.length} transmitting · no overlap`;
  } else {
    banner.className = "banner ok";
    banner.textContent = "✓ no overlap · all RX";
  }
  let m = `groups: by ${il.grouping}`;
  if (il.violation_count) {
    const lv = il.last_violation;
    m += ` · ⚠ ${il.violation_count} overlap event(s) since start`;
    if (lv) m += ` (last: ${lv.group} = ${lv.instances.join("+")}, ${age(lv.age)} ago)`;
  } else {
    m += " · 0 overlaps since start";
  }
  meta.textContent = m;

  const rows = il.groups.filter(g => g.transmitting.length || g.instances.length > 1);
  const body = $("il-body"); body.innerHTML = "";
  $("il-empty").style.display = rows.length ? "none" : "block";
  if (!rows.length && il.groups.length)
    $("il-empty").textContent = "no instance transmitting — all RX";
  for (const g of rows) {
    const tr = document.createElement("tr");
    if (g.overlap) tr.className = "overlap";
    const status = g.overlap ? '<span class="warn">⚠ OVERLAP</span>'
                 : g.transmitting.length ? '<span class="state-TX">TX</span>'
                 : '<span class="state-RX">idle</span>';
    tr.innerHTML =
      `<td>${g.group}</td><td>${g.instances.join(", ")}</td>` +
      `<td class="state-TX">${g.transmitting.join(", ")||"—"}</td><td>${status}</td>`;
    body.appendChild(tr);
  }
}

function renderRoster(r) {
  if (!r || !$("ros-meta")) return;
  $("ros-meta").textContent =
    `${r.count} workable · ${r.excluded} suppressed (dupe/unreachable) · ` +
    `strategy ${r.strategy} · band ${r.condition}`;
  const body = $("ros-body"); body.innerHTML = "";
  $("ros-empty").style.display = r.candidates.length ? "none" : "block";
  for (const c of r.candidates) {
    const tr = document.createElement("tr");
    if (c.is_new_mult) tr.className = "mult";
    const badges =
      (c.is_new_mult ? '<span class="badge">new mult</span>' : '') +
      (c.is_rover ? '<span class="badge rover">rover</span>' : '');
    const why = c.factors
      .map(f => `<b>${f.name}</b> ${f.contribution>=0?'+':''}${f.contribution}`)
      .join(" · ");
    tr.innerHTML =
      `<td class="num score">${c.score.toFixed(1)}</td>` +
      `<td>${c.call}${badges}</td><td>${c.grid||"-"}</td><td>${c.band}</td>` +
      `<td>${c.instance}</td><td class="num">${c.snr>=0?'+':''}${c.snr}</td>` +
      `<td class="num">${age(c.age)}</td><td class="why">${why}</td>`;
    body.appendChild(tr);
  }
}

// -- dispatch + connect ----------------------------------------------------- //

function render(s) {
  renderHeader(s);
  renderSystem(s);
  renderInterlock(s.interlock);
  renderRoster(s.roster);
  renderInstances(s);
  renderActivity(s.activity);
  renderDecodes(s.decodes);
  renderSync(s.n1mm_sync);
  renderLoggers(s);
}

function connect() {
  const es = new EventSource("/events");
  es.onopen = () => { $("conn").textContent = "● live"; $("conn").className = "up"; };
  es.onmessage = (e) => render(JSON.parse(e.data));
  es.onerror = () => { $("conn").textContent = "● disconnected"; $("conn").className = "down"; };
}
connect();
