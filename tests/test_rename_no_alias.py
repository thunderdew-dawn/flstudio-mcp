from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_fls_pilot_is_the_only_source_package() -> None:
    assert (ROOT / "src" / "fls_pilot").is_dir()
    assert not (ROOT / "src" / "fl_studio_mcp").exists()


def test_console_scripts_have_no_old_aliases() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    scripts = _project_scripts(pyproject)

    assert 'name = "fls-pilot"' in pyproject
    assert scripts == {
        "fls-pilot": "fls_pilot.server:main",
        "fls-pilot-control-center": "fls_pilot.control_center:main",
        "fls-pilot-daemon": "fls_pilot.daemon:main",
        "fls-pilot-doctor": "fls_pilot.doctor:main",
        "fls-pilot-status": "fls_pilot.status:main",
    }
    assert "fl-studio-mcp" not in scripts
    assert "fl-studio-mcp-daemon" not in scripts


def _project_scripts(pyproject: str) -> dict[str, str]:
    in_scripts = False
    scripts: dict[str, str] = {}
    for line in pyproject.splitlines():
        stripped = line.strip()
        if stripped == "[project.scripts]":
            in_scripts = True
            continue
        if in_scripts and stripped.startswith("["):
            break
        if not in_scripts or not stripped or stripped.startswith("#"):
            continue
        name, value = stripped.split("=", 1)
        scripts[name.strip()] = value.strip().strip('"')
    return scripts
