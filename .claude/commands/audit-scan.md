---
description: Scan HEAD tegen docs/FIX_PATTERNS.md — produceer prioriteerde bevindingen. Optioneel scope: /audit-scan fiscal
argument-hint: "[domein?]"
model: opus
---

Read-only audit van de huidige codebase met `docs/FIX_PATTERNS.md` als checklist. Geen fixes — alléén bevindingen met `file:line` + mapping naar een taxonomie-klasse.

## Precondities

1. `docs/FIX_PATTERNS.md` moet bestaan. Anders: stop en zeg "run eerst `/audit-mine-commits`".
2. Schakel **Plan Mode** in (EnterPlanMode). Dit is read-only.
3. Als `$ARGUMENTS` niet leeg is, beperk scope tot dat domein (bv. `fiscal`, `facturen`, `bank`, `werkdagen`, `async`). Anders: full scan.

## Context laden (sequentieel, main thread)

Lees: `CLAUDE.md`, `PRODUCT_FLOWS.md`, `MEMORY.md`, `docs/plans/*.md`, `docs/FIX_PATTERNS.md`.

Belangrijk: items die al in `docs/plans/` staan worden **niet** opnieuw als bevinding gerapporteerd — alleen genoteerd als "reeds gepland".

## Scan (parallelle opus-subagents, max 4)

Dispatch via `superpowers:dispatching-parallel-agents`. Kies clusters zodat er geen overlap is:

- **Cluster A — Data & berekeningen**: `fiscal/`, `database.py` queries, `pages/aangifte.py`, `pages/jaarafsluiting.py`. Focus: taxonomie-klassen rond silent fallbacks, hardcoded fiscale waarden, snapshot/live-read mismatches, year-lock gaps op mutatiepunten.
- **Cluster B — Facturen & werkdagen**: `pages/facturen.py`, `pages/werkdagen.py`, `components/invoice_*.py`, `templates/factuur.html`. Focus: status-lifecycle, PDF-pad resolutie, concept-exclusie, edit-guards, km_tarief=0 ANW.
- **Cluster C — Integraties & I/O**: `pages/bank.py`, mail helpers, imports, launcher, `main.py`. Focus: matching-confidence, blocking I/O zonder `asyncio.to_thread`, safety (quote-escape, atomic writes, port/process handling).
- **Cluster D — Dode code & feature-gaps**: hele codebase cross-referentie. Functies zonder callers, unused imports, UI-events zonder handler en vice versa. Plus: `PRODUCT_FLOWS.md` ↔ code diff, en de *feature-trends* uit FIX_PATTERNS.md → waar ontbreekt een equivalent?

Elk subagent ontvangt: (a) `docs/FIX_PATTERNS.md`, (b) zijn scope, (c) instructie **elke bevinding → file:line + taxonomie-klasse-id + korte evidence-snippet**. Rapport ≤ 400 woorden per subagent.

## Verificatie (main thread)

1. Voor elke bevinding: open het genoemde bestand, bevestig de regel bestaat en zegt wat de subagent claimt. Niet-verifieerbaar → schrappen.
2. Kruisreferentie met `docs/plans/` — reeds gepland? Verplaats naar "Reeds gepland"-sectie.
3. Optioneel (als sqlite MCP beschikbaar): voor data-claims ("er staan concept-facturen in de omzet-query") — query de echte DB via het `sqlite` MCP-server om het cijfer te bevestigen.
4. Draai de tests:
   ```bash
   DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ --tb=short -q
   ```
   Een falende test gealigneerd met een bevinding → directe **Kritiek**.

## Output formaat

Gebruik exact deze headers, gematcht met `full-code-review.md`:

### KRITIEK
Per item: `file:line` — wat is fout — **klasse**: `<taxonomie-id>` — **bewijs**: code-snippet of grep — **historisch precedent**: `<hash>`.

### BELANGRIJK
Zelfde vorm.

### MINOR
Eén-regel items.

### DODE CODE
`file:line name — callers: geen (verified via grep)`.

### FEATURE-GAPS
Twee subsecties:
1. *Uit PRODUCT_FLOWS.md*: flows niet/anders geïmplementeerd.
2. *Uit feature-trends*: waar zou meer van bestaande patronen helpen (bv. health-alert-equivalent op andere pagina's, pre-flight check op andere mutaties).

### REEDS GEPLAND
Lijst: bevinding → plan-bestand in `docs/plans/`.

### STERKTES
Specifieke voorbeelden, geen generieke lof.

### ARCHITECTUUR-OORDEEL
Eén paragraaf: grootste structurele risico nu, in relatie tot de taxonomie.

## Guardrails

- **Geen code-wijzigingen**. Als gebruiker fixes wil: suggereer follow-up met `superpowers:writing-plans` + `superpowers:test-driven-development` tegen de Kritiek-lijst.
- **Bewijs of schrappen** — geen bevinding zonder file:line + klasse-id.
- **Respecteer Plan Mode** tot de gebruiker expliciet exit.
