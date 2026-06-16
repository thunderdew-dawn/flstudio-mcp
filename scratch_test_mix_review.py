from __future__ import annotations
import json
from fls_pilot import control_center

snapshot = {
    "playing": False,
    "levels_valid": False,
    "peak_window": None,
    "tracks": [
        {
            "index": 0,
            "name": "Master",
            "vol_db": 0.0,
            "peak_db": -2.0,
            "peak_max": 0.8,
            "pan": 0.0,
            "stereo_sep": 0.0,
            "plugins": [],
            "routes_to": [],
        },
    ],
    "template_context": {},
    "gather_errors": [],
}

report = control_center._build_mix_review_report(snapshot)
print(json.dumps(report, indent=2))
