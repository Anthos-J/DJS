// MANDATE "Your task" workbench (R-E4.3.1). Bring your own task and documents; MANDATE governs every action.
// Uses app.js helpers ($, esc, http, act, api, stamp, why, toolH, head, term, ask, loading, empty, errBox, clock, poll).
// Every verdict shown here is read back from the real control plane and the tool server; this file decides nothing.
"use strict";
const WB = { cat: null, draft: null, run: null, previews: {} };
const EXAMPLES = [
  { t: "Research three suppliers, compare their prices, and prepare a purchase recommendation.", p: "procurement", k: "supplier_review_docs", docs: true },
  { t: "Read these documents and summarize the important information in a wiki page.", p: "research", k: "document_review", docs: true },
  { t: "Analyze the quarterly business report and prepare a short report for the team wiki.", p: "research", k: "document_review", docs: true },
  { t: "Review stark_quote_poisoned.txt and identify any suspicious instructions that try to manipulate the AI agent.", p: "research", k: "document_review", docs: true },
  { t: "Compare the supplier quotes, but do not access HR records or send information outside the approved environment.", p: "procurement", k: "supplier_review_docs", docs: true },
];
const MODES = {
  simulate: ["Dry run", "Check a plan against the live rules. Nothing executes, nothing is recorded.", "info"],
  steps: ["Run my steps", "Your steps go through the real checkpoint to the mock tools. Effects are recorded.", "indigo"],
  ai: ["Live AI agent", "A real model (Groq) plans and acts. Every call it makes still passes the checkpoint.", "allow"],
};
const draft = () => WB.draft || (WB.draft = { instruction: "", profile: "research", task: "document_review", mode: "simulate", steps: [], accept: false });
const prof = id => WB.cat.profiles.find(p => p.id === id);
const taskOf = d => (prof(d.profile) || { tasks: [] }).tasks.find(t => t.id === d.task);
const scanTag = s => !s ? "" : s.verified === false ? `<span class="tag block"><span class="d"></span>could not verify · treated as untrusted</span>`
  : s.flagged ? `<span class="tag block"><span class="d"></span>hidden instructions detected · score ${esc(s.score)}</span>` : `<span class="tag allow"><span class="d"></span>scanned clean · score ${esc(s.score)}</span>`;

function suggest(d) {
  const docs = (WB.cat.docs || []).map(x => x.name), first = docs.slice(0, 3);
  const T = {
    supplier_review_docs: [["list_workspace_docs", {}], ...first.map(n => ["read_workspace_doc", { name: n }]), ["search_suppliers", { item: "valves" }], ["get_prices", { item: "valves" }]],
    price_check: [["search_suppliers", { item: "valves" }], ["get_prices", { item: "valves" }]],
    purchase: [["search_suppliers", { item: "valves" }], ["get_prices", { item: "valves" }], ["create_purchase_request", { supplier: "umbrella", amount: 41.5 }]],
    document_review: [["list_workspace_docs", {}], ...first.map(n => ["read_workspace_doc", { name: n }]), ["write_summary", { title: "document-review", text: "Summary of the reviewed documents." }]],
    research: [["web_search", { url: "https://kb.public.example/valves", destination: "kb.public.example" }], ["write_summary", { title: "valves-research", text: "Summary." }]],
    report: [["read_doc", { page: "valves" }], ["write_summary", { title: "valves-report", text: "Report." }], ["send_email", { to: "team@corp.internal", body: "Report attached.", destination: "internal" }]],
  };
  return (T[d.task] || []).map(([tool, args]) => ({ tool, args }));
}

// ---------------------------------------------------------------- composer
VIEWS.task = async el => {
  el.innerHTML = loading("Opening the workbench…");
  try { WB.cat = await http("/console/workbench"); } catch (e) { el.innerHTML = errBox(e, "Loading the workbench"); return; }
  const d = draft();
  if (!prof(d.profile)) d.profile = WB.cat.profiles[0].id;
  if (!taskOf(d)) d.task = prof(d.profile).tasks[0].id;
  if (d.mode === "ai" && !WB.cat.llm.enabled) d.mode = "simulate";
  draw(el);
};

