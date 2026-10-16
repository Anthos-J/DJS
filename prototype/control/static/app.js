// MANDATE console: plain JS, polling the control-plane API. No build step.
const $ = s => document.querySelector(s);
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let TOKEN = "";
try { TOKEN = sessionStorage.getItem("mandate-token") || ""; } catch (e) {}
$("#token").value = TOKEN;
$("#token").addEventListener("change", e => { TOKEN = e.target.value; try { sessionStorage.setItem("mandate-token", TOKEN); } catch (x) {} refresh(); });
async function api(path, opts = {}) {
  const r = await fetch(path, {...opts, headers: {"Content-Type": "application/json", "X-Owner-Token": TOKEN, ...(opts.headers || {})}});
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.status);
  return j;
}
const ts = t => t ? new Date(t * 1000).toLocaleTimeString() : "";
const chip = (t, cls = "") => `<span class="chip ${esc(cls)}">${esc(t)}</span>`;
function factorsHtml(fs) {
  if (!fs || !fs.length) return `<div class="mute">no risk factors</div>`;
  return `<ul class="factors">${fs.map(f => `<li><span class="p">+${f.points}</span><b>${esc(f.factor)}</b><span class="mute">${esc(f.evidence)}</span></li>`).join("")}</ul>`;
}
document.querySelectorAll("#tabs button").forEach(b => b.onclick = () => {
  document.querySelectorAll("#tabs button").forEach(x => x.classList.toggle("on", x === b));
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("on", t.id === b.dataset.tab)); refresh();
});
function confirmAction(title, body) {
  return new Promise(res => {
    $("#dlgtitle").textContent = title; $("#dlgbody").innerHTML = body; $("#dlgreason").value = "";
    const d = $("#dlg"); d.showModal();
    d.onclose = () => res(d.returnValue === "ok" ? $("#dlgreason").value.trim() : null);
  });
}
async function setStatus(aid, status) {
  const reason = await confirmAction(`${status === "active" ? "Resume" : status[0].toUpperCase() + status.slice(1)} ${aid}?`,
    `<p class="mute">${status === "quarantined" ? "All actions by this agent will be denied at the PEP, and its delegations suspended." :
      status === "restricted" ? "Reads continue; every consequential action needs owner approval." : "The agent returns to normal enforcement. The drift accumulator resets."}</p>`);
  if (!reason) return;
  await api(`/api/agents/${encodeURIComponent(aid)}/status`, {method: "POST", body: JSON.stringify({status, reason})}); refresh();
}
async function resolve(id, approve) {
  await api(`/api/approvals/${id}`, {method: "POST", body: JSON.stringify({approve, note: approve ? "approved in console" : "rejected in console"})}); refresh();
}
window.setStatus = setStatus; window.resolveAp = resolve;

