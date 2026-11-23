"""The check API.

A check module is a Python module that the catalog names in its `module` key.
It has a function with the name given in the catalog key `entry`
(by convention `entry`):

    def entry(context: Context) -> list[Finding]:
        ...

Rules for a check:

- It receives a `Context`. It reads files only through the context helpers.
- It returns a list of `Finding`. An empty list means the check passed.
- It never writes a file in the checked repository.
- It does not catch its own internal errors. An exception gives the check
  status `error` and exit code 3.
- The result must be deterministic. The same input gives the same findings.

The runner imports the module of an enabled check only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

SEVERITIES = ("info", "warning", "error")


@dataclass(frozen=True)
class Finding:
    """One defect found by a check."""

    rule_id: str
    severity: str
    path: str | None
    line: int | None
    message: str
    evidence: str = ""

    def sort_key(self) -> tuple:
        return (
            self.path or "",
            self.line if self.line is not None else 0,
            self.rule_id,
            self.message,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "path": self.path,
            "line": self.line,
            "message": self.message,
            "evidence": self.evidence,
        }


class Context:
    """Read-only view of the checked repository for one check."""

    def __init__(self, root: Path, parameters: dict[str, Any] | None = None):
        self._root = Path(root).resolve()
        self._parameters = dict(parameters or {})

    @property
    def root(self) -> Path:
        return self._root

    @property
    def parameters(self) -> dict[str, Any]:
        return dict(self._parameters)

    def resolve(self, relpath: str) -> Path:
        """Return the absolute path of a repository-relative path.

        Raise ValueError if the path leaves the repository.
        """
        candidate = (self._root / relpath).resolve()
        if candidate != self._root and self._root not in candidate.parents:
            raise ValueError(f"path leaves the repository: {relpath}")
        return candidate

    def exists(self, relpath: str) -> bool:
        return self.resolve(relpath).exists()

    def read_text(self, relpath: str) -> str:
        return self.resolve(relpath).read_text(encoding="utf-8")

    def read_bytes(self, relpath: str) -> bytes:
        return self.resolve(relpath).read_bytes()

    def list_files(self, pattern: str = "**/*") -> list[str]:
        """Return sorted repository-relative POSIX paths of files that match."""
        found = []
        for path in self._root.glob(pattern):
            if path.is_file() and ".git" not in path.relative_to(self._root).parts:
                found.append(PurePosixPath(path.relative_to(self._root)).as_posix())
        return sorted(found)
