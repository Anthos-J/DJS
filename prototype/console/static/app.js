// MANDATE judge console. Plain JS, no build step. Every value shown comes from a live server response:
// /api/* is the real control plane (proxied by the console), /console/* is the host-side orchestrator.
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ts = t => (t ? new Date(t * 1000).toLocaleString() : "—");
const pill = (t, cls = "muted") => `<span class="pill ${cls}">${esc(t)}</span>`;
const RESP = { ALLOW: "ok", DENY: "bad", APPROVAL_REQUIRED: "warn" };
const STATUS = { active: "ok", restricted: "warn", quarantined: "bad" };
const ROLES = ["procurement", "hr_assistant", "research", "devops"];   // role catalogue (config/roles_e421.json); the server validates
let TOKEN = ""; try { TOKEN = sessionStorage.getItem("mandate-token") || ""; } catch (e) { /* storage unavailable */ }
const S = { health: null, meta: null, agents: [], approvals: [], route: "overview", timer: null, busy: false, lastRun: null, sel: null };

class ApiError extends Error { constructor(msg, status, body) { super(msg); this.status = status; this.body = body; } }
async function http(path, opts = {}) {
  const r = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", "X-Owner-Token": TOKEN, ...(opts.headers || {}) } });
  let j = {}; try { j = await r.json(); } catch (e) { /* non-JSON */ }
  if (!r.ok) throw new ApiError(j.error || `HTTP ${r.status}`, r.status, j);
  return j;
}
const api = (p, body) => http(p, body === undefined ? {} : { method: "POST", body: JSON.stringify(body) });
const consoleAction = (p, body) => http(p, { method: "POST", body: JSON.stringify(body || {}), headers: { "X-Console-Action": "1" } });

function errBox(e, what) {
  const unreachable = e.status === 503;
  return `<div class="empty">${unreachable ? "<b>Control plane unreachable.</b> " : ""}${esc(what)} failed: ${esc(e.message)}${
    e.status === 401 ? "<br>Enter the owner token at the top right." : unreachable ? "<br>See <a href=\"#/diagnostics\">Diagnostics</a> or <a href=\"#/recovery\">Recovery</a>." : ""}</div>`;
}
const loading = t => `<div class="loading">${esc(t || "Loading…")}</div>`;
const empty = t => `<div class="empty">${esc(t)}</div>`;

function factorsHtml(fs) {
  if (!fs || !fs.length) return `<div class="faint">No risk factors recorded.</div>`;
  return `<ul class="factors">${fs.map(f => `<li><span class="p">+${esc(f.points)}</span><b>${esc(f.factor)}</b><span class="mute">${esc(f.evidence)}</span></li>`).join("")}</ul>`;
}

// ---------------------------------------------------------------- dialog
function ask(title, body, { reason = true, ok = "Confirm", danger = false } = {}) {
  return new Promise(res => {
    $("#dlgtitle").textContent = title; $("#dlgbody").innerHTML = body; $("#dlgreason").value = ""; $("#dlgerr").textContent = "";
    $("#dlgreasonwrap").hidden = !reason; $("#dlgok").textContent = ok; $("#dlgok").className = danger ? "danger" : "primary";
    const d = $("#dlg"); let settled = false;
    const finish = v => { if (settled) return; settled = true; if (d.open) d.close(); res(v); };   // resolve from the buttons, not the async 'close' event
    $("#dlgok").onclick = ev => {
      ev.preventDefault();
      if (reason && !$("#dlgreason").value.trim()) { $("#dlgerr").textContent = "A reason is required."; return; }
      finish($("#dlgreason").value.trim() || true);
    };
    $("#dlgform").querySelector('button[value="cancel"]').onclick = ev => { ev.preventDefault(); finish(null); };
    d.oncancel = ev => { ev.preventDefault(); finish(null); };
    d.onclose = () => finish(null);
    d.showModal();
  });
}

// ---------------------------------------------------------------- header status (from /console/health, never hardcoded)
async function refreshStatus() {
  try { S.health = await http("/console/health"); } catch (e) { S.health = null; }
  const h = S.health, m = h && h.control.meta; S.meta = m;
  const parts = [];
  if (!h) parts.push(pill("console unreachable", "bad"));
  else {
    parts.push(h.control.reachable ? pill("control plane up", "ok") : pill("control plane DOWN", "bad"));
    if (m) parts.push(pill(`engine ${m.engine}`, h.engine_ok ? "ok" : "bad"));
    if (m && m.recovery) parts.push(pill("RECOVERY MODE", "warn"));
    if (m) parts.push(pill(m.audit.ok ? "audit chain OK" : "audit chain BROKEN", m.audit.ok ? "ok" : "bad"));
    if (m) parts.push(pill(m.persistence.state_dir ? (m.persistence.anchor ? "state persisted + anchor" : "state persisted") : "state in memory", m.persistence.state_dir ? "info" : "warn"));
  }
  $("#status").innerHTML = parts.join("");
  $("#tokwrap").hidden = !!(h && h.console_demo_token);
  const b = $("#banner");
  if (h && !h.control.reachable) { b.hidden = false; b.innerHTML = `<b>Control plane unreachable</b> (${esc(h.control.error || "")}). The PEP fails closed: protected actions are denied. Use <a href="#/recovery">Recovery</a> or <a href="#/diagnostics">Diagnostics</a>.`; }
  else if (h && h.engine_ok === false) { b.hidden = false; b.innerHTML = `<b>Wrong engine:</b> running ${esc(m.engine)}, the submission demo requires ${esc(h.engine_required)}. Restart with <span class="mono">demo/launch.sh</span>.`; }
  else b.hidden = true;
  if (m) $("#nav-ap").textContent = m.counts.pending_approvals || "";
}

// ---------------------------------------------------------------- routing
const VIEWS = {};
const TITLES = { overview: "Security overview", demo: "Live scenarios", llm: "Live LLM agent (optional)", agents: "Agents & authority", approvals: "Approval center", investigate: "Threat & incident investigation",
  audit: "Audit explorer", recovery: "Owner recovery", results: "Evaluation results", diagnostics: "System diagnostics" };
