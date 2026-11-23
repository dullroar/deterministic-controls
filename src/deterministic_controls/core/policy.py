"""Policy: maps a finding severity to failure."""

from __future__ import annotations

from deterministic_controls.core.api import Finding

FAILING_SEVERITIES = frozenset({"warning", "error"})


def finding_fails(finding: Finding) -> bool:
    """Return True if the finding must fail the run."""
    return finding.severity in FAILING_SEVERITIES
