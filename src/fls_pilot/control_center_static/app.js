// ─── State ───────────────────────────────────────────────────────────────────
const state = {
  status: null,
  report: "",
  mixReview: {
    loading: false,
    report: null,
    error: null
  },
  lowEndAnalysis: {
    loading: false,
    report: null,
    error: null
  },
  routingAudit: {
    loading: false,
    report: null,
    error: null,
    level2: {
      stage: "idle",
      decision: null,
      markerName: null,
      loopDurationSeconds: null
    }
  },
  projectOrganizer: {
    loading: false,
    report: null,
    error: null
  },
  projectHealth: {
    loading: false,
    error: null,
    lastRun: null
  },
  transport: {
    loading: false,
    polling: false,
    error: null,
    pollTimer: null,
    lastAppliedKey: "",
    lastMetric: null,
    lastPlaying: false,
    lastLivePosition: null,
    stopResetDetected: false,
    wrapCount: 0
  },
  audioAnalysis: {
    loading: false,
    jobs: [],
    activeJob: null,
    report: null,
    error: null,
    pollTimer: null
  },
  runtimeWorkflows: {},
  workflowUserDecisions: {},
  setupFeedback: {},
  actionFeedback: {},
  evidenceKeys: new Set()
};

// ─── Terminology Constants ────────────────────────────────────────────────────
const TERMINOLOGY = {
  stateLabels: {
    blocked: "Action needed",
    needs_manual_action: "Action needed",
    disconnected: "Not connected",
    partial: "Partial",
    connected: "Connected",
    live: "Connected",
    ready_for_review: "Ready",
    ready_for_write_tools: "Ready",
    stopped: "Not running",
    running: "Running",
    external: "Running",
    unavailable: "Unavailable",
    checking: "Checking",
  }
};

const DEFAULT_WORKFLOW_CATALOG = [
  { id: "project_health", panel_id: "producer_health", title: "Health", group: "Project Review", maturity: "read_only", enabled: true, endpoint: null, client_action: "runProjectHealth", action_label: "Run Health Scan", safety_note: "Read-only overview across available workflow reports." },
  { id: "mix_review", panel_id: "producer_mix_review", title: "Mix Review", group: "Project Review", maturity: "read_only", enabled: true, endpoint: "/api/workflows/mix-review", action_label: "Run Mix Review", safety_note: "Read-only mixer review. No project changes are made." },
  { id: "routing_audit", panel_id: "producer_routing", title: "Routing Audit", group: "Project Review", maturity: "read_only", enabled: true, endpoint: "/api/workflows/routing-audit", action_label: "Run Routing Audit", safety_note: "Read-only routing audit. Cleanup remains proposal-first." },
  { id: "low_end_analysis", panel_id: "producer_low_end", title: "Low-End Analysis", group: "Project Review", maturity: "read_only", enabled: true, endpoint: "/api/workflows/low-end-analysis", action_label: "Run Low-End Analysis", safety_note: "Read-only low-end and stereo safety review." },
  { id: "audio_evidence", panel_id: "producer_audio_evidence", title: "Audio Evidence", group: "Project Review", maturity: "read_only", enabled: true, endpoint: "/api/audio-analysis", action_label: "Analyze Audio", safety_note: "Offline analysis of a user-selected file. Source audio and FL Studio projects are not modified." },
  { id: "project_organizer", panel_id: "producer_organizer", title: "Organizer", group: "Project Review", maturity: "read_only", enabled: true, endpoint: "/api/workflows/project-organizer", action_label: "Run Organizer", safety_note: "Read-only scan. Any cleanup requires an approved safe-write tool." },
  { id: "preflight", panel_id: "producer_preflight", title: "Preflight", group: "Project Review", maturity: "read_only", enabled: true, endpoint: "/api/workflows/preflight", action_label: "Run Preflight", safety_note: "Read-only export-readiness review. Render, save, export, and mastering remain manual." },
  { id: "jam_2_project", panel_id: "producer_jam_2_project", title: "Jam 2 Project", group: "Roadmap", maturity: "planned", enabled: false, endpoint: null, action_label: null, safety_note: "Planned for v3.1+. No Control Center action is available in v3.0." },
  { id: "sidechain_routing_check", panel_id: "producer_sidechaining", title: "Sidechain Routing Check", group: "Roadmap", maturity: "planned", enabled: false, endpoint: null, action_label: null, safety_note: "Planned after v3.0. Plugin detector settings remain a manual check." },
  { id: "plugin_assistant", panel_id: "producer_plugin_assistant", title: "Plugin Assistant", group: "Roadmap", maturity: "planned", enabled: false, endpoint: null, action_label: null, safety_note: "Planned after v3.0. Plugin loading remains manual." },
  { id: "preset_assistant", panel_id: "producer_preset_assistant", title: "Preset Assistant", group: "Roadmap", maturity: "planned", enabled: false, endpoint: null, action_label: null, safety_note: "Planned after v3.0. Preset loading remains manual." }
];

const ROUTING_LEVEL2_MARKER_NAMES = [
  "loudest",
  "loudest section",
  "drop",
  "main drop",
  "chorus",
  "full mix",
  "test loop",
  "routing test",
  "analysis loop"
];

// ─── Setup Doctor Layers ──────────────────────────────────────────────────────
const setupLayers = [
  { group: "environment",  title: "Environment",                priority: "required" },
  { group: "daemon",       title: "FL Studio Bridge Service",   priority: "required" },
  { group: "midi",         title: "MIDI Loopback Ports",        priority: "required" },
  { group: "controller",  title: "FL Studio Controller",        priority: "required" },
  { group: "mcp_sse",     title: "AI Client Server",            priority: "optional" },
  { group: "mcp_apply",   title: "Piano Roll Apply",            priority: "optional" }
];

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** Safe value for normal UI – never shows [object Object] */
function safeString(value) {
  if (value == null || value === "") return "Unavailable";
  if (typeof value === "object") return "Unavailable";
  return String(value);
}

/** Safe value for Advanced/Debug/Logs contexts – pretty-prints objects */
function safeDebugString(value) {
  if (value == null || value === "") return "Unavailable";
  if (typeof value === "object") {
    try { return JSON.stringify(value, null, 2); } catch { return "Unavailable"; }
  }
  return String(value);
}

function workflowCatalog() {
  const catalog = state.status?.ui?.workflow_catalog;
  return Array.isArray(catalog) && catalog.length ? catalog : DEFAULT_WORKFLOW_CATALOG;
}

function workflowById(id) {
  return workflowCatalog().find(item => item.id === id) || null;
}

function workflowByPanel(panelId) {
  return workflowCatalog().find(item => item.panel_id === panelId) || null;
}

function maturityLabel(value) {
  const labels = {
    beta: "Read-only",
    preview: "Read-only",
    read_only: "Read-only",
    planned: "Planned",
  };
  return labels[value] || safeString(value);
}

function maturityBadgeClass(value, enabled = true) {
  if (!enabled || value === "planned") return "badge-planned";
  if (value === "beta" || value === "preview" || value === "read_only") return "badge-ok";
  return "badge-pro-preview";
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  const type = response.headers.get("content-type") || "";
  return type.includes("application/json") ? response.json() : response.text();
}

function statusReportData() {
  return getStatusReport() || {};
}

function setStatusTransport(transport) {
  if (!state.status || !transport) return;
  const report = getStatusReport();
  if (report) report.transport = transport;
  if (state.status.status_report) state.status.status_report.transport = transport;
  if (state.status.dashboard) state.status.dashboard.transport = transport;
}

function positionMetric(position) {
  if (!position || typeof position !== "object") return null;
  for (const key of ["position_beats", "beats", "position_ticks", "ticks", "position_ms", "ms"]) {
    const value = Number(position[key]);
    if (Number.isFinite(value)) return { key, value };
  }
  return null;
}

function observeTransport(transport, sourceKey = "") {
  if (!transport || typeof transport !== "object") return;
  const playing = Boolean(transport.playing);
  const metric = positionMetric(transport.song_position);
  const key = [
    sourceKey,
    playing ? "playing" : "stopped",
    transport.recording ? "recording" : "idle",
    metric ? `${metric.key}:${metric.value}` : "no-position"
  ].join("|");
  if (key && key === state.transport.lastAppliedKey) return;
  state.transport.lastAppliedKey = key;

  if (playing && metric) {
    if (
      state.transport.lastPlaying
      && state.transport.lastMetric
      && state.transport.lastMetric.key === metric.key
      && metric.value + 0.5 < state.transport.lastMetric.value
    ) {
      state.transport.wrapCount += 1;
    }
    state.transport.lastMetric = metric;
    state.transport.lastLivePosition = transport.song_position;
    state.transport.stopResetDetected = false;
  }

  if (!playing && state.transport.lastPlaying && metric && state.transport.lastMetric) {
    state.transport.stopResetDetected =
      state.transport.lastMetric.key === metric.key
      && metric.value + 0.5 < state.transport.lastMetric.value;
  }
  state.transport.lastPlaying = playing;
}

function applyTransportSnapshot(transport, sourceKey = "") {
  if (!transport || typeof transport !== "object") return;
  setStatusTransport(transport);
  observeTransport(transport, sourceKey);
}

async function refreshTransportStatus() {
  if (state.transport.loading || state.transport.polling) return;
  state.transport.polling = true;
  try {
    const response = await api("/api/transport", {
      method: "POST",
      body: JSON.stringify({ action: "get_status" })
    });
    if (!response.ok) throw new Error(response.error || "Transport unavailable");
    applyTransportSnapshot(response.transport, `transport:${Date.now()}`);
    state.transport.error = null;
    renderProjectData();
    renderLivePlaybackMounts();
  } catch (error) {
    state.transport.error = error.message;
    renderTransportFeedback(error.message, true);
  } finally {
    state.transport.polling = false;
  }
}

async function transportAction(action, params = {}) {
  state.transport.loading = true;
  renderTransportButtons();
  try {
    const response = await api("/api/transport", {
      method: "POST",
      body: JSON.stringify({ action, params })
    });
    if (!response.ok) throw new Error(response.error || "Transport action failed");
    applyTransportSnapshot(response.transport, `action:${action}:${Date.now()}`);
    state.transport.error = null;
    renderTransportFeedback(transportActionLabel(action, response.result));
    renderProjectData();
    renderLivePlaybackMounts();
  } catch (error) {
    state.transport.error = error.message;
    renderTransportFeedback(error.message, true);
  } finally {
    state.transport.loading = false;
    renderTransportButtons();
  }
}

function transportActionLabel(action, result) {
  const labels = {
    play: "Playback started.",
    pause: "Playback paused.",
    stop: "Playback stopped.",
    record: result?.recording ? "Record armed. Press Play to record." : "Record disarmed.",
    jump_to_marker: "Moved to marker.",
    jump_marker_relative: "Moved to marker.",
    set_song_position: "Playhead moved."
  };
  return labels[action] || "Transport updated.";
}

function syncTransportPolling(live) {
  if (window.__FLS_PILOT_TEST__) return;
  if (live && !state.transport.pollTimer) {
    state.transport.pollTimer = setInterval(refreshTransportStatus, 1000);
  } else if (!live && state.transport.pollTimer) {
    clearInterval(state.transport.pollTimer);
    state.transport.pollTimer = null;
  }
}

let loadingInterval = null;

async function refresh() {
  const loadingOverlay = document.getElementById("loading-overlay");
  const loadingText = document.getElementById("loading-text");

  if (loadingOverlay) {
    loadingOverlay.style.display = "flex";
    let isPerforming = true;
    if (loadingText) loadingText.textContent = "Checking status...";
    if (loadingInterval) clearInterval(loadingInterval);
    loadingInterval = setInterval(() => {
      isPerforming = !isPerforming;
      if (loadingText) loadingText.textContent = isPerforming ? "Checking status..." : "Loading results...";
    }, 1500);
  }

  try {
    state.status = await api("/api/refresh", { method: "POST", body: "{}" });
    render();
  } catch (error) {
    const refreshTime = document.getElementById("refresh-time");
    if (refreshTime) refreshTime.textContent = "Error";
    const bridgePill = document.getElementById("bridge-pill");
    if (bridgePill) {
      bridgePill.textContent = "Error";
      bridgePill.className = "pill pill-offline";
    }
  } finally {
    if (loadingOverlay) loadingOverlay.style.display = "none";
    if (loadingInterval) { clearInterval(loadingInterval); loadingInterval = null; }
  }
}

// ─── Status data accessor (supports both status_report and dashboard keys) ───
function getStatusReport() {
  if (!state.status) return null;
  return state.status.status_report || state.status.dashboard || null;
}

// ─── Render coordinator ───────────────────────────────────────────────────────
function render() {
  if (!state.status) return;

  const data = getStatusReport();
  const bridge = data?.bridge || {};
  const live = bridge.state === "live";

  // Topbar readiness pill
  const rawState = state.status.readiness?.state || "unavailable";
  let stateLabel = live ? "LIVE" : (TERMINOLOGY.stateLabels[rawState] || rawState.replaceAll("_", " ").toUpperCase());

  const bridgePill = document.getElementById("bridge-pill");
  if (bridgePill) {
    bridgePill.textContent = stateLabel;
    bridgePill.className = (live || stateLabel === "READY" || stateLabel === "CONNECTED")
      ? "pill pill-live" : "pill pill-offline";
  }

  const versionPill = document.getElementById("version-pill");
  if (versionPill && state.status.version) {
    const v = state.status.version.startsWith("v") ? state.status.version : "v" + state.status.version;
    versionPill.textContent = v.toUpperCase();
  }

  const refreshTime = document.getElementById("refresh-time");
  if (refreshTime) refreshTime.textContent = new Date().toLocaleTimeString();

  renderOverview();
  renderConnectionCheck();
  renderSetup();
  renderRuntime();
  renderClients();
  renderProjectData();
  renderLivePlaybackMounts();
  renderMixReview();
  renderLowEndAnalysis();
  renderAudioAnalysis();
  renderRoutingAudit();
  renderProjectOrganizer();
  renderProjectHealth();
  renderRuntimeProductPanels();
  renderLogsHistory();
  renderPorts();
  renderConnection();
  renderWorkflowCatalogState();
  renderWorkflowMetadataCatalog();
  renderPlannedWorkflows();
  renderNextAction();
  renderConnectionReadyBanner();
  syncTransportPolling(live);
}

function renderWorkflowCatalogState() {
  const catalog = workflowCatalog();
  for (const item of catalog) {
    const nav = document.querySelector(`[data-workflow-id="${item.id}"]`);
    if (nav) {
      nav.classList.toggle("nav-item-disabled", item.enabled === false);
      nav.disabled = false;
      nav.title = item.enabled === false ? item.safety_note || "Planned workflow." : "";
      const badge = nav.querySelector(".nav-badge");
      if (badge) {
        badge.textContent = maturityLabel(item.maturity);
        badge.className = `nav-badge ${maturityBadgeClass(item.maturity, item.enabled !== false)}`;
      }
    }
  }
}

function renderWorkflowMetadataCatalog() {
  const container = document.getElementById("workflow-metadata-catalog");
  if (!container) return;
  container.innerHTML = "";
  for (const item of workflowCatalog()) {
    const card = document.createElement("article");
    card.className = "panel roadmap-card";

    const heading = document.createElement("div");
    heading.className = "panel-heading";
    const title = document.createElement("h2");
    title.textContent = item.title;
    heading.appendChild(title);
    for (const badgeData of workflowMetadataBadges(item)) {
      const badge = document.createElement("span");
      badge.className = `badge ${badgeData.className}`;
      badge.textContent = badgeData.label;
      heading.appendChild(badge);
    }

    const body = document.createElement("div");
    body.className = "roadmap-card-body";
    const note = document.createElement("p");
    note.textContent = item.safety_note || "No additional workflow note.";
    body.appendChild(note);

    for (const extension of workflowPackExtensions(item)) {
      const pack = document.createElement("p");
      pack.textContent = `${extension.pack_title || extension.pack_id} ${extension.pack_version || ""}`.trim();
      body.appendChild(pack);
      for (const profile of Array.isArray(extension.profiles) ? extension.profiles : []) {
        const profileRow = document.createElement("p");
        profileRow.textContent = `Profile: ${profile.title || profile.id}`;
        body.appendChild(profileRow);
      }
    }

    card.append(heading, body);
    container.appendChild(card);
  }
}

function workflowPackExtensions(item) {
  const extensions = item?.metadata?.pack_extensions;
  return Array.isArray(extensions) ? extensions : [];
}

function workflowMetadataBadges(item) {
  const badges = [];
  const extensions = workflowPackExtensions(item);
  if (extensions.length) badges.push({ label: "Pack", className: "badge-pro-preview" });
  if (item.enabled === false || item.maturity === "planned") {
    badges.push({ label: "Planned", className: "badge-planned" });
  } else if (item.maturity === "read_only" || item.maturity === "beta" || item.maturity === "preview") {
    badges.push({ label: "Read-only", className: "badge-ok" });
  }
  const locked = item.locked === true
    || item.metadata?.locked === true
    || extensions.some(extension => extension.metadata?.locked === true);
  if (locked) badges.push({ label: "Locked", className: "badge-warn" });

  const entitlementKinds = new Set(
    extensions.map(extension => extension.entitlement?.kind).filter(Boolean)
  );
  if (entitlementKinds.has("pro") || entitlementKinds.has("sku")) {
    badges.push({ label: "Pro", className: "badge-pro-preview" });
  }

  const genres = new Set();
  for (const extension of extensions) {
    if (extension.metadata?.genre) genres.add(String(extension.metadata.genre));
    for (const profile of Array.isArray(extension.profiles) ? extension.profiles : []) {
      if (profile.genre) genres.add(String(profile.genre));
    }
  }
  for (const genre of genres) {
    badges.push({ label: `Genre · ${genre}`, className: "badge-neutral" });
  }
  return badges;
}

function renderPlannedWorkflows() {
  const list = document.getElementById("planned-workflow-list");
  if (!list) return;
  list.innerHTML = "";
  const planned = workflowCatalog().filter(item => item.enabled === false || item.maturity === "planned");
  if (!planned.length) {
    list.appendChild(placeholder("No planned workflows in the current catalog."));
    return;
  }
  for (const item of planned) {
    const card = document.createElement("article");
    card.className = "panel roadmap-card";

    const heading = document.createElement("div");
    heading.className = "panel-heading";
    const title = document.createElement("h2");
    title.textContent = item.title;
    const badge = document.createElement("span");
    badge.className = `badge ${maturityBadgeClass(item.maturity, false)}`;
    badge.textContent = maturityLabel(item.maturity);
    heading.append(title, badge);

    const body = document.createElement("div");
    body.className = "roadmap-card-body";
    const note = document.createElement("p");
    note.textContent = item.safety_note || "Planned workflow. No Control Center action is available yet.";
    const action = document.createElement("button");
    action.type = "button";
    action.className = "ghost-button";
    action.textContent = "View details";
    action.addEventListener("click", () => selectPanel(item.panel_id));
    body.append(note, action);

    card.append(heading, body);
    list.appendChild(card);
  }
}

function runtimeWorkflowState(workflowId) {
  if (!state.runtimeWorkflows[workflowId]) {
    state.runtimeWorkflows[workflowId] = { loading: false, report: null, error: null };
  }
  return state.runtimeWorkflows[workflowId];
}

function workflowReportSlot(workflowId) {
  return {
    mix_review: state.mixReview,
    low_end_analysis: state.lowEndAnalysis,
    routing_audit: state.routingAudit,
    project_organizer: state.projectOrganizer,
  }[workflowId] || runtimeWorkflowState(workflowId);
}

function currentWorkflowReport(workflowId) {
  return workflowReportSlot(workflowId)?.report || null;
}

function setWorkflowReport(workflowId, report) {
  workflowReportSlot(workflowId).report = report;
}

function interactionRequestId(requestOrDecision) {
  return String(
    requestOrDecision?.interaction_request_id
    || requestOrDecision?.interaction_id
    || requestOrDecision?.id
    || ""
  ).trim();
}

function getWorkflowUserDecisions(workflowId) {
  const rows = state.workflowUserDecisions?.[workflowId];
  return Array.isArray(rows) ? rows : [];
}

function syncWorkflowUserDecisions(workflowId, report) {
  if (!workflowId || !report) return;
  if (!state.workflowUserDecisions) state.workflowUserDecisions = {};
  const existing = getWorkflowUserDecisions(workflowId);
  const incoming = Array.isArray(report.user_decisions) ? report.user_decisions : [];
  const merged = [...existing];
  for (const row of incoming) {
    const requestId = interactionRequestId(row);
    if (!requestId) continue;
    const normalized = { ...row, interaction_request_id: requestId, interaction_id: requestId };
    const index = merged.findIndex(item => interactionRequestId(item) === requestId);
    if (index >= 0) merged[index] = normalized;
    else merged.push(normalized);
  }
  state.workflowUserDecisions[workflowId] = merged;
  report.user_decisions = merged;
}

function upsertWorkflowUserDecision(workflowId, decision) {
  if (!workflowId) return;
  if (!state.workflowUserDecisions) state.workflowUserDecisions = {};
  const requestId = interactionRequestId(decision);
  if (!requestId) return;
  const normalized = {
    ...decision,
    interaction_request_id: requestId,
    interaction_id: requestId,
    workflow_id: workflowId,
  };
  const existing = getWorkflowUserDecisions(workflowId);
  state.workflowUserDecisions[workflowId] = [
    ...existing.filter(item => interactionRequestId(item) !== requestId),
    normalized,
  ];
  const report = currentWorkflowReport(workflowId);
  if (report) {
    report.user_decisions = state.workflowUserDecisions[workflowId];
    setWorkflowReport(workflowId, report);
  }
}

function workflowRunBody(workflowId, base = {}) {
  const decisions = getWorkflowUserDecisions(workflowId);
  return decisions.length ? { ...base, user_decisions: decisions } : { ...base };
}

async function runRuntimeProductWorkflow(workflowId) {
  const workflow = workflowById(workflowId);
  if (!workflow?.endpoint) return;
  const workflowState = runtimeWorkflowState(workflowId);
  workflowState.loading = true;
  workflowState.error = null;
  renderRuntimeProductPanel(workflowId);
  try {
    const body = {};
    if (workflowId === "plugin_assistant") {
      const raw = document.getElementById("plugin-assistant-track")?.value;
      if (raw !== "" && raw != null) body.track = Number(raw);
    }
    if (workflowId === "preset_assistant") {
      body.plugin = document.getElementById("preset-assistant-plugin")?.value || "";
      body.description = document.getElementById("preset-assistant-description")?.value || "";
    }
    const requestBody = workflowRunBody(workflowId, body);
    workflowState.report = await api(workflow.endpoint, {
      method: "POST",
      body: JSON.stringify(requestBody)
    });
    syncWorkflowUserDecisions(workflowId, workflowState.report);
  } catch (error) {
    workflowState.error = error.message;
  } finally {
    workflowState.loading = false;
    renderRuntimeProductPanel(workflowId);
  }
}

function renderRuntimeProductPanels() {
  for (const workflow of workflowCatalog()) {
    if (workflow.id === "preflight") {
      renderRuntimeProductPanel(workflow.id);
    }
  }
}

function renderRuntimeProductPanel(workflowId) {
  const workflow = workflowById(workflowId);
  const panel = workflow?.panel_id ? document.getElementById(workflow.panel_id) : null;
  if (!workflow || !panel) return;
  const container = panel.querySelector?.(".runtime-workflow-content")
    || document.getElementById(`${workflowId}-runtime-content`);
  if (!container) return;
  container.innerHTML = "";
  const workflowState = runtimeWorkflowState(workflowId);
  const report = workflowState.report;

  const controls = document.createElement("div");
  controls.className = "workflow-runtime-controls";
  if (workflowId === "plugin_assistant") {
    controls.appendChild(runtimeInput("plugin-assistant-track", "Mixer track", "number", "0"));
  }
  if (workflowId === "preset_assistant") {
    controls.appendChild(runtimeInput("preset-assistant-plugin", "Plugin", "text", "Serum"));
    controls.appendChild(runtimeInput("preset-assistant-description", "Sound description", "text", "bright pluck"));
  }
  const runButton = document.createElement("button");
  runButton.type = "button";
  runButton.className = "ghost-button primary-action";
  runButton.textContent = workflowState.loading ? "Running..." : (workflow.action_label || "Run Check");
  runButton.disabled = workflowState.loading || workflow.enabled === false;
  runButton.addEventListener("click", () => runRuntimeProductWorkflow(workflowId));
  controls.appendChild(runButton);
  container.appendChild(controls);

  if (workflowState.error) {
    container.appendChild(runtimeNotice(
      "Workflow unavailable",
      `${workflowState.error} Check Setup Doctor, then run the workflow again.`,
      "is-critical"
    ));
    return;
  }
  if (!report) {
    container.appendChild(runtimeNotice(
      "No report yet",
      workflow.safety_note || "Run the read-only workflow to collect current evidence.",
      "is-info"
    ));
    return;
  }

  const evidence = report.evidence_mode || report.analysis_mode || "unknown";
  const freshness = report.freshness?.status || "unknown";
  const coverage = report.coverage?.score;
  const summary = document.createElement("div");
  summary.className = "workflow-runtime-summary";
  for (const [label, value] of [
    ["Evidence", evidenceLabel(evidence)],
    ["Freshness", stateLabel(freshness)],
    ["Coverage", coverage == null ? "Unavailable" : `${coverage}%`],
    ["Confidence", report.confidence_score == null ? "Unavailable" : `${report.confidence_score}%`]
  ]) {
    const item = document.createElement("div");
    const key = document.createElement("span");
    key.textContent = label;
    const val = document.createElement("strong");
    val.textContent = value;
    item.append(key, val);
    summary.appendChild(item);
  }
  container.appendChild(summary);
  container.appendChild(runtimeInteractionRequests(workflowId, report));
  container.appendChild(runtimeReportList("Findings", report.findings, "No findings in available evidence."));
  container.appendChild(runtimeReportList("Limitations", report.limitations, "No additional limitations reported."));
  container.appendChild(runtimeReportList("Next evidence step", report.next_actions, "No next evidence step reported."));
}