async function route() {
  const r = (location.hash.replace(/^#\//, "").split("?")[0]) || "overview";
  S.route = VIEWS[r] ? r : "overview";
  document.querySelectorAll("#nav a").forEach(a => a.classList.toggle("on", a.dataset.r === S.route));
  $("#title").textContent = TITLES[S.route];
  await refreshStatus();
  await VIEWS[S.route]($("#view"));
}
window.addEventListener("hashchange", route);
$("#token").addEventListener("change", e => { TOKEN = e.target.value; try { sessionStorage.setItem("mandate-token", TOKEN); } catch (x) { /* ignore */ } route(); });
$("#token").value = TOKEN;
function poll(fn, ms = 5000) { clearInterval(S.timer); S.timer = setInterval(() => { if (!S.busy && !document.querySelector("dialog[open]")) fn(); }, ms); }

// ---------------------------------------------------------------- 1. overview
VIEWS.overview = async el => {
  el.innerHTML = loading("Loading live state…");
  const draw = async () => {
    await refreshStatus();
    const m = S.meta;
    let ev = [], al = [], res = null, err = null;
    try { [ev, al] = await Promise.all([api("/api/events?limit=12"), api("/api/alerts")]); } catch (e) { err = e; }
    try { res = await http("/console/results"); } catch (e) { /* results optional */ }
    const fin = res && res.comparison.find(c => c.engine.startsWith("E4.2.1"));
    const k = (l, v, s, cls = "") => `<div class="card kpi"><div class="l">${esc(l)}</div><div class="v ${cls}">${v}</div><div class="s">${s || ""}</div></div>`;
    el.innerHTML = `
      <div class="grid g4">
        ${k("Control plane", m ? `<span class="pill ok">up</span>` : `<span class="pill bad">down</span>`, m ? `engine ${esc(m.engine)} · config ${esc(m.engine_config)} · Cedar ${m.cedar ? "on" : "off"}` : "PEP fails closed while down")}
        ${k("Agents", m ? m.counts.agents : "—", m ? `${m.counts.quarantined} quarantined` : "")}
        ${k("Pending approvals", m ? m.counts.pending_approvals : "—", `<a href="#/approvals">Open approval center</a>`)}
        ${k("Audit", m ? (m.audit.ok ? "chain OK" : "BROKEN") : "—", m ? `${m.audit.records} hash-chained records${m.recovery ? " · recovery mode" : ""}` : "", m && !m.audit.ok ? "bad" : "")}
      </div>
      ${m ? `<p class="faint">Runtime: decisions ${m.counts.decisions}, alerts ${m.counts.alerts}. Persistence: ${m.persistence.state_dir ? "checkpointed state" : "in-memory"}${m.persistence.anchor ? " + separate anchor" : ""}${m.persistence.signed ? " (signed)" : " (unsigned demo checkpoint)"}. Baseline: ${esc(m.baseline_source || "none loaded")}.</p>` : ""}
      ${err ? errBox(err, "Loading live decisions") : `
      <div class="grid g2" style="margin-top:14px">
        <div class="card"><h3>Recent policy decisions</h3>${ev.length ? `<div class="tbl"><table><tr><th>Time</th><th>Agent</th><th>Tool</th><th>Decision</th><th>Control</th></tr>
          ${ev.slice().reverse().map(e => `<tr class="click" onclick="location.hash='#/investigate?d=${esc(e.decision_id)}'"><td class="faint">${ts(e.ts)}</td><td class="mono">${esc(e.agent_id)}</td><td>${esc(e.tool)}</td><td>${pill(e.response, RESP[e.response])}</td><td class="mute">${esc(e.control)}</td></tr>`).join("")}</table></div>` : empty("No decisions yet. Run a live scenario.")}</div>
        <div class="card"><h3>Recent alerts</h3>${al.length ? `<div class="tbl"><table><tr><th>Time</th><th>Agent</th><th>Tool</th><th>Score</th><th>Response</th></tr>
          ${al.slice(0, 8).map(a => `<tr class="click" onclick="location.hash='#/investigate?d=${esc(a.decision_id)}'"><td class="faint">${ts(a.ts)}</td><td class="mono">${esc(a.agent_id)}</td><td>${esc(a.tool)}${a.aggregated_count ? ` <span class="faint">×${a.aggregated_count}</span>` : ""}</td><td class="mono">${esc(a.risk_score)}</td><td>${pill(a.response, RESP[a.response])}</td></tr>`).join("")}</table></div>` : empty("No alerts.")}
          <p class="faint">An alert is a detection record. Whether an effect was prevented is shown by the decision (DENY / APPROVAL_REQUIRED) and verified at the tool server in Live scenarios.</p></div>
      </div>`}
      ${fin ? `<h2>Recorded evaluation (final engine E4.2.1, ${esc(fin.seeds)})</h2>
      <div class="grid g4">
        ${k("Attack scenarios", fin.attack_scenarios, "engine-level, AI-generated, scripted agents")}
        ${k("Unmitigated successes", fin.attack_outcomes.SUCCEEDED || 0, "all in family C4 (below-budget reading): documented limitation", "bad")}
        ${k("Legitimate tasks denied", fin.benign_outcomes.DENIED_LEGIT || 0, `of ${fin.benign_scenarios}; ${fin.benign_outcomes.APPROVAL_FRICTION || 0} needed an approval`)}
        ${k("Benign alert rate", fin.benign_alert_rate, `actionable ${fin.benign_actionable_alert_rate} · per ${fin.benign_actions} benign actions`)}
      </div><p class="faint">Not a real-world prevention rate. Details: <a href="#/results">Evaluation results</a>.</p>` : ""}`;
  };
  await draw(); poll(draw);
};

// ---------------------------------------------------------------- 2. live scenarios
VIEWS.demo = async el => {
  clearInterval(S.timer);
  let list = [], runs = [];
  try { [list, runs] = await Promise.all([http("/console/scenarios"), http("/console/runs")]); } catch (e) { el.innerHTML = errBox(e, "Loading scenarios"); return; }
  const last = {}; runs.forEach(r => { if (!last[r.id]) last[r.id] = r; });
  el.innerHTML = `
    <p class="lead">Each scenario drives the <b>real path</b>: a scripted agent in its isolated cell → sidecar (bound credential) → mTLS terminator → PEP → control-plane decision → mock tool server. Outcomes are judged at the tool server's effect log. The agents are scripted (no LLM), and the tools and outbound effects are simulated.</p>
    <div class="row" style="margin:12px 0 4px"><button class="primary" id="runall">Run 1–9 in order</button><button id="reset" class="danger">Reset demo to baseline</button>
      <span class="faint">Reset redeploys the prototype (AM11 static and runtime gates) and reseeds the baseline (about 1 minute). Scenarios 10–12 restart or stop the control plane, in the demo environment only.</span></div>
    <div class="grid g2" style="margin-top:12px">
      <div class="card"><div class="tbl"><table><tr><th>#</th><th>Journey</th><th>Last result</th><th></th></tr>
        ${list.map((s, i) => `<tr><td class="mono">${i + 1}</td><td>${esc(s.title)}${s.destructive ? ` ${pill("restarts control plane", "warn")}` : ""}</td>
          <td>${last[s.id] ? `${pill(last[s.id].verdict, last[s.id].verdict === "PASS" ? "ok" : "bad")} <span class="faint">${ts(last[s.id].finished)}</span>` : `<span class="faint">not run</span>`}</td>
          <td><button class="sm" data-run="${esc(s.id)}">Run</button></td></tr>`).join("")}</table></div></div>
      <div class="card" id="runout">${S.lastRun ? runHtml(S.lastRun) : runs[0] ? runHtml(runs[0]) : empty("Run a scenario to see its steps, the control-plane decisions and the tool-server evidence.")}</div>
    </div>`;
  const run = async id => {
    const s = list.find(x => x.id === id);
    if (s.destructive && !(await ask(`Run "${s.title}"?`, `<p>This restarts or stops the <b>demo</b> control-plane container and, for scenario 11, deletes the audit log inside the demo's Docker volume. Repository evidence is never touched.</p>`, { reason: false, ok: "Run", danger: true }))) return false;
    S.busy = true; $("#runout").innerHTML = loading(`Running: ${s.title} (live)…`);
    el.querySelectorAll("button").forEach(b => b.disabled = true);
    try { S.lastRun = await consoleAction(`/console/scenarios/${id}/run`); } catch (e) { $("#runout").innerHTML = errBox(e, "Scenario"); S.busy = false; return false; }
    S.busy = false; await VIEWS.demo(el); return S.lastRun.verdict === "PASS";
  };
  el.querySelectorAll("[data-run]").forEach(b => b.onclick = () => run(b.dataset.run));
  $("#runall").onclick = async () => { for (const s of list.filter(x => !x.destructive)) { await run(s.id); } };
  $("#reset").onclick = async () => {
    if (!(await ask("Reset the demo?", "<p>Redeploys the prototype from scratch (AM11 static check → up → AM11 runtime check) with engine E4.2.1 and reseeds the declared baseline. Demo state is discarded; repository evidence is not.</p>", { reason: false, ok: "Reset", danger: true }))) return;
    S.busy = true; $("#runout").innerHTML = loading("Redeploying (about 1 minute)…");
    try { const r = await consoleAction("/console/reset"); $("#runout").innerHTML = `<h3>Reset ${pill(r.ok ? "OK" : "FAILED", r.ok ? "ok" : "bad")}</h3><pre>${esc((r.launcher || []).join("\n"))}\nseeded: ${r.seeded}</pre>`; }
    catch (e) { $("#runout").innerHTML = errBox(e, "Reset"); }
    S.busy = false; refreshStatus();
  };
};
function runHtml(r) {
  return `<div class="row"><h3 style="margin:0">${esc(r.title)}</h3><span class="spacer"></span>${pill(r.verdict, r.verdict === "PASS" ? "ok" : "bad")}</div>
    <p class="faint">${ts(r.started)} · ${((r.finished - r.started) || 0).toFixed(1)} s · record saved under <span class="mono">demo/runs/</span></p>
    <h3 style="margin-top:12px">Checks (verified at the real boundary)</h3>
    <ul class="checks">${r.checks.map(c => `<li>${pill(c.ok ? "PASS" : "FAIL", c.ok ? "ok" : "bad")} ${esc(c.what)} <span class="faint mono">${esc(JSON.stringify(c.observed)).slice(0, 160)}</span></li>`).join("")}</ul>
    <h3 style="margin-top:12px">Steps</h3><div class="steps">${r.steps.map(s => `<div class="step ${esc(s.kind)}"><div class="k">${esc(s.kind)}</div><div>${esc(s.what)}</div>
      ${s.pep_results ? `<div class="row" style="margin-top:4px">${s.pep_results.map(p => `${pill(`${p.tool}: ${p.ok ? "executed" : (p.text || "").split(":")[0]}`, p.ok ? "ok" : (String(p.text).startsWith("APPROVAL") ? "warn" : "bad"))}`).join("")}</div>` : ""}
      ${s.tool_calls && s.tool_calls.length ? `<div class="faint">model proposed: ${esc(s.tool_calls.map(c => c.name).join(", "))}</div>` : ""}${s.content ? `<div class="faint">model said: ${esc(s.content.slice(0, 240))}</div>` : ""}${s.answer ? `<div>${esc(s.answer)}</div>` : ""}
      ${s.tool_server_effects ? `<div class="faint">tool-server effects: ${s.tool_server_effects.length ? esc(s.tool_server_effects.map(e => e.tool).join(", ")) : "none"}</div>` : ""}
      ${s.decisions ? `<div class="tbl"><table>${s.decisions.map(d => `<tr><td>${esc(d.tool)}</td><td>${pill(d.response, RESP[d.response])}</td><td class="mute">${esc(d.control)}</td><td class="faint">${esc(d.reason)}</td></tr>`).join("")}</table></div>` : ""}
      <details><summary>raw</summary><pre>${esc(JSON.stringify(s, null, 1))}</pre></details></div>`).join("")}</div>`;
}

// ---------------------------------------------------------------- 2b. optional live LLM agent
VIEWS.llm = async el => {
  clearInterval(S.timer);
  let st; try { st = await http("/console/llm"); } catch (e) { el.innerHTML = errBox(e, "LLM status"); return; }
  el.innerHTML = `
    <div class="note${st.enabled ? "" : " w"}"><b>${st.enabled ? "Live model enabled" : "Live model disabled"}</b>: ${esc(st.provider)} / <span class="mono">${esc(st.model)}</span>.
      ${st.enabled ? "A real model plans the agent's tool calls; every call still passes the real PEP, and the verdict is judged from the tool server's effect log. Model behaviour varies from run to run." :
      `Optional. To enable it, set it in your own terminal: <span class="mono">export GROQ_API_KEY=…</span> and <span class="mono">export MANDATE_LLM_CONSENT=1</span>, then run <span class="mono">bash demo/launch.sh</span>. The key is read from the environment only and is never stored or shown.`}</div>
    <p class="lead">Sent to the provider: the task prompt, the tool list and the mock tool results (demo data). The agent cells stay network-isolated; the model runs on the host.</p>
    <div class="grid g2" style="margin-top:12px">
      <div class="card"><div class="tbl"><table><tr><th>Task</th><th></th></tr>
        ${st.tasks.map(t => `<tr><td>${esc(t.title)}</td><td><button class="sm" data-llm="${esc(t.id)}" ${st.enabled ? "" : "disabled"}>Run live</button></td></tr>`).join("")}</table></div></div>
      <div class="card" id="llmout">${S.lastLlm ? runHtml(S.lastLlm) : empty("Run a task to see the model's turns, each PEP decision and the tool-server evidence.")}</div>
    </div>`;
  el.querySelectorAll("[data-llm]").forEach(b => b.onclick = async () => {
    S.busy = true; $("#llmout").innerHTML = loading("Live model running (up to a minute)…"); el.querySelectorAll("button").forEach(x => x.disabled = true);
    try { S.lastLlm = await consoleAction(`/console/llm/${b.dataset.llm}/run`); } catch (e) { $("#llmout").innerHTML = errBox(e, "Live run"); S.busy = false; return; }
    S.busy = false; VIEWS.llm(el);
  });
};

// ---------------------------------------------------------------- 3. agents & authority
VIEWS.agents = async el => {
  clearInterval(S.timer); el.innerHTML = loading();
  try { S.agents = await api("/api/agents"); } catch (e) { el.innerHTML = errBox(e, "Loading agents"); return; }
  if (!S.agents.length) { el.innerHTML = empty("No agents registered. Use Live scenarios → Reset demo to load the declared baseline."); return; }
  const a = S.agents.find(x => x.agent_id === S.sel) || S.agents[0]; S.sel = a.agent_id;
  const tasks = Object.keys(a.mandate.tasks || {});
  el.innerHTML = `
    <div class="card"><div class="tbl"><table><tr><th>Agent</th><th>Role</th><th>Task</th><th>HR scope</th><th>Status</th><th>Baseline</th><th>Open alerts</th></tr>
      ${S.agents.map(x => `<tr class="click ${x.agent_id === a.agent_id ? "sel" : ""}" data-a="${esc(x.agent_id)}"><td class="mono">${esc(x.agent_id)}</td><td>${esc(x.role)}</td>
        <td>${esc(x.task || "—")}<div class="faint">${esc(x.task_instruction || "")}</div></td><td>${(x.subjects || []).length ? esc(x.subjects.join(", ")) : `<span class="faint">none</span>`}</td>
        <td>${pill(x.status, STATUS[x.status])}</td><td>${x.cold_start ? pill("cold start", "warn") : pill(`${x.history_n} events`, "muted")}</td><td>${esc(x.open_alerts)}</td></tr>`).join("")}</table></div></div>
    <div class="grid g2" style="margin-top:14px">
      <div class="card"><h3>Declared authority: <span class="mono">${esc(a.agent_id)}</span></h3>
        <dl class="kv"><dt>Role</dt><dd>${esc(a.role)}</dd><dt>Tools</dt><dd>${esc(a.mandate.tools.join(", "))}</dd>
          <dt>Max sensitivity</dt><dd>${esc(a.mandate.max_sensitivity)}</dd><dt>Destinations</dt><dd>${esc(a.mandate.destinations.join(", "))}</dd>
          <dt>May delegate to</dt><dd>${esc((a.mandate.may_delegate_to || []).join(", ") || "none")}</dd><dt>Read budget</dt><dd class="mono">${esc(JSON.stringify(a.mandate.read_budget || {}))}</dd>
          <dt>Owner</dt><dd>${esc(a.owner)}</dd><dt>Drift accumulator</dt><dd>${esc(a.accumulator)}</dd></dl>
        <div class="row" style="margin-top:12px">
          ${a.status !== "quarantined" ? `<button class="danger" id="q">Quarantine…</button>` : ""}${a.status !== "active" ? `<button class="primary" id="res">Resume…</button>` : ""}
          ${a.status === "active" ? `<button id="rst">Restrict…</button>` : ""}</div></div>
      <div class="card"><h3>Assign task (owner)</h3>
        <form id="tf" class="form" novalidate>
          <label class="f">Role<select name="role">${ROLES.map(r => `<option ${r === a.role ? "selected" : ""}>${r}</option>`).join("")}</select></label>
          <label class="f">Task<select name="task">${tasks.map(t => `<option ${t === a.task ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></label>
          <label class="f" style="grid-column:1/-1">Instruction (owner text; never used to authorize HR access)<input name="instruction" value="${esc(a.task_instruction || "")}"></label>
          <label class="f" id="subjwrap" style="grid-column:1/-1">HR subjects (structured scope; comma-separated identifiers)<input name="subjects" placeholder="e.g. grace" value="${esc((a.subjects || []).join(", "))}"></label>
          <div><button class="primary">Assign</button></div>
        </form><p class="err" id="tferr"></p>
        <p class="faint">Changing the role resets the agent's behavioural baseline (cold start) and loads the new role's tasks. HR tasks other than payroll_batch are refused by the server unless a subject is declared, and names in the instruction never grant access.</p></div>
    </div>`;
  el.querySelectorAll("[data-a]").forEach(r => r.onclick = () => { S.sel = r.dataset.a; VIEWS.agents(el); });
  const setStatus = async (status, label) => {
    const reason = await ask(`${label} ${a.agent_id}?`, `<p>Status → <b>${status}</b>. Recorded in the audit with your reason.</p>`, { ok: label, danger: status !== "active" });
    if (!reason) return;
    try { await api(`/api/agents/${encodeURIComponent(a.agent_id)}/status`, { status, reason }); } catch (e) { alert(e.message); }
    VIEWS.agents(el);
  };
  if ($("#q")) $("#q").onclick = () => setStatus("quarantined", "Quarantine");
  if ($("#res")) $("#res").onclick = () => setStatus("active", "Resume");
  if ($("#rst")) $("#rst").onclick = () => setStatus("restricted", "Restrict");
  const f = $("#tf"), sw = () => { $("#subjwrap").hidden = f.role.value !== "hr_assistant"; };
  f.role.onchange = async () => {
    sw();
    if (f.role.value !== a.role) {
      if (!(await ask(`Change role of ${a.agent_id} to ${f.role.value}?`, "<p>The baseline is reset (cold start). Then choose a task for the new role.</p>", { reason: false, ok: "Change role" }))) { f.role.value = a.role; sw(); return; }
      try { await api(`/api/agents/${encodeURIComponent(a.agent_id)}/task`, { role: f.role.value }); } catch (e) { $("#tferr").textContent = e.message; return; }
      VIEWS.agents(el);
    }
  };
  sw();
  f.onsubmit = async ev => {
    ev.preventDefault(); $("#tferr").textContent = "";
    const subjects = f.subjects.value.split(",").map(s => s.trim()).filter(Boolean);
    if (a.role === "hr_assistant") {   // client-side check mirrors the server rule; the server remains authoritative
      if (f.task.value !== "payroll_batch" && !subjects.length) { $("#tferr").textContent = "HR tasks need at least one declared subject."; return; }
      const bad = subjects.find(s => !/^[A-Za-z0-9._-]+$/.test(s)); if (bad) { $("#tferr").textContent = `Invalid subject "${bad}": one identifier per entry.`; return; }
    }
    const body = { task: f.task.value, instruction: f.instruction.value };
    if (a.role === "hr_assistant" && subjects.length) body.subjects = subjects;
    try { await api(`/api/agents/${encodeURIComponent(a.agent_id)}/task`, body); VIEWS.agents(el); }
    catch (e) { $("#tferr").textContent = `Server refused: ${e.message}`; }
  };
};

// ---------------------------------------------------------------- 4. approvals
VIEWS.approvals = async el => {
  const draw = async () => {
    let aps, ev;
    try { [aps, ev] = await Promise.all([api("/api/approvals"), api("/api/events?limit=1000")]); } catch (e) { el.innerHTML = errBox(e, "Loading approvals"); return; }
    const sig = JSON.stringify([aps, ev.filter(e => e.control === "approval_grant").map(e => e.decision_id)]);
    if (sig === S.apSig && el.querySelector("[data-ap], .card")) return;   // re-render only when the data changed
    S.apSig = sig;
    const used = id => ev.filter(e => e.control === "approval_grant" && String(e.reason).includes(id));
    const pend = aps.filter(a => a.status === "pending"), done = aps.filter(a => a.status !== "pending");
    const row = a => { const u = used(a.id); return `<div class="card" style="margin-bottom:10px"><div class="row"><b class="mono">${esc(a.id)}</b>${pill(a.status, { pending: "warn", approved: "info", consumed: "ok", rejected: "bad" }[a.status])}
        ${pill(a.kind === "read_budget_extension" ? "read-budget extension" : "one-time action", "muted")}<span class="spacer"></span><span class="faint">${ts(a.created)}</span></div>
      <dl class="kv" style="margin-top:8px"><dt>Agent</dt><dd class="mono">${esc(a.agent_id)}</dd><dt>Requested action</dt><dd><b>${esc(a.tool)}</b> <span class="mono">${esc(JSON.stringify(a.args))}</span></dd>
        <dt>Why approval</dt><dd>${esc(a.reason)} <span class="faint">(risk score ${esc(a.risk_score)}, ordinal)</span></dd>
        ${a.note ? `<dt>Owner note</dt><dd>${esc(a.note)} <span class="faint">by ${esc(a.resolved_by)}</span></dd>` : ""}
        <dt>Execution outcome</dt><dd>${u.length ? `${pill(`executed ${u.length}×`, u.length === 1 ? "ok" : "bad")} <span class="faint">decision ${esc(u[0].decision_id)} at ${ts(u[0].ts)}</span>` :
          a.status === "approved" ? `<span class="mute">approved; the agent has not retried yet. It will execute once at most.</span>` : a.status === "pending" ? `<span class="mute">nothing executed (held)</span>` : `<span class="mute">not executed</span>`}</dd></dl>
      <details><summary>policy evidence (${(a.factors || []).length} factors)</summary>${factorsHtml(a.factors)}</details>
      ${a.status === "pending" ? `<div class="row" style="margin-top:10px"><button class="primary" data-ap="${esc(a.id)}" data-v="1">Approve once…</button><button class="danger" data-ap="${esc(a.id)}" data-v="0">Reject…</button></div>` : ""}</div>`; };
    el.innerHTML = `<p class="lead">Approval-required actions are <b>held</b>: nothing reaches the tool server until the owner approves. An approval is bound to the exact agent, tool and arguments and is consumed by its first execution.</p>
      <h2>Pending (${pend.length})</h2>${pend.length ? pend.map(row).join("") : empty("No pending approvals.")}
      <h2>Resolved (${done.length})</h2>${done.length ? done.slice(0, 30).map(row).join("") : empty("None yet.")}`;
    el.querySelectorAll("[data-ap]").forEach(b => b.onclick = async () => {
      const yes = b.dataset.v === "1";
      const note = await ask(`${yes ? "Approve" : "Reject"} ${b.dataset.ap}?`, yes ? "<p>The agent's identical call may then execute <b>once</b>.</p>" : "<p>The action stays blocked.</p>", { ok: yes ? "Approve once" : "Reject", danger: !yes });
      if (!note) return;
      try { await api(`/api/approvals/${encodeURIComponent(b.dataset.ap)}`, { approve: yes, note }); } catch (e) { alert(`Server refused: ${e.message}`); }
      S.apSig = null; draw(); refreshStatus();
    });
  };
  S.apSig = null; el.innerHTML = loading(); await draw(); poll(draw, 6000);
};

// ---------------------------------------------------------------- 5. investigations
VIEWS.investigate = async el => {
  clearInterval(S.timer); el.innerHTML = loading();
  const q = new URLSearchParams(location.hash.split("?")[1] || "");
  let ev, al;
  try { [ev, al] = await Promise.all([api("/api/events?limit=1000"), api("/api/alerts")]); } catch (e) { el.innerHTML = errBox(e, "Loading events"); return; }
  ev = ev.slice().reverse();
  const agents = [...new Set(ev.map(e => e.agent_id))];
  const f = { agent: q.get("agent") || "", resp: q.get("resp") || "", d: q.get("d") || (ev[0] && ev[0].decision_id) };
  const sel = ev.find(e => e.decision_id === f.d) || ev[0];
  const list = ev.filter(e => (!f.agent || e.agent_id === f.agent) && (!f.resp || e.response === f.resp));
  const alert_ = sel && al.find(a => a.decision_id === sel.decision_id || (a.aggregated_into === sel.aggregated_into && sel.aggregated_into));
  const outcome = e => e.response === "ALLOW" ? "Executed (effect allowed)" : e.response === "DENY" ? "Prevented: denied before execution" : "Held: nothing executes until an owner approves";
  el.innerHTML = !ev.length ? empty("No decisions yet. Run a live scenario.") : `
    <div class="row"><label class="f">Agent<select id="fa"><option value="">all</option>${agents.map(a => `<option ${a === f.agent ? "selected" : ""}>${esc(a)}</option>`).join("")}</select></label>
      <label class="f">Decision<select id="fr"><option value="">all</option>${["ALLOW", "DENY", "APPROVAL_REQUIRED"].map(r => `<option ${r === f.resp ? "selected" : ""}>${r}</option>`).join("")}</select></label>
      <span class="faint">${list.length} of ${ev.length} decisions</span></div>
    <div class="grid g2" style="margin-top:12px">
      <div class="card"><div class="tbl" style="max-height:640px;overflow:auto"><table><tr><th>Time</th><th>Agent</th><th>Tool</th><th>Decision</th><th>Score</th></tr>
        ${list.map(e => `<tr class="click ${sel && e.decision_id === sel.decision_id ? "sel" : ""}" data-d="${esc(e.decision_id)}"><td class="faint">${ts(e.ts)}</td><td class="mono">${esc(e.agent_id)}</td><td>${esc(e.tool)}</td>
          <td>${pill(e.response, RESP[e.response])}${e.agent_status_change ? ` ${pill(e.agent_status_change, STATUS[e.agent_status_change])}` : ""}</td><td class="mono">${esc(e.risk_score)}</td></tr>`).join("")}</table></div></div>
      ${sel ? `<div class="card"><div class="row"><h3 style="margin:0">${esc(sel.tool)}</h3>${pill(sel.response, RESP[sel.response])}${sel.agent_status_change ? pill(`agent ${sel.agent_status_change}`, STATUS[sel.agent_status_change]) : ""}<span class="spacer"></span><span class="mono faint">${esc(sel.decision_id)}</span></div>
        <dl class="kv" style="margin-top:10px"><dt>Resulting action</dt><dd><b>${outcome(sel)}</b></dd><dt>Agent</dt><dd class="mono">${esc(sel.agent_id)} (${esc(sel.role)} / ${esc(sel.task)})</dd>
          <dt>Arguments</dt><dd class="mono">${esc(JSON.stringify(sel.args))}</dd><dt>Destination</dt><dd>${esc(sel.destination)}</dd><dt>Reason</dt><dd>${esc(sel.reason)}</dd>
          <dt>Stopping control</dt><dd>${esc(sel.control)}</dd><dt>Risk score</dt><dd>${esc(sel.risk_score)} (${esc(sel.risk_band)}) <span class="faint">ordinal sum of documented factor points, not a probability</span></dd>
          <dt>Confidence</dt><dd>${esc(sel.confidence)}</dd><dt>Cedar policy P</dt><dd>${esc(sel.cedar ?? "n/a")}</dd>
          ${sel.delegation ? `<dt>Delegation chain</dt><dd class="mono">${esc(JSON.stringify(sel.delegation))}</dd>` : ""}
          ${sel.provenance_label ? `<dt>Provenance</dt><dd>${esc(sel.provenance_label)}</dd>` : ""}
          <dt>Detection alert</dt><dd>${sel.alert_id ? `${pill(sel.alert_id, "info")} ${alert_ && alert_.actionable === false ? `<span class="faint">informational, aggregated ${alert_.aggregated_count || 1}×</span>` : ""}` : sel.aggregated_into ? `<span class="faint">folded into ${esc(sel.aggregated_into)}</span>` : `<span class="faint">none</span>`}</dd></dl>
        <h3 style="margin-top:12px">Contributing factors and evidence</h3>${factorsHtml(sel.factors)}
        <h3 style="margin-top:12px">Expected authority</h3><pre>${esc(JSON.stringify(sel.expected_authority, null, 1))}</pre>
        <p class="faint">A detection alert is not an outcome. Prevention is the decision itself (DENY or APPROVAL_REQUIRED); live scenarios additionally verify that the tool server recorded no effect.</p></div>` : ""}
    </div>`;
  const go = (k, v) => { const p = new URLSearchParams({ agent: f.agent, resp: f.resp, d: f.d, [k]: v }); location.hash = `#/investigate?${p}`; };
  if ($("#fa")) { $("#fa").onchange = e => go("agent", e.target.value); $("#fr").onchange = e => go("resp", e.target.value); }
  el.querySelectorAll("[data-d]").forEach(r => r.onclick = () => go("d", r.dataset.d));
};

// ---------------------------------------------------------------- 6. audit explorer
VIEWS.audit = async el => {
  clearInterval(S.timer); el.innerHTML = loading("Loading and verifying the audit chain…");
  let au; try { au = await api("/api/audit?limit=5000"); } catch (e) { el.innerHTML = errBox(e, "Loading the audit"); return; }
  const recs = au.records.slice().reverse();
  const kinds = [...new Set(recs.map(r => r.entry.kind))].sort();
  const agentOf = e => e.agent_id || e.agent || e.child || "";
  const agents = [...new Set(recs.map(r => agentOf(r.entry)).filter(Boolean))];
  const st = { kind: "", agent: "", resp: "", text: "", from: "" };
  const v = au.verify;
  el.innerHTML = `
    <div class="card">${v.ok ? `${pill("hash chain verified", "ok")} <span class="mute">${v.records} records; head <span class="mono">${esc(String(v.head).slice(0, 16))}…</span></span>` :
      `${pill("hash chain BROKEN", "bad")} <span>at record ${esc(v.broken_at)}: an edit, deletion or reordering occurred.</span>`}
      <p class="faint">What the audit proves: the records the control plane holds have not been edited, removed or reordered since they were chained. What it does not prove: that a record was ever written for traffic that bypassed the PEP, that the whole file was not replaced together with its checkpoint and anchor, or that tool outputs were truthful. Agents are scripted; outbound effects are simulated.</p></div>
    <div class="row" style="margin:14px 0"><label class="f">Event type<select id="ak"><option value="">all</option>${kinds.map(k => `<option>${esc(k)}</option>`).join("")}</select></label>
      <label class="f">Agent<select id="aa"><option value="">all</option>${agents.map(a => `<option>${esc(a)}</option>`).join("")}</select></label>
      <label class="f">Decision<select id="ar"><option value="">all</option><option>ALLOW</option><option>DENY</option><option>APPROVAL_REQUIRED</option></select></label>
      <label class="f">Since<input id="af" type="datetime-local"></label><label class="f">Text<input id="at" placeholder="tool, reason, status…"></label>
      <span class="faint" id="acount"></span></div>
    <div class="card"><div class="tbl" id="atbl"></div></div>`;
  const draw = () => {
    const from = st.from ? new Date(st.from).getTime() / 1000 : 0;
    const rows = recs.filter(r => (!st.kind || r.entry.kind === st.kind) && (!st.agent || agentOf(r.entry) === st.agent) && (!st.resp || r.entry.response === st.resp)
      && (!from || r.t >= from) && (!st.text || JSON.stringify(r.entry).toLowerCase().includes(st.text.toLowerCase())));
    $("#acount").textContent = `${rows.length} of ${recs.length} records`;
    $("#atbl").innerHTML = rows.length ? `<table><tr><th>Seq</th><th>Time</th><th>Type</th><th>Agent</th><th>Summary</th></tr>${rows.slice(0, 400).map(r => { const e = r.entry;
      const sum = e.kind === "decision" ? `${e.tool} → ${pill(e.response, RESP[e.response])} ${esc(e.reason)}` : e.kind === "status_changed" ? `${pill(`${e.from} → ${e.to}`, STATUS[e.to])} ${esc(e.reason)} <span class="faint">by ${esc(e.by)}</span>`
        : e.kind === "approval_resolved" ? `${esc(e.approval)} ${pill(e.status, e.status === "approved" ? "ok" : "bad")} ${esc(e.note || "")}` : `<span class="mono faint">${esc(JSON.stringify(e)).slice(0, 180)}</span>`;
      return `<tr><td class="mono">${r.seq}</td><td class="faint">${ts(r.t)}</td><td>${esc(e.kind)}</td><td class="mono">${esc(agentOf(e))}</td><td>${sum}</td></tr>`; }).join("")}</table>${rows.length > 400 ? `<p class="faint">Showing the newest 400; narrow the filters.</p>` : ""}` : empty("No records match.");
  };
  [["#ak", "kind"], ["#aa", "agent"], ["#ar", "resp"], ["#af", "from"], ["#at", "text"]].forEach(([s, k]) => $(s).oninput = e => { st[k] = e.target.value; draw(); });
  draw();
};

// ---------------------------------------------------------------- 7. recovery
VIEWS.recovery = async el => {
  clearInterval(S.timer);
  const h = S.health, m = S.meta;
  el.innerHTML = `
    <div class="grid g3">
      <div class="card kpi"><div class="l">Control plane</div><div class="v">${h && h.control.reachable ? pill("running", "ok") : pill("not running", "bad")}</div><div class="s">${h && !h.control.reachable ? esc(h.control.error || "") : ""}</div></div>
      <div class="card kpi"><div class="l">Mode</div><div class="v">${m ? (m.recovery ? pill("owner recovery", "warn") : pill("normal", "ok")) : "—"}</div><div class="s">${m && m.recovery_reason ? esc(m.recovery_reason) : ""}</div></div>
      <div class="card kpi"><div class="l">Persistence</div><div class="v">${m ? (m.persistence.state_dir ? pill("checkpointed", "info") : pill("memory", "warn")) : "—"}</div><div class="s">${m ? `${m.persistence.anchor ? "separate anchor" : "no anchor"} · ${m.persistence.signed ? "signed" : "unsigned (demo)"}${m.persistence.findings.length ? " · " + esc(m.persistence.findings.join(", ")) : ""}` : ""}</div></div>
    </div>
    <h2>How recovery works</h2>
    <p class="lead">At start-up the control plane checks that the audit log still contains the checkpointed record with the checkpointed hash (and the separate anchor). If history is missing, replaced, rolled back or torn, it <b>refuses to start</b>, and the PEP then denies every protected action. Only the owner can start it in <b>recovery mode</b>: the unverifiable log segment is kept as evidence, every read and effect needs an approval, and normal enforcement resumes only after an explicit acknowledgement. The lost history is not counted after acknowledgement (documented limitation V2).</p>
    <div class="card"><div class="row">
      <button id="rstart" ${h && h.control.reachable && !(m && m.recovery) ? "disabled" : ""}>1 · Start in owner recovery mode</button>
      <button id="rack" class="primary" ${m && m.recovery ? "" : "disabled"}>2 · Acknowledge recovery…</button>
      <span class="spacer"></span><a href="#/demo">Reproduce with live scenario 11</a></div>
      <p class="faint">Step 1 recreates only the demo control-plane container with MANDATE_RECOVERY=1 and reseeds the declared demo agents (their earlier state was in the lost history). Destructive demonstrations run only against the demo Docker volume.</p>
      <div id="rout"></div></div>`;
  $("#rstart").onclick = async () => {
    if (!(await ask("Start the control plane in owner recovery mode?", "<p>Every read and effect will need an approval until you acknowledge.</p>", { reason: false, ok: "Start recovery" }))) return;
    $("#rout").innerHTML = loading("Recreating the control plane in recovery mode…");
    try { const r = await consoleAction("/console/recovery/start"); $("#rout").innerHTML = `<pre>${esc(JSON.stringify(r, null, 1))}</pre>`; } catch (e) { $("#rout").innerHTML = errBox(e, "Recovery start"); }
    await refreshStatus(); VIEWS.recovery(el);
  };
  $("#rack").onclick = async () => {
    const note = await ask("Acknowledge recovery?", "<p>You accept that history before the loss is not counted. Normal enforcement resumes.</p>", { ok: "Acknowledge" });
    if (!note) return;
    try { await api("/api/recovery/ack", { note }); } catch (e) { alert(e.message); }
    await refreshStatus(); VIEWS.recovery(el);
  };
};

// ---------------------------------------------------------------- 8. results
VIEWS.results = async el => {
  clearInterval(S.timer); el.innerHTML = loading();
  let r; try { r = await http("/console/results"); } catch (e) { el.innerHTML = errBox(e, "Loading results"); return; }
  const n = (o, k) => o[k] || 0;
  const bar = (o, total, keys) => `<div class="bar">${keys.map(([k, c]) => `<span style="width:${100 * n(o, k) / total}%;background:var(--${c})" title="${k}: ${n(o, k)}"></span>`).join("")}</div>`;
  const AK = [["DENIED", "ok"], ["APPROVAL_PENDING", "warn"], ["EXECUTED_LABELLED", "info"], ["SUCCEEDED", "bad"]];
  const fams = Object.entries(r.families).sort();
  el.innerHTML = `
    <div class="note w"><b>What these numbers are:</b> engine-level evaluation on AI-generated scenarios, with scripted agents, a mock tool server and simulated outbound effects. Outcomes are classified from recorded tool effects. They are not real-world prevention rates, and the scenarios were not authored independently. Repeated runs show reproducibility only.</div>
    <h2>Engine comparison (1,260 attack / 840 benign scenarios per run)</h2>
    <div class="card tbl"><table><tr><th>Engine</th><th>Seeds</th><th>Denied</th><th>Approval pending</th><th>Executed, labelled</th><th>Succeeded</th><th>Alert before / at / none</th><th>Benign clean / friction / denied</th><th>Benign alert rate (actionable)</th></tr>
      ${r.comparison.map(c => `<tr><td><b>${esc(c.engine)}</b></td><td class="faint">${esc(c.seeds)}</td><td>${n(c.attack_outcomes, "DENIED")}</td><td>${n(c.attack_outcomes, "APPROVAL_PENDING")}</td><td>${n(c.attack_outcomes, "EXECUTED_LABELLED")}</td>
        <td class="${n(c.attack_outcomes, "SUCCEEDED") ? "bad" : ""}"><b>${n(c.attack_outcomes, "SUCCEEDED")}</b></td><td>${n(c.alert_timing, "BEFORE")} / ${n(c.alert_timing, "AT")} / ${n(c.alert_timing, "NONE")}</td>
        <td>${n(c.benign_outcomes, "CLEAN")} / ${n(c.benign_outcomes, "APPROVAL_FRICTION")} / ${n(c.benign_outcomes, "DENIED_LEGIT")}</td><td>${c.benign_alert_rate} (${c.benign_actionable_alert_rate})</td></tr>
        <tr><td colspan="9">${bar(c.attack_outcomes, c.attack_scenarios, AK)}</td></tr>`).join("")}</table>
      <div class="legend">${AK.map(([k, c]) => `<span><i style="background:var(--${c})"></i>${k}</span>`).join("")}</div>
      <p class="faint">Final run repeated with an identical decision hash: ${r.final_repeat_hash_equal ? "yes" : "no"}. Denominators: benign alert rate = new alerts on benign actions / benign actions (including benign steps inside attack scenarios). Sources: ${r.comparison.map(c => `<span class="mono">${esc(c.file)}</span>`).join(", ")}.</p></div>
    <h2>Earlier held-out sets (decision-classified, different scenario pools; not directly comparable)</h2>
    <div class="card tbl"><table><tr><th>Engine</th><th>Attack outcomes</th><th>Benign outcomes</th><th>Source</th></tr>
      ${r.historical.map(h => `<tr><td>${esc(h.engine)}</td><td class="mono">${esc(JSON.stringify(h.attack_outcomes))}</td><td class="mono">${esc(JSON.stringify(h.benign_outcomes))}</td><td class="faint mono">${esc(h.file)}</td></tr>`).join("")}</table></div>
    <h2>Scenario families and their disposition (final run)</h2>
    <div class="card tbl" style="max-height:520px;overflow:auto"><table><tr><th>Family</th><th>Outcomes (30 scenarios each)</th></tr>
      ${fams.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${Object.entries(v).map(([o, c]) => pill(`${o} ${c}`, { DENIED: "ok", APPROVAL_PENDING: "warn", CLEAN: "ok", APPROVAL_FRICTION: "warn", SUCCEEDED: "bad", DENIED_LEGIT: "bad", EXECUTED_LABELLED: "info", INCONCLUSIVE: "bad" }[o])).join(" ")}</td></tr>`).join("")}</table></div>
    <h2>Post-freeze red team against E4.2.1 (AI adversarial self-review)</h2>
    <div class="card tbl" style="max-height:420px;overflow:auto"><table><tr><th>Case</th><th>Outcome</th><th>Harmful executed</th><th>Note</th></tr>
      ${r.redteam.map(c => `<tr><td>${esc(c.id)}</td><td>${pill(c.outcome, /SUCC|EVADED/.test(c.outcome) ? "bad" : /REFUSED/.test(c.outcome) ? "muted" : "ok")}</td><td>${esc(c.executed)}/${esc(c.of)}</td><td class="faint">${esc(c.note || c.set || "")}</td></tr>`).join("")}</table></div>
    <h2>Limitations and validation status</h2>
    <div class="card tbl"><table><tr><th>ID</th><th>Item</th><th>Status</th><th>Evidence</th></tr>
      ${r.limitations.items.map(l => `<tr><td class="mono">${esc(l.id)}</td><td>${esc(l.item)}</td><td>${pill(l.status, /FIXED AND/.test(l.status) && !/PENDING|PARTIAL/.test(l.status) ? "ok" : /DOCUMENTED|EXTERNAL/.test(l.status) ? "bad" : "warn")}</td><td class="faint">${esc(l.evidence)}</td></tr>`).join("")}</table>
      <p class="faint">Source: ${esc(r.limitations.source)}. Owner sign-off of the acceptance criteria is pending (OWNER_REVIEW_CHECKLIST_E421.md).</p></div>`;
};

// ---------------------------------------------------------------- 9. diagnostics
VIEWS.diagnostics = async el => {
  const draw = async () => {
    let d; try { d = await http("/console/diagnostics"); } catch (e) { el.innerHTML = errBox(e, "Diagnostics"); return; }
    const h = S.health || {};
    const am = x => x ? pill(x.ok === false || x.pass === false || x.violations ? "see JSON" : "recorded", "info") : pill("not found", "warn");
    el.innerHTML = `
      <div class="grid g2">
        <div class="card"><h3>Services (docker compose ps)</h3>${h.docker ? `<div class="tbl"><table><tr><th>Service</th><th>State</th><th>Status</th></tr>${(h.services || []).map(s => `<tr><td>${esc(s.service)}</td><td>${s.service === "pki" && /Exited \(0\)/.test(s.status) ? pill("one-shot, completed", "muted") : pill(s.state, s.state === "running" ? "ok" : "bad")}</td><td class="faint">${esc(s.status)}</td></tr>`).join("")}</table></div>`
          : `<div class="empty">Docker CLI unavailable: ${esc(h.docker_error || "")}<br>Start Docker Desktop, then run <span class="mono">bash demo/launch.sh</span>.</div>`}</div>
        <div class="card"><h3>Engine configuration</h3><dl class="kv"><dt>Required</dt><dd>${esc(h.engine_required)}</dd><dt>Container env</dt><dd class="mono">${esc(JSON.stringify(h.container_env || {}))}</dd>
          <dt>Reported by control</dt><dd>${S.meta ? `${esc(S.meta.engine)} (config ${esc(S.meta.engine_config)})` : "control plane unreachable"}</dd><dt>Match</dt><dd>${h.engine_ok === true ? pill("yes", "ok") : h.engine_ok === false ? pill("NO", "bad") : pill("unknown", "warn")}</dd>
          <dt>Demo token injection</dt><dd>${h.console_demo_token ? "on (local demo only)" : "off"}</dd></dl>
          ${!h.control?.reachable ? `<p class="note w">The control plane is not answering. If the last scenario was 11, open <a href="#/recovery">Recovery</a>. Otherwise use Reset demo. Logs: <span class="mono">docker compose -f compose.yaml logs control</span>.</p>` : ""}</div>
        <div class="card"><h3>Last deployment (AM11 gates)</h3>${d.last_deploy ? `<p class="faint mono">${esc(d.last_deploy.dir)}</p><pre>${esc(d.last_deploy.log.join("\n"))}</pre>` : empty("No deployment record.")}
          <div class="row">AM11 static ${am(d.am11_static)} runtime ${am(d.am11_runtime)}</div></div>
        <div class="card"><h3>Recorded test results</h3>${d.tests ? `<p class="faint mono">${esc(d.tests.file)}</p><pre>${esc(d.tests.lines.join("\n"))}</pre>` : empty("none")}
          ${d.last_e2e ? `<p>Last live E2E: <b>${d.last_e2e.passed}/${d.last_e2e.total}</b> <span class="faint mono">${esc(d.last_e2e.file)} · ${esc(d.last_e2e.engine || "")}</span></p>` : ""}
          ${d.console_tests ? `<p>Console integration tests: <b>${d.console_tests.passed}/${d.console_tests.total}</b> <span class="faint">${ts(d.console_tests.finished)}</span></p>` : ""}</div>
        <div class="card"><h3>Evidence integrity</h3><p>State: ${pill(d.evidence_verify.state, { ok: "ok", failed: "bad", running: "warn" }[d.evidence_verify.state] || "muted")} ${d.evidence_verify.at ? `<span class="faint">${ts(d.evidence_verify.at)}</span>` : ""}</p>
          ${d.evidence_verify.output ? `<pre>${esc(d.evidence_verify.output.join("\n"))}</pre>` : ""}
          <button id="ver" ${d.evidence_verify.state === "running" ? "disabled" : ""}>Run verify_evidence.py verify</button> <span class="faint">Read-only; recomputes every evidence hash from git objects (a few minutes).</span></div>
      </div>`;
    $("#ver").onclick = async () => { try { await consoleAction("/console/verify-evidence"); } catch (e) { alert(e.message); } draw(); };
  };
  el.innerHTML = loading(); await draw(); poll(draw, 8000);
};

route();
