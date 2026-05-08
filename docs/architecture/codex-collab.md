# Codex-samenwerking als kwaliteitsstandaard

**Gouden regel**: voor elke niet-triviale wijziging is Codex een zelfstandige second opinion, GEEN rubber stamp. Sprint A→F bewees: 6 echte bugs gevangen die de single-agent pipeline gemist had.

| # | Bug | Waar gevangen |
|---|---|---|
| 1 | T2 `.text-h1..h6 color: var(--text)` overruled `.text-white` in donkere header | Codex T2 review |
| 2 | T6 `.q-btn { 8px }` overruled `q-btn--round` modifier | Codex T6 review |
| 3 | T6 `.builder-line-card` cascade-shadow regression | Code-quality reviewer T6 |
| 4 | Sprint A holiday/blocker-marker fills cascade-volgorde | Codex post-merge audit |
| 5 | D3 `klant.color` round-trip bug | Codex D3 review |
| 6 | F `.alert-link/.severity-fg` cascade — Quasar defaults wonnen | Codex Sprint F review |

## 4-layer review pattern (verplicht voor non-trivial werk)

```
implementer subagent (opus) → spec reviewer (opus) → Codex CLI → code-quality reviewer (opus)
        |                          |                     |               |
        └─ doet werk + zelf-codex  ├─ "matcht spec?"   ├─ second-opinion ├─ "is het mooi?"
                                   └─ catched scope-creep
                                                       ├─ catched cascade
                                                       ├─ catched bugs
                                                       └─ catched typos
```

## Concrete praktijk-richtlijnen

1. **Per sprint-task subagent-driven**: gebruik `superpowers:subagent-driven-development`. Per task: implementer + spec reviewer + Codex + code-quality. Geen task "klaar" zonder alle 4.

2. **Codex CLI direct via Bash voor architectuur-vragen**: bij design-keuzes (token-keuze, schema-design, scope-decisie), invoke Codex via `env -u OPENAI_API_KEY codex exec --sandbox read-only "..."` met je voorstel + jouw advies. Codex denkt zelfstandig — neemt soms je voorkeur over, soms niet.

3. **Bevindingen evalueren, niet blind overnemen**: Codex hallucineert soms. Apply `superpowers:receiving-code-review` — verifieer in code voor je het accepteert.

4. **Plan-amendments bij real bugs**: als Codex een bug catched die in een eerdere stap al was gepland, **back-annotate de plan-doc** met `> Plan-amendment YYYY-MM-DD (na Codex review): ... niet herintroduceren bij re-run.` — voorkomt dat re-runs dezelfde bug terugbrengen.

5. **Post-merge audit ronde**: na een grote sprint (10+ commits), draai een **combined post-merge audit**: code-reviewer agent + Codex CLI parallel op de volledige diff. Sprint B post-merge audit ving 6 bevindingen die de per-task pipeline gemist had. Sprint A→F post-audit ving er nog 7. Dit patroon vindt cumulative inconsistencies die per-task niet zien.

6. **Atomic-paren bij gekoppelde changes**: bv. T1 (token-blok + body inline-style fix samen) en T7 (font-family rewrite alle 7 classes + CDN-link removal samen). Tussentijdse half-state = silent regression. Documenteer in commit-message als `ATOMIC: ...`.

7. **Cascade-discipline test enforced**: `tests/test_visual_css.py` + 4 specifieke regels. ALTIJD `.q-*` overrides + app-classes-op-Quasar-elementen BUITEN `@layer components`. Zie `docs/architecture/visual-css.md`.

## Codex CLI invocation

- Subscription auth (ChatGPT Plus/Pro): altijd prefix met `env -u OPENAI_API_KEY` om te voorkomen dat een per ongeluk geset env-var je API credits opeet.
- Sandbox read-only: `--sandbox read-only` — Codex kan niets wijzigen.
- Skip voor pure docs/comment changes. Kill switch: `SKIP_CODEX_REVIEW=1`.
- Codex `project_doc_max_bytes` default = 32 KiB. Bump in `.codex/config.toml` (huidige waarde: 65536) of split content naar `docs/architecture/`.

## Symmetrische hooks (cross-vendor review-coverage)

Twee Stop hooks in `.codex/hooks.json`:

1. **`quality-gate.sh`** — Claude Code Stop hook. Bij `.py|.html|.sql|.css|.js` changes: runt pytest, blokkeert finish bij failures (exit 2). Deterministische test-discipline.
2. **`codex-claude-review.sh`** — Codex Stop hook (symmetric). Bij dezelfde file-extensies: pipet de diff door `claude -p` headless. Print findings als info (exit 0 — Claude's review is opinion, geen ground truth). Kill switch: `SKIP_CLAUDE_REVIEW=1`.

Resultaat: élke code-change wordt door BOTH agents gezien, ongeacht welke je direct aanstuurt. Claude calls Codex via de `codex-review` skill; Codex calls Claude via de Stop hook.

**Niet** een MCP broker (Delega/OpenAI Codex MCP plugin): die kosten ofwel API tokens (jouw setup gebruikt ChatGPT subscription = gratis) ofwel routen private fiscal-data diffs door derden. Bash-subprocess pattern is goedkoper en even hoge review-kwaliteit (kwaliteit komt uit model-onafhankelijkheid, niet transport).