function draw(el) {
  const d = draft(), c = WB.cat, p = prof(d.profile), t = taskOf(d), llm = c.llm;
  el.innerHTML = head("Your task", "Bring your own task. Watch MANDATE govern it.",
    `Describe what you want an AI agent to do, pick the agent and its job, add your own documents if you like, and run it. Every action the agent attempts passes the ${term("pep", "checkpoint")}: you'll see what was allowed, what was ${term("held", "held")} for your approval, what was blocked, and why. Use synthetic or sanitized data only.`,
    `<span class="tag indigo"><span class="d"></span>engine ${esc(c.engine)}</span>`) + `
  <div class="split wb">
    <div class="stack">
      <section class="card"><div class="eyebrow">1 · Describe the task</div>
        <textarea id="wb-ins" maxlength="${c.limits.instruction_chars}" placeholder="e.g. Read the supplier quotes, compare prices and recommend one. Do not access HR records." style="margin-top:10px;min-height:96px">${esc(d.instruction)}</textarea>
        <div class="row small ink3" style="margin-top:6px"><span>Try an example:</span></div>
        <div class="wb-chips">${EXAMPLES.map((x, i) => `<button class="sm ghost" data-ex="${i}">${esc(x.t.length > 70 ? x.t.slice(0, 68) + "…" : x.t)}</button>`).join("")}</div>
        <p class="ink3 small" style="margin-top:8px">${esc(c.authority_note)}</p></section>

      <section class="card"><div class="eyebrow">2 · Choose the agent and its job</div>
        <div class="grid g2" style="margin-top:10px">${c.profiles.map(x => `<label class="wb-pick ${x.id === d.profile ? "on" : ""}"><input type="radio" name="wb-prof" value="${esc(x.id)}" ${x.id === d.profile ? "checked" : ""}>
          <b>${esc(x.label)}</b><span class="ink2 small">${esc(x.blurb)}</span></label>`).join("")}</div>
        <label class="f" style="margin-top:12px">Task (sets which tools the agent may use)
          <select id="wb-task">${p.tasks.map(x => `<option value="${esc(x.id)}" ${x.id === d.task ? "selected" : ""}>${esc(x.title)}</option>`).join("")}</select>
          <small>${esc(t ? t.description : "")}</small></label></section>

      <section class="card"><div class="row"><div class="eyebrow">3 · Documents (optional)</div><span class="spacer"></span>
          <button class="sm ghost" id="wb-samples">Add sample documents</button></div>
        <div id="wb-docs" style="margin-top:10px">${docsHtml()}</div>
        <label class="wb-drop" id="wb-drop"><input type="file" id="wb-file" multiple accept="${c.documents.formats.join(",")}" hidden>
          <b>Drop text files here or click to choose</b><span class="ink3 small">${esc(c.documents.formats.join(" "))} · up to ${(c.documents.max_bytes / 1000).toFixed(0)} KB each · ${c.documents.max_docs} files max</span></label>
        <p class="ink3 small" style="margin-top:8px">${esc(c.documents.rules)}</p><p class="err" id="wb-docerr"></p></section>

      <section class="card"><div class="eyebrow">4 · How should it run?</div>
        <div class="grid g3" style="margin-top:10px">${Object.entries(MODES).map(([k, [n, s]]) => `<label class="wb-pick ${k === d.mode ? "on" : ""} ${k === "ai" && !llm.enabled ? "off" : ""}">
          <input type="radio" name="wb-mode" value="${k}" ${k === d.mode ? "checked" : ""} ${k === "ai" && !llm.enabled ? "disabled" : ""}><b>${esc(n)}</b><span class="ink2 small">${esc(s)}</span>
          ${k === "ai" && !llm.enabled ? `<span class="ink3 small">Not enabled. Set GROQ_API_KEY and MANDATE_LLM_CONSENT=1 in your terminal, then relaunch.</span>` : ""}</label>`).join("")}</div>
        ${d.mode === "ai" ? `<div class="callout info" style="margin-top:12px"><b>Data sent to a model provider.</b> In this mode your task text, the tool list and every tool result the agent reads, <i>including your documents' text</i>, are sent to Groq (<span class="mono">${esc(llm.model)}</span>). The key stays in your terminal's environment.
            <label class="row" style="margin-top:10px;font-weight:600"><input type="checkbox" id="wb-accept" style="width:auto" ${d.accept ? "checked" : ""}> I understand, and my documents are synthetic or sanitized.</label></div>`
          : `<div id="wb-steps" style="margin-top:12px">${stepsHtml()}</div>`}
        <div class="row" style="margin-top:14px"><button class="primary" id="wb-go">${d.mode === "simulate" ? "Check this plan (dry run)" : d.mode === "steps" ? "Run through the checkpoint" : "Start the AI agent"}</button>
          <span class="ink3 small">${d.mode === "simulate" ? "No side effects." : "Real decisions, mock tools, simulated outbound effects."}</span></div>
        <p class="err" id="wb-err"></p></section>
    </div>

    <aside class="stack result">
      <section class="card"><div class="eyebrow">What MANDATE will enforce</div>
        <h3 style="margin-top:8px">${esc(p.label)} · ${esc(t ? t.title : "")}</h3>
        <p class="ink2 small" style="margin-top:6px">The checkpoint allows only these tools for this task. Anything else the agent tries is blocked or held, whatever the instruction says.</p>
        <div class="wb-tools">${(t ? t.tools : []).map(x => `<div><b>${esc(toolH(x.name))}</b> <span class="mono ink3">${esc(x.name)}</span>
          <div class="ink3 small">${esc(x.backend)}${x.source === "untrusted" ? " · untrusted content: scanned, and later writes need approval" : ""}</div></div>`).join("")}</div>
        <dl class="kv"><dt>May send to</dt><dd>${p.destinations.map(esc).join(", ")}</dd><dt>Data ceiling</dt><dd>sensitivity ${esc(p.max_sensitivity)} (no HR or restricted data)</dd></dl>
        <div id="wb-hints"></div></section>
      <section class="card flat"><div class="eyebrow">Not connected in this prototype</div>
        <ul class="wb-list">${c.unavailable.map(u => `<li><b>${esc(u.what)}</b>: <span class="ink2">${esc(u.why)}</span></li>`).join("")}</ul></section>
      ${c.runs.length ? `<section class="card flat"><div class="eyebrow">Recent runs</div><div class="feed" style="margin-top:6px">${c.runs.slice(0, 6).map(r => `<div class="item" onclick="location.hash='#/taskrun?id=${esc(r.id)}'">
          <div class="t">${clock(r.created)}</div><div><div class="s">${esc(r.instruction.slice(0, 80))}</div><div class="w">${esc(MODES[r.mode][0])} · ${esc(r.status)}</div></div><div>${runBadge(r)}</div></div>`).join("")}</div></section>` : ""}
    </aside></div>`;
  wire(el);
}

