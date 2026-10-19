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
//   Operate  — roster; TX groups banner only when a group conflicts
//   Status   — overview / WSJT / N1MM (N1MM owns contest log pick/resync)
//   Setup    — install diagnostics: networking checklist, host app configs

const $ = (id) => document.getElementById(id);
const age = (a) => a == null ? "-" : (a < 90 ? a.toFixed(0)+"s" : (a/60).toFixed(0)+"m");
const mhz = (hz) => hz ? (hz/1e6).toFixed(6) : "-";
const esc = (s) => (s||"").replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function escAttr(s) {
  return (s || "").replace(/[&<>"]/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
  }[c]));
}
const sgn = (n) => (n>=0?'+':'')+n;
// Meter bands: 6m → 6M (M = meters). cm unchanged. Not instance ids (ROY-6m).
function fmtBand(b) {
  if (b == null || b === "" || b === "-" || b === "—") return b == null ? "" : b;
  const s = String(b);
  if (/^\d+(\.\d+)?m$/i.test(s)) return s.slice(0, -1) + "M";
  if (/^\d+(\.\d+)?cm$/i.test(s)) return s.replace(/cm$/i, "cm");
  return s;
}
function fmtBands(list, sep) {
  return (list || []).map(fmtBand).filter(Boolean).join(sep == null ? ", " : sep);
}

function renderHeader(s) {
  const ing = s.ingest || {};
  if ($("rx")) {
    let rx = `rx ${s.rx.wsjtx} WSJT-X / ${s.rx.n1mm} N1MM`;
    if (ing.wsjt_age_s != null) rx += ` · last WSJT ${age(ing.wsjt_age_s)}`;
    $("rx").textContent = rx;
  }
  if ($("clock")) $("clock").textContent = new Date(s.now*1000).toLocaleTimeString();
  renderIngestStall(s);
}

function renderIngestStall(s) {
  const el = $("ingest-stall");
  if (!el) return;
  const ing = s.ingest || {};
  if (!ing.stale) {
    el.hidden = true;
    el.textContent = "";
    el.className = "meta";
    return;
  }
  el.hidden = false;
  el.className = "meta warn";
  const a = age(ing.wsjt_age_s);
  el.textContent = `WSJT multicast silent ${a} — rejoining`;
  el.title = `IGMP membership may have dropped. Auto-rejoin ${ing.rejoins || 0}, socket rebind ${ing.rebinds || 0}.`;
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
    `<span><span class="k">rx:</span>${s.rx.wsjtx} WSJT-X / ${s.rx.n1mm} N1MM pkts</span>` +
    (s.ingest && s.ingest.stale
      ? `<span class="warn">WSJT multicast silent ${age(s.ingest.wsjt_age_s)} — rejoining</span>`
      : (s.ingest && s.ingest.wsjt_age_s != null
        ? `<span><span class="k">last WSJT:</span>${age(s.ingest.wsjt_age_s)}</span>`
        : ``));
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
    const liveWsjt = (b.wsjt || []).filter(w => (w.health || "") !== "DEAD");
    const ids = liveWsjt.map(w => w.id).filter(Boolean).join(", ") || "—";
    const tx = (b.wsjt_tx || []).length ? esc((b.wsjt_tx || []).join(", ")) : "—";
    const logs = (b.loggers || []).map(l => {
      const mc = l.mycall ? ` (${l.mycall})` : "";
      const h = l.host ? `@${l.host}` : "";
      return `${l.id || "?"}${h}${mc}`;
    }).join(", ") || "—";
    tr.innerHTML =
      `<td><b>${esc(fmtBand(b.band))}</b></td>` +
      `<td>${policyBadge(b.share_policy)}</td>` +
      `<td class="num">${liveWsjt.length}</td>` +
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
    const txMark = (n.tx_capable === false)
      ? ' <span class="badge" title="seat-profile: decode-only (H2)">decode</span>'
      : (n.rf_path === "trx"
          ? ' <span class="badge armed" title="seat-profile: TX-capable">TX</span>'
          : "");
    tr.innerHTML =
      `<td>${esc(n.id)}${collide}${txMark}</td><td>${hostCell}</td><td>${esc(fmtBand(n.band||"-"))}</td>` +
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
      : `${l.last_call||""} ${fmtBand(l.last_band||"")} (${age(l.last_qso_age)} ago)`;
    const alias = (l.aliases && l.aliases.length)
      ? ` <span class="meta">aka ${esc(l.aliases.join(", "))}</span>` : "";
    const bands = (l.bands && l.bands.length)
      ? fmtBands(l.bands)
      : ((l.bands_seen && l.bands_seen.length) ? fmtBands(l.bands_seen)
        : (fmtBand(l.last_band) || "—"));
    const role = l.role === "digital_logger"
      ? `<span class="ALIVE">digital</span>`
      : `<span class="STALE" title="No WSJT-X bound to this N1MM — SSB/CW only or reader not set">no WSJT</span>`;
    const wsjtList = (l.wsjt_instances || []);
    let wsjtCell;
    if (!wsjtList.length) {
      wsjtCell = `<span class="meta">— none</span>`;
    } else {
      wsjtCell = wsjtList.map(w => {
        const b = w.band ? ` <span class="meta">(${esc(fmtBand(w.band))})</span>` : "";
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
        (w.band ? ` <span class="meta">(${esc(fmtBand(w.band))})</span>` : "") +
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
    if (e.band && e.band !== "?" && allowed.has(e.band)) return true;
    // Unknown-band (no Status dial yet): show only if that instance id is
    // checked. Do not dump '?' Replay floods onto a 2m-only filter.
    if (e.instance && allowed.has(e.instance)) return true;
    return false;
  });
  const empty = $("dlog-empty");
  if (empty) empty.style.display = rows.length ? "none" : "block";
  const showCountry = dlogEnsureCountry();
  body.innerHTML = "";
  for (const e of rows) {
    const tr = document.createElement("tr");
    if (e.is_cq) tr.className = "cqrow";
    const country = showCountry ? dlogCountryCell(e) : "";
    if (opsCols) {
      tr.innerHTML =
        `<td>${new Date(e.ts*1000).toLocaleTimeString()}</td>` +
        `<td title="WSJT-X --rig-name / UDP id">${esc(e.instance || "—")}</td>` +
        `<td>${esc(fmtBand(e.band || "—"))}</td>` +
        `<td class="num">${sgn(e.snr)}</td><td class="num">${e.df}</td>` +
        country +
        `<td>${esc(e.message)}</td>`;
    } else {
      tr.innerHTML =
        `<td>${new Date(e.ts*1000).toLocaleTimeString()}</td>` +
        `<td title="WSJT-X --rig-name / UDP id">${esc(e.instance || "—")}</td>` +
        `<td class="num">${sgn(e.snr)}</td><td class="num">${e.df}</td>` +
        country +
        `<td>${esc(e.message)}</td>`;
    }
    body.appendChild(tr);
  }
}

function dlogCountryCell(e) {
  const name = String(e.country || "").trim();
  if (!name) return "<td></td>";
  const tip = rosCountryTip(e);
  return `<td class="country"><span class="ros-country" title="${escAttr(tip)}">${esc(name)}</span></td>`;
}

function dlogEnsureCountry() {
  const body = $("dlog-body");
  if (!body) return false;
  const table = body.closest("table");
  const head = table && table.querySelector("thead tr");
  if (!head) return false;
  if (!head.querySelector("th[data-col='country']")) {
    const th = document.createElement("th");
    th.dataset.col = "country";
    th.textContent = "Country";
    th.title = "DXCC entity for the station in the message. Blank when the prefix is not known.";
    if (head.lastElementChild) head.insertBefore(th, head.lastElementChild);
    else head.appendChild(th);
  }
  return true;
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
    const lq = n.last_qso ? `${n.last_qso.call} ${fmtBand(n.last_qso.band)} (${age(n.last_qso.age)} ago)` : "—";
    const seed = n.seed ? ` ✓ seeded from ${esc(n.seed.source)}` : "";
    const rsTxt = formatResync(n.last_resync);
    const resyncHint = $("contest-resync")
      ? "use <b>Resync log</b> above"
      : "<b>Resync log</b> is on the Log page";
    const resync = rsTxt
      ? `<span><span class="k">last resync:</span>${esc(rsTxt)}</span>`
      : `<span><span class="k">last resync:</span>— ${resyncHint}</span>`;
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
  if (!n) return;
  const act = $("contest-active");
  const active = n.active_contest;
  if (act && active && (active.label || active.contest_name)) {
    act.innerHTML =
      `<span><span class="dot active"></span><span class="k">active log:</span>` +
      `<b>${esc(active.label || active.contest_name)}</b></span>` +
      `<span><span class="k">file:</span>${esc(active.db_label || "")}</span>` +
      `<span><span class="k">loaded:</span><b>${n.qso_count||0}</b> QSOs in WIMS</span>`;
  } else if (act) {
    act.innerHTML =
      `<span><span class="dot idle"></span><span class="k">active log:</span>` +
      `<b>none</b> — choose a contest on the Log page</span>`;
  }
  // Remember active for the ephemeral picker "loaded" badge (picker is not always open).
  const prev = contestPickerActive;
  contestPickerActive = active || null;
  const rline = $("contest-resync-line");
  if (rline) {
    const rsTxt = formatResync(n.last_resync);
    rline.innerHTML = rsTxt
      ? `Last resync: <b>${esc(rsTxt)}</b>`
      : `Last resync: <span class="k">never</span> — use <b>Resync log</b> after the contest file changes, or if already-worked stations look wrong.`;
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

function wireLogPage() {
  renderLogPageControls();
  const again = $("log-refresh");
  if (again && !again._wired) {
    again._wired = true;
    again.onclick = () => {
      const msg = $("log-refresh-msg");
      if (msg) msg.textContent = "Looking…";
      fetch("/api/rules", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({action: "refresh_logs"}),
      }).then(r => r.json()).then(j => {
        if (msg) msg.textContent = (j && j.ok) ? "Log list updated." : "Could not look again.";
      }).catch(() => {
        if (msg) msg.textContent = "Could not look again.";
      });
    };
  }
}

/** Setup: mark rig-names / N1MM stations that report IF, not RF. */
let _ifSeatsHtml = "";
function escAttr(s) {
  return esc(s).replace(/"/g, "&quot;");
}
function postIfSeat(id, reportsIf) {
  fetch("/api/if-seats", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({id: id, reports_if: !!reportsIf}),
  }).catch(() => {});
}
function wireIfSeatsOnce() {
  const box = $("if-seats");
  if (!box || box.dataset.wired) return;
  box.dataset.wired = "1";
  box.addEventListener("change", (ev) => {
    const el = ev.target;
    if (!el || !el.dataset || !el.dataset.ifId) return;
    postIfSeat(el.dataset.ifId, el.checked);
  });
  box.addEventListener("submit", (ev) => {
    const form = ev.target;
    if (!form || form.id !== "if-seat-add") return;
    ev.preventDefault();
    const field = form.querySelector('input[name="id"]');
    const id = (field && field.value || "").trim();
    if (!id) return;
    postIfSeat(id, true);
    form.reset();
    _ifSeatsHtml = "";
  });
}
function renderIfSeats(s) {
  const box = $("if-seats");
  // renderSync calls this with a null snapshot before the full state arrives.
  // Ignore that pass so the checkbox list is not wiped every tick.
  if (!box || !s) return;
  wireIfSeatsOnce();
  const pathEl = $("if-seats-path");
  const info = (s && s.if_seats) || {instances: [], path: "", override: null};
  if (pathEl && info.path) pathEl.textContent = info.path;
  const configured = new Set((info.instances || []).map(x => String(x)));
  const rows = [];
  const seen = new Set();
  function addRow(id, where, checked) {
    if (!id || seen.has(id)) return;
    seen.add(id);
    rows.push(
      `<label style="display:flex;gap:8px;align-items:baseline;margin:2px 0">` +
      `<input type="checkbox" data-if-id="${escAttr(id)}"${checked ? " checked" : ""}>` +
      `<span><b>${esc(id)}</b> <span class="k">${esc(where)}</span></span></label>`
    );
  }
  for (const n of (s && s.instances) || []) {
    addRow(n.id, "WSJT-X on the wire" + (n.band ? " · " + n.band : ""),
           !!n.if_configured);
  }
  for (const lg of (s && s.loggers) || []) {
    addRow(lg.id, "N1MM station" + (lg.last_band ? " · " + lg.last_band : ""),
           !!lg.if_configured);
  }
  for (const id of info.instances || []) {
    addRow(id, "saved, not heard right now", true);
  }
  let note = "";
  if (info.override === "on") {
    note = `<p class="hint">WIMS_TRANSVERTER is forcing IF mapping <b>on for every seat</b>. Unset it to use this list.</p>`;
  } else if (info.override === "off") {
    note = `<p class="hint">WIMS_TRANSVERTER=0 is forcing IF mapping <b>off</b>. Unset it to use this list.</p>`;
  }
  const list = rows.length
    ? rows.join("")
    : `<span class="k">No WSJT-X or N1MM ids heard yet. Add a rig-name below if you already know it.</span>`;
  const html =
    note + list +
    `<form id="if-seat-add" style="margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">` +
    `<input name="id" placeholder="rig-name or N1MM station" style="font:inherit;padding:4px 6px">` +
    `<button type="submit" style="font:inherit;padding:4px 10px">Mark as IF</button>` +
    `</form>` +
    (configured.size
      ? `<p class="hint" style="margin-top:6px">Saved: ${[...configured].map(esc).join(", ")}</p>`
      : `<p class="hint" style="margin-top:6px">None saved — 21 MHz and 28 MHz dials stay 15m and 10m.</p>`);
  if (html !== _ifSeatsHtml) {
    _ifSeatsHtml = html;
    box.innerHTML = html;
  }
}

/** Setup-only live hints (no-op on other pages). */
function renderSetupExtras(n1mm, s) {
  renderIfSeats(s);
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
  renderSeatMarks(s);
}

let _contestWired = false;
let _contestAdvSig = "";
let _goalMenus = null;
let _checklistSig = "";

function goalTip(text) {
  const tip = text || "";
  const t = escAttr(tip);
  return `<span class="advtip"><button type="button" class="tipbtn" title="${t}" aria-label="Help. ${t}">?</button>` +
    `<span class="tiptxt" role="tooltip">${esc(tip)}</span></span>`;
}

function wireGoalTips() {
  if (window._wimsGoalTipsWired) return;
  window._wimsGoalTipsWired = true;
  const stop = (ev) => {
    const btn = ev.target.closest && ev.target.closest(".tipbtn");
    if (!btn) return;
    ev.preventDefault();
    ev.stopPropagation();
  };
  document.addEventListener("click", stop);
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== " " && ev.key !== "Enter") return;
    stop(ev);
  });
}

