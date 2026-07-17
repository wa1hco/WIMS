/*
 * WIMS — WSJT-X Instance Management System
 * Copyright (C) 2026 Jeff Millar, WA1HCO
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <https://www.gnu.org/licenses/>.
 */

// WIMS console — shared render layer for Operate / Status / Setup.
// One SSE feed (/events) carries the full JSON state contract; each page includes
// only the DOM containers for the panels it wants, and every render* function
// no-ops when its container is absent. The frontend is the disposable part; the
// state contract (server/state.py) is the durable boundary.
//
//   Operate  — roster + interlock (work the contest)
//   Status   — live health, RF/decode activity, operators on the wire
//   Setup    — config: contest log, networking checklist, host app configs

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
  const agents = s.agents || [];
  const aErr = agents.filter(a => a.severity === "error").length;
  el.innerHTML =
    `<span><span class="dot active"></span><b>WIMS server</b> · live</span>` +
    `<span><span class="k">WSJT-X:</span>${inst.length} (` +
      `<span class="ALIVE">${by("ALIVE")} alive</span>` +
      (by("STALE") ? ` · <span class="STALE">${by("STALE")} stale</span>` : ``) +
      (by("DEAD")  ? ` · <span class="DEAD">${by("DEAD")} dead</span>`   : ``) +
      (quiet ? ` · <span class="quiet">${quiet} quiet</span>` : ``) + `)</span>` +
    `<span><span class="k">transmitting:</span>${tx}</span>` +
    `<span><span class="k">N1MM loggers:</span>${(s.loggers||[]).length}</span>` +
    `<span><span class="k">seat agents:</span>${agents.length}` +
      (aErr ? ` · <span class="warn">${aErr} error</span>` : ``) + `</span>` +
    `<span><span class="k">rx:</span>${s.rx.wsjtx} WSJT-X / ${s.rx.n1mm} N1MM pkts</span>`;
}

function _flagOn(v) {
  if (v === true) return '<span class="ALIVE">yes</span>';
  if (v === false) return '<span class="DEAD">no</span>';
  return '<span class="meta">?</span>';
}