function docsHtml() {
  const docs = WB.cat.docs || [];
  if (!docs.length) return `<div class="ink3 small">No documents yet. Agents can only read what you add here, and only through the checkpoint.</div>`;
  return `<div class="wb-doclist">${docs.map(x => { const pv = WB.previews[x.name];
    return `<div class="wb-doc"><span class="mono">${esc(x.name)}</span><span class="ink3 small">${(x.bytes / 1000).toFixed(1)} KB</span><span class="spacer"></span>
      ${pv ? (pv.error ? `<span class="tag">${esc(pv.error)}</span>` : scanTag({ verified: pv.verified, flagged: pv.injection, score: pv.score })) : `<button class="sm ghost" data-prev="${esc(x.name)}">Check for hidden instructions</button>`}
      <button class="sm ghost" data-del="${esc(x.name)}" aria-label="Remove ${esc(x.name)}">✕</button></div>`; }).join("")}</div>
    <p class="ink3 small" style="margin-top:6px">The check is a preview. The real protection is the scan that runs when an agent actually reads the document.</p>`;
}

function stepsHtml() {
  const d = draft(), spec = WB.cat.tool_spec, t = taskOf(d);
  if (!d.steps.length) d.steps = suggest(d);
  const allowed = new Set((t ? t.tools : []).map(x => x.name));
  return `<div class="row"><b class="small">The agent's plan</b><span class="ink3 small">Edit freely. Add a step outside the task to see what the checkpoint does with it.</span></div>
    ${d.steps.map((s, i) => `<div class="wb-step"><span class="mono ink3">${i + 1}</span>
      <select data-st="${i}">${Object.keys(spec).map(n => `<option value="${esc(n)}" ${n === s.tool ? "selected" : ""}>${esc(toolH(n))}${allowed.has(n) ? "" : " (outside this task)"}</option>`).join("")}</select>
      <div class="wb-args">${Object.entries(spec[s.tool].params).map(([k, ty]) => `<input data-arg="${i}" data-k="${esc(k)}" data-ty="${esc(ty)}" placeholder="${esc(k)}${spec[s.tool].required.includes(k) ? " *" : ""}" value="${esc(s.args[k] ?? "")}">`).join("") || `<span class="ink3 small">no arguments</span>`}</div>
      <button class="sm ghost" data-rm="${i}" aria-label="Remove step">✕</button></div>`).join("")}
    <div class="row" style="margin-top:8px"><button class="sm" id="wb-add">+ Add step</button><button class="sm ghost" id="wb-reset">Suggested plan for this task</button></div>`;
}

