from __future__ import annotations

from typing import Any

BLOCKING_SEVERITIES = {"critical", "major"}


def open_blocking_issues(quality_report: dict[str, Any]) -> list[dict[str, Any]]:
    """Return unresolved Critical/Major issues."""

    return [
        issue
        for issue in quality_report.get("issues", [])
        if issue.get("severity") in BLOCKING_SEVERITIES and issue.get("status") == "open"
    ]