function runtimeInput(id, labelText, type, placeholderText) {
  const label = document.createElement("label");
  label.className = "workflow-runtime-input";
  const title = document.createElement("span");
  title.textContent = labelText;
  const input = document.createElement("input");
  input.id = id;
  input.type = type;
  input.placeholder = placeholderText;
  if (type === "number") input.min = "0";
  label.append(title, input);
  return label;
}

function runtimeNotice(titleText, bodyText, className) {
  const notice = document.createElement("div");
  notice.className = `workflow-runtime-notice ${className}`;
  const title = document.createElement("strong");
  title.textContent = titleText;
  const body = document.createElement("p");
  body.textContent = bodyText;
  notice.append(title, body);
  return notice;
}

function runtimeReportList(titleText, rows, emptyText) {
  const card = document.createElement("section");
  card.className = "workflow-runtime-list";
  const title = document.createElement("h2");
  title.textContent = titleText;
  card.appendChild(title);
  const values = Array.isArray(rows) ? rows : [];
  if (!values.length) {
    const empty = document.createElement("p");
    empty.textContent = emptyText;
    card.appendChild(empty);
    return card;
  }
  const list = document.createElement("ul");
  for (const row of values.slice(0, 12)) {
    const item = document.createElement("li");
    if (typeof row === "string") {
      item.textContent = row;
    } else {
      item.textContent = safeString(row.title || row.label || row.id || "Review evidence");
    }
    list.appendChild(item);
  }
  card.appendChild(list);
  return card;
}

function runtimeInteractionRequests(workflowId, report) {
  return renderInteractionRequests(report, workflowId, { showEmpty: true });
}

function renderInteractionRequests(report, workflowId, { showEmpty = false } = {}) {
  syncWorkflowUserDecisions(workflowId, report);
  const card = document.createElement("section");
  card.className = "workflow-runtime-list workflow-runtime-interactions";
  const title = document.createElement("h2");
  title.textContent = "Workflow needs your input";
  card.appendChild(title);

  const requests = Array.isArray(report?.interaction_requests) ? report.interaction_requests : [];
  if (!requests.length) {
    if (!showEmpty) return null;
    const empty = document.createElement("p");
    empty.textContent = "No interaction requests reported.";
    card.appendChild(empty);
    return card;
  }

  for (const request of requests.slice(0, 12)) {
    if (!request || typeof request !== "object") continue;
    const item = document.createElement("div");
    item.className = "workflow-interaction-request";

    const heading = document.createElement("h3");
    heading.textContent = safeString(request.title || interactionTypeLabel(request.type));
    const prompt = document.createElement("p");
    prompt.textContent = safeString(request.prompt || request.id || "Review this request.");
    item.append(heading, prompt);

    const body = document.createElement("div");
    body.className = "workflow-interaction-body";
    renderInteractionControl(body, workflowId, report, request);
    item.appendChild(body);

    const decision = findUserDecision(report, interactionRequestId(request), workflowId);
    if (decision) {
      const saved = document.createElement("p");
      saved.className = "workflow-interaction-decision";
      saved.textContent = `Saved. Re-run this workflow to apply your answer: ${formatUserDecision(decision)}`;
      item.appendChild(saved);
    }
    card.appendChild(item);
  }
  return card;
}

function renderWorkflowInteractionMount(mountId, workflowId, report) {
  const mount = document.getElementById(mountId);
  if (!mount) return;
  mount.innerHTML = "";
  const node = renderInteractionRequests(report, workflowId);
  if (node) mount.appendChild(node);
}

function renderInteractionControl(container, workflowId, report, request) {
  const type = request.type;
  const requestId = interactionRequestId(request);
  if (type === "confirm") {
    const row = document.createElement("div");
    row.className = "workflow-interaction-actions";
    row.append(
      interactionButton("Confirm", true, () => updateUserDecision(workflowId, report, request, { decision: "confirmed", confirmed: true, skipped: false })),
      interactionButton("Skip", false, () => updateUserDecision(workflowId, report, request, { decision: "skipped", confirmed: false, skipped: true }))
    );
    container.appendChild(row);
    return;
  }

  if (type === "manual_task") {
    const row = document.createElement("div");
    row.className = "workflow-interaction-actions";
    row.append(
      interactionButton("I did this", true, () => updateUserDecision(workflowId, report, request, {
        decision: "completed",
        confirmed: true,
        completed: true,
        value: manualTaskInputValue(container),
      })),
      interactionButton("Skip for now", false, () => updateUserDecision(workflowId, report, request, {
        decision: "skipped",
        skipped: true,
        completed: false,
        value: manualTaskInputValue(container),
      }))
    );
    container.appendChild(row);

    const label = document.createElement("label");
    label.className = "workflow-interaction-option";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = Boolean(findUserDecision(report, requestId, workflowId)?.completed);
    input.addEventListener("change", () => {
      updateUserDecision(workflowId, report, request, {
        decision: input.checked ? "completed" : "skipped",
        confirmed: Boolean(input.checked),
        skipped: !input.checked,
        completed: Boolean(input.checked),
        value: manualTaskInputValue(container),
      });
    });
    const textNode = document.createElement("span");
    textNode.textContent = "Task completed";
    label.append(input, textNode);
    container.appendChild(label);

    if (request.resume_input?.type) {
      const resume = document.createElement("input");
      resume.className = "workflow-interaction-resume";
      resume.type = "text";
      resume.placeholder = resumeInputPlaceholder(request.resume_input);
      resume.value = String(findUserDecision(report, requestId, workflowId)?.value || "");
      resume.addEventListener("input", () => {
        updateUserDecision(workflowId, report, request, {
          decision: input.checked ? "completed" : "pending",
          confirmed: Boolean(input.checked),
          skipped: false,
          completed: Boolean(input.checked),
          value: resume.value,
        });
      });
      container.appendChild(resume);
    }
    return;
  }

  if (type === "single_select" || type === "multi_select") {
    const options = Array.isArray(request.options) ? request.options : [];
    if (!options.length) {
      const empty = document.createElement("p");
      empty.textContent = "No options were provided for this request.";
      container.appendChild(empty);
      return;
    }
    const decision = findUserDecision(report, requestId, workflowId);
    const selectedRows = Array.isArray(decision?.selected_values)
      ? decision.selected_values
      : Array.isArray(decision?.selected)
        ? decision.selected
        : decision?.selected_value
          ? [decision.selected_value]
          : [];
    const selected = new Set(selectedRows);
    for (const option of options) {
      const optionId = safeString(option.id || option.value || option.label);
      const label = document.createElement("label");
      label.className = "workflow-interaction-option";
      const input = document.createElement("input");
      input.type = type === "single_select" ? "radio" : "checkbox";
      input.name = `interaction-${safeString(request.id)}`;
      input.value = optionId;
      input.checked = selected.size ? selected.has(optionId) : Boolean(option.selected);
      input.addEventListener("change", () => {
        const inputs = Array.from(container.querySelectorAll?.("input") || []);
        const values = inputs
          .filter(node => node.checked)
          .map(node => node.value);
        updateUserDecision(workflowId, report, request, {
          decision: "selected",
          selected: type === "single_select" ? values.slice(0, 1) : values,
          selected_values: type === "single_select" ? values.slice(0, 1) : values,
          selected_value: type === "single_select" ? (values[0] || "") : undefined,
          skipped: false,
        });
      });
      const textNode = document.createElement("span");
      textNode.textContent = safeString(option.label || optionId);
      label.append(input, textNode);
      container.appendChild(label);
    }
    return;
  }

  const unsupported = document.createElement("p");
  unsupported.textContent = `Unsupported interaction type: ${safeString(type)}`;
  container.appendChild(unsupported);
}

function interactionButton(label, primary, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `ghost-button${primary ? " primary-action" : ""}`;
  button.textContent = label;
  button.addEventListener("click", onClick);
  return button;
}

function updateUserDecision(workflowId, report, request, values) {
  const requestId = interactionRequestId(request);
  if (!requestId) return;
  const decision = {
    interaction_request_id: requestId,
    interaction_id: request.id,
    workflow_id: workflowId,
    type: request.type,
    ...values,
  };
  upsertWorkflowUserDecision(workflowId, decision);
  const updated = currentWorkflowReport(workflowId) || report;
  if (updated) updated.user_decisions = getWorkflowUserDecisions(workflowId);
  renderWorkflowPanelById(workflowId);
}

function findUserDecision(report, requestId, workflowId) {
  const stored = workflowId ? getWorkflowUserDecisions(workflowId) : [];
  const reportDecisions = Array.isArray(report?.user_decisions) ? report.user_decisions : [];
  const decisions = [...stored, ...reportDecisions];
  return decisions.find(item => interactionRequestId(item) === requestId) || null;
}

function manualTaskInputValue(container) {
  const input = container.querySelector?.(".workflow-interaction-resume");
  return input?.value || "";
}

function resumeInputPlaceholder(resumeInput) {
  if (resumeInput.type === "file_path") return "Path to completed file";
  return safeString(resumeInput.label || resumeInput.type || "Response");
}

function interactionTypeLabel(type) {
  const labels = {
    confirm: "Confirmation",
    manual_task: "Manual task",
    single_select: "Single select",
    multi_select: "Multi select",
  };
  return labels[type] || "Interaction";
}

function formatUserDecision(decision) {
  if (decision.skipped) return "skipped";
  if (decision.type === "confirm") return decision.confirmed ? "confirmed" : "declined";
  if (decision.type === "manual_task") {
    const suffix = decision.value ? ` (${decision.value})` : "";
    return `${decision.completed ? "completed" : "not completed"}${suffix}`;
  }
  if (Array.isArray(decision.selected_values)) return decision.selected_values.join(", ") || "none selected";
  if (Array.isArray(decision.selected)) return decision.selected.join(", ") || "none selected";
  return "recorded";
}

function renderWorkflowPanelById(workflowId) {
  if (workflowId === "mix_review") {
    renderMixReview();
    return;
  }
  if (workflowId === "low_end_analysis") {
    renderLowEndAnalysis();
    return;
  }
  if (workflowId === "routing_audit") {
    renderRoutingAudit();
    return;
  }
  if (workflowId === "project_organizer") {
    renderProjectOrganizer();
    return;
  }
  renderRuntimeProductPanel(workflowId);
}

function evidenceLabel(value) {
  const labels = {
    static_snapshot_only: "Project metadata",
    loaded_plugin_inventory: "Loaded plugin inventory",
    local_preset_name_inventory: "Local preset names",
    rendered_master: "Rendered master audio",
    stem: "Selected short stem",
    candidate: "Selected audio candidate",
    manual_check: "Manual check",
    unavailable: "Unavailable"
  };
  return labels[value] || safeString(value).replaceAll("_", " ");
}

// ─── Audio Analysis Jobs ─────────────────────────────────────────────────────
async function audioAnalysisRequest(action, payload = {}) {
  const response = await api("/api/audio-analysis", {
    method: "POST",
    body: JSON.stringify({ action, ...payload })
  });
  if (response?.ok === false) throw new Error(response.error || "Audio analysis failed.");
  return response;
}

function audioWorkflowTargets() {
  const raw = document.getElementById("audio-workflow-targets")?.value || "";
  return raw.split(",").map(item => item.trim()).filter(Boolean);
}

async function submitAudioAnalysis() {
  const audioState = state.audioAnalysis;
  const path = document.getElementById("audio-analysis-path")?.value?.trim() || "";
  audioState.loading = true;
  audioState.error = null;
  audioState.report = null;
  renderAudioAnalysis();
  try {
    const response = await audioAnalysisRequest("submit", { path });
    audioState.activeJob = response.job;
    await loadAudioAnalysisJobs();
    scheduleAudioJobPoll(response.job.job_id);
  } catch (error) {
    audioState.error = error.message;
  } finally {
    audioState.loading = false;
    renderAudioAnalysis();
  }
}

async function loadAudioAnalysisJobs() {
  try {
    const response = await audioAnalysisRequest("list", { limit: 20, offset: 0 });
    state.audioAnalysis.jobs = response.jobs || [];
    if (!state.audioAnalysis.activeJob && state.audioAnalysis.jobs.length) {
      state.audioAnalysis.activeJob = state.audioAnalysis.jobs[0];
    }
    renderAudioAnalysis();
    return response;
  } catch (error) {
    state.audioAnalysis.error = error.message;
    renderAudioAnalysis();
    return null;
  }
}

async function refreshAudioAnalysisJob(jobId, { continuePolling = false } = {}) {
  try {
    const response = await audioAnalysisRequest("status", { job_id: jobId });
    state.audioAnalysis.activeJob = response.job;
    const index = state.audioAnalysis.jobs.findIndex(item => item.job_id === jobId);
    if (index >= 0) state.audioAnalysis.jobs[index] = response.job;
    else state.audioAnalysis.jobs.unshift(response.job);
    state.audioAnalysis.error = null;
    renderAudioAnalysis();
    if (continuePolling && ["queued", "running", "interrupted"].includes(response.job.status)) {
      scheduleAudioJobPoll(jobId);
    }
    return response.job;
  } catch (error) {
    state.audioAnalysis.error = error.message;
    renderAudioAnalysis();
    return null;
  }
}

function scheduleAudioJobPoll(jobId) {
  if (window.__FLS_PILOT_TEST__) return;
  if (state.audioAnalysis.pollTimer) clearTimeout(state.audioAnalysis.pollTimer);
  state.audioAnalysis.pollTimer = setTimeout(() => {
    state.audioAnalysis.pollTimer = null;
    refreshAudioAnalysisJob(jobId, { continuePolling: true });
  }, 800);
}

async function cancelAudioAnalysisJob(jobId) {
  try {
    const response = await audioAnalysisRequest("cancel", { job_id: jobId });
    state.audioAnalysis.activeJob = response.job;
    await loadAudioAnalysisJobs();
  } catch (error) {
    state.audioAnalysis.error = error.message;
    renderAudioAnalysis();
  }
}

async function linkAudioAnalysisResult(jobId) {
  try {
    const response = await audioAnalysisRequest("result", {
      job_id: jobId,
      link_evidence: true,
      evidence_kind: document.getElementById("audio-evidence-kind")?.value || "rendered_master",
      stem_role: document.getElementById("audio-stem-role")?.value?.trim() || null,
      workflow_targets: audioWorkflowTargets(),
      confirmed_by_user: Boolean(document.getElementById("audio-confirm-project")?.checked)
    });
    state.audioAnalysis.activeJob = response.job;
    state.audioAnalysis.report = response.report || null;
    state.audioAnalysis.error = null;
    renderAudioAnalysis();
  } catch (error) {
    state.audioAnalysis.error = error.message;
    renderAudioAnalysis();
  }
}

function renderAudioAnalysis() {
  const audioState = state.audioAnalysis;
  const submit = document.getElementById("submit-audio-analysis");
  if (submit) {
    submit.disabled = audioState.loading;
    submit.textContent = audioState.loading ? "Submitting..." : "Analyze Audio";
  }
  const feedback = document.getElementById("audio-analysis-feedback");
  if (feedback) {
    feedback.className = `workflow-runtime-notice ${audioState.error ? "is-critical" : "is-info"}`;
    feedback.innerHTML = "";
    const title = document.createElement("strong");
    const body = document.createElement("p");
    if (audioState.error) {
      title.textContent = "Audio analysis unavailable";
      body.textContent = audioState.error;
    } else if (audioState.report) {
      title.textContent = "Evidence linked";
      body.textContent = "The Runtime recorded project-scoped rendered audio evidence.";
    } else {
      title.textContent = "Offline and non-destructive";
      body.textContent = "Runtime jobs never render from FL Studio and never modify the source file.";
    }
    feedback.append(title, body);
  }
  const active = audioState.activeJob;
  text("audio-active-status", active ? stateLabel(active.status) : "Idle");
  const activeContainer = document.getElementById("audio-active-job");
  if (activeContainer) {
    activeContainer.innerHTML = "";
    activeContainer.appendChild(
      active ? audioJobCard(active, { active: true }) : placeholder("No audio analysis job selected.")
    );
  }
  text("audio-job-count", audioState.jobs.length);
  const list = document.getElementById("audio-job-list");
  if (list) {
    list.innerHTML = "";
    if (!audioState.jobs.length) {
      list.appendChild(placeholder("No Runtime audio jobs yet."));
    } else {
      for (const job of audioState.jobs.slice(0, 20)) {
        list.appendChild(audioJobCard(job));
      }
    }
  }
}

function audioJobCard(job, { active = false } = {}) {
  const card = document.createElement("article");
  card.className = "audio-job-card";
  const header = document.createElement("div");
  header.className = "audio-job-card-header";
  const name = document.createElement("strong");
  name.textContent = job.input_summary?.source_basename || job.job_id || "Audio job";
  const badge = document.createElement("span");
  badge.className = `badge ${job.status === "succeeded" ? "badge-ok" : "badge-neutral"}`;
  badge.textContent = stateLabel(job.status);
  header.append(name, badge);
  card.appendChild(header);

  const progress = document.createElement("div");
  progress.className = "audio-job-progress";
  const bar = document.createElement("i");
  bar.style.width = `${Math.round(Number(job.progress || 0) * 100)}%`;
  progress.appendChild(bar);
  card.appendChild(progress);

  const metrics = document.createElement("div");
  metrics.className = "audio-job-metrics";
  const summary = job.result_ref?.summary || {};
  for (const value of [
    `${Math.round(Number(job.progress || 0) * 100)}%`,
    job.cache_hit ? "Cache hit" : null,
    summary.duration_seconds == null ? null : `${numberValue(summary.duration_seconds, 1)} s`,
    summary.integrated_lufs == null ? null : `${numberValue(summary.integrated_lufs, 1)} LUFS`
  ].filter(Boolean)) {
    const item = document.createElement("span");
    item.textContent = value;
    metrics.appendChild(item);
  }
  card.appendChild(metrics);

  if (job.error?.message) {
    const error = document.createElement("p");
    error.textContent = job.error.message;
    card.appendChild(error);
  }
  const actions = document.createElement("div");
  actions.className = "audio-job-actions";
  if (!active) {
    actions.appendChild(audioJobButton("View", () => {
      state.audioAnalysis.activeJob = job;
      renderAudioAnalysis();
    }));
  }
  if (["queued", "running", "interrupted"].includes(job.status)) {
    actions.appendChild(audioJobButton("Refresh", () => refreshAudioAnalysisJob(job.job_id)));
    actions.appendChild(audioJobButton("Cancel", () => cancelAudioAnalysisJob(job.job_id)));
  }
  if (job.status === "succeeded") {
    actions.appendChild(audioJobButton("Link Evidence", () => linkAudioAnalysisResult(job.job_id), true));
  }
  if (actions.children.length) card.appendChild(actions);
  return card;
}

function audioJobButton(label, handler, primary = false) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `ghost-button${primary ? " primary-action" : ""}`;
  button.textContent = label;
  button.addEventListener("click", handler);
  return button;
}

function renderNextAction() {
  const action = state.status?.ui?.next_action || fallbackNextAction();
  text("next-action-title", action.label || "Check status");
  text("next-action-detail", action.detail || "Run a check to see the current setup state.");
  const button = document.getElementById("next-action-button");
  if (!button) return;
  button.textContent = action.action_label || action.label || "Run Check";
  button.onclick = () => {
    if (action.action_path && action.action_path !== "/api/refresh") {
      processAction(action.action_path);
      return;
    }
    if (action.action_path === "/api/refresh") {
      refresh();
      return;
    }
    if (action.target_panel) {
      selectPanel(action.target_panel);
      return;
    }
    refresh();
  };
}

function fallbackNextAction() {
  if (!state.status) {
    return {
      label: "Run Status Check",
      detail: "Run a check to see the current setup state.",
      action_path: "/api/refresh",
      action_label: "Run Check"
    };
  }
  const data = getStatusReport();
  const bridge = data?.bridge || {};
  const daemonProc = state.status?.processes?.daemon || {};
  const live = bridge.state === "live";
  const daemonRunning = isManagedProcessRunning(daemonProc) || daemonProc.state === "external";
  if (!daemonRunning) {
    return {
      label: "Start FL Studio Bridge Service",
      detail: "The local bridge service is stopped. Start it before checking FL Studio controller data.",
      action_path: "/api/process/daemon/start",
      action_label: "Start Service"
    };
  }
  if (!live) {
    return {
      label: "Connect FL Studio Controller",
      detail: "The bridge service is running, but FL Studio is not sending fresh controller data yet.",
      target_panel: "setup",
      action_path: "/api/refresh",
      action_label: "Re-check"
    };
  }
  return {
    label: "Run Health Scan",
    detail: "FL Studio is connected. Start with a read-only project overview.",
    target_panel: "producer_health",
    action_label: "Open Health"
  };
}

function renderConnectionReadyBanner() {
  const banner = document.getElementById("connection-ready-banner");
  if (banner) banner.style.display = hasLiveFlData() ? "flex" : "none";
}

function placeholder(message) {
  const node = document.createElement("div");
  node.className = "placeholder-card";
  node.textContent = message;
  return node;
}

function setRunButton(id, isLoading, readyLabel) {
  const button = document.getElementById(id);
  if (!button) return;
  button.disabled = isLoading;
  button.textContent = isLoading ? "Running..." : readyLabel;
}

function setWorkflowFeedback({ id, baseClass, loading, error, report, loadingText, idleText, completeLabel }) {
  const feedback = document.getElementById(id);
  if (!feedback) return;
  feedback.className = baseClass;
  if (loading) {
    feedback.classList.add("is-loading");
    feedback.textContent = loadingText;
    return;
  }
  if (error) {
    feedback.classList.add("is-error");
    feedback.textContent = error;
    return;
  }
  if (report?.ok) {
    feedback.classList.add("is-live");
    const timestamp = new Date(report.generated_at || Date.now()).toLocaleTimeString();
    feedback.textContent = `${completeLabel}: ${timestamp}. Read-only scan. No project changes are made.`;
    return;
  }
  feedback.textContent = idleText;
}

// ─── Setup Overview ───────────────────────────────────────────────────────────
function renderOverview() {
  const data = getStatusReport();
  renderOverviewCards(data);
}

function renderOverviewCards(data) {
  const cardsEl = document.getElementById("overview-status-cards");
  if (!cardsEl) return;

  const bridge = data?.bridge || {};
  const safety = data?.safety || {};
  const daemonProc = state.status?.processes?.daemon || {};
  const sseProc = state.status?.processes?.sse || {};
  const snippets = state.status?.snippets || {};

  const daemonRunning = isManagedProcessRunning(daemonProc) || daemonProc.state === "external";
  const sseRunning = isManagedProcessRunning(sseProc);
  const live = bridge.state === "live";
  const readOnly = safety.read_only !== false;

  cardsEl.innerHTML = "";

  // Card 1: FL Studio Connection
  const bridgeStatus = live ? "connected" : (bridge.state === "unavailable" || !bridge.state ? "not_connected" : bridge.state);
  const bridgeLabel = live ? "Connected" : "Not Connected";
  const flVersion = safeString(bridge.fl_version || data?.project?.fl_version);
  const bridgeDesc = live
    ? `FL Studio is responding. ${flVersion !== "Unavailable" ? "Version: " + flVersion : "Bridge heartbeat is live."}`
    : "FL Studio is not sending controller data yet. See the checklist below to diagnose.";
  cardsEl.appendChild(makeStatusCard({
    id: "card-fl-connection",
    icon: "◈",
    title: "FL Studio Connection",
    status: bridgeStatus,
    statusLabel: bridgeLabel,
    description: bridgeDesc,
    actionLabel: "Refresh Status",
    actionTarget: null,
    actionDirect: () => refresh(),
    live
  }));

  // Card 2: Background Service
  const svcStatus = daemonRunning ? "running" : "stopped";
  const svcLabel = daemonRunning ? "Running" : "Not Running";
  const svcDesc = daemonRunning
    ? (daemonProc.state === "external" ? "FL Studio Bridge Service is reachable (managed externally)." : "FL Studio Bridge Service is running under this Control Center.")
    : "The background service is not running. Start it to enable FL Studio communication.";
  cardsEl.appendChild(makeStatusCard({
    id: "card-background-service",
    icon: "▶",
    title: "Background Service",
    status: svcStatus,
    statusLabel: svcLabel,
    description: svcDesc,
    actionLabel: daemonRunning ? "Refresh Status" : "Start Service",
    actionTarget: null,
    actionDirect: daemonRunning ? () => refresh() : () => processAction("/api/process/daemon/start"),
    live: daemonRunning
  }));

  // Card 3: AI Client Setup
  const aiStatus = sseRunning ? "running" : "not_required";
  const aiLabel = sseRunning ? "Running" : "Optional";
  const aiDesc = sseRunning
    ? `AI Client Server is running. Copy the SSE URL to connect your AI client.`
    : "The AI Client Server is optional. Start it only if your AI client uses SSE/HTTP (e.g. ChatGPT).";
  cardsEl.appendChild(makeStatusCard({
    id: "card-ai-client",
    icon: "◇",
    title: "AI Client Setup",
    status: aiStatus,
    statusLabel: aiLabel,
    description: aiDesc,
    actionLabel: "Open AI Clients",
    actionTarget: "clients",
    live: sseRunning
  }));

  // Card 4: Safety Mode
  const safetyStatus = readOnly ? "readonly" : "write_enabled";
  const safetyLabel = readOnly ? "Read-only" : "Write enabled";
  const safetyDesc = readOnly
    ? "Read-only mode is active. No FL Studio project changes are made."
    : "Write-capable mode is active. Safe Apply remains proposal-first.";
  cardsEl.appendChild(makeStatusCard({
    id: "card-safety-mode",
    icon: "◆",
    title: "Safety Mode",
    status: safetyStatus,
    statusLabel: safetyLabel,
    description: safetyDesc,
    actionLabel: "View Safety Details",
    actionTarget: "overview",
    actionHash: "safety",
    live: true
  }));
}