function wire(el) {
  const d = draft(), rerender = () => draw(el);
  $("#wb-ins").oninput = e => { d.instruction = e.target.value; hints(); };
  el.querySelectorAll("[data-ex]").forEach(b => b.onclick = async () => { const x = EXAMPLES[+b.dataset.ex];
    Object.assign(d, { instruction: x.t, profile: x.p, task: x.k, steps: [] });
    if (x.docs && !(WB.cat.docs || []).length) { try { const r = await act("/console/workbench/docs/samples"); WB.cat.docs = r.documents; } catch (e) { /* shown on next action */ } }
    rerender(); hints(); });
  el.querySelectorAll('[name="wb-prof"]').forEach(r => r.onchange = () => { d.profile = r.value; d.task = prof(d.profile).tasks[0].id; d.steps = []; rerender(); });
  $("#wb-task").onchange = e => { d.task = e.target.value; d.steps = []; rerender(); };
  el.querySelectorAll('[name="wb-mode"]').forEach(r => r.onchange = () => { d.mode = r.value; rerender(); });
  const acc = $("#wb-accept"); if (acc) acc.onchange = () => { d.accept = acc.checked; };
  $("#wb-samples").onclick = async () => { try { const r = await act("/console/workbench/docs/samples"); WB.cat.docs = r.documents; d.steps = []; rerender(); } catch (e) { $("#wb-docerr").textContent = e.message; } };
  el.querySelectorAll("[data-del]").forEach(b => b.onclick = async () => { try { const r = await act("/console/workbench/docs/delete", { name: b.dataset.del }); WB.cat.docs = r.documents; delete WB.previews[b.dataset.del]; d.steps = []; rerender(); } catch (e) { $("#wb-docerr").textContent = e.message; } });
  el.querySelectorAll("[data-prev]").forEach(b => b.onclick = async () => { b.disabled = true; b.textContent = "Checking…";
    try { const r = await act("/console/workbench/docs/preview", { name: b.dataset.prev }); WB.previews[b.dataset.prev] = r.available ? r : { error: "no detector in this engine" }; } catch (e) { WB.previews[b.dataset.prev] = { error: e.message }; }
    $("#wb-docs").innerHTML = docsHtml(); wire(el); });
  const drop = $("#wb-drop"), file = $("#wb-file");
  drop.onclick = e => { if (e.target !== file) file.click(); };
  drop.ondragover = e => { e.preventDefault(); drop.classList.add("over"); }; drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = e => { e.preventDefault(); drop.classList.remove("over"); upload([...e.dataTransfer.files]); };
  file.onchange = () => upload([...file.files]);
  async function upload(files) {
    const errs = [];
    for (const f of files) {
      if (f.size > WB.cat.documents.max_bytes) { errs.push(`${f.name}: larger than ${WB.cat.documents.max_bytes / 1000} KB`); continue; }
      let text; try { text = await f.text(); } catch (x) { errs.push(`${f.name}: could not be read as text`); continue; }
      try { const r = await act("/console/workbench/docs", { name: f.name, text }); WB.cat.docs = r.documents; if (r.warning) errs.push(`${f.name}: ${r.warning}`); }
      catch (x) { errs.push(`${f.name}: ${x.message}`); }
    }
    d.steps = []; rerender(); if (errs.length) $("#wb-docerr").textContent = errs.join(" · ");
  }
  el.querySelectorAll("[data-st]").forEach(s => s.onchange = () => { d.steps[+s.dataset.st] = { tool: s.value, args: {} }; $("#wb-steps").innerHTML = stepsHtml(); wire(el); });
  el.querySelectorAll("[data-arg]").forEach(inp => inp.oninput = () => { const st = d.steps[+inp.dataset.arg];
    st.args[inp.dataset.k] = inp.dataset.ty === "number" && inp.value !== "" && !isNaN(+inp.value) ? +inp.value : inp.value; if (inp.value === "") delete st.args[inp.dataset.k]; });
  el.querySelectorAll("[data-rm]").forEach(b => b.onclick = () => { d.steps.splice(+b.dataset.rm, 1); if (!d.steps.length) d.steps.push({ tool: "list_workspace_docs", args: {} }); $("#wb-steps").innerHTML = stepsHtml(); wire(el); });
  const add = $("#wb-add"); if (add) add.onclick = () => { d.steps.push({ tool: "read_hr_record", args: { employee: "grace" } }); $("#wb-steps").innerHTML = stepsHtml(); wire(el); };
  const rs = $("#wb-reset"); if (rs) rs.onclick = () => { d.steps = suggest(d); $("#wb-steps").innerHTML = stepsHtml(); wire(el); };
  $("#wb-go").onclick = async () => {
    $("#wb-err").textContent = "";
    if (!d.instruction.trim()) { $("#wb-err").textContent = "Describe the task first (step 1)."; return; }
    const body = { instruction: d.instruction, profile: d.profile, task: d.task, mode: d.mode };
    if (d.mode === "ai") body.accept_provider_disclosure = d.accept; else body.steps = d.steps.map(s => ({ tool: s.tool, args: s.args }));
    $("#wb-go").disabled = true;
    try { const r = await act("/console/workbench/run", body); WB.run = r; location.hash = `#/taskrun?id=${r.id}`; }
    catch (e) { $("#wb-err").textContent = e.message; $("#wb-go").disabled = false; }
  };
  hints();
}