function renderAgents(s) {
  // Status table (#agents-body) and Setup drill-down (#setup-agents / #setup-cfg-audit)
  // are on different pages — do not early-return when only one is present.
  const list = s.agents || [];
  const body = $("agents-body");
  if (body) {
    const empty = $("agents-empty");
    if (empty) empty.style.display = list.length ? "none" : "block";
    body.innerHTML = "";
    for (const a of list) {
      const tr = document.createElement("tr");
      if (a.severity === "error") tr.className = "overlap";
      else if (a.severity === "warn") tr.className = "tx";
      const label = a.seat_id
        ? `${esc(a.seat_id)} <span class="meta">(${esc(a.agent_id)})</span>`
        : esc(a.agent_id);
      const host = [a.hostname, (a.lan_ips || []).join(", ")].filter(Boolean).join(" · ") || "-";
      const sevCls = a.severity === "error" ? "DEAD" : (a.severity === "warn" ? "STALE" : "ALIVE");
      const procs = `WSJT ${_flagOn(a.wsjtx_running)} · N1MM ${_flagOn(a.n1mm_running)}`;
      tr.innerHTML =
        `<td>${label}</td><td>${esc(host)}</td>` +
        `<td class="${a.health}">${a.health}</td>` +
        `<td class="${sevCls}">${esc(a.severity)}</td>` +
        `<td class="num">${age(a.age)}</td>` +
        `<td class="num">${a.wsjtx_errors || 0}</td>` +
        `<td>${procs}</td>` +
        `<td style="white-space:normal;max-width:420px">${esc(a.message)}</td>`;
      body.appendChild(tr);
    }
  }

  // Setup page: summary strip + nested config audit (plan: wims_agent_dashboard.md)
  const setupHead = $("setup-agents");
  if (setupHead) {
    if (!list.length) {
      setupHead.innerHTML = `<span class="k">No agents reporting — start wims.agent on each seat with --server http://&lt;this-host&gt;:8787</span>`;
    } else {
      setupHead.innerHTML =
        `<span><span class="k">agents:</span><b>${list.length}</b></span>` +
        list.map(a =>
          `<span><span class="k">${esc(a.seat_id || a.agent_id)}:</span>` +
          `<span class="${a.severity === "error" ? "DEAD" : (a.severity === "warn" ? "STALE" : "ALIVE")}">` +
          `${esc(a.severity)}</span> · ${age(a.age)}` +
          ` · WSJT ${_flagOn(a.wsjtx_running)} N1MM ${_flagOn(a.n1mm_running)}</span>`
        ).join("");
    }
  }
  const setup = $("setup-cfg-audit");
  if (setup) {
    if (!list.length) {
      setup.className = "empty";
      setup.textContent = "No agent config detail yet.";
    } else {
      setup.className = "";
      let html = "";
      for (const a of list) {
        const r = a.report || {};
        const cfgs = ((r.wsjtx || {}).configs) || [];
        const n1 = r.n1mm || {};
        html += `<div style="margin:8px 0 12px;padding:8px;border:1px solid var(--line,#ccc);border-radius:6px;background:var(--panel,#f8f8f8)">`;
        html += `<div><b>${esc(a.seat_id || a.agent_id)}</b>` +
          (a.agent_id && a.seat_id ? ` <span class="meta">(${esc(a.agent_id)})</span>` : "") +
          ` · ${esc(a.hostname || "")}` +
          ((a.lan_ips && a.lan_ips.length) ? ` · ${esc(a.lan_ips.join(", "))}` : "") +
          ` · <span class="${a.health}">${a.health}</span>` +
          ` · <span class="${a.severity === "error" ? "DEAD" : (a.severity === "warn" ? "STALE" : "ALIVE")}">${esc(a.severity)}</span>` +
          `</div>`;
        html += `<div class="meta" style="margin:4px 0">${esc(a.message)}</div>`;
        html += `<div class="meta">Processes: WSJT-X ${_flagOn(a.wsjtx_running)}` +
          ` · N1MM ${_flagOn(a.n1mm_running)}` +
          (a.mode ? ` · mode ${esc(a.mode)}` : "") + `</div>`;

        if (!cfgs.length) {
          html += `<div class="meta" style="margin-top:6px">No WSJT-X configs in last report.</div>`;
        }
        for (const c of cfgs) {
          html += `<div style="margin-top:6px"><b>WSJT-X</b> <code>${esc(c.name)}</code>` +
            (c.source ? ` <span class="meta">${esc(c.source)}</span>` : "") + `</div>`;
          html += `<div style="margin-left:8px">UDP Server <code>${esc(c.udp_server || "-")}</code>` +
            ` port <code>${esc(String(c.udp_port || "-"))}</code>` +
            ` · Outgoing iface <code>${esc(c.udp_iface || "(empty)")}</code>` +
            (c.udp_ttl ? ` · TTL ${esc(String(c.udp_ttl))}` : "") +
            (c.accept_udp != null ? ` · AcceptUDP=${esc(String(c.accept_udp))}` : "") +
            `</div>`;
          if (c.my_call || c.my_grid) {
            html += `<div class="meta" style="margin-left:8px">MyCall ${esc(c.my_call || "-")}` +
              ` · MyGrid ${esc(c.my_grid || "-")}</div>`;
          }
          for (const iss of (c.issues || [])) {
            const cls = iss.severity === "error" ? "DEAD" : (iss.severity === "warn" ? "STALE" : "meta");
            html += `<div class="${cls}" style="margin-left:8px">[${esc(iss.severity)}] ${esc(iss.message)}</div>`;
          }
        }

        html += `<div style="margin-top:8px"><b>N1MM</b> found=${_flagOn(n1.found)}` +
          (n1.user_dir ? ` · user ${esc(n1.user_dir)}` : "") +
          (n1.databases_dir ? ` · Databases ${esc(n1.databases_dir)}` : "") + `</div>`;
        const opens = n1.open_databases || [];
        const files = n1.s3db_files || [];
        if (files.length || opens.length) {
          html += `<div class="meta" style="margin-left:8px">Contest/system .s3db: ` +
            esc(files.join(", ") || "—") +
            (opens.length ? ` · likely open: ${esc(opens.join(", "))}` : "") + `</div>`;
        }
        for (const row of (n1.s3db || []).filter(x => x.kind === "contest" || x.likely_open)) {
          html += `<div class="meta" style="margin-left:8px">` +
            `<code>${esc(row.name)}</code> ${esc(row.kind || "")}` +
            (row.likely_open ? " · open(WAL)" : "") +
            (row.path ? ` · ${esc(row.path)}` : "") + `</div>`;
        }
        for (const iss of (n1.issues || [])) {
          const cls = iss.severity === "error" ? "DEAD" : (iss.severity === "warn" ? "STALE" : "meta");
          html += `<div class="${cls}" style="margin-left:8px">[${esc(iss.severity)}] ${esc(iss.message)}</div>`;
        }
        for (const ini of (n1.ini_files || []).slice(0, 2)) {
          const hints = (ini.hints || []).filter(h =>
            /broadcast|wsjt|udp|external/i.test(h)).slice(0, 8);
          if (hints.length) {
            html += `<div class="meta" style="margin-left:8px;margin-top:4px">ini ${esc(ini.path || "")}: ` +
              esc(hints.join(" · ")) + `</div>`;
          }
        }
        html += `</div>`;
      }
      setup.innerHTML = html;
    }
  }
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

function formatResync(rs) {
  if (!rs) return null;
  const when = rs.age == null ? "" : ` · ${age(rs.age)} ago`;
  const up = rs.upserted != null ? `+${rs.upserted}` : "";
  const del = rs.deleted != null ? `−${rs.deleted}` : "";
  const delta = [up, del].filter(Boolean).join(" / ");
  const total = rs.total != null ? ` → ${rs.total} QSOs` : "";
  const src = rs.source ? ` · ${rs.source}` : "";
  return `${delta}${total}${src}${when}`;
}

function renderSync(n) {
  if (!n) return;
  if ($("n1mm-sync")) {
    const label = {active:"active", idle:"quiet · N1MM has no heartbeat",
                   none:"none heard yet (broadcast not enabled?)"}[n.status];
    const feed = n.feed_age == null ? "none seen" : `${age(n.feed_age)} ago`;
    const lq = n.last_qso ? `${n.last_qso.call} ${n.last_qso.band} (${age(n.last_qso.age)} ago)` : "—";
    const seed = n.seed ? ` ✓ seeded from ${esc(n.seed.source)}` : "";
    const rsTxt = formatResync(n.last_resync);
    const resync = rsTxt
      ? `<span><span class="k">last resync:</span>${esc(rsTxt)}</span>`
      : `<span><span class="k">last resync:</span>— <a href="/setup">Setup → Resync log</a></span>`;
    $("n1mm-sync").innerHTML =
      `<span><span class="dot ${n.status}"></span><span class="k">live feed:</span><b>${label}</b></span>` +
      `<span><span class="k">last packet:</span>${feed}</span>` +
      `<span><span class="k">packets:</span>${n.packets}</span>` +
      `<span><span class="k">log copy:</span><b>${n.qso_count}</b> QSO${n.qso_count===1?'':'s'}${seed}</span>` +
      `<span><span class="k">last logged:</span>${lq}</span>` +
      resync;
  }
  // Status: one-line pointer to Setup for contest selection (not the full picker).
  const line = $("status-contest-line");
  if (line) {
    const ac = n.active_contest;
    if (ac && (ac.label || ac.contest_name)) {
      line.innerHTML = `Contest log: <b>${esc(ac.label || ac.contest_name)}</b> · `
        + `${n.qso_count||0} QSOs in WIMS · change / resync under <a href="/setup">Setup</a>`;
    } else {
      line.innerHTML = `Contest log: <b>none loaded</b> — dupe/mult will be wrong until you `
        + `pick a log under <a href="/setup">Setup</a>`;
    }
  }
  renderContests(n);
  renderSetupExtras(n, /*fullState*/ null);
}

// Contest picker is ephemeral: only open after Rescan, closed on select/cancel.
// Do not paint the full catalog on every SSE tick.
let contestPickerOpen = false;
let contestPickerList = [];
let contestPickerActive = null;   // active contest at last render (for "loaded" badge)

function hideContestPicker() {
  contestPickerOpen = false;
  contestPickerList = [];
  const picker = $("contest-picker");
  if (picker) picker.style.display = "none";
  const body = $("contest-body");
  if (body) body.innerHTML = "";
  const empty = $("contest-empty");
  if (empty) empty.style.display = "none";
}

function fillContestPicker(list, active) {
  const body = $("contest-body");
  const empty = $("contest-empty");
  const picker = $("contest-picker");
  if (!body || !picker) return;
  contestPickerOpen = true;
  contestPickerList = list || [];
  contestPickerActive = active || null;
  picker.style.display = "block";
  body.innerHTML = "";
  if (empty) empty.style.display = contestPickerList.length ? "none" : "block";
  if (!contestPickerList.length) return;
  const sorted = [...contestPickerList].sort((a, b) =>
    (b.qso_count - a.qso_count) || (b.recommended ? 1 : 0) - (a.recommended ? 1 : 0));
  for (const c of sorted) {
    const isActive = contestPickerActive && contestPickerActive.db_path === c.db_path &&
      Number(contestPickerActive.contest_nr) === Number(c.contest_nr);
    const tr = document.createElement("tr");
    if (isActive) tr.className = "tx";
    const start = (c.start_date || "").startsWith("1900")
      ? "—" : esc((c.start_date || "").slice(0, 10) || "—");
    const rec = c.recommended && !isActive ? ' <span class="badge">auto</span>' : "";
    const btn = isActive
      ? "<span class=\"meta\">loaded</span>"
      : `<button type="button" data-db="${esc(c.db_path)}" data-nr="${c.contest_nr}">Use this log</button>`;
    tr.innerHTML =
      `<td>${btn}</td>` +
      `<td>${esc(c.contest_name || "?")}${rec}</td>` +
      `<td>${start}</td>` +
      `<td class="num">${c.qso_count}</td>` +
      `<td class="meta">${esc(c.db_label || "")}</td>`;
    body.appendChild(tr);
  }
  body.querySelectorAll("button[data-nr]").forEach(btn => {
    btn.onclick = () => selectContest(btn.dataset.db, btn.dataset.nr);
  });
}

function renderContests(n) {
  // Setup page only — other pages have no contest-active element.
  const act = $("contest-active");
  if (!act) return;
  const active = n.active_contest;
  if (active && (active.label || active.contest_name)) {
    act.innerHTML =
      `<span><span class="dot active"></span><span class="k">active log:</span>` +
      `<b>${esc(active.label || active.contest_name)}</b></span>` +
      `<span><span class="k">file:</span>${esc(active.db_label || "")}</span>` +
      `<span><span class="k">loaded:</span><b>${n.qso_count||0}</b> QSOs in WIMS</span>`;
  } else {
    act.innerHTML =
      `<span><span class="dot idle"></span><span class="k">active log:</span>` +
      `<b>none</b> — Rescan… to pick a contest (needed for correct dupe/mult)</span>`;
  }
  // Remember active for the ephemeral picker "loaded" badge (picker is not always open).
  const prev = contestPickerActive;
  contestPickerActive = active || null;
  const rline = $("contest-resync-line");
  if (rline) {
    const rsTxt = formatResync(n.last_resync);
    rline.innerHTML = rsTxt
      ? `Last resync: <b>${esc(rsTxt)}</b>`
      : `Last resync: <span class="k">never</span> — use <b>Resync log</b> after copying a fresh N1MM .s3db or if roster greying looks wrong.`;
  }
  // While picker is open, only re-paint if the active log identity changed (avoid
  // clobbering mid-click on every SSE tick). Catalog itself is fixed from Rescan.
  if (contestPickerOpen) {
    const same = prev && contestPickerActive
      && prev.db_path === contestPickerActive.db_path
      && Number(prev.contest_nr) === Number(contestPickerActive.contest_nr);
    const bothNone = !prev && !contestPickerActive;
    if (!same && !bothNone) {
      fillContestPicker(contestPickerList, contestPickerActive);
    }
  }
}

async function selectContest(dbPath, contestNr) {
  const msg = $("contest-msg");
  if (msg) msg.textContent = "loading…";
  try {
    const r = await fetch("/api/contests/select", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({db_path: dbPath, contest_nr: Number(contestNr)}),
    });
    const j = await r.json();
    if (msg) {
      msg.textContent = j.ok
        ? `loaded ${j.seeded} QSOs · ${j.contest && j.contest.label ? j.contest.label : ""}`
        : (j.error || "failed");
    }
    if (j.ok) hideContestPicker();
  } catch (e) {
    if (msg) msg.textContent = String(e);
  }
}

