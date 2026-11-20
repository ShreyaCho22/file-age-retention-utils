import os
import tempfile
import unittest
from pathlib import Path

from file_age_retention_utils import FileAgeRetention, RetentionReport, RetentionResult


class FakeClock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class FileAgeRetentionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.clock = FakeClock(1_000_000.0)

    def _write(self, name: str, mtime: float) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("data", encoding="utf-8")
        os.utime(path, (mtime, mtime))
        return path

    def test_dry_run_marks_old_files_without_removing_them(self) -> None:
        old = self._write("old.txt", self.clock.value - 100)
        fresh = self._write("fresh.txt", self.clock.value - 10)
        retention = FileAgeRetention(self.root, 50, clock=self.clock)

        report = retention.run(dry_run=True)

        self.assertIsInstance(report, RetentionReport)
        self.assertTrue(report.dry_run)
        self.assertEqual(report.scanned, 2)
        self.assertEqual(report.deleted, 1)
        self.assertEqual(report.skipped, 1)
        self.assertEqual(report.errors, 0)
        self.assertTrue(old.exists())
        self.assertTrue(fresh.exists())
        by_path = {r.path: r for r in report.results}
        self.assertTrue(by_path[str(old)].deleted)
        self.assertFalse(by_path[str(fresh)].deleted)

    def test_live_run_removes_old_files_and_keeps_fresh_ones(self) -> None:
        old = self._write("old.txt", self.clock.value - 100)
        fresh = self._write("fresh.txt", self.clock.value - 10)
        retention = FileAgeRetention(self.root, 50, clock=self.clock)

        report = retention.run(dry_run=False)

        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())
        self.assertEqual(report.deleted, 1)
        self.assertEqual(report.skipped, 1)
        self.assertFalse(report.dry_run)

    def test_boundary_age_is_kept(self) -> None:
        # Exactly at the threshold is not "older than", so it must survive.
        exact = self._write("exact.txt", self.clock.value - 50)
        retention = FileAgeRetention(self.root, 50, clock=self.clock)

        report = retention.run(dry_run=True)

        self.assertTrue(exact.exists())
        self.assertEqual(report.deleted, 0)
        self.assertEqual(report.skipped, 1)

    def test_one_second_past_boundary_is_deleted(self) -> None:
        past = self._write("past.txt", self.clock.value - 51)
        retention = FileAgeRetention(self.root, 50, clock=self.clock)

        report = retention.run(dry_run=True)

        self.assertEqual(report.deleted, 1)
        self.assertTrue(past.exists())

    def test_recursive_scan_covers_subdirectories(self) -> None:
        nested = self._write("a/b/old.txt", self.clock.value - 100)
        retention = FileAgeRetention(self.root, 50, recursive=True, clock=self.clock)

        report = retention.run(dry_run=True)

        self.assertIn(str(nested), [r.path for r in report.results])
        self.assertEqual(report.deleted, 1)

    def test_non_recursive_scan_ignores_subdirectories(self) -> None:
        top = self._write("top.txt", self.clock.value - 100)
        nested = self._write("a/b/old.txt", self.clock.value - 100)
        retention = FileAgeRetention(self.root, 50, recursive=False, clock=self.clock)

        report = retention.run(dry_run=True)

        paths = [r.path for r in report.results]
        self.assertIn(str(top), paths)
        self.assertNotIn(str(nested), paths)

    def test_missing_directory_yields_empty_report(self) -> None:
        retention = FileAgeRetention(self.root / "nope", 50, clock=self.clock)

        report = retention.run(dry_run=True)

        self.assertEqual(report.scanned, 0)
        self.assertEqual(report.deleted, 0)
        self.assertEqual(report.results, [])

    def test_plan_and_apply_wrappers(self) -> None:
        old = self._write("old.txt", self.clock.value - 100)
        retention = FileAgeRetention(self.root, 50, clock=self.clock)

        plan = retention.plan()
        self.assertTrue(plan.dry_run)
        self.assertTrue(old.exists())

        applied = retention.apply()
        self.assertFalse(applied.dry_run)
        self.assertFalse(old.exists())

    def test_report_summary_is_stable(self) -> None:
        self._write("old.txt", self.clock.value - 100)
        self._write("fresh.txt", self.clock.value - 10)
        retention = FileAgeRetention(self.root, 50, clock=self.clock)

        report = retention.run(dry_run=True)

        self.assertEqual(report.summary(), "dry-run: scanned=2 deleted=1 skipped=1 errors=0")

    def test_negative_max_age_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            FileAgeRetention(self.root, -1, clock=self.clock)

    def test_retention_result_is_frozen(self) -> None:
        result = RetentionResult(path="/x", age_seconds=1.0, deleted=False)
        with self.assertRaises(Exception):
            result.path = "/y"  # type: ignore[misc]

    def test_zero_max_age_deletes_any_positive_age(self) -> None:
        old = self._write("old.txt", self.clock.value - 1)
        retention = FileAgeRetention(self.root, 0, clock=self.clock)

        report = retention.run(dry_run=True)

        self.assertEqual(report.deleted, 1)
        self.assertTrue(old.exists())

    def test_symlinked_file_is_skipped(self) -> None:
        target = self._write("target.txt", self.clock.value - 100)
        link = self.root / "link.txt"
        link.symlink_to(target)
        retention = FileAgeRetention(self.root, 50, clock=self.clock)

        report = retention.run(dry_run=True)

        paths = [r.path for r in report.results]
        self.assertIn(str(target), paths)
        self.assertNotIn(str(link), paths)


if __name__ == "__main__":
    unittest.main()
