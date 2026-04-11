"""One-shot: copy DB + all subdirs from old project location to new per-user location.

SAFETY REQUIREMENTS:
- The app MUST be closed (no process holding the DB open).
- The DB file itself is copied via sqlite3 VACUUM INTO (atomic, consistent),
  not via shutil — this avoids any WAL/shm ghost-state issues.
- Sub-directories (facturen/, uitgaven/, ...) are copied with shutil.copytree.
"""
import shutil
import sqlite3
import sys
from pathlib import Path
from database import DB_PATH

OLD_DIR = Path(__file__).resolve().parent / "data"
NEW_DIR = DB_PATH.parent
OLD_DB = OLD_DIR / "boekhouding.sqlite3"
NEW_DB = NEW_DIR / "boekhouding.sqlite3"
SUBDIRS = ['facturen', 'uitgaven', 'jaarafsluiting', 'bank_csv', 'aangifte', 'logo']


def _refuse(msg: str) -> None:
    print(f"REFUSING: {msg}", file=sys.stderr)
    sys.exit(1)


def migrate() -> None:
    if OLD_DIR.resolve() == NEW_DIR.resolve():
        print("No migration needed — DB is already at target location.")
        return
    if not OLD_DB.exists():
        print("No old DB found — nothing to migrate.")
        return
    if NEW_DB.exists():
        _refuse(
            f"Target DB already exists at {NEW_DB}. "
            "Back it up and remove manually if you are sure."
        )
    wal = OLD_DIR / "boekhouding.sqlite3-wal"
    if wal.exists() and wal.stat().st_size > 0:
        print("Note: non-empty WAL found, running checkpoint before migration...")
        conn = sqlite3.connect(str(OLD_DB))
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
    # Probe: attempt a write lock to detect a running app holding the DB.
    probe = sqlite3.connect(str(OLD_DB), timeout=1.0)
    try:
        try:
            probe.execute("BEGIN IMMEDIATE")
            probe.execute("ROLLBACK")
        except sqlite3.OperationalError as exc:
            _refuse(
                f"Cannot acquire write lock on {OLD_DB}: {exc}. "
                "Is the app still running? Close it and retry."
            )
    finally:
        probe.close()
    NEW_DIR.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(OLD_DB))
    safe_new_db = str(NEW_DB).replace("'", "''")
    src.execute(f"VACUUM INTO '{safe_new_db}'")
    src.close()
    print(f"DB copied via VACUUM INTO → {NEW_DB}")
    for sub in SUBDIRS:
        old_sub = OLD_DIR / sub
        new_sub = NEW_DIR / sub
        if old_sub.exists() and not new_sub.exists():
            shutil.copytree(old_sub, new_sub)
            print(f"  copied {sub}/")
    print("\nMigration complete. Old directory NOT deleted.")
    print("After verifying the app works, delete the old location:")
    print(f"  rm -rf {OLD_DIR}")


if __name__ == "__main__":
    migrate()