function wireContestToolbar() {
  const scan = $("contest-rescan");
  if (scan && !scan._wired) {
    scan._wired = true;
    scan.onclick = async () => {
      const msg = $("contest-msg");
      if (msg) msg.textContent = "scanning…";
      try {
        const r = await fetch("/api/contests/rescan", {method: "POST", body: "{}"});
        const j = await r.json();
        if (!j.ok) {
          if (msg) msg.textContent = j.error || "fail";
          return;
        }
        const list = j.contests || [];
        // Prefer active from live SSE cache if present; picker works without it.
        fillContestPicker(list, contestPickerActive);
        if (msg) {
          msg.textContent = list.length
            ? `${list.length} contest(s) — select one or Cancel`
            : "no contests found";
        }
      } catch (e) {
        if (msg) msg.textContent = String(e);
      }
    };
  }
  const cancel = $("contest-cancel");
  if (cancel && !cancel._wired) {
    cancel._wired = true;
    cancel.onclick = () => {
      hideContestPicker();
      const msg = $("contest-msg");
      if (msg) msg.textContent = "cancelled";
    };
  }
  const sync = $("contest-resync");
  if (sync && !sync._wired) {
    sync._wired = true;
    sync.onclick = async () => {
      const msg = $("contest-msg");
      if (msg) msg.textContent = "resyncing from N1MM file…";
      sync.disabled = true;
      try {
        const r = await fetch("/api/log/resync", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: "{}",
        });
        const j = await r.json();
        if (msg) {
          if (j.ok && j.summary) {
            const s = j.summary;
            msg.textContent =
              `resync +${s.upserted} / −${s.deleted} → ${s.total} QSOs`
              + (s.source ? ` · ${s.source}` : "");
          } else {
            msg.textContent = j.hint || j.error || "resync failed";
          }
        }
      } catch (e) {
        if (msg) msg.textContent = String(e);
      } finally {
        sync.disabled = false;
      }
    };
  }
}
wireContestToolbar();