function fillGoalSelect(sel, options, current) {
  if (!sel || document.activeElement === sel) return;
  const html = (options || []).map(o =>
    `<option value="${esc(o.id)}"${o.enabled === false ? " disabled" : ""}>${esc(o.title)}</option>`
  ).join("");
  if (sel.dataset.html !== html) {
    sel.innerHTML = html;
    sel.dataset.html = html;
  }
  const cur = current || "";
  if (html && sel.value !== cur) sel.value = cur;
}

function postRules(body) {
  return fetch("/api/rules", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  }).catch(() => {});
}

function renderGoalChecklist(goal) {
  const box = $("goal-checklist");
  if (!box) return;
  if (!goal || !goal.show_checklist) {
    if (box.innerHTML) box.innerHTML = "";
    _checklistSig = "";
    return;
  }
  if (box.contains(document.activeElement)) return;
  const list = goal.checklist || {};
  const rows = list.rows || [];
  const scopes = list.scopes || [];
  const sig = JSON.stringify({rows, scopes, tip: goal.scope_tip || ""});
  if (sig === _checklistSig && box.dataset.ready === "1") return;
  _checklistSig = sig;
  const scopeTip = goal.scope_tip || "";
  const body = rows.map(row => {
    const tip = row.tip || "";
    const scopeHtml = scopes.map(sc =>
      `<option value="${esc(sc.id)}"${sc.id === row.scope ? " selected" : ""}>${esc(sc.label)}</option>`
    ).join("");
    const soon = !!row.coming_soon;
    const locked = soon || row.available === false;
    const label = soon ? `${row.label} (coming soon)` : row.label;
    const checked = !locked && !!row.enabled;
    return `<div class="goal-row advline">` +
      `<label class="${locked ? "goal-soon" : ""}" title="${escAttr(tip)}">` +
      `<input type="checkbox" data-kind="${esc(row.kind)}"${checked ? " checked" : ""}` +
      `${locked ? " disabled" : ""} title="${escAttr(tip)}"> ${esc(label)}</label>` +
      `<select data-scope="${esc(row.kind)}" title="${escAttr(scopeTip)}"${locked ? " disabled" : ""}>` +
      scopeHtml + `</select>` +
      goalTip(tip) +
      `</div>`;
  }).join("");
  box.innerHTML =
    `<p class="hint" style="margin:4px 0">Check what is worth working. ` +
    `WIMS compares each station with the contacts already in the log.</p>` +
    body;
  box.dataset.ready = "1";
  const send = () => {
    const items = rows.map(row => {
      const boxEl = box.querySelector(`input[data-kind="${row.kind}"]`);
      const scopeEl = box.querySelector(`select[data-scope="${row.kind}"]`);
      const soon = !!row.coming_soon;
      const locked = soon || row.available === false;
      const kept = row.stored != null ? !!row.stored : !!row.enabled;
      return {
        kind: row.kind,
        enabled: locked ? kept : !!(boxEl && boxEl.checked),
        scope: (scopeEl && scopeEl.value) || row.scope || "overall",
      };
    });
    _checklistSig = "";
    postRules({action: "checklist", items});
  };
  box.querySelectorAll("input[data-kind], select[data-scope]").forEach(el => {
    el.addEventListener("change", send);
  });
}

