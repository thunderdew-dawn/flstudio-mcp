from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "src" / "fls_pilot" / "control_center_static" / "app.js"


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
    version: "3.0.0b1",
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
    if (path === "/api/refresh") {
      return response(baseStatus({ state: "stopped", logs: [] }));
    }
    throw new Error(`unexpected fetch path: ${path}`);
  };

  await controls.processAction("/api/process/daemon/start");
  assert.deepStrictEqual(calls, ["/api/process/daemon/start", "/api/refresh"]);
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
  "mix-note-list"
]) {
  register(id, id === "mix-track-table" ? "tbody" : "div");
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
      }
    ],
    notes: ["Rough peak-energy estimate only."],
    limits: ["No output spectrum is available."],
    gather_errors: []
  }
};

controls.renderMixReview();

assert.strictEqual(elements.get("run-mix-review").disabled, false);
assert.strictEqual(elements.get("mix-score-value").textContent, "72%");
assert.strictEqual(elements.get("mix-master-peak").textContent, "0.2 dB");
assert.match(textTree(elements.get("mix-review-feedback")), /Last review/);
assert.match(textTree(elements.get("mix-level-list")), /Lead Vox/);
assert.match(textTree(elements.get("mix-finding-list")), /Clipping/);
assert.match(textTree(elements.get("mix-proposal-list")), /Lower Lead Vox/);
assert.match(textTree(elements.get("mix-band-sources")), /Sub Bass/);
assert.match(textTree(elements.get("mix-stereo-field")), /Sub Bass/);
assert.match(textTree(elements.get("mix-track-table")), /Fruity Parametric EQ 2/);
assert.match(textTree(elements.get("mix-note-list")), /output spectrum/);
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
assert.strictEqual(elements.get("routing-score-value").textContent, "81%");
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