function makeStatusCard({ id, icon, title, status, statusLabel, description, actionLabel, actionTarget, actionDirect, actionHash, live }) {
  const card = document.createElement("article");
  card.className = "status-card";
  card.id = id || "";

  // Status indicator dot
  const indicator = document.createElement("div");
  indicator.className = `status-card-indicator ${live ? "live" : (status === "not_required" || status === "readonly" ? "neutral" : "offline")}`;

  const body = document.createElement("div");
  body.className = "status-card-body";

  const header = document.createElement("div");
  header.className = "status-card-header";

  const titleEl = document.createElement("span");
  titleEl.className = "status-card-icon";
  titleEl.ariaHidden = "true";
  titleEl.textContent = icon;

  const h3 = document.createElement("h3");
  h3.className = "status-card-title";
  h3.textContent = title;

  const badge = document.createElement("span");
  badge.className = `status-card-badge ${live ? "badge-ok" : (status === "not_required" || status === "readonly" ? "badge-neutral" : "badge-warn")}`;
  badge.textContent = statusLabel;

  header.append(titleEl, h3, badge);

  const desc = document.createElement("p");
  desc.className = "status-card-desc";
  desc.textContent = description;

  const footer = document.createElement("div");
  footer.className = "status-card-footer";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "ghost-button";
  btn.textContent = actionLabel;
  btn.addEventListener("click", () => {
    if (actionDirect) { actionDirect(); }
    else { selectPanel(actionTarget); }
  });
  footer.appendChild(btn);

  body.append(header, desc, footer);
  card.append(indicator, body);
  return card;
}

// ─── Connection Check ─────────────────────────────────────────────────────────
function renderConnectionCheck() {
  const container = document.getElementById("connection-check-grid");
  if (!container) return;
  container.innerHTML = "";

  const data = getStatusReport();
  const bridge = data?.bridge || {};
  const safety = data?.safety || {};
  const daemonProc = state.status?.processes?.daemon || {};
  const sseProc = state.status?.processes?.sse || {};
  const sseProbe = state.status?.mcp?.sse_probe || state.status?.processes?.sse?.probe || {};

  const live = bridge.state === "live";
  const daemonRunning = isManagedProcessRunning(daemonProc) || daemonProc.state === "external";
  const sseRunning = isManagedProcessRunning(sseProc);
  const readOnly = safety.read_only !== false;

  const rows = [
    {
      label: "FL Studio Bridge",
      status: live ? "Connected" : "Not Connected",
      ok: live,
      detail: live ? "Bridge heartbeat is live." : (bridge.error || "No fresh controller heartbeat received."),
    },
    {
      label: "Background Service",
      status: daemonRunning ? "Running" : "Not Running",
      ok: daemonRunning,
      detail: daemonRunning
        ? (daemonProc.state === "external" ? "Running (external)." : "Running under this Control Center.")
        : "Start the FL Studio Bridge Service to enable communication.",
    },
    {
      label: "AI Client Server",
      status: sseRunning ? "Running" : "Not Started",
      ok: sseRunning,
      neutral: !sseRunning,
      detail: sseRunning
        ? (sseProbe.message || "SSE server is running.")
        : "Optional — start only if your AI client uses SSE/HTTP.",
    },
    {
      label: "Basic Read Test",
      status: live ? "Passed" : "Not Available",
      ok: live,
      detail: live
        ? "FL Studio project data is readable."
        : "Connect FL Studio to run a read test.",
    },
    {
      label: "Safety Mode",
      status: readOnly ? "Read-only" : "Write enabled",
      ok: true,
      neutral: true,
      detail: readOnly ? "No project changes are made." : "Project changes require Safe Apply.",
    },
    {
      label: "Last Check",
      status: new Date().toLocaleTimeString(),
      ok: true,
      neutral: true,
      detail: "Click Refresh to run all checks again.",
    },
  ];

  // Summary card
  const summaryCard = document.createElement("details");
  summaryCard.className = "panel connection-check-summary";

  const summaryHeading = document.createElement("summary");
  summaryHeading.className = "panel-heading";
  summaryHeading.style.cursor = "pointer";
  const summaryH2 = document.createElement("h2");
  summaryH2.textContent = "Connection Status";
  summaryHeading.appendChild(summaryH2);

  const summaryList = document.createElement("ul");
  summaryList.className = "connection-check-list";
  for (const row of rows) {
    const li = document.createElement("li");
    li.className = "connection-check-row";

    const dot = document.createElement("span");
    dot.className = `check-dot ${row.ok && !row.neutral ? "ok" : (row.neutral ? "neutral" : "warn")}`;

    const labelEl = document.createElement("strong");
    labelEl.className = "check-label";
    labelEl.textContent = row.label;

    const statusEl = document.createElement("span");
    statusEl.className = "check-status";
    statusEl.textContent = row.status;

    const detailEl = document.createElement("span");
    detailEl.className = "check-detail";
    detailEl.textContent = row.detail;

    li.append(dot, labelEl, statusEl, detailEl);
    summaryList.appendChild(li);
  }

  // Next step
  const nextStep = _recommendedNextStep();
  const nextStepEl = document.createElement("div");
  nextStepEl.className = "check-next-step";
  const nextStepLabel = document.createElement("span");
  nextStepLabel.className = "check-next-step-label";
  nextStepLabel.textContent = "Recommended next step:";
  const nextStepText = document.createElement("p");
  nextStepText.textContent = nextStep;
  nextStepEl.append(nextStepLabel, nextStepText);

  summaryCard.append(summaryHeading, summaryList, nextStepEl);
  container.appendChild(summaryCard);
}

function _recommendedNextStep() {
  if (!state.status) return "Run a check to see the current status.";
  const data = getStatusReport();
  const bridge = data?.bridge || {};
  const daemonProc = state.status?.processes?.daemon || {};
  const live = bridge.state === "live";
  const daemonRunning = isManagedProcessRunning(daemonProc) || daemonProc.state === "external";

  if (!daemonRunning) return "Start the FL Studio Bridge Service from Overview or Setup Doctor.";
  if (!live) return "FL Studio Bridge Service is running, but FL Studio is not sending controller data yet. Open FL Studio, load fls-pilot in the controller settings, and check the MIDI loopback ports.";
  return "FL Studio is connected. Run Health for a read-only project overview, or open AI Clients to configure your MCP client.";
}

// ─── Setup Doctor ─────────────────────────────────────────────────────────────
function renderSetup() {
  const container = document.getElementById("setup-steps");
  if (!container) return;
  container.innerHTML = "";

  // Root-cause summary banner
  const banner = _buildSetupDoctorBanner();
  if (banner) container.appendChild(banner);

  renderGuidedTroubleshooting(container);

  // Required group header
  const requiredHeader = document.createElement("div");
  requiredHeader.className = "setup-group-header";
  requiredHeader.textContent = "Required";
  container.appendChild(requiredHeader);

  for (const item of setupLayers.filter(l => l.priority === "required")) {
    container.appendChild(card(item.title, groupStatus(item.group), groupText(item.group)));
  }

  // Optional group header
  const optionalHeader = document.createElement("div");
  optionalHeader.className = "setup-group-header setup-group-optional";
  optionalHeader.textContent = "Optional";
  container.appendChild(optionalHeader);

  for (const item of setupLayers.filter(l => l.priority === "optional")) {
    container.appendChild(card(item.title, groupStatus(item.group), groupText(item.group)));
  }
}

function _buildSetupDoctorBanner() {
  if (!state.status) return null;
  const daemonProc = state.status?.processes?.daemon || {};
  const data = getStatusReport();
  const bridge = data?.bridge || {};
  const daemonRunning = isManagedProcessRunning(daemonProc) || daemonProc.state === "external";
  const live = bridge.state === "live";

  let message = null;
  if (daemonRunning && !live) {
    message = "FL Studio Bridge Service is running, but FL Studio is not sending controller data yet. Check the FL Studio controller settings and MIDI loopback ports.";
  } else if (!daemonRunning) {
    message = "The Background Service is not running. Start the FL Studio Bridge Service to begin setup.";
  }

  if (!message) return null;

  const banner = document.createElement("div");
  banner.className = "setup-summary-banner";
  const icon = document.createElement("span");
  icon.className = "banner-icon";
  icon.ariaHidden = "true";
  icon.textContent = "ℹ";
  const text = document.createElement("p");
  text.textContent = message;
  banner.append(icon, text);
  return banner;
}

function renderGuidedTroubleshooting(container) {
  const guidance = state.status?.setup_guidance || [];
  for (const item of guidance) {
    const buttons = [];
    if (item.checkpoint) {
      const feedback = state.setupFeedback[item.checkpoint];
      const isChecking = feedback?.state === "checking";
      buttons.push({
        text: isChecking ? "Checking..." : (item.action_label || "I did this"),
        disabled: isChecking,
        onclick: () => confirmStep({ key: item.checkpoint, groups: item.groups || [] })
      });
    } else if (item.action_path) {
      buttons.push({
        text: item.action_label || "Run",
        disabled: false,
        onclick: () => runGuidanceAction(item.action_path)
      });
    }
    const node = card(item.title, item.status, item.text, buttons.length ? buttons : null);
    if (item.checkpoint) {
      const confirmed = state.status.checkpoints?.[item.checkpoint];
      const feedback = state.setupFeedback[item.checkpoint] || (
        confirmed ? { state: "attention", text: "Confirmation saved. The related automated check still needs attention." } : null
      );
      appendSetupFeedback(node, feedback);
    }
    container.appendChild(node);
  }
}

function groupStatus(group) {
  const findings = state.status?.groups?.[group] || [];
  if (group === "daemon") {
    const dynamicStatus = daemonRuntimeStatus(findings);
    if (dynamicStatus) return dynamicStatus;
  }
  if (group === "mcp_sse") {
    const dynamicStatus = mcpSseStatus(findings);
    if (dynamicStatus) return dynamicStatus;
  }
  const failed = findings.find(item => item.status === "failed");
  if (failed) return failed.severity === "blocker" ? "Setup Required" : "Action Needed";
  const manual = findings.find(item => item.status === "manual_check" || item.status === "probe_needed");
  if (manual) return "Manual Check";
  return findings.length ? "OK" : "Not Required";
}

function groupNeedsAction(group) {
  const status = groupStatus(group).toLowerCase();
  return status !== "ok" && status !== "not required";
}

function isGroupOk(group) {
  return groupStatus(group).toLowerCase() === "ok";
}

function groupText(group) {
  const findings = state.status?.groups?.[group] || [];
  if (group === "daemon") {
    const dynamicText = daemonRuntimeText(findings);
    if (dynamicText) return dynamicText;
  }
  if (group === "mcp_sse") {
    const dynamicText = mcpSseText(findings);
    if (dynamicText) return dynamicText;
  }
  if (!findings.length) return "No finding for this setup layer.";
  return findings.map(item =>
    `${safeString(item.component)}: ${safeString(item.evidence)}${item.remediation ? ` Fix: ${safeString(item.remediation)}` : ""}`
  ).join("\n");
}

function hasLiveFlData() {
  const data = getStatusReport();
  const bridge = data?.bridge || {};
  const project = data?.project || {};
  return bridge.state === "live" && project.state === "live";
}

function daemonRuntimeStatus(findings = []) {
  const daemonProc = state.status?.processes?.daemon || {};
  const health = daemonProc.health || {};
  const running = isManagedProcessRunning(daemonProc) || daemonProc.state === "external";
  const problemFinding = findings.some(item => item.status === "failed" || item.status === "manual_check" || item.status === "probe_needed");
  if (problemFinding) return null;
  if (!running) return "Not Running";
  if (health.reachable === false) return "Action Needed";
  return null;
}

function daemonRuntimeText(findings = []) {
  const daemonProc = state.status?.processes?.daemon || {};
  const health = daemonProc.health || {};
  const running = isManagedProcessRunning(daemonProc) || daemonProc.state === "external";
  const problemFinding = findings.some(item => item.status === "failed" || item.status === "manual_check" || item.status === "probe_needed");
  if (problemFinding) return null;
  if (!running) return "FL Studio Bridge Service is not running. Start the service, then re-check setup.";
  if (health.reachable === false) return "The service process is running, but the TCP health check is not reachable.";
  return null;
}

function mcpSseProbe() {
  return state.status?.mcp?.sse_probe || state.status?.processes?.sse?.probe || null;
}

function mcpSseStatus(findings = []) {
  const probe = mcpSseProbe();
  if (!probe) return null;
  const sseProc = state.status?.processes?.sse || {};
  const running = isManagedProcessRunning(sseProc);
  if (!running && (probe.state === "not_required" || probe.state === "stopped")) {
    return findings.length ? null : "Not Required";
  }
  if (probe.state === "ok") return "OK";
  if (probe.state === "failed") return "Action Needed";
  if (probe.state === "checking") return "Checking";
  if (running) return "Running";
  return null;
}

function mcpSseText(findings = []) {
  const probe = mcpSseProbe();
  if (!probe) return null;
  if (findings.length && !state.status?.processes?.sse?.running && (probe.state === "not_required" || probe.state === "stopped")) {
    return null;
  }
  const parts = [safeString(probe.message) !== "Unavailable" ? probe.message : "AI Client Server status is unavailable."];
  if (probe.url) parts.push(`URL: ${safeString(probe.url)}`);
  if (probe.checked_at) parts.push(`Last test: ${new Date(probe.checked_at).toLocaleTimeString()}`);
  return parts.join("\n");
}

function setupGroupSnapshot(groups) {
  const out = {};
  for (const group of groups) out[group] = groupStatus(group);
  return out;
}

function groupStatusRank(status) {
  const normalized = String(status || "").toLowerCase();
  if (normalized === "ok") return 4;
  if (normalized === "not required") return 3;
  if (normalized === "manual check") return 2;
  if (normalized === "action needed") return 1;
  if (normalized === "setup required") return 0;
  return 0;
}

function evaluateSetupFeedback(step, before) {
  const after = setupGroupSnapshot(step.groups);
  const groupsOk = step.groups.every(group => isGroupOk(group) || groupStatus(group).toLowerCase() === "not required");
  const improved = step.groups.some(group => groupStatusRank(after[group]) > groupStatusRank(before[group]));
  const stillNeedsAction = step.groups.some(group => groupNeedsAction(group));

  if (groupsOk) return { state: "verified", text: "Verified: the related automated check now passes." };
  if (improved) return { state: "progress", text: "Progress detected. One related check improved; continue with the next setup layer." };
  if (stillNeedsAction) return { state: "attention", text: "Checked again: the expected automated signal is still missing." };
  return { state: "saved", text: "Confirmation saved. No additional automated signal is available for this step." };
}

function appendSetupFeedback(node, feedback) {
  if (!feedback) return;
  const message = document.createElement("div");
  message.className = `setup-feedback ${feedback.state}`;
  message.textContent = feedback.text;
  node.appendChild(message);
}

// ─── Services / Runtime ───────────────────────────────────────────────────────
function processStatus(process) {
  return process?.running ? "running" : (safeString(process?.state) || "stopped");
}

function isManagedProcessRunning(process) {
  return Boolean(process?.running) || process?.state === "running";
}

function isProcessReachable(process) {
  return isManagedProcessRunning(process) || process?.state === "external";
}

function processActionKey(path) {
  if (path.includes("/daemon/")) return "daemon";
  if (path.includes("/sse/")) return "sse";
  return "runtime";
}

function processActionLabel(path) {
  if (path.endsWith("/start")) return "Start";
  if (path.endsWith("/stop")) return "Stop";
  if (path.endsWith("/test")) return "Test";
  return "Action";
}

function processActionFeedback(path, result) {
  const label = processActionLabel(path);
  const parts = [];
  if (result?.message) parts.push(safeString(result.message));
  if (result?.fallback_port) parts.push(`Fallback port: ${safeString(result.fallback_port)}.`);
  if (result?.url) parts.push(`URL: ${safeString(result.url)}`);
  if (result?.probe?.message) parts.push(`Probe: ${safeString(result.probe.message)}`);
  if (!parts.length) parts.push(result?.ok ? `${label} completed.` : `${label} did not complete.`);
  return { state: result?.ok ? "verified" : "attention", text: parts.join("\n") };
}

function renderRuntime() {
  const container = document.getElementById("runtime-status");
  if (!container) return;
  container.innerHTML = "";

  if (!state.status || !state.status.processes || !state.status.ports) return;

  const daemonProc = state.status.processes.daemon || {};
  const daemonPort = state.status.ports.daemon || {};

  const daemonStatus = processStatus(daemonProc);
  const daemonHost = safeString(daemonPort.host);
  const daemonSelectedPort = safeString(daemonPort.selected_port);
  const daemonPreferredPort = safeString(daemonPort.preferred_port);

  let daemonText = `Local connection: ${daemonHost === "Unavailable" ? "127.0.0.1" : daemonHost}:${daemonSelectedPort}`;
  if (daemonPreferredPort !== daemonSelectedPort && daemonSelectedPort !== "Unavailable") {
    daemonText += ` (preferred: ${daemonPreferredPort})`;
  }
  if (daemonStatus === "external") {
    daemonText += "\n\nExternal daemon is reachable. This Control Center can use it but cannot stop it.";
  }
  const logs = (daemonProc.logs || []).slice(-6);
  daemonText += "\n\nService log:\n" + (logs.length ? logs.join("\n") : "No recent log entries.");

  const daemonCard = card("FL Studio Bridge Service", daemonStatus, daemonText, [
    { text: "Start Service", disabled: isProcessReachable(daemonProc), onclick: () => processAction("/api/process/daemon/start") },
    { text: "Stop Service", disabled: !isManagedProcessRunning(daemonProc), onclick: () => processAction("/api/process/daemon/stop") }
  ]);
  appendSetupFeedback(daemonCard, state.actionFeedback.daemon);

  // Add link buttons to Advanced screens
  const daemonLinks = document.createElement("div");
  daemonLinks.style.cssText = "padding: 0 26px 16px; display: flex; gap: 8px;";
  const logsBtn = document.createElement("button");
  logsBtn.type = "button"; logsBtn.className = "ghost-button"; logsBtn.textContent = "View Logs & History";
  logsBtn.addEventListener("click", () => selectPanel("logs_history"));
  const portsBtn = document.createElement("button");
  portsBtn.type = "button"; portsBtn.className = "ghost-button"; portsBtn.textContent = "View Ports";
  portsBtn.addEventListener("click", () => selectPanel("ports"));
  daemonLinks.append(logsBtn, portsBtn);
  daemonCard.appendChild(daemonLinks);
  container.appendChild(daemonCard);

  const sseProc = state.status.processes.sse || {};
  const ssePort = state.status.ports.sse || {};

  const sseStatus = processStatus(sseProc);
  const sseHost = safeString(ssePort.host);
  const sseSelectedPort = safeString(ssePort.selected_port);
  const ssePreferredPort = safeString(ssePort.preferred_port);

  let sseText = `Local connection: ${sseHost === "Unavailable" ? "127.0.0.1" : sseHost}:${sseSelectedPort}`;
  if (ssePreferredPort !== sseSelectedPort && sseSelectedPort !== "Unavailable") {
    sseText += ` (preferred: ${ssePreferredPort})`;
  }
  const sseLogs = (sseProc.logs || []).slice(-6);
  sseText += "\n\nService log:\n" + (sseLogs.length ? sseLogs.join("\n") : "No recent log entries.");

  const sseCard = card("AI Client Server", sseStatus, sseText, [
    { text: "Start AI Client Server", disabled: isProcessReachable(sseProc), onclick: () => processAction("/api/process/sse/start") },
    { text: "Stop AI Client Server", disabled: !isManagedProcessRunning(sseProc), onclick: () => processAction("/api/process/sse/stop") }
  ]);
  appendSetupFeedback(sseCard, state.actionFeedback.sse);
  container.appendChild(sseCard);

  const ccPort = state.status.ports.control_center || {};
  const footerPortSpan = document.getElementById("footer-cc-port");
  if (footerPortSpan) {
    const ccHost = safeString(ccPort.host);
    const ccSelected = safeString(ccPort.selected_port);
    const ccPreferred = safeString(ccPort.preferred_port);
    footerPortSpan.textContent = `Control Center: ${ccHost}:${ccSelected} (default: ${ccPreferred})`;
  }
}

// ─── Connection card (sidebar) ─────────────────────────────────────────────────
function renderConnection() {
  const data = getStatusReport();
  if (!data) return;
  const bridge = data.bridge || {};
  const project = data.project || {};
  const live = bridge.state === "live";

  const connCard = document.querySelector(".connection-card");
  if (connCard) connCard.classList.toggle("offline", !live);

  const eyebrow = document.querySelector(".connection-card .eyebrow");
  if (eyebrow) eyebrow.textContent = live ? "Connected To" : "Status";

  const dot = byId("connection-dot");
  if (dot) dot.classList.toggle("live", live);

  text("connected-version", live
    ? (safeString(project.fl_version || bridge.fl_version) !== "Unavailable" ? safeString(project.fl_version || bridge.fl_version) : "Local connection")
    : "Not reachable");
  text("connected-target", live ? "FL Studio (Local)" : "Disconnected");
}

// ─── AI Clients ───────────────────────────────────────────────────────────────
function renderClients() {
  const container = document.getElementById("client-snippets");
  if (!container) return;
  container.innerHTML = "";
  const snippets = state.status?.snippets;
  if (!snippets) return;

  // ChatGPT
  const chatgptUrl = safeString(snippets.chatgpt?.url);
  container.appendChild(makeAiClientCard({
    id: "ai-chatgpt",
    title: "ChatGPT",
    badge: "SSE / HTTP",
    steps: [
      "Start the AI Client Server from Overview when your client uses SSE/HTTP.",
      "Open ChatGPT → Settings → Connected Apps → MCP.",
      "Paste the SSE URL below.",
      "Run a connection check."
    ],
    copyLabel: "Copy URL",
    copyValue: chatgptUrl !== "Unavailable" ? chatgptUrl : snippets.chatgpt?.url,
    fieldLabel: "SSE URL",
    fieldValue: chatgptUrl !== "Unavailable" ? chatgptUrl : "Start the AI Client Server to get the URL.",
    advancedLabel: "Show advanced config",
    advancedContent: safeDebugString(snippets.chatgpt)
  }));

  // Claude Desktop
  const claudeJson = JSON.stringify(snippets.claude, null, 2);
  container.appendChild(makeAiClientCard({
    id: "ai-claude",
    title: "Claude Desktop",
    badge: "stdio / TCP",
    steps: [
      "Open claude_desktop_config.json (usually in ~/Library/Application Support/Claude/).",
      "Add the JSON snippet below to the file.",
      "Restart Claude Desktop."
    ],
    copyLabel: "Copy config",
    copyValue: claudeJson,
    fieldLabel: "Config JSON",
    fieldValue: claudeJson,
    advancedLabel: null
  }));

  // Cursor
  const cursorJson = JSON.stringify(snippets.cursor, null, 2);
  container.appendChild(makeAiClientCard({
    id: "ai-cursor",
    title: "Cursor",
    badge: "stdio / TCP",
    steps: [
      "Open Cursor Settings → MCP (Cmd+Shift+P → 'MCP').",
      "Add the JSON snippet below.",
      "Restart Cursor."
    ],
    copyLabel: "Copy config",
    copyValue: cursorJson,
    fieldLabel: "Config JSON",
    fieldValue: cursorJson,
    advancedLabel: null
  }));

  // Terminal fallback
  const termDaemon = safeString(snippets.terminal?.daemon);
  const termSse = safeString(snippets.terminal?.sse);
  const termText = `${termDaemon}\n${termSse}`;
  container.appendChild(makeAiClientCard({
    id: "ai-terminal",
    title: "Terminal Fallback",
    badge: "Manual",
    steps: [
      "Run these commands manually in your terminal to start the services."
    ],
    copyLabel: "Copy commands",
    copyValue: termText,
    fieldLabel: "Commands",
    fieldValue: termText,
    advancedLabel: null
  }));
}