const LOG_TIPS = {
  pick: "The log WIMS checks for needed and already worked. Your choice stays until you change it. Suggested for this goal is used only when you have not chosen.",
  cutoff: "Whole log counts every contact. Start now counts only contacts you log after you pick it. This year counts contacts since January 1. This changes which contacts count as worked, not just the list on screen.",
  refresh: "Look for logs again. A new contest file shows up here, and the log you already chose stays chosen.",
  resync: "Read this N1MM contest file again. Use this after the file was updated, or when already-worked stations look wrong.",
};

function renderLogToUse(s) {
  const line = $("log-in-use");
  if (!line) return;
  const info = s && s.log_in_use;
  if (!info) {
    line.textContent = "Log in use: waiting for the server…";
    return;
  }
  line.textContent = info.line || "Log in use: no log yet, 0 contacts, whole log";
  const why = $("log-in-use-why");
  if (why) why.textContent = info.why || "";
  const warn = $("log-warnings");
  if (warn) {
    const rows = (info.warnings || []).concat(info.notes || []);
    warn.innerHTML = rows.map(r => {
      const bad = r.level === "warn";
      return `<div${bad ? ' style="color:#8a3b00"' : ""}>${esc(r.message || "")}</div>`;
    }).join("");
  }
  const guide = $("log-guidance");
  if (guide) guide.textContent = info.guidance || "";
  const pick = $("log-pick");
  const cut = $("log-cutoff");
  if (pick) fillGoalSelect(pick, info.options || [], info.selected_id || "auto");
  if (cut) fillGoalSelect(cut, info.cutoffs || [], info.cutoff || "whole");
  const pickTip = $("log-pick-tip");
  if (pickTip && pickTip.dataset.tip !== LOG_TIPS.pick) {
    pickTip.innerHTML = goalTip(LOG_TIPS.pick);
    pickTip.dataset.tip = LOG_TIPS.pick;
  }
  const cutTip = $("log-cutoff-tip");
  if (cutTip && cutTip.dataset.tip !== LOG_TIPS.cutoff) {
    cutTip.innerHTML = goalTip(LOG_TIPS.cutoff);
    cutTip.dataset.tip = LOG_TIPS.cutoff;
  }
  if (pick && cut && !window._wimsLogWired) {
    window._wimsLogWired = true;
    wireGoalTips();
    pick.addEventListener("change", () => {
      postRules({action: "select_log", id: pick.value});
    });
    cut.addEventListener("change", () => {
      postRules({action: "select_cutoff", cutoff: cut.value});
    });
  }
  const refreshTip = $("log-refresh-tip");
  if (refreshTip && refreshTip.dataset.tip !== LOG_TIPS.refresh) {
    refreshTip.innerHTML = goalTip(LOG_TIPS.refresh);
    refreshTip.dataset.tip = LOG_TIPS.refresh;
  }
  const resyncTip = $("log-resync-tip");
  if (resyncTip && resyncTip.dataset.tip !== LOG_TIPS.resync) {
    resyncTip.innerHTML = goalTip(LOG_TIPS.resync);
    resyncTip.dataset.tip = LOG_TIPS.resync;
  }
  const tools = $("log-n1mm-tools");
  if (tools) tools.hidden = info.kind !== "n1mm";
  const shared = $("shared-log");
  if (shared && shared.dataset.filled !== "1" && document.activeElement !== shared) {
    shared.value = info.shared_path || "";
    shared.dataset.filled = "1";
  }
}

function renderN1mmNav(s) {
  const n = (s && s.loggers) ? s.loggers.length : 0;
  const multi = n >= 2;
  let here = false;
  try {
    const p = (location.pathname || "/").replace(/\/$/, "") || "/";
    here = p === "/n1mm";
  } catch (_) {}
  document.querySelectorAll("a.nav-n1mm").forEach(a => {
    // Several stations: show it everywhere. One station: show it only on this page,
    // so a direct visit still has a selected tab.
    if (multi || here) a.removeAttribute("hidden");
    else a.setAttribute("hidden", "");
  });
  const single = $("n1mm-single");
  const multiBox = $("n1mm-multi");
  if (single) single.hidden = multi;
  if (multiBox) multiBox.hidden = !multi;
}

function renderContestRules(s) {
  renderLogToUse(s);
  const rules = s && s.rules;
  if (!rules) return;
  let line = rules.source_label
    ? (rules.source_label + " — " + (rules.summary || ""))
    : (rules.summary || "");
  if (rules.suggested_note) line += " " + rules.suggested_note;
  if (rules.n1mm_line) line += " " + rules.n1mm_line;
  for (const id of ["contest-summary", "ros-rules", "n1mm-rules-line"]) {
    const el = $(id);
    if (el) el.textContent = line;
  }
  const logs = $("contest-logs");
  if (logs) {
    const rows = s.log_access || [];
    logs.innerHTML = rows.map(r => {
      const bad = r.status && r.status !== "ok" && r.status !== "missing_file";
      return `<div${bad ? ' style="color:#8a3b00"' : ""}>${esc(r.message || "")}</div>`;
    }).join("");
  }
  const goal = rules.goal;
  const typeSel = $("goal-pick");
  const detailSel = $("goal-detail");
  if (goal && typeSel) {
    _goalMenus = goal.menus || _goalMenus;
    const typeTip = ((goal.types || []).find(t => t.id === goal.type) || {}).tip || typeSel.title;
    if (document.activeElement !== typeSel) typeSel.title = typeTip || typeSel.title;
    fillGoalSelect(typeSel, goal.types || [], goal.type);
    const tipHost = $("goal-pick-tip");
    if (tipHost && tipHost.dataset.tip !== typeTip) {
      tipHost.innerHTML = goalTip(typeTip);
      tipHost.dataset.tip = typeTip || "";
    }
  }
  if (goal && detailSel) {
    const detailTip = goal.detail_tip || detailSel.title;
    if (document.activeElement !== detailSel) detailSel.title = detailTip;
    const lab = $("goal-detail-label");
    if (lab && goal.detail_label) lab.textContent = goal.detail_label;
    fillGoalSelect(detailSel, goal.options || [], goal.id);
    const tipHost = $("goal-detail-tip");
    if (tipHost && tipHost.dataset.tip !== detailTip) {
      tipHost.innerHTML = goalTip(detailTip);
      tipHost.dataset.tip = detailTip || "";
    }
  }
  if (typeSel && detailSel && !_contestWired) {
    _contestWired = true;
    wireGoalTips();
    typeSel.addEventListener("change", () => {
      const next = typeSel.value;
      const menu = (_goalMenus && _goalMenus[next]) || {};
      const opt = (menu.options || []).find(o => o.enabled !== false);
      const lab = $("goal-detail-label");
      if (lab && menu.label) lab.textContent = menu.label;
      if (menu.tip) detailSel.title = menu.tip;
      fillGoalSelect(detailSel, menu.options || [], opt ? opt.id : "");
      postRules({action: "select", goal: next, goal_id: opt ? opt.id : ""});
    });
    detailSel.addEventListener("change", () => {
      const picked = detailSel.selectedOptions && detailSel.selectedOptions[0];
      if (picked && picked.disabled) return;
      postRules({
        action: "select",
        goal: typeSel.value,
        goal_id: detailSel.value,
      });
    });
  }
  renderGoalChecklist(goal);
  renderContestAdvanced(s);
}

// Plain-language tips for Setup → Advanced. One or two short sentences.
// Casual operators: no commands, no file-format names, no setting keys.
const ADV_TIPS = {
  summary: "Extra choices. Leave this closed when the Goal menus already look right.",
  stationState: "The state you are operating from, such as NY. Leave this blank when the contest does not care.",
  stationCounty: "The county you are operating from. In a county contest, a later change here can let the same station count again.",
  saveStation: "Remember this state and county on this computer.",
  sharedLog: "One log file used by every WSJT-X on this computer. Leave this blank to keep each program's own log.",
  saveShared: "Read contacts from the file in the box, for every WSJT-X on this computer.",
  rules: "Choices for a contest that is not in the Contest list. Saving them switches Goal to Custom.",
  dupeScope: "How often the same station can count. Once on each band, once on each band for voice, CW, and digital separately, or only once in the whole contest.",
  dupeReset: "After you change county, the same station can count again. A station that stays in one county is not affected.",
  banFt8: "FT8 contacts do not count in this custom contest. Leave this unchecked when FT8 is allowed.",
  banFt4: "FT4 contacts do not count in this custom contest. Leave this unchecked when FT4 is allowed.",
  modeGroups: "Voice is one group, CW is another, and digital is a third. The menu above can count each group as its own contact.",
  points: "A custom rule gives 1 point for voice, 2 for CW, and 3 for digital. A contest in the menu uses that contest's own points.",
  multipliers: "A custom rule does not add multipliers. ARRL VHF counts a new grid on each band, and NY QSO Party does not mark multipliers yet.",
  rover: "Working a rover again counts as a new contact after that rover moves to a new grid square.",
  saveCustom: "Save these contest choices and switch Goal to Custom.",
  udcPath: "An N1MM contest file on this computer. WIMS reads it, shows what it understood, and does not change the file.",
  udcImport: "Read the N1MM contest file named above and show the name, how often a station counts, the points, and the multipliers.",
  checkLogs: "Compare the logs WIMS found on this computer and list what does not match. Nothing in the logs is changed.",
};

