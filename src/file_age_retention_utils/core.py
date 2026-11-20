"""File age retention: delete files older than a threshold.

This module intentionally keeps the surface small: one class that scans a
directory, decides which regular files are older than a threshold, and either
removes them or reports what it would remove.  The clock is injectable so tests
never depend on wall-clock time.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class RetentionResult:
    """Outcome for a single file considered by a retention run.

    ``path`` is the absolute path of the file, ``age_seconds`` is its age at
    the moment of evaluation, ``deleted`` is True if the file was removed (or
    would be removed in dry-run mode), and ``error`` is a human-readable
    description when the file could not be removed.
    """

    path: str
    age_seconds: float
    deleted: bool
    error: Optional[str] = None


@dataclass
class RetentionReport:
    """Aggregated report for one retention run.

    ``results`` holds one entry per regular file that was inspected.  The
    counts are derived from ``results`` so callers can present a summary
    without re-walking the list.
    """

    results: List[RetentionResult] = field(default_factory=list)
    dry_run: bool = False

    @property
    def scanned(self) -> int:
        return len(self.results)

    @property
    def deleted(self) -> int:
        return sum(1 for r in self.results if r.deleted)

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if not r.deleted and r.error is None)

    @property
    def errors(self) -> int:
        return sum(1 for r in self.results if r.error is not None)

    def summary(self) -> str:
        """Return a compact, stable, human-readable summary line.

        The wording is fixed rather than localised because the tests and any
        downstream log scraping depend on it.
        """
        mode = "dry-run" if self.dry_run else "live"
        return (
            f"{mode}: scanned={self.scanned} deleted={self.deleted} "
            f"skipped={self.skipped} errors={self.errors}"
        )


class FileAgeRetention:
    """Delete files in a directory tree older than a given age.

    Parameters
    ----------
    directory:
        Root directory to scan.  The scan is recursive by default.
    max_age_seconds:
        Files whose age is strictly greater than this value are candidates for
        deletion.  A file exactly at the threshold is kept, which makes the
        boundary deterministic and easy to test.
    recursive:
        When True (the default), subdirectories are scanned as well.
    clock:
        Callable returning the current time in seconds since the epoch.  Tests
        pass a fake clock; production code can rely on ``time.time``.
    """

    def __init__(
        self,
        directory: str,
        max_age_seconds: float,
        *,
        recursive: bool = True,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        if max_age_seconds < 0:
            raise ValueError("max_age_seconds must be non-negative")
        self.directory = os.path.abspath(directory)
        self.max_age_seconds = float(max_age_seconds)
        self.recursive = bool(recursive)
        self._clock = clock if clock is not None else __import__("time").time

    def _iter_files(self) -> Sequence[str]:
        """Return absolute paths of regular files under the root.

        Symlinks are skipped entirely.  Following them would let the scanner
        escape the configured directory, and deleting through a symlink is a
        surprising side effect for a retention tool.
        """
        found: List[str] = []
        if not os.path.isdir(self.directory):
            return found
        if self.recursive:
            for root, dirs, files in os.walk(self.directory, followlinks=False):
                # Do not descend into symlinked directories either.
                dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
                for name in files:
                    path = os.path.join(root, name)
                    if os.path.islink(path):
                        continue
                    if os.path.isfile(path):
                        found.append(path)
        else:
            for name in os.listdir(self.directory):
                path = os.path.join(self.directory, name)
                if os.path.islink(path):
                    continue
                if os.path.isfile(path):
                    found.append(path)
        return sorted(found)

    def run(self, dry_run: bool = False) -> RetentionReport:
        """Evaluate every file and optionally delete the old ones.

        In dry-run mode the report marks files as ``deleted`` when they *would*
        be removed, but no filesystem mutation happens.  This keeps the report
        shape identical between the two modes.
        """
        report = RetentionReport(dry_run=bool(dry_run))
        now = self._clock()
        for path in self._iter_files():
            try:
                mtime = os.path.getmtime(path)
            except OSError as exc:
                report.results.append(
                    RetentionResult(
                        path=path,
                        age_seconds=0.0,
                        deleted=False,
                        error=f"stat failed: {exc}",
                    )
                )
                continue
            age = now - mtime
            if age > self.max_age_seconds:
                if dry_run:
                    report.results.append(
                        RetentionResult(path=path, age_seconds=age, deleted=True)
                    )
                else:
                    try:
                        os.remove(path)
                        report.results.append(
                            RetentionResult(path=path, age_seconds=age, deleted=True)
                        )
                    except OSError as exc:
                        report.results.append(
                            RetentionResult(
                                path=path,
                                age_seconds=age,
                                deleted=False,
                                error=f"remove failed: {exc}",
                            )
                        )
            else:
                report.results.append(
                    RetentionResult(path=path, age_seconds=age, deleted=False)
                )
        return report

    def plan(self) -> RetentionReport:
        """Convenience wrapper for a dry run."""
        return self.run(dry_run=True)

    def apply(self) -> RetentionReport:
        """Convenience wrapper for a live run."""
        return self.run(dry_run=False)
