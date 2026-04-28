"""One-shot: verify no personal-info or customer-name tokens are present
in tracked files. Use before flipping repo to public."""

import sqlite3
import pathlib
import subprocess
import sys

DB = pathlib.Path.home() / 'Library/Application Support/Boekhouding/data/boekhouding.sqlite3'

CITY_ALLOWLIST = {
    'Groningen', 'Zuidhorn', 'Stadskanaal', 'Delfzijl', 'Scheemda',
    'Assen', 'Hoogeveen', 'Emmen', 'Vlagtwedde', 'Marum', 'Winsum',
    'Smilde', 'Sellingen', 'Wilp', 'Drenthe',
}
GENERIC_ALLOWLIST = {
    'Huisarts', 'Huisartsen', 'Huisartsenpraktijk', 'Huisartspraktijk',
    'Huisartswaarnemer', 'HAP', 'Centrum', 'Praktijk', 'Spoedpost',
    'Doktersdienst', 'Dokter', 'Test', 'TestBV',
}


def main() -> int:
    if not DB.exists():
        print(f'❌ DB not found at {DB}')
        return 2
    conn = sqlite3.connect(DB)
    full_tokens: set[str] = set()
    for r in conn.execute('SELECT naam FROM klanten'):
        if r[0]:
            full_tokens.add(r[0])
    bg_row = conn.execute(
        'SELECT naam, bedrijfsnaam, adres, postcode_plaats, telefoon, email, kvk, iban '
        'FROM bedrijfsgegevens'
    ).fetchone() or ()
    for t in bg_row:
        if t and len(str(t)) >= 4:
            full_tokens.add(str(t))

    fragment_tokens: set[str] = set()
    for r in conn.execute('SELECT naam FROM klanten'):
        if not r[0]:
            continue
        for part in r[0].replace('.', ' ').split():
            if (len(part) >= 4 and part[0].isupper()
                and part not in CITY_ALLOWLIST
                and part not in GENERIC_ALLOWLIST):
                fragment_tokens.add(part)

    leaks = []
    for token in sorted(full_tokens | fragment_tokens):
        result = subprocess.run(
            ['git', 'grep', '-l', '-F', token],
            capture_output=True, text=True)
        if not result.stdout.strip():
            continue
        for path in result.stdout.strip().split('\n'):
            if 'verify_public_safe' in path or 'audit_missing_locaties' in path:
                continue
            ctx = subprocess.run(
                ['git', 'grep', '-n', '-F', token, path],
                capture_output=True, text=True).stdout.strip().split('\n')[0]
            leaks.append((token, path, ctx))

    if leaks:
        print(f'❌ {len(leaks)} potential leaks (review context):')
        for token, path, ctx in leaks:
            print(f'  [{token}] {ctx}')
        return 1
    print('✅ public-safe: 0 leaks')
    return 0


if __name__ == '__main__':
    sys.exit(main())