function tipBtn(text) {
  const t = escAttr(text);
  return `<span class="advtip"><button type="button" class="tipbtn" title="${t}" aria-label="Help. ${t}">?</button><span class="tiptxt" role="tooltip">${t}</span></span>`;
}

function wireTipButtons() {
  if (window._wimsTipsWired) return;
  window._wimsTipsWired = true;
  const hit = (e) => e.target && e.target.closest && e.target.closest("button.tipbtn");
  document.addEventListener("mousedown", (e) => {
    if (!hit(e)) return;
    e.stopPropagation();
  }, true);
  document.addEventListener("click", (e) => {
    if (!hit(e)) return;
    e.preventDefault();
    e.stopPropagation();
  }, true);
  document.addEventListener("keydown", (e) => {
    if (e.key !== " " && e.key !== "Enter") return;
    if (!hit(e)) return;
    e.preventDefault();
    e.stopPropagation();
  }, true);
}

function renderContestAdvanced(s) {
  const box = $("contest-advanced-body");
  if (!box || !s || !s.rules) return;
  if (box.contains(document.activeElement)) return;
  const rules = s.rules;
  const choice = rules.choice || {};
  const sig = JSON.stringify({choice});
  if (sig === _contestAdvSig && box.dataset.ready === "1") return;
  _contestAdvSig = sig;
  box.innerHTML =
    `<p class="advline"><label>Station state <input id="st-state" title="${escAttr(ADV_TIPS.stationState)}" value="${escAttr(choice.station_state || "")}" size="6"></label>${tipBtn(ADV_TIPS.stationState)} ` +
    `<label>county <input id="st-county" title="${escAttr(ADV_TIPS.stationCounty)}" value="${escAttr(choice.station_county || "")}" size="12"></label>${tipBtn(ADV_TIPS.stationCounty)} ` +
    `<button type="button" id="st-save" title="${escAttr(ADV_TIPS.saveStation)}">Save station</button>${tipBtn(ADV_TIPS.saveStation)}</p>` +
    `<p class="advline">Contest rules ${tipBtn(ADV_TIPS.rules)}</p>` +
    `<p class="advline"><label>How often a station counts <select id="custom-scope" title="${escAttr(ADV_TIPS.dupeScope)}">` +
    `<option value="band">once per band</option>` +
    `<option value="band+group">once per band for voice, CW, and digital separately</option>` +
    `<option value="all">once per contest</option></select></label>${tipBtn(ADV_TIPS.dupeScope)}</p>` +
    `<span class="advline"><label><input type="checkbox" id="custom-county" title="${escAttr(ADV_TIPS.dupeReset)}"> Reset a dupe when my county changes</label>${tipBtn(ADV_TIPS.dupeReset)}</span>` +
    `<span class="advline"><label><input type="checkbox" id="custom-ft8" title="${escAttr(ADV_TIPS.banFt8)}"> Do not count FT8</label>${tipBtn(ADV_TIPS.banFt8)}</span>` +
    `<span class="advline"><label><input type="checkbox" id="custom-ft4" title="${escAttr(ADV_TIPS.banFt4)}"> Do not count FT4</label>${tipBtn(ADV_TIPS.banFt4)}</span>` +
    `<p class="advline">Mode groups ${tipBtn(ADV_TIPS.modeGroups)}</p>` +
    `<p class="advline">Points ${tipBtn(ADV_TIPS.points)}</p>` +
    `<p class="advline">Multipliers ${tipBtn(ADV_TIPS.multipliers)}</p>` +
    `<span class="advline"><label><input type="checkbox" id="custom-rover" title="${escAttr(ADV_TIPS.rover)}"> A rover in a new grid is a new contact</label>${tipBtn(ADV_TIPS.rover)}</span>` +
    `<p class="advline"><button type="button" id="custom-save" title="${escAttr(ADV_TIPS.saveCustom)}">Save custom rules</button>${tipBtn(ADV_TIPS.saveCustom)}</p>` +
    `<p class="advline"><label>N1MM contest file on this computer <input id="udc-path" title="${escAttr(ADV_TIPS.udcPath)}" size="42"></label>${tipBtn(ADV_TIPS.udcPath)} ` +
    `<button type="button" id="udc-import" title="${escAttr(ADV_TIPS.udcImport)}">Read it</button>${tipBtn(ADV_TIPS.udcImport)}</p>` +
    `<pre id="udc-out" style="white-space:pre-wrap"></pre>`;
  box.dataset.ready = "1";
  const post = (body) => fetch("/api/rules", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  });
  $("st-save").onclick = () => post({
    action: "station",
    station_state: $("st-state").value,
    station_county: $("st-county").value,
  }).catch(() => {});
  $("custom-save").onclick = () => post({
    action: "save_custom",
    dupe_scope: $("custom-scope").value,
    dupe_reset_county: $("custom-county").checked,
    ban_ft8: $("custom-ft8").checked,
    ban_ft4: $("custom-ft4").checked,
    rover_grid: $("custom-rover").checked,
  }).catch(() => {});
  $("udc-import").onclick = () => {
    post({action: "import_udc", path: $("udc-path").value})
      .then(r => r.json())
      .then(j => { $("udc-out").textContent = JSON.stringify(j.udc || j, null, 2); })
      .catch(() => {});
  };
}

function renderLogPageControls() {
  const shared = $("log-shared");
  if (shared && shared.dataset.ready !== "1") {
    shared.innerHTML =
      `<p class="advline"><label>Shared log file <input id="shared-log" title="${escAttr(ADV_TIPS.sharedLog)}" size="42"></label>${tipBtn(ADV_TIPS.sharedLog)} ` +
      `<button type="button" id="shared-save" title="${escAttr(ADV_TIPS.saveShared)}">Use this WSJT-X log</button>${tipBtn(ADV_TIPS.saveShared)}</p>`;
    shared.dataset.ready = "1";
    $("shared-save").onclick = () => {
      const field = $("shared-log");
      if (field) field.dataset.filled = "1";
      fetch("/api/rules", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          action: "shared_log",
          shared_path: field ? field.value : "",
          use_wsjtx: true,
        }),
      }).catch(() => {});
    };
  }
  const check = $("log-check");
  if (check && check.dataset.ready !== "1") {
    check.innerHTML =
      `<p class="advline"><button type="button" id="logs-check" title="${escAttr(ADV_TIPS.checkLogs)}">Check logs</button>${tipBtn(ADV_TIPS.checkLogs)} ` +
      `<span id="logs-check-progress" class="meta"></span></p>` +
      `<div id="logs-check-out"></div>`;
    check.dataset.ready = "1";
    $("logs-check").onclick = () => startLogCheck();
  }
}

const LOG_CHECK_PAGE = 40;

function startLogCheck() {
  const prog = $("logs-check-progress");
  const out = $("logs-check-out");
  if (prog) prog.textContent = "Looking for logs…";
  if (out) out.innerHTML = "";
  const tick = () => {
    fetch("/api/logs/check").then(r => r.json()).then(j => {
      if (!j || j.state === "running" || j.state === "idle") {
        if (prog) prog.textContent = (j && j.progress) || "Looking for logs…";
        setTimeout(tick, 400);
        return;
      }
      if (prog) prog.textContent = "";
      renderLogCheckResult(out, j);
    }).catch(() => { if (prog) prog.textContent = "Check failed. Try again."; });
  };
  fetch("/api/logs/check", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: "{}",
  }).then(r => r.json()).then(j => {
    if (j && j.state === "done") {
      if (prog) prog.textContent = "";
      renderLogCheckResult(out, j);
      return;
    }
    if (prog) prog.textContent = (j && j.progress) || "Looking for logs…";
    setTimeout(tick, 400);
  }).catch(() => { if (prog) prog.textContent = "Check failed. Try again."; });
}

function renderLogCheckResult(out, report) {
  if (!out || !report) return;
  const state = {page: {}, filter: ""};
  const paint = () => {
    const body = out.querySelector("[data-logcheck-detail]");
    if (!body) return;
    body.innerHTML = logCheckDetailHtml(report, state);
    body.querySelectorAll("button[data-page]").forEach(btn => {
      btn.onclick = () => {
        state.page[btn.getAttribute("data-group")] = Number(btn.getAttribute("data-page"));
        paint();
      };
    });
  };
  const sources = (report.sources || []).map(src => {
    let extra = "";
    if (src.shared_by && src.shared_by.length > 1) {
      extra += " Same file for " + src.shared_by.map(esc).join(", ") + ".";
    }
    if (src.cached) extra += " Unchanged, so it was not read again.";
    return `<div>${esc(src.name)} — ${esc(src.detail || src.status || "")}.${extra}</div>`;
  }).join("");
  const notes = (report.notes || []).map(note => `<div class="meta">${esc(note)}</div>`).join("");
  out.innerHTML =
    `<p><b>${esc(report.summary || "")}</b></p>` +
    sources + notes +
    `<details><summary>Show details</summary>` +
    `<p><label>Filter <input data-logcheck-filter size="18" title="Show only contacts that match this text."></label></p>` +
    `<div data-logcheck-detail></div></details>`;
  const filt = out.querySelector("[data-logcheck-filter]");
  if (filt) {
    filt.oninput = () => {
      state.filter = filt.value;
      state.page = {};
      paint();
    };
  }
  paint();
}

