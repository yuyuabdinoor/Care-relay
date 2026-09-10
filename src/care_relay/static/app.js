const labels = {
  appointment: { icon: "◫", name: "Appointment" },
  transport: { icon: "↗", name: "Transportation" },
  referral: { icon: "⌁", name: "Referral handoff" },
  follow_up: { icon: "✓", name: "Follow-up" },
};
let state;
let decisionInFlight = false;
let pollTimer;
let previousCommitmentStates = {};
let previousSystemStates = {};

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  if (!response.ok) { const error = await response.json(); throw new Error(error.detail || "Something went wrong"); }
  return response.json();
}

function niceState(value) { return value.replaceAll("_", " "); }
function stateLabel(value) {
  const marks = { verified: "✓", claimed: "“ ”", blocked: "!", conflicted: "!", needs_approval: "◇", pending: "○" };
  return `${marks[value] || "○"} ${niceState(value)}`;
}
function agentClass(agent) { return agent === "Verifier" ? "verifier" : agent === "Aisha" ? "human" : "coordinator"; }
function initials(agent) { return agent === "Verifier" ? "V" : agent === "Aisha" ? "A" : "C"; }
function fmtDate(value) { return new Date(value).toLocaleString("en-US", { weekday:"long", month:"long", day:"numeric", hour:"numeric", minute:"2-digit" }); }
function shortDate(value) { return value ? new Date(value).toLocaleString("en-US", {month:"short", day:"numeric", hour:"numeric", minute:"2-digit"}) : "Not scheduled"; }
function escapeHtml(value) {
  const entities = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" };
  return String(value ?? "").replace(/[&<>"']/g, character => entities[character]);
}
function safeLayer(value) { return ["agent", "code", "evidence"].includes(value) ? value : "agent"; }
function safeState(value) { return ["discovered", "assigned", "verified", "claimed", "blocked", "conflicted", "needs_approval", "pending"].includes(value) ? value : "pending"; }
function safeEvidenceKind(value) { return ["fact", "claim", "verification", "inference"].includes(value) ? value : "inference"; }
function safeRuntimeState(value) { return ["not_started", "running", "waiting_for_human", "error", "completed"].includes(value) ? value : "error"; }

function render(data) {
  state = data;
  document.querySelector("#case-id").textContent = data.case.id;
  document.querySelector("#readiness").textContent = `${data.case.readiness}%`;
  document.querySelector("#ring").style.setProperty("--progress", `${data.case.readiness * 3.6}deg`);
  const verifiedCount = data.commitments.filter(item => item.state === "verified").length;
  const runtime = data.agent_runtime;
  document.querySelector("#readiness-note").textContent = `${verifiedCount} of ${data.commitments.length} independently verified`;
  document.querySelector("#headline-status").textContent = data.complete ? "ready" : runtime.state === "error" ? "paused" : data.approvals.length ? "waiting for you" : runtime.state === "running" ? "being coordinated" : "under watch";
  document.querySelector("#headline-copy").textContent = data.complete ? "Every required commitment has independent evidence." : runtime.state === "error" ? "The case is preserved, but live agent work needs the AWS connection restored." : data.approvals.length ? "The agents have paused at a consequential decision." : "Care Relay is watching every commitment around this appointment.";
  const runtimeChip = document.querySelector("#runtime-chip");
  runtimeChip.className = `quiet-chip runtime-${safeRuntimeState(runtime.state)}`;
  runtimeChip.innerHTML = `<span class="pulse"></span>${runtime.state === "running" ? "Agents working" : runtime.state === "waiting_for_human" ? "Waiting for Aisha" : runtime.state === "error" ? "Connection needed" : data.complete ? "Visit ready" : "Live case"}`;
  const date = new Date(data.case.appointment_at);
  document.querySelector("#day").textContent = date.getDate();
  document.querySelector("#month").textContent = date.toLocaleString("en-US", {month:"short"}).toUpperCase();
  document.querySelector("#appointment-time").textContent = fmtDate(data.case.appointment_at);

  const liveAgent = document.querySelector("#live-agent");
  liveAgent.hidden = !data.can_start_agents && !data.can_process_event;
  liveAgent.disabled = false;
  liveAgent.innerHTML = data.can_process_event ? "<span class='spark'>✦</span> Receive provider update" : data.can_start_agents ? "<span class='spark'>✦</span> Start live Strands run" : "<span class='spark'>✦</span> Continue Strands run";

  const hasRipple = data.commitments.filter(x => ["blocked","conflicted"].includes(x.state)).length > 1;
  document.querySelector("#reset").disabled = runtime.state === "running";
  const newestEvent = data.external_events?.[0];
  document.querySelector("#external-events").innerHTML = newestEvent ? `<div class="external-event"><span class="event-icon">↘</span><div><strong>${escapeHtml(newestEvent.subject)} <span class="event-source">· ${escapeHtml(newestEvent.source)}</span></strong><p>${escapeHtml(newestEvent.message)}</p></div><small>${escapeHtml(newestEvent.channel)}</small></div>` : "";
  const runtimeCopy = runtime.state === "running"
    ? "Coordinator and verifier are reasoning, delegating, and using tools now. This page will update as work completes."
    : runtime.state === "waiting_for_human"
      ? "The coordinator has been interrupted before a protected tool and is waiting for your decision."
      : runtime.state === "error"
        ? runtime.message
        : "Coordinator and verifier completed this execution boundary through Strands.";
  document.querySelector("#causal-alert").innerHTML = runtime.state !== "not_started" ? `<div class="agent-mode"><span class="pulse"></span><div><strong>Live Strands run: ${escapeHtml(niceState(runtime.state))}</strong>${escapeHtml(runtimeCopy)}</div></div>` : hasRipple ? `<div class="ripple"><span>↯</span><div><strong>One change created a causal ripple</strong>The new appointment time invalidated commitments that depended on the old one. Care Relay opened only the affected work.</div></div>` : "";
  const dependencies = data.dependencies || [];
  const byId = Object.fromEntries(data.commitments.map(item => [item.id, item]));
  const referral = byId.referral;
  const misdirected = referral?.evidence?.find(item => item.kind === "fact" && item.summary.includes("required"));
  const correctionSent = referral?.evidence?.some(item => item.summary.includes("Corrected referral was transmitted"));
  const correctionVerified = referral?.evidence?.some(item => item.summary.includes("confirmed receipt and acceptance"));
  const approval = data.ledger.find(item => item.event_type === "approval_decided");
  const approvalStep = approval ? (approval.details.approved ? `<li class="done"><b>◇</b><span>Aisha approved</span></li>` : `<li class="stopped"><b>×</b><span>Aisha declined</span></li>`) : `<li class="current"><b>◇</b><span>Approval required</span></li>`;
  document.querySelector("#verification-insight").innerHTML = misdirected ? `<div class="verification-insight"><div class="insight-mark">≠</div><div class="insight-copy"><em class="provenance-label layer-agent">Chosen by agent</em><span>Verifier discovery</span><strong>Sent did not mean received</strong><p>${escapeHtml(misdirected.summary)}.</p><ol class="evidence-chain"><li class="done"><b>“ ”</b><span>Clinic claimed sent</span></li><li class="fact"><b>!</b><span>Imaging reported missing</span></li>${approvalStep}${correctionSent ? `<li class="done"><b>→</b><span>Correction transmitted</span></li>` : ""}${correctionVerified ? `<li class="done"><b>✓</b><span>Imaging confirmed receipt</span></li>` : ""}</ol><p class="counterfactual">A system that trusted the original claim would have marked this handoff complete.</p></div><div><em class="provenance-label layer-evidence">Confirmed by evidence</em><div class="insight-state">${escapeHtml(stateLabel(referral.state))}</div></div></div>` : "";
  const changedSources = new Set(dependencies.filter(edge => byId[edge.target_id]?.state === "blocked").map(edge => edge.source_id));
  document.querySelector("#dependency-map").innerHTML = data.stage > 0 && dependencies.length ? `<div class="dependency-map"><div class="dependency-map-label">causal graph</div><em class="provenance-label layer-code graph-provenance">Enforced by code</em><div class="dependency-source"><strong>${escapeHtml(labels[byId[dependencies[0].source_id].kind].name)}</strong><span>Time changed</span></div><div class="dependency-branches">${dependencies.map(edge => `<div class="dependency-edge"><span class="dependency-arrow">→</span><div class="dependency-target ${changedSources.has(edge.source_id) && byId[edge.target_id].state === "blocked" ? "affected" : ""}"><strong>${escapeHtml(labels[byId[edge.target_id].kind].name)}</strong><span>${escapeHtml(edge.relation)}</span><em class="edge-state ${safeState(byId[edge.target_id].state)}">${escapeHtml(niceState(byId[edge.target_id].state))}</em></div></div>`).join("")}</div><p class="graph-note">Referral was discovered independently during verification—not caused by this appointment ripple.</p></div>` : "";
  document.querySelector("#commitments").innerHTML = data.commitments.map(item => `<div class="commitment ${safeState(item.state)} ${previousCommitmentStates[item.id] && previousCommitmentStates[item.id] !== item.state ? "state-changed" : ""}"><div class="node-icon">${escapeHtml(labels[item.kind].icon)}</div><h3>${escapeHtml(labels[item.kind].name)}</h3><p>${item.blocker ? escapeHtml(item.blocker) : `${escapeHtml(item.label)}<br>Owner: ${escapeHtml(item.owner || "Unassigned")}`}</p><span class="state">${escapeHtml(stateLabel(item.state))}</span></div>`).join("");
  previousCommitmentStates = Object.fromEntries(data.commitments.map(item => [item.id, item.state]));

  const systems = data.connected_systems;
  const calendarMoved = Boolean(systems.calendar.previous_appointment_at);
  const googleCalendar = systems.calendar.backend === "google";
  const calendarConfirmation = systems.calendar.confirmation;
  const rideAccepted = systems.family_messages.status === "verified";
  const portal = systems.provider_portal;
  const portalStatus = portal.receipt_verified ? "Received and accepted" : portal.correction_sent ? "Correction delivered" : portal.discovered_destination ? "Wrong destination found" : "Sender reports sent";
  const systemStates = {
    calendar: `${systems.calendar.appointment_at}|${systems.calendar.follow_up_at}|${calendarConfirmation?.provider_updated_at || ""}`,
    messages: `${systems.family_messages.driver}|${systems.family_messages.status}`,
    portal: `${portal.state}|${portal.correction_sent}|${portal.receipt_verified}`,
  };
  const changed = key => previousSystemStates[key] && previousSystemStates[key] !== systemStates[key] ? "system-changed" : "";
  document.querySelector("#system-proof").textContent = googleCalendar ? "Google Calendar connected" : "Tool-backed demo services";
  const initialFollowUp = systems.calendar.initial_follow_up_at;
  const calendarLink = googleCalendar && calendarConfirmation?.html_link?.startsWith("https://www.google.com/calendar/")
    ? `<a class="calendar-external-link" href="${escapeHtml(calendarConfirmation.html_link)}" target="_blank" rel="noopener">Open in Google Calendar ↗</a>`
    : "";
  document.querySelector("#connected-systems").innerHTML = `
    <section class="system-card ${changed("calendar")}">
      <div class="system-card-head"><span class="system-icon calendar-icon">▦</span><div><b>${googleCalendar ? "Google Calendar" : "Family calendar"}</b><small>${calendarConfirmation ? `${googleCalendar ? "External" : "Demo"} event confirmed` : calendarMoved ? "Schedule needs repair" : "Original schedule"}</small></div><em>${calendarConfirmation ? "CONFIRMED" : calendarMoved ? "CHANGED" : "WATCHING"}</em></div>
      ${calendarMoved ? `<div class="calendar-old"><span>${shortDate(systems.calendar.previous_appointment_at)}</span><s>Imaging appointment</s></div>` : ""}
      <div class="calendar-event"><span>${shortDate(systems.calendar.appointment_at)}</span><strong>Imaging appointment</strong><small>Northside Imaging · Building C</small></div>
      ${systems.calendar.follow_up_at ? `<div class="calendar-followup"><span>${shortDate(systems.calendar.follow_up_at)}</span><b>Follow-up moved after imaging</b><i>✓ ${googleCalendar ? "Google confirmed" : "Calendar confirmed"}</i></div>${calendarLink}` : calendarMoved ? `<div class="calendar-followup calendar-invalid"><span>${shortDate(initialFollowUp)}</span><b>Riverside follow-up</b><i>! Now occurs before imaging</i></div>` : `<div class="calendar-followup calendar-initial"><span>${shortDate(initialFollowUp)}</span><b>Riverside follow-up</b><i>✓ Valid after imaging</i></div>`}
    </section>
    <section class="system-card ${changed("messages")}">
      <div class="system-card-head"><span class="system-icon message-icon">↗</span><div><b>Family messages</b><small>Approved transport circle</small></div><em>${rideAccepted ? "ACCEPTED" : calendarMoved ? "NEEDS RIDE" : "ARRANGED"}</em></div>
      ${calendarMoved ? `<div class="message-bubble old-message"><b>Marcus</b><span>My ride was for ${shortDate(systems.calendar.previous_appointment_at)}.</span></div>` : `<div class="message-bubble"><b>Marcus</b><span>I can drive Daniel to the appointment.</span></div>`}
      ${rideAccepted ? `<div class="message-bubble accepted-message"><b>${escapeHtml(systems.family_messages.driver)}</b><span>Accepted the new pickup for ${escapeHtml(shortDate(systems.family_messages.appointment_at))}.</span><i>✓ Confirmed</i></div>` : calendarMoved ? `<div class="message-search"><span></span>Care Relay is checking approved family...</div>` : ""}
    </section>
    <section class="system-card portal-card ${changed("portal")}">
      <div class="system-card-head"><span class="system-icon portal-icon">⌁</span><div><b>Provider portal</b><small>Referral delivery record</small></div><em class="portal-state-${safeState(portal.state)}">${escapeHtml(portalStatus.toUpperCase())}</em></div>
      <div class="portal-route"><small>Original transmission</small><strong>Riverside Orthopedics</strong><span>→</span><b>${escapeHtml(portal.discovered_destination || "Destination not independently checked")}</b></div>
      ${portal.discovered_destination ? `<div class="portal-warning">! Required destination: ${escapeHtml(portal.required_destination)}</div>` : `<p class="system-wait">Claim recorded. Independent receipt check pending.</p>`}
      ${portal.correction_sent ? `<div class="portal-correction"><span>TX-8842</span><b>Correction sent to Imaging</b><em>${portal.receipt_verified ? "✓ Receipt verified" : "Awaiting receipt"}</em></div>` : ""}
    </section>`;
  previousSystemStates = systemStates;

  document.querySelector("#activity").innerHTML = data.activity.map(item => `<div class="activity-row ${agentClass(item.agent)} activity-${safeLayer(item.layer)}"><span class="agent-dot">${initials(item.agent)}</span><div><strong>${escapeHtml(item.agent)}</strong><span class="provenance-label layer-${safeLayer(item.layer)}">${item.layer === "code" ? "Enforced by code" : item.layer === "evidence" ? "Confirmed by evidence" : "Chosen by agent"}</span><p>${escapeHtml(item.message)}</p></div><em>${escapeHtml(item.duration || item.kind)}</em></div>`).join("");
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
  document.querySelector("#traces").innerHTML = significantTraces.map(item => `<div class="trace-row ${item.agent === "verification_agent" ? "verifier-trace" : ""}"><span class="trace-dot"></span><div><strong>${item.agent === "verification_agent" ? "Verifier" : "Coordinator"} · ${escapeHtml(item.details.tool ? niceState(item.details.tool) : niceState(item.details.stop_reason))}</strong><p>${escapeHtml(item.summary)}</p><span class="trace-meta">#${escapeHtml(item.sequence)}${item.details.duration_ms ? ` · ${escapeHtml(item.details.duration_ms)} ms` : ""}</span></div></div>`).join("");
  const evidence = data.commitments.flatMap(item => item.evidence.map(ev => ({...ev, label: labels[item.kind].name}))).reverse().slice(0,6);
  document.querySelector("#evidence").innerHTML = evidence.length ? `<div class="evidence-item evidence-latest"><strong>${escapeHtml(evidence[0].label)}</strong><p>${escapeHtml(evidence[0].summary)}</p><span class="evidence-kind kind-${safeEvidenceKind(evidence[0].kind)}">${escapeHtml(evidence[0].kind)} · ${escapeHtml(evidence[0].source)}</span></div>${evidence.length > 1 ? `<details class="evidence-more"><summary>View ${evidence.length - 1} earlier evidence records</summary>${evidence.slice(1).map(ev => `<div class="evidence-item"><strong>${escapeHtml(ev.label)}</strong><p>${escapeHtml(ev.summary)}</p><span class="evidence-kind kind-${safeEvidenceKind(ev.kind)}">${escapeHtml(ev.kind)} · ${escapeHtml(ev.source)}</span></div>`).join("")}</details>` : ""}` : "";

  const errorNotice = runtime.state === "error" ? `<div class="system-alert"><div class="system-alert-mark">!</div><div><strong>Live agent connection paused</strong><p>${escapeHtml(runtime.message)}</p></div><span>Case state preserved</span></div>` : "";
  const approvalNotices = data.approvals.map(item => `<div class="decision-card"><div class="decision-icon">!</div><div><h3>Your approval is needed</h3><p>Send a correction to ${escapeHtml(item.recipient)}. Shares only: ${item.disclosure.map(escapeHtml).join(", ")}.</p></div><div class="decision-actions">${data.can_restore_agents ? `<button class="approve" data-restore-agent>Restore paused agent</button>` : `<button data-approval-id="${escapeHtml(item.approval_id)}" data-approved="false">Decline</button><button class="approve" data-approval-id="${escapeHtml(item.approval_id)}" data-approved="true">Approve & send</button>`}</div></div>`).join("");
  document.querySelector("#decision-zone").innerHTML = errorNotice + approvalNotices;
  document.querySelectorAll("[data-approval-id]").forEach(button => button.addEventListener("click", () => decide(button.dataset.approvalId, button.dataset.approved === "true")));
  document.querySelectorAll("[data-restore-agent]").forEach(button => button.addEventListener("click", restoreAgents));
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