let hintT;
function hints() {
  clearTimeout(hintT); const d = draft();
  hintT = setTimeout(async () => { const box = $("#wb-hints"); if (!box) return;
    try { const r = await act("/console/workbench/assess", { instruction: d.instruction, profile: d.profile, task: d.task });
      box.innerHTML = r.hints.length ? `<div class="callout" style="margin-top:12px"><b>Before you run:</b><ul class="wb-list">${r.hints.map(h => `<li>${esc(h)}</li>`).join("")}</ul><div class="ink3 small">${esc(r.hint_note)}</div></div>` : "";
    } catch (e) { box.innerHTML = ""; } }, 350);
}

// ---------------------------------------------------------------- run view
const runBadge = r => { const s = (r.summary && r.summary.by_response) || {}, sim = r.mode === "simulate";
  if (r.status === "running" || r.status === "queued") return `<span class="tag info"><span class="d"></span>running</span>`;
  if (r.status === "failed") return `<span class="tag block"><span class="d"></span>failed</span>`;
  return sim ? `<span class="tag info"><span class="d"></span>dry run</span>` : (s.DENY ? `<span class="tag block"><span class="d"></span>${s.DENY} blocked</span>` : s.APPROVAL_REQUIRED ? `<span class="tag held"><span class="d"></span>${s.APPROVAL_REQUIRED} held</span>` : `<span class="tag allow"><span class="d"></span>done</span>`); };