function makeAiClientCard({ id, title, badge, steps, copyLabel, copyValue, fieldLabel, fieldValue, advancedLabel, advancedContent }) {
  const node = document.createElement("article");
  node.className = "panel ai-client-card";
  if (id) node.id = id;

  const heading = document.createElement("div");
  heading.className = "panel-heading";
  const h2 = document.createElement("h2");
  h2.textContent = title;
  const badgeEl = document.createElement("span");
  badgeEl.className = "badge badge-neutral";
  badgeEl.textContent = badge;
  badgeEl.style.marginLeft = "auto";
  heading.append(h2, badgeEl);

  const stepsEl = document.createElement("ol");
  stepsEl.className = "ai-client-steps";
  for (const step of steps) {
    const li = document.createElement("li");
    li.textContent = step;
    stepsEl.appendChild(li);
  }

  const fieldWrap = document.createElement("div");
  fieldWrap.className = "ai-client-field-wrap";
  const fieldLabelEl = document.createElement("label");
  fieldLabelEl.className = "ai-client-field-label";
  fieldLabelEl.textContent = fieldLabel;
  const fieldEl = document.createElement("pre");
  fieldEl.className = "copy-field";
  fieldEl.textContent = safeString(fieldValue) !== "Unavailable" ? fieldValue : "Unavailable";

  const btnRow = document.createElement("div");
  btnRow.className = "ai-client-btn-row";
  const copyBtn = document.createElement("button");
  copyBtn.type = "button";
  copyBtn.className = "ghost-button";
  copyBtn.textContent = copyLabel;
  copyBtn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(String(copyValue || ""));
      copyBtn.textContent = "Copied!";
      copyBtn.classList.add("copied");
      setTimeout(() => { copyBtn.textContent = copyLabel; copyBtn.classList.remove("copied"); }, 1400);
    } catch { copyBtn.textContent = "Copy failed"; }
  });
  btnRow.appendChild(copyBtn);

  fieldWrap.append(fieldLabelEl, fieldEl);

  node.append(heading, stepsEl, fieldWrap, btnRow);

  if (advancedLabel && advancedContent) {
    const details = document.createElement("details");
    details.className = "ai-client-advanced";
    const summary = document.createElement("summary");
    summary.textContent = advancedLabel;
    const advPre = document.createElement("pre");
    advPre.className = "copy-field";
    advPre.textContent = advancedContent;
    details.append(summary, advPre);
    node.appendChild(details);
  }

  return node;
}

// ─── Project Data (Connection Evidence, within Overview) ──────────────────────
function renderProjectData() {
  const disconnectedOverlay = document.getElementById("disconnected-overlay");
  const data = getStatusReport();

  if (!state.status || !data) {
    if (disconnectedOverlay) disconnectedOverlay.style.display = "flex";
    return;
  }

  const bridge = data.bridge || {};
  const live = bridge.state === "live";

  if (!live) {
    if (disconnectedOverlay) disconnectedOverlay.style.display = "flex";
  } else {
    if (disconnectedOverlay) disconnectedOverlay.style.display = "none";
  }

  // Project Snapshot
  const project = data.project || {};
  const resources = data.resources || {};
  text("tempo-value", bpm(project.tempo_bpm));
  text("channel-count", project.channel_count == null ? count(resources.channels) : project.channel_count);

  let mixCount = project.mixer_track_count == null ? count(resources.mixer) : project.mixer_track_count;
  if (typeof mixCount === "number") mixCount = Math.max(0, mixCount - 2);
  text("mixer-count", mixCount);

  let patCount = project.pattern_count == null ? count(resources.patterns) : project.pattern_count;
  if (typeof patCount === "number") patCount = Math.max(1, patCount);
  text("pattern-count", patCount);
  text("playlist-count", project.playlist_track_count == null ? count(resources.playlist) : project.playlist_track_count);
  renderProjectMetadata(project.metadata || {});

  // Transport
  const transport = data.transport || {};
  applyTransportSnapshot(transport, state.status?.generated_at || "");
  let playing = transport.playing;
  if (playing == null) playing = project.playing;
  let recording = transport.recording;
  if (recording == null) recording = project.recording;

  text("record-state", recording == null ? "Unavailable" : recording ? "ON" : "OFF");
  text("song-position", formatTransportPosition(transport));

  const statusOrb = document.getElementById("status-orb");
  if (statusOrb) {
    statusOrb.className = "status-orb";
    if (recording) statusOrb.classList.add("is-recording");
    else if (playing) statusOrb.classList.add("is-playing");
    else if (playing === false) statusOrb.classList.add("is-stopped");
  }
  renderTransportButtons();
  renderTransportFeedback();
  renderMarkerStrip("playlist-marker-strip", markerRows(transport), true);

  // Safety (read-only-context)
  const safety = data.safety || {};
  const readOnly = safety.read_only !== false;
  const dryRunAvailable = safety.dry_run_available !== false;

  text("read-only-state", readOnly ? "Active" : "Inactive");
  text("dry-run-state", dryRunAvailable ? "Available" : "Not available");

  // Rollback row: only show if not read-only / write context is relevant
  const rollbackRow = document.getElementById("rollback-row");
  if (rollbackRow) {
    rollbackRow.hidden = readOnly;
  }
  if (!readOnly) {
    text("rollback-state", safety.rollback_available ? "Available" : "Not available");
  }

  // Evidence
  const table = byId("evidence-table");
  let evidence = data.evidence || [];
  if (table) {
    table.innerHTML = "";
    if (!evidence.length) {
      evidence = [{
        label: "Status data",
        state: "unavailable",
        value: "Unavailable",
        source: "Generated data",
        detail: "Status data was not populated."
      }];
    }
    evidence.forEach(entry => {
      const row = document.createElement("div");
      row.className = "evidence-row";

      const entryLabel = safeString(entry.label);
      const entryValue = safeString(entry.value);
      const entryDetail = safeString(entry.detail);
      const entryState = safeString(entry.state);
      const key = entryLabel + entryValue + entryDetail + entryState;
      if (!state.evidenceKeys.has(key)) {
        row.classList.add("new");
        state.evidenceKeys.add(key);
      }

      row.dataset.state = entry.state || "unavailable";

      const stateSpan = document.createElement("span");
      stateSpan.className = "evidence-state";
      stateSpan.textContent = stateLabel(entry.state || "unavailable");

      const label = document.createElement("strong");
      label.textContent = entryLabel !== "Unavailable" ? entryLabel : "Evidence";

      const value = document.createElement("span");
      value.textContent = entryValue;

      const source = document.createElement("span");
      source.textContent = safeString(entry.source || entry.detail);
      source.title = entryDetail;

      row.append(stateSpan, label, value, source);
      table.appendChild(row);
    });
  }
}

function renderProjectMetadata(metadata) {
  text("project-title", metadata.title || "Unavailable");
  text("project-author", metadata.author || "Unavailable");
  text("project-genre", metadata.genre || "Unavailable");
}

function formatTransportPosition(transport) {
  const current = formatPosition(transport?.song_position);
  if (!transport || current === "Unavailable") return current;
  const pieces = [current];
  if (state.transport.stopResetDetected && state.transport.lastLivePosition) {
    pieces.push(`Last ${formatPosition(state.transport.lastLivePosition)}`);
  }
  if (state.transport.wrapCount > 0) {
    pieces.push(`Loop ${state.transport.wrapCount}`);
  }
  return pieces.join(" · ");
}

function markerRows(transport) {
  const markers = transport?.markers?.markers;
  return Array.isArray(markers) ? markers : [];
}

function renderMarkerStrip(containerId, markers, enabled) {
  const container = typeof containerId === "string" ? byId(containerId) : containerId;
  if (!container) return;
  container.innerHTML = "";
  if (!markers.length) {
    const empty = document.createElement("span");
    empty.className = "playlist-marker-empty";
    empty.textContent = "No playlist markers";
    container.appendChild(empty);
    return;
  }
  for (const marker of markers) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "playlist-marker-button";
    button.textContent = marker.name || `Marker ${Number(marker.index) + 1}`;
    button.title = "Move playhead to marker";
    button.disabled = !enabled || state.transport.loading;
    button.addEventListener("click", () => {
      transportAction("jump_to_marker", { index: Number(marker.index) || 0 });
    });
    container.appendChild(button);
  }
}

function renderTransportButtons() {
  const data = getStatusReport() || {};
  const transport = data.transport || {};
  const playing = Boolean(transport.playing);
  const recording = Boolean(transport.recording);
  for (const button of document.querySelectorAll("[data-transport-action]")) {
    const action = button.dataset.transportAction;
    button.disabled = state.transport.loading;
    button.classList.toggle("is-active", (action === "play" && playing) || (action === "record" && recording));
  }
}

function renderTransportFeedback(message, isError = false) {
  const node = byId("transport-feedback");
  if (!node) return;
  const fallback = state.transport.error || "";
  node.textContent = message || fallback;
  node.classList.toggle("is-error", Boolean(isError || fallback));
}

function renderLivePlaybackMounts() {
  const data = getStatusReport() || {};
  const project = data.project || {};
  const transport = data.transport || {};
  const markers = markerRows(transport);
  for (const mount of document.querySelectorAll("[data-live-playback]")) {
    mount.innerHTML = "";
    const panel = document.createElement("article");
    panel.className = "panel live-playback-panel";

    const heading = document.createElement("div");
    heading.className = "panel-heading";
    const title = document.createElement("h2");
    title.textContent = "Live Playback";
    const badge = document.createElement("span");
    badge.className = "badge badge-neutral";
    badge.textContent = transport.playing ? "Level 2" : "Level 1";
    heading.append(title, badge);

    const grid = document.createElement("div");
    grid.className = "live-playback-grid";
    for (const [label, value] of [
      ["Position", formatTransportPosition(transport)],
      ["Tempo", bpm(project.tempo_bpm || transport.tempo?.bpm || transport.tempo)],
      ["Record", transport.recording ? "ON" : "OFF"],
      ["Markers", markers.length ? String(markers.length) : "None"]
    ]) {
      const item = document.createElement("div");
      const key = document.createElement("span");
      key.textContent = label;
      const val = document.createElement("strong");
      val.textContent = safeString(value);
      item.append(key, val);
      grid.appendChild(item);
    }

    const controls = document.createElement("div");
    controls.className = "transport-controls";
    for (const action of ["play", "pause", "stop", "record"]) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = action === "record" ? "transport-button transport-record" : "transport-button";
      button.dataset.transportAction = action;
      button.textContent = action.charAt(0).toUpperCase() + action.slice(1);
      button.addEventListener("click", () => transportAction(action));
      controls.appendChild(button);
    }

    const markerStrip = document.createElement("div");
    markerStrip.className = "playlist-marker-strip";
    renderMarkerStrip(markerStrip, markers, true);

    panel.append(heading, grid, controls, markerStrip);
    mount.appendChild(panel);
  }
  renderTransportButtons();
}

// ─── Mix Review ──────────────────────────────────────────────────────────────
async function runMixReview() {
  state.mixReview.loading = true;
  state.mixReview.error = null;
  renderMixReview();
  try {
    const result = await api("/api/workflows/mix-review", {
      method: "POST",
      body: JSON.stringify(workflowRunBody("mix_review"))
    });
    state.mixReview.report = result;
    syncWorkflowUserDecisions("mix_review", result);
    state.mixReview.error = result?.ok === false
      ? (result.error || "Mix Review unavailable.")
      : null;
  } catch (error) {
    state.mixReview.error = `Mix Review failed: ${error.message}`;
  } finally {
    state.mixReview.loading = false;
    renderMixReview();
  }
}

function renderMixReview() {
  const layout = document.getElementById("mix-review-layout");
  if (!layout) return;

  const report = state.mixReview.report;
  const isLoading = state.mixReview.loading;
  const error = state.mixReview.error;

  setRunButton("run-mix-review", isLoading, "Run Mix Review");

  renderMixFeedback(report, error, isLoading);
  renderWorkflowInteractionMount("mix-review-interactions", "mix_review", report);
  renderMixSummary(report, isLoading);
  renderMixLevels(report);
  renderMixFindings(report);
  renderMixProposals(report);
  renderMixTone(report);
  renderMixStereo(report);
  renderMixTables(report);
  renderMixNotes(report);
}

function renderMixFeedback(report, error, isLoading) {
  setWorkflowFeedback({
    id: "mix-review-feedback",
    baseClass: "mix-review-feedback",
    loading: isLoading,
    error,
    report,
    loadingText: "Mix Review is reading FL Studio mixer data...",
    idleText: "Review has not run yet.",
    completeLabel: "Last review"
  });
}

function renderMixSummary(report, isLoading) {
  const summary = report?.summary || {};
  const score = Number.isFinite(Number(summary.health_score))
    ? Number(summary.health_score)
    : null;
  const label = summary.health_label || (report?.ok ? "Live" : "Idle");

  text("mix-score-value", score == null ? "--" : `${Math.round(score)}%`);
  text("mix-score-caption", isLoading ? "Reading" : label);
  text("mix-score-label", label);
  text("mix-used-total", summary.used_tracks ?? "--");
  text("mix-hot-total", summary.hot_tracks ?? "--");
  text("mix-finding-total", summary.findings ?? "--");
  text("mix-proposal-total", summary.proposals ?? "--");
  text("mix-findings-count", summary.findings ?? 0);
  text("mix-proposals-count", summary.proposals ?? 0);
  text("mix-track-count", summary.tracks ?? 0);
  text("mix-master-peak", formatDb(summary.master_peak_db));
  text("mix-master-headroom", formatDb(summary.master_headroom_db));
  text("mix-peak-source", mixPeakSourceLabel(summary.peak_source));

  const ring = document.getElementById("mix-score-ring");
  if (ring) {
    const clampedScore = score == null ? 0 : Math.max(0, Math.min(100, score));
    ring.style.setProperty("--score", clampedScore);
    ring.dataset.state = routingScoreState(score);
  }

  const scoreLabel = document.getElementById("mix-score-label");
  if (scoreLabel) {
    scoreLabel.className = `badge ${mixBadgeClass(score, report?.ok)}`;
  }

  const levelState = document.getElementById("mix-level-state");
  if (levelState) {
    const hasLevels = summary.levels_valid === true;
    levelState.textContent = isLoading
      ? "Reading"
      : report?.ok
        ? (hasLevels ? "Live" : "Limited")
        : "Idle";
    levelState.className = `badge ${report?.ok && hasLevels ? "badge-ok" : "badge-neutral"}`;
  }

  renderExplicitLabels(".mix-score-stats", report);
}

function renderMixLevels(report) {
  const list = document.getElementById("mix-level-list");
  if (!list) return;
  list.innerHTML = "";

  const tracks = Array.isArray(report?.visuals?.level_tracks)
    ? report.visuals.level_tracks
    : [];
  if (!tracks.length) {
    list.appendChild(mixPlaceholder("Run Mix Review to populate levels."));
    return;
  }

  for (const track of tracks) {
    const stateName = String(track.level_state || "unknown").toLowerCase();
    const row = document.createElement("div");
    row.className = `mix-level-row mix-level-${stateName}`;

    const meta = document.createElement("div");
    meta.className = "mix-level-meta";
    const title = document.createElement("strong");
    title.textContent = safeString(track.name);
    const detail = document.createElement("span");
    detail.textContent = [
      mixTrackNumber(track.track),
      mixTrackRoleLabel(track.role),
      `Fader ${formatDb(track.fader_db)}`
    ].join(" · ");
    meta.append(title, detail);

    const bar = document.createElement("div");
    bar.className = "mix-level-bar";
    const fill = document.createElement("i");
    fill.style.setProperty("--value", mixLevelPercent(track.peak_db));
    bar.appendChild(fill);

    const value = document.createElement("span");
    value.className = "mix-level-value";
    value.textContent = track.mute ? "Muted" : formatDb(track.peak_db);

    row.append(meta, bar, value);
    list.appendChild(row);
  }
}

function renderMixFindings(report) {
  const list = document.getElementById("mix-finding-list");
  if (!list) return;
  list.innerHTML = "";

  const findings = Array.isArray(report?.findings) ? report.findings : [];
  if (!findings.length) {
    list.appendChild(mixPlaceholder("No findings yet."));
    return;
  }

  for (const finding of findings) {
    const row = document.createElement("div");
    row.className = `mix-finding ${mixSeverityClass(finding.severity)}`;

    const icon = document.createElement("span");
    icon.className = "mix-finding-icon";
    icon.textContent = mixSeverityIcon(finding.severity);

    const body = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = safeString(finding.title);
    const detail = document.createElement("span");
    detail.textContent = mixFindingDetail(finding);
    body.append(title, detail);

    const severity = document.createElement("span");
    severity.className = "mix-finding-severity";
    severity.textContent = safeString(finding.severity).toUpperCase();

    row.append(icon, body, severity);
    list.appendChild(row);
  }
}

function renderMixProposals(report) {
  const list = document.getElementById("mix-proposal-list");
  if (!list) return;
  list.innerHTML = "";

  const proposals = Array.isArray(report?.proposals) ? report.proposals : [];
  if (!proposals.length) {
    list.appendChild(mixPlaceholder("No proposals yet."));
    return;
  }

  for (const proposal of proposals) {
    const row = document.createElement("div");
    row.className = `mix-proposal ${mixSeverityClass(proposal.severity)}`;

    const title = document.createElement("strong");
    title.textContent = safeString(proposal.title);

    const detail = document.createElement("span");
    detail.textContent = mixProposalDetail(proposal);

    const values = document.createElement("em");
    values.textContent = mixProposalValues(proposal);

    row.append(title, detail, values);
    list.appendChild(row);
  }
}

function renderMixTone(report) {
  const balance = report?.visuals?.band_balance || {};
  const bands = balance.bands_pct || {};
  for (const band of ["low", "mid", "high"]) {
    const value = Number(bands[band] || 0);
    const meter = document.getElementById(`mix-band-${band}`);
    if (meter) meter.style.setProperty("--value", Math.max(0, Math.min(100, value)));
    text(`mix-band-${band}-value`, formatPercent(value));
  }

  const toneState = document.getElementById("mix-tone-state");
  if (toneState) {
    toneState.textContent = report?.ok ? "Estimate" : "Idle";
    toneState.className = `badge ${report?.ok ? "badge-ok" : "badge-neutral"}`;
  }

  const sources = document.getElementById("mix-band-sources");
  if (!sources) return;
  sources.innerHTML = "";
  const trackBuckets = balance.tracks || {};
  for (const band of ["low", "mid", "high"]) {
    const row = document.createElement("span");
    const names = Array.isArray(trackBuckets[band]) ? trackBuckets[band] : [];
    row.textContent = `${band.toUpperCase()}: ${names.slice(0, 4).map(safeString).join(", ") || "--"}`;
    sources.appendChild(row);
  }
}

function renderMixStereo(report) {
  const field = document.getElementById("mix-stereo-field");
  if (!field) return;
  field.innerHTML = "";

  const tracks = Array.isArray(report?.visuals?.stereo_tracks)
    ? report.visuals.stereo_tracks
    : [];
  text("mix-stereo-count", tracks.length);
  if (!tracks.length) {
    field.appendChild(mixPlaceholder("Run Mix Review to populate stereo metadata."));
    return;
  }

  for (const track of tracks) {
    const row = document.createElement("div");
    row.className = track.low_end ? "mix-stereo-row is-low-end" : "mix-stereo-row";

    const label = document.createElement("div");
    label.className = "mix-stereo-label";
    const name = document.createElement("strong");
    name.textContent = safeString(track.name);
    const detail = document.createElement("span");
    detail.textContent = `${mixTrackNumber(track.track)} · Peak ${formatDb(track.peak_db)}`;
    label.append(name, detail);

    const rail = document.createElement("div");
    rail.className = "mix-stereo-rail";
    const width = document.createElement("span");
    width.className = "mix-stereo-width";
    width.style.setProperty("--width", mixStereoWidth(track.stereo_sep));
    const dot = document.createElement("i");
    dot.className = "mix-stereo-dot";
    dot.style.setProperty("--pan", mixPanPercent(track.pan));
    rail.append(width, dot);

    const value = document.createElement("em");
    value.textContent = `Pan ${formatSigned(track.pan)} · Width ${formatSigned(track.stereo_sep)}`;

    row.append(label, rail, value);
    field.appendChild(row);
  }
}

function renderMixTables(report) {
  const body = document.getElementById("mix-track-table");
  if (!body) return;
  body.innerHTML = "";

  const tracks = Array.isArray(report?.details?.tracks) ? report.details.tracks : [];
  if (!tracks.length) {
    appendMixTableEmpty(body, 7, "No mixer track rows.");
    return;
  }

  for (const track of tracks) {
    const row = document.createElement("tr");
    appendCell(row, `${safeString(track.name)} (${safeString(track.track)})`);
    appendCell(row, formatDb(track.peak_db));
    appendCell(row, formatDb(track.fader_db));
    appendCell(row, formatSigned(track.pan));
    appendCell(row, formatSigned(track.stereo_sep));
    appendCell(row, mixPluginList(track.plugins));
    appendCell(row, mixTrackStateLabel(track), `mix-state-${mixTrackState(track)}`);
    body.appendChild(row);
  }
}

function renderMixNotes(report) {
  const list = document.getElementById("mix-note-list");
  if (!list) return;
  list.innerHTML = "";

  const details = report?.details || {};
  const notes = [
    ...(Array.isArray(details.notes) ? details.notes : []),
    ...(Array.isArray(details.limits) ? details.limits : []),
    ...(Array.isArray(details.gather_errors) ? details.gather_errors : []),
    ...(Array.isArray(details.low_end?.manual_checks) ? details.low_end.manual_checks.map(lowEndManualCheckText) : [])
  ].filter(Boolean);
  text("mix-note-count", notes.length);

  if (!notes.length) {
    list.appendChild(mixPlaceholder("No notes yet."));
    return;
  }

  for (const note of notes.slice(0, 8)) {
    const row = document.createElement("div");
    row.className = "mix-note-row";
    row.textContent = safeString(note);
    list.appendChild(row);
  }
}

// ─── Low-End Analysis ────────────────────────────────────────────────────────
async function runLowEndAnalysis() {
  state.lowEndAnalysis.loading = true;
  state.lowEndAnalysis.error = null;
  renderLowEndAnalysis();
  try {
    const result = await api("/api/workflows/low-end-analysis", {
      method: "POST",
      body: JSON.stringify(workflowRunBody("low_end_analysis"))
    });
    state.lowEndAnalysis.report = result;
    syncWorkflowUserDecisions("low_end_analysis", result);
    state.lowEndAnalysis.error = result?.ok === false
      ? (result.error || "Low-End Analysis unavailable.")
      : null;
  } catch (error) {
    state.lowEndAnalysis.error = `Low-End Analysis failed: ${error.message}`;
  } finally {
    state.lowEndAnalysis.loading = false;
    renderLowEndAnalysis();
  }
}

function renderLowEndAnalysis() {
  const layout = document.getElementById("low-end-layout");
  if (!layout) return;

  const report = state.lowEndAnalysis.report;
  const isLoading = state.lowEndAnalysis.loading;
  const error = state.lowEndAnalysis.error;

  setRunButton("run-low-end-analysis", isLoading, "Run Low-End Analysis");

  renderLowEndFeedback(report, error, isLoading);
  renderWorkflowInteractionMount("low-end-interactions", "low_end_analysis", report);
  renderLowEndSummary(report, isLoading);
  renderLowEndFocus(report);
  renderLowEndFindings(report);
  renderLowEndBalance(report);
  renderLowEndStereo(report);
  renderLowEndTable(report);
  renderLowEndNotes(report);
}

function renderLowEndFeedback(report, error, isLoading) {
  setWorkflowFeedback({
    id: "low-end-feedback",
    baseClass: "low-end-feedback",
    loading: isLoading,
    error,
    report,
    loadingText: "Low-End Analysis is reading FL Studio mixer data...",
    idleText: "Analysis has not run yet.",
    completeLabel: "Last analysis"
  });
}

function renderLowEndSummary(report, isLoading) {
  const tracks = lowEndTracks(report);
  const findings = lowEndFindings(report);
  const score = lowEndScore(report, tracks, findings);
  const label = lowEndScoreLabel(score, report?.ok);
  const summary = report?.summary || {};

  text("low-end-score-value", score == null ? "--" : `${Math.round(score)}%`);
  text("low-end-score-caption", isLoading ? "Reading" : label);
  text("low-end-score-label", label);
  text("low-end-track-total", report ? tracks.length : "--");
  text("low-end-finding-total", report ? findings.length : "--");
  text("low-end-findings-count", findings.length);
  text("low-end-detail-count", tracks.length);
  text("low-end-master-headroom", formatDb(summary.master_headroom_db));
  text("low-end-peak-source", mixPeakSourceLabel(summary.peak_source));

  const ring = document.getElementById("low-end-score-ring");
  if (ring) {
    const clampedScore = score == null ? 0 : Math.max(0, Math.min(100, score));
    ring.style.setProperty("--score", clampedScore);
    ring.dataset.state = routingScoreState(score);
  }

  const scoreLabel = document.getElementById("low-end-score-label");
  if (scoreLabel) {
    scoreLabel.className = `badge ${mixBadgeClass(score, report?.ok)}`;
  }

  const mapState = document.getElementById("low-end-map-state");
  if (mapState) {
    mapState.textContent = isLoading ? "Reading" : (report?.ok ? "Live" : "Idle");
    mapState.className = `badge ${report?.ok ? "badge-ok" : "badge-neutral"}`;
  }

  renderExplicitLabels(".low-end-score-stats", report);
}

