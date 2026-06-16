from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import datetime

ET = ZoneInfo("America/New_York")

@dataclass(frozen=True)
class PMOPaths:
    pmo_dir: Path
    pmo_root: Path
    csv_dir: Path
    report_dir: Path
    pine_dir: Path
    runtime_log_dir: Path
    storage_db: Path

    def ensure(self) -> "PMOPaths":
        for path in (self.csv_dir, self.report_dir, self.pine_dir, self.runtime_log_dir):
            path.mkdir(parents=True, exist_ok=True)
        return self


def build_paths(file: str | Path) -> PMOPaths:
    pmo_dir = Path(file).resolve().parent
    pmo_root = pmo_dir.parent if pmo_dir.name.lower() == "python" else pmo_dir
    return PMOPaths(
        pmo_dir=pmo_dir,
        pmo_root=pmo_root,
        csv_dir=pmo_dir / "pmo_csv",
        report_dir=pmo_dir / "pmo_reports",
        pine_dir=pmo_dir / "pmo_pinescript",
        runtime_log_dir=pmo_dir / "pmo_runtime_logs",
        storage_db=pmo_dir / "pmo_storage.sqlite3",
    ).ensure()


def now_et() -> datetime:
    return datetime.now(ET)