VIEWS.taskrun = async el => {
  const id = new URLSearchParams(location.hash.split("?")[1] || "").get("id");
  if (!id) { location.hash = "#/task"; return; }
  const draw2 = async () => {
    let r; try { r = await http(`/console/workbench/runs/${encodeURIComponent(id)}`); } catch (e) { el.innerHTML = errBox(e, "Loading the run"); return; }
    WB.run = r; el.innerHTML = runHtmlWB(r); wireRun(el, r);
    if (r.status === "running" || r.status === "queued") setTimeout(() => { if (location.hash.includes(id)) draw2(); }, 1500);
  };
  el.innerHTML = loading("Loading the run…"); await draw2();
};

function explainEvent(e, sim) {
  const d = e.decision || {};
  if (!e.decision) return e.ok ? "Executed (no decision record found)." : `No decision was recorded: ${esc(e.result || "the call did not reach the checkpoint")}`;
  return esc(why(d)) || esc(d.reason || "");
}

function runHtmlWB(r) {
  const sim = r.mode === "simulate", s = r.summary || {};
  const live = {}; r.events.filter(e => e.kind === (sim ? "simulated" : "tool")).forEach(e => { const k = (e.decision || {}).response || (e.ok ? "ALLOW" : "DENY"); live[k] = (live[k] || 0) + 1; });
  const by = r.summary ? (sim ? (s.simulated_by_response || {}) : (s.by_response || {})) : live;
  const tools = r.events.filter(e => e.kind === "tool" || e.kind === "simulated");
  const effects = s.tool_server_effects || r.events.filter(e => e.kind === "tool").flatMap(e => e.effects || []);
  return head(`Your task · ${esc(MODES[r.mode][0])}`, esc(r.instruction.length > 110 ? r.instruction.slice(0, 108) + "…" : r.instruction),
    `${esc(r.profile_label)} · task <span class="mono">${esc(r.task)}</span>${r.documents.length ? ` · documents: ${r.documents.map(esc).join(", ")}` : ""}${r.provider ? ` · model <span class="mono">${esc(r.provider.model)}</span>` : ""}`,
    `<div class="row">${runBadge(r)}<a class="btn sm" href="#/task">New task</a></div>`) + `
  ${sim ? `<div class="callout info"><b>Dry run.</b> Each step below is what MANDATE <i>would</i> decide right now, on a copy of the live state. Nothing was sent to the tools, nothing was recorded, nobody was quarantined. Document scanning needs real tool output, so it happens only when you run for real.</div>` : ""}
  ${r.status === "failed" ? `<div class="callout block" style="margin-top:12px"><b>The run stopped.</b> ${esc(r.error || "")}</div>` : ""}
  <section class="sect"><div class="grid g4">
    <div class="card stat"><div class="l">${sim ? "Would be allowed" : "Allowed"}</div><div class="v" style="color:var(--allow)">${by.ALLOW || 0}</div></div>
    <div class="card stat"><div class="l">${sim ? "Would be held" : "Held for you"}</div><div class="v" style="color:var(--held)">${by.APPROVAL_REQUIRED || 0}</div><div class="s">${(s.pending_approvals || []).length ? `${s.pending_approvals.length} waiting below` : ""}</div></div>
    <div class="card stat"><div class="l">${sim ? "Would be blocked" : "Blocked"}</div><div class="v" style="color:var(--block)">${by.DENY || 0}</div></div>
    <div class="card stat"><div class="l">What actually happened</div><div class="v">${sim ? "nothing" : effects.length}</div><div class="s">${sim ? "dry run" : "effects recorded by the tool server"}</div></div></div></section>
  <div class="split"><section class="card"><div class="eyebrow">Step by step</div><div class="wb-tl">
    ${r.events.map(e => {
      if (e.kind === "setup") return `<div class="wb-ev sys"><b>Set up</b><span class="ink2">${esc(e.what)}</span></div>`;
      if (e.kind === "note") return `<div class="wb-ev sys"><span class="ink2">${esc(e.what)}</span></div>`;
      if (e.kind === "error") return `<div class="wb-ev sys"><span class="tag block"><span class="d"></span>error</span> <span>${esc(e.what)}</span></div>`;
      if (e.kind === "model" && !e.tool_calls.length && r.final_answer) return `<div class="wb-ev model"><span class="eyebrow">Model · turn ${esc(e.turn)}</span><div class="ink2 small">Finished. The answer is shown on the right.</div></div>`;
      if (e.kind === "model") return `<div class="wb-ev model"><span class="eyebrow">Model · turn ${esc(e.turn)}</span>${e.content ? `<div class="wb-think">${esc(e.content)}</div>` : ""}${e.tool_calls.length ? `<div class="ink3 small">wants to: ${e.tool_calls.map(c => esc(toolH(c.name))).join(", ")}</div>` : ""}</div>`;
      if (e.kind === "owner") return `<div class="wb-ev sys"><b>You ${esc(e.what)}</b>${e.note ? ` <span class="ink3">“${esc(e.note)}”</span>` : ""}</div>`;
      const d = e.decision || {}, resp = d.response || (e.ok ? "ALLOW" : "DENY");
      const pend = (s.pending_approvals || []).find(a => a.id === d.approval_id);
      return `<div class="wb-ev">
        <div class="row"><span class="ink3 small">${e.source === "model" ? "The AI agent" : e.source === "owner-approved" ? "Approved retry" : sim ? "Plan step" : "Your step"}</span><span class="spacer"></span>${stamp(resp)}</div>
        <div style="margin-top:4px">wants to <b>${esc(toolH(e.tool))}</b>${argBrief(e.args)}</div>
        <div class="ink2" style="margin-top:4px">${explainEvent(e, sim)}</div>
        ${e.scan ? `<div style="margin-top:6px">${scanTag(e.scan)}</div>` : ""}
        ${sim ? "" : `<div class="ink3 small" style="margin-top:6px">${e.effects && e.effects.length ? `Tool server recorded: ${e.effects.map(x => esc(x.tool)).join(", ")}` : "Nothing happened at the tool server."}</div>`}
        ${pend ? (s.agent_status === "quarantined" ? `<div class="callout block" style="margin-top:8px">Waiting for your decision, but the agent is now <b>quarantined</b> (it attempted something outside its mandate), so an approved action could not run. Review it in <a href="#/agents">Agents &amp; mandates</a> and resume it with a reason before approving. <button class="sm danger" data-ap="${esc(pend.id)}" data-ok="0">Reject</button></div>`
          : `<div class="row" style="margin-top:8px"><button class="sm primary" data-ap="${esc(pend.id)}" data-ok="1">Approve once and run it</button><button class="sm danger" data-ap="${esc(pend.id)}" data-ok="0">Reject</button></div>`) : ""}
        <details class="tech mini"><summary>Evidence</summary><div><pre>${esc(JSON.stringify({ decision: e.decision, scan: e.scan, tool_server_effects: e.effects, result_seen_by_agent: e.result }, null, 1))}</pre>
          ${d.decision_id ? `<div class="row"><a class="btn sm" href="#/investigate?d=${esc(d.decision_id)}">Open in Decisions</a><button class="sm" data-pack="${esc(d.decision_id)}">Export verifiable evidence pack</button></div>` : ""}</div></details></div>`;
    }).join("") || empty("Starting…", "")}</div></section>
  <aside class="stack">
    ${r.final_answer ? `<section class="card"><div class="eyebrow">The agent's answer</div><div class="wb-think" style="margin-top:8px">${esc(r.final_answer)}</div>
      <p class="ink3 small" style="margin-top:8px">Written by the model. What it actually did is the timeline and the tool server's record, not this text.</p></section>` : ""}
    ${!sim && r.summary ? `<section class="card"><div class="eyebrow">Outcome</div><dl class="kv">
      <dt>Agent status</dt><dd>${statusTag(s.agent_status || "active")}</dd>
      <dt>Documents scanned</dt><dd>${(s.scans || []).length ? s.scans.map(x => `${esc(x.name || x.tool)}: ${x.verified === false ? "could not verify" : x.flagged ? "hidden instructions" : "clean"}`).join("<br>") : "none read"}</dd>
      <dt>Alerts</dt><dd>${(s.alerts || []).length ? s.alerts.map(a => `${esc(a.severity)} · ${esc(String(a.reason).slice(0, 90))}`).join("<br>") : "none"}</dd>
      <dt>Tool-server effects</dt><dd>${effects.length ? effects.map(x => `<span class="mono">${esc(x.tool)}</span>${x.simulated_delivery ? " (simulated)" : ""}`).join(", ") : "none"}</dd></dl>
      <div class="row" style="margin-top:12px"><a class="btn sm" href="#/graph">Attack map</a><a class="btn sm" href="#/audit">Audit trail</a><a class="btn sm" href="#/approvals">Approvals</a></div></section>` : ""}
    <section class="card flat"><div class="eyebrow">How to read this</div><ul class="wb-list small">
      <li>${stamp("ALLOW")} reached the tool. ${stamp("APPROVAL_REQUIRED")} paused until you decide; an approval works once. ${stamp("DENY")} never happened.</li>
      <li>Blocked and held actions are decided by the role catalogue and the rules, not by the instruction text.</li>
      <li>Document text is untrusted. If it's flagged or can't be verified, later writes and sends need your approval.</li></ul></section>
  </aside></div>`;
}

function wireRun(el, r) {
  el.querySelectorAll("[data-ap]").forEach(b => b.onclick = async () => {
    const ok = b.dataset.ok === "1";
    const note = await ask(ok ? "Approve this action once?" : "Reject this action?", `<p>${ok ? "It will run exactly once, through the checkpoint, and the tool server will record it." : "It will not run."} Your reason goes into the audit trail.</p>`, { ok: ok ? "Approve and run" : "Reject", danger: !ok });
    if (!note) return;
    el.querySelectorAll("[data-ap]").forEach(x => x.disabled = true);
    try { await act(`/console/workbench/runs/${encodeURIComponent(r.id)}/approvals/${encodeURIComponent(b.dataset.ap)}`, { approve: ok, note }); } catch (e) { alert(e.message); }
    VIEWS.taskrun(el);
  });
  el.querySelectorAll("[data-pack]").forEach(b => b.onclick = async () => {
    b.disabled = true; b.textContent = "Exporting…";
    try { const p = await http(`/console/evidence/${encodeURIComponent(b.dataset.pack)}`);
      const blob = new Blob([JSON.stringify(p, null, 1)], { type: "application/json" }); const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = `${b.dataset.pack}.evidence.json`; a.click(); URL.revokeObjectURL(a.href);
      b.textContent = (p._self_check || []).every(c => c.ok) ? "Exported · self-check verified" : "Exported · self-check FAILED"; }
    catch (e) { b.textContent = `Export failed: ${e.message}`; }
  });
}

