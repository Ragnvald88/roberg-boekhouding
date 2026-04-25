---
name: codex-review
description: Use proactively after editing or writing any code file (.py, .html, .sql, .css) in the Boekhouding project — required before claiming a code-change task as "klaar"/done. Runs OpenAI Codex CLI as a second-opinion reviewer to catch bugs, SQL filter inconsistencies, year-locking violations, sign convention errors, pdf path resolution issues, NiceGUI pattern regressions, and CLAUDE.md-rule violations. Skip for docs-only changes (.md), comment-only edits, or pure config tweaks.
---

# Codex Auto-Review Skill

Je roept hier OpenAI Codex CLI op als externe reviewer. Codex draait sandbox read-only (kan niets wijzigen) op de huidige diff.

## Wanneer invoke

**Wel:**
- Na Edit/Write op `.py`, `.html`, `.sql`, `.css`, `.js` files in deze repo
- Vóór je een code-change task als "klaar" rapporteert

**Niet:**
- Pure docs-changes (`.md`, `.txt`)
- Comment-only edits
- Config tweaks zonder logic-impact (settings.json, .gitignore)
- Als gebruiker expliciet zegt "skip review" of `SKIP_CODEX_REVIEW=1` is geset
- Op exact dezelfde diff die je in deze sessie al gereviewed hebt

## Stap 1 — pre-flight

```bash
# Kill switch
[ "${SKIP_CODEX_REVIEW:-0}" = "1" ] && echo "SKIP" && exit 0

# Bepaal wat te reviewen: uncommitted eerst, anders laatste commit
cd "$(git rev-parse --show-toplevel)"
DIFF=$(git diff HEAD -- '*.py' '*.html' '*.sql' '*.css' '*.js' 2>/dev/null)
if [ -z "$DIFF" ]; then
  DIFF=$(git show HEAD -- '*.py' '*.html' '*.sql' '*.css' '*.js' 2>/dev/null)
  SOURCE="HEAD commit"
else
  SOURCE="working tree (uncommitted)"
fi

# Skip als <5 regels (te triviaal)
LINES=$(printf '%s\n' "$DIFF" | wc -l | tr -d ' ')
[ "$LINES" -lt 5 ] && echo "Diff te klein ($LINES regels), skip review" && exit 0
```

## Stap 2 — invoke codex

**Belangrijk:** altijd `env -u OPENAI_API_KEY` prefix gebruiken. Dit dwingt subscription-auth (ChatGPT Plus/Pro) en voorkomt dat een per ongeluk geset env-var je API credits opeet.

```bash
printf '%s\n' "$DIFF" | env -u OPENAI_API_KEY codex exec --sandbox read-only "Je krijgt een diff van het Boekhouding project (NiceGUI/Python/SQLite, eenmanszaak huisartswaarnemer). Review specifiek op:

- **Bugs / off-by-one / edge cases** — vooral in datum/jaar-logica, factuur-status-transities, bank-tx koppelingen
- **SQL-filter consistency** — \`status='concept'\` exclusions in revenue queries; sign conventions (\`bedrag < 0\` voor debits)
- **Year-locking schendingen** — mutaties op definitieve jaren zonder \`assert_year_writable\` (gespecificeerd in CLAUDE.md K6)
- **PDF path resolution** — alle row-menu actions moeten via \`_ensure_factuur_pdf\`; geen directe \`pdf_pad\` reads
- **NiceGUI patterns** — \`q-btn-dropdown\` + \`\$parent.\$emit\` werkt NIET (teleport bug); \`ui.upload\` events moeten \`await e.file.read()\`; blocking I/O in \`asyncio.to_thread\`
- **Tests die mogelijk breken** — als je test_*.py imports of fixtures herkent

Wees terse: alleen concrete bevindingen, met file:regel context als beschikbaar. MAX 5 bullets. Geen 'wat doet de code'-samenvatting, geen style-nits, geen voorgestelde refactors.

Als alles OK: antwoord exact 'GEEN BEVINDINGEN'."
```

Bash tool timeout: 120s (codex review duurt typisch 30-90s afhankelijk van diff-grootte).

## Stap 3 — verwerken van de output

Codex output is **input voor jouw oordeel, geen verdict.** Volg `superpowers:receiving-code-review` principes:

1. **Lees alle bevindingen.**
2. **Per bevinding evalueer technisch:**
   - Klopt het? Verifieer in de code (Read of Grep).
   - Is het een echte bug of een hallucinatie / verouderde aanname?
   - Past de impliciete fix bij codebase-conventies (CLAUDE.md regels)?
3. **Rapporteer aan user** in tabel-vorm:

   | Bevinding | Mijn oordeel | Voorgestelde actie |
   |---|---|---|
   | (codex citaat, kort) | klopt / nuance / hallucinatie + reden | fix nu / fix later / negeer |

4. **Wacht op user-instructie** voor je iets uitvoert. NIET automatisch fixes implementeren.

## Wat NIET te doen

- ❌ Niet automatisch implementeren wat codex voorstelt
- ❌ "GEEN BEVINDINGEN" interpreteren als gegarandeerd-bug-vrij (codex mist soms dingen)
- ❌ Meerdere keren in zelfde sessie op identieke diff runnen (verspilt subscription quota)
- ❌ De `env -u OPENAI_API_KEY` prefix vergeten (kan API credits opeten als var ooit terugkomt)
- ❌ Skill invoken voor pure docs/comment changes (waste of time + tokens)

## Failure modes

- **`codex: command not found`** → user heeft codex CLI niet geïnstalleerd; rapporteer en stop.
- **Authentication error** → user moet handmatig `codex login` doen (interactieve flow, kun je niet vanaf hier).
- **Timeout** → diff was waarschijnlijk te groot. Probeer opnieuw met enkel staged changes (`git diff --cached`) of een specifieke file.
- **Non-fatal `failed to record rollout items` ERROR-regel** → bekend Codex 0.125.0 logging-bug, antwoord zelf is correct ontvangen. Negeer.
