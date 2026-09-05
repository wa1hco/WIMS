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
//   Status   — overview / WSJT / N1MM (N1MM owns contest log pick/resync)
//   Setup    — install diagnostics: networking checklist, host app configs

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
  const bands = s.bands || [];
  const nInter = bands.filter(b => b.share_policy === "interlock").length;
  const nCoord = bands.filter(b => b.share_policy === "coordinated").length;
  el.innerHTML =
    `<span><span class="dot active"></span><b>WIMS server</b> · live</span>` +
    `<span><span class="k">WSJT-X:</span>${inst.length} (` +
      `<span class="ALIVE">${by("ALIVE")} alive</span>` +
      (by("STALE") ? ` · <span class="STALE">${by("STALE")} stale</span>` : ``) +
      (by("DEAD")  ? ` · <span class="DEAD">${by("DEAD")} dead</span>`   : ``) +
      (quiet ? ` · <span class="quiet">${quiet} quiet</span>` : ``) + `)</span>` +
    `<span><span class="k">transmitting:</span>${tx}</span>` +
    `<span><span class="k">bands:</span>${bands.length}` +
      (nInter || nCoord
        ? ` (<span class="policy-interlock">${nInter} interlock</span>` +
          ` · <span class="policy-coordinated">${nCoord} coordinated</span>)`
        : ``) + `</span>` +
    `<span><span class="k">N1MM loggers:</span>${(s.loggers||[]).length}</span>` +
    `<span><span class="k">seat agents:</span>${agents.length}` +
      (aErr ? ` · <span class="warn">${aErr} error</span>` : ``) + `</span>` +
    `<span><span class="k">rx:</span>${s.rx.wsjtx} WSJT-X / ${s.rx.n1mm} N1MM pkts</span>`;
}

function policyBadge(pol) {
  const p = (pol || "coordinated").toLowerCase();
  const cls = p === "interlock" ? "policy-interlock" : "policy-coordinated";
  const title = p === "interlock"
    ? "SSB/CW KEY inhibit when configured — automatic priority"
    : "Manual handoff — WIMS informs operators, does not inhibit";
  return `<span class="pill ${cls}" title="${title}">${esc(p)}</span>`;
}

