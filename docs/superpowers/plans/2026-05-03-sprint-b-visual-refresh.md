# Sprint B — Visual Refresh Implementation Plan

> **🚫 SHIPPED — historisch plan.** Volledig uitgevoerd en gemerged naar
> `master` via merge-commit `7d1d14e` op 2026-05-03. Subagent-driven met
> 4-layer review (implementer→spec→codex→code-quality) per task. Codex
> catched 2 echte bugs onderweg (T2 heading-color, T6 q-btn--round) —
> beide gefixt + plan back-annotated. T11-T17/T18 user-smoke deferred.
> Voor lessons learned: zie auto-memory `project_visual_refresh.md` en
> CLAUDE.md § Visuele tokens.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apple-stijl visual refresh consistent doortrekken over de Boekhouding-app conform `docs/superpowers/specs/2026-05-03-sprint-b-visual-refresh-design.md`.

**Architecture:** Single CSS-laag in `components/layout.py` met 9-token systeem. Quasar `.q-*` overrides BUITEN `@layer components` (cascade-order). System-font stack + SF Mono. Tier 1 (chrome global, 8 atomic commits) → user-acceptatie gate → Tier 2 (per page smoke + minimal) → Tier 3 spot-check.

**Tech Stack:** NiceGUI ≥3.0 + Quasar/Vue, native pywebview macOS. CSS-only changes (geen DB/services/business-logic). Bestaande pytest-suite (~1261 tests) blijft groen baseline.

**Verifiable Spec Claims** (gemeten 2026-05-03):
- Baseline tests: 1261 (zal pre-flight herijkt worden)
- 6 huidige Quasar overrides in `@layer components`: `.q-table th` (regel 16), `.q-table tbody tr:nth-child(even)` (24), `.page-toolbar .q-field` (37), `.page-toolbar .q-field--outlined .q-field__control` (40,47,50), `.page-toolbar .q-field__label` (54)
- 7 classes met `'JetBrains Mono'` font-family: `.num`, `.mono`, `.chip`, `.seg-btn`, `.selection-bar .sb-count`, `.selection-bar .sb-meta`, `.page-sub`
- Body inline-style: `layout.py:331` (`ui.query('body').style('background-color: #F8FAFC')`)
- Google Fonts CDN-link: `layout.py:286-290`
- `pages/bank.py`: 13 regels, broken client-side redirect (Codex-verified)
- `/bank` references buiten `pages/bank.py`: 1 (`main.py:33` import)

---

## File Structure

**Modified:**
- `components/layout.py` — alle Tier 1 wijzigingen (tokens, chrome, Quasar overrides, font-family, CDN removal)
- `main.py:33` — verwijder `import pages.bank`
- (mogelijk) `pages/dashboard.py`, `pages/werkdagen.py`, etc. — alleen als Tier 2-smoke een token-pickup-opportunity blootlegt

**Removed:**
- `pages/bank.py` — volledig schrappen

**Created:**
- (geen — visueel-only sprint)

---

## Task 0: Pre-flight setup

**Doel:** Baseline-meting + feature branch aanmaken zodat alles rollback-baar is.

- [ ] **Step 1: Verifieer working tree clean en op master**

Run:
```bash
git status
git rev-parse --abbrev-ref HEAD
```
Expected: working tree clean, branch `master`.

- [ ] **Step 2: Maak feature-branch**

Run:
```bash
git checkout -b feature/sprint-b-visual-refresh
```

- [ ] **Step 3: Meet pytest-baseline**

Run:
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ --collect-only -q | tail -1
```
Expected: `1261 tests collected in <X>s`. Noteer count als T0-baseline.

- [ ] **Step 4: Run pytest baseline (groene start)**

Run:
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q 2>&1 | tail -5
```
Expected: `1261 passed in <X>s` (of de actuele T0-count). Als rood: stop, fix eerst.

- [ ] **Step 5: Commit branch-start marker**

Run:
```bash
git commit --allow-empty -m "chore(sprint-b): baseline T0 = 1261 tests groen — begin feature/sprint-b-visual-refresh"
```

---

## Task 1: Token-blok + body inline-style fix (ATOMIC)

**Doel:** 9 design-tokens introduceren als CSS custom properties bovenin het bestaande `ui.add_css(...)` blok, EN tegelijk de inline body-style op `layout.py:331` neutraliseren zodat de token-waarde wint.

**Files:**
- Modify: `components/layout.py:13` (begin van `ui.add_css(...)` blok)
- Modify: `components/layout.py:331` (inline body-style)

- [ ] **Step 1: Lees huidige `ui.add_css` openings-context**

Run:
```bash
sed -n '13,20p' components/layout.py
```
Verwacht: regel 13 begint met `ui.add_css('''` en regel 14 met `@layer components {`.

- [ ] **Step 2: Voeg token-blok toe vóór `@layer components {`**

Edit `components/layout.py`. Vervang:
```python
ui.add_css('''
@layer components {
    /* Table header styling */
```
Door:
```python
ui.add_css('''
/* === TOKENS (Sprint B) === */
:root {
    --bg: #F5F5F7;            /* page background — system gray */
    --surface: #FFFFFF;        /* cards, dialogs, header */
    --border: rgba(60,60,67,0.12);
    --text: #1C1C1E;           /* primary ink */
    --muted: #6E6E73;          /* secondary ink, labels, captions */
    --accent: #0F766E;         /* teal brand — unchanged */
    --accent-soft: rgba(15,118,110,0.10);
    --shadow: 0 2px 8px rgba(0,0,0,0.06);
    --radius: 12px;
}

/* === BASE === */
body {
    background: var(--bg);
}

@layer components {
    /* Table header styling */
```

- [ ] **Step 3: Vervang inline body-style om token te respecteren**

Edit `components/layout.py:331`. Vervang:
```python
    # Off-white page background
    ui.query('body').style('background-color: #F8FAFC')
```
Door:
```python
    # Background komt nu uit CSS-token --bg (zie ui.add_css blok bovenin).
    # Inline-style hier zou CSS overrulen — daarom weggehaald in Sprint B.
```

- [ ] **Step 4: Verifieer pytest blijft groen**

Run:
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q 2>&1 | tail -5
```
Expected: `1261 passed`.

- [ ] **Step 5: Commit**

Run:
```bash
git add components/layout.py
git commit -m "$(cat <<'EOF'
feat(sprint-b): voeg 9-token CSS design system toe + neutraliseer body inline-style

Atomic: nieuwe :root tokens-blok plus body { background: var(--bg) } CSS rule
moeten samen met de removal van ui.query('body').style('background-color: ...')
op layout.py:331 — anders wint inline van CSS-token (Codex review punt 2).

Tokens: --bg --surface --border --text --muted --accent --accent-soft
        --shadow --radius

