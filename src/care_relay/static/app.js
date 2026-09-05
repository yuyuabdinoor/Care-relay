const labels = {
  appointment: { icon: "◫", name: "Appointment" },
  transport: { icon: "↗", name: "Transportation" },
  referral: { icon: "⌁", name: "Referral handoff" },
  follow_up: { icon: "✓", name: "Follow-up" },
};
let state;
let decisionInFlight = false;
let pollTimer;

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  if (!response.ok) { const error = await response.json(); throw new Error(error.detail || "Something went wrong"); }
  return response.json();
}

function niceState(value) { return value.replaceAll("_", " "); }
function initials(agent) { return agent === "Verifier" ? "V" : agent === "Aisha" ? "A" : "C"; }
function fmtDate(value) { return new Date(value).toLocaleString("en-US", { weekday:"long", month:"long", day:"numeric", hour:"numeric", minute:"2-digit" }); }

function render(data) {
  state = data;
  document.querySelector("#case-id").textContent = data.case.id;
  document.querySelector("#readiness").textContent = `${data.case.readiness}%`;
  document.querySelector("#ring").style.setProperty("--progress", `${data.case.readiness * 3.6}deg`);
  document.querySelector("#headline-status").textContent = data.complete ? "ready" : data.approvals.length ? "waiting for you" : "being coordinated";
  document.querySelector("#headline-copy").textContent = data.complete ? "Every required commitment has independent evidence." : data.approvals.length ? "The agents have paused at a consequential decision." : "Care Relay is watching every commitment around this appointment.";
  const date = new Date(data.case.appointment_at);
  document.querySelector("#day").textContent = date.getDate();
  document.querySelector("#month").textContent = date.toLocaleString("en-US", {month:"short"}).toUpperCase();
  document.querySelector("#appointment-time").textContent = fmtDate(data.case.appointment_at);

  const liveAgent = document.querySelector("#live-agent");
  liveAgent.hidden = !data.can_start_agents && !data.can_process_event;
  liveAgent.disabled = false;
  liveAgent.innerHTML = data.can_process_event ? "<span class='spark'>✦</span> Process with Strands" : "<span class='spark'>✦</span> Continue Strands run";

  const hasRipple = data.commitments.filter(x => ["blocked","conflicted"].includes(x.state)).length > 1;
  const runtime = data.agent_runtime;
  document.querySelector("#reset").disabled = runtime.state === "running";
  const newestEvent = data.external_events?.[0];
  document.querySelector("#external-events").innerHTML = newestEvent ? `<div class="external-event"><span class="event-icon">↘</span><div><strong>${newestEvent.subject} <span class="event-source">· ${newestEvent.source}</span></strong><p>${newestEvent.message}</p></div><small>${newestEvent.channel}</small></div>` : "";
  const runtimeCopy = runtime.state === "running"
    ? "Coordinator and verifier are reasoning, delegating, and using tools now. This page will update as work completes."
    : runtime.state === "waiting_for_human"
      ? "The coordinator has been interrupted before a protected tool and is waiting for your decision."
      : runtime.state === "error"
        ? runtime.message
        : "Coordinator and verifier completed this execution boundary through Strands.";
  document.querySelector("#causal-alert").innerHTML = runtime.state !== "not_started" ? `<div class="agent-mode"><span class="pulse"></span><div><strong>Live Strands run: ${niceState(runtime.state)}</strong>${runtimeCopy}</div></div>` : hasRipple ? `<div class="ripple"><span>↯</span><div><strong>One change created a causal ripple</strong>The new appointment time invalidated commitments that depended on the old one. Care Relay opened only the affected work.</div></div>` : "";
  const dependencies = data.dependencies || [];
  const byId = Object.fromEntries(data.commitments.map(item => [item.id, item]));
  const referral = byId.referral;
  const misdirected = referral?.evidence?.find(item => item.kind === "fact" && item.summary.includes("required"));
  document.querySelector("#verification-insight").innerHTML = misdirected ? `<div class="verification-insight"><div class="insight-mark">≠</div><div><span>VERIFIER DISCOVERY</span><strong>Sent did not mean received</strong><p>${misdirected.summary}. Care Relay kept the visit open until Imaging independently accepted the correction.</p></div><div class="insight-state">${niceState(referral.state)}</div></div>` : "";
  const changedSources = new Set(dependencies.filter(edge => byId[edge.target_id]?.state === "blocked").map(edge => edge.source_id));
  document.querySelector("#dependency-map").innerHTML = data.stage > 0 && dependencies.length ? `<div class="dependency-map"><div class="dependency-map-label">causal graph</div><div class="dependency-source"><strong>${labels[byId[dependencies[0].source_id].kind].name}</strong><span>Time changed</span></div><div class="dependency-branches">${dependencies.map(edge => `<div class="dependency-edge"><span class="dependency-arrow">→</span><div class="dependency-target ${changedSources.has(edge.source_id) && byId[edge.target_id].state === "blocked" ? "affected" : ""}"><strong>${labels[byId[edge.target_id].kind].name}</strong><span>${edge.relation}</span><em class="edge-state ${byId[edge.target_id].state}">${niceState(byId[edge.target_id].state)}</em></div></div>`).join("")}</div></div>` : "";
  document.querySelector("#commitments").innerHTML = data.commitments.map(item => `<div class="commitment ${item.state}"><div class="node-icon">${labels[item.kind].icon}</div><h3>${labels[item.kind].name}</h3><p>${item.blocker || `${item.label}<br>Owner: ${item.owner || "Unassigned"}`}</p><span class="state">${niceState(item.state)}</span></div>`).join("");

  document.querySelector("#activity").innerHTML = data.activity.map(item => `<div class="activity-row"><span class="agent-dot">${initials(item.agent)}</span><div><strong>${item.agent}</strong><p>${item.message}</p></div><em>${item.kind}</em></div>`).join("");
  const tracePanel = document.querySelector("#trace-panel");
  tracePanel.hidden = !data.traces?.length;
  const traces = data.traces || [];
  const toolFinishes = traces.filter(item => item.event === "tool_finished");
  const successfulTools = toolFinishes.filter(item => item.details.status === "success");
  const agentCount = new Set(traces.map(item => item.agent)).size;
  const verifierActions = successfulTools.filter(item => item.agent === "verification_agent").length;
  const humanDecisions = data.ledger.filter(item => item.event_type === "approval_decided").length;
  document.querySelector("#trace-summary").innerHTML = traces.length ? `<div><strong>${agentCount}</strong><span>Strands agents</span></div><div><strong>${successfulTools.length}</strong><span>tools completed</span></div><div><strong>${verifierActions}</strong><span>independent checks</span></div><div><strong>${humanDecisions}</strong><span>human decisions</span></div>` : "";
  const significantTraces = traces.filter(item => item.event === "tool_finished" || (item.event === "run_stopped" && ["interrupt", "end_turn"].includes(item.details.stop_reason))).slice(-10).reverse();
  document.querySelector("#traces").innerHTML = significantTraces.map(item => `<div class="trace-row ${item.agent === "verification_agent" ? "verifier-trace" : ""}"><span class="trace-dot"></span><div><strong>${item.agent === "verification_agent" ? "Verifier" : "Coordinator"} · ${item.details.tool ? niceState(item.details.tool) : niceState(item.details.stop_reason)}</strong><p>${item.summary}</p><span class="trace-meta">#${item.sequence}${item.details.duration_ms ? ` · ${item.details.duration_ms} ms` : ""}</span></div></div>`).join("");
  const evidence = data.commitments.flatMap(item => item.evidence.map(ev => ({...ev, label: labels[item.kind].name}))).reverse().slice(0,6);
  document.querySelector("#evidence").innerHTML = evidence.map(ev => `<div class="evidence-item"><strong>${ev.label}</strong><p>${ev.summary}</p><span>${ev.kind} · ${ev.source}</span></div>`).join("");

  document.querySelector("#decision-zone").innerHTML = data.approvals.map(item => `<div class="decision-card"><div class="decision-icon">!</div><div><h3>Your approval is needed</h3><p>Send a correction to ${item.recipient}. Shares only: ${item.disclosure.join(", ")}.</p></div><div class="decision-actions">${data.can_restore_agents ? `<button class="approve" onclick="restoreAgents()">Restore paused agent</button>` : `<button onclick="decide('${item.approval_id}', false)">Decline</button><button class="approve" onclick="decide('${item.approval_id}', true)">Approve & send</button>`}</div></div>`).join("");
}