function renderLowEndFocus(report) {
  const board = document.getElementById("low-end-focus-board");
  if (!board) return;
  board.innerHTML = "";

  const tracks = lowEndTracks(report);
  if (!tracks.length) {
    board.appendChild(lowEndPlaceholder("Run Low-End Analysis to populate kick, bass, and sub focus tracks."));
    return;
  }

  const lanes = [
    { id: "kick", title: "Kick", tracks: tracks.filter(track => track.low_end_role === "kick") },
    { id: "sub", title: "Sub / 808", tracks: tracks.filter(track => track.low_end_role === "sub") },
    { id: "bass", title: "Bass", tracks: tracks.filter(track => track.low_end_role === "bass") },
    { id: "other", title: "Other Low-End", tracks: tracks.filter(track => track.low_end_role === "other") }
  ];

  for (const lane of lanes) {
    const laneEl = document.createElement("div");
    laneEl.className = `low-end-lane low-end-lane-${lane.id}`;

    const heading = document.createElement("div");
    heading.className = "low-end-lane-heading";
    const title = document.createElement("strong");
    title.textContent = lane.title;
    const count = document.createElement("span");
    count.textContent = lane.tracks.length;
    heading.append(title, count);
    laneEl.appendChild(heading);

    if (!lane.tracks.length) {
      const empty = document.createElement("div");
      empty.className = "low-end-lane-empty";
      empty.textContent = "No named track";
      laneEl.appendChild(empty);
    }

    for (const track of lane.tracks.slice(0, 4)) {
      const item = document.createElement("div");
      item.className = lowEndTrackStereoRisk(track)
        ? "low-end-focus-item has-stereo-risk"
        : "low-end-focus-item";

      const meta = document.createElement("div");
      meta.className = "low-end-focus-meta";
      const name = document.createElement("strong");
      name.textContent = safeString(track.name);
      const detail = document.createElement("span");
      detail.textContent = `${mixTrackNumber(track.track)} · Peak ${formatDb(track.peak_db)}`;
      meta.append(name, detail);

      const meter = document.createElement("div");
      meter.className = "low-end-focus-meter";
      const fill = document.createElement("i");
      fill.style.setProperty("--value", mixLevelPercent(track.peak_db));
      meter.appendChild(fill);

      const stereo = document.createElement("span");
      stereo.className = "low-end-focus-stereo";
      stereo.textContent = `Pan ${formatSigned(track.pan)} · Width ${formatSigned(track.stereo_sep)}`;

      item.append(meta, meter, stereo);
      laneEl.appendChild(item);
    }

    board.appendChild(laneEl);
  }
}

function renderLowEndFindings(report) {
  const list = document.getElementById("low-end-finding-list");
  if (!list) return;
  list.innerHTML = "";

  const findings = lowEndFindings(report);
  if (!findings.length) {
    list.appendChild(lowEndPlaceholder(report ? "No low-end findings in the current analysis." : "No analysis result yet."));
    return;
  }

  for (const finding of findings) {
    const row = document.createElement("div");
    row.className = `low-end-finding ${mixSeverityClass(finding.severity)}`;

    const icon = document.createElement("span");
    icon.className = "low-end-finding-icon";
    icon.textContent = mixSeverityIcon(finding.severity);

    const body = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = safeString(finding.title);
    const detail = document.createElement("span");
    detail.textContent = mixFindingDetail(finding);
    body.append(title, detail);

    const severity = document.createElement("span");
    severity.className = "low-end-finding-severity";
    severity.textContent = safeString(finding.severity).toUpperCase();

    row.append(icon, body, severity);
    list.appendChild(row);
  }
}

function renderLowEndBalance(report) {
  const balance = report?.visuals?.band_balance || {};
  const bands = balance.bands_pct || {};
  for (const band of ["low", "mid", "high"]) {
    const value = Number(bands[band] || 0);
    const meter = document.getElementById(`low-end-band-${band}`);
    if (meter) meter.style.setProperty("--value", Math.max(0, Math.min(100, value)));
    text(`low-end-band-${band}-value`, formatPercent(value));
  }

  const stateEl = document.getElementById("low-end-balance-state");
  if (stateEl) {
    stateEl.textContent = report?.ok ? "Estimate" : "Idle";
    stateEl.className = `badge ${report?.ok ? "badge-ok" : "badge-neutral"}`;
  }

  const sources = document.getElementById("low-end-band-sources");
  if (!sources) return;
  sources.innerHTML = "";
  const trackBuckets = balance.tracks || {};
  for (const band of ["low", "mid", "high"]) {
    const row = document.createElement("span");
    const names = Array.isArray(trackBuckets[band]) ? trackBuckets[band] : [];
    row.textContent = `${band.toUpperCase()}: ${names.slice(0, 5).map(safeString).join(", ") || "--"}`;
    sources.appendChild(row);
  }
}

function renderLowEndStereo(report) {
  const field = document.getElementById("low-end-stereo-field");
  if (!field) return;
  field.innerHTML = "";

  const tracks = lowEndTracks(report);
  text("low-end-stereo-count", tracks.length);
  if (!tracks.length) {
    field.appendChild(lowEndPlaceholder("Run Low-End Analysis to populate stereo and mono-safety metadata."));
    return;
  }

  for (const track of tracks) {
    const row = document.createElement("div");
    row.className = lowEndTrackStereoRisk(track)
      ? "low-end-stereo-row has-stereo-risk"
      : "low-end-stereo-row";

    const label = document.createElement("div");
    label.className = "low-end-stereo-label";
    const name = document.createElement("strong");
    name.textContent = safeString(track.name);
    const detail = document.createElement("span");
    detail.textContent = `${mixTrackNumber(track.track)} · ${lowEndRoleLabel(track.low_end_role)}`;
    label.append(name, detail);

    const rail = document.createElement("div");
    rail.className = "low-end-stereo-rail";
    const width = document.createElement("span");
    width.className = "low-end-stereo-width";
    width.style.setProperty("--width", mixStereoWidth(track.stereo_sep));
    const dot = document.createElement("i");
    dot.className = "low-end-stereo-dot";
    dot.style.setProperty("--pan", mixPanPercent(track.pan));
    rail.append(width, dot);

    const value = document.createElement("em");
    value.textContent = `Pan ${formatSigned(track.pan)} · Width ${formatSigned(track.stereo_sep)}`;

    row.append(label, rail, value);
    field.appendChild(row);
  }
}

function renderLowEndTable(report) {
  const body = document.getElementById("low-end-track-table");
  if (!body) return;
  body.innerHTML = "";

  const tracks = lowEndTracks(report);
  if (!tracks.length) {
    appendMixTableEmpty(body, 7, "No low-end track rows.");
    return;
  }

  for (const track of tracks) {
    const row = document.createElement("tr");
    appendCell(row, `${safeString(track.name)} (${safeString(track.track)})`);
    appendCell(row, lowEndRoleLabel(track.low_end_role));
    appendCell(row, formatDb(track.peak_db));
    appendCell(row, formatDb(track.fader_db));
    appendCell(row, formatSigned(track.pan));
    appendCell(row, formatSigned(track.stereo_sep), lowEndTrackStereoRisk(track) ? "low-end-risk-value" : "");
    appendCell(row, mixPluginList(track.plugins));
    body.appendChild(row);
  }
}

function renderLowEndNotes(report) {
  const list = document.getElementById("low-end-note-list");
  if (!list) return;
  list.innerHTML = "";

  const details = report?.details || {};
  const lowEnd = details.low_end || {};
  const notes = [
    ...(Array.isArray(details.limits) ? details.limits : []),
    ...(Array.isArray(details.gather_errors) ? details.gather_errors : []),
    ...(Array.isArray(lowEnd.manual_checks) ? lowEnd.manual_checks.map(lowEndManualCheckText) : [])
  ].filter(Boolean);

  text("low-end-note-count", notes.length);
  if (!notes.length) {
    list.appendChild(lowEndPlaceholder("No low-end notes yet."));
    return;
  }

  for (const note of notes.slice(0, 8)) {
    const row = document.createElement("div");
    row.className = "low-end-note-row";
    row.textContent = safeString(note);
    list.appendChild(row);
  }
}

function appendMixTableEmpty(body, colspan, message) {
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.colSpan = colspan;
  cell.className = "mix-table-empty";
  cell.textContent = message;
  row.appendChild(cell);
  body.appendChild(row);
}

function mixPlaceholder(message) {
  const node = document.createElement("div");
  node.className = "mix-placeholder";
  node.textContent = message;
  return node;
}

function mixBadgeClass(score, ok) {
  if (!ok || score == null) return "badge-neutral";
  if (score >= 90) return "badge-ok";
  if (score >= 75) return "badge-warn";
  return "badge-warn";
}

function mixSeverityClass(severity) {
  const value = String(severity || "").toLowerCase();
  if (value === "critical" || value === "high") return "is-critical";
  if (value === "warning" || value === "medium") return "is-warning";
  if (value === "ok") return "is-ok";
  return "is-info";
}

function mixSeverityIcon(severity) {
  const value = String(severity || "").toLowerCase();
  if (value === "critical" || value === "high") return "!";
  if (value === "warning" || value === "medium") return "△";
  if (value === "ok") return "✓";
  return "i";
}

function mixFindingDetail(finding) {
  const track = finding.track == null ? "" : `Track ${finding.track}: `;
  return `${track}${safeString(finding.detail || finding.evidence)}`;
}

function mixProposalDetail(proposal) {
  const track = proposal.track_name || proposal.track;
  const prefix = track == null ? "" : `${safeString(track)} · `;
  return `${prefix}${safeString(proposal.detail || proposal.kind)}`;
}

function mixProposalValues(proposal) {
  const values = [];
  if (proposal.current_fader_db != null || proposal.target_fader_db != null) {
    values.push(`${formatDb(proposal.current_fader_db)} → ${formatDb(proposal.target_fader_db)}`);
  }
  if (proposal.current_peak_db != null || proposal.target_peak_db != null) {
    values.push(`Peak ${formatDb(proposal.current_peak_db)} → ${formatDb(proposal.target_peak_db)}`);
  }
  return values.join(" · ") || (proposal.actionable ? "Actionable" : "Manual review");
}

function mixPluginList(plugins) {
  if (!Array.isArray(plugins) || !plugins.length) return "None";
  const names = plugins.map(plugin => safeString(plugin.name)).filter(name => name !== "Unavailable");
  if (!names.length) return "None";
  const shown = names.slice(0, 3).join(", ");
  return names.length > 3 ? `${shown}, +${names.length - 3}` : shown;
}

function mixTrackState(track) {
  if (track.mute) return "muted";
  if (track.solo) return "solo";
  return track.used ? "used" : "idle";
}

function mixTrackStateLabel(track) {
  const stateName = mixTrackState(track);
  const labels = {
    used: "Used",
    idle: "Idle",
    muted: "Muted",
    solo: "Solo"
  };
  return labels[stateName] || "Unknown";
}

function mixTrackNumber(value) {
  return value == null ? "Track ?" : (Number(value) === 0 ? "Master" : `Track ${value}`);
}

function mixTrackRoleLabel(role) {
  const labels = {
    master: "Master",
    bus: "Bus",
    stem_bus: "Stem Bus",
    premaster: "Premaster",
    insert: "Insert",
    source: "Source",
    utility: "Utility"
  };
  return labels[role] || safeString(role);
}

function mixPeakSourceLabel(value) {
  if (!value || value === "none") return "--";
  return safeString(String(value).replaceAll("_", " "));
}

function mixLevelPercent(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 0;
  return Math.max(3, Math.min(100, ((numeric + 48) / 48) * 100));
}

function mixPanPercent(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 50;
  return Math.max(4, Math.min(96, 50 + numeric * 42));
}

function mixStereoWidth(value) {
  const numeric = Math.abs(Number(value));
  if (!Number.isFinite(numeric)) return 10;
  return Math.max(10, Math.min(72, 10 + numeric * 62));
}

function lowEndFindings(report) {
  const findings = report?.details?.low_end?.findings;
  return Array.isArray(findings) ? findings : [];
}

function lowEndTracks(report) {
  const rows = new Map();

  function keyFor(track) {
    if (track.track != null) return `track:${track.track}`;
    if (track.name) return `name:${String(track.name).toLowerCase()}`;
    return null;
  }

  function put(raw, forceLowEnd = false) {
    if (!raw || typeof raw !== "object") return;
    const name = raw.name || raw.track_name;
    if (!forceLowEnd && !lowEndNameMatches(name)) return;
    const normalized = {
      track: raw.track,
      name,
      role: raw.role,
      fader_db: raw.fader_db,
      peak_db: raw.peak_db,
      pan: raw.pan,
      stereo_sep: raw.stereo_sep,
      plugins: raw.plugins,
      low_end_role: lowEndRole(name)
    };
    const key = keyFor(normalized);
    if (!key) return;
    const merged = { ...(rows.get(key) || {}) };
    for (const [field, value] of Object.entries(normalized)) {
      if (value != null && value !== "") merged[field] = value;
    }
    if (!Array.isArray(merged.plugins)) merged.plugins = [];
    if (!merged.low_end_role) merged.low_end_role = lowEndRole(merged.name);
    rows.set(key, merged);
  }

  const details = Array.isArray(report?.details?.tracks) ? report.details.tracks : [];
  const explicit = Array.isArray(report?.details?.low_end?.tracks)
    ? report.details.low_end.tracks
    : [];
  const stereo = Array.isArray(report?.visuals?.stereo_tracks)
    ? report.visuals.stereo_tracks
    : [];

  details.forEach(track => put(track));
  explicit.forEach(track => put(track, true));
  stereo.forEach(track => put(track, Boolean(track.low_end)));

  const roleOrder = { kick: 0, sub: 1, bass: 2, other: 3 };
  return Array.from(rows.values())
    .sort((a, b) => {
      const roleDelta = (roleOrder[a.low_end_role] ?? 9) - (roleOrder[b.low_end_role] ?? 9);
      if (roleDelta !== 0) return roleDelta;
      return mixPeakSortValue(b.peak_db) - mixPeakSortValue(a.peak_db);
    })
    .slice(0, 18);
}

function lowEndNameMatches(value) {
  const name = String(value || "").toLowerCase();
  return ["kick", "sub", "bass", "808", "boom"].some(keyword => name.includes(keyword));
}

function lowEndRole(value) {
  const name = String(value || "").toLowerCase();
  if (name.includes("kick")) return "kick";
  if (name.includes("sub") || name.includes("808")) return "sub";
  if (name.includes("bass")) return "bass";
  return "other";
}

function lowEndRoleLabel(role) {
  const labels = {
    kick: "Kick",
    sub: "Sub / 808",
    bass: "Bass",
    other: "Other Low-End"
  };
  return labels[role] || "Low-End";
}

function lowEndTrackStereoRisk(track) {
  const pan = Math.abs(Number(track?.pan));
  const stereo = Number(track?.stereo_sep);
  return (Number.isFinite(pan) && pan >= 0.2)
    || (Number.isFinite(stereo) && stereo >= 0.25);
}

function lowEndScore(report, tracks, findings) {
  if (report?.summary?.health_score != null) {
    return report.summary.health_score;
  }
  // COMPATIBILITY FALLBACK FOR OLD PAYLOADS
  if (!report) return null;
  if (report.ok === false) return 0;
  const rows = Array.isArray(findings) ? findings : [];
  const high = rows.filter(row => ["high", "critical"].includes(String(row.severity || "").toLowerCase())).length;
  const medium = rows.filter(row => ["medium", "warning"].includes(String(row.severity || "").toLowerCase())).length;
  const low = rows.filter(row => String(row.severity || "").toLowerCase() === "low").length;
  const stereoRisks = (tracks || []).filter(lowEndTrackStereoRisk).length;
  const levelsValid = report?.summary?.levels_valid !== false;
  const penalty = high * 24 + medium * 12 + low * 4 + stereoRisks * 5 + (levelsValid ? 0 : 8);
  return Math.max(0, Math.min(100, 100 - penalty));
}

function lowEndScoreLabel(score, ok) {
  if (!ok || score == null) return "Idle";
  if (score >= 90) return "Solid";
  if (score >= 75) return "Needs Review";
  return "At Risk";
}

function renderExplicitLabels(containerSelector, report) {
  const container = document.querySelector(containerSelector);
  if (!container || !report) return;

  let explicitDiv = container.querySelector(".explicit-labels-group");
  if (!explicitDiv) {
    explicitDiv = document.createElement("div");
    explicitDiv.className = "explicit-labels-group";
    explicitDiv.style.gridColumn = "1 / -1";
    explicitDiv.style.display = "grid";
    explicitDiv.style.gridTemplateColumns = "repeat(2, 1fr)";
    explicitDiv.style.gap = "var(--space-3)";
    container.insertBefore(explicitDiv, container.firstChild);
  }

  explicitDiv.innerHTML = "";

  const addStat = (label, value) => {
    const div = document.createElement("div");
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value;
    div.append(dt, dd);
    explicitDiv.append(div);
  };

  const analysis = report.analysis || {};
  const h = analysis.health_score ?? report.summary?.health_score;
  const r = analysis.risk_score ?? report.summary?.risk_score;
  const c = analysis.coverage;
  const conf = analysis.confidence_score;

  if (h != null) addStat("Health", `${Math.round(h)} / 100`);
  if (r != null) addStat("Risk", `${Math.round(r)} / 100`);
  if (c != null && c.required) addStat("Coverage", `${c.available} / ${c.required}`);
  if (conf != null) {
    const band = conf >= 75 ? "High" : conf >= 40 ? "Medium" : "Low";
    addStat("Confidence", band);
  }
}

function lowEndManualCheckText(check) {
  if (typeof check === "string") return check;
  if (!check || typeof check !== "object") return "";
  const topic = check.topic ? `${safeString(check.topic).replaceAll("_", " ")}: ` : "";
  const detail = check.check || check.reason || "";
  return `${topic}${safeString(detail)}`;
}

function lowEndPlaceholder(message) {
  const node = document.createElement("div");
  node.className = "low-end-placeholder";
  node.textContent = message;
  return node;
}

function mixPeakSortValue(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : -999;
}

function formatDb(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "--";
  return `${numeric.toFixed(1)} dB`;
}

function formatPercent(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "--";
  return `${numeric.toFixed(1)}%`;
}

function formatSigned(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "--";
  return `${numeric >= 0 ? "+" : ""}${numeric.toFixed(2)}`;
}

// ─── Routing Audit ───────────────────────────────────────────────────────────
function routingAuditOptions() {
  const mode = document.getElementById("routing-check-mode")?.value || "level_1_static";
  const compliance = document.getElementById("routing-template-compliance")?.value || "auto_detect";
  const selected = document.getElementById("routing-template-profile")?.value || "";
  const options = {
    routing_check_mode: mode,
    template_compliance: compliance,
  };
  if (compliance === "manual_select" && selected) {
    options.selected_template_profile = selected;
  }
  if (mode === "level_2_signal_flow") {
    const level2 = state.routingAudit.level2 || {};
    if (level2.decision) options.playback_decision = level2.decision;
    if (level2.markerName) options.marker_name = level2.markerName;
    if (level2.loopDurationSeconds) options.loop_duration_seconds = level2.loopDurationSeconds;
  }
  return options;
}

function routingTemplateProfiles() {
  const rows = state.routingAudit.report?.details?.template_profile_catalog
    || state.status?.ui?.template_profile_catalog
    || [];
  return Array.isArray(rows) ? rows : [];
}

function populateRoutingTemplateProfiles() {
  const select = document.getElementById("routing-template-profile");
  if (!select) return;
  const previous = select.value;
  const profiles = routingTemplateProfiles();
  select.innerHTML = "";
  if (!profiles.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No profiles loaded";
    select.appendChild(option);
    return;
  }
  for (const profile of profiles) {
    const option = document.createElement("option");
    option.value = profile.profile_id || "";
    option.textContent = profile.display_name || profile.profile_id || "Template Profile";
    select.appendChild(option);
  }
  if (previous && [...select.options].some(option => option.value === previous)) {
    select.value = previous;
  }
}

function resetRoutingLevel2Flow() {
  state.routingAudit.level2 = {
    stage: "idle",
    decision: null,
    markerName: null,
    loopDurationSeconds: null
  };
}

function routingLevel2Ready() {
  const level2 = state.routingAudit.level2 || {};
  return ["ready_auto", "ready_manual", "ready_existing_loop"].includes(level2.stage);
}

async function runRoutingAuditWithCurrentOptions() {
  state.routingAudit.loading = true;
  state.routingAudit.error = null;
  renderRoutingAudit();
  try {
    const result = await api("/api/workflows/routing-audit", {
      method: "POST",
      body: JSON.stringify(workflowRunBody("routing_audit", routingAuditOptions()))
    });
    state.routingAudit.report = result;
    syncWorkflowUserDecisions("routing_audit", result);
    state.routingAudit.error = result?.ok === false
      ? (result.error || "Routing Audit unavailable.")
      : null;
    if (
      result?.routing_check_level === 2
      && result?.details?.signal_flow
      && result.details.signal_flow.available === false
    ) {
      state.routingAudit.level2 = {
        ...state.routingAudit.level2,
        stage: "fallback"
      };
    }
  } catch (error) {
    state.routingAudit.error = `Routing Audit failed: ${error.message}`;
  } finally {
    state.routingAudit.loading = false;
    renderRoutingAudit();
  }
}

async function runRoutingAudit() {
  const options = routingAuditOptions();
  if (options.routing_check_mode !== "level_2_signal_flow") {
    resetRoutingLevel2Flow();
    await runRoutingAuditWithCurrentOptions();
    return;
  }
  if (!routingLevel2Ready()) {
    state.routingAudit.level2 = {
      ...state.routingAudit.level2,
      stage: "choose"
    };
    renderRoutingAudit();
    return;
  }
  await runRoutingAuditWithCurrentOptions();
}

function renderRoutingAudit() {
  const layout = document.getElementById("routing-audit-layout");
  if (!layout) return;

  const report = state.routingAudit.report;
  const isLoading = state.routingAudit.loading;
  const error = state.routingAudit.error;

  setRunButton("run-routing-audit", isLoading, "Run Routing Audit");

  renderRoutingFeedback(report, error, isLoading);
  renderRoutingControls(report);
  renderWorkflowInteractionMount("routing-audit-interactions", "routing_audit", report);
  renderRoutingSummary(report, isLoading);
  renderRoutingGraph(report);
  renderRoutingFindings(report);
  renderRoutingRisks(report);
  renderRoutingTables(report);
}

function renderRoutingControls(report) {
  populateRoutingTemplateProfiles();
  const compliance = document.getElementById("routing-template-compliance")?.value || "auto_detect";
  const profileWrap = document.getElementById("routing-template-profile-wrap");
  if (profileWrap) profileWrap.hidden = compliance !== "manual_select";

  const status = document.getElementById("routing-template-status");
  if (status) {
    const template = report?.details?.template_status || {};
    if (compliance === "off") {
      status.textContent = "Template Compliance: Off";
    } else if (template.display_name && template.profile_source === "manual_select") {
      status.textContent = `Selected template: ${safeString(template.display_name)} / Confidence: ${safeString(template.confidence)}`;
    } else if (template.display_name) {
      status.textContent = `Detected template: ${safeString(template.display_name)} / Confidence: ${safeString(template.confidence)}`;
    } else if (compliance === "manual_select") {
      status.textContent = "Selected template: choose a profile before running compliance checks.";
    } else {
      status.textContent = "Template Compliance: Auto-detect";
    }
  }

  renderRoutingLevel2Flow(report);
}

function renderRoutingLevel2Flow(report) {
  const container = document.getElementById("routing-level2-flow");
  if (!container) return;
  container.innerHTML = "";
  const mode = document.getElementById("routing-check-mode")?.value || "level_1_static";
  if (mode !== "level_2_signal_flow") return;

  const level2 = state.routingAudit.level2 || {};
  const stage = level2.stage || "idle";
  if (stage === "idle") {
    container.appendChild(routingLevel2Notice(
      "Signal Flow Assisted Routing Audit (Lvl 2)",
      "Level 2 requires playback to collect simple signal-flow data such as peak activity and level changes. Lower your monitoring volume before continuing.",
      [
        ["Prepare Level 2", () => {
          state.routingAudit.level2 = { ...level2, stage: "choose" };
          renderRoutingAudit();
        }]
      ]
    ));
    return;
  }

  if (stage === "choose") {
    container.appendChild(routingLevel2Notice(
      "Signal Flow Assisted Routing Audit (Lvl 2)",
      "Do you want FLS Pilot to start playback automatically?",
      [
        ["Start playback automatically", () => startRoutingLevel2Automatic()],
        ["I will start playback manually", () => showRoutingManualPlayback()],
        ["Cancel Level 2 check", () => {
          resetRoutingLevel2Flow();
          const modeSelect = document.getElementById("routing-check-mode");
          if (modeSelect) modeSelect.value = "level_1_static";
          renderRoutingAudit();
        }]
      ]
    ));
    return;
  }

  if (stage === "marker_found") {
    const marker = level2.marker || {};
    container.appendChild(routingLevel2Notice(
      "Analysis Marker Found",
      `FLS Pilot found a possible analysis marker: "${safeString(marker.name)}". Use this marker for the Signal Flow Assisted Routing Audit (Lvl 2)?`,
      [
        ["Use marker and start playback", () => useRoutingMarkerAndStart(marker)],
        ["Choose another marker", () => showRoutingMarkerChooser()],
        ["I will set the loop manually", () => showRoutingManualLoopPrompt()],
        ["Cancel", () => { resetRoutingLevel2Flow(); renderRoutingAudit(); }]
      ]
    ));
    return;
  }

  if (stage === "choose_marker") {
    container.appendChild(routingMarkerChooser());
    return;
  }

  if (stage === "no_marker") {
    container.appendChild(routingLevel2Notice(
      "Set An Analysis Loop",
      "No suitable analysis marker was found. Please set a playlist marker or loop around the loudest or most representative section of the song. Recommended loop length: 8-60 seconds.",
      [
        ["I have set the marker/loop - continue", () => {
          state.routingAudit.level2 = {
            stage: "ready_existing_loop",
            decision: "start_playback_automatically",
            markerName: null,
            loopDurationSeconds: 16
          };
          runRoutingAuditWithCurrentOptions();
        }],
        ["I will start playback manually", () => showRoutingManualPlayback()],
        ["Run Static Routing & Settings Audit (Lvl 1) instead", () => runRoutingLevel1Instead()],
        ["Cancel", () => { resetRoutingLevel2Flow(); renderRoutingAudit(); }]
      ]
    ));
    return;
  }

  if (stage === "manual") {
    container.appendChild(routingLevel2Notice(
      "Manual Playback",
      "Please start playback in FL Studio and loop the loudest or most representative section of the song. Recommended loop length: 8-60 seconds.",
      [
        ["Playback is running - start analysis", () => {
          state.routingAudit.level2 = {
            stage: "ready_manual",
            decision: "manual_playback_running",
            markerName: null,
            loopDurationSeconds: 16
          };
          runRoutingAuditWithCurrentOptions();
        }],
        ["Run Level 1", () => runRoutingLevel1Instead()],
        ["Cancel", () => { resetRoutingLevel2Flow(); renderRoutingAudit(); }]
      ]
    ));
    return;
  }

  if (stage === "fallback") {
    container.appendChild(routingLevel2Notice(
      "Signal Flow Data Unavailable",
      "Signal Flow Assisted Routing Audit (Lvl 2) could not collect signal-flow data. You can either set a loop and try again, or run Static Routing & Settings Audit (Lvl 1) instead.",
      [
        ["Try Level 2 again", () => {
          state.routingAudit.level2 = { stage: "choose", decision: null, markerName: null, loopDurationSeconds: null };
          renderRoutingAudit();
        }],
        ["Run Level 1", () => runRoutingLevel1Instead()],
        ["Cancel", () => { resetRoutingLevel2Flow(); renderRoutingAudit(); }]
      ]
    ));
    return;
  }

  if (routingLevel2Ready()) {
    container.appendChild(routingLevel2Notice(
      "Level 2 Ready",
      "Playback evidence is ready for a signal-flow assisted routing audit.",
      [
        ["Run Signal Flow Assisted Routing Audit (Lvl 2)", () => runRoutingAuditWithCurrentOptions()],
        ["Reset", () => { resetRoutingLevel2Flow(); renderRoutingAudit(); }]
      ]
    ));
  }
}