function logCheckHit(row, q) {
  if (!q) return true;
  return [row.call, row.band, row.mode, row.time, row.grid, row.found_in, row.detail]
    .join(" ").toLowerCase().includes(q);
}

function logCheckDetailHtml(report, state) {
  const q = (state.filter || "").trim().toLowerCase();
  const missing = report.missing || {};
  let html = "";
  Object.keys(missing).forEach(name => {
    const all = (missing[name] || []).filter(row => logCheckHit(row, q));
    if (!all.length && q) return;
    const page = state.page[name] || 0;
    const slice = all.slice(page * LOG_CHECK_PAGE, (page + 1) * LOG_CHECK_PAGE);
    html += `<p><b>Missing from ${esc(name)}</b> (${all.length})</p>` +
      slice.map(logCheckLine).join("") + logCheckPager(name, page, all.length);
  });
  const disag = (report.disagreements || []).filter(row => logCheckHit(row, q));
  if (disag.length) {
    const page = state.page.disagreements || 0;
    const slice = disag.slice(page * LOG_CHECK_PAGE, (page + 1) * LOG_CHECK_PAGE);
    html += `<p><b>Different grid or mode</b> (${disag.length})</p>` +
      slice.map(row => {
        const why = row.detail === "grid" ? (row.grid ? "  " + esc(row.grid) : "")
          : (row.detail ? "  " + esc(row.detail) : "");
        return `<div>${esc(row.time)}  ${esc(row.call)}  ${esc(row.band)}  ${esc(row.mode)}${why}</div>`;
      }).join("") + logCheckPager("disagreements", page, disag.length);
  }
  const dupes = report.duplicates || [];
  if (dupes.length) {
    const extra = dupes.reduce((n, row) => n + Math.max(0, (row.count || 0) - 1), 0);
    html += `<p><b>${extra} extra cop${extra === 1 ? "y" : "ies"} collapsed</b></p>` +
      dupes.slice(0, LOG_CHECK_PAGE).map(row =>
        `<div>${esc(row.time)}  ${esc(row.call)}  ${esc(row.band)}  ${esc(row.mode)}  ×${esc(row.count)}</div>`
      ).join("");
  }
  if (!html) html = `<p class="meta">Nothing else to list.</p>`;
  return html;
}

function logCheckLine(row) {
  const grid = row.grid ? "  " + esc(row.grid) : "";
  const found = row.found_in ? "  (in " + esc(row.found_in) + ")" : "";
  return `<div>${esc(row.time)}  ${esc(row.call)}  ${esc(row.band)}  ${esc(row.mode)}${grid}${found}</div>`;
}

function logCheckPager(name, page, total) {
  if (total <= LOG_CHECK_PAGE) return "";
  const from = page * LOG_CHECK_PAGE + 1;
  const to = Math.min(total, (page + 1) * LOG_CHECK_PAGE);
  const prev = page > 0
    ? `<button type="button" data-group="${esc(name)}" data-page="${page - 1}" title="Previous page">Previous</button> `
    : "";
  const next = to < total
    ? ` <button type="button" data-group="${esc(name)}" data-page="${page + 1}" title="Next page">Next</button>`
    : "";
  return `<p>${prev}${from}–${to} of ${total}${next}</p>`;
}

// -- H2 seat-profile marks (Setup) ------------------------------------------ //

let _seatMarksWired = false;
let _seatMarkDraft = {}; // id -> true|false (tx_capable)

function renderSeatMarks(s) {
  const box = $("seat-marks");
  if (!box || !s) return;
  const pathEl = $("seat-path");
  const classEl = $("seat-class");
  const checksEl = $("seat-checks");
  const sp = s.seat_profile || {};
  if (pathEl) {
    pathEl.textContent = sp.path
      ? ((sp.exists ? "file: " : "will create: ") + sp.path)
      : "";
  }
  if (classEl && document.activeElement !== classEl) {
    classEl.value = sp.station_class || "";
  }
  const live = (s.instances || []).filter(n => (n.health || "") !== "DEAD");
  const marked = {};
  for (const m of (sp.instances || [])) {
    if (m && m.id) marked[m.id] = m;
  }
  // Seed draft from live + profile once per id (keep operator edits).
  for (const n of live) {
    if (_seatMarkDraft[n.id] === undefined) {
      _seatMarkDraft[n.id] = (n.tx_capable !== false);
    }
  }
  if (!live.length) {
    box.className = "empty";
    box.textContent = "No live WSJT-X yet — start instances, then mark them.";
  } else {
    box.className = "";
    box.innerHTML = live.map(n => {
      const tx = !!_seatMarkDraft[n.id];
      const name = esc(n.id);
      const band = esc(fmtBand(n.band || "?"));
      return `<div class="syncrow" style="justify-content:flex-start;gap:14px;margin:4px 0">` +
        `<span style="min-width:10em"><b>${name}</b> <span class="meta">${band}</span></span>` +
        `<label><input type="radio" name="seat-tx-${esc(n.id)}" value="1"` +
        `${tx ? " checked" : ""} data-seat-id="${esc(n.id)}"> TX-capable</label>` +
        `<label><input type="radio" name="seat-tx-${esc(n.id)}" value="0"` +
        `${tx ? "" : " checked"} data-seat-id="${esc(n.id)}"> decode-only</label>` +
        `</div>`;
    }).join("");
    box.querySelectorAll("input[type=radio][data-seat-id]").forEach(inp => {
      inp.onchange = () => {
        _seatMarkDraft[inp.dataset.seatId] = inp.value === "1";
      };
    });
  }
  if (checksEl) {
    const checks = sp.checks || [];
    if (!checks.length) {
      checksEl.innerHTML = `<span class="k">No profile checks yet.</span>`;
    } else {
      checksEl.innerHTML = checks.map(c => {
        const sev = (c.severity || "info").toLowerCase();
        const cls = sev === "error" ? "DEAD" : (sev === "warn" ? "warn" : "meta");
        return `<span class="${cls}">[${esc(sev)}] ${esc(c.detail || c.code || "")}</span>`;
      }).join(" ");
    }
  }
  if (!_seatMarksWired) {
    _seatMarksWired = true;
    const saveBtn = $("seat-save");
    const reloadBtn = $("seat-reload");
    if (saveBtn) {
      saveBtn.onclick = async () => {
        const instances = Object.keys(_seatMarkDraft).sort().map(id => ({
          id,
          tx_capable: !!_seatMarkDraft[id],
          rf_path: _seatMarkDraft[id] ? "trx" : "sdr_rx",
        }));
        const body = {
          station_class: ($("seat-class") && $("seat-class").value) || "",
          instances,
          clear_missing: true,
        };
        try {
          const r = await fetch("/api/seat-profile", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(body),
          });
          const j = await r.json().catch(() => ({}));
          if (!j.ok) {
            alert("Save failed: " + (j.detail || j.error || r.status));
            return;
          }
          // Refresh draft from saved marks.
          _seatMarkDraft = {};
          for (const m of (j.instances || [])) {
            _seatMarkDraft[m.id] = !!m.tx_capable;
          }
          if (checksEl) {
            const checks = j.checks || [];
            checksEl.innerHTML = checks.map(c => {
              const sev = (c.severity || "info").toLowerCase();
              const cls = sev === "error" ? "DEAD" : (sev === "warn" ? "warn" : "meta");
              return `<span class="${cls}">[${esc(sev)}] ${esc(c.detail || "")}</span>`;
            }).join(" ") || `<span class="meta">Saved.</span>`;
          }
          if (pathEl) pathEl.textContent = "saved: " + (j.path || "");
        } catch (e) {
          alert("Save failed: " + e);
        }
      };
    }
    if (reloadBtn) {
      reloadBtn.onclick = async () => {
        try {
          const r = await fetch("/api/seat-profile", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({reload: true}),
          });
          const j = await r.json().catch(() => ({}));
          _seatMarkDraft = {};
          for (const m of (j.instances || [])) {
            _seatMarkDraft[m.id] = !!m.tx_capable;
          }
          if (classEl) classEl.value = j.station_class || "";
          // Next SSE tick will re-render; force from GET-shaped payload.
          renderSeatMarks({
            instances: (s && s.instances) || [],
            seat_profile: j,
          });
        } catch (e) {
          alert("Reload failed: " + e);
        }
      };
    }
  }
}

// -- operating page --------------------------------------------------------- //

// What a "group" is. Shown as a hover title on the TX groups label (and the
// banner), not as a paragraph on the page.
const IL_GROUP_TIP =
  "A group is a set of WSJT-X instances that must not transmit at the same time " +
  "(shared PA, antenna, or band policy). WIMS refuses Work when another instance " +
  "in the same group already holds TX.";