/** Setup-only live hints (no-op on other pages). */
function renderSetupExtras(n1mm, s) {
  const net = $("setup-net-live");
  if (net && s) {
    const inst = s.instances || [];
    const logs = s.loggers || [];
    const hosts = [...new Set(inst.map(i => i.host).filter(Boolean))];
    net.innerHTML =
      `<span><span class="k">WSJT-X ids on wire:</span><b>${inst.length}</b></span>` +
      `<span><span class="k">source hosts:</span>${hosts.length ? hosts.map(esc).join(", ") : "—"}</span>` +
      `<span><span class="k">N1MM stations heard:</span><b>${logs.length}</b>` +
      (logs.length ? ` (${logs.map(l => esc(l.id)).join(", ")})` : "") + `</span>` +
      `<span><span class="k">rx:</span>${s.rx.wsjtx} WSJT-X / ${s.rx.n1mm} N1MM</span>`;
  }
  const fleet = $("setup-fleet-hint");
  if (fleet && s) {
    const inst = s.instances || [];
    const byHost = {};
    for (const n of inst) {
      const h = n.host || "?";
      byHost[h] = byHost[h] || [];
      byHost[h].push(n.id);
    }
    const parts = Object.keys(byHost).sort().map(h =>
      `<span><span class="k">${esc(h)}:</span>${byHost[h].map(esc).join(", ")}</span>`);
    fleet.innerHTML = parts.length
      ? parts.join("")
      : `<span class="k">No WSJT-X hosts seen yet — start instances with LAN multicast (see checklist).</span>`;
  }
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

// GridTracker-style call roster: one row per station heard, with the score kept as a
// column. Rows filter by need (from the N1MM log copy) and band; every header sorts,
// and the chosen sort/filter persist across live SSE re-renders (state below).
const utc = (ts) => new Date(ts*1000).toISOString().substr(11, 8);
const ROS_COLS = [
  {key:"call",          label:"DX",      cls:"",          cell:rosCall},
  {key:"to_call",       label:"Calling", cls:"",          cell:c=>rosCalling(c)},
  {key:"band",          label:"Band",    cls:"",          cell:c=>c.band||"-"},
  {key:"mode",          label:"Mode",    cls:"",          cell:c=>c.mode||"-"},
  {key:"grid",          label:"Grid",    cls:"",          cell:c=>c.grid||"-"},
  {key:"snr",           label:"dB",      cls:"num", num:1, cell:c=>sgn(c.snr)},
  {key:"freq_hz",       label:"Freq",    cls:"num", num:1, cell:c=>c.freq_hz?(c.freq_hz/1e6).toFixed(4):"-"},
  {key:"az",            label:"Az",      cls:"num", num:1, cell:c=>c.az==null?"-":c.az+"°"},
  {key:"age",           label:"Age",     cls:"num", num:1, cell:c=>age(c.age)},
  {key:"ts",            label:"UTC",     cls:"num", num:1, cell:c=>utc(c.ts)},
  {key:"operator_call", label:"Op",      cls:"",          cell:c=>c.operator_call||"—"},
  {key:"score",         label:"Score",   cls:"num score", num:1, cell:c=>c.score.toFixed(1)},
];
let _rosData = null;                              // latest roster payload
let _rosSort = {key:"score", dir:-1};             // default: score, descending
let _rosWired = false;

function rosCall(c) {
  const badges =
    (c.is_new_mult ? '<span class="badge">mult</span>' : '') +
    (c.is_rover ? '<span class="badge rover">R</span>' : '');
  return `${esc(c.call)}${badges}`;
}
function rosCalling(c) {
  return c.is_cq ? '<span class="cq">CQ</span>' : esc(c.to_call || "-");
}

function rosBuildHead() {
  const head = $("ros-head");
  head.innerHTML = ROS_COLS.map(col => {
    const active = col.key === _rosSort.key;
    const arrow = active ? (_rosSort.dir < 0 ? " ▾" : " ▴") : "";
    return `<th data-key="${col.key}" class="${col.cls}${active?' sort':''}">${col.label}${arrow}</th>`;
  }).join("");
}

function rosWire() {
  if (_rosWired) return;
  _rosWired = true;
  $("ros-head").addEventListener("click", (e) => {
    const th = e.target.closest("th"); if (!th) return;
    const key = th.dataset.key;
    if (_rosSort.key === key) _rosSort.dir *= -1;
    else _rosSort = {key, dir: (ROS_COLS.find(c=>c.key===key)||{}).num ? -1 : 1};
    rosDraw();
  });
  $("ros-needed").addEventListener("change", rosDraw);
  $("ros-band").addEventListener("change", rosDraw);
}

function renderRoster(r) {
  if (!r || !$("ros-body")) return;
  _rosData = r;
  rosWire();
  rosDraw();
}

function rosDraw() {
  const r = _rosData; if (!r) return;
  // Band filter options, preserving the current selection.
  const sel = $("ros-band"), cur = sel.value;
  const bands = [...new Set(r.candidates.map(c => c.band).filter(Boolean))].sort();
  sel.innerHTML = '<option value="all">all</option>' +
    bands.map(b => `<option value="${b}">${b}</option>`).join("");
  sel.value = bands.includes(cur) || cur === "all" ? cur : "all";

  const neededOnly = $("ros-needed").checked;
  let rows = r.candidates.filter(c =>
    (!neededOnly || c.is_needed) && (sel.value === "all" || c.band === sel.value));

  const col = ROS_COLS.find(c => c.key === _rosSort.key) || ROS_COLS[0];
  const val = (c) => {
    const v = c[col.key];
    if (col.num) return v == null ? -Infinity : v;
    return (v || "").toString().toUpperCase();
  };
  rows.sort((a, b) => {
    const x = val(a), y = val(b);
    return (x < y ? -1 : x > y ? 1 : 0) * _rosSort.dir;
  });

  rosBuildHead();
  $("ros-meta").textContent =
    `${r.needed} needed · ${r.not_needed} worked · ${r.count} heard` +
    ` · showing ${rows.length} · strategy ${r.strategy} · band ${r.condition}`;
  const body = $("ros-body"); body.innerHTML = "";
  $("ros-empty").style.display = rows.length ? "none" : "block";
  for (const c of rows) {
    const tr = document.createElement("tr");
    tr.className = (c.is_new_mult ? "mult " : "") + (c.is_needed ? "" : "dupe");
    tr.innerHTML = ROS_COLS.map(col =>
      `<td class="${col.cls}">${col.cell(c)}</td>`).join("");
    body.appendChild(tr);
  }
}

// -- dispatch + connect ----------------------------------------------------- //

function render(s) {
  renderHeader(s);
  renderSystem(s);
  renderAgents(s);
  renderInterlock(s.interlock);
  renderRoster(s.roster);
  renderInstances(s);
  renderActivity(s.activity);
  renderDecodes(s.decodes);
  renderSync(s.n1mm_sync);
  renderLoggers(s);
  renderSetupExtras(s.n1mm_sync, s);
}

function connect() {
  const es = new EventSource("/events");
  es.onopen = () => { $("conn").textContent = "● live"; $("conn").className = "up"; };
  es.onmessage = (e) => render(JSON.parse(e.data));
  es.onerror = () => { $("conn").textContent = "● disconnected"; $("conn").className = "down"; };
}
connect();