function alertCard(a) {
  return `<div class="card"><div class="h"><span class="score ${esc(a.severity)}">${a.risk_score}</span>${chip(a.severity, a.severity)}${chip(a.response, a.response)}
  <b class="mono">${esc(a.agent_id)}</b><span class="mono">${esc(a.tool)}</span><span class="mute">${ts(a.ts)}</span>${chip("confidence: " + a.confidence)}</div>
  <div>${esc(a.reason)}</div>${factorsHtml(a.factors)}
  ${a.expected_authority ? `<div class="mute" style="margin-top:6px">Expected authority: role <b>${esc(a.expected_authority.role)}</b>, task <b>${esc(a.expected_authority.task)}</b>,
  task tools ${esc((a.expected_authority.task_tools || []).join(", "))}, max sensitivity ${a.expected_authority.max_sensitivity}, destinations ${esc((a.expected_authority.destinations || []).join(", "))}</div>` : ""}</div>`;
}
async function refresh() {
  try {
    const m = await fetch("/api/meta").then(r => r.json());
    $("#meta").innerHTML = `engine ${esc(m.engine_config)} · Cedar ${m.cedar ? "loaded" : "<b class='DENY'>missing (fail closed)</b>"} · baseline: ${esc(m.baseline_source || "none loaded")}`;
    if (!TOKEN) { $("#kpis").innerHTML = `<div class="empty">Enter the owner token to load data.</div>`; return; }
    const [agents, alerts, aps, evs] = await Promise.all([api("/api/agents"), api("/api/alerts"), api("/api/approvals"), api("/api/events?limit=400")]);
    const pend = aps.filter(a => a.status === "pending"); $("#apcount").textContent = pend.length || "";
    const by = r => evs.filter(e => e.response === r).length;
    $("#kpis").innerHTML = [["Agents", agents.length], ["Quarantined", agents.filter(a => a.status === "quarantined").length], ["Restricted", agents.filter(a => a.status === "restricted").length],
      ["Decisions", evs.length], ["Allowed", by("ALLOW")], ["Approval required", by("APPROVAL_REQUIRED")], ["Denied", by("DENY")], ["Open alerts", alerts.filter(a => a.status === "open").length]]
      .map(([l, v]) => `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`).join("");
    $("#ov-alerts").innerHTML = alerts.slice(0, 5).map(alertCard).join("") || `<div class="empty">No alerts.</div>`;
    $("#agent-table").innerHTML = `<table><tr><th>Agent identity</th><th>Role / mandate</th><th>Task</th><th>Status</th><th>History</th><th>Drift</th><th>Alerts</th><th>Actions</th></tr>${agents.map(a => `<tr>
      <td class="mono">${esc(a.agent_id)}<div class="mute">owner ${esc(a.owner)}</div></td><td><b>${esc(a.role)}</b><div class="mute">${esc(a.mandate.description)}</div><div>${a.mandate.tools.map(t => chip(t)).join("")}</div></td>
      <td>${esc(a.task || "—")}<div class="mute">${esc(a.task_instruction || "")}</div></td><td class="${esc(a.status)}"><b>${esc(a.status)}</b></td>
      <td>${a.history_n} events ${a.cold_start ? chip("cold start: role prior", "MEDIUM") : ""}</td><td>JS ${a.drift_js}<div class="bar" title="accumulator"><i style="width:${Math.min(100, a.accumulator / 1.2)}%"></i></div></td>
      <td>${a.open_alerts}</td><td>${a.status !== "quarantined" ? `<button class="act bad" onclick="setStatus('${esc(a.agent_id)}','quarantined')">Quarantine</button>` : ""}
      ${a.status === "active" ? `<button class="act" onclick="setStatus('${esc(a.agent_id)}','restricted')">Restrict</button>` : ""}
      ${a.status !== "active" ? `<button class="act ok" onclick="setStatus('${esc(a.agent_id)}','active')">Resume</button>` : ""}</td></tr>`).join("")}</table>`;
    const sel = $("#tl-agent"), cur = sel.value; sel.innerHTML = `<option value="">all</option>` + agents.map(a => `<option ${a.agent_id === cur ? "selected" : ""}>${esc(a.agent_id)}</option>`).join("");
    const tl = evs.filter(e => !cur || e.agent_id === cur).slice().reverse();
    $("#tl").innerHTML = `<table><tr><th>Time</th><th>Agent</th><th>Action</th><th>Destination</th><th>Delegation</th><th>Response</th><th>Risk</th><th>Reason</th></tr>${tl.map(e => `<tr>
      <td>${ts(e.ts)}</td><td class="mono">${esc(e.agent_id)}</td><td class="mono">${esc(e.tool)} <span class="mute">${esc(JSON.stringify(e.args || {}))}</span></td><td class="mono">${esc(e.destination || "")}</td>
      <td class="mono">${e.delegation ? esc(e.delegation.chain.join(" → ") + " → " + e.agent_id) : ""}</td><td class="${esc(e.response)}"><b>${esc(e.response)}</b></td>
      <td class="${esc(e.risk_band)}">${e.risk_score ?? ""}</td><td>${esc(e.reason)}</td></tr>`).join("")}</table>`;
    $("#alert-list").innerHTML = alerts.map(alertCard).join("") || `<div class="empty">No alerts.</div>`;
    $("#ap-list").innerHTML = aps.map(a => `<div class="card"><div class="h"><span class="score">${a.risk_score}</span>${chip(a.status, a.status)}<b class="mono">${esc(a.agent_id)}</b>
      <span class="mono">${esc(a.tool)} ${esc(JSON.stringify(a.args))}</span><span class="mute">${ts(a.created)}</span>
      ${a.status === "pending" ? `<button class="act ok" onclick="resolveAp('${a.id}',true)">Approve once</button><button class="act bad" onclick="resolveAp('${a.id}',false)">Reject</button>` : ""}</div>
      <div>${esc(a.reason)}</div>${factorsHtml(a.factors)}<div class="mute">An approval allows exactly one retry of this exact action by this agent.</div></div>`).join("") || `<div class="empty">No approval requests.</div>`;
    if (document.querySelector("#delegation.on")) {
      const dl = await api("/api/delegations");
      $("#dl").innerHTML = dl.length ? `<table><tr><th>Delegation</th><th>Responsibility chain</th><th>Child</th><th>Attenuated scopes</th><th>Status</th></tr>${dl.map(d => `<tr>
        <td class="mono">${esc(d.id)}</td><td class="mono">${esc(d.root)} → ${esc(d.chain.join(" → "))}</td><td class="mono">${esc(d.child)}</td><td>${d.scopes.map(s => chip(s)).join("")}</td>
        <td class="${d.status === "active" ? "active" : "quarantined"}">${esc(d.status)}</td></tr>`).join("")}</table>` : `<div class="empty">No delegations.</div>`;
    }
    const bsel = $("#bl-agent"), bcur = bsel.value || (agents[0] && agents[0].agent_id);
    bsel.innerHTML = agents.map(a => `<option ${a.agent_id === bcur ? "selected" : ""}>${esc(a.agent_id)}</option>`).join("");
    if (document.querySelector("#baselines.on") && bcur) {
      const b = await api(`/api/agents/${encodeURIComponent(bcur)}/baseline`);
      const tools = [...new Set([...Object.keys(b.baseline_tools), ...Object.keys(b.recent_tools)])];
      $("#bl").innerHTML = `<div class="grid2"><div class="card"><b>${esc(b.agent)}</b> · ${esc(b.role)} · ${b.history_n} events ${b.cold_start ? chip("cold start: assessed against role prior (low confidence)", "MEDIUM") : ""}
        <h3>Tool mix: baseline vs recent window</h3><table><tr><th>Tool</th><th>Baseline</th><th>Recent</th></tr>${tools.map(t => `<tr><td class="mono">${esc(t)}</td>
        <td><div class="bar"><i style="width:${(b.baseline_tools[t] || 0) * 100}%"></i></div></td><td><div class="bar"><i style="width:${(b.recent_tools[t] || 0) * 100}%;background:var(--warn)"></i></div></td></tr>`).join("")}</table></div>
        <div class="card"><h3>Drift indicators</h3><div>Jensen-Shannon divergence (recent vs frozen reference): <b>${b.drift_js}</b> <span class="mute">(flag at 0.25)</span></div>
        <div style="margin-top:8px">Drift accumulator: <b>${b.accumulator}</b> / ${b.quarantine_threshold} <span class="mute">(automatic quarantine at threshold)</span></div>
        <div class="bar" style="margin-top:6px"><i style="width:${Math.min(100, 100 * b.accumulator / b.quarantine_threshold)}%;background:var(--bad)"></i></div></div></div>`;
    }
    if (document.querySelector("#evaluation.on")) {
      const ev = await api("/api/eval"); let h = "";
      if (ev.heldout) { const s = ev.heldout.data; h += `<div class="card"><h3>Held-out evaluation (engine ${esc(s.inputs_sha256 ? "E1" : "")}, seeds ${esc(s.seeds.join(","))})</h3>
        <div class="kpis">${[["Attack scenarios", s.attack_scenarios], ["Prevented", s.attacks_prevented], ["…by deny", s.attacks_blocked_by_deny], ["…by approval gate only", s.attacks_only_approval_gated],
          ["Benign scenarios", s.benign_scenarios], ["Benign completed", s.benign_completed_without_intervention], ["Benign approvals", s.benign_actions_needing_approval],
          ["Benign denials", s.benign_actions_denied], ["FP alert rate / action", s.false_positive_alert_rate_per_benign_action]].map(([l, v]) => `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`).join("")}</div>
        <p class="mute">${esc(s.LABEL)}. Source: ${esc(ev.heldout.file)}</p></div>`; }
      if (ev.redteam) { h += `<div class="card"><h3>Post-freeze adaptive red team</h3><table><tr><th>Attack</th><th>Outcome</th></tr>${ev.redteam.data.map(r => `<tr><td>${esc(r.id)}</td>
        <td class="${r.harmful_executed ? "DENY" : "ALLOW"}"><b>${esc(r.outcome)}</b> (${r.harmful_executed}/${r.harmful_actions})</td></tr>`).join("")}</table></div>`; }
      if (ev.e2e) { h += `<div class="card"><h3>End-to-end through the real PEP</h3><pre class="mono">${esc(JSON.stringify(ev.e2e.data, null, 1)).slice(0, 4000)}</pre></div>`; }
      $("#ev").innerHTML = h || `<div class="empty">No evaluation results found.</div>`;
    }
    if (document.querySelector("#audit.on")) {
      const au = await api("/api/audit?limit=150");
      $("#au").innerHTML = `<div class="card">Hash chain: ${au.verify.ok ? `<b class="ALLOW">intact</b> (${au.verify.records} records, head ${esc(au.verify.head.slice(0, 16))}…)` : `<b class="DENY">BROKEN at ${au.verify.broken_at}</b>`}</div>
        <table><tr><th>#</th><th>Time</th><th>Kind</th><th>Detail</th><th>Hash</th></tr>${au.records.slice().reverse().map(r => `<tr><td>${r.seq}</td><td>${ts(r.t)}</td><td>${esc(r.entry.kind)}</td>
        <td class="mono">${esc(JSON.stringify(r.entry).slice(0, 220))}</td><td class="mono">${esc(r.hash.slice(0, 12))}</td></tr>`).join("")}</table>`;
    }
  } catch (e) { $("#meta").textContent = "error: " + e.message; }
}
refresh(); setInterval(refresh, 2500);
