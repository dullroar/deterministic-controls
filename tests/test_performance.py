"""Performance tests: a loose bound on run time for synthetic repositories.

The bound is loose on purpose: 10,000 Markdown files in under 120 seconds.
The test prints the times. Copy them to `docs/fault-matrix.md` when they change much.
"""

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_mutation import FILES, build_repo, run  # noqa: E402

LIMIT_SECONDS = 120
PER_DIRECTORY = 100


def add_markdown_files(root: Path, count: int) -> None:
    """Add `count` Markdown files in `docs/`. Each file links to the next one."""
    for i in range(count):
        folder = root / "docs" / f"d{i // PER_DIRECTORY:03d}"
        folder.mkdir(parents=True, exist_ok=True)
        nxt = (i + 1) % count
        target = f"../d{nxt // PER_DIRECTORY:03d}/f{nxt:05d}.md"
        (folder / f"f{i:05d}.md").write_text(
            f"# File {i}\n\nText for file {i}.\n\nSee the [next file]({target}#file-{nxt}).\n",
            encoding="utf-8",
        )


class PerformanceTests(unittest.TestCase):
    def measure(self, count: int) -> float:
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(Path(tmp), "repo", FILES)
            add_markdown_files(root, count)
            started = time.monotonic()
            result = run(root)
            elapsed = time.monotonic() - started
        print(f"performance: {count:>6} Markdown files: {elapsed:7.2f} s", file=sys.stderr)
        self.assertEqual(result["status"], "passed", [
            (c["check_id"], c["findings"][:2]) for c in result["checks"] if c["findings"]])
        return elapsed

    def test_100_files(self):
        self.assertLess(self.measure(100), LIMIT_SECONDS)

    def test_1000_files(self):
        self.assertLess(self.measure(1000), LIMIT_SECONDS)

    def test_10000_files(self):
        self.assertLess(self.measure(10000), LIMIT_SECONDS)


if __name__ == "__main__":
    unittest.main()
