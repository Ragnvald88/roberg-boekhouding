"""One-shot: export current klant_aliases to JSON snapshot.

This snapshot becomes the recovery source for migration 34's JSON-fallback
path, so that even after `klant_mapping_local.py` is deleted a future
DB-restore-from-old-backup can still seed klant_aliases.
"""

import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _config_dir() -> Path:
    override = os.environ.get('BOEKHOUDING_CONFIG_DIR')
    if override:
        return Path(override)
    return (Path.home() / 'Library' / 'Application Support'
            / 'Boekhouding' / 'config')


def main() -> int:
    db = (Path.home() / 'Library' / 'Application Support'
          / 'Boekhouding' / 'data' / 'boekhouding.sqlite3')
    if not db.exists():
        print(f'❌ DB not found at {db}')
        return 2
    conn = sqlite3.connect(db)
    rows = conn.execute("""
        SELECT k.naam AS klant_naam, a.type AS type, a.pattern AS pattern
        FROM klant_aliases a JOIN klanten k ON k.id = a.klant_id
        ORDER BY a.type, a.pattern
    """).fetchall()
    conn.close()

    out_dir = _config_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot = [{'klant_naam': r[0], 'type': r[1], 'pattern': r[2]}
                for r in rows]
    out = out_dir / 'klant_aliases_backup.json'
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2),
                   encoding='utf-8')
    print(f'✅ Exported {len(snapshot)} aliases to {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