function routingLevel2Notice(titleText, bodyText, actions = []) {
  const panel = document.createElement("div");
  panel.className = "routing-level2-card";
  const title = document.createElement("strong");
  title.textContent = titleText;
  const body = document.createElement("p");
  body.textContent = bodyText;
  const actionRow = document.createElement("div");
  actionRow.className = "routing-level2-actions";
  for (const [label, handler] of actions) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = label.includes("Run") || label.includes("Use") || label.includes("start")
      ? "ghost-button primary-action"
      : "ghost-button";
    button.textContent = label;
    button.addEventListener("click", handler);
    actionRow.appendChild(button);
  }
  panel.append(title, body, actionRow);
  return panel;
}

function routingAnalysisMarkers() {
  const markers = markerRows(getStatusReport()?.transport || {});
  return markers.filter(marker => {
    const name = String(marker.name || "").toLowerCase();
    return ROUTING_LEVEL2_MARKER_NAMES.some(token => name.includes(token));
  });
}

function startRoutingLevel2Automatic() {
  const markers = routingAnalysisMarkers();
  if (markers.length) {
    state.routingAudit.level2 = {
      ...state.routingAudit.level2,
      stage: "marker_found",
      marker: markers[0],
      markerName: markers[0].name || null
    };
  } else {
    state.routingAudit.level2 = {
      ...state.routingAudit.level2,
      stage: "no_marker",
      decision: null,
      markerName: null
    };
  }
  renderRoutingAudit();
}

function showRoutingMarkerChooser() {
  state.routingAudit.level2 = {
    ...state.routingAudit.level2,
    stage: "choose_marker"
  };
  renderRoutingAudit();
}

function routingMarkerChooser() {
  const markers = markerRows(getStatusReport()?.transport || {});
  const panel = routingLevel2Notice(
    "Choose Analysis Marker",
    "Select the playlist marker that starts the loudest or most representative section.",
    []
  );
  const row = panel.querySelector(".routing-level2-actions");
  for (const marker of markers) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ghost-button";
    button.textContent = marker.name || `Marker ${Number(marker.index) + 1}`;
    button.addEventListener("click", () => useRoutingMarkerAndStart(marker));
    row.appendChild(button);
  }
  const manual = document.createElement("button");
  manual.type = "button";
  manual.className = "ghost-button";
  manual.textContent = "I will set the loop manually";
  manual.addEventListener("click", showRoutingManualLoopPrompt);
  row.appendChild(manual);
  return panel;
}

function showRoutingManualLoopPrompt() {
  state.routingAudit.level2 = {
    ...state.routingAudit.level2,
    stage: "no_marker"
  };
  renderRoutingAudit();
}

function showRoutingManualPlayback() {
  state.routingAudit.level2 = {
    stage: "manual",
    decision: "manual_playback",
    markerName: null,
    loopDurationSeconds: null
  };
  renderRoutingAudit();
}

async function useRoutingMarkerAndStart(marker) {
  state.routingAudit.level2 = {
    stage: "ready_auto",
    decision: "start_playback_automatically",
    markerName: marker?.name || null,
    loopDurationSeconds: 16
  };
  if (marker && marker.index != null) {
    await transportAction("jump_to_marker", { index: Number(marker.index) || 0 });
  }
  await transportAction("play");
  await runRoutingAuditWithCurrentOptions();
}

async function runRoutingLevel1Instead() {
  resetRoutingLevel2Flow();
  const modeSelect = document.getElementById("routing-check-mode");
  if (modeSelect) modeSelect.value = "level_1_static";
  await runRoutingAuditWithCurrentOptions();
}

function renderRoutingFeedback(report, error, isLoading) {
  setWorkflowFeedback({
    id: "routing-audit-feedback",
    baseClass: "routing-audit-feedback",
    loading: isLoading,
    error,
    report,
    loadingText: "Routing Audit is reading FL Studio routing data...",
    idleText: "Audit has not run yet.",
    completeLabel: "Last audit"
  });
}

function renderRoutingSummary(report, isLoading) {
  const summary = report?.summary || {};
  const score = Number.isFinite(Number(summary.health_score))
    ? Number(summary.health_score)
    : null;
  const label = summary.health_label || (report?.ok ? "Live" : "Idle");

  text("routing-score-value", score == null ? "--" : `${Math.round(score)}%`);
  text("routing-score-caption", isLoading ? "Reading" : label);
  text("routing-score-label", label);
  text("routing-automation-total", summary.unrouted_automation_clips ?? "--");
  text("routing-channel-total", summary.channels ?? "--");
  text("routing-track-total", summary.mixer_tracks ?? "--");
  text("routing-route-total", summary.routes ?? "--");
  text("routing-channel-count", summary.channels ?? 0);
  text("routing-track-count", summary.mixer_tracks ?? 0);
  text("routing-route-count", summary.routes ?? 0);
  text("routing-findings-count", report?.findings?.length ?? 0);

  const ring = document.getElementById("routing-score-ring");
  if (ring) {
    const clampedScore = score == null ? 0 : Math.max(0, Math.min(100, score));
    ring.style.setProperty("--score", clampedScore);
    ring.dataset.state = routingScoreState(score);
  }

  const mapState = document.getElementById("routing-map-state");
  if (mapState) {
    mapState.textContent = isLoading ? "Reading" : (report?.ok ? "Live" : "Idle");
    mapState.className = `badge ${report?.ok ? "badge-ok" : "badge-neutral"}`;
  }
}

function renderRoutingGraph(report) {
  const columns = {
    sources: document.getElementById("routing-graph-sources"),
    buses: document.getElementById("routing-graph-buses"),
    master: document.getElementById("routing-graph-master")
  };
  const svg = document.getElementById("routing-links");
  for (const column of Object.values(columns)) {
    if (column) column.innerHTML = "";
  }
  if (svg) svg.innerHTML = "";

  const graph = report?.graph || {};
  const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
  if (!nodes.length) {
    const empty = document.createElement("div");
    empty.className = "routing-empty-state";
    empty.textContent = report?.ok === false
      ? "Routing graph unavailable."
      : "No routing graph data.";
    if (columns.sources) columns.sources.appendChild(empty);
    return;
  }

  for (const node of nodes) {
    const column = columns[node.column] || columns.sources;
    if (!column) continue;
    const item = document.createElement("div");
    item.className = `routing-node ${routingNodeClass(node.kind)}`;
    item.dataset.routingNodeId = node.id;

    const dot = document.createElement("span");
    dot.className = "routing-node-dot";
    const label = document.createElement("strong");
    label.textContent = safeString(node.label);
    const meta = document.createElement("span");
    meta.textContent = routingNodeMeta(node);
    item.append(dot, label, meta);
    column.appendChild(item);
  }

  const omitted = Number(graph.omitted_source_count || 0);
  if (omitted > 0 && columns.sources) {
    const more = document.createElement("div");
    more.className = "routing-node routing-node-muted";
    more.textContent = `+${omitted} more sources`;
    columns.sources.appendChild(more);
  }

  scheduleRoutingLinkDraw(graph.links || []);
}

function scheduleRoutingLinkDraw(links) {
  const schedule = window.requestAnimationFrame
    || (typeof setTimeout === "function"
      ? ((callback) => setTimeout(callback, 0))
      : ((callback) => callback()));
  schedule(() => drawRoutingGraphLinks(links));
}

function drawRoutingGraphLinks(links) {
  const svg = document.getElementById("routing-links");
  const map = document.getElementById("routing-map");
  if (!svg || !map || typeof document.createElementNS !== "function") return;
  if (typeof map.getBoundingClientRect !== "function") return;

  svg.innerHTML = "";
  const mapRect = map.getBoundingClientRect();
  if (!mapRect.width || !mapRect.height) return;
  svg.setAttribute("viewBox", `0 0 ${mapRect.width} ${mapRect.height}`);

  const nodeMap = {};
  document.querySelectorAll(".routing-node").forEach(node => {
    if (node.dataset.routingNodeId) nodeMap[node.dataset.routingNodeId] = node;
  });

  for (const link of links) {
    const src = nodeMap[link.from];
    const dst = nodeMap[link.to];
    if (!src || !dst || typeof src.getBoundingClientRect !== "function") continue;
    const srcRect = src.getBoundingClientRect();
    const dstRect = dst.getBoundingClientRect();
    const x1 = srcRect.right - mapRect.left;
    const y1 = srcRect.top + srcRect.height / 2 - mapRect.top;
    const x2 = dstRect.left - mapRect.left;
    const y2 = dstRect.top + dstRect.height / 2 - mapRect.top;
    const distance = Math.max(54, Math.abs(x2 - x1) * 0.48);
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute(
      "d",
      `M ${x1} ${y1} C ${x1 + distance} ${y1}, ${x2 - distance} ${y2}, ${x2} ${y2}`
    );
    path.setAttribute("class", `routing-link routing-link-${link.kind || "audio"}`);
    svg.appendChild(path);
  }
}

function renderRoutingFindings(report) {
  const list = document.getElementById("routing-finding-list");
  if (!list) return;
  list.innerHTML = "";
  const findings = Array.isArray(report?.findings) ? report.findings : [];
  if (!findings.length) {
    list.appendChild(routingPlaceholder("Run an audit to populate findings."));
    return;
  }

  for (const finding of findings) {
    const row = document.createElement("div");
    row.className = `routing-finding ${routingSeverityClass(finding.severity)}`;

    const icon = document.createElement("span");
    icon.className = "routing-finding-icon";
    icon.textContent = routingSeverityIcon(finding.severity);

    const body = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = safeString(finding.title);
    const detail = document.createElement("span");
    detail.textContent = safeString(finding.detail || finding.evidence?.[0]?.detail);
    body.append(title, detail);

    const count = document.createElement("span");
    count.className = "routing-finding-count";
    count.textContent = safeString(finding.count ?? 0);

    row.append(icon, body, count);
    list.appendChild(row);
  }
}

function renderRoutingRisks(report) {
  const list = document.getElementById("routing-risk-list");
  if (!list) return;
  list.innerHTML = "";

  const summary = report?.summary || {};
  const graph = report?.graph || {};
  const rows = [
    {
      label: "Direct-to-Master channel paths",
      value: summary.direct_to_master ?? 0,
      state: Number(summary.direct_to_master || 0) ? "warning" : "ok"
    },
    {
      label: "Unrouted channels",
      value: summary.unrouted_channels ?? 0,
      state: Number(summary.unrouted_channels || 0) ? "critical" : "ok"
    },
    {
      label: "Mixer paths without output",
      value: summary.dead_end_tracks ?? 0,
      state: Number(summary.dead_end_tracks || 0) ? "critical" : "ok"
    },
    {
      label: "Unused mixer inserts",
      value: summary.unused_mixer_tracks ?? 0,
      state: Number(summary.unused_mixer_tracks || 0) ? "warning" : "ok"
    }
  ];
  if (Number(graph.omitted_source_count || 0) > 0) {
    rows.push({
      label: "Sources hidden from graph",
      value: graph.omitted_source_count,
      state: "info"
    });
  }

  if (!report) {
    list.appendChild(routingPlaceholder("No audit result yet."));
    return;
  }

  for (const row of rows) {
    const item = document.createElement("div");
    item.className = `routing-risk-row ${routingSeverityClass(row.state)}`;
    const label = document.createElement("span");
    label.textContent = row.label;
    const value = document.createElement("strong");
    value.textContent = safeString(row.value);
    item.append(label, value);
    list.appendChild(item);
  }
}

function renderRoutingTables(report) {
  const channelBody = document.getElementById("routing-channel-table");
  const routeBody = document.getElementById("routing-route-table");
  const trackBody = document.getElementById("routing-track-table");
  if (channelBody) {
    channelBody.innerHTML = "";
    const channels = Array.isArray(report?.details?.channels) ? report.details.channels : [];
    if (!channels.length) {
      appendRoutingTableEmpty(channelBody, 4, "No channel routing rows.");
    } else {
      for (const channel of channels) {
        const row = document.createElement("tr");
        appendCell(row, safeString(channel.name));
        appendCell(row, safeString(channel.type));
        appendCell(row, routingTargetLabel(channel));
        appendCell(row, routingRouteStateLabel(channel.route_state), `route-state-${channel.route_state || "unknown"}`);
        channelBody.appendChild(row);
      }
    }
  }

  if (trackBody) {
    trackBody.innerHTML = "";
    const tracks = Array.isArray(report?.details?.tracks) ? report.details.tracks : [];
    if (!tracks.length) {
      appendRoutingTableEmpty(trackBody, 5, "No mixer track rows.");
    } else {
      for (const track of tracks) {
        const row = document.createElement("tr");
        appendCell(row, `${safeString(track.name)} (${safeString(track.track)})`);
        appendCell(row, routingTrackRoleLabel(track.role));
        appendCell(row, safeString(track.incoming_count ?? 0));
        appendCell(row, safeString(track.targeted_channel_count ?? 0));
        appendCell(row, routingTrackOutputs(track.routes_to));
        trackBody.appendChild(row);
      }
    }
  }

  if (routeBody) {
    routeBody.innerHTML = "";
    const routes = Array.isArray(report?.details?.routes) ? report.details.routes : [];
    if (!routes.length) {
      appendRoutingTableEmpty(routeBody, 3, "No mixer route rows.");
    } else {
      for (const route of routes) {
        const row = document.createElement("tr");
        appendCell(row, `${safeString(route.src_name)} (${safeString(route.src)})`);
        appendCell(row, `${safeString(route.dst_name)} (${safeString(route.dst)})`);
        appendCell(row, formatRouteLevel(route.level));
        routeBody.appendChild(row);
      }
    }
  }
}

function appendCell(row, value, className) {
  const cell = document.createElement("td");
  cell.textContent = value;
  if (className) cell.className = className;
  row.appendChild(cell);
}

function appendRoutingTableEmpty(body, colspan, message) {
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.colSpan = colspan;
  cell.className = "routing-table-empty";
  cell.textContent = message;
  row.appendChild(cell);
  body.appendChild(row);
}

function routingPlaceholder(message) {
  const node = document.createElement("div");
  node.className = "routing-placeholder";
  node.textContent = message;
  return node;
}

function routingScoreState(score) {
  if (score == null) return "idle";
  if (score >= 90) return "ok";
  if (score >= 75) return "warning";
  return "critical";
}

function routingSeverityClass(severity) {
  const value = String(severity || "").toLowerCase();
  if (value === "critical" || value === "high" || value === "error") return "is-critical";
  if (value === "warning" || value === "medium") return "is-warning";
  if (value === "ok") return "is-ok";
  return "is-info";
}

function routingSeverityIcon(severity) {
  const value = String(severity || "").toLowerCase();
  if (value === "critical" || value === "high" || value === "error") return "!";
  if (value === "warning" || value === "medium") return "△";
  if (value === "ok") return "✓";
  return "i";
}

function routingNodeClass(kind) {
  const value = String(kind || "").toLowerCase().replaceAll("_", "-");
  if (value === "master") return "routing-node-master";
  if (value === "bus") return "routing-node-bus";
  if (value === "unrouted" || value === "dead-end") return "routing-node-alert";
  return "routing-node-source";
}

function routingNodeMeta(node) {
  if (node.kind === "master") return "Output";
  if (node.kind === "bus") return node.track == null ? "Bus" : `Track ${node.track}`;
  if (node.kind === "unrouted") return "No mixer target";
  if (node.kind === "dead_end") return "No output route";
  if (node.target_track == null) return safeString(node.kind);
  return `Track ${node.target_track}`;
}

function routingTargetLabel(channel) {
  const target = channel.target_mixer_track;
  if (target == null || target === 0) return "None";
  const name = safeString(channel.target_name);
  return name === "Unavailable" ? `Track ${target}` : `${name} (${target})`;
}

function routingRouteStateLabel(stateValue) {
  const labels = {
    bus_routed: "Bus routed",
    direct_to_master: "Direct to Master",
    no_output: "No output",
    unrouted: "Unrouted"
  };
  return labels[stateValue] || "Unknown";
}

function routingTrackRoleLabel(role) {
  const labels = {
    master: "Master",
    bus: "Bus",
    stem_bus: "Stem Bus",
    premaster: "Premaster",
    sidechain_control: "Sidechain",
    template_reserved_placeholder: "Reserved",
    insert: "Insert",
    source: "Source",
    utility: "Utility",
    unknown: "Unknown"
  };
  return labels[role] || safeString(role);
}

function routingTrackOutputs(routes) {
  if (!Array.isArray(routes) || !routes.length) return "None";
  return routes
    .map(route => {
      const dst = route.dst == null ? "?" : route.dst;
      const label = route.dst_name || (dst === 0 ? "Master" : `Track ${dst}`);
      return `${safeString(label)} (${safeString(dst)})`;
    })
    .join(", ");
}

function formatRouteLevel(value) {
  if (value == null || value === "") return "Full";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return safeString(value);
  return numeric.toFixed(3);
}

// ─── Project Organizer ──────────────────────────────────────────────────────
async function runProjectOrganizer() {
  state.projectOrganizer.loading = true;
  state.projectOrganizer.error = null;
  renderProjectOrganizer();
  try {
    const result = await api("/api/workflows/project-organizer", {
      method: "POST",
      body: JSON.stringify(workflowRunBody("project_organizer"))
    });
    state.projectOrganizer.report = result;
    syncWorkflowUserDecisions("project_organizer", result);
    state.projectOrganizer.error = result?.ok === false
      ? (result.error || "Project Organizer unavailable.")
      : null;
  } catch (error) {
    state.projectOrganizer.error = `Project Organizer failed: ${error.message}`;
  } finally {
    state.projectOrganizer.loading = false;
    renderProjectOrganizer();
  }
}

function renderProjectOrganizer() {
  const layout = document.getElementById("organizer-layout");
  if (!layout) return;

  const report = state.projectOrganizer.report;
  const isLoading = state.projectOrganizer.loading;
  const error = state.projectOrganizer.error;

  setRunButton("run-project-organizer", isLoading, "Run Organizer");

  renderOrganizerFeedback(report, error, isLoading);
  renderWorkflowInteractionMount("organizer-interactions", "project_organizer", report);
  renderOrganizerSummary(report, isLoading);
  renderOrganizerMap(report);
  renderOrganizerGuided(report);
  renderOrganizerFindings(report);
  renderOrganizerPlan(report);
  renderOrganizerStandards(report);
  renderOrganizerGrouping(report);
  renderOrganizerDetails(report);
  renderOrganizerNotes(report);
}

function renderOrganizerFeedback(report, error, isLoading) {
  setWorkflowFeedback({
    id: "organizer-feedback",
    baseClass: "organizer-feedback",
    loading: isLoading,
    error,
    report,
    loadingText: "Project Organizer is reading channels, mixer tracks, patterns, and playlist tracks...",
    idleText: "Organizer has not run yet.",
    completeLabel: "Last scan"
  });
}

function renderOrganizerSummary(report, isLoading) {
  const summary = report?.summary || {};
  const score = Number.isFinite(Number(summary.organization_score))
    ? Number(summary.organization_score)
    : null;
  const label = summary.health_label || (report?.ok ? "Live" : "Idle");

  text("organizer-score-value", score == null ? "--" : `${Math.round(score)}%`);
  text("organizer-score-caption", isLoading ? "Reading" : label);
  text("organizer-score-label", label);
  text("organizer-channel-total", summary.channels ?? "--");
  text("organizer-pattern-total", summary.patterns ?? "--");
  text("organizer-finding-total", summary.diagnostics ?? "--");
  text("organizer-proposal-total", summary.proposed_changes ?? "--");
  text("organizer-name-total", summary.naming_cleanup ?? "--");
  text("organizer-routing-total", summary.routing_cleanup ?? "--");
  text("organizer-color-total", summary.color_readback_missing ?? "--");
  text("organizer-group-total", summary.grouping_candidates ?? "--");
  text("organizer-findings-count", summary.diagnostics ?? 0);
  text("organizer-plan-count", summary.proposed_changes ?? 0);

  const ring = document.getElementById("organizer-score-ring");
  if (ring) {
    const clampedScore = score == null ? 0 : Math.max(0, Math.min(100, score));
    ring.style.setProperty("--score", clampedScore);
    ring.dataset.state = routingScoreState(score);
  }

  const scoreLabel = document.getElementById("organizer-score-label");
  if (scoreLabel) {
    scoreLabel.className = `badge ${mixBadgeClass(score, report?.ok)}`;
  }

  const mapState = document.getElementById("organizer-map-state");
  if (mapState) {
    mapState.textContent = isLoading ? "Reading" : (report?.ok ? "Live" : "Idle");
    mapState.className = `badge ${report?.ok ? "badge-ok" : "badge-neutral"}`;
  }

  renderExplicitLabels(".organizer-score-stats", report);
}

function renderOrganizerMap(report) {
  const grid = document.getElementById("organizer-map-grid");
  if (!grid) return;
  grid.innerHTML = "";

  const summary = report?.summary || {};
  const cards = [
    {
      title: "Analyze Organization",
      tool: "fl_analyze_project_organization",
      value: summary.diagnostics ?? "--",
      detail: "Finds naming, routing, color-readback, pattern, and playlist cleanup signals.",
      state: Number(summary.diagnostics || 0) ? "warning" : "ok"
    },
    {
      title: "Plan Cleanup",
      tool: "fl_plan_project_cleanup",
      value: summary.proposed_changes ?? "--",
      detail: "Builds proposal-mode actions before any write is considered.",
      state: Number(summary.proposed_changes || 0) ? "info" : "ok"
    },
    {
      title: "Apply One Step",
      tool: "fl_apply_project_cleanup_step",
      value: summary.routing_cleanup ?? "--",
      detail: "Routes, renames, or colors one approved cleanup unit with rollback.",
      state: Number(summary.routing_cleanup || 0) ? "warning" : "ok"
    },
    {
      title: "Guided Cleanup",
      tool: "fl_start_guided_cleanup",
      value: safeString(report?.guided?.state || "idle"),
      detail: "Presents the next issue, one proposed fix, approval, readback, and rollback note.",
      state: report?.guided?.state === "ready" ? "info" : "ok"
    },
    {
      title: "Naming Standard",
      tool: "fl_apply_naming_standard",
      value: summary.naming_cleanup ?? "--",
      detail: "Collects consistent channel and mixer naming rules for approval.",
      state: Number(summary.naming_cleanup || 0) ? "info" : "ok"
    },
    {
      title: "Color Standard",
      tool: "fl_apply_color_standard",
      value: summary.color_readback_missing ?? "--",
      detail: "Shows color coverage limits and prepares approved color rules.",
      state: Number(summary.color_readback_missing || 0) ? "info" : "ok"
    },
    {
      title: "Group Tracks",
      tool: "fl_group_tracks",
      value: summary.grouping_candidates ?? "--",
      detail: "Suggests bus grouping candidates without selecting a bus automatically.",
      state: Number(summary.grouping_candidates || 0) ? "info" : "ok"
    }
  ];

  for (const card of cards) {
    const node = document.createElement("div");
    node.className = `organizer-map-card ${routingSeverityClass(card.state)}`;

    const top = document.createElement("div");
    top.className = "organizer-map-card-top";
    const title = document.createElement("strong");
    title.textContent = card.title;
    const value = document.createElement("span");
    value.textContent = safeString(card.value);
    top.append(title, value);

    const detail = document.createElement("p");
    detail.textContent = card.detail;
    const tool = document.createElement("code");
    tool.textContent = card.tool;

    node.append(top, detail, tool);
    grid.appendChild(node);
  }
}

