from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

from fls_pilot import protocol
from fls_pilot.step_sequencer import build_group_writes

CONTROLLER_PATH = (
    Path(__file__).resolve().parents[1]
    / "fl_controller"
    / "FLStudioPilot"
    / "device_FLStudioPilot.py"
)


class Stub(types.ModuleType):
    def __getattr__(self, name):
        value = 0
        setattr(self, name, value)
        return value


@pytest.fixture()
def controller(monkeypatch):
    module_names = (
        "channels",
        "device",
        "general",
        "midi",
        "mixer",
        "patterns",
        "playlist",
        "plugins",
        "transport",
        "ui",
        "arrangement",
        "utils",
    )
    stubs = {name: Stub(name) for name in module_names}
    for name, stub in stubs.items():
        monkeypatch.setitem(sys.modules, name, stub)

    spec = importlib.util.spec_from_file_location("fl_controller_wire_test", CONTROLLER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_send_message_replaces_oversized_response(controller) -> None:
    sent = []
    controller._send_sysex_fn = sent.append

    controller._send_message(
        controller.DIR_RESPONSE,
        "12345678",
        {"v": controller.PROTOCOL_VERSION, "ok": True, "data": {"blob": "x" * 4000}},
    )

    assert len(sent) == 1
    assert len(sent[0]) <= controller.MAX_SYSEX_WIRE_SAFE
    decoded = controller._decode_message(sent[0][1:-1])
    assert decoded is not None
    assert decoded[2]["code"] == "response_too_large"


def test_send_message_keeps_small_response(controller) -> None:
    sent = []
    controller._send_sysex_fn = sent.append
    payload = {"v": controller.PROTOCOL_VERSION, "ok": True, "data": {"pong": True}}

    controller._send_message(controller.DIR_RESPONSE, "12345678", payload)

    assert len(sent) == 1
    assert len(sent[0]) <= controller.MAX_SYSEX_WIRE_SAFE
    assert controller._decode_message(sent[0][1:-1])[2] == payload


def test_host_wire_guard_rejects_oversized_request() -> None:
    encoded = protocol.encode_message(
        protocol.DIR_REQUEST,
        "12345678",
        protocol.make_request("oversized", {"blob": "x" * 4000}),
    )

    with pytest.raises(protocol.SysExWireSizeError):
        protocol.ensure_wire_safe(encoded)


def test_stable_handler_registry_excludes_mutating_dev_probes(controller) -> None:
    assert controller._ENABLE_DEV_PROBES is False
    assert "mixer_probe_eq_type" not in controller._HANDLERS
    assert "mixer_probe_eq_gain" not in controller._HANDLERS
    assert "mixer_probe_eq_freq" not in controller._HANDLERS
    assert "mixer_probe_eq_q" not in controller._HANDLERS


def test_api_probe_is_read_only_whitelist(controller) -> None:
    assert controller._h_api_probe({"op": "ppq"})
    assert controller._h_api_probe({"op": "marker_add"}) == {
        "error": "unknown op: marker_add"
    }


def test_channel_get_steps_is_bounded_and_field_selective(controller) -> None:
    calls = {"grid": 0, "param": 0}
    controller.patterns.patternNumber = lambda: 1
    controller.patterns.patternCount = lambda: 1
    controller.channels.getGridBit = lambda _channel, _step: calls.__setitem__(
        "grid", calls["grid"] + 1
    ) or 1
    controller.channels.getStepParam = lambda *_args: calls.__setitem__(
        "param", calls["param"] + 1
    ) or 100

    result = controller._h_channel_get_steps(
        {"channel": 0, "steps": 64, "start": 0, "count": 16, "include": ["grid"]}
    )

    assert result["count"] == 16
    assert result["next_start"] == 16
    assert calls == {"grid": 16, "param": 0}
    assert controller._fits_response_data(result)


def test_channel_set_steps_has_compact_default_response(controller) -> None:
    calls = {"grid_write": 0, "grid_read": 0, "param_read": 0}
    controller.patterns.patternNumber = lambda: 1
    controller.patterns.patternCount = lambda: 1
    controller.channels.setGridBit = lambda *_args: calls.__setitem__(
        "grid_write", calls["grid_write"] + 1
    )
    controller.channels.getGridBit = lambda *_args: calls.__setitem__(
        "grid_read", calls["grid_read"] + 1
    )
    controller.channels.getStepParam = lambda *_args: calls.__setitem__(
        "param_read", calls["param_read"] + 1
    )
    controller.channels.updateGraphEditor = lambda: None

    result = controller._h_channel_set_steps(
        {"channel": 0, "pattern": 1, "steps": [{"step": 0, "value": True}]}
    )

    assert result == {
        "channel": 0,
        "pattern": 1,
        "changed": 1,
        "failures": [],
    }
    assert calls == {"grid_write": 1, "grid_read": 0, "param_read": 0}


def test_mixer_peak_page_stays_below_wire_limit(controller) -> None:
    controller.mixer.trackCount = lambda: 126
    controller.mixer.getTrackPeaks = lambda track, _mode: 1.0 + track / 1000.0

    result = controller._h_mixer_get_all_peaks({"start": 0, "count": 32})

    assert result["count"] == 32
    assert result["next_start"] == 32
    assert result["scale"] == 1_000_000
    assert all(type(value) is int for value in result["peaks"])
    assert controller._fits_response_data(result)


def test_plugin_names_only_avoids_value_reads(controller) -> None:
    calls = {"value": 0, "string": 0}
    controller.plugins.isValid = lambda *_args: True
    controller.plugins.getParamCount = lambda *_args: 100
    controller.plugins.getPluginName = lambda *_args: "Test Plugin"
    controller.plugins.getParamName = lambda index, *_args: f"Parameter {index}"
    controller.plugins.getParamValue = lambda *_args: calls.__setitem__(
        "value", calls["value"] + 1
    )
    controller.plugins.getParamValueString = lambda *_args: calls.__setitem__(
        "string", calls["string"] + 1
    )

    result = controller._h_plugin_get_params(
        {"track": 1, "slot": 0, "count": 16, "names_only": True}
    )

    assert result["count"] == 16
    assert calls == {"value": 0, "string": 0}
    assert all(set(row) == {"i", "name"} for row in result["params"])
    assert controller._fits_response_data(result)


def test_step_write_windows_are_request_wire_safe() -> None:
    rows = [
        {
            "step": step,
            "value": True,
            "velocity": 1.0,
            "pan": -1.0,
            "shift": 1.0,
            "repeat": 15,
            "release": 1.0,
            "mod": 1.0,
            "pitch": 120,
        }
        for step in range(64)
    ]

    writes = build_group_writes(0, 1, rows)

    assert len(writes) == 13
    for write in writes:
        encoded = protocol.encode_message(
            protocol.DIR_REQUEST,
            "00000000",
            protocol.make_request(write["command"], write["params"]),
        )
        assert protocol.sysex_wire_size(encoded) <= protocol.MAX_SYSEX_WIRE_SAFE