function monitorRun() {
  clearTimeout(pollTimer);
  if (state?.agent_runtime?.state !== "running") return;
  pollTimer = setTimeout(async () => {
    try {
      render(await api("/api/case"));
      monitorRun();
    } catch (error) {
      toast(error.message);
      monitorRun();
    }
  }, 700);
}

function toast(message) { const el=document.querySelector("#toast"); el.textContent=message;el.classList.add("show-toast");setTimeout(()=>el.classList.remove("show-toast"),2200); }
async function decide(id, approved) {
  if (decisionInFlight) return;
  decisionInFlight = true;
  document.querySelectorAll(".decision-actions button").forEach(button => { button.disabled = true; });
  try {
    render(await api("/api/agents/resume", {method:"POST",body:JSON.stringify({approval_id:id, approved})}));
    toast(approved ? "Approved. Agents are resuming safely." : "Decision recorded.");
    monitorRun();
  } catch(e) {
    toast(e.message);
    document.querySelectorAll(".decision-actions button").forEach(button => { button.disabled = false; });
  } finally {
    decisionInFlight = false;
  }
}
async function runLiveAgents() { const button=document.querySelector("#live-agent"); button.disabled=true;button.innerHTML="<span class='spark'>✦</span> Agents working…"; try { const eventMode=state.can_process_event; const path=eventMode ? "/api/agents/process-event" : "/api/agents/start"; const options={method:"POST"}; if(eventMode) options.body=JSON.stringify({source:"Northside Imaging",channel:"Email",subject:"Appointment time updated",message:"Daniel's imaging appointment has moved from Sep 10 at 10:00 AM to Sep 11 at 2:30 PM ET."}); render(await api(path,options)); toast("Strands agents started working in the background."); monitorRun(); } catch(e) { button.disabled=false;button.innerHTML="<span class='spark'>✦</span> Try live Strands";toast(e.message); } }
async function restoreAgents() { try { render(await api("/api/agents/restore", {method:"POST"})); toast("Paused Strands run restored. You can now decide."); } catch(e) { toast(e.message); } }
window.decide = decide;
window.restoreAgents = restoreAgents;
document.querySelector("#live-agent").addEventListener("click", runLiveAgents);
document.querySelector("#reset").addEventListener("click", async () => { render(await api("/api/demo/reset", {method:"POST"})); toast("Demo reset"); });
api("/api/case").then(data => { render(data); monitorRun(); }).catch(error => toast(error.message));
