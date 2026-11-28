# file-age-retention-utils

Scan a directory (recursively by default) and delete regular files whose age exceeds a threshold, with a dry-run mode and a per-file report.

```python
from file_age_retention_utils import FileAgeRetention

retention = FileAgeRetention("/var/tmp/reports", max_age_seconds=7 * 24 * 3600)
print(retention.plan().summary())   # dry-run: scanned=42 deleted=3 skipped=39 errors=0
report = retention.apply()         # actually removes the old files
for result in report.results:
    if result.deleted:
        print("removed", result.path)
```

## Why this exists

Cron jobs that clean up spool directories usually reimplement the same loop: walk a tree, stat every file, compare against a cutoff, and delete. The tricky parts are not the deletion itself but the boundary condition and the testability of the cutoff. This library makes the cutoff explicit (`age > max_age_seconds`, so a file exactly at the threshold is kept) and accepts a clock callable, so a test can pin "now" without sleeping or mocking the filesystem.

The trade-off: the scanner is deliberately conservative. Symlinks are skipped rather than followed, because following them can delete files outside the configured directory, and that is a worse failure than missing a symlinked file. The report is a flat list of `RetentionResult` objects rather than a callback interface, which keeps the API small but means very large trees hold one small object per file in memory.

## Awkward edge

`age > max_age_seconds` is strict. A file whose mtime is exactly `now - max_age_seconds` is kept. If your cutoff is "delete anything at or past seven days", pass a threshold one second less than you mean, or check the boundary test in `tests/test_core.py` and decide deliberately.

## API

- `FileAgeRetention(directory, max_age_seconds, *, recursive=True, clock=None)`
  - `run(dry_run=False) -> RetentionReport`
  - `plan() -> RetentionReport` (dry run)
  - `apply() -> RetentionReport` (live run)
- `RetentionReport` with `results`, `dry_run`, `scanned`, `deleted`, `skipped`, `errors`, `summary()`
- `RetentionResult` with `path`, `age_seconds`, `deleted`, `error`

`max_age_seconds` must be non-negative; a negative value raises `ValueError`. A missing directory produces an empty report rather than an error.

## Performance

The window keeps a bounded buffer, so `push` is constant time and memory does not
grow with the length of the stream. `peak` and `trough` are linear in the window
size, which is the trade that keeps `push` cheap.

## Design notes

The window stores values eagerly rather than keeping running aggregates. Running
sums drift with floating point over long streams, and recomputing from a small
buffer is cheap enough that the drift is not worth the speed.