function renderBandInventory(s) {
  const body = $("band-inv-body");
  if (!body) return;
  const bands = s.bands || [];
  const empty = $("band-inv-empty");
  if (empty) empty.style.display = bands.length ? "none" : "block";
  body.innerHTML = "";
  for (const b of bands) {
    const tr = document.createElement("tr");
    if ((b.wsjt_tx || []).length) tr.className = "tx";
    const ids = (b.wsjt || []).map(w => {
      const nl = w.n1mm_logger;
      if (nl && nl.id) return `${w.id}→${nl.id}`;
      return w.id;
    }).filter(Boolean).join(", ") || "—";
    const tx = (b.wsjt_tx || []).length ? esc((b.wsjt_tx || []).join(", ")) : "—";
    const logs = (b.loggers || []).map(l => {
      const mc = l.mycall ? ` (${l.mycall})` : "";
      const h = l.host ? `@${l.host}` : "";
      return `${l.id || "?"}${h}${mc}`;
    }).join(", ") || "—";
    tr.innerHTML =
      `<td><b>${esc(b.band)}</b></td>` +
      `<td>${policyBadge(b.share_policy)}</td>` +
      `<td class="num">${b.wsjt_count ?? (b.wsjt || []).length}</td>` +
      `<td style="white-space:normal;max-width:280px">${esc(ids)}</td>` +
      `<td class="${(b.wsjt_tx || []).length ? "state-TX" : ""}">${tx}</td>` +
      `<td class="num">${b.logger_count ?? (b.loggers || []).length}</td>` +
      `<td style="white-space:normal;max-width:240px">${esc(logs)}</td>` +
      `<td class="num">${b.ssb_count ?? 0}</td>`;
    body.appendChild(tr);
  }
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

function n1mmLoggerCell(nl) {
  if (!nl || nl.status === "missing" || !nl.id) {
    const tip = (nl && nl.detail) ? nl.detail : "No N1MM broadcast matched this band";
    return `<span class="warn" title="${esc(tip)}">⚠ none</span>`;
  }
  const addr = nl.host || (nl.hosts && nl.hosts[0]) || "?";
  const call = nl.mycall ? ` · ${nl.mycall}` : "";
  const label = `${nl.id} @ ${addr}${call}`;
  if (nl.status === "multiple") {
    return `<span class="warn" title="${esc(nl.detail || "multiple N1MM on band")}">⚠ ${esc(label)}</span>`;
  }
  if (nl.status === "colocated") {
    return `<span class="STALE" title="${esc(nl.detail || "same host; band not confirmed")}">${esc(label)} <span class="meta">· host</span></span>`;
  }
  return `<span class="ALIVE" title="Logger-of-record for this band">${esc(label)}</span>`;
}

function renderInstances(s) {
  const ib = $("inst-body");
  if (!ib) return;
  ib.innerHTML = "";
  $("inst-empty").style.display = s.instances.length ? "none" : "block";
  for (const n of s.instances) {
    const tr = document.createElement("tr");
    if (n.transmitting) tr.className = "tx";
    if (n.id_collision) tr.className = (tr.className ? tr.className + " " : "") + "id-collide";
    const health = n.health + (n.quiet ? " · QUIET" : "");
    // Same UDP id on 2 PCs (default "WSJT-X") → one row; show ALL hosts.
    const hosts = (n.hosts && n.hosts.length) ? n.hosts : (n.host ? [n.host] : []);
    const hostCell = n.id_collision
      ? `<span class="warn">⚠ shared id</span> ${esc(hosts.join(" · "))}`
      : esc(hosts.join(", ") || n.host || "-");
    const collide = n.id_collision
      ? ' <span class="warn" title="Two PCs use the same WSJT-X name — set unique --rig-name on each">⚠ rename</span>'
      : "";
    tr.innerHTML =
      `<td>${esc(n.id)}${collide}</td><td>${hostCell}</td><td>${esc(n.band||"-")}</td>` +
      `<td style="white-space:normal;max-width:260px">${n1mmLoggerCell(n.n1mm_logger)}</td>` +
      `<td>${policyBadge(n.share_policy)}</td>` +
      `<td>${esc(n.mode||"-")}</td><td class="num">${mhz(n.dial_hz)}</td>` +
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
  const net = s.n1mm_network || {};
  const loggers = s.loggers || [];
  lb.innerHTML = "";
  const empty = $("log-empty");
  if (empty) empty.style.display = loggers.length ? "none" : "block";

  const sum = $("n1mm-net-summary");
  if (sum) {
    if (!loggers.length) {
      sum.innerHTML = `<span class="k">No N1MM on network yet</span>`;
    } else {
      const withW = net.with_wsjt != null ? net.with_wsjt
        : loggers.filter(l => l.has_wsjt).length;
      const without = net.without_wsjt != null ? net.without_wsjt
        : loggers.filter(l => !l.has_wsjt).length;
      const unbound = (net.unbound_wsjt || []).length;
      sum.innerHTML =
        `<span><span class="k">N1MM stations:</span><b>${loggers.length}</b></span>` +
        `<span><span class="k">with WSJT logging:</span><span class="ALIVE">${withW}</span></span>` +
        `<span><span class="k">no WSJT:</span>${without ? `<span class="STALE">${without}</span>` : "0"}</span>` +
        (unbound
          ? `<span><span class="k">WSJT unbound:</span><span class="warn">${unbound}</span></span>`
          : ``);
    }
  }

  for (const l of loggers) {
    const tr = document.createElement("tr");
    if (!l.has_wsjt) tr.className = "n1mm-no-wsjt";
    const fresh = l.last_seen_age != null && l.last_seen_age < 60;
    const seen = l.last_seen_age == null ? "-" : age(l.last_seen_age) + " ago";
    const lastq = l.last_qso_age == null ? "—"
      : `${l.last_call||""} ${l.last_band||""} (${age(l.last_qso_age)} ago)`;
    const alias = (l.aliases && l.aliases.length)
      ? ` <span class="meta">aka ${esc(l.aliases.join(", "))}</span>` : "";
    const bands = (l.bands && l.bands.length)
      ? l.bands.join(", ")
      : ((l.bands_seen && l.bands_seen.length) ? l.bands_seen.join(", ")
        : (l.last_band || "—"));
    const role = l.role === "digital_logger"
      ? `<span class="ALIVE">digital</span>`
      : `<span class="STALE" title="No WSJT-X bound to this N1MM — SSB/CW only or reader not set">no WSJT</span>`;
    const wsjtList = (l.wsjt_instances || []);
    let wsjtCell;
    if (!wsjtList.length) {
      wsjtCell = `<span class="meta">— none</span>`;
    } else {
      wsjtCell = wsjtList.map(w => {
        const b = w.band ? ` <span class="meta">(${esc(w.band)})</span>` : "";
        const h = w.host ? ` @${esc(w.host)}` : "";
        const st = w.health === "ALIVE" ? "ALIVE" : (w.health || "");
        return `<span class="${st}">${esc(w.id || "?")}</span>${b}${h}`;
      }).join("<br>");
    }
    tr.innerHTML =
      `<td><span class="dot ${fresh?'active':'idle'}"></span>${esc(l.kind)} · <b>${esc(l.id)}</b>${alias}</td>` +
      `<td>${esc(l.host||"-")}</td><td>${esc(l.mycall||"-")}</td>` +
      `<td>${role}</td>` +
      `<td style="white-space:normal;max-width:120px">${esc(bands)}</td>` +
      `<td style="white-space:normal;max-width:320px">${wsjtCell}</td>` +
      `<td class="num">${l.wsjt_count ?? wsjtList.length}</td>` +
      `<td>${seen}</td><td class="num">${l.qso_count}</td>` +
      `<td>${esc(lastq)}</td>`;
    lb.appendChild(tr);
  }

  const wrap = $("n1mm-unbound-wrap");
  const ub = $("n1mm-unbound");
  const unbound = net.unbound_wsjt || [];
  if (wrap && ub) {
    if (!unbound.length) {
      wrap.style.display = "none";
      ub.innerHTML = "";
    } else {
      wrap.style.display = "block";
      ub.innerHTML = unbound.map(w =>
        `<span class="warn">${esc(w.id || "?")}</span>` +
        (w.band ? ` <span class="meta">(${esc(w.band)})</span>` : "") +
        (w.host ? ` @${esc(w.host)}` : "")
      ).join(" · ");
    }
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
  _dlogData = list || [];
  dlogDraw();
}

let _dlogData = [];

function dlogDraw() {
  const body = $("dlog-body");
  if (!body) return;
  const list = _dlogData || [];
  const opsCols = !!$("ros-bands");
  const allowed = opsCols ? rosSelectedBands() : null;
  const rows = list.filter(e => {
    if (!allowed) return true;
    // Keep unknown-band lines so operators still see traffic while Status catches up.
    if (!e.band || e.band === "?") return true;
    return allowed.has(e.band);
  });
  const empty = $("dlog-empty");
  if (empty) empty.style.display = rows.length ? "none" : "block";
  body.innerHTML = "";
  for (const e of rows) {
    const tr = document.createElement("tr");
    if (e.is_cq) tr.className = "cqrow";
    if (opsCols) {
      tr.innerHTML =
        `<td>${new Date(e.ts*1000).toLocaleTimeString()}</td>` +
        `<td title="WSJT-X --rig-name / UDP id">${esc(e.instance || "—")}</td>` +
        `<td>${esc(e.band || "—")}</td>` +
        `<td class="num">${sgn(e.snr)}</td><td class="num">${e.df}</td>` +
        `<td>${esc(e.message)}</td>`;
    } else {
      tr.innerHTML =
        `<td>${new Date(e.ts*1000).toLocaleTimeString()}</td>` +
        `<td title="WSJT-X --rig-name / UDP id">${esc(e.instance || "—")}</td>` +
        `<td class="num">${sgn(e.snr)}</td><td class="num">${e.df}</td>` +
        `<td>${esc(e.message)}</td>`;
    }
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
      : `<span><span class="k">last resync:</span>— use <b>Resync log</b> above</span>`;
    $("n1mm-sync").innerHTML =
      `<span><span class="dot ${n.status}"></span><span class="k">live feed:</span><b>${label}</b></span>` +
      `<span><span class="k">last packet:</span>${feed}</span>` +
      `<span><span class="k">packets:</span>${n.packets}</span>` +
      `<span><span class="k">log copy:</span><b>${n.qso_count}</b> QSO${n.qso_count===1?'':'s'}${seed}</span>` +
      `<span><span class="k">last logged:</span>${lq}</span>` +
      resync;
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

function fillContestPicker(list, active, scanDirs) {
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
  const scanEl = $("contest-scan-dirs");
  if (scanEl) {
    const dirs = scanDirs || [];
    scanEl.innerHTML = dirs.length
      ? `Scanned: <code>${dirs.map(esc).join("</code>; <code>")}</code>`
      : "Scanned: <i>no Databases folders found on this host</i>";
  }
  const hint = $("seed-dir-hint");
  if (hint && scanDirs && scanDirs.length) {
    hint.textContent = scanDirs.join(" · ");
  }
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
  // N1MM tab — other pages have no contest-active element.
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
      fillContestPicker(contestPickerList, contestPickerActive,
                        (n && n.scan_dirs) || []);
    }
  }
  const hint = $("seed-dir-hint");
  if (hint && n && n.scan_dirs && n.scan_dirs.length) {
    hint.textContent = n.scan_dirs.join(" · ");
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
        fillContestPicker(list, contestPickerActive, j.scan_dirs || []);
        if (msg) {
          msg.textContent = list.length
            ? `${list.length} contest(s) — select one or Cancel`
            : "no contests found (see scanned dirs below)";
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
  const hint = $("seed-dir-hint");
  if (hint && n1mm && n1mm.scan_dirs && n1mm.scan_dirs.length) {
    hint.textContent = n1mm.scan_dirs.join(" · ");
  }
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
// column. Rows filter by need (from the N1MM log copy) and band checkboxes; every
// header sorts. Click the *line* to Work (no Work button). Columns are selectable
// (localStorage) so the table can stay narrow on small screens.
const ROS_COLS = [
  {key:"call",          label:"DX",      cls:"",          locked:1, cell:rosCall},
  {key:"to_call",       label:"Calling", cls:"",          cell:c=>rosCalling(c)},
  {key:"band",          label:"Band",    cls:"",          cell:c=>c.band||"-"},
  {key:"instance",      label:"Source",  cls:"",          cell:rosSource},
  {key:"mode",          label:"Mode",    cls:"",          cell:c=>c.mode||"-"},
  {key:"grid",          label:"Grid",    cls:"",          cell:c=>c.grid||"-"},
  {key:"snr",           label:"dB",      cls:"num", num:1, cell:c=>sgn(c.snr)},
  {key:"freq_hz",       label:"Freq",    cls:"num", num:1, cell:c=>c.freq_hz?(c.freq_hz/1e6).toFixed(4):"-"},
  {key:"az",            label:"Az DX",   cls:"num", num:1, cell:rosAzDx},
  {key:"az_ant",        label:"Az ant",  cls:"num", num:1, cell:rosAzAnt},
  {key:"delta_az",      label:"Δaz",     cls:"num", num:1, cell:c=>c.delta_az==null?"-":c.delta_az+"°"},
  {key:"distance_km",   label:"km",      cls:"num", num:1, cell:c=>c.distance_km==null?"-":c.distance_km},
  {key:"age",           label:"Age",     cls:"num", num:1, cell:c=>age(c.age)},
  {key:"score",         label:"Score",   cls:"num score", num:1, cell:c=>c.score.toFixed(1)},
];
// Compact default: hide Source/Mode/Freq/Az ant/Δaz/km until the operator enables them.
const ROS_COLS_DEFAULT = [
  "call", "to_call", "band", "grid", "snr", "az", "age", "score",
];
let _rosData = null;                              // latest roster payload
let _rosSort = {key:"score", dir:-1};             // default: score, descending
let _rosWired = false;
const ROS_BANDS_KEY = "wims.ops.bands";
const ROS_COLS_KEY = "wims.ops.cols";
const ROS_AGE_KEY = "wims.ops.maxAgeSec";
const ROS_AGE_DEFAULT = 120; // match GridTracker-ish “last ~2 minutes” feel
let _rosColsBuilt = false;

function rosCall(c) {
  const badges =
    (c.is_calling_us ? '<span class="badge callus">us</span>' : '') +
    (c.is_armed ? '<span class="badge armed">TX</span>' : '') +
    (c.is_new_mult ? '<span class="badge">mult</span>' : '') +
    (c.is_rover ? '<span class="badge rover">R</span>' : '');
  return `${esc(c.call)}${badges}`;
}
function rosCalling(c) {
  if (c.is_cq) return '<span class="cq">CQ</span>';
  const t = c.to_call || "";
  if (c.is_qsy || /^QSY\b/i.test(t) || /^(NOQSY|TNX|SRI|AGN)$/i.test(t)) {
    return `<span class="qsy" title="WSJT-X Message System / QSY">${esc(t || "QSY")}</span>`;
  }
  return esc(t || "-");
}
/** Short Source label: rig-name only (drop redundant "WSJT-X - " prefix). */
function rosSourceLabel(raw) {
  const t = (raw || "").trim();
  if (!t) return "—";
  const bare = t.replace(/^wsjt-?x\s*[-–—:]\s*/i, "").trim();
  if (!bare || /^wsjt-?x$/i.test(bare)) return "default";
  return bare;
}
function rosSource(c) {
  const raw = c.instance || "";
  const short = rosSourceLabel(raw);
  if (!raw || short === raw) return esc(short);
  return `<span title="${esc(raw)}">${esc(short)}</span>`;
}
function rosAzDx(c) {
  // Clickable when a rotator is mapped — point antenna to this Az DX.
  if (c.az == null) return "-";
  if (c.rotator_id) {
    return `<button type="button" class="azbtn" data-point-row="${esc(c.id||"")}" ` +
           `title="Point ${esc(c.rotator_id)} to ${c.az}°">${c.az}°</button>`;
  }
  return c.az + "°";
}
function rosAzAnt(c) {
  if (c.az_ant == null) return "—";
  const cls = c.rotator_moving ? "az-moving" : "";
  return `<span class="${cls}" title="${c.rotator_moving ? "slewing…" : "settled"}">${c.az_ant}°</span>`;
}

function rosLoadColPref() {
  try {
    const raw = localStorage.getItem(ROS_COLS_KEY);
    if (!raw) return null;
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr : null;
  } catch (_) { return null; }
}

function rosSaveColPref(keys) {
  try { localStorage.setItem(ROS_COLS_KEY, JSON.stringify([...keys])); }
  catch (_) {}
}

function rosVisibleCols() {
  const wrap = $("ros-cols");
  if (!wrap) return ROS_COLS; // no column UI → show all
  const boxes = [...wrap.querySelectorAll('input[type="checkbox"][data-col]')];
  if (!boxes.length) {
    const pref = rosLoadColPref();
    const want = new Set(pref && pref.length ? pref : ROS_COLS_DEFAULT);
    want.add("call");
    return ROS_COLS.filter(c => want.has(c.key));
  }
  const on = new Set(boxes.filter(b => b.checked).map(b => b.dataset.col));
  on.add("call");
  return ROS_COLS.filter(c => on.has(c.key));
}

function rosSyncColChecks() {
  const wrap = $("ros-cols");
  if (!wrap || _rosColsBuilt) return;
  _rosColsBuilt = true;
  const pref = rosLoadColPref();
  const want = new Set(pref && pref.length ? pref : ROS_COLS_DEFAULT);
  want.add("call");
  wrap.innerHTML = "";
  for (const col of ROS_COLS) {
    const lab = document.createElement("label");
    lab.className = "col-check";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.dataset.col = col.key;
    cb.checked = want.has(col.key);
    if (col.locked) {
      cb.checked = true;
      cb.disabled = true;
      lab.title = "DX is always shown";
    }
    cb.addEventListener("change", () => {
      const keys = [...wrap.querySelectorAll('input[data-col]')]
        .filter(b => b.checked).map(b => b.dataset.col);
      if (!keys.includes("call")) keys.unshift("call");
      rosSaveColPref(keys);
      rosDraw();
    });
    lab.appendChild(cb);
    lab.appendChild(document.createTextNode(col.label));
    wrap.appendChild(lab);
  }
}

function rosBuildHead() {
  const head = $("ros-head");
  const cols = rosVisibleCols();
  head.innerHTML = cols.map(col => {
    const active = col.key === _rosSort.key;
    const arrow = active ? (_rosSort.dir < 0 ? " ▾" : " ▴") : "";
    return `<th data-key="${col.key}" class="${col.cls}${active?' sort':''}">${col.label}${arrow}</th>`;
  }).join("");
}

/** Measure content and pin each roster column to the narrowest width that still
 *  shows its cells (no wrap). Re-run after data, visible-column, or zoom/resize. */
function rosFitColumns() {
  const table = $("ros");
  const head = $("ros-head");
  const body = $("ros-body");
  if (!table || !head) return;
  const ths = [...head.children];
  const n = ths.length;
  if (!n) return;

  // Natural measure pass: drop prior col widths so scrollWidth reflects content.
  const old = table.querySelector("colgroup.ros-fit");
  if (old) old.remove();
  table.style.width = "max-content";
  table.style.tableLayout = "auto";

  const widths = new Array(n).fill(0);
  for (let i = 0; i < n; i++) {
    widths[i] = Math.ceil(ths[i].getBoundingClientRect().width);
  }
  if (body) {
    for (const tr of body.rows) {
      const cells = tr.cells;
      for (let i = 0; i < n && i < cells.length; i++) {
        widths[i] = Math.max(widths[i], Math.ceil(cells[i].getBoundingClientRect().width));
      }
    }
  }

  const cg = document.createElement("colgroup");
  cg.className = "ros-fit";
  for (const w of widths) {
    const col = document.createElement("col");
    // +1px avoids occasional ellipsis/clip from subpixel rounding after zoom.
    col.style.width = (w + 1) + "px";
    cg.appendChild(col);
  }
  table.insertBefore(cg, table.firstChild);
  table.style.tableLayout = "fixed";
  table.style.width = "max-content";
}

let _rosFitTimer = 0;
function rosFitColumnsSoon() {
  if (_rosFitTimer) clearTimeout(_rosFitTimer);
  _rosFitTimer = setTimeout(() => {
    _rosFitTimer = 0;
    rosFitColumns();
  }, 30);
}

function rosLoadBandPref() {
  try {
    const raw = localStorage.getItem(ROS_BANDS_KEY);
    if (!raw) return null;
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr : null;
  } catch (_) { return null; }
}

function rosSaveBandPref(bands) {
  try { localStorage.setItem(ROS_BANDS_KEY, JSON.stringify([...bands])); }
  catch (_) {}
}

function rosSelectedBands() {
  const wrap = $("ros-bands");
  if (!wrap) return null; // Status / no filter UI → all bands
  const boxes = [...wrap.querySelectorAll('input[type="checkbox"][data-band]')];
  if (!boxes.length) return null;
  const on = boxes.filter(b => b.checked).map(b => b.dataset.band);
  return new Set(on);
}

let _rosBandListKey = "";

function rosSyncBandChecks(bands) {
  const wrap = $("ros-bands");
  if (!wrap) return;
  const key = bands.join("|");
  // Only rebuild when the visible band set changes (SSE ticks must not wipe clicks).
  if (key === _rosBandListKey && wrap.querySelector("input[data-band]")) return;
  const knownBefore = _rosBandListKey ? _rosBandListKey.split("|").filter(Boolean) : [];
  const prev = rosSelectedBands();
  const pref = rosLoadBandPref();
  _rosBandListKey = key;
  wrap.innerHTML = "";
  if (!bands.length) {
    wrap.innerHTML = '<span class="meta">none yet</span>';
    return;
  }
  for (const b of bands) {
    const lab = document.createElement("label");
    lab.className = "band-check";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.dataset.band = b;
    if (window._rosShotBands && window._rosShotBands.size) {
      cb.checked = window._rosShotBands.has(b);
    } else if (prev && knownBefore.length) {
      // Keep prior checks; newly appeared bands default on so they are noticed.
      cb.checked = knownBefore.includes(b) ? prev.has(b) : true;
    } else if (pref && pref.length) {
      cb.checked = pref.includes(b);
    } else {
      cb.checked = true;
    }
    cb.addEventListener("change", () => {
      const sel = rosSelectedBands();
      if (sel) rosSaveBandPref(sel);
      rosDraw();
    });
    lab.appendChild(cb);
    lab.appendChild(document.createTextNode(b));
    wrap.appendChild(lab);
  }
}

function rosLoadMaxAge() {
  try {
    const raw = localStorage.getItem(ROS_AGE_KEY);
    if (raw == null || raw === "") return ROS_AGE_DEFAULT;
    const n = Number(raw);
    return Number.isFinite(n) && n >= 0 ? n : ROS_AGE_DEFAULT;
  } catch (_) { return ROS_AGE_DEFAULT; }
}

function rosSaveMaxAge(sec) {
  try { localStorage.setItem(ROS_AGE_KEY, String(sec)); }
  catch (_) {}
}

function rosMaxAgeSec() {
  const sel = $("ros-max-age");
  if (!sel) return 0; // no control → no client age filter
  const n = Number(sel.value);
  return Number.isFinite(n) && n >= 0 ? n : 0;
}

function rosSyncMaxAgeControl() {
  const sel = $("ros-max-age");
  if (!sel || sel.dataset.wired) return;
  sel.dataset.wired = "1";
  const want = rosLoadMaxAge();
  const opt = [...sel.options].some(o => Number(o.value) === want);
  sel.value = String(opt ? want : ROS_AGE_DEFAULT);
  sel.addEventListener("change", () => {
    rosSaveMaxAge(rosMaxAgeSec());
    rosDraw();
  });
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
  const needed = $("ros-needed");
  if (needed) needed.addEventListener("change", rosDraw);
  rosSyncMaxAgeControl();
  applyOperateShotContext();
  // Ctrl+/- zoom and window resize: remeasure column widths.
  window.addEventListener("resize", rosFitColumnsSoon);
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", rosFitColumnsSoon);
  }
}

/** URL query context for docs screenshots, e.g. /?needed=1&bands=144&maxAge=60 */
function applyOperateShotContext() {
  if (!$("ros-needed") && !$("ros-max-age") && !$("ros-cols")) return;
  let q;
  try { q = new URLSearchParams(location.search || ""); }
  catch (_) { return; }
  if (![...q.keys()].length) return;
  if (q.has("needed")) {
    const needed = $("ros-needed");
    if (needed) needed.checked = !["0", "false", "no"].includes(String(q.get("needed")).toLowerCase());
  }
  if (q.has("maxAge")) {
    const sel = $("ros-max-age");
    const v = String(q.get("maxAge") || "");
    if (sel && [...sel.options].some(o => o.value === v)) {
      sel.value = v;
      rosSaveMaxAge(Number(v));
    }
  }
  if (q.has("cols")) {
    const want = new Set(
      String(q.get("cols") || "").split(",").map(s => s.trim()).filter(Boolean)
    );
    want.add("call");
    if (want.size) {
      rosSaveColPref([...want]);
      _rosColsBuilt = false;
      const wrap = $("ros-cols");
      if (wrap) wrap.innerHTML = "";
      rosSyncColChecks();
    }
  }
  if (q.has("bands")) {
    // Applied on next rosDraw once band checkboxes exist.
    window._rosShotBands = new Set(
      String(q.get("bands") || "").split(",").map(s => s.trim()).filter(Boolean)
    );
  }
}

function renderRoster(r) {
  if (!r || !$("ros-body")) return;
  _rosData = r;
  rosSyncColChecks();
  rosWire();
  rosDraw();
}

function rosDraw() {
  const r = _rosData; if (!r) return;
  rosSyncMaxAgeControl();
  const bands = [...new Set(r.candidates.map(c => c.band).filter(Boolean))].sort();
  rosSyncBandChecks(bands);
  const selected = rosSelectedBands();
  const neededOnly = $("ros-needed") ? $("ros-needed").checked : false;
  const maxAge = rosMaxAgeSec();
  let rows = r.candidates.filter(c => {
    if (neededOnly && !c.is_needed) return false;
    // Unknown band ("?" / empty): keep visible so Decode-only / pre-Status
    // instances are not hidden by the band checks.
    if (selected && c.band && c.band !== "?" && !selected.has(c.band)) return false;
    if (maxAge > 0 && c.age != null && c.age > maxAge) return false;
    return true;
  });

  const vis = rosVisibleCols();
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
  const bandNote = selected
    ? (selected.size === bands.length ? "all bands"
       : selected.size ? [...selected].sort().join(",") : "no bands")
    : "all bands";
  const colNote = vis.length === ROS_COLS.length ? "all cols"
    : `${vis.length}/${ROS_COLS.length} cols`;
  $("ros-meta").textContent =
    `${r.needed} needed · ${r.not_needed} worked · ${r.count} heard` +
    ` · showing ${rows.length} · ${bandNote} · ${colNote}`;
  const body = $("ros-body"); body.innerHTML = "";
  $("ros-empty").style.display = rows.length ? "none" : "block";
  // Drop prior fit widths before painting new cells so measure sees content.
  const table = $("ros");
  const oldFit = table && table.querySelector("colgroup.ros-fit");
  if (oldFit) oldFit.remove();
  if (table) table.style.tableLayout = "auto";
  const canWork = !!( _txState && _txState.can_tx );
  for (const c of rows) {
    const tr = document.createElement("tr");
    // Highlight priority: calling-us (red) > armed (green) > mult (soft green) > dupe dim.
    const classes = [];
    if (c.is_calling_us) classes.push("calling-us");
    else if (c.is_armed) classes.push("armed");
    else if (c.is_new_mult) classes.push("mult");
    if (!c.is_needed) classes.push("dupe");
    if (canWork) classes.push("workable");
    tr.className = classes.join(" ");
    if (c.id) tr.dataset.row = c.id;
    if (canWork) {
      let tip = "Click to work " + (c.call || "") + " via " + (c.instance || "?");
      if (c.is_calling_us) tip = "Calling us — " + tip;
      else if (c.is_armed) tip = "Enable Tx set for this DX — " + tip;
      tr.title = tip;
    }
    tr.innerHTML = vis.map(col =>
      `<td class="${col.cls}">${col.cell(c)}</td>`).join("");
    body.appendChild(tr);
  }
  // After layout: pin each column to content width (numbers, col set, zoom).
  requestAnimationFrame(() => rosFitColumns());
}

// -- TX control (work / halt; no global arm — GT2-style roster click) ------- //

let _txState = null;      // latest tx block; can_tx when controller is wired
let _txWired = false;

async function txPost(url, payload) {
  try {
    const r = await fetch(url, {method: "POST",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
    txFlash(await r.json().catch(() => ({})), url);
  } catch (e) { txFlash({ok: false, error: String(e)}, url); }
}

function txFlash(j, url) {
  const m = $("tx-meta"); if (!m) return;
  if (j.ok) {
    m.className = "meta";
    if (j.sent && String(j.sent).includes("reply")) {
      const dests = j.dests || (j.dest ? [j.dest] : []);
      const dest = dests.length
        ? " → " + dests.map(d => Array.isArray(d) ? `${d[0]}:${d[1]}` : d).join(", ")
        : "";
      const via = j.sent !== "reply" ? ` (${j.sent})` : "";
      m.textContent = `→ Work ${j.call || "?"} on ${j.instance || "?"}${via}${dest}`
        + (j.detail ? ` · ${j.detail}` : "");
    } else if (Array.isArray(j.halted)) {
      m.textContent = `halted ${j.halted.length}`;
    } else {
      m.textContent = "ok";
    }
  } else {
    m.className = "meta warn";
    const err = j.error || "failed";
    const hint = {
      tx_disabled: "Server is --no-tx (read-only)",
      unknown_row: "Row gone — wait for a new decode",
      group_busy: "Another radio holds TX — Halt first",
    }[err];
    m.textContent = `Work failed: ${j.detail || hint || err}`;
  }
}

function txWire() {
  if (_txWired) return;
  _txWired = true;
  const halt = $("tx-halt");
  if (halt) halt.addEventListener("click", () => txPost("/api/tx/halt", {}));
  // Click a roster *line* → Work (GT2-style). No Work button column.
  // Az DX button → point rotator only (does not TX).
  const body = $("ros-body");
  if (body) body.addEventListener("click", (e) => {
    const pointBtn = e.target.closest("button.azbtn[data-point-row]");
    if (pointBtn) {
      e.stopPropagation();
      const rid = pointBtn.dataset.pointRow;
      if (rid) rotPost("/api/rotator/point", {row_id: rid});
      return;
    }
    if (!(_txState && _txState.can_tx)) return;
    if (e.target.closest("a,button,input,select,label")) return;
    const tr = e.target.closest("tr[data-row]");
    if (tr && tr.dataset.row) txPost("/api/tx/work", {row_id: tr.dataset.row});
  });
}

async function rotPost(url, payload) {
  try {
    const r = await fetch(url, {method: "POST",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
    const j = await r.json().catch(() => ({}));
    const m = $("tx-meta");
    if (m) {
      if (j.ok) {
        m.className = "meta";
        m.textContent = j.az != null
          ? `→ Point ${j.rotator || "?"} to ${j.az}°` + (j.detail ? ` (${j.detail})` : "")
          : (j.detail || "rotator ok");
      } else {
        m.className = "meta warn";
        m.textContent = `Point failed: ${j.detail || j.error || "failed"}`;
      }
    }
  } catch (e) {
    const m = $("tx-meta");
    if (m) { m.className = "meta warn"; m.textContent = String(e); }
  }
}

function renderRotators(list) {
  const body = $("rot-body");
  if (!body) return;
  const rows = list || [];
  const empty = $("rot-empty");
  const section = $("rot-section") || $("rot-section-status");
  const onOps = !!$("tx-halt");
  // Hide Rotators until WIMS has seen at least one (Operate + Status overview).
  if (section) {
    section.style.display = rows.length ? "block" : "none";
  } else if (empty) {
    empty.style.display = rows.length ? "none" : "block";
  }
  body.innerHTML = "";
  for (const r of rows) {
    const tr = document.createElement("tr");
    const move = r.moving ? '<span class="az-moving">slewing</span>' : "settled";
    let tail = onOps
      ? `<td class="act"><button type="button" class="txbtn" data-rot-stop="${esc(r.id)}">Stop</button></td>`
      : `<td>${esc(r.source || "—")}</td>`;
    tr.innerHTML =
      `<td>${esc(r.label || r.id)}</td>` +
      `<td class="num">${r.az == null ? "—" : r.az + "°"}</td>` +
      `<td class="num">${r.target_az == null ? "—" : r.target_az + "°"}</td>` +
      `<td>${move}</td>` +
      `<td>${esc(r.health || "?")}</td>` +
      `<td>${esc((r.instances || []).join(", ") || "—")}</td>` +
      tail;
    body.appendChild(tr);
  }
  if (!_rotWired && onOps) {
    _rotWired = true;
    body.addEventListener("click", (e) => {
      const b = e.target.closest("[data-rot-stop]");
      if (b) rotPost("/api/rotator/stop", {rotator_id: b.dataset.rotStop});
    });
  }
}
let _rotWired = false;

function renderTxBar(tx) {
  if (!$("tx-status") && !$("tx-halt")) return;  // not on Operate
  _txState = tx || {enabled: false, can_tx: false};
  txWire();
  const status = $("tx-status"), halt = $("tx-halt");
  if (!_txState.enabled) {
    if (status) {
      status.textContent = "TX OFF (read-only console)";
      status.className = "banner";
    }
    if (halt) halt.disabled = true;
    return;
  }
  if (status) {
    status.textContent = "Click a roster line to Work (answer)";
    status.className = "banner ok";
    if (!status.title) {
      status.title =
        "Work = answer that station (UDP Reply to that row’s WSJT-X). " +
        "Answering a CQ/73 line turns Enable Tx on; a mid-exchange line needs " +
        "Hold Tx Freq in WSJT-X. Red = calling us · green = Enable Tx on that DX · " +
        "click Az DX° to point a rotator when mapped.";
    }
  }
  if (halt) halt.disabled = false;           // panic stop always available
}

// -- dispatch + connect ----------------------------------------------------- //

function render(s) {
  renderHeader(s);
  renderSystem(s);
  renderBandInventory(s);
  renderAgents(s);
  renderTxBar(s.tx);                          // before roster: rosWork() reads can_tx
  renderRotators(s.rotators);
  renderInterlock(s.interlock);
  renderRoster(s.roster);
  renderInstances(s);
  renderActivity(s.activity);
  renderDecodes(s.decodes);                   // no-op unless #dlog-body exists
  renderSync(s.n1mm_sync);
  renderLoggers(s);
  renderSetupExtras(s.n1mm_sync, s);
}

// Status panels selected by top nav path: /overview | /wsjt | /n1mm (/status → overview)
function statusTabFromPath() {
  const p = (location.pathname || "/").replace(/\/$/, "") || "/";
  if (p === "/wsjt") return "wsjt";
  if (p === "/n1mm") return "n1mm";
  if (p === "/overview" || p === "/status") return "overview";
  return null; // not a status page
}

function statusShowTab(name) {
  const allowed = ["overview", "wsjt", "n1mm"];
  if (!allowed.includes(name)) name = "overview";
  // Title per panel
  const titles = {
    overview: "WIMS — Overview",
    wsjt: "WIMS — WSJT-X",
    n1mm: "WIMS — N1MM",
  };
  try { document.title = titles[name] || "WIMS — Status"; } catch (_) {}
  for (const id of allowed) {
    const panel = $("panel-" + id);
    if (!panel) continue;
    const on = id === name;
    panel.classList.toggle("active", on);
    if (on) panel.removeAttribute("hidden");
    else panel.setAttribute("hidden", "");
  }
}

function markNavActive() {
  const nav = document.querySelector("header nav");
  if (!nav) return;
  let p = (location.pathname || "/").replace(/\/$/, "") || "/";
  if (p === "/status") p = "/overview";
  for (const a of nav.querySelectorAll("a")) {
    let href = (a.getAttribute("href") || "").replace(/\/$/, "") || "/";
    a.classList.toggle("active", href === p);
  }
}

function connect() {
  const tab = statusTabFromPath();
  if (tab) statusShowTab(tab);
  markNavActive();
  const es = new EventSource("/events");
  es.onopen = () => { $("conn").textContent = "● live"; $("conn").className = "up"; };
  es.onmessage = (e) => render(JSON.parse(e.data));
  es.onerror = () => { $("conn").textContent = "● disconnected"; $("conn").className = "down"; };
}
connect();