// Display rule (does not grant, refuse, or halt):
//   * Hide the whole block while every group has one instance, nothing is
//     blocked, no overlap has been seen, and Work has not been refused.
//   * A group with more than one instance keeps a closed "TX groups" list so
//     a multi-op station can open the table.
//   * Overlap now, a recorded overlap, a refused Work, or one transmitter in
//     a shared group shows a one-line banner. The list opens itself only
//     while an overlap is in progress.
let _ilLast = null;
let _ilRefused = null;       // {holder, misses, seen} after group_busy
let _ilOverlapLatched = false;

function interlockGroupOf(il, tx, holder) {
  if (!holder) return "";
  const holders = (tx && tx.holders) || {};
  const keys = Object.keys(holders);
  for (let i = 0; i < keys.length; i++) {
    if (holders[keys[i]] === holder) return keys[i];
  }
  const groups = (il && il.groups) || [];
  for (let i = 0; i < groups.length; i++) {
    const g = groups[i];
    const ids = g.instances || [];
    const txing = g.transmitting || [];
    if (ids.indexOf(holder) >= 0 || txing.indexOf(holder) >= 0) return g.group;
  }
  return holder;
}

function interlockHolderLive(il, tx, holder) {
  if (!holder) return false;
  const holders = (tx && tx.holders) || {};
  const keys = Object.keys(holders);
  for (let i = 0; i < keys.length; i++) {
    if (holders[keys[i]] === holder) return true;
  }
  const groups = (il && il.groups) || [];
  for (let i = 0; i < groups.length; i++) {
    if ((groups[i].transmitting || []).indexOf(holder) >= 0) return true;
  }
  return false;
}

function interlockView(il, tx, refusedHolder) {
  const groups = (il && il.groups) || [];
  const holders = (tx && tx.holders) || {};
  const multi = groups.some(g => (g.instances || []).length > 1);
  const overlapNames = [];
  for (let i = 0; i < groups.length; i++) {
    const txing = groups[i].transmitting || [];
    // Two transmitters in one group is an overlap even if a flag was missed.
    if (groups[i].overlap || txing.length > 1) overlapNames.push(groups[i].group);
  }
  const overlapNow = !!(il && il.overlap_now) || overlapNames.length > 0;
  if (overlapNow) {
    if (!overlapNames.length && il && il.last_violation && il.last_violation.group)
      overlapNames.push(il.last_violation.group);
    const label = overlapNames.length ? fmtBands(overlapNames) : "group";
    return {
      section: true, banner: true, level: "alarm", open: true, multi: true,
      text: "Overlap: " + label,
    };
  }
  const blocked = [];
  for (let i = 0; i < groups.length; i++) {
    const g = groups[i];
    const ids = g.instances || [];
    if (ids.length < 2) continue;
    const txing = g.transmitting || [];
    const holder = holders[g.group];
    const othersBlocked = !!(holder && ids.some(id => id !== holder));
    if ((txing.length === 1 || othersBlocked) && blocked.indexOf(g.group) < 0)
      blocked.push(g.group);
  }
  // null/undefined = no refusal. A string (even empty) means Work just came
  // back group_busy and the snapshot may not list the holder yet.
  if (refusedHolder != null) {
    const g = refusedHolder ? interlockGroupOf(il, tx, refusedHolder) : "";
    const name = g || "group";
    if (blocked.indexOf(name) < 0) blocked.push(name);
  }
  if (blocked.length) {
    const verb = blocked.length > 1 ? "are" : "is";
    return {
      section: true, banner: true, level: "alarm", open: false, multi: multi,
      text: "Work blocked: " + fmtBands(blocked) + " " + verb + " transmitting",
    };
  }
  if (il && il.violation_count) {
    const g = (il.last_violation && il.last_violation.group) || "group";
    return {
      section: true, banner: true, level: "tx", open: false, multi: multi,
      text: "Overlap: " + fmtBand(g),
    };
  }
  return {
    section: multi, banner: false, level: "ok", open: false, multi: multi, text: "",
  };
}

function renderInterlock(il, tx, holdRefusal) {
  if (!il || !$("il-banner")) return;
  _ilLast = il;
  const txState = tx || _txState;
  if (!holdRefusal && _ilRefused) {
    if (interlockHolderLive(il, txState, _ilRefused.holder)) {
      _ilRefused.seen = true;
      _ilRefused.misses = 0;
    } else if (_ilRefused.seen) {
      _ilRefused = null;
    } else {
      _ilRefused.misses = (_ilRefused.misses || 0) + 1;
      if (_ilRefused.misses >= 2) _ilRefused = null;
    }
  }
  const refused = _ilRefused ? (_ilRefused.holder || "") : null;
  const view = interlockView(il, txState, refused);
  const section = $("il-section");
  const banner = $("il-banner");
  const details = $("il-details");
  const summary = $("il-summary");
  if (summary) summary.title = IL_GROUP_TIP;
  banner.title = IL_GROUP_TIP;
  if (section) section.hidden = !view.section;
  if (view.section && view.banner) {
    banner.hidden = false;
    banner.className = "banner " + view.level;
    banner.textContent = view.text;
  } else {
    banner.hidden = true;
    banner.textContent = "";
  }
  if (details) {
    if (view.open && !_ilOverlapLatched) {
      details.open = true;
      _ilOverlapLatched = true;
    }
    if (!view.open) _ilOverlapLatched = false;
  }
  const meta = $("il-meta");
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
      `<td>${esc(fmtBand(g.group))}</td><td>${g.instances.join(", ")}</td>` +
      `<td class="state-TX">${g.transmitting.join(", ")||"—"}</td><td>${status}</td>`;
    body.appendChild(tr);
  }
}