function renderOrganizerGuided(report) {
  const guided = report?.guided || {};
  const stateValue = guided.state || "idle";
  text("organizer-next-priority", guided.priority || "--");
  text("organizer-next-issue", guided.next_issue || "Run Organizer to get the next step.");
  text("organizer-next-tool", guided.next_tool || "No write tool selected.");

  const stateBadge = document.getElementById("organizer-guided-state");
  if (stateBadge) {
    stateBadge.textContent = stateValue === "ready" ? "Ready" : stateValue === "clear" ? "Clear" : "Idle";
    stateBadge.className = `badge ${stateValue === "ready" ? "badge-warn" : stateValue === "clear" ? "badge-ok" : "badge-neutral"}`;
  }

  const steps = document.getElementById("organizer-guided-steps");
  if (!steps) return;
  steps.innerHTML = "";
  const rows = Array.isArray(guided.steps) ? guided.steps : [];
  if (!rows.length) {
    steps.appendChild(organizerPlaceholder("Run Organizer to start guided cleanup context."));
    return;
  }
  for (const row of rows) {
    const item = document.createElement("div");
    item.className = `organizer-guided-step is-${safeClassName(row.state || "pending")}`;
    const dot = document.createElement("span");
    dot.className = "organizer-guided-dot";
    const body = document.createElement("div");
    const label = document.createElement("strong");
    label.textContent = safeString(row.label);
    const tool = document.createElement("em");
    tool.textContent = safeString(row.tool);
    body.append(label, tool);
    item.append(dot, body);
    steps.appendChild(item);
  }
}

function renderOrganizerFindings(report) {
  const list = document.getElementById("organizer-finding-list");
  if (!list) return;
  list.innerHTML = "";
  const findings = Array.isArray(report?.findings) ? report.findings : [];
  if (!findings.length) {
    list.appendChild(organizerPlaceholder("Run Organizer to populate findings."));
    return;
  }

  for (const finding of findings) {
    const row = document.createElement("div");
    row.className = `organizer-finding ${routingSeverityClass(finding.severity)}`;

    const icon = document.createElement("span");
    icon.className = "organizer-finding-icon";
    icon.textContent = routingSeverityIcon(finding.severity);

    const body = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = safeString(finding.title);
    const detail = document.createElement("span");
    detail.textContent = safeString(finding.detail);
    body.append(title, detail);

    const count = document.createElement("span");
    count.className = "organizer-finding-count";
    count.textContent = safeString(finding.count ?? 0);

    row.append(icon, body, count);
    list.appendChild(row);
  }
}

function renderOrganizerPlan(report) {
  const list = document.getElementById("organizer-plan-list");
  if (!list) return;
  list.innerHTML = "";

  const steps = Array.isArray(report?.cleanup_plan?.steps) ? report.cleanup_plan.steps : [];
  if (!steps.length) {
    list.appendChild(organizerPlaceholder("No cleanup proposals yet."));
    return;
  }

  for (const step of steps) {
    const row = document.createElement("div");
    row.className = `organizer-plan-step priority-${safeClassName(step.priority || "low")}`;

    const header = document.createElement("div");
    header.className = "organizer-plan-header";
    const title = document.createElement("strong");
    title.textContent = safeString(step.title);
    const risk = document.createElement("span");
    risk.textContent = `Risk: ${safeString(step.risk)}`;
    header.append(title, risk);

    const detail = document.createElement("p");
    detail.textContent = safeString(step.detail);

    const footer = document.createElement("div");
    footer.className = "organizer-plan-footer";
    const tool = document.createElement("code");
    tool.textContent = safeString(step.tool);
    const approval = document.createElement("em");
    approval.textContent = step.requires_explicit_approval ? "Approval required" : "Read-only";
    footer.append(tool, approval);

    row.append(header, detail, footer);
    list.appendChild(row);
  }
}

function renderOrganizerStandards(report) {
  const grid = document.getElementById("organizer-standard-grid");
  if (!grid) return;
  grid.innerHTML = "";

  const standards = report?.standards || {};
  const entries = [
    {
      title: "Naming Standard",
      tool: standards.naming?.tool || "fl_apply_naming_standard",
      style: standards.naming?.style || "dynamic",
      count: standards.naming?.suggested_rule_count ?? 0,
      detail: "Applies consistent names across approved channel and mixer rules."
    },
    {
      title: "Color Standard",
      tool: standards.color?.tool || "fl_apply_color_standard",
      style: standards.color?.style || "dynamic",
      count: standards.color?.suggested_rule_count ?? 0,
      detail: "Applies a color palette only after exact rules are reviewed."
    }
  ];
  text("organizer-standard-count", entries.reduce((sum, entry) => sum + Number(entry.count || 0), 0));

  for (const entry of entries) {
    const card = document.createElement("div");
    card.className = "organizer-standard-card";
    const top = document.createElement("div");
    top.className = "organizer-standard-top";
    const title = document.createElement("strong");
    title.textContent = entry.title;
    const count = document.createElement("span");
    count.textContent = safeString(entry.count);
    top.append(title, count);

    const detail = document.createElement("p");
    detail.textContent = entry.detail;

    const meta = document.createElement("div");
    meta.className = "organizer-standard-meta";
    const tool = document.createElement("code");
    tool.textContent = entry.tool;
    const style = document.createElement("em");
    style.textContent = `Style: ${entry.style}`;
    meta.append(tool, style);

    card.append(top, detail, meta);
    grid.appendChild(card);
  }
}

function renderOrganizerGrouping(report) {
  const list = document.getElementById("organizer-group-list");
  if (!list) return;
  list.innerHTML = "";
  const groups = Array.isArray(report?.grouping?.candidate_groups)
    ? report.grouping.candidate_groups
    : [];
  text("organizer-grouping-count", groups.length);
  if (!groups.length) {
    list.appendChild(organizerPlaceholder("No grouping candidates yet."));
    return;
  }

  for (const group of groups) {
    const row = document.createElement("div");
    row.className = "organizer-group-row";
    const title = document.createElement("strong");
    title.textContent = safeString(group.name);
    const sources = document.createElement("span");
    const sourceNames = Array.isArray(group.source_names) ? group.source_names : [];
    sources.textContent = sourceNames.slice(0, 5).map(safeString).join(", ") || "No sources";
    const meta = document.createElement("em");
    meta.textContent = `${safeString(group.tool || "fl_group_tracks")} · bus required`;
    row.append(title, sources, meta);
    list.appendChild(row);
  }
}

function renderOrganizerDetails(report) {
  const body = document.getElementById("organizer-detail-table");
  if (!body) return;
  body.innerHTML = "";
  const rows = Array.isArray(report?.details?.items) ? report.details.items : [];
  text("organizer-detail-count", rows.length);
  if (!rows.length) {
    appendRoutingTableEmpty(body, 5, "No project detail rows.");
    return;
  }
  for (const item of rows) {
    const row = document.createElement("tr");
    appendCell(row, safeString(item.area));
    appendCell(row, safeString(item.index));
    appendCell(row, safeString(item.name));
    appendCell(row, safeString(item.status), `organizer-status-${safeClassName(item.status)}`);
    appendCell(row, safeString(item.detail));
    body.appendChild(row);
  }
}

function renderOrganizerNotes(report) {
  const list = document.getElementById("organizer-note-list");
  if (!list) return;
  list.innerHTML = "";
  const notes = Array.isArray(report?.details?.notes) ? report.details.notes : [];
  text("organizer-note-count", notes.length);
  if (!notes.length) {
    list.appendChild(organizerPlaceholder("No safety notes yet."));
    return;
  }
  for (const note of notes) {
    const row = document.createElement("div");
    row.className = "organizer-note-row";
    row.textContent = safeString(note);
    list.appendChild(row);
  }
}

function organizerPlaceholder(message) {
  const node = document.createElement("div");
  node.className = "organizer-placeholder";
  node.textContent = message;
  return node;
}

function safeClassName(value) {
  return String(value || "unknown").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "unknown";
}

// ─── Project Health ─────────────────────────────────────────────────────────
async function runProjectHealth() {
  state.projectHealth.loading = true;
  state.projectHealth.error = null;
  state.projectHealth.lastRun = null;
  renderProjectHealth();

  try {
    const payload = await api("/api/workflows/project-health", { method: "POST", body: "{}" });
    if (!payload || !Array.isArray(payload.sections)) {
      throw new Error("Invalid backend Project Health payload shape");
    }
    state.projectHealth.backendData = payload;
  } catch (error) {
    state.projectHealth.backendData = null;
    state.projectHealth.error = error.message || "Runtime Project Health is unavailable.";
    console.warn("Runtime Project Health request failed:", error);
  }

  state.projectHealth.loading = false;
  state.projectHealth.lastRun = new Date().toISOString();
  renderProjectHealth();
}

function renderProjectHealth() {
  const layout = document.getElementById("health-layout");
  if (!layout) return;

  const aggregate = buildHealthOverview();
  const isLoading = state.projectHealth.loading
    || aggregate.sections.some(section => section.loading);

  setRunButton("run-project-health", isLoading, "Run Health Scan");

  renderHealthFeedback(aggregate, isLoading);
  renderHealthSummary(aggregate, isLoading);
  renderHealthSections(aggregate.sections);
  renderHealthWarnings(aggregate);
  renderHealthNavigation(aggregate.sections);
  renderHealthNotes(aggregate);
}

function buildHealthOverview() {
  const backend = state.projectHealth.backendData;
  if (backend) {
    const sections = backend.sections.map(sec => {
      const panelId = workflowById(sec.workflow)?.panel_id || "producer_health";
      const findings = healthNormalizeFindings(
        sec.title || sec.workflow,
        panelId,
        Array.isArray(sec.findings) ? sec.findings : []
      );
      return {
        id: sec.workflow,
        title: sec.title,
        target: panelId,
        score: sec.health_score,
        risk: sec.risk_score,
        coverage: sec.coverage,
        confidence: sec.confidence_score,
        hasReport: sec.report_id != null,
        error: sec.freshness === "missing" || sec.freshness === "unavailable" ? sec.reason : null,
        findingsCount: findings.length,
        findings,
        metrics: [
          { label: "Coverage", value: sec.coverage?.score != null ? `${sec.coverage.score}%` : "--" },
          { label: "Confidence", value: sec.confidence_score != null ? `${sec.confidence_score}%` : "--" }
        ]
      };
    });
    const warnings = healthDedupeFindings(sections.flatMap(section => section.findings))
      .sort(healthWarningSort);
    
    return {
      sections,
      score: backend.overall_health_score,
      risk: backend.overall_risk_score,
      coverage_pct: backend.overall_coverage_pct,
      confidence: backend.overall_confidence_score,
      warnings,
      availableSections: backend.sections.filter(s => s.report_id != null).length,
      readySections: backend.sections.filter(s => s.freshness === "fresh" || s.freshness === "partial").length,
      findingTotal: sections.reduce((sum, section) => sum + section.findingsCount, 0),
      blockerTotal: warnings.filter(row => healthSeverityRank(row.severity) >= 3).length,
      warningTotal: warnings.filter(row => healthSeverityRank(row.severity) >= 2).length,
      totalSections: backend.sections.length
    };
  }

  // Render-only compatibility for reports already present in older clients.
  const sections = [
    buildLegacyRuntimeSection("project_organizer", "Organizer", "producer_organizer", state.projectOrganizer),
    buildLegacyRuntimeSection("mix_review", "Mix Review", "producer_mix_review", state.mixReview),
    buildLegacyRuntimeSection("routing_audit", "Routing", "producer_routing", state.routingAudit),
    buildLegacyRuntimeSection("low_end_analysis", "Low-End", "producer_low_end", state.lowEndAnalysis)
  ];
  const warnings = healthDedupeFindings(sections.flatMap(section => section.findings))
    .sort(healthWarningSort);
  const availableSections = sections.filter(section => section.hasReport).length;
  const readySections = sections.filter(section => section.hasReport && !section.error).length;
  const findingTotal = sections.reduce((sum, section) => sum + section.findingsCount, 0);
  const blockerTotal = warnings.filter(row => healthSeverityRank(row.severity) >= 3).length;
  const warningTotal = warnings.filter(row => healthSeverityRank(row.severity) >= 2).length;

  return {
    sections,
    score: null,
    risk: null,
    warnings,
    availableSections,
    readySections,
    findingTotal,
    blockerTotal,
    warningTotal,
    totalSections: sections.length
  };
}

function buildLegacyRuntimeSection(id, title, target, stateData) {
  const report = stateData.report;
  const analysis = report?.analysis || report?.details?.analysis_report || {};
  const findings = healthNormalizeFindings(
    title,
    target,
    Array.isArray(report?.findings) ? report.findings : []
  );
  return {
    id,
    title,
    target,
    score: Number.isFinite(Number(analysis.health_score)) ? Number(analysis.health_score) : null,
    risk: Number.isFinite(Number(analysis.risk_score)) ? Number(analysis.risk_score) : null,
    coverage: analysis.coverage || null,
    confidence: analysis.confidence_score ?? null,
    hasReport: Boolean(report),
    error: stateData.error || null,
    loading: Boolean(stateData.loading),
    findings,
    findingsCount: findings.length,
    metrics: []
  };
}

function buildOrganizerHealthSection() {
  const report = state.projectOrganizer.report;
  const summary = report?.summary || {};
  const findings = healthNormalizeFindings(
    "Organizer",
    "producer_organizer",
    Array.isArray(report?.findings) ? report.findings : []
  );
  const proposed = Number(summary.proposed_changes || 0);
  if (proposed > 0) {
    findings.push({
      source: "Organizer",
      target: "producer_organizer",
      severity: "info",
      title: "Cleanup Plan Ready",
      detail: `${proposed} proposed cleanup step${proposed === 1 ? "" : "s"} available.`,
      count: proposed
    });
  }

  return makeHealthSection({
    id: "organizer",
    title: "Organizer",
    target: "producer_organizer",
    stateData: state.projectOrganizer,
    score: healthNumericScore(summary.organization_score, report),
    scoreLabel: summary.health_label,
    findings,
    metrics: [
      { label: "Proposals", value: summary.proposed_changes ?? "--" },
      { label: "Routing", value: summary.routing_cleanup ?? "--" }
    ]
  });
}

function buildMixHealthSection() {
  const report = state.mixReview.report;
  const summary = report?.summary || {};
  const findings = healthNormalizeFindings(
    "Mix Review",
    "producer_mix_review",
    Array.isArray(report?.findings) ? report.findings : []
  );
  const hotTracks = Number(summary.hot_tracks || 0);
  if (hotTracks > 0) {
    findings.push({
      source: "Mix Review",
      target: "producer_mix_review",
      severity: "warning",
      title: "Hot Tracks",
      detail: `${hotTracks} track${hotTracks === 1 ? "" : "s"} need level review.`,
      count: hotTracks
    });
  }
  const masterPeak = Number(summary.master_peak_db);
  if (Number.isFinite(masterPeak) && masterPeak >= 0) {
    findings.push({
      source: "Mix Review",
      target: "producer_mix_review",
      severity: "critical",
      title: "Master Peak Over 0 dB",
      detail: `Master peak reads ${formatDb(masterPeak)}.`,
      count: 1
    });
  }
  const headroom = Number(summary.master_headroom_db);
  if (Number.isFinite(headroom) && headroom < 3) {
    findings.push({
      source: "Mix Review",
      target: "producer_mix_review",
      severity: "warning",
      title: "Low Master Headroom",
      detail: `Master headroom is ${formatDb(headroom)}.`,
      count: 1
    });
  }

  return makeHealthSection({
    id: "mix",
    title: "Mix Review",
    target: "producer_mix_review",
    stateData: state.mixReview,
    score: healthNumericScore(summary.health_score, report),
    scoreLabel: summary.health_label,
    findings,
    metrics: [
      { label: "Hot Tracks", value: summary.hot_tracks ?? "--" },
      { label: "Headroom", value: formatDb(summary.master_headroom_db) }
    ]
  });
}

function buildRoutingHealthSection() {
  const report = state.routingAudit.report;
  const summary = report?.summary || {};
  const findings = healthNormalizeFindings(
    "Routing",
    "producer_routing",
    Array.isArray(report?.findings) ? report.findings : []
  );
  const unrouted = Number(summary.unrouted_channels || 0);
  if (unrouted > 0) {
    findings.push({
      source: "Routing",
      target: "producer_routing",
      severity: "critical",
      title: "Unrouted Channels",
      detail: `${unrouted} channel${unrouted === 1 ? "" : "s"} without a mixer target.`,
      count: unrouted
    });
  }
  const deadEnds = Number(summary.dead_end_tracks || 0);
  if (deadEnds > 0) {
    findings.push({
      source: "Routing",
      target: "producer_routing",
      severity: "critical",
      title: "Mixer Paths Without Output",
      detail: `${deadEnds} mixer path${deadEnds === 1 ? "" : "s"} do not reach an output.`,
      count: deadEnds
    });
  }
  const direct = Number(summary.direct_to_master || 0);
  if (direct > 0) {
    findings.push({
      source: "Routing",
      target: "producer_routing",
      severity: "warning",
      title: "Direct Master Paths",
      detail: `${direct} source${direct === 1 ? "" : "s"} route directly to Master.`,
      count: direct
    });
  }

  return makeHealthSection({
    id: "routing",
    title: "Routing",
    target: "producer_routing",
    stateData: state.routingAudit,
    score: healthNumericScore(summary.health_score, report),
    scoreLabel: summary.health_label,
    findings,
    metrics: [
      { label: "Unrouted", value: summary.unrouted_channels ?? "--" },
      { label: "Direct Master", value: summary.direct_to_master ?? "--" }
    ]
  });
}

function buildLowEndHealthSection() {
  const report = state.lowEndAnalysis.report;
  const tracks = lowEndTracks(report);
  const lowFindings = lowEndFindings(report);
  const findings = healthNormalizeFindings("Low-End", "producer_low_end", lowFindings);
  const stereoRisks = tracks.filter(lowEndTrackStereoRisk).length;
  if (stereoRisks > 0) {
    findings.push({
      source: "Low-End",
      target: "producer_low_end",
      severity: "warning",
      title: "Wide Low-End Elements",
      detail: `${stereoRisks} low-end track${stereoRisks === 1 ? "" : "s"} show stereo or pan risk.`,
      count: stereoRisks
    });
  }
  const manualChecks = Array.isArray(report?.details?.low_end?.manual_checks)
    ? report.details.low_end.manual_checks
    : [];
  if (manualChecks.length > 0) {
    findings.push({
      source: "Low-End",
      target: "producer_low_end",
      severity: "info",
      title: "Manual Low-End Checks",
      detail: `${manualChecks.length} manual check${manualChecks.length === 1 ? "" : "s"} remain.`,
      count: manualChecks.length
    });
  }

  return makeHealthSection({
    id: "low-end",
    title: "Low-End",
    target: "producer_low_end",
    stateData: state.lowEndAnalysis,
    score: lowEndScore(report, tracks, lowFindings),
    scoreLabel: lowEndScoreLabel(lowEndScore(report, tracks, lowFindings), report?.ok),
    findings,
    metrics: [
      { label: "Tracks", value: report ? tracks.length : "--" },
      { label: "Stereo Risk", value: report ? stereoRisks : "--" }
    ]
  });
}

function makeHealthSection({ id, title, target, stateData, score, scoreLabel, findings, metrics }) {
  const report = stateData.report;
  const errorFinding = stateData.error ? [{
    source: title,
    target,
    severity: "critical",
    title: `${title} Unavailable`,
    detail: stateData.error,
    count: 1
  }] : [];
  const normalized = healthDedupeFindings([...errorFinding, ...(findings || [])])
    .sort(healthWarningSort);
  const effectiveScore = Number.isFinite(score)
    ? Math.max(0, Math.min(100, Math.round(score)))
    : (stateData.error ? 0 : null);
  const status = healthSectionStatus(effectiveScore, Boolean(report), stateData.loading, stateData.error);

  return {
    id,
    title,
    target,
    report,
    hasReport: Boolean(report),
    loading: stateData.loading,
    error: stateData.error,
    score: effectiveScore,
    risk: effectiveScore == null ? null : Math.max(0, Math.min(100, 100 - effectiveScore)),
    scoreLabel,
    status,
    findings: normalized,
    findingsCount: normalized.reduce((sum, row) => sum + healthFindingCountValue(row.count), 0),
    topFinding: normalized[0] || null,
    metrics: metrics || []
  };
}

function renderHealthFeedback(aggregate, isLoading) {
  const report = aggregate.availableSections > 0
    ? { ok: true, generated_at: state.projectHealth.lastRun || Date.now() }
    : null;
  const coverage = `${aggregate.availableSections}/${aggregate.totalSections}`;
  setWorkflowFeedback({
    id: "health-feedback",
    baseClass: "health-feedback",
    loading: isLoading,
    error: state.projectHealth.error,
    report,
    loadingText: "Health scan is reading Organizer, Mix Review, Routing, and Low-End reports...",
    idleText: "Health overview has not run yet.",
    completeLabel: `Last overview. Coverage ${coverage}`
  });
}

function renderHealthSummary(aggregate, isLoading) {
  const riskText = aggregate.risk == null ? "--" : `${Math.round(aggregate.risk)}%`;
  const scoreText = aggregate.score == null ? "--" : `${Math.round(aggregate.score)}%`;
  const label = isLoading ? "Reading" : healthRiskLabel(aggregate.risk, aggregate.availableSections);

  text("health-risk-value", riskText);
  text("health-risk-caption", label);
  text("health-score-value", scoreText);
  text("health-coverage-value", `${aggregate.availableSections}/${aggregate.totalSections}`);
  text("health-finding-total", aggregate.availableSections ? aggregate.findingTotal : "--");
  text("health-blocker-total", aggregate.availableSections ? aggregate.blockerTotal : "--");
  text("health-section-count", `${aggregate.availableSections}/${aggregate.totalSections}`);
  text("health-ready-total", `${aggregate.readySections} ready`);

  const ring = document.getElementById("health-risk-ring");
  if (ring) {
    ring.style.setProperty("--risk", aggregate.risk == null ? 0 : Math.max(0, Math.min(100, aggregate.risk)));
    ring.dataset.state = healthRiskState(aggregate.risk);
  }

  const statusLabel = document.getElementById("health-status-label");
  if (statusLabel) {
    statusLabel.textContent = label;
    statusLabel.className = `badge ${healthRiskBadgeClass(aggregate.risk, aggregate.availableSections)}`;
  }
}

function renderHealthSections(sections) {
  const grid = document.getElementById("health-section-grid");
  if (!grid) return;
  grid.innerHTML = "";

  for (const section of sections) {
    const card = document.createElement("div");
    card.className = `health-section-card ${healthSectionClass(section)}`;

    const top = document.createElement("div");
    top.className = "health-section-card-top";
    const title = document.createElement("strong");
    title.textContent = section.title;
    const status = document.createElement("span");
    status.className = `badge ${healthSectionBadgeClass(section)}`;
    status.textContent = section.status;
    top.append(title, status);

    const score = document.createElement("div");
    score.className = "health-section-score";
    const value = document.createElement("strong");
    value.textContent = section.risk == null ? "--" : `${Math.round(section.risk)}%`;
    const label = document.createElement("span");
    label.textContent = "Risk";
    score.append(value, label);

    const metrics = document.createElement("div");
    metrics.className = "health-section-metrics";
    for (const metric of section.metrics.slice(0, 2)) {
      const metricEl = document.createElement("div");
      const metricLabel = document.createElement("span");
      metricLabel.textContent = metric.label;
      const metricValue = document.createElement("strong");
      metricValue.textContent = safeString(metric.value);
      metricEl.append(metricLabel, metricValue);
      metrics.appendChild(metricEl);
    }

    const finding = document.createElement("p");
    finding.className = "health-section-finding";
    finding.textContent = section.topFinding
      ? `${section.topFinding.title}: ${section.topFinding.detail}`
      : (section.hasReport ? "No active warnings." : "No report available.");

    const action = document.createElement("button");
    action.type = "button";
    action.className = "ghost-button health-section-action";
    action.textContent = "Open details";
    action.addEventListener("click", () => selectPanel(section.target));

    card.append(top, score, metrics, finding, action);
    grid.appendChild(card);
  }
}

function renderHealthWarnings(aggregate) {
  const list = document.getElementById("health-warning-list");
  if (!list) return;
  list.innerHTML = "";
  text("health-warning-count", aggregate.warningTotal);

  const warnings = aggregate.warnings
    .filter(row => healthSeverityRank(row.severity) >= 1)
    .slice(0, 6);
  if (!warnings.length) {
    list.appendChild(healthPlaceholder(
      aggregate.availableSections ? "No warnings in available reports." : "No health reports available."
    ));
    return;
  }

  for (const warning of warnings) {
    const row = document.createElement("div");
    row.className = `health-warning-row ${mixSeverityClass(warning.severity)}`;

    const icon = document.createElement("span");
    icon.className = "health-warning-icon";
    icon.textContent = mixSeverityIcon(warning.severity);

    const body = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = warning.title;
    const detail = document.createElement("span");
    detail.textContent = `${warning.source} · ${warning.detail}`;
    body.append(title, detail);

    const meta = document.createElement("div");
    meta.className = "health-warning-meta";
    const count = document.createElement("span");
    count.textContent = safeString(warning.count ?? 1);
    const action = document.createElement("button");
    action.type = "button";
    action.className = "ghost-button";
    action.textContent = "Open";
    action.addEventListener("click", () => selectPanel(warning.target));
    meta.append(count, action);

    row.append(icon, body, meta);
    list.appendChild(row);
  }
}

