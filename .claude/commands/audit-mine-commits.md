---
description: Mine fix/revert/perf commits to produce docs/FIX_PATTERNS.md — a reusable defect taxonomy for this repo.
argument-hint: "[--refresh]"
model: opus
---

Bouw (of ververs) `docs/FIX_PATTERNS.md` — een korte, reviewbare defect-taxonomie op basis van deze repo's eigen historie. Dit artefact wordt door `/audit-scan` gebruikt; bouw het éénmalig zodat die runs goedkoop blijven.

## Precondities
- Als `docs/FIX_PATTERNS.md` bestaat en `$ARGUMENTS` bevat geen `--refresh`: stop, toon path en zeg "gebruik `/audit-mine-commits --refresh` om opnieuw te minen".
- Anders: door naar minen.

## Stappen

1. Enumereer kandidaten:
   ```bash
   git log --pretty=format:'%h %s' -500 | grep -E '^[a-f0-9]+ (fix|revert|perf)'
   ```
   Cap op maximaal **30 commits** — sample representatief over scopes (facturen, fiscal, bank, instellingen, year-lock, safety, launcher, facturen-mail, werkdagen). Ongescopede `fix:` commits: neem er 5–8 mee.

2. Voor elke gesamplede commit:
   ```bash
   git show --stat <hash>
   git show <hash> -- <top 1–2 changed files>
   ```
   Lees de diff, destilleer de *bug-klasse*. Niet de specifieke bug.

3. Clusteren: groepeer commits met dezelfde onderliggende klasse. Doel: **8–12 klassen**, niet meer. Als een klasse maar één commit heeft, weglaten óf samenvoegen met verwante klasse.

4. Schrijf `docs/FIX_PATTERNS.md` met exact dit schema per klasse:

   ```markdown
   ## <klasse-id-kebab-case> — <korte naam>

   **Samenvatting**: één zin wat er fout gaat.

   **CLAUDE.md regel**: citeer de regel die dit voorkomt (of "geen expliciete regel — kandidaat voor toevoeging").

   **Voorbeelden** (3–5 commits, meest recent eerst):
   - `<hash>` <subject>

   **Hoe in HEAD te detecteren**:
   - Grep: `<regex of patroon>`
   - Glob scope: `<pad/glob>`
   - Handmatige check: <wat niet via grep gaat>
   ```

5. Eind-secties:
   - **Feature-trends**: welke soorten `feat:` commits zijn er geweest (UX-polish, guards, health-alerts, pre-flight checks, category suggestions)? Eén alinea. Doel: bij `/audit-scan` kan hieruit een "waar meer van hetzelfde zou helpen"-lijst komen.
   - **Meta**: aantal gesamplede commits, datum-range, git-hash HEAD bij generatie.

## Guardrails

- **Geen speculatie**: een klasse bestaat alleen als er ≥ 2 commits onder vallen, of 1 met hoge impact.
- **Blijf kort**: doel is ~150–250 regels totaal. Als het langer wordt: consolideer klassen.
- **Geen fixes schrijven** — dit command produceert alléén het taxonomie-bestand.
- Als `docs/FIX_PATTERNS.md` al bestaat en je runt met `--refresh`: overschrijven mag, maar noem in de Meta-sectie "vervangt eerdere versie van <datum>".