// GridTracker-style call roster: one row per station heard, with the score kept as a
// column. The show menu filters by need, CQ, and 73; band checkboxes narrow further.
// Every header sorts. Click the *line* to Work (no Work button). Columns are selectable
// (localStorage) so the table can stay narrow on small screens.
const ROS_COLS = [
  {key:"call",          label:"DX",      cls:"",          locked:1, cell:rosCall},
  {key:"country",       label:"Country", cls:"country",
   hint:"DXCC entity for this call. Blank when the prefix is not known. Hover for the full name, and continent and CQ zone when WIMS has them.",
   cell:rosCountry},
  {key:"to_call",       label:"Calling", cls:"",          cell:c=>rosCalling(c)},
  {key:"msg",           label:"Message", cls:"",
   hint:"Report, grid, 73, or other text after the callsigns. Hover a cell for the full decode.",
   cell:rosMessage},
  {key:"band",          label:"Band",    cls:"",          cell:c=>fmtBand(c.band||"-")},
  {key:"instance",      label:"Source",  cls:"",          cell:rosSource},
  {key:"mode",          label:"Mode",    cls:"",          cell:c=>c.mode||"-"},
  {key:"grid",          label:"Grid",    cls:"",          cell:rosGrid},
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
// Message sits immediately after Calling.
const ROS_COLS_DEFAULT = [
  "call", "country", "to_call", "msg", "band", "grid", "snr", "az", "age", "score",
];
// Visible Message text. Longer QSY / free text is cut here so rosFitColumns
// measures a short cell; the title attribute keeps the full decode.
const ROS_MSG_SHOW = 14;
let _rosData = null;                              // latest roster payload
let _rosSort = {key:"score", dir:-1};             // default: score, descending
let _rosWired = false;
const ROS_BANDS_KEY = "wims.ops.bands";
const ROS_COLS_KEY = "wims.ops.cols";
// 2: Message (msg) joined the default set, right after Calling.
// 3: Country joined the default set, right after DX.
// A saved list from an older version never contained the new column, so it
// would hide the column forever. The one-time merge below inserts it, then
// leaves later unchecks alone.
const ROS_COLS_VERSION = 3;
const ROS_COLS_VERSION_KEY = "wims.ops.cols.v";
const DASH_ID_KEY = "wims.ops.dashboardId";

function dashboardId() {
  try {
    let id = localStorage.getItem(DASH_ID_KEY);
    if (!id) {
      id = (crypto.randomUUID && crypto.randomUUID())
        || ("d-" + Math.random().toString(16).slice(2) + Date.now().toString(16));
      localStorage.setItem(DASH_ID_KEY, id);
    }
    return id;
  } catch (_) {
    if (!window._wimsDashId) {
      window._wimsDashId = "d-mem-" + Math.random().toString(16).slice(2);
    }
    return window._wimsDashId;
  }
}

function myTxClaims(tx) {
  const id = dashboardId();
  return ((tx && tx.claims) || []).filter(c => c.dashboard_id === id);
}

function myTxBands(tx) {
  return [...new Set(myTxClaims(tx).map(c => c.band).filter(Boolean))].sort();
}
const ROS_AGE_KEY = "wims.ops.maxAgeSec";
const ROS_NEED_KEY = "wims.ops.needed";
const ROS_AGE_DEFAULT = 120; // match GridTracker-ish “last ~2 minutes” feel
let _rosColsBuilt = false;

function rosCall(c) {
  const badges =
    (c.is_calling_us ? '<span class="badge callus">us</span>' : '') +
    (c.is_armed ? '<span class="badge armed">TX</span>' : '') +
    (c.is_new_mult ? '<span class="badge" title="' + escAttr(c.mult_reason || '') + '">mult</span>' : '') +
    (c.is_rover ? '<span class="badge rover">R</span>' : '');
  return `${esc(c.call)}${badges}`;
}
const CONTINENT_NAME = {
  NA: "North America", SA: "South America", EU: "Europe",
  AF: "Africa", AS: "Asia", OC: "Oceania", AN: "Antarctica",
};
function rosCountryTip(c) {
  const name = String(c.country || "").trim();
  if (!name) return "";
  const bits = [name];
  const raw = String(c.continent || c.continent_name || "").trim();
  const cont = CONTINENT_NAME[raw.toUpperCase()] || raw;
  if (cont && cont.toUpperCase() !== name.toUpperCase()) bits.push(cont);
  const cq = (c.cq_zone != null && c.cq_zone !== "") ? c.cq_zone
    : ((c.cqz != null && c.cqz !== "") ? c.cqz : "");
  if (cq !== "") bits.push("CQ " + cq);
  return bits.join(" · ");
}
function rosCountry(c) {
  const name = String(c.country || "").trim();
  if (!name) return "";
  const tip = rosCountryTip(c);
  return `<span class="ros-country" title="${escAttr(tip)}">${esc(name)}</span>`;
}
function rosCalling(c) {
  if (c.is_cq) return '<span class="cq">CQ</span>';
  const t = c.to_call || "";
  if (c.is_qsy || /^QSY\b/i.test(t) || /^(NOQSY|TNX|SRI|AGN)$/i.test(t)) {
    return `<span class="qsy" title="WSJT-X Message System / QSY">${esc(t || "QSY")}</span>`;
  }
  return esc(t || "-");
}
function rosGrid(c) {
  // Italic: the square is remembered from an earlier decode, not this message.
  const tip = c.grid_tip || "";
  const title = tip ? ` title="${escAttr(tip)}"` : "";
  if (c.grid_stale) return `<span class="grid-stale"${title}>-</span>`;
  if (!c.grid) return "-";
  if (c.grid_remembered) {
    return `<span class="grid-remembered"${title}>${esc(c.grid)}</span>`;
  }
  return esc(c.grid);
}
function rosMessage(c) {
  const tail = rosExchangeTail(c);
  const full = String(c.message || "").trim();
  const tip = full || tail;
  if (!tail) {
    if (!tip) return "-";
    return `<span class="ros-msg" title="${escAttr(tip)}">-</span>`;
  }
  const short = tail.length > ROS_MSG_SHOW
    ? tail.slice(0, ROS_MSG_SHOW - 1) + "…"
    : tail;
  return `<span class="ros-msg" title="${escAttr(tip)}">${esc(short)}</span>`;
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
  const mark = (c.tx_capable === false)
    ? ' <span class="badge" title="decode-only">decode</span>'
    : "";
  if (!raw || short === raw) return esc(short) + mark;
  return `<span title="${esc(raw)}">${esc(short)}</span>${mark}`;
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

function rosInsertNewCols(keys) {
  // Saved sets from before Message existed omit msg. Put it right after Calling.
  if (!keys || keys.indexOf("msg") >= 0) return keys;
  const at = keys.indexOf("to_call");
  if (at >= 0) return keys.slice(0, at + 1).concat(["msg"], keys.slice(at + 1));
  return ["msg"].concat(keys);
}

function rosInsertCountry(keys) {
  // Saved sets from before Country existed omit it. Put it right after DX.
  if (!keys || keys.indexOf("country") >= 0) return keys;
  const at = keys.indexOf("call");
  if (at >= 0) return keys.slice(0, at + 1).concat(["country"], keys.slice(at + 1));
  return ["country"].concat(keys);
}

function rosMigrateColPref(pref) {
  let version = 0;
  try {
    version = Number(localStorage.getItem(ROS_COLS_VERSION_KEY) || "0") || 0;
  } catch (_) {
    return pref;
  }
  if (version >= ROS_COLS_VERSION) return pref;
  let next = pref;
  if (version < 2 && next && next.length && next.indexOf("msg") < 0) {
    next = rosInsertNewCols(next);
  }
  if (version < 3 && next && next.length && next.indexOf("country") < 0) {
    next = rosInsertCountry(next);
  }
  if (next !== pref) rosSaveColPref(next);
  try { localStorage.setItem(ROS_COLS_VERSION_KEY, String(ROS_COLS_VERSION)); }
  catch (_) {}
  return next;
}

function rosLoadColPref() {
  let pref = null;
  try {
    const raw = localStorage.getItem(ROS_COLS_KEY);
    if (!raw) return rosMigrateColPref(null);
    const arr = JSON.parse(raw);
    pref = Array.isArray(arr) ? arr : null;
  } catch (_) {
    return null;
  }
  return rosMigrateColPref(pref);
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
    } else if (col.hint) {
      lab.title = col.hint;
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
    const hint = col.hint ? ` title="${escAttr(col.hint)}"` : "";
    return `<th data-key="${col.key}" class="${col.cls}${active?' sort':''}"${hint}>${col.label}${arrow}</th>`;
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
    lab.appendChild(document.createTextNode(fmtBand(b)));
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

// Show menu. Same rule as wims.engine.roster_filter, on the Message-column
// fields (is_cq and the exchange tail). Not a second decode parser.
// A saved checked checkbox (true / "1") is Needed; unchecked (false / "0") is All.
function rosNormalizeNeed(saved) {
  if (saved == null || saved === "") return "needed";
  const s = String(saved).trim().toLowerCase();
  if (s === "needed" || s === "needed-cq" || s === "needed-73" || s === "all") return s;
  if (s === "true" || s === "1" || s === "yes" || s === "on" || s === "checked") return "needed";
  if (s === "false" || s === "0" || s === "no" || s === "off" || s === "unchecked") return "all";
  return "needed";
}

function rosExchangeTail(c) {
  return String(c.msg != null && c.msg !== "" ? c.msg : (c.message_tail || "")).trim();
}

function rosTailIsFreeSignoff(tail) {
  const parts = String(tail || "").trim().toUpperCase().split(/\s+/);
  for (let i = 0; i < parts.length; i++) {
    if (parts[i] === "73" || parts[i] === "RR73") return true;
  }
  return false;
}

function rosKeepCandidate(c, mode) {
  const m = rosNormalizeNeed(mode);
  if (m === "all") return true;
  if (!c || !c.is_needed) return false;
  if (m === "needed") return true;
  if (m === "needed-cq") return !!c.is_cq;
  if (m === "needed-73") return !!c.is_cq || rosTailIsFreeSignoff(rosExchangeTail(c));
  return true;
}

function rosSaveNeed(mode) {
  try { localStorage.setItem(ROS_NEED_KEY, rosNormalizeNeed(mode)); }
  catch (_) {}
}

function rosLoadNeed() {
  try {
    const raw = localStorage.getItem(ROS_NEED_KEY);
    const mode = rosNormalizeNeed(raw);
    if (raw != null && String(raw) !== mode) rosSaveNeed(mode);
    return mode;
  } catch (_) {
    return "needed";
  }
}

function rosNeedButtons() {
  const menu = $("ros-needed");
  if (!menu) return [];
  return [...menu.querySelectorAll('button[role="option"]')];
}

function rosSetNeed(mode, save) {
  const menu = $("ros-needed");
  const btn = $("ros-needed-btn");
  if (!menu) return;
  const m = rosNormalizeNeed(mode);
  const opts = rosNeedButtons();
  let pick = null;
  for (const o of opts) {
    if (o.dataset.value === m) pick = o;
  }
  if (!pick && opts.length) pick = opts[0];
  if (!pick) return;
  menu.dataset.value = pick.dataset.value;
  for (const o of opts) {
    o.setAttribute("aria-selected", o === pick ? "true" : "false");
  }
  if (btn) {
    btn.textContent = pick.textContent;
    btn.title = pick.title || "";
  }
  if (save) rosSaveNeed(menu.dataset.value);
}

function rosCloseNeed() {
  const menu = $("ros-needed");
  const btn = $("ros-needed-btn");
  if (menu) menu.hidden = true;
  if (btn) btn.setAttribute("aria-expanded", "false");
}

function rosOpenNeed() {
  const menu = $("ros-needed");
  const btn = $("ros-needed-btn");
  if (!menu || !btn) return;
  const cols = document.querySelector("details.ros-cols-menu");
  if (cols) cols.open = false;
  menu.hidden = false;
  btn.setAttribute("aria-expanded", "true");
}

function rosToggleNeed() {
  const menu = $("ros-needed");
  if (!menu) return;
  if (menu.hidden) rosOpenNeed();
  else rosCloseNeed();
}

function rosSyncNeedControl() {
  const menu = $("ros-needed");
  const btn = $("ros-needed-btn");
  if (!menu || !btn || menu.dataset.wired) return;
  menu.dataset.wired = "1";
  rosSetNeed(rosLoadNeed(), false);
  btn.addEventListener("click", () => rosToggleNeed());
  for (const o of rosNeedButtons()) {
    o.addEventListener("click", () => {
      rosSetNeed(o.dataset.value, true);
      rosCloseNeed();
      rosDraw();
    });
  }
  document.addEventListener("click", (e) => {
    const wrap = $("ros-needed-wrap");
    if (!menu.hidden && wrap && !wrap.contains(e.target)) rosCloseNeed();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") rosCloseNeed();
  });
}

function rosNeedMode() {
  const menu = $("ros-needed");
  if (!menu) return "all";
  return rosNormalizeNeed(menu.dataset.value || "needed");
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
  rosSyncNeedControl();
  rosSyncMaxAgeControl();
  applyOperateShotContext();
  // Ctrl+/- zoom and window resize: remeasure column widths.
  window.addEventListener("resize", rosFitColumnsSoon);
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", rosFitColumnsSoon);
  }
  // Native <details> only toggles on the summary. Dismiss on any click
  // outside the menu (checkboxes inside stay usable).
  document.addEventListener("click", (e) => {
    const menu = document.querySelector("details.ros-cols-menu");
    if (!menu || !menu.open) return;
    if (menu.contains(e.target)) return;
    menu.open = false;
  });
}

/** URL query context for docs screenshots, e.g. /?needed=1&bands=144&maxAge=60 */
function applyOperateShotContext() {
  if (!$("ros-needed") && !$("ros-max-age") && !$("ros-cols")) return;
  let q;
  try { q = new URLSearchParams(location.search || ""); }
  catch (_) { return; }
  if (![...q.keys()].length) return;
  if (q.has("needed")) {
    // needed=1 is the old checked box (Needed). needed=0 is the old unchecked box (All).
    rosSetNeed(q.get("needed"), false);
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

let _rosOffered = []; // live WSJT-X bands (or instance ids until Status)

function operateOfferedBands(s) {
  // Heartbeat-alive instances — not decode traffic. Status dial gives the
  // band; Heartbeat has no frequency, so idle radios fall back to UDP id.
  const inst = (s.instances || []).filter(n => (n.health || "") !== "DEAD");
  const order = (s.bands || []).map(b => b.band);
  const out = [];
  const seen = new Set();
  const add = (x) => {
    if (!x || seen.has(x)) return;
    seen.add(x);
    out.push(x);
  };
  for (const n of inst) {
    if (n.band && n.band !== "?") add(n.band);
  }
  const live = s.roster && s.roster.live_bands;
  if (Array.isArray(live)) live.forEach(add);
  out.sort((a, b) => {
    const ia = order.indexOf(a), ib = order.indexOf(b);
    if (ia >= 0 || ib >= 0) return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib);
    return a < b ? -1 : a > b ? 1 : 0;
  });
  for (const n of inst) {
    if (!n.band || n.band === "?") add(n.id);
  }
  return out;
}

function rosDraw() {
  const r = _rosData; if (!r) return;
  rosSyncMaxAgeControl();
  rosSyncNeedControl();
  const bands = _rosOffered.length
    ? _rosOffered
    : (Array.isArray(r.live_bands)
      ? r.live_bands.filter(Boolean)
      : [...new Set((r.candidates || []).map(c => c.band).filter(Boolean))].sort());
  rosSyncBandChecks(bands);
  const selected = rosSelectedBands();
  const needMode = rosNeedMode();
  const maxAge = rosMaxAgeSec();
  let rows = r.candidates.filter(c => {
    if (!rosKeepCandidate(c, needMode)) return false;
    if (selected && selected.size) {
      const hitBand = c.band && c.band !== "?" && selected.has(c.band);
      const hitInst = c.instance && selected.has(c.instance);
      const unknown = !c.band || c.band === "?";
      // Unknown-band lines stay visible until Status fills dial/band.
      if (!hitBand && !hitInst && !unknown) return false;
    }
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
  const canWorkBase = !!( _txState && _txState.can_tx );
  for (const c of rows) {
    const tr = document.createElement("tr");
    // Highlight priority: calling-us (red) > armed (green) > mult (soft green) > dupe dim.
    const classes = [];
    if (c.is_calling_us) classes.push("calling-us");
    else if (c.is_armed) classes.push("armed");
    else if (c.is_new_mult) classes.push("mult");
    if (!c.is_needed) classes.push("dupe");
    const rowCanWork = canWorkBase && (c.tx_capable !== false);
    if (rowCanWork) classes.push("workable");
    if (c.tx_capable === false) classes.push("decode-only");
    tr.className = classes.join(" ");
    if (c.id) tr.dataset.row = c.id;
    if (rowCanWork) {
      let tip = "Click to work " + (c.call || "") + " via " + (c.instance || "?");
      if (c.is_calling_us) tip = "Calling us — " + tip;
      else if (c.is_armed) tip = "Enable Tx set for this DX — " + tip;
      tr.title = tip;
    } else     if (c.tx_capable === false) {
      tr.title = (c.instance || "instance") + " is decode-only — Work denied (H2 mark)";
    }
    if (c.need_reason) {
      tr.title = (tr.title ? tr.title + " — " : "") + c.need_reason;
    }
    if (c.mult_reason && c.mult_reason !== c.need_reason) {
      tr.title = (tr.title ? tr.title + " — " : "") + c.mult_reason;
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
      if (!j.halted.length) {
        m.textContent = j.detail || "nothing to halt from this console";
      } else {
        const bands = fmtBands((j.bands || []).filter(Boolean), "+");
        m.textContent = bands ? `halted ${bands}` : `halted ${j.halted.length}`;
      }
    } else {
      m.textContent = "ok";
    }
  } else {
    m.className = "meta warn";
    const err = j.error || "failed";
    const errKey = String(err).startsWith("send_failed") ? "send_failed" : err;
    const hint = {
      tx_disabled: "Server is --no-tx (read-only)",
      unknown_row: "Row gone — wait for a new decode",
      group_busy: "Another radio holds TX — Halt first",
      other_dashboard: "Started from another console",
      no_control_port: "No UDP control port for that WSJT-X yet",
      send_failed: "UDP send failed (Windows 22 = bad dest; wait for Status)",
      decode_only: "That instance is decode-only (H2 mark) — Work the TX instance",
    }[errKey];
    const isHalt = url && String(url).indexOf("/halt") >= 0;
    m.textContent = (isHalt ? "Halt failed: " : "Work failed: ")
      + (j.detail || hint || err);
    // Display only: a refused Work is a conflict the Operate page must show
    // even before the next live snapshot lists the holder.
    if (!isHalt && err === "group_busy") {
      _ilRefused = {holder: j.holder || "", misses: 0, seen: false};
      if (_ilLast) renderInterlock(_ilLast, _txState, true);
    }
  }
}

function txWire() {
  if (_txWired) return;
  _txWired = true;
  const halt = $("tx-halt");
  if (halt) halt.addEventListener("click", () =>
    txPost("/api/tx/halt", {dashboard_id: dashboardId()}));
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
    if (tr && tr.classList.contains("decode-only")) return;
    if (tr && tr.dataset.row) {
      txPost("/api/tx/work", {row_id: tr.dataset.row, dashboard_id: dashboardId()});
    }
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
  if (halt) {
    halt.disabled = false;           // always available; no-op if this console started none
    const bands = myTxBands(_txState);
    const shown = fmtBands(bands, "+");
    halt.textContent = bands.length ? ("◼ Halt " + shown) : "◼ Halt TX";
    halt.title = bands.length
      ? ("Stop this console’s Work on " + fmtBands(bands, " + ")
         + ". Other operators are not halted. Two bands → both stop.")
      : "Stop QSOs this console started. Does not halt other operators or local WSJT-X CQ.";
  }
}

// -- dispatch + connect ----------------------------------------------------- //

function render(s) {
  renderHeader(s);
  renderSystem(s);
  renderBandInventory(s);
  renderAgents(s);
  renderTxBar(s.tx);                          // before roster: rosWork() reads can_tx
  renderRotators(s.rotators);
  renderInterlock(s.interlock, s.tx);
  _rosOffered = operateOfferedBands(s);
  renderRoster(s.roster);
  renderInstances(s);
  renderActivity(s.activity);
  renderDecodes(s.decodes);                   // no-op unless #dlog-body exists
  renderSync(s.n1mm_sync);
  renderLoggers(s);
  renderSetupExtras(s.n1mm_sync, s);
  renderContestRules(s);
  renderN1mmNav(s);
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
  wireTipButtons();
  wireLogPage();
  const tab = statusTabFromPath();
  if (tab) statusShowTab(tab);
  markNavActive();
  rosSyncNeedControl();
  const es = new EventSource("/events");
  es.onopen = () => { $("conn").textContent = "● live"; $("conn").className = "up"; };
  es.onmessage = (e) => render(JSON.parse(e.data));
  es.onerror = () => { $("conn").textContent = "● disconnected"; $("conn").className = "down"; };
}
connect();