function renderHealthNavigation(sections) {
  const list = document.getElementById("health-nav-list");
  if (!list) return;
  list.innerHTML = "";

  for (const section of sections) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = `health-nav-item ${healthSectionClass(section)}`;
    item.addEventListener("click", () => selectPanel(section.target));

    const label = document.createElement("strong");
    label.textContent = section.title;
    const detail = document.createElement("span");
    detail.textContent = section.score == null
      ? section.status
      : `${Math.round(section.score)}% score · ${section.status}`;

    item.append(label, detail);
    list.appendChild(item);
  }
}

function renderHealthNotes(aggregate) {
  const list = document.getElementById("health-note-list");
  if (!list) return;
  list.innerHTML = "";

  const notes = [];
  if (!aggregate.availableSections) {
    notes.push("No health reports are available yet.");
  } else if (aggregate.availableSections < aggregate.totalSections) {
    notes.push(`${aggregate.totalSections - aggregate.availableSections} section report${aggregate.totalSections - aggregate.availableSections === 1 ? "" : "s"} missing from this overview.`);
  }
  if (aggregate.blockerTotal > 0) {
    notes.push(`${aggregate.blockerTotal} blocker finding${aggregate.blockerTotal === 1 ? "" : "s"} need detailed review.`);
  } else if (aggregate.availableSections) {
    notes.push("Available reports show no blocker findings.");
  }
  if (aggregate.warningTotal > 0) {
    notes.push(`${aggregate.warningTotal} warning finding${aggregate.warningTotal === 1 ? "" : "s"} found across available reports.`);
  }
  notes.push("Health summarizes read-only scan results. Project-changing cleanup remains proposal-first.");

  text("health-note-count", notes.length);
  for (const note of notes) {
    const row = document.createElement("div");
    row.className = "health-note-row";
    row.textContent = note;
    list.appendChild(row);
  }
}

function healthNormalizeFindings(source, target, findings) {
  return findings.map(finding => ({
    source,
    target,
    severity: healthSeverity(finding.severity),
    title: safeString(finding.title || finding.id || source),
    detail: healthFindingDetail(finding),
    count: finding.count ?? 1
  }));
}

function healthFindingDetail(finding) {
  const parts = [];
  const track = finding.track_name ?? finding.track;
  if (track != null && track !== "") {
    parts.push(typeof track === "number" ? `Track ${track}` : safeString(track));
  }
  const detail = finding.detail || finding.evidence || finding.reason || finding.check;
  if (detail) parts.push(safeString(detail));
  return parts.join(" · ") || "Review the section details.";
}

function healthDedupeFindings(findings) {
  const seen = new Set();
  return findings.filter(finding => {
    const key = [
      finding.source,
      finding.title,
      finding.detail,
      healthSeverity(finding.severity)
    ].join("|");
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function healthWarningSort(a, b) {
  const severityDelta = healthSeverityRank(b.severity) - healthSeverityRank(a.severity);
  if (severityDelta !== 0) return severityDelta;
  return healthFindingCountValue(b.count) - healthFindingCountValue(a.count);
}

function healthFindingCountValue(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric > 0 ? numeric : 1;
}

function healthNumericScore(value, report) {
  if (report?.ok === false) return 0;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? Math.max(0, Math.min(100, numeric)) : null;
}

function healthSeverity(severity) {
  const value = String(severity || "").toLowerCase();
  if (["critical", "high", "blocker"].includes(value)) return "critical";
  if (["warning", "medium"].includes(value)) return "warning";
  if (value === "ok") return "ok";
  return "info";
}

function healthSeverityRank(severity) {
  const value = healthSeverity(severity);
  if (value === "critical") return 3;
  if (value === "warning") return 2;
  if (value === "info") return 1;
  return 0;
}

function healthSectionStatus(score, hasReport, loading, error) {
  if (loading) return "Reading";
  if (error) return "Unavailable";
  if (!hasReport) return "Not run";
  if (score == null) return "Limited";
  if (score >= 90) return "Clear";
  if (score >= 75) return "Needs review";
  return "At risk";
}

function healthRiskLabel(risk, availableSections) {
  if (!availableSections || risk == null) return "Idle";
  if (risk <= 10) return "Low risk";
  if (risk <= 25) return "Needs review";
  return "High risk";
}

function healthRiskState(risk) {
  if (risk == null) return "idle";
  if (risk <= 10) return "ok";
  if (risk <= 25) return "warning";
  return "critical";
}

function healthRiskBadgeClass(risk, availableSections) {
  if (!availableSections || risk == null) return "badge-neutral";
  if (risk <= 10) return "badge-ok";
  return "badge-warn";
}

function healthSectionClass(section) {
  if (section.loading) return "is-info";
  if (section.error || (section.score != null && section.score < 75)) return "is-critical";
  if (section.score != null && section.score < 90) return "is-warning";
  if (section.hasReport) return "is-ok";
  return "is-info";
}

function healthSectionBadgeClass(section) {
  if (section.hasReport && !section.error && section.score != null && section.score >= 90) return "badge-ok";
  if (!section.hasReport && !section.loading) return "badge-neutral";
  return "badge-warn";
}

function healthPlaceholder(message) {
  const node = document.createElement("div");
  node.className = "health-placeholder";
  node.textContent = message;
  return node;
}

// ─── Logs & History ───────────────────────────────────────────────────────────
function renderLogsHistory() {
  const container = document.getElementById("logs-history-content");
  if (!container) return;
  container.innerHTML = "";

  // Section 1: Runtime Logs
  const runtimeSection = document.createElement("div");
  runtimeSection.className = "log-section";
  const runtimeH3 = document.createElement("h3");
  runtimeH3.className = "log-section-title";
  runtimeH3.textContent = "Runtime Logs";
  runtimeSection.appendChild(runtimeH3);

  const daemonProc = state.status?.processes?.daemon || {};
  const sseProc = state.status?.processes?.sse || {};
  const daemonLogs = (daemonProc.logs || []);
  const sseLogs = (sseProc.logs || []);

  // Daemon logs
  const daemonLogCard = document.createElement("div");
  daemonLogCard.className = "log-subsection";
  const daemonLogTitle = document.createElement("h4");
  daemonLogTitle.className = "log-subsection-title";
  daemonLogTitle.textContent = "FL Studio Bridge Service";
  const daemonLogPre = document.createElement("pre");
  daemonLogPre.className = "log-output";
  daemonLogPre.textContent = daemonLogs.length ? daemonLogs.join("\n") : "No log entries yet.";
  daemonLogCard.append(daemonLogTitle, daemonLogPre);

  // SSE logs
  const sseLogCard = document.createElement("div");
  sseLogCard.className = "log-subsection";
  const sseLogTitle = document.createElement("h4");
  sseLogTitle.className = "log-subsection-title";
  sseLogTitle.textContent = "AI Client Server";
  const sseLogPre = document.createElement("pre");
  sseLogPre.className = "log-output";
  sseLogPre.textContent = sseLogs.length ? sseLogs.join("\n") : "No log entries yet.";
  sseLogCard.append(sseLogTitle, sseLogPre);

  runtimeSection.append(daemonLogCard, sseLogCard);

  // Section 2: Setup Check History
  const historySection = document.createElement("div");
  historySection.className = "log-section";
  const historyH3 = document.createElement("h3");
  historyH3.className = "log-section-title";
  historyH3.textContent = "Setup Check History";
  const historyPlaceholder = document.createElement("div");
  historyPlaceholder.className = "placeholder-card";
  historyPlaceholder.textContent = "Setup check history is not persisted yet. The latest setup state is shown in Setup Doctor.";
  historySection.append(historyH3, historyPlaceholder);

  // Section 3: Safety & Rollback Logs
  const rollbackSection = document.createElement("div");
  rollbackSection.className = "log-section";
  const rollbackH3 = document.createElement("h3");
  rollbackH3.className = "log-section-title";
  rollbackH3.textContent = "Safety & Rollback Logs";
  const rollbackPlaceholder = document.createElement("div");
  rollbackPlaceholder.className = "placeholder-card";
  rollbackPlaceholder.textContent = "No rollback events yet. Rollback logs will appear here when proposal/apply workflows are available.";
  rollbackSection.append(rollbackH3, rollbackPlaceholder);

  container.append(runtimeSection, historySection, rollbackSection);
}

// ─── Ports ────────────────────────────────────────────────────────────────────
function renderPorts() {
  const container = document.getElementById("ports-table-wrap");
  if (!container) return;
  container.innerHTML = "";

  const ports = state.status?.ports;
  if (!ports || typeof ports !== "object" || Object.keys(ports).length === 0) {
    const empty = document.createElement("div");
    empty.className = "placeholder-card";
    empty.textContent = "Ports are not available in the current status payload.";
    container.appendChild(empty);
    return;
  }

  const table = document.createElement("table");
  table.className = "port-table";

  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  for (const col of ["Service", "Host", "Preferred Port", "Selected Port", "Fallback", "Local Connection"]) {
    const th = document.createElement("th");
    th.textContent = col;
    headerRow.appendChild(th);
  }
  thead.appendChild(headerRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  const serviceNames = {
    control_center: "Control Center",
    daemon: "FL Studio Bridge Service",
    sse: "AI Client Server",
  };

  for (const [key, data] of Object.entries(ports)) {
    if (typeof data !== "object" || !data) continue;
    const tr = document.createElement("tr");

    const name = serviceNames[key] || safeString(key);
    const host = safeString(data.host);
    const preferred = safeString(data.preferred_port);
    const selected = safeString(data.selected_port);
    const fallback = data.fallback_port ? safeString(data.fallback_port) : "None";
    const localAddr = (host !== "Unavailable" && selected !== "Unavailable")
      ? `http://${host === "0.0.0.0" ? "127.0.0.1" : host}:${selected}/`
      : "Unavailable";

    for (const val of [name, host, preferred, selected, fallback, localAddr]) {
      const td = document.createElement("td");
      td.textContent = val;
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  container.appendChild(table);
}

// ─── Support Report ───────────────────────────────────────────────────────────
function renderSupportSummary() {
  const summaryEl = document.getElementById("support-summary-content");
  if (!summaryEl) return;

  const data = getStatusReport();
  const bridge = data?.bridge || {};
  const safety = data?.safety || {};
  const daemonProc = state.status?.processes?.daemon || {};
  const sseProc = state.status?.processes?.sse || {};

  const live = bridge.state === "live";
  const daemonRunning = isManagedProcessRunning(daemonProc) || daemonProc.state === "external";
  const sseRunning = isManagedProcessRunning(sseProc);
  const readOnly = safety.read_only !== false;

  const rows = [
    { label: "Overall Status", value: live ? "FL Studio connected" : "FL Studio not connected" },
    { label: "FL Studio Bridge", value: live ? "Connected" : "Not connected" },
    { label: "Background Service", value: daemonRunning ? "Running" : "Not running" },
    { label: "AI Client Server", value: sseRunning ? "Running" : "Not started" },
    { label: "Safety Mode", value: readOnly ? "Read-only (no project changes)" : "Write enabled" },
    { label: "Recommended Next Step", value: _recommendedNextStep() },
  ];

  summaryEl.innerHTML = "";
  const dl = document.createElement("dl");
  dl.className = "support-summary-list";
  for (const row of rows) {
    const dt = document.createElement("dt");
    dt.textContent = row.label;
    const dd = document.createElement("dd");
    dd.textContent = row.value;
    dl.append(dt, dd);
  }
  summaryEl.appendChild(dl);
}

// ─── Panel card factory ───────────────────────────────────────────────────────
function card(title, status, bodyText, buttonConfig) {
  const node = document.createElement("article");
  node.className = "panel";

  const heading = document.createElement("div");
  heading.className = "panel-heading";
  const h2 = document.createElement("h2");
  h2.textContent = safeString(title);

  const tag = document.createElement("span");
  tag.className = "evidence-state";
  tag.textContent = safeString(status);
  tag.style.marginLeft = "auto";
  tag.style.fontSize = "11px";

  const statLower = String(status || "").toLowerCase();
  // Only use red/blocker for genuine safety blockades — not normal first-run states
  if (statLower === "ok" || statLower.includes("running") || statLower === "external" || statLower.includes("confirmed")) {
    tag.style.color = "#70fba0";
    tag.style.background = "rgba(27, 228, 126, 0.14)";
    tag.style.borderColor = "rgba(54, 244, 152, 0.44)";
  } else if (statLower === "blocked" || statLower.includes("fail") || statLower === "port_conflict") {
    // "BLOCKED" only for genuine security/safety blockades
    tag.style.color = "#ffb0ba";
    tag.style.background = "rgba(255, 77, 104, 0.12)";
    tag.style.borderColor = "rgba(255, 96, 116, 0.38)";
  } else if (statLower === "not required" || statLower === "not running" || statLower === "stopped") {
    tag.style.color = "#9eacc7";
    tag.style.background = "rgba(158, 172, 199, 0.12)";
    tag.style.borderColor = "rgba(158, 172, 199, 0.44)";
  } else {
    // setup required, action needed, manual check, checking — all amber
    tag.style.color = "#ffb23e";
    tag.style.background = "rgba(255, 178, 62, 0.12)";
    tag.style.borderColor = "rgba(255, 178, 62, 0.5)";
  }

  heading.append(h2, tag);

  const p = document.createElement("p");
  p.className = "panel-note";
  p.style.marginTop = "16px";
  p.style.whiteSpace = "pre-wrap";
  p.style.lineHeight = "1.5";
  p.textContent = safeString(bodyText);

  node.append(heading, p);

  if (buttonConfig) {
    const btnRow = document.createElement("div");
    btnRow.style.cssText = "padding: 0 26px 20px; display: flex; gap: 8px; flex-wrap: wrap;";
    const configs = Array.isArray(buttonConfig) ? buttonConfig : [buttonConfig];
    for (const config of configs) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "ghost-button";
      btn.textContent = safeString(config.text);
      btn.disabled = Boolean(config.disabled);
      btn.onclick = config.onclick;
      if (config.disabled) { btn.style.opacity = "0.5"; btn.style.cursor = "not-allowed"; }
      btnRow.appendChild(btn);
    }
    node.appendChild(btnRow);
  }

  return node;
}

// ─── Setup step confirmation ──────────────────────────────────────────────────
async function confirmStep(step) {
  const before = setupGroupSnapshot(step.groups);
  state.setupFeedback[step.key] = { state: "checking", text: "Checking for the expected setup improvement..." };
  render();
  try {
    state.status = await api("/api/setup/confirm-step", {
      method: "POST",
      body: JSON.stringify({ step: step.key })
    });
    state.setupFeedback[step.key] = evaluateSetupFeedback(step, before);
  } catch (error) {
    state.setupFeedback[step.key] = { state: "attention", text: `Could not re-check this step: ${error.message}` };
  }
  render();
}

async function processAction(path) {
  const key = processActionKey(path);
  state.actionFeedback[key] = { state: "checking", text: `${processActionLabel(path)} in progress...` };
  render();
  try {
    const result = await api(path, { method: "POST", body: "{}" });
    state.actionFeedback[key] = processActionFeedback(path, result);
    render();
    await refresh();
  } catch (error) {
    state.actionFeedback[key] = { state: "attention", text: `${processActionLabel(path)} failed: ${error.message}` };
    render();
  }
}

async function runGuidanceAction(path) {
  if (path === "/api/refresh") { await refresh(); return; }
  await processAction(path);
}

async function loadReport() {
  state.report = await api("/api/setup/report");
  const reportEl = document.getElementById("setup-report");
  if (reportEl) reportEl.textContent = state.report;
}

// ─── Navigation ───────────────────────────────────────────────────────────────
function selectPanel(targetId) {
  // Backward compat alias
  if (targetId === "project_data") targetId = "overview";

  document.querySelectorAll(".nav-item").forEach(el => {
    el.classList.toggle("active", el.dataset.target === targetId);
  });

  // Support both .status-report (live HTML) and .dashboard (test harness)
  const panels = [
    ...Array.from(document.querySelectorAll(".status-report")),
    ...Array.from(document.querySelectorAll(".dashboard"))
  ];
  const seen = new Set();
  for (const el of panels) {
    if (seen.has(el)) continue;
    seen.add(el);
    const isTarget = el.id === targetId;
    el.classList.toggle("active", isTarget);
    el.style.display = isTarget ? "block" : "none";
  }

  if (targetId === "support") {
    loadReport();
    renderSupportSummary();
  }
  if (targetId === "producer_mix_review") renderMixReview();
  if (targetId === "producer_low_end") renderLowEndAnalysis();
  if (targetId === "producer_audio_evidence") {
    renderAudioAnalysis();
    loadAudioAnalysisJobs();
  }
  if (targetId === "producer_routing") renderRoutingAudit();
  if (targetId === "producer_organizer") renderProjectOrganizer();
  if (targetId === "producer_health") renderProjectHealth();
  const runtimeWorkflow = workflowByPanel(targetId);
  if (runtimeWorkflow?.id === "preflight") {
    renderRuntimeProductPanel(runtimeWorkflow.id);
  }
  if (targetId === "producer_roadmap") renderPlannedWorkflows();
  if (targetId === "logs_history") renderLogsHistory();
  if (targetId === "ports") renderPorts();
}

// ─── Data format helpers ──────────────────────────────────────────────────────
function byId(id) { return document.getElementById(id); }

function text(id, value) {
  const node = byId(id);
  if (node) node.textContent = safeString(value);
}

function numberValue(value, digits) {
  if (value == null || value === "") return "Unavailable";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return safeString(value);
  return digits == null ? String(Math.round(numeric)) : numeric.toFixed(digits);
}

function bpm(value) {
  if (value == null) return "Unavailable";
  return numberValue(value, 1);
}

function yesNo(value) { return value ? "YES" : "NO"; }

function stateLabel(s) {
  if (!s) return "Unavailable";
  if (s === "server-state") return "Server";
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function count(resource) {
  if (!resource || resource.state !== "live") return "Unavailable";
  return resource.total == null ? resource.shown || 0 : resource.total;
}

function formatPosition(value) {
  if (value == null) return "Unavailable";
  if (typeof value === "object") {
    if (value.song_position != null) return formatPosition(value.song_position);
    if (value.position != null) return formatPosition(value.position);
    const beats = Number(value.position_beats ?? value.beats);
    if (Number.isFinite(beats)) return `${beats.toFixed(2)} beats`;
    const ms = Number(value.position_ms ?? value.ms);
    if (Number.isFinite(ms)) {
      const totalSeconds = Math.max(0, Math.floor(ms / 1000));
      const minutes = Math.floor(totalSeconds / 60);
      const seconds = String(totalSeconds % 60).padStart(2, "0");
      return `${minutes}:${seconds}`;
    }
    const ticks = Number(value.position_ticks ?? value.ticks);
    if (Number.isFinite(ticks)) return `${Math.round(ticks)} ticks`;
    return "Unavailable";
  }
  const str = String(value);
  // Guard against raw JSON-like strings that might appear if value is serialized
  if (str.startsWith("{") || str.startsWith("[")) return "Unavailable";
  return str;
}

// ─── Event wiring ─────────────────────────────────────────────────────────────
function wireEvents() {
  document.querySelectorAll(".nav-item").forEach(tab => {
    tab.addEventListener("click", () => selectPanel(tab.dataset.target));
  });

  document.querySelectorAll(".nav-subgroup-header").forEach(header => {
    header.addEventListener("click", () => {
      const parent = header.closest(".nav-subgroup");
      if (parent) {
        parent.classList.toggle("open");
      }
    });
  });

  const refreshButton = document.getElementById("refresh-button");
  if (refreshButton) refreshButton.addEventListener("click", refresh);

  document.querySelectorAll(".transport-panel [data-transport-action]").forEach(button => {
    button.addEventListener("click", () => transportAction(button.dataset.transportAction));
  });

  document.querySelectorAll("[data-marker-relative]").forEach(button => {
    button.addEventListener("click", () => {
      const delta = Number(button.dataset.markerRelative);
      transportAction("jump_marker_relative", { delta });
    });
  });

  const runMixButton = document.getElementById("run-mix-review");
  if (runMixButton) runMixButton.addEventListener("click", runMixReview);

  const mixRefreshButton = document.getElementById("mix-refresh-status");
  if (mixRefreshButton) mixRefreshButton.addEventListener("click", refresh);

  const runLowEndButton = document.getElementById("run-low-end-analysis");
  if (runLowEndButton) runLowEndButton.addEventListener("click", runLowEndAnalysis);

  const lowEndRefreshButton = document.getElementById("low-end-refresh-status");
  if (lowEndRefreshButton) lowEndRefreshButton.addEventListener("click", refresh);

  const submitAudioButton = document.getElementById("submit-audio-analysis");
  if (submitAudioButton) submitAudioButton.addEventListener("click", submitAudioAnalysis);

  const refreshAudioButton = document.getElementById("refresh-audio-jobs");
  if (refreshAudioButton) refreshAudioButton.addEventListener("click", loadAudioAnalysisJobs);

  const runRoutingButton = document.getElementById("run-routing-audit");
  if (runRoutingButton) runRoutingButton.addEventListener("click", runRoutingAudit);

  const routingRefreshButton = document.getElementById("routing-refresh-status");
  if (routingRefreshButton) routingRefreshButton.addEventListener("click", refresh);

  const routingMode = document.getElementById("routing-check-mode");
  if (routingMode) routingMode.addEventListener("change", () => {
    resetRoutingLevel2Flow();
    renderRoutingAudit();
  });

  const routingTemplateCompliance = document.getElementById("routing-template-compliance");
  if (routingTemplateCompliance) routingTemplateCompliance.addEventListener("change", () => {
    renderRoutingAudit();
  });

  const routingTemplateProfile = document.getElementById("routing-template-profile");
  if (routingTemplateProfile) routingTemplateProfile.addEventListener("change", () => {
    renderRoutingAudit();
  });

  const runOrganizerButton = document.getElementById("run-project-organizer");
  if (runOrganizerButton) runOrganizerButton.addEventListener("click", runProjectOrganizer);

  const organizerRefreshButton = document.getElementById("organizer-refresh-status");
  if (organizerRefreshButton) organizerRefreshButton.addEventListener("click", refresh);

  const runHealthButton = document.getElementById("run-project-health");
  if (runHealthButton) runHealthButton.addEventListener("click", runProjectHealth);

  const healthRefreshButton = document.getElementById("health-refresh-status");
  if (healthRefreshButton) healthRefreshButton.addEventListener("click", refresh);

  const setupButton = document.getElementById("disconnected-setup-button");
  if (setupButton) setupButton.addEventListener("click", () => selectPanel("setup"));

  const successOverlay = document.getElementById("success-overlay");
  const successOverview = document.getElementById("success-overview-button");
  if (successOverview) {
    successOverview.addEventListener("click", () => {
      if (successOverlay) successOverlay.style.display = "none";
      selectPanel("overview");
    });
  }
  const successClients = document.getElementById("success-clients-button");
  if (successClients) {
    successClients.addEventListener("click", () => {
      if (successOverlay) successOverlay.style.display = "none";
      selectPanel("clients");
    });
  }
  const successDismiss = document.getElementById("success-dismiss-button");
  if (successDismiss && successOverlay) {
    successDismiss.addEventListener("click", () => { successOverlay.style.display = "none"; });
  }

  const copyReport = document.getElementById("copy-report");
  if (copyReport) {
    copyReport.addEventListener("click", async () => {
      await loadReport();
      await navigator.clipboard.writeText(state.report);
      copyReport.textContent = "Copied!";
      copyReport.classList.add("copied");
      setTimeout(() => { copyReport.textContent = "Copy support report"; copyReport.classList.remove("copied"); }, 1400);
    });
  }

  const downloadReport = document.getElementById("download-report");
  if (downloadReport) {
    downloadReport.addEventListener("click", async () => {
      await loadReport();
      const url = URL.createObjectURL(new Blob([state.report], { type: "text/markdown" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = "fls-pilot-setup-report.md";
      link.click();
      URL.revokeObjectURL(url);
    });
  }
}

// ─── Public API (for testing) ─────────────────────────────────────────────────
window.flsPilotControlCenter = {
  state,
  processAction,
  transportAction,
  refreshTransportStatus,
  runMixReview,
  runLowEndAnalysis,
  runRoutingAudit,
  runProjectOrganizer,
  runProjectHealth,
  submitAudioAnalysis,
  loadAudioAnalysisJobs,
  refreshAudioAnalysisJob,
  cancelAudioAnalysisJob,
  linkAudioAnalysisResult,
  runRuntimeProductWorkflow,
  renderMixReview,
  renderLowEndAnalysis,
  renderProjectData,
  renderLivePlaybackMounts,
  renderRoutingAudit,
  renderProjectOrganizer,
  renderProjectHealth,
  renderAudioAnalysis,
  renderRuntimeProductPanel,
  renderRuntimeProductPanels,
  renderRuntime,
  renderOverview,
  renderConnectionCheck,
  renderWorkflowCatalogState,
  renderWorkflowMetadataCatalog,
  renderPlannedWorkflows,
  renderNextAction,
  renderConnectionReadyBanner,
  renderLogsHistory,
  renderPorts,
  selectPanel,
  workflowRunBody,
  safeString,
  safeDebugString,
};

if (!window.__FLS_PILOT_TEST__) {
  wireEvents();
  refresh().catch(() => {
    const refreshTime = document.getElementById("refresh-time");
    if (refreshTime) refreshTime.textContent = "Error";
  });
}
