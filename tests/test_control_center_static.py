from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "src" / "fls_pilot" / "control_center_static" / "app.js"
INDEX_HTML = ROOT / "src" / "fls_pilot" / "control_center_static" / "index.html"


def _run_node_dom_check(script: str) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for control center static DOM checks")
    result = subprocess.run(
        [node, "-e", script, str(APP_JS)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_v3_runtime_workflow_copy_exposes_evidence_limits() -> None:
    html = INDEX_HTML.read_text("utf-8")
    js = APP_JS.read_text("utf-8")

    assert 'Preflight <span class="badge badge-ok">Read-only</span>' in html
    assert "Level evidence, render settings, and mastering remain separate checks." in html
    assert 'Jam 2 Project <span class="badge badge-planned">Planned</span>' in html
    assert "It is not part of the v3.0 release scope." in html
    assert "/api/workflows/jam-2-project" not in js
    assert "/api/workflows/plugin-assistant" not in js
    assert 'rendered_master: "Rendered master audio"' in js
    assert 'static_snapshot_only: "Project metadata"' in js
    assert 'id="producer_audio_evidence"' in html
    assert 'id="project-title"' in html
    assert 'id="transport-play"' in html
    assert 'id="playlist-marker-strip"' in html
    assert 'data-live-playback="mix_review"' in html
    assert 'data-live-playback="low_end_analysis"' in html
    assert 'data-live-playback="preflight"' in html
    assert 'id="mix-review-interactions"' in html
    assert 'id="low-end-interactions"' in html
    assert 'id="low-end-selection-list"' in html
    assert 'id="low-end-add-track"' in html
    assert "function renderLowEndSelection" in js
    assert "role_changes" in js
    assert "added_entities" in js
    assert "removed_entities" in js
    assert 'id="routing-audit-interactions"' in html
    assert 'id="organizer-interactions"' in html
    assert "Routing Check Mode" in html
    assert "Static Routing &amp; Settings Audit (Lvl 1)" in html
    assert "Signal Flow Assisted Routing Audit (Lvl 2)" in html
    assert "Template Compliance" in html
    assert "Auto-detect Template Compliance" in html
    assert "Select Template Profile" in html
    assert "Template Compliance Off" in html
    assert "async function submitAudioAnalysis()" in js
    assert "function renderRoutingLevel2Flow" in js
    assert "Start playback automatically" in js
    assert "Playback is running - start analysis" in js
    assert 'audioAnalysisRequest("cancel"' in js
    assert 'audioAnalysisRequest("result"' in js


def test_live_transport_polling_does_not_disable_controls() -> None:
    js = APP_JS.read_text("utf-8")

    refresh_start = js.index("async function refreshTransportStatus()")
    action_start = js.index("async function transportAction(")
    refresh_body = js[refresh_start:action_start]

    assert "polling: false" in js
    assert "state.transport.polling = true" in refresh_body
    assert "state.transport.polling = false" in refresh_body
    assert "state.transport.loading = true" not in refresh_body
    assert "state.transport.loading = false" not in refresh_body
    assert "button.disabled = state.transport.loading;" in js


def test_initial_refresh_runs_full_status_before_quick_status() -> None:
    js = APP_JS.read_text("utf-8")

    assert 'const statusPath = state.status ? "/api/status/quick" : "/api/status";' in js
    assert "const API_REQUEST_TIMEOUT_MS = 20000;" in js


def test_control_center_static_status_failure_guides_setup_recheck() -> None:
    _run_node_dom_check(
        r"""
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

class Element {
  constructor(tagName, id = "") {
    this.tagName = tagName.toUpperCase();
    this.id = id;
    this.children = [];
    this.style = {};
    this.dataset = {};
    this.disabled = false;
    this.onclick = null;
    this._textContent = "";
    this._className = "";
  }
  set className(value) { this._className = String(value || ""); }
  get className() { return this._className; }
  set textContent(value) {
    this._textContent = String(value ?? "");
    this.children = [];
  }
  get textContent() {
    return this._textContent + this.children.map((child) => child.textContent).join("");
  }
  append(...nodes) { for (const node of nodes) this.appendChild(node); }
  appendChild(node) { this.children.push(node); return node; }
}

function textTree(node) {
  if (!node) return "";
  return [node._textContent || "", ...node.children.map(textTree)].join("");
}

const elements = new Map();
function register(id, tagName = "div") {
  const element = new Element(tagName, id);
  elements.set(id, element);
  return element;
}

register("bridge-pill");
register("refresh-time");
register("next-action-title");
register("next-action-detail");
register("next-action-button", "button");
register("setup-steps");

const document = {
  createElement: (tagName) => new Element(tagName),
  getElementById: (id) => elements.get(id) || null,
  querySelectorAll: () => [],
  querySelector: () => null
};

const context = {
  Blob,
  URL,
  clearInterval,
  clearTimeout,
  console,
  document,
  fetch: async () => { throw new Error("status backend did not answer"); },
  navigator: {},
  setInterval,
  setTimeout,
  window: { __FLS_PILOT_TEST__: true }
};
context.window.document = document;

vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);

const controls = context.window.flsPilotControlCenter;

(async () => {
  await controls.refresh();

  assert.match(controls.state.statusError, /status backend did not answer/);
  assert.strictEqual(elements.get("next-action-title").textContent, "Status check did not finish");
  assert.strictEqual(elements.get("next-action-button").textContent, "Re-check Status");
  const setupText = textTree(elements.get("setup-steps"));
  assert.match(setupText, /Status check did not finish/);
  assert.match(setupText, /No FL Studio project changes were made/);
})().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
});
"""
    )


def test_control_center_static_runtime_and_disconnect_behaviour() -> None:
    _run_node_dom_check(
        r"""
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

class ClassList {
  constructor(element) {
    this.element = element;
    this.values = new Set();
  }

  setFromString(value) {
    this.values = new Set(String(value || "").split(/\s+/).filter(Boolean));
  }

  sync() {
    this.element._className = Array.from(this.values).join(" ");
  }

  add(name) {
    this.values.add(name);
    this.sync();
  }

  remove(name) {
    this.values.delete(name);
    this.sync();
  }

  contains(name) {
    return this.values.has(name);
  }

  toggle(name, force) {
    const enabled = force === undefined ? !this.values.has(name) : Boolean(force);
    if (enabled) {
      this.values.add(name);
    } else {
      this.values.delete(name);
    }
    this.sync();
    return enabled;
  }
}

class Element {
  constructor(tagName = "div", id = "") {
    this.tagName = tagName.toUpperCase();
    this.id = id;
    this.children = [];
    this.dataset = {};
    this.disabled = false;
    this.listeners = {};
    this.onclick = null;
    this.parentElement = null;
    this.style = {};
    this.textContent = "";
    this.title = "";
    this._className = "";
    this.classList = new ClassList(this);
  }

  set className(value) {
    this._className = String(value || "");
    this.classList.setFromString(this._className);
  }

  get className() {
    return this._className;
  }

  append(...nodes) {
    for (const node of nodes) {
      this.appendChild(node);
    }
  }

  appendChild(node) {
    node.parentElement = this;
    this.children.push(node);
    return node;
  }

  addEventListener(name, handler) {
    this.listeners[name] = handler;
  }
}

function collect(root, predicate) {
  const out = [];
  function walk(node) {
    if (predicate(node)) out.push(node);
    for (const child of node.children || []) walk(child);
  }
  walk(root);
  return out;
}

function textTree(root) {
  let out = root.textContent || "";
  for (const child of root.children || []) out += "\n" + textTree(child);
  return out;
}

function response(payload) {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    headers: { get: () => "application/json" },
    json: async () => payload,
    text: async () => JSON.stringify(payload)
  };
}

function baseStatus(daemonProcess, bridgeState = "unavailable") {
  return {
    version: "3.0.0b4",
    readiness: { state: "blocked" },
    groups: {
      environment: [],
      daemon: [],
      midi: [],
      controller: [],
      mcp_sse: [],
      mcp_apply: []
    },
    setup_guidance: [],
    checkpoints: {},
    processes: {
      daemon: daemonProcess,
      sse: { state: "stopped", logs: [] }
    },
    ports: {
      control_center: { host: "127.0.0.1", selected_port: 8766, preferred_port: 8766 },
      daemon: { host: "127.0.0.1", selected_port: 9787, preferred_port: 9787 },
      sse: { host: "127.0.0.1", selected_port: 8080, preferred_port: 8080 }
    },
    snippets: {
      chatgpt: { url: "http://localhost:8080/sse" },
      claude: {},
      cursor: {},
      terminal: { daemon: "fls-pilot-daemon", sse: "fls-pilot --sse" }
    },
    mcp: {
      sse_probe: {
        state: "not_required",
        message: "SSE server is stopped.",
        url: "http://localhost:8080/sse"
      }
    },
    dashboard: {
      bridge: { state: bridgeState },
      project: {},
      resources: {},
      transport: {},
      safety: { read_only: true, dry_run_available: true, rollback_available: false },
      evidence: []
    }
  };
}

function createHarness() {
  const elements = new Map();
  const navItems = [];
  const dashboards = [];

  function register(id, tagName = "div", className = "") {
    const element = new Element(tagName, id);
    element.className = className;
    elements.set(id, element);
    return element;
  }

  for (const id of [
    "bridge-pill",
    "version-pill",
    "refresh-time",
    "setup-steps",
    "runtime-status",
    "client-snippets",
    "connected-version",
    "connected-target",
    "connection-dot",
    "disconnected-overlay",
    "tempo-value",
    "channel-count",
    "mixer-count",
    "pattern-count",
    "playlist-count",
    "record-state",
    "song-position",
    "status-orb",
    "read-only-state",
    "rollback-state",
    "dry-run-state",
    "evidence-table",
    "footer-cc-port",
    "success-overlay",
    "loading-overlay",
    "loading-text"
  ]) {
    register(id);
  }

  for (const id of ["project_data", "setup", "runtime", "clients", "support"]) {
    const dashboard = register(id, "main", "dashboard");
    dashboard.style.display = id === "project_data" ? "block" : "none";
    dashboards.push(dashboard);
  }

  for (const target of ["project_data", "runtime", "clients", "setup", "support"]) {
    const item = new Element("button");
    item.className = target === "project_data" ? "nav-item active" : "nav-item";
    item.dataset.target = target;
    navItems.push(item);
  }

  const connectionCard = new Element("div");
  connectionCard.className = "connection-card";
  const eyebrow = new Element("span");
  eyebrow.className = "eyebrow";
  connectionCard.appendChild(eyebrow);

  const document = {
    createElement: (tagName) => new Element(tagName),
    getElementById: (id) => elements.get(id) || null,
    querySelectorAll: (selector) => {
      if (selector === ".nav-item") return navItems;
      if (selector === ".dashboard") return dashboards;
      return [];
    },
    querySelector: (selector) => {
      if (selector === ".connection-card") return connectionCard;
      if (selector === ".connection-card .eyebrow") return eyebrow;
      return null;
    }
  };

  const context = {
    Blob,
    URL,
    clearInterval,
    console,
    document,
    fetch: async () => response({}),
    navigator: { clipboard: { writeText: async () => undefined } },
    setInterval,
    window: { __FLS_PILOT_TEST__: true }
  };
  context.window.document = document;

  vm.createContext(context);
  vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);

  return {
    controls: context.window.flsPilotControlCenter,
    context,
    dashboards,
    elements
  };
}

(async () => {
  const harness = createHarness();
  const controls = harness.controls;

  controls.state.status = baseStatus({ state: "stopped", logs: [] });
  controls.renderProjectData();
  assert.strictEqual(harness.elements.get("disconnected-overlay").style.display, "flex");
  assert.strictEqual(harness.elements.get("project_data").style.display, "block");
  assert.strictEqual(harness.elements.get("setup").style.display, "none");

  controls.state.status = baseStatus(
    { state: "external", health: { reachable: true }, logs: [] },
    "live"
  );
  controls.renderRuntime();
  const runtime = harness.elements.get("runtime-status");
  const daemonCard = runtime.children[0];
  const daemonButtons = collect(daemonCard, (node) => node.tagName === "BUTTON");
  assert.strictEqual(daemonButtons[0].disabled, true);
  assert.strictEqual(daemonButtons[1].disabled, true);
  assert.match(textTree(daemonCard), /External daemon is reachable/);

  const calls = [];
  harness.context.fetch = async (path) => {
    calls.push(path);
    if (path === "/api/process/daemon/start") {
      return response({
        ok: false,
        state: "port_conflict",
        message: "Port 127.0.0.1:9787 is occupied by a non-daemon process.",
        fallback_port: 9788
      });
    }
    if (path === "/api/status/quick") {
      return response(baseStatus({ state: "stopped", logs: [] }));
    }
    throw new Error(`unexpected fetch path: ${path}`);
  };

  await controls.processAction("/api/process/daemon/start");
  assert.deepStrictEqual(calls, ["/api/process/daemon/start", "/api/status/quick"]);
  assert.strictEqual(controls.state.actionFeedback.daemon.state, "attention");
  assert.match(controls.state.actionFeedback.daemon.text, /non-daemon process/);
  assert.match(controls.state.actionFeedback.daemon.text, /9788/);
  assert.match(textTree(harness.elements.get("runtime-status")), /non-daemon process/);
})().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
});
"""
    )


def test_control_center_static_workflow_catalog_render() -> None:
    _run_node_dom_check(
        r"""
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

class ClassList {
  constructor(element) {
    this.element = element;
    this.values = new Set();
  }
  setFromString(value) {
    this.values = new Set(String(value || "").split(/\s+/).filter(Boolean));
  }
  sync() {
    this.element._className = Array.from(this.values).join(" ");
  }
  add(name) { this.values.add(name); this.sync(); }
  remove(name) { this.values.delete(name); this.sync(); }
  contains(name) { return this.values.has(name); }
  toggle(name, force) {
    const enabled = force === undefined ? !this.values.has(name) : Boolean(force);
    if (enabled) this.values.add(name); else this.values.delete(name);
    this.sync();
    return enabled;
  }
}

class Element {
  constructor(tagName = "div", id = "") {
    this.tagName = tagName.toUpperCase();
    this.id = id;
    this.children = [];
    this.dataset = {};
    this.disabled = false;
    this.listeners = {};
    this.onclick = null;
    this.parentElement = null;
    this.style = {};
    this.textContent = "";
    this.title = "";
    this._className = "";
    this.classList = new ClassList(this);
  }
  set className(value) {
    this._className = String(value || "");
    this.classList.setFromString(this._className);
  }
  get className() { return this._className; }
  append(...nodes) { for (const node of nodes) this.appendChild(node); }
  appendChild(node) {
    node.parentElement = this;
    this.children.push(node);
    return node;
  }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  querySelector(selector) {
    if (selector === ".nav-badge") {
      return collect(this, (node) => node.classList.contains("nav-badge"))[0] || null;
    }
    return null;
  }
}

function collect(root, predicate) {
  const out = [];
  function walk(node) {
    if (predicate(node)) out.push(node);
    for (const child of node.children || []) walk(child);
  }
  walk(root);
  return out;
}

function textTree(root) {
  let out = root.textContent || "";
  for (const child of root.children || []) out += "\n" + textTree(child);
  return out;
}

const elements = new Map();
const navItems = [];
const panels = [];

function register(id, tagName = "div", className = "") {
  const element = new Element(tagName, id);
  element.className = className;
  elements.set(id, element);
  return element;
}

function nav(id, target, workflowId) {
  const item = new Element("button", id);
  item.className = "nav-item";
  item.dataset.target = target;
  item.dataset.workflowId = workflowId;
  const label = new Element("span");
  label.textContent = workflowId;
  const badge = new Element("span");
  badge.className = "nav-badge badge-neutral";
  item.append(label, badge);
  navItems.push(item);
  return item;
}

nav("nav-mix-review", "producer_mix_review", "mix_review");
const preflightNav = nav("nav-preflight", "producer_preflight", "preflight");
const healthPanel = register("producer_health", "main", "status-report");
healthPanel.style.display = "none";
panels.push(register("overview", "main", "status-report"));
panels.push(healthPanel);
register("planned-workflow-list");
register("workflow-metadata-catalog");
register("next-action-title");
register("next-action-detail");
register("next-action-button", "button");
register("connection-ready-banner");

const document = {
  createElement: (tagName) => new Element(tagName),
  getElementById: (id) => elements.get(id) || null,
  querySelectorAll: (selector) => {
    if (selector === ".nav-item") return navItems;
    if (selector === ".status-report") return panels;
    if (selector === ".dashboard") return [];
    return [];
  },
  querySelector: (selector) => {
    const match = selector.match(/^\[data-workflow-id="([^"]+)"\]$/);
    if (match) return navItems.find((item) => item.dataset.workflowId === match[1]) || null;
    return null;
  }
};

const context = {
  Blob,
  URL,
  clearInterval,
  console,
  document,
  fetch: async () => { throw new Error("fetch not expected"); },
  navigator: {},
  setInterval,
  setTimeout,
  window: { __FLS_PILOT_TEST__: true }
};
context.window.document = document;

vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);

const controls = context.window.flsPilotControlCenter;
controls.state.status = {
  ui: {
    workflow_catalog: [
      {
        id: "mix_review",
        panel_id: "producer_mix_review",
        title: "Mix Review",
        maturity: "read_only",
        enabled: true,
        safety_note: "Read-only mixer review.",
        metadata: {
          pack_extensions: [{
            pack_id: "genre.house",
            pack_title: "House Pack",
            pack_version: "1.0.0",
            entitlement: { kind: "pro" },
            profiles: [{ id: "house", title: "House", genre: "house" }],
            metadata: { genre: "house" }
          }]
        }
      },
      { id: "preflight", panel_id: "producer_preflight", title: "Preflight", maturity: "planned", enabled: false, locked: true, safety_note: "Planned. No action is available yet." }
    ],
    next_action: {
      label: "Run Health Scan",
      detail: "Start with a read-only overview.",
      target_panel: "producer_health",
      action_label: "Open Health"
    }
  },
  status_report: {
    bridge: { state: "live" },
    project: { state: "live" }
  }
};

controls.renderWorkflowCatalogState();
assert(preflightNav.classList.contains("nav-item-disabled"));
assert.strictEqual(preflightNav.querySelector(".nav-badge").textContent, "Planned");

controls.renderWorkflowMetadataCatalog();
const catalogText = textTree(elements.get("workflow-metadata-catalog"));
assert.match(catalogText, /Mix Review/);
assert.match(catalogText, /Read-only/);
assert.match(catalogText, /Pack/);
assert.match(catalogText, /Pro/);
assert.match(catalogText, /Genre · house/);
assert.match(catalogText, /Profile: House/);
assert.match(catalogText, /Planned/);
assert.match(catalogText, /Locked/);

controls.renderPlannedWorkflows();
const plannedText = textTree(elements.get("planned-workflow-list"));
assert.match(plannedText, /Preflight/);
assert.match(plannedText, /No action is available yet/);

controls.renderNextAction();
assert.strictEqual(elements.get("next-action-title").textContent, "Run Health Scan");
assert.strictEqual(elements.get("next-action-button").textContent, "Open Health");
elements.get("next-action-button").onclick();
assert.strictEqual(healthPanel.style.display, "block");

controls.renderConnectionReadyBanner();
assert.strictEqual(elements.get("connection-ready-banner").style.display, "flex");
"""
    )


def test_control_center_static_runtime_interaction_requests_collect_decisions() -> None:
    _run_node_dom_check(
        r"""
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

class ClassList {
  constructor(element) {
    this.element = element;
    this.values = new Set();
  }
  setFromString(value) {
    this.values = new Set(String(value || "").split(/\s+/).filter(Boolean));
  }
  sync() {
    this.element._className = Array.from(this.values).join(" ");
  }
  add(name) { this.values.add(name); this.sync(); }
  remove(name) { this.values.delete(name); this.sync(); }
  contains(name) { return this.values.has(name); }
  toggle(name, force) {
    const enabled = force === undefined ? !this.values.has(name) : Boolean(force);
    if (enabled) this.values.add(name); else this.values.delete(name);
    this.sync();
    return enabled;
  }
}

class Element {
  constructor(tagName = "div", id = "") {
    this.tagName = tagName.toUpperCase();
    this.id = id;
    this.children = [];
    this.dataset = {};
    this.disabled = false;
    this.listeners = {};
    this.parentElement = null;
    this.style = {};
    this.textContent = "";
    this.title = "";
    this.type = "";
    this.name = "";
    this.value = "";
    this.checked = false;
    this.placeholder = "";
    this._className = "";
    this.classList = new ClassList(this);
  }
  set className(value) {
    this._className = String(value || "");
    this.classList.setFromString(this._className);
  }
  get className() { return this._className; }
  set innerHTML(value) {
    this.children = [];
    this.textContent = String(value || "");
  }
  get innerHTML() { return this.textContent; }
  append(...nodes) { for (const node of nodes) this.appendChild(node); }
  appendChild(node) {
    node.parentElement = this;
    this.children.push(node);
    return node;
  }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  querySelector(selector) {
    return collect(this, (node) => matches(node, selector))[0] || null;
  }
  querySelectorAll(selector) {
    return collect(this, (node) => matches(node, selector));
  }
}

function matches(node, selector) {
  if (selector === "input") return node.tagName === "INPUT";
  if (selector.startsWith(".")) return node.classList.contains(selector.slice(1));
  return false;
}

function collect(root, predicate) {
  const out = [];
  function walk(node) {
    if (predicate(node)) out.push(node);
    for (const child of node.children || []) walk(child);
  }
  walk(root);
  return out;
}

function textTree(root) {
  let out = root.textContent || "";
  for (const child of root.children || []) out += "\n" + textTree(child);
  return out;
}

const elements = new Map();
function register(id, tagName = "div", className = "") {
  const element = new Element(tagName, id);
  element.className = className;
  elements.set(id, element);
  return element;
}

const panel = register("producer_preflight", "main", "status-report");
const content = register("preflight-runtime-content", "div", "runtime-workflow-content");
panel.appendChild(content);

const document = {
  createElement: (tagName) => new Element(tagName),
  getElementById: (id) => elements.get(id) || null,
  querySelectorAll: () => [],
  querySelector: () => null
};

const context = {
  Blob,
  URL,
  clearInterval,
  console,
  document,
  fetch: async () => { throw new Error("fetch not expected"); },
  navigator: {},
  setInterval,
  setTimeout,
  window: { __FLS_PILOT_TEST__: true }
};
context.window.document = document;

vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);

const controls = context.window.flsPilotControlCenter;
controls.state.runtimeWorkflows.preflight = {
  loading: false,
  error: null,
  report: {
    report_id: "rep_interactions",
    workflow: "preflight",
    title: "Preflight",
    analysis_mode: "static_snapshot",
    evidence_mode: "static_snapshot_only",
    freshness: { status: "fresh" },
    coverage: { score: 100 },
    confidence_score: 80,
    findings: [],
    limitations: [],
    next_actions: [],
    user_decisions: [],
    interaction_requests: [
      {
        id: "preflight.confirm_export",
        type: "confirm",
        title: "Confirm export target",
        prompt: "Confirm the export target is correct."
      },
      {
        id: "audio.render_master",
        type: "manual_task",
        title: "Render master",
        prompt: "Render a master WAV manually.",
        resume_input: { type: "file_path" }
      },
      {
        id: "preflight.pick_quality",
        type: "single_select",
        prompt: "Pick a quality gate.",
        options: [
          { id: "draft", label: "Draft" },
          { id: "release", label: "Release" }
        ]
      },
      {
        id: "preflight.pick_checks",
        type: "multi_select",
        prompt: "Pick manual checks.",
        options: [
          { id: "mono", label: "Mono", selected: true },
          { id: "tails", label: "Tails" }
        ]
      }
    ]
  }
};

controls.renderRuntimeProductPanel("preflight");
assert.match(textTree(content), /Decisions affecting this workflow/);
assert.doesNotMatch(textTree(content), /Confirm the export target is correct/);
assert.match(textTree(content), /Render a master WAV manually/);
assert.match(textTree(content), /Pick a quality gate/);
assert.match(textTree(content), /Pick manual checks/);

let release = collect(content, (node) => node.tagName === "INPUT" && node.value === "release")[0];
release.checked = true;
release.listeners.change();
let qualityDecision = controls.state.runtimeWorkflows.preflight.report.user_decisions.find((item) => item.interaction_id === "preflight.pick_quality");
assert.strictEqual(qualityDecision.selected.length, 1);
assert.strictEqual(qualityDecision.selected[0], "release");

let tails = collect(content, (node) => node.tagName === "INPUT" && node.value === "tails")[0];
tails.checked = true;
tails.listeners.change();
let checksDecision = controls.state.runtimeWorkflows.preflight.report.user_decisions.find((item) => item.interaction_id === "preflight.pick_checks");
assert.strictEqual(checksDecision.selected.length, 2);
assert.strictEqual(checksDecision.selected[0], "mono");
assert.strictEqual(checksDecision.selected[1], "tails");

let resume = collect(content, (node) => node.classList.contains("workflow-interaction-resume"))[0];
resume.value = "/tmp/master.wav";
resume.listeners.input();
let completed = collect(content, (node) => node.tagName === "INPUT" && node.type === "checkbox" && !node.value)[0];
completed.checked = true;
completed.listeners.change();
let manualDecision = controls.state.runtimeWorkflows.preflight.report.user_decisions.find((item) => item.interaction_id === "audio.render_master");
assert.strictEqual(manualDecision.type, "manual_task");
assert.strictEqual(manualDecision.completed, true);
assert.strictEqual(manualDecision.value, "/tmp/master.wav");
assert.match(textTree(content), /Saved\. Re-run this workflow to apply your answer: completed/);

const body = controls.workflowRunBody("preflight");
assert.strictEqual(body.user_decisions.length, 3);
assert.strictEqual(
  JSON.stringify(body.user_decisions.map((item) => item.interaction_id).sort()),
  JSON.stringify([
    "audio.render_master",
    "preflight.pick_checks",
    "preflight.pick_quality"
  ])
);
"""
    )


def test_control_center_static_mix_review_render() -> None:
    _run_node_dom_check(
        r"""
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

class ClassList {
  constructor(element) {
    this.element = element;
    this.values = new Set();
  }

  setFromString(value) {
    this.values = new Set(String(value || "").split(/\s+/).filter(Boolean));
  }

  sync() {
    this.element._className = Array.from(this.values).join(" ");
  }

  add(name) {
    this.values.add(name);
    this.sync();
  }

  remove(name) {
    this.values.delete(name);
    this.sync();
  }

  contains(name) {
    return this.values.has(name);
  }
}

class Element {
  constructor(tagName = "div", id = "") {
    this.tagName = tagName.toUpperCase();
    this.id = id;
    this.children = [];
    this.dataset = {};
    this.disabled = false;
    this.listeners = {};
    this.parentElement = null;
    this.textContent = "";
    this.colSpan = 1;
    this._className = "";
    this.classList = new ClassList(this);
    this.style = {
      setProperty(name, value) {
        this[name] = value;
      }
    };
  }

  set className(value) {
    this._className = String(value || "");
    this.classList.setFromString(this._className);
  }

  get className() {
    return this._className;
  }

  append(...nodes) {
    for (const node of nodes) this.appendChild(node);
  }

  appendChild(node) {
    node.parentElement = this;
    this.children.push(node);
    return node;
  }

  addEventListener(name, handler) {
    this.listeners[name] = handler;
  }
}

function textTree(root) {
  let out = root.textContent || "";
  for (const child of root.children || []) out += "\n" + textTree(child);
  return out;
}

const elements = new Map();
const root = new Element("div", "root");

function register(id, tagName = "div") {
  const element = new Element(tagName, id);
  elements.set(id, element);
  root.appendChild(element);
  return element;
}

for (const id of [
  "mix-review-layout",
  "run-mix-review",
  "mix-review-feedback",
  "mix-level-state",
  "mix-master-peak",
  "mix-master-headroom",
  "mix-peak-source",
  "mix-level-list",
  "mix-score-label",
  "mix-score-ring",
  "mix-score-value",
  "mix-score-caption",
  "mix-used-total",
  "mix-hot-total",
  "mix-finding-total",
  "mix-proposal-total",
  "mix-findings-count",
  "mix-finding-list",
  "mix-proposals-count",
  "mix-proposal-list",
  "mix-tone-state",
  "mix-band-low",
  "mix-band-mid",
  "mix-band-high",
  "mix-band-low-value",
  "mix-band-mid-value",
  "mix-band-high-value",
  "mix-band-sources",
  "mix-stereo-count",
  "mix-stereo-field",
  "mix-track-count",
  "mix-track-table",
  "mix-note-count",
  "mix-note-list",
  "low-end-layout",
  "run-low-end-analysis",
  "low-end-feedback",
  "low-end-map-state",
  "low-end-focus-board",
  "low-end-score-label",
  "low-end-score-ring",
  "low-end-score-value",
  "low-end-score-caption",
  "low-end-track-total",
  "low-end-finding-total",
  "low-end-master-headroom",
  "low-end-peak-source",
  "low-end-findings-count",
  "low-end-finding-list",
  "low-end-balance-state",
  "low-end-band-low",
  "low-end-band-mid",
  "low-end-band-high",
  "low-end-band-low-value",
  "low-end-band-mid-value",
  "low-end-band-high-value",
  "low-end-band-sources",
  "low-end-stereo-count",
  "low-end-stereo-field",
  "low-end-detail-count",
  "low-end-track-table",
  "low-end-note-count",
  "low-end-note-list"
]) {
  register(id, id === "mix-track-table" || id === "low-end-track-table" ? "tbody" : "div");
}

const document = {
  createElement: (tagName) => new Element(tagName),
  getElementById: (id) => elements.get(id) || null,
  querySelectorAll: () => [],
  querySelector: () => null
};

const context = {
  Blob,
  URL,
  clearInterval,
  console,
  document,
  fetch: async () => ({
    ok: true,
    headers: { get: () => "application/json" },
    json: async () => ({})
  }),
  navigator: { clipboard: { writeText: async () => undefined } },
  setInterval,
  window: { __FLS_PILOT_TEST__: true }
};
context.window.document = document;

vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);

const controls = context.window.flsPilotControlCenter;
controls.state.mixReview.report = {
  ok: true,
  state: "live",
  generated_at: "2026-06-14T12:00:00Z",
  summary: {
    health_score: 72,
    health_label: "At Risk",
    tracks: 4,
    used_tracks: 3,
    levels_valid: true,
    peak_source: "sustained_1200ms",
    findings: 2,
    proposals: 1,
    master_peak_db: 0.2,
    master_headroom_db: -0.2,
    hot_tracks: 1
  },
  findings: [
    {
      severity: "high",
      title: "Clipping / Peak Risk",
      detail: "Master is over 0 dBFS",
      track: 0
    },
    {
      severity: "medium",
      title: "Low-End Width Risk",
      detail: "Sub Bass is wide",
      track: 2
    }
  ],
  proposals: [
    {
      severity: "medium",
      title: "Lower Lead Vox",
      detail: "Trim the loudest source before the master",
      track_name: "Lead Vox",
      current_fader_db: -2,
      target_fader_db: -5,
      current_peak_db: -0.4,
      target_peak_db: -3
    }
  ],
  visuals: {
    level_tracks: [
      {
        track: 0,
        name: "Master",
        peak_db: 0.2,
        fader_db: 0,
        role: "master",
        level_state: "clip"
      },
      {
        track: 1,
        name: "Lead Vox",
        peak_db: -0.4,
        fader_db: -2,
        role: "insert",
        level_state: "risk"
      }
    ],
    stereo_tracks: [
      {
        track: 2,
        name: "Sub Bass",
        pan: 0.42,
        stereo_sep: 0.5,
        peak_db: -4,
        low_end: true
      }
    ],
    band_balance: {
      bands_pct: { low: 44.2, mid: 51.3, high: 4.5 },
      tracks: { low: ["Sub Bass"], mid: ["Lead Vox"], high: ["Hat"] }
    }
  },
  details: {
    tracks: [
      {
        track: 1,
        name: "Lead Vox",
        peak_db: -0.4,
        fader_db: -2,
        pan: 0,
        stereo_sep: 0,
        plugins: [{ slot: 0, name: "Fruity Parametric EQ 2" }],
        used: true
      },
      {
        track: 2,
        name: "Sub Bass",
        peak_db: -4,
        fader_db: -3,
        pan: 0.42,
        stereo_sep: 0.5,
        plugins: [{ slot: 1, name: "Fruity Parametric EQ 2" }],
        used: true
      }
    ],
    notes: ["Rough peak-energy estimate only."],
    limits: ["No output spectrum is available."],
    gather_errors: [],
    low_end: {
      summary: { low_end_tracks: 1, wide_low_end: 1 },
      tracks: [
        {
          track: 2,
          name: "Sub Bass",
          pan: 0.42,
          stereo_sep: 0.5,
          peak_db: -4
        }
      ],
      findings: [
        {
          severity: "medium",
          title: "Low-End Width Risk",
          detail: "Sub Bass is wide",
          track: "Sub Bass"
        }
      ],
      manual_checks: [
        {
          topic: "mono_sum",
          check: "Mono-sum the loudest section."
        }
      ]
    }
  }
};

controls.renderMixReview();

assert.strictEqual(elements.get("run-mix-review").disabled, false);
assert.strictEqual(elements.get("mix-score-value").textContent, "72 / 100");
assert.strictEqual(elements.get("mix-master-peak").textContent, "0.2 dB");
assert.match(textTree(elements.get("mix-review-feedback")), /Last review/);
assert.match(textTree(elements.get("mix-level-list")), /Lead Vox/);
assert.match(textTree(elements.get("mix-finding-list")), /Clipping/);
assert.match(textTree(elements.get("mix-proposal-list")), /Lower Lead Vox/);
assert.match(textTree(elements.get("mix-band-sources")), /Sub Bass/);
assert.match(textTree(elements.get("mix-stereo-field")), /Sub Bass/);
assert.match(textTree(elements.get("mix-track-table")), /Fruity Parametric EQ 2/);
assert.match(textTree(elements.get("mix-note-list")), /output spectrum/);

controls.state.lowEndAnalysis.report = controls.state.mixReview.report;
controls.renderLowEndAnalysis();

assert.strictEqual(elements.get("run-low-end-analysis").disabled, false);
assert.strictEqual(elements.get("low-end-track-total").textContent, "1");
assert.strictEqual(elements.get("low-end-finding-total").textContent, "1");
assert.match(textTree(elements.get("low-end-feedback")), /Last analysis/);
assert.match(textTree(elements.get("low-end-focus-board")), /Sub Bass/);
assert.match(textTree(elements.get("low-end-finding-list")), /Low-End Width Risk/);
assert.match(textTree(elements.get("low-end-band-sources")), /Sub Bass/);
assert.match(textTree(elements.get("low-end-stereo-field")), /Sub Bass/);
assert.match(textTree(elements.get("low-end-track-table")), /Sub Bass/);
assert.match(textTree(elements.get("low-end-note-list")), /Mono-sum/);
"""
    )


def test_control_center_static_routing_audit_render() -> None:
    _run_node_dom_check(
        r"""
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

class ClassList {
  constructor(element) {
    this.element = element;
    this.values = new Set();
  }

  setFromString(value) {
    this.values = new Set(String(value || "").split(/\s+/).filter(Boolean));
  }

  sync() {
    this.element._className = Array.from(this.values).join(" ");
  }

  add(name) {
    this.values.add(name);
    this.sync();
  }

  remove(name) {
    this.values.delete(name);
    this.sync();
  }

  contains(name) {
    return this.values.has(name);
  }
}

class Element {
  constructor(tagName = "div", id = "") {
    this.tagName = tagName.toUpperCase();
    this.id = id;
    this.children = [];
    this.dataset = {};
    this.disabled = false;
    this.listeners = {};
    this.parentElement = null;
    this.textContent = "";
    this.colSpan = 1;
    this._className = "";
    this.classList = new ClassList(this);
    this.style = {
      setProperty(name, value) {
        this[name] = value;
      }
    };
  }

  set className(value) {
    this._className = String(value || "");
    this.classList.setFromString(this._className);
  }

  get className() {
    return this._className;
  }

  append(...nodes) {
    for (const node of nodes) this.appendChild(node);
  }

  appendChild(node) {
    node.parentElement = this;
    this.children.push(node);
    return node;
  }

  addEventListener(name, handler) {
    this.listeners[name] = handler;
  }
}

function collect(root, predicate) {
  const out = [];
  function walk(node) {
    if (predicate(node)) out.push(node);
    for (const child of node.children || []) walk(child);
  }
  walk(root);
  return out;
}

function textTree(root) {
  let out = root.textContent || "";
  for (const child of root.children || []) out += "\n" + textTree(child);
  return out;
}

const elements = new Map();
const root = new Element("div", "root");

function register(id, tagName = "div") {
  const element = new Element(tagName, id);
  elements.set(id, element);
  root.appendChild(element);
  return element;
}

for (const id of [
  "routing-audit-layout",
  "run-routing-audit",
  "routing-audit-feedback",
  "routing-score-value",
  "routing-score-caption",
  "routing-score-label",
  "routing-channel-total",
  "routing-track-total",
  "routing-route-total",
  "routing-channel-count",
  "routing-track-count",
  "routing-route-count",
  "routing-findings-count",
  "routing-score-ring",
  "routing-map-state",
  "routing-graph-sources",
  "routing-graph-buses",
  "routing-graph-master",
  "routing-links",
  "routing-map",
  "routing-finding-list",
  "routing-risk-list",
  "routing-channel-table",
  "routing-route-table",
  "routing-track-table"
]) {
  register(id, id.endsWith("-table") ? "tbody" : "div");
}

const document = {
  createElement: (tagName) => new Element(tagName),
  getElementById: (id) => elements.get(id) || null,
  querySelectorAll: (selector) => {
    if (selector === ".routing-node") {
      return collect(root, (node) => node.classList.contains("routing-node"));
    }
    return [];
  },
  querySelector: () => null
};

const context = {
  Blob,
  URL,
  clearInterval,
  console,
  document,
  fetch: async () => ({
    ok: true,
    headers: { get: () => "application/json" },
    json: async () => ({})
  }),
  navigator: { clipboard: { writeText: async () => undefined } },
  setInterval,
  window: { __FLS_PILOT_TEST__: true }
};
context.window.document = document;

vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);

const controls = context.window.flsPilotControlCenter;
controls.state.routingAudit.report = {
  ok: true,
  state: "live",
  generated_at: "2026-06-14T12:00:00Z",
  summary: {
    health_score: 81,
    health_label: "Needs Review",
    channels: 4,
    mixer_tracks: 6,
    routes: 3,
    direct_to_master: 1,
    unrouted_channels: 1,
    dead_end_tracks: 1,
    unused_mixer_tracks: 1
  },
  findings: [
    {
      id: "generators_direct_to_master",
      severity: "warning",
      title: "Generators Direct to Master",
      detail: "Kick routes directly",
      count: 1
    },
    {
      id: "unrouted_channels",
      severity: "critical",
      title: "Unrouted Channels",
      detail: "FX Riser has no target",
      count: 1
    }
  ],
  graph: {
    nodes: [
      { id: "channel:1", label: "Kick", column: "sources", kind: "genplug", target_track: 1 },
      { id: "channel:2", label: "Vocal", column: "sources", kind: "audio", target_track: 3 },
      { id: "track:10", label: "Vocal Bus", column: "buses", kind: "bus", track: 10 },
      { id: "unrouted", label: "Unrouted", column: "buses", kind: "unrouted" },
      { id: "master", label: "Master", column: "master", kind: "master" }
    ],
    links: [
      { from: "channel:1", to: "master", kind: "direct" },
      { from: "channel:2", to: "track:10", kind: "audio" },
      { from: "track:10", to: "master", kind: "audio" }
    ],
    omitted_source_count: 0
  },
  details: {
    channels: [
      {
        name: "Kick",
        type: "genplug",
        target_mixer_track: 1,
        target_name: "Kick",
        route_state: "direct_to_master"
      },
      {
        name: "Vocal",
        type: "audio",
        target_mixer_track: 3,
        target_name: "Vocal",
        route_state: "bus_routed"
      }
    ],
    routes: [
      { src: 1, src_name: "Kick", dst: 0, dst_name: "Master", level: 1 },
      { src: 3, src_name: "Vocal", dst: 10, dst_name: "Vocal Bus", level: 0.75 }
    ],
    tracks: [
      {
        track: 0,
        name: "Master",
        role: "master",
        incoming_count: 2,
        targeted_channel_count: 0,
        routes_to: []
      },
      {
        track: 10,
        name: "Vocal Bus",
        role: "bus",
        incoming_count: 1,
        targeted_channel_count: 0,
        routes_to: [{ dst: 0, dst_name: "Master", level: 1 }]
      }
    ]
  }
};

controls.renderRoutingAudit();

assert.strictEqual(elements.get("run-routing-audit").disabled, false);
assert.strictEqual(elements.get("routing-score-value").textContent, "81 / 100");
assert.match(textTree(elements.get("routing-graph-sources")), /Kick/);
assert.match(textTree(elements.get("routing-graph-buses")), /Vocal Bus/);
assert.match(textTree(elements.get("routing-graph-master")), /Master/);
assert.match(textTree(elements.get("routing-finding-list")), /Generators Direct to Master/);
assert.match(textTree(elements.get("routing-risk-list")), /Direct-to-Master channel paths/);
assert.match(textTree(elements.get("routing-channel-table")), /Direct to Master/);
assert.match(textTree(elements.get("routing-route-table")), /Vocal Bus/);
assert.match(textTree(elements.get("routing-track-table")), /Vocal Bus/);
"""
    )


def test_control_center_static_project_organizer_render() -> None:
    _run_node_dom_check(
        r"""
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

class ClassList {
  constructor(element) {
    this.element = element;
    this.values = new Set();
  }

  setFromString(value) {
    this.values = new Set(String(value || "").split(/\s+/).filter(Boolean));
  }

  sync() {
    this.element._className = Array.from(this.values).join(" ");
  }

  add(name) {
    this.values.add(name);
    this.sync();
  }

  remove(name) {
    this.values.delete(name);
    this.sync();
  }

  contains(name) {
    return this.values.has(name);
  }
}

class Element {
  constructor(tagName = "div", id = "") {
    this.tagName = tagName.toUpperCase();
    this.id = id;
    this.children = [];
    this.dataset = {};
    this.disabled = false;
    this.listeners = {};
    this.parentElement = null;
    this.textContent = "";
    this.colSpan = 1;
    this._className = "";
    this.classList = new ClassList(this);
    this.style = {
      setProperty(name, value) {
        this[name] = value;
      }
    };
  }

  set className(value) {
    this._className = String(value || "");
    this.classList.setFromString(this._className);
  }

  get className() {
    return this._className;
  }

  append(...nodes) {
    for (const node of nodes) this.appendChild(node);
  }

  appendChild(node) {
    node.parentElement = this;
    this.children.push(node);
    return node;
  }

  addEventListener(name, handler) {
    this.listeners[name] = handler;
  }
}

function textTree(root) {
  let out = root.textContent || "";
  for (const child of root.children || []) out += "\n" + textTree(child);
  return out;
}

const elements = new Map();
const root = new Element("div", "root");

function register(id, tagName = "div") {
  const element = new Element(tagName, id);
  elements.set(id, element);
  root.appendChild(element);
  return element;
}

for (const id of [
  "organizer-layout",
  "run-project-organizer",
  "organizer-feedback",
  "organizer-map-state",
  "organizer-name-total",
  "organizer-routing-total",
  "organizer-color-total",
  "organizer-group-total",
  "organizer-map-grid",
  "organizer-score-label",
  "organizer-score-ring",
  "organizer-score-value",
  "organizer-score-caption",
  "organizer-channel-total",
  "organizer-pattern-total",
  "organizer-finding-total",
  "organizer-proposal-total",
  "organizer-guided-state",
  "organizer-next-priority",
  "organizer-next-issue",
  "organizer-next-tool",
  "organizer-guided-steps",
  "organizer-findings-count",
  "organizer-finding-list",
  "organizer-plan-count",
  "organizer-plan-list",
  "organizer-standard-count",
  "organizer-standard-grid",
  "organizer-grouping-count",
  "organizer-group-list",
  "organizer-detail-count",
  "organizer-detail-table",
  "organizer-note-count",
  "organizer-note-list"
]) {
  register(id, id === "organizer-detail-table" ? "tbody" : "div");
}

const document = {
  createElement: (tagName) => new Element(tagName),
  getElementById: (id) => elements.get(id) || null,
  querySelectorAll: () => [],
  querySelector: () => null
};

const context = {
  Blob,
  URL,
  clearInterval,
  console,
  document,
  fetch: async () => ({
    ok: true,
    headers: { get: () => "application/json" },
    json: async () => ({})
  }),
  navigator: { clipboard: { writeText: async () => undefined } },
  setInterval,
  window: { __FLS_PILOT_TEST__: true }
};
context.window.document = document;

vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);

const controls = context.window.flsPilotControlCenter;
controls.state.projectOrganizer.report = {
  ok: true,
  state: "live",
  generated_at: "2026-06-14T12:00:00Z",
  summary: {
    organization_score: 76,
    health_label: "Needs Cleanup",
    channels: 8,
    mixer_tracks: 12,
    patterns: 5,
    playlist_tracks: 4,
    diagnostics: 3,
    proposed_changes: 4,
    naming_cleanup: 2,
    routing_cleanup: 1,
    color_readback_missing: 6,
    grouping_candidates: 1
  },
  findings: [
    {
      id: "unnamed_channels",
      severity: "warning",
      title: "Default Channel Names",
      detail: "Channels with empty or default-looking names.",
      count: 2
    },
    {
      id: "routing_cleanup",
      severity: "critical",
      title: "Channels Need Mixer Targets",
      detail: "Channels routed only to Master or with unknown routing.",
      count: 1
    }
  ],
  cleanup_plan: {
    steps: [
      {
        id: "route_channel_1",
        kind: "channel_routing",
        priority: "high",
        title: "Route channel 1 to a free mixer track",
        detail: "Creates a one-step routing proposal using an existing free mixer track.",
        tool: "fl_apply_project_cleanup_step",
        risk: "low",
        requires_explicit_approval: true
      },
      {
        id: "rename_channel_2",
        kind: "channel_naming",
        priority: "medium",
        title: "Rename channel 2 to Lead",
        detail: "Uses channel metadata as naming evidence.",
        tool: "fl_apply_naming_standard",
        risk: "low",
        requires_explicit_approval: true
      }
    ]
  },
  guided: {
    state: "ready",
    priority: "High",
    next_issue: "Route channel 1 to a free mixer track",
    next_tool: "fl_apply_project_cleanup_step",
    steps: [
      { label: "Scan", tool: "fl_analyze_project_organization", state: "done" },
      { label: "Plan", tool: "fl_plan_project_cleanup", state: "active" },
      { label: "Approve One Step", tool: "User confirmation", state: "pending" }
    ]
  },
  standards: {
    naming: {
      tool: "fl_apply_naming_standard",
      style: "dynamic",
      suggested_rule_count: 2
    },
    color: {
      tool: "fl_apply_color_standard",
      style: "dynamic",
      suggested_rule_count: 4
    }
  },
  grouping: {
    candidate_groups: [
      {
        name: "Drum Bus",
        source_names: ["Kick", "Snare"],
        tool: "fl_group_tracks"
      }
    ]
  },
  details: {
    items: [
      {
        area: "Channel",
        index: 1,
        name: "Channel 1",
        status: "Needs name",
        detail: "No mixer target"
      },
      {
        area: "Mixer",
        index: 5,
        name: "Lead",
        status: "Named",
        detail: "Insert"
      }
    ],
    notes: [
      "Project Organizer is read-only in Control Center.",
      "Apply only one approved cleanup step at a time."
    ]
  }
};

controls.renderProjectOrganizer();

assert.strictEqual(elements.get("run-project-organizer").disabled, false);
assert.strictEqual(elements.get("organizer-score-value").textContent, "76 / 100");
assert.strictEqual(elements.get("organizer-routing-total").textContent, "1");
assert.match(textTree(elements.get("organizer-feedback")), /Last scan/);
assert.match(textTree(elements.get("organizer-map-grid")), /fl_scan_project_organization/);
assert.match(textTree(elements.get("organizer-guided-steps")), /fl_plan_project_cleanup/);
assert.match(textTree(elements.get("organizer-finding-list")), /Default Channel Names/);
assert.match(textTree(elements.get("organizer-plan-list")), /fl_apply_project_cleanup_step/);
assert.match(textTree(elements.get("organizer-standard-grid")), /fl_apply_color_standard/);
assert.match(textTree(elements.get("organizer-group-list")), /Drum Bus/);
assert.match(textTree(elements.get("organizer-detail-table")), /No mixer target/);
assert.match(textTree(elements.get("organizer-note-list")), /read-only/);
"""
    )


def test_control_center_static_project_health_render() -> None:
    _run_node_dom_check(
        r"""
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

class ClassList {
  constructor(element) {
    this.element = element;
    this.values = new Set();
  }

  setFromString(value) {
    this.values = new Set(String(value || "").split(/\s+/).filter(Boolean));
  }

  sync() {
    this.element._className = Array.from(this.values).join(" ");
  }

  add(name) {
    this.values.add(name);
    this.sync();
  }

  remove(name) {
    this.values.delete(name);
    this.sync();
  }

  contains(name) {
    return this.values.has(name);
  }

  toggle(name, force) {
    const enabled = force === undefined ? !this.values.has(name) : Boolean(force);
    if (enabled) {
      this.values.add(name);
    } else {
      this.values.delete(name);
    }
    this.sync();
    return enabled;
  }
}

class Element {
  constructor(tagName = "div", id = "") {
    this.tagName = tagName.toUpperCase();
    this.id = id;
    this.children = [];
    this.dataset = {};
    this.disabled = false;
    this.listeners = {};
    this.parentElement = null;
    this.textContent = "";
    this._className = "";
    this.classList = new ClassList(this);
    this.style = {
      setProperty(name, value) {
        this[name] = value;
      }
    };
  }

  set className(value) {
    this._className = String(value || "");
    this.classList.setFromString(this._className);
  }

  get className() {
    return this._className;
  }

  append(...nodes) {
    for (const node of nodes) this.appendChild(node);
  }

  appendChild(node) {
    node.parentElement = this;
    this.children.push(node);
    return node;
  }

  addEventListener(name, handler) {
    this.listeners[name] = handler;
  }
}

function textTree(root) {
  let out = root.textContent || "";
  for (const child of root.children || []) out += "\n" + textTree(child);
  return out;
}

const elements = new Map();
const root = new Element("div", "root");

function register(id, tagName = "div") {
  const element = new Element(tagName, id);
  elements.set(id, element);
  root.appendChild(element);
  return element;
}

for (const id of [
  "health-layout",
  "run-project-health",
  "health-feedback",
  "health-status-label",
  "health-risk-ring",
  "health-risk-value",
  "health-risk-caption",
  "health-score-value",
  "health-risk-stat-value",
  "health-coverage-value",
  "health-confidence-value",
  "health-freshness-value",
  "health-finding-total",
  "health-blocker-total",
  "health-section-count",
  "health-ready-total",
  "health-section-grid",
  "health-warning-count",
  "health-warning-list",
  "health-nav-list",
  "health-note-count",
  "health-note-list"
]) {
  register(id);
}

const document = {
  createElement: (tagName) => new Element(tagName),
  getElementById: (id) => elements.get(id) || null,
  querySelectorAll: () => [],
  querySelector: () => null
};

const context = {
  Blob,
  URL,
  clearInterval,
  console,
  document,
  fetch: async () => ({
    ok: true,
    headers: { get: () => "application/json" },
    json: async () => ({})
  }),
  navigator: { clipboard: { writeText: async () => undefined } },
  setInterval,
  window: { __FLS_PILOT_TEST__: true }
};
context.window.document = document;

vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);

const controls = context.window.flsPilotControlCenter;
controls.state.projectHealth.lastRun = "2026-06-14T12:00:00Z";
controls.state.projectOrganizer.report = {
  ok: true,
  summary: {
    organization_score: 76,
    health_label: "Needs Cleanup",
    proposed_changes: 4,
    routing_cleanup: 1
  },
  findings: [
    {
      severity: "warning",
      title: "Default Channel Names",
      detail: "Channels with empty or default-looking names.",
      count: 2
    },
    {
      severity: "critical",
      title: "Channels Need Mixer Targets",
      detail: "Channels routed only to Master or with unknown routing.",
      count: 1
    }
  ]
};
controls.state.mixReview.report = {
  ok: true,
  summary: {
    health_score: 72,
    health_label: "At Risk",
    hot_tracks: 1,
    master_peak_db: 0.2,
    master_headroom_db: 2.4
  },
  findings: [
    {
      severity: "high",
      title: "Clipping",
      detail: "Lead Vox clips on the loudest section.",
      track: "Lead Vox"
    }
  ]
};
controls.state.routingAudit.report = {
  ok: true,
  summary: {
    health_score: 81,
    health_label: "Needs Review",
    unrouted_channels: 1,
    dead_end_tracks: 0,
    direct_to_master: 1
  },
  findings: [
    {
      severity: "critical",
      title: "Unrouted Channels",
      detail: "FX Riser has no mixer target.",
      count: 1
    }
  ]
};
controls.state.lowEndAnalysis.report = {
  ok: true,
  summary: {
    master_headroom_db: 2.4,
    levels_valid: true
  },
  details: {
    tracks: [
      {
        track: 2,
        name: "Sub Bass",
        peak_db: -4,
        pan: 0.42,
        stereo_sep: 0.5
      }
    ],
    low_end: {
      findings: [
        {
          severity: "medium",
          title: "Low-End Width Risk",
          detail: "Sub Bass is wide.",
          track: "Sub Bass"
        }
      ],
      manual_checks: [
        {
          topic: "mono_sum",
          check: "Mono-sum the loudest section."
        }
      ]
    }
  }
};
controls.state.projectHealth.backendData = {
  overall_status: "fresh",
  overall_health_score: 78,
  overall_risk_score: 22,
  overall_coverage_pct: 100,
  overall_confidence_score: 82,
  sections: [
    {
      workflow: "project_organizer",
      title: "Organizer",
      report_id: "rep_org",
      freshness: "fresh",
      health_score: 76,
      risk_score: 24,
      confidence_score: 80,
      coverage: { required: 1, available: 1, status: "fresh", score: 100 },
      findings: controls.state.projectOrganizer.report.findings
    },
    {
      workflow: "mix_review",
      title: "Mix Review",
      report_id: "rep_mix",
      freshness: "fresh",
      health_score: 72,
      risk_score: 28,
      confidence_score: 80,
      coverage: { required: 1, available: 1, status: "fresh", score: 100 },
      findings: [
        ...controls.state.mixReview.report.findings,
        {
          severity: "critical",
          title: "Master Peak Over 0 dB",
          detail: "Master peak reads 0.2 dB."
        }
      ]
    },
    {
      workflow: "routing_audit",
      title: "Routing",
      report_id: "rep_routing",
      freshness: "fresh",
      health_score: 81,
      risk_score: 19,
      confidence_score: 90,
      coverage: { required: 1, available: 1, status: "fresh", score: 100 },
      findings: controls.state.routingAudit.report.findings
    },
    {
      workflow: "low_end_analysis",
      title: "Low-End",
      report_id: "rep_low",
      freshness: "fresh",
      health_score: 83,
      risk_score: 17,
      confidence_score: 78,
      coverage: { required: 1, available: 1, status: "fresh", score: 100 },
      findings: controls.state.lowEndAnalysis.report.details.low_end.findings
    }
  ]
};

controls.renderProjectHealth();

assert.strictEqual(elements.get("run-project-health").disabled, false);
assert.strictEqual(elements.get("health-risk-value").textContent, "78 / 100");
assert.strictEqual(elements.get("health-score-value").textContent, "78 / 100");
assert.strictEqual(elements.get("health-risk-stat-value").textContent, "22 / 100");
assert.strictEqual(elements.get("health-coverage-value").textContent, "4/4");
assert.strictEqual(elements.get("health-confidence-value").textContent, "82 / 100");
assert.strictEqual(elements.get("health-freshness-value").textContent, "Fresh");
assert.strictEqual(elements.get("health-ready-total").textContent, "4 ready");
assert.match(textTree(elements.get("health-feedback")), /No project changes are made/);
assert.match(textTree(elements.get("health-section-grid")), /Organizer/);
assert.match(textTree(elements.get("health-section-grid")), /Mix Review/);
assert.match(textTree(elements.get("health-warning-list")), /Master Peak Over 0 dB/);
assert.match(textTree(elements.get("health-warning-list")), /Channels Need Mixer Targets/);
assert.match(textTree(elements.get("health-nav-list")), /Routing/);
assert.match(textTree(elements.get("health-note-list")), /warning finding/);
"""
    )