Body achtergrond zal nu visueel licht-grijs (#F5F5F7) zijn ipv slate-50
(#F8FAFC). Verschil is subtiel — Apple system gray vs Tailwind slate-50.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: System font-stack op body + headings

**Doel:** Roboto vervangen door `-apple-system` system stack zodat macOS zelf SF Pro Text/Display kiest.

**Files:**
- Modify: `components/layout.py` — uitbreiding van `/* === BASE === */` blok uit Task 1

- [ ] **Step 1: Lees huidige BASE-blok**

Run:
```bash
sed -n '26,32p' components/layout.py
```
Verwacht: een blok beginnend met `/* === BASE === */` en `body { background: var(--bg); }`.

- [ ] **Step 2: Voeg font-family toe aan body + headings**

Edit `components/layout.py`. Vervang:
```css
/* === BASE === */
body {
    background: var(--bg);
}
```
Door:
```css
/* === BASE === */
body {
    background: var(--bg);
    font-family: -apple-system, "SF Pro Text", system-ui, sans-serif;
    color: var(--text);
}
.q-page {
    font-family: -apple-system, "SF Pro Text", system-ui, sans-serif;
}
.text-h1, .text-h2, .text-h3, .text-h4, .text-h5, .text-h6 {
    font-family: -apple-system, "SF Pro Display", system-ui, sans-serif;
    /* Geen color hier — body's color: var(--text) erft via inheritance.
       Een eigen color zou Quasar utility classes (.text-white in donkere
       header, .text-primary elders) overrulen via gelijke specificity. */
}
```

> **Plan-amendment 2026-05-03 (na Codex T2 review)**: oorspronkelijke
> Step 2 had `color: var(--text)` op `.text-h1..h6` — verwijderd in
> commit `36d63d2`. Reden: zou Quasar utilities (`.text-white`,
> `.text-primary`) overrulen via gelijke specificity. Body's color
> erft naar headings via inheritance, en utility classes winnen via
> directe element-class-selector. Niet herintroduceren bij re-run.

- [ ] **Step 3: Verifieer pytest blijft groen**

Run:
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q 2>&1 | tail -5
```
Expected: `1261 passed`.

- [ ] **Step 4: Commit**

Run:
```bash
git add components/layout.py
git commit -m "$(cat <<'EOF'
feat(sprint-b): system font-stack — -apple-system voor body+headings

macOS-only app, dus geen webfonts nodig — system stack laat macOS zelf
SF Pro Text (body) en SF Pro Display (headings) kiezen. Geen rounded
(Codex review: rounded is voor casual apps zoals Calendar, financial
app moet rustig voelen).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Migreer 6 Quasar `.q-*` overrides naar buiten `@layer components`

**Doel:** Alle 6 huidige `.q-*` regels die binnen `@layer components` staan verhuizen naar boven `@layer components { ... }` met **identieke styling**. Cascade-order: unlayered styles winnen van layered (Codex review punt 3 + ronde 1).

**Files:**
- Modify: `components/layout.py` — verplaats 6 regels van binnen-naar-buiten layer

- [ ] **Step 1: Lees huidige `.q-table`-regels (binnen layer)**

Run:
```bash
sed -n '14,30p' components/layout.py
```
Verwacht: ziet `@layer components {` op regel ~14, dan `.q-table th { ... }` en `.q-table tbody tr:nth-child(even) { ... }` daarbinnen.

- [ ] **Step 2: Lees huidige `.page-toolbar`-regels (binnen layer)**

Run:
```bash
sed -n '34,57p' components/layout.py
```
Verwacht: `.page-toolbar { ... }` (regel ~34) gevolgd door 4 `.page-toolbar .q-field*`-regels.

- [ ] **Step 3: Knip `.q-table th` en zebra uit @layer, plak boven @layer**

Edit `components/layout.py`. Vervang het blok dat begint met `@layer components {` en de eerste 2 styling-regels daarbinnen:

```css
@layer components {
    /* Table header styling */
    .q-table th {
        background-color: #F1F5F9;
        font-weight: 600;
        text-transform: uppercase;
        font-size: 0.7rem;
        letter-spacing: 0.05em;
        color: #475569;
    }
    .q-table tbody tr:nth-child(even) {
        background-color: #F8FAFC;
    }
```
Door:
```css
/* === QUASAR OVERRIDES (UNLAYERED — winnen van Quasar defaults) === */
/* Sprint B Codex regel: Quasar's eigen CSS is unlayered; layered styles
   verliezen ALTIJD van unlayered ongeacht specificity. Daarom alle .q-*
   overrides hier buiten @layer components plaatsen. */

/* Table header styling */
.q-table th {
    background-color: #F1F5F9;
    font-weight: 600;
    text-transform: uppercase;
    font-size: 0.7rem;
    letter-spacing: 0.05em;
    color: #475569;
}
.q-table tbody tr:nth-child(even) {
    background-color: #F8FAFC;
}

@layer components {
```

- [ ] **Step 4: Knip 4 `.page-toolbar .q-*`-regels uit @layer, plak boven @layer (na `.q-table`-regels)**

Edit `components/layout.py`. Vervang het binnen-layer-blok:
```css
    .page-toolbar .q-field { min-height: unset; }

    /* White pill selects inside toolbar */
    .page-toolbar .q-field--outlined .q-field__control {
        background: white !important;
        border-color: transparent !important;
        border-radius: 20px !important;
        min-height: 36px !important;
        transition: box-shadow 0.15s ease;
    }
    .page-toolbar .q-field--outlined .q-field__control:hover {
        box-shadow: 0 2px 8px rgba(0,0,0,0.07);
    }
    .page-toolbar .q-field--outlined.q-field--focused .q-field__control {
        border-color: var(--q-primary) !important;
        box-shadow: 0 0 0 2px rgba(15, 118, 110, 0.12);
    }
    .page-toolbar .q-field__label {
        font-size: 11px !important;
    }
```
Door (binnen-layer wordt verwijderd, buiten-layer wordt toegevoegd na de `.q-table`-regels):

Voeg aan de `/* === QUASAR OVERRIDES === */` sectie (na de zebra-regel) toe:
```css

/* Page-toolbar Quasar overrides */
.page-toolbar .q-field { min-height: unset; }

/* White pill selects inside toolbar */
.page-toolbar .q-field--outlined .q-field__control {
    background: white !important;
    border-color: transparent !important;
    border-radius: 20px !important;
    min-height: 36px !important;
    transition: box-shadow 0.15s ease;
}
.page-toolbar .q-field--outlined .q-field__control:hover {
    box-shadow: 0 2px 8px rgba(0,0,0,0.07);
}
.page-toolbar .q-field--outlined.q-field--focused .q-field__control {
    border-color: var(--q-primary) !important;
    box-shadow: 0 0 0 2px rgba(15, 118, 110, 0.12);
}
.page-toolbar .q-field__label {
    font-size: 11px !important;
}
```

En verwijder de overeenkomstige regels binnen `@layer components { ... }`.

- [ ] **Step 5: Verifieer dat de migratie compleet is — geen `.q-*` of `.page-toolbar` meer binnen @layer**

Run:
```bash
awk '/@layer components \{/,/^}/' components/layout.py | grep -nE "\.q-|\.page-toolbar" | head -10
```
Expected: leeg (geen matches). Als wel matches: er staat nog een `.q-*`/`.page-toolbar` regel binnen layer — herstel.

- [ ] **Step 6: Verifieer dat alle 6 regels nu BUITEN layer staan**

Run:
```bash
awk '/@layer components \{/{flag=1; next}/^}/{flag=0}!flag' components/layout.py | grep -nE "\.q-|\.page-toolbar" | head -10
```
Expected: 6 regels gevonden — `.q-table th`, `.q-table tbody tr:nth-child(even)`, `.page-toolbar`, `.page-toolbar .q-field`, `.page-toolbar .q-field--outlined .q-field__control` (3×), `.page-toolbar .q-field__label`.

- [ ] **Step 7: Verifieer pytest blijft groen**

Run:
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q 2>&1 | tail -5
```
Expected: `1261 passed`.

- [ ] **Step 8: Commit**

Run:
```bash
git add components/layout.py
git commit -m "$(cat <<'EOF'
refactor(sprint-b): migreer 6 Quasar .q-* overrides naar buiten @layer

Codex review punt 3 + originele cascade-layer waarschuwing: layered
styles verliezen ALTIJD van unlayered Quasar defaults. Onze .q-*
overrides moeten dus buiten @layer components staan om robuust te zijn
tegen Quasar updates.

Verhuisde regels (identieke styling, alleen scope-relocatie, 0 visuele
wijziging):
- .q-table th
- .q-table tbody tr:nth-child(even)
- .page-toolbar .q-field
- .page-toolbar .q-field--outlined .q-field__control (+ :hover + .q-field--focused)
- .page-toolbar .q-field__label

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Lichte header (opaque white)

**Doel:** `ui.header()` van donker `#0F172A` naar opaque white met 1px border-bottom + dark text/icons.

**Files:**
- Modify: `components/layout.py:333-339` (binnen `create_layout()`)

- [ ] **Step 1: Lees huidige header-blok**

Run:
```bash
sed -n '333,340p' components/layout.py
```
Verwacht: `with ui.header().classes('items-center shadow-sm') ...` met `background-color: #0F172A`.

- [ ] **Step 2: Vervang header styling — opaque white met dark content**

Edit `components/layout.py`. Vervang:
```python
    with ui.header().classes('items-center shadow-sm') \
            .style('background-color: #0F172A'):
        ui.button(icon='menu', on_click=lambda: drawer.toggle()) \
            .props('flat color=white round dense')
        ui.label('Boekhouding').classes('text-h6 text-white q-ml-sm')
        ui.space()
        ui.label(title).classes('text-subtitle1').style('color: #CBD5E1')
```
Door:
```python
    with ui.header().classes('items-center') \
            .style('background-color: var(--surface); '
                   'border-bottom: 1px solid var(--border); '
                   'box-shadow: none;'):
        ui.button(icon='menu', on_click=lambda: drawer.toggle()) \
            .props('flat round dense') \
            .style('color: var(--text)')
        ui.label('Boekhouding').classes('text-h6 q-ml-sm') \
            .style('color: var(--text); font-weight: 600')
        ui.space()
        ui.label(title).classes('text-subtitle1').style('color: var(--muted)')
```

- [ ] **Step 3: Verifieer pytest blijft groen**

Run:
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q 2>&1 | tail -5
```
Expected: `1261 passed`.

- [ ] **Step 4: Commit**

Run:
```bash
git add components/layout.py
git commit -m "$(cat <<'EOF'
feat(sprint-b): opaque white header met dark content

Codex YAGNI-cut: geen backdrop-filter (geen meaningful content erachter
in single-window pywebview, GPU-cost zonder winst). Opaque white met
1px border-bottom + dark text/icons via tokens.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Lichte sidebar (gradient + active dot-marker)

**Doel:** `ui.left_drawer()` van donker `#0F172A` naar lichte gradient + nav-item styling herwerken voor lichte achtergrond met soft-accent active state.

**Files:**
- Modify: `components/layout.py` — `.nav-item` CSS-blok (regel ~64-86) + `create_layout()` drawer setup (regel ~341-343)

- [ ] **Step 1: Lees huidige `.nav-item` CSS-blok**

Run:
```bash
sed -n '63,87p' components/layout.py
```
Verwacht: `.nav-item { ... }` definitie met `color: #94A3B8`, hover `background: rgba(255,255,255,0.06)`, active `color: #5EEAD4` etc.

- [ ] **Step 2: Vervang `.nav-item` CSS-blok met lichte variant**

Edit `components/layout.py`. Vervang:
```css
    /* Sidebar nav — clean minimal style */
    .nav-item {
        display: flex; align-items: center; gap: 10px;
        padding: 7px 14px; margin: 1px 8px;
        border-radius: 6px; cursor: pointer;
        color: #94A3B8; font-size: 13px; font-weight: 400;
        transition: all 0.15s;
        text-decoration: none; border: none; background: none;
        width: calc(100% - 16px);
    }
    .nav-item:hover { background: rgba(255,255,255,0.06); color: #E2E8F0; }
    .nav-item .nav-icon { font-size: 18px; width: 20px; text-align: center; }

    .nav-item.active {
        color: #5EEAD4;
        background: rgba(94,234,212,0.08);
        font-weight: 500;
        border-left: 3px solid #14B8A6;
        margin-left: 5px;
        padding-left: 11px;
    }

    .nav-gap { height: 12px; }
    .nav-divider { height: 1px; background: #1E293B; margin: 8px 16px; }
```
Door:
```css
    /* Sidebar nav — Sprint B lichte variant */
    .nav-item {
        display: flex; align-items: center; gap: 10px;
        padding: 7px 14px; margin: 1px 8px;
        border-radius: 8px; cursor: pointer;
        color: var(--muted); font-size: 13px; font-weight: 400;
        transition: background 0.12s, color 0.12s;
        text-decoration: none; border: none; background: none;
        width: calc(100% - 16px);
        position: relative;
    }
    .nav-item:hover {
        background: rgba(60,60,67,0.05);
        color: var(--text);
    }
    .nav-item .nav-icon {
        font-size: 18px; width: 20px; text-align: center;
        color: var(--muted);
    }
    .nav-item:hover .nav-icon { color: var(--text); }

    .nav-item.active {
        color: var(--text);
        background: var(--accent-soft);
        font-weight: 600;
    }
    .nav-item.active .nav-icon { color: var(--accent); }
    .nav-item.active::after {
        content: '';
        width: 6px; height: 6px; border-radius: 50%;
        background: var(--accent);
        position: absolute; right: 12px; top: 50%;
        transform: translateY(-50%);
    }

    .nav-gap { height: 12px; }
    .nav-divider { height: 1px; background: var(--border); margin: 8px 16px; }
```

- [ ] **Step 3: Lees huidige drawer setup**

Run:
```bash
sed -n '341,344p' components/layout.py
```
Verwacht: `drawer = ui.left_drawer(value=True, bordered=False).style('background-color: #0F172A').props('width=180')`.

- [ ] **Step 4: Vervang drawer-styling met lichte gradient**

Edit `components/layout.py`. Vervang:
```python
    drawer = ui.left_drawer(value=True, bordered=False) \
        .style('background-color: #0F172A') \
        .props('width=180')
```
Door:
```python
    drawer = ui.left_drawer(value=True, bordered=False) \
        .style('background: linear-gradient(180deg, '
               '#FAFAFA 0%, '
               'rgba(15,118,110,0.02) 30%, '
               'var(--bg) 100%); '
               'border-right: 1px solid var(--border);') \
        .props('width=180')
```

- [ ] **Step 5: Verifieer pytest blijft groen**

Run:
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q 2>&1 | tail -5
```
Expected: `1261 passed`.

- [ ] **Step 6: Commit**

Run:
```bash
git add components/layout.py
git commit -m "$(cat <<'EOF'
feat(sprint-b): lichte sidebar met soft-accent active state + dot-marker

Codex YAGNI-cuts: 180px breed (geen 260px — content-width op tabellen
beschermd), geen glassmorphic-blur. Active state via:
- background var(--accent-soft) (teal-tinted soft)
- nav-icon color var(--accent) (teal)
- ::after dot-marker rechts (6px teal cirkel)
- font-weight 600 + color var(--text)

Drawer-background = gradient white → soft teal-tint → bg-gray.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Quasar `.q-card` + `.q-btn` overrides toevoegen (UNLAYERED)

**Doel:** Globale `.q-card` (radius/shadow/border via tokens) + `.q-btn` (radius polish) styling toevoegen aan de `/* === QUASAR OVERRIDES === */` sectie buiten @layer.

**Files:**
- Modify: `components/layout.py` — uitbreiding van QUASAR OVERRIDES sectie uit Task 3

- [ ] **Step 1: Localiseer einde van `/* === QUASAR OVERRIDES === */` sectie**

Run:
```bash
grep -n "QUASAR OVERRIDES\|@layer components" components/layout.py | head -5
```
Verwacht: één regel `/* === QUASAR OVERRIDES (UNLAYERED ...) === */` en daaronder de `.page-toolbar`-regels uit Task 3, dan `@layer components {` start.

- [ ] **Step 2: Voeg `.q-card` en `.q-btn` toe net vóór `@layer components {`**

Edit `components/layout.py`. Vóór de regel `@layer components {` (na alle bestaande Quasar overrides), voeg toe:

```css
/* Card defaults — Sprint B token-driven */
.q-card {
    border-radius: var(--radius);
    border: 1px solid var(--border);
    box-shadow: var(--shadow);
    background: var(--surface);
}

/* Button polish — Sprint B (NIET op round/rounded modifiers — die houden Quasar's cirkel-shape) */
.q-btn:not(.q-btn--round):not(.q-btn--rounded) {
    border-radius: 8px;
}

/* Field polish — Sprint B (alleen radius op outlined fields buiten toolbar) */
.q-field--outlined .q-field__control {
    border-radius: 8px;
}
```

> **Plan-amendment 2026-05-03 (na Codex T6 review)**: oorspronkelijke
> `.q-btn { border-radius: 8px; }` overruled Quasar's `.q-btn--round`
> en `.q-btn--rounded` modifiers via gelijke specificity + unlayered
> cascade. Header menu-button (`props('round')`) werd afgerond vierkant
> ipv cirkel. Fix in commit 7aa1696 — `:not()` selector toegevoegd.
> Niet herintroduceren bij re-run.
>
> **Plan-amendment 2026-05-03 (na code-quality T6 review)**: extra
> `.builder-line-card` cascade-fix in commit cead04c. Bewuste
> `box-shadow: none` op invoice-builder line-cards verloor van T6's
> unlayered `.q-card`. Verhuisd naar buiten @layer als chained
> `.q-card.builder-line-card` selector.

- [ ] **Step 3: Verifieer pytest blijft groen**

Run:
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q 2>&1 | tail -5
```
Expected: `1261 passed`.

- [ ] **Step 4: Commit**

Run:
```bash
git add components/layout.py
git commit -m "$(cat <<'EOF'
feat(sprint-b): Quasar .q-card + .q-btn + .q-field tokens (UNLAYERED)

Globale Quasar overrides voor cards (radius/shadow/border via tokens),
buttons (8px radius) en outlined fields (8px radius). Buiten @layer
voor cascade-veiligheid.

Tier-3-impact (eerlijk): .q-card raakt /aangifte fiscale cards en
/jaarafsluiting tabellen — radius wordt 12px ipv square, shadow zachter.
Density behouden (rij-hoogte, kolom-breedte ongewijzigd).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Font-family rewrite (7 classes) + Google Fonts CDN-link weg (ATOMIC)

**Doel:** Alle 7 classes met `'JetBrains Mono'` font-family naar SF Mono stack omzetten EN tegelijk de Google Fonts CDN `<link>` verwijderen. **Atomair**: anders fallback naar Menlo zodra CDN weg is.

**Files:**
- Modify: `components/layout.py` — 7 font-family declaraties + `<link>` verwijderen op regel ~286-290

- [ ] **Step 1: Lees alle 7 JetBrains Mono usages**

Run:
```bash
grep -n "'JetBrains Mono'" components/layout.py
```
Expected: 7 hits in classes `.num`/`.mono` (regels ~112,116), `.chip` (~129), `.seg-btn` (~148), `.selection-bar .sb-count` (~165), `.selection-bar .sb-meta` (~169), `.page-sub` (~175).

- [ ] **Step 2: Vervang alle 7 occurrences met SF Mono stack**

Run:
```bash
sed -i '' "s|'JetBrains Mono', ui-monospace, Menlo, monospace|\"SF Mono\", ui-monospace, Menlo, monospace|g" components/layout.py
sed -i '' "s|'JetBrains Mono', ui-monospace, monospace|\"SF Mono\", ui-monospace, Menlo, monospace|g" components/layout.py
sed -i '' "s|'JetBrains Mono', monospace|\"SF Mono\", ui-monospace, Menlo, monospace|g" components/layout.py
```

- [ ] **Step 3: Verifieer dat alle JetBrains Mono refs weg zijn**

Run:
```bash
grep -c "JetBrains Mono" components/layout.py
```
Expected: `0`.

- [ ] **Step 4: Verifieer dat alle 7 classes nu SF Mono noemen**

Run:
```bash
grep -n '"SF Mono"' components/layout.py
```
Expected: minimaal 7 hits.

- [ ] **Step 5: Verwijder Google Fonts `<link>` (regel ~286-290)**

Lees eerst:
```bash
sed -n '283,292p' components/layout.py
```
Verwacht: comment-regel "JetBrains Mono via Google Fonts" + `ui.add_head_html('<link ...')` blok.

Edit `components/layout.py`. Vervang:
```python
# JetBrains Mono via Google Fonts — pywebview cached na eerste load,
# offline-fallback via ui-monospace stack in de helpers hierboven.
ui.add_head_html(
    '<link rel="stylesheet" '
    'href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&display=swap">',
    shared=True,
)
```
Door:
```python
# Sprint B: Google Fonts CDN-link voor JetBrains Mono verwijderd —
# alle .num/.mono/.chip/.seg-btn/.selection-bar/.page-sub classes
# gebruiken nu SF Mono (system-font, OS-native vanaf macOS 10.11).
```

- [ ] **Step 6: Verifieer pytest blijft groen**

Run:
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q 2>&1 | tail -5
```
Expected: `1261 passed`.

- [ ] **Step 7: Commit**

Run:
```bash
git add components/layout.py
git commit -m "$(cat <<'EOF'
feat(sprint-b): SF Mono font-stack — 7 classes + Google Fonts CDN weg

ATOMIC: font-family rewrite op .num, .mono, .chip, .seg-btn,
.selection-bar .sb-count, .selection-bar .sb-meta, .page-sub plus
verwijderen van CDN <link>. Anders fallback naar Menlo zodra CDN weg.

SF Mono is OS-native vanaf macOS 10.11 — geen download nodig.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `.card-hero` + `page_title()` → token-pickup

**Doel:** Bestaande `.card-hero` class en `page_title()` helper updaten om tokens te gebruiken ipv hardcoded hex. Beide zijn shared utilities die meteen alle Tier 2-pages raken.

**Files:**
- Modify: `components/layout.py` — `.card-hero` definitie (regel ~103) + `page_title()` (regel ~293-296)

- [ ] **Step 1: Lees huidige `.card-hero` en `page_title()`**

Run:
```bash
grep -n "card-hero\|def page_title" components/layout.py
```
Verwacht: 1 hit voor `.card-hero { ... }` en 1 hit voor `def page_title(...)`.

- [ ] **Step 2: Update `.card-hero` met tokens**

Edit `components/layout.py`. Vervang:
```css
    .card-hero { border-radius: 14px; border: 1px solid #E2E8F0; }
```
Door:
```css
    .card-hero {
        border-radius: var(--radius);
        border: 1px solid var(--border);
        box-shadow: var(--shadow);
        background: var(--surface);
    }
```

- [ ] **Step 3: Update `page_title()` met token**

Edit `components/layout.py`. Vervang:
```python
def page_title(text: str):
    """Render a consistent page title label."""
    return ui.label(text).classes('text-h5') \
        .style('color: #0F172A; font-weight: 700')
```
Door:
```python
def page_title(text: str):
    """Render a consistent page title label."""
    return ui.label(text).classes('text-h5') \
        .style('color: var(--text); font-weight: 700')
```

- [ ] **Step 4: Verifieer pytest blijft groen**

Run:
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q 2>&1 | tail -5
```
Expected: `1261 passed`.

- [ ] **Step 5: Commit**

Run:
```bash
git add components/layout.py
git commit -m "$(cat <<'EOF'
refactor(sprint-b): .card-hero + page_title() gebruiken tokens

YAGNI-pickup van shared utilities die door alle Tier 2 pages worden
gebruikt — vervangen van hardcoded hex (#E2E8F0, #0F172A) door tokens
(--border, --text). Effect: dashboard KPI-cards + alle page titles
veranderen automatisch.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: `/bank` route + bestand schrappen

**Doel:** `pages/bank.py` (broken client-side redirect, Codex-verified) verwijderen + import uit `main.py:33` weghalen.

**Files:**
- Delete: `pages/bank.py`
- Modify: `main.py:33`

- [ ] **Step 1: Verifieer dat geen andere code naar `/bank` linkt**

Run:
```bash
grep -rn "'/bank'\|\"/bank\"" pages/ components/ main.py 2>/dev/null
```
Expected: alleen `pages/bank.py:10:@ui.page('/bank')` zelf. Als andere hits: stop, bekijk de hits.

- [ ] **Step 2: Verifieer dat geen andere code `pages.bank` importeert**

Run:
```bash
grep -rn "pages.bank\|from pages import.*bank" main.py pages/ components/ 2>/dev/null
```
Expected: alleen `main.py:33:import pages.bank`.

- [ ] **Step 3: Verwijder import in main.py**

Lees eerst:
```bash
sed -n '30,36p' main.py
```

Edit `main.py`. Vervang:
```python
import pages.bank
```
Door (lege regel of niets — kies wat de import-blok consistent houdt). Concrete edit:

Run:
```bash
sed -i '' '/^import pages\.bank$/d' main.py
```

Verifieer:
```bash
grep -n "pages\.bank" main.py
```
Expected: leeg.

- [ ] **Step 4: Verwijder `pages/bank.py` bestand**

Run:
```bash
git rm pages/bank.py
```

- [ ] **Step 5: Verifieer pytest blijft groen**

Run:
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q 2>&1 | tail -5
```
Expected: `1261 passed`. Als rood en error mentioned `bank` of `import`: stop, fix.

- [ ] **Step 6: Commit**

Run:
```bash
git add -A
git commit -m "$(cat <<'EOF'
chore(sprint-b): schrap /bank route — ui.navigate.to redirect ineffectief

Codex review punt 1: pages/bank.py gebruikte ui.navigate.to('/transacties')
maar dat is client-side window.open() — geen HTTP-redirect, geen
history-replace. Back-button kaatst terug op /bank.

NiceGUI/FastAPI heeft geen app.router.add_redirect; server-side middleware
overkill voor 1-user app. 404 op /bank is acceptabel — niemand bookmarkt
deze legacy URL.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Tier 1 user-acceptatie checkpoint

**Doel:** Gebruiker visueel valideren dat Tier 1 chrome werkt vóór Tier 2 begint. Dit is een GATE — geen Tier 2 totdat Tier 1 visueel akkoord is.

**Files:** geen.

- [ ] **Step 1: Push branch (als remote bestaat)**

Run:
```bash
git push -u origin feature/sprint-b-visual-refresh 2>/dev/null || echo "geen remote — local only"
```

- [ ] **Step 2: Vraag user om app-restart en visuele check**

Vraag aan user:
> Tier 1 commits klaar (Tasks 1-9). Sluit de huidige Boekhouding-app af en start opnieuw met `open -a Boekhouding`. Loop deze checks door:
>
> 1. **Header**: opaque white met "Boekhouding" links + huidige page-titel rechts in donkere tekst, zonder dropshadow.
> 2. **Sidebar**: lichte gradient (white → soft teal-tint), nav-items met dot-marker rechts bij actieve pagina.
> 3. **Body-background**: licht systeem-grijs (`#F5F5F7`) — subtiel anders dan voorheen `#F8FAFC`.
> 4. **Numbers in /werkdagen tabel** (als die `.num` class gebruikt): renderen in SF Mono — nauwer dan vroeger JetBrains Mono.
> 5. **Cards op /aangifte** (Tier 3): hebben subtiel rondere hoeken (12px radius) — leesbaar of te druk?
>
> Bij OK → groen licht voor Tier 2.
> Bij issue → noteer welke route + wat — dan corrigeren we in Tier 1 vóór door te gaan.

- [ ] **Step 3: Wacht op user-akkoord vóór Tier 2 te starten**

(geen code-actie — gate.)

---

## Task 11: Tier 2 — `/dashboard` smoke

**Doel:** Verifieer dat `/dashboard` (root `/`) na Tier 1 werkt. Voer subflow-checks uit.

**Files:** mogelijk `pages/dashboard.py` (alleen als token-pickup-opportunity blootgelegd door smoke).

- [ ] **Step 1: Vraag user om `/` te bezoeken in pywebview**

Vraag aan user, met checklist:
> Bezoek `/` (Dashboard). Controleer:
> 1. KPI-cards renderen
> 2. Click op "Te verwerken"-card navigeert naar `/transacties?status=ongecategoriseerd`
> 3. Charts renderen
> 4. Sparklines (als omzet > 0) renderen
> 5. Geen console-errors (open DevTools indien mogelijk)
>
> Hardcoded `#E2E8F0` of `#0F172A`-stijl in cards die Apple-stijl zou doorbreken: meld als token-pickup-kandidaat.

- [ ] **Step 2: Wacht op user-feedback**

(geen code-actie tenzij user issues meldt.)

- [ ] **Step 3: Mark task done als user "OK" zegt**

Geen commit nodig als 0 wijzigingen.

---

## Task 12: Tier 2 — `/werkdagen` smoke + portal-event-check

**Doel:** Verifieer `/werkdagen` werkt; expliciet portal-event-check op rij-menu (`q-menu` teleport, regel 244).

**Files:** mogelijk `pages/werkdagen.py`.

- [ ] **Step 1: Vraag user om `/werkdagen` te bezoeken**

Vraag aan user, met checklist:
> Bezoek `/werkdagen`. Controleer:
> 1. Tabel rendert met juiste row-height + zebra
> 2. Filter-toolbar werkt (jaar/maand/zoek)
> 3. "+ Werkdag" knop opent dialog → bewaart een test-werkdag
> 4. **Portal-event-check (KRITIEK)**: rij-menu (`...` knop op een rij) opent → klik "Bewerken" → werkdag-dialog opent met de juiste werkdag voorgeladen → annuleer
> 5. **Portal-event-check**: rij-menu → "Verwijderen" → bevestigingsdialog opent → annuleer
>
> Bij portal-event-bug (menu opent maar klikken doet niks): meld dit DIRECT — dan rollback we Tier 1 commit dat het heeft veroorzaakt (`git bisect` op feature-branch).

- [ ] **Step 2: Wacht op user-feedback**

- [ ] **Step 3: Mark task done als user "OK" zegt**

---

## Task 13: Tier 2 — `/facturen` smoke + 3 status-flow checks

**Doel:** Verifieer `/facturen` werkt; expliciet status-transities + PDF self-healing testen (Codex review punt 5).

**Files:** mogelijk `pages/facturen.py`.

- [ ] **Step 1: Vraag user om `/facturen` te bezoeken**

Vraag aan user, met checklist:
> Bezoek `/facturen`. Controleer in volgorde:
>
> **Basistests:**
> 1. Tabel rendert
> 2. Filter-toolbar (jaar/status/zoek) werkt
> 3. "+ Factuur" opent invoice builder → annuleer
>
> **Portal-event + Bewerken-flow:**
> 4. Op een **concept**-factuur: rij-menu → "Bewerken" → invoice builder opent met regels voorgeladen → annuleer
>
> **Status-flow A (concept → verstuurd):**
> 5. Op een **concept**-factuur: rij-menu → "Verstuur via mail" → Mail.app opent met PDF attached → sluit Mail.app → factuur status flipt naar `verstuurd` (badge wordt blauw)
>
> **Status-flow B (betaald → concept twee-staps):**
> 6. Op een **betaalde** factuur: rij-menu → "Markeer als concept" → waarschuwingsdialog opent → bevestig → factuur loopt door betaald→verstuurd→concept transitie → status badge wordt grijs
>
> **PDF self-healing:**
> 7. Pak een factuur waarvan je de PDF in `~/Library/Application Support/Boekhouding/data/pdfs/` handmatig hebt verwijderd (of vraag de gebruiker dit te doen) → rij-menu → "PDF preview" → de PDF wordt opnieuw gegenereerd en preview opent

- [ ] **Step 2: Wacht op user-feedback**

- [ ] **Step 3: Mark task done als user "OK" zegt**

---

## Task 14: Tier 2 — `/transacties` smoke + q-select event-check

**Doel:** Verifieer `/transacties` werkt; expliciet portal-event-check op categorie q-select per rij.

**Files:** mogelijk `pages/transacties.py`.

- [ ] **Step 1: Vraag user om `/transacties` te bezoeken**

Vraag aan user, met checklist:
> Bezoek `/transacties`. Controleer:
> 1. Tabel rendert met juiste sign-coloring (teal voor positief, rood voor negatief)
> 2. Filter-toolbar (jaar/maand/status/categorie/type/zoek) werkt
>
> **Portal-event-check (KRITIEK — historische bug):**
> 3. Klik op de categorie-dropdown van een **ongecategoriseerde** rij → kies een categorie → de waarde wordt opgeslagen (UI ververst, status flipt naar `gecategoriseerd`)
> 4. Klik op de categorie-dropdown van een **andere** rij → kies "" (leeg) → categorie wordt geleegd
>
> **Match-flow:**
> 5. Click "Matches controleren (N)" header-knop (als N > 0) → preview-dialog opent met match-suggesties → annuleer
>
> **Bulk-acties:**
> 6. Selecteer 2-3 rijen via checkboxes → "Categorie wijzigen" werkt + bevestigingsdialog opent
> 7. Selecteer 2-3 bank-rijen → "Markeer als privé" werkt
> 8. "Verwijderen" → bevestigingsdialog opent (annuleer)
>
> Bij q-select event-bug (dropdown opent maar selectie wordt niet opgeslagen): rollback Tier 1 commit dat dit veroorzaakt.

- [ ] **Step 2: Wacht op user-feedback**

- [ ] **Step 3: Mark task done als user "OK" zegt**

---

## Task 15: Tier 2 — `/kosten` smoke

**Doel:** Verifieer `/kosten` (read-only) werkt.

- [ ] **Step 1: Vraag user om `/kosten` te bezoeken**

Vraag aan user, met checklist:
> Bezoek `/kosten`. Controleer:
> 1. Tab "Overzicht" laadt: KPI-strip, per-maand bar chart, categorie breakdown, terugkerende-kosten-card
> 2. Click op een categorie-bar → navigeert naar `/transacties?jaar=X&categorie=Y` (categorie correct URL-encoded)
> 3. Click op "(nog te categoriseren)" muted-card → navigeert naar `/transacties?status=ongecategoriseerd`
> 4. Click op een vendor-card in "Terugkerende kosten" → navigeert naar `/transacties?search=vendor`
> 5. Tab "Investeringen" laadt: activastaat-tabel met afschrijvingen

- [ ] **Step 2: Wacht op user-feedback**

- [ ] **Step 3: Mark task done als user "OK" zegt**

---

## Task 16: Tier 2 — `/klanten` smoke + alias-CRUD

**Doel:** Verifieer `/klanten` + klant-dialog edit-mode + alias-CRUD-sectie.

- [ ] **Step 1: Vraag user om `/klanten` te bezoeken**

Vraag aan user, met checklist:
> Bezoek `/klanten`. Controleer:
> 1. Tabel rendert
> 2. "+ Klant" → nieuwe klant-dialog opent
> 3. Op bestaande klant: rij-menu → "Bewerken" → klant-dialog opent
> 4. **Aliassen-sectie** (alleen in edit-mode): aliases-lijst rendert, "+ Alias toevoegen" dialog werkt (kies type + pattern)
> 5. Delete-knop op een alias werkt + bevestigt
> 6. Inactief-toggle op klant werkt

- [ ] **Step 2: Wacht op user-feedback**

- [ ] **Step 3: Mark task done als user "OK" zegt**

---

## Task 17: Tier 2 — `/documenten` smoke + upload

**Doel:** Verifieer `/documenten` werkt incl. upload-flow.

- [ ] **Step 1: Vraag user om `/documenten` te bezoeken**

Vraag aan user, met checklist:
> Bezoek `/documenten`. Controleer:
> 1. Tabel rendert (categorieen)
> 2. Filter-toolbar werkt
> 3. Upload-veld accepteert een test-PDF → file verschijnt in tabel
> 4. Click op een document → preview opent (iframe)
> 5. Verwijder-knop op een document werkt + bevestigt

- [ ] **Step 2: Wacht op user-feedback**

- [ ] **Step 3: Mark task done als user "OK" zegt**

---

## Task 18: Tier 3 — spot-check `/aangifte`, `/jaarafsluiting`, `/instellingen`

**Doel:** Verifieer dat de drie fiscale pages na Tier 1 chrome+token-pickup nog leesbaar zijn (geen layout-druk).

- [ ] **Step 1: Vraag user om de 3 routes te bezoeken**

Vraag aan user, met checklist:
> Bezoek de drie Tier-3 routes:
>
> **`/aangifte`:**
> 1. Tabs (Box 1 / Box 3 / etc.) wisselen
> 2. Fiscale cijfers in cards leesbaar — geen layout-druk door 12px radius?
> 3. Inkomen-tabel rendert
>
> **`/jaarafsluiting`:**
> 4. Tabs (Controles / Snapshot / Heropenen) werken
> 5. Tabellen krijgen zebra-rows — visueel druk of OK?
> 6. "Definitief maken"-knop opent dialog
>
> **`/instellingen`:**
> 7. Jaar-selector werkt
> 8. Arbeidskorting-brackets editor laadt
> 9. Opslaan-knop landt zonder error
>
> Bij issue ("te druk", "radius te rond voor density"): single-token tweak in `--radius` (bv. 8px) of `--shadow` (subtieler).

- [ ] **Step 2: Wacht op user-feedback**

- [ ] **Step 3: Bij token-tweak nodig — apply en commit**

Indien user "te druk" meldt: edit `components/layout.py` token-blok regel `--radius: 12px;` naar `--radius: 8px;` (of vergelijkbaar). Pytest groen, commit met `style(sprint-b): tweak --radius naar 8px op verzoek na Tier 3 spot-check`.

- [ ] **Step 4: Mark task done als user "OK" zegt**

---

## Task 19: `/agenda` regression-check (Sprint A behouden)

**Doel:** Verifieer dat Sprint A's `/agenda` visueel onveranderd is (calendar-grid pixel-vergelijkbaar).

- [ ] **Step 1: Vraag user om `/agenda` te bezoeken**

Vraag aan user, met checklist:
> Bezoek `/agenda`. Controleer:
> 1. Maandgrid rendert met dezelfde `.wd-pill` styling als vóór Sprint B (teal voor dagpraktijk, paars voor anw, grijs voor overig)
> 2. `.agenda-cell` borders + corners onveranderd
> 3. Status-bars onder werkdag-pills onveranderd (grijs/blauw/rood/groen)
> 4. Holiday-markers + blocker-overlays onveranderd
> 5. Day-inspector dialoog opent + werkt
> 6. Sidebar/header zijn lichter (dat is OK — Tier 1 effect)
>
> Bij visuele wijziging op `.wd-*` of `.agenda-cell`: regression — meld direct.

- [ ] **Step 2: Wacht op user-feedback**

- [ ] **Step 3: Mark task done als user "OK" zegt**

---

## Task 20: Codex auto-review op finale `layout.py` diff

**Doel:** Codex CLI als second-opinion reviewer op alle Tier 1 + /bank wijzigingen.

- [ ] **Step 1: Genereer combined diff sinds master**

Run:
```bash
cd "$(git rev-parse --show-toplevel)"
git diff master..HEAD -- components/layout.py main.py | head -300
```

- [ ] **Step 2: Run codex-review skill**

Run de `codex-review` skill (zie `.claude/skills/codex-review/SKILL.md`):

```bash
DIFF=$(git diff master..HEAD -- components/layout.py main.py)
printf '%s\n' "$DIFF" | env -u OPENAI_API_KEY codex exec --sandbox read-only "Review de Sprint B visual refresh diff op components/layout.py + main.py. Focus op:
- CSS-syntax errors of ongebalanceerde brackets
- Hardcoded hex die token-referentie had moeten zijn
- Per ongeluk overschreven Sprint A regel (wd-pill, agenda-cell, week-summary)
- Cascade-layer issue: zit een .q-* override per ongeluk binnen @layer?
- main.py import-cleanup: zijn er andere stale references naar pages.bank?

Wees terse, max 5 bullets. Als alles OK: 'GEEN BEVINDINGEN'."
```

- [ ] **Step 3: Verwerk Codex bevindingen**

Per bevinding evalueer:
- Klopt het? Verifieer in code (Read of Grep).
- Is het een echte bug of hallucinatie?
- Past de fix bij Sprint B scope?

Bij echte bug: fix + commit met `fix(sprint-b): <bevinding-summary> (codex)`. Bij hallucinatie: noteer waarom genegeerd.

- [ ] **Step 4: Mark task done bij GEEN BEVINDINGEN of bewust geaccepteerde nuance**

---

## Task 21: Auto-memory update + finale pytest

**Doel:** Memory bijwerken voor toekomstige sessies + finale pytest-baseline.

**Files:**
- Create: `~/.claude/projects/-Users-macbookpro-ronald-Library-CloudStorage-SynologyDrive-Main-06-Development-1-roberg-boekhouding/memory/project_visual_refresh.md`
- Modify: `~/.claude/projects/.../memory/MEMORY.md` (index)

- [ ] **Step 1: Finale pytest groen**

Run:
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q 2>&1 | tail -5
```
Expected: `1261 passed` (of T0-baseline).

- [ ] **Step 2: Schrijf memory-file voor visual-refresh**

Write naar `~/.claude/projects/-Users-macbookpro-ronald-Library-CloudStorage-SynologyDrive-Main-06-Development-1-roberg-boekhouding/memory/project_visual_refresh.md`:

```markdown
---
name: Sprint B visual refresh (2026-05-03)
description: Apple-stijl chrome-port met 9 tokens — teal blijft brand, lichte sidebar/header, system-font + SF Mono, /bank geschrapt
type: project
---

Sprint B SHIPPED 2026-05-03 op feature/sprint-b-visual-refresh.

**Why:** Sprint A had Apple-stijl alleen op /agenda; rest van app voelde
inconsistent (donkere sidebar/header tegen lichte content). Codex
YAGNI-pushback heeft scope ingedikt — geen glassmorphism, geen Rounded
headings, geen brede sidebar, geen token-explosie.

**How to apply (toekomstige work):**
- Gebruik tokens uit components/layout.py :root (--bg, --surface,
  --border, --text, --muted, --accent, --accent-soft, --shadow,
  --radius). Geen nieuwe hardcoded hex in pages/.
- Quasar .q-* overrides BUITEN @layer components plaatsen
  (cascade-order: layered verliest van unlayered Quasar defaults).
- App-only classes (.app-card, .nav-item, .wd-pill, etc.) BINNEN
  @layer components.
- Numbers in tabellen/labels via .num class (SF Mono + tabular-nums).
  Sprint B raakte alleen de class-definitie — pages/-adoptie is YAGNI.
- /bank route bestaat niet meer — geen ui.navigate.to('/bank') of
  hardcoded /bank links toevoegen.
```

- [ ] **Step 3: Update MEMORY.md index**

Edit `~/.claude/projects/-Users-macbookpro-ronald-Library-CloudStorage-SynologyDrive-Main-06-Development-1-roberg-boekhouding/memory/MEMORY.md`:

Voeg na de Agenda Sprint A regel toe:
```markdown
- [Visual refresh Sprint B (2026-05-03)](project_visual_refresh.md) — Apple-stijl chrome (lichte sidebar/header, 9 tokens, system-font); /bank geschrapt; Sprint A /agenda intact
```

- [ ] **Step 4: Update CLAUDE.md project-instructies (mini-sectie)**

Edit `CLAUDE.md` (project root). Voeg vóór de `### YAGNI` sectie toe:

```markdown
### Visuele tokens (Sprint B, 2026-05-03)

`components/layout.py` definieert 9 CSS custom properties als single
source of truth voor visual styling: `--bg`, `--surface`, `--border`,
`--text`, `--muted`, `--accent`, `--accent-soft`, `--shadow`,
`--radius`. Nieuw werk gebruikt deze — geen hardcoded hex meer in
`pages/`.

**Cascade-regel**: Quasar `.q-*` overrides ALTIJD buiten
`@layer components` plaatsen — layered styles verliezen van Quasar's
unlayered defaults. App-only classes (`.app-card`, `.nav-item`,
`.wd-pill`, etc.) horen wél binnen `@layer components`.

**Font-stack**: body+headings = `-apple-system` system stack (laat
macOS SF Pro Text/Display zelf kiezen); numbers = SF Mono via `.num`
class. Geen webfont-CDN meer.
```

- [ ] **Step 5: Commit + push**

Run:
```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(sprint-b): CLAUDE.md mini-sectie over visuele tokens + cascade-regel

Sprint B SHIPPED — auto-memory bijgewerkt + project-instructies
uitgebreid met de 9 tokens en de Quasar-overrides-buiten-layer regel
zodat toekomstige sessies dit oppakken.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push 2>/dev/null || echo "geen remote — local only"
```

- [ ] **Step 6: Toon commit-summary aan user**

Run:
```bash
git log --oneline master..HEAD
```

Toon resultaat aan user en vraag of de branch klaar is voor merge naar master (eventueel via PR + ultrareview, of direct merge).

---

## Self-Review Checklist (auteur — vóór hand-off)

- [x] **Spec coverage**: alle 8 § In-scope items hebben minstens 1 task
  (token-blok=Task1, CDN-link=Task7, tabel-leesbaarheid=Task3, KPI-cards=Task6+8, forms/dialogs=Task6, /bank=Task9, smoke-test=Tasks11-19, pytest groen=elke task Step "verifieer pytest").
- [x] **Placeholder scan**: geen TBD/TODO/"add appropriate". Alle code is concreet.
- [x] **Atomicity-paren**: Task 1 (token+body inline-style atomic), Task 7
  (font-family+CDN atomic) — beide expliciet als atomair beschreven.
- [x] **DoD coverage**: alle Definition of Done items uit spec hebben een
  task: tokens (T1), Quasar buiten layer (T3+T6), body inline-style (T1),
  light header (T4), light sidebar (T5), system font (T2), SF Mono +
  CDN weg (T7), /bank weg (T9), pytest baseline (T0+elke task), smoke (T10-T19), portal-events (T12,T13,T14), user-acceptatie (T10,T18,T19), codex-review (T20), auto-memory (T21).
- [x] **Type/naming consistency**: token-namen consistent door alle tasks.
- [x] **Verifiable claims**: 1261 baseline, 6 .q-* regels, 7 JetBrains
  Mono classes, layout.py:331 inline-style, layout.py:286-290 CDN-link,
  pages/bank.py = 13 regels — alle pre-flight gemeten 2026-05-03.

---

## Out of plan (bewust)

- Numeric-alignment-pass over 89× `format_euro` callers in `pages/` (uit
  spec uitgesloten — geen "kleine pickup").
- Per-page CSS-files (Aanpak 2 verworpen).
- Klant-specifieke kleuren (Sprint C kandidaat).
- Token-tweaks die *wel* een YAGNI-extension zijn (`--ink-1..4`,
  `--shadow-sm/-lg`).
- iOS-blue als primary (teal blijft).
- SF Pro Rounded voor headings (system-stack only).

---

## Execution opties

Plan klaar. Twee execution-opties:

**1. Subagent-driven (aanbevolen)** — fresh subagent per task, review tussen tasks, snelle iteratie. Past bij een sprint waar elke task <5 min is.

**2. Inline execution** — uitvoeren in deze sessie via `executing-plans`, batch met checkpoints.

Welke?
