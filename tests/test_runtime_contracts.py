from __future__ import annotations

from fls_pilot.runtime.contracts import (
    ProjectContext,
    ReportScope,
    RuntimeResponse,
    RuntimeSession,
)


def test_runtime_session_round_trip() -> None:
    session = RuntimeSession(id="runtime_test", started_at="now", runtime_version="3.0")
    assert RuntimeSession.from_dict(session.to_dict()) == session


def test_unknown_project_context_remains_explicit() -> None:
    context = ProjectContext.unknown("runtime_test")
    restored = ProjectContext.from_dict(context.to_dict())

    assert restored.runtime_session_id == "runtime_test"
    assert restored.project_scope_id == "unknown"
    assert restored.project_fingerprint == "unknown"
    assert restored.snapshot_id == "unknown"
    assert restored.is_known is False


def test_report_scope_and_runtime_response_round_trip() -> None:
    scope = ReportScope(
        workflow_id="mix_review",
        runtime_session_id="runtime_test",
        project_scope_id="project_test",
        snapshot_id="snapshot_test",
        snapshot_revision=2,
    )
    response = RuntimeResponse(
        ok=True,
        operation="analysis.report.latest",
        data={"scope": scope.to_dict()},
    )

    restored = RuntimeResponse.from_dict(response.to_dict())
    assert restored == response
    assert ReportScope.from_dict(restored.data["scope"]) == scope
