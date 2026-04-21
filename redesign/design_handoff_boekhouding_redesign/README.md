# Handoff: Boekhouding Redesign

A calm, minimal redesign of a Dutch sole-trader (ZZP) bookkeeping app. Replaces the existing NiceGUI-based Python UI with a unified, keyboard-first interface organised around the tax-year rhythm (urencriterium, BTW-vrijstelling, jaarafsluiting).

---

## About the Design Files

The files in `prototype/` and `source/` are **design references** — an HTML/React prototype built with Babel-in-browser + inline JSX. They are not production code to copy directly.

**Your task:** recreate this design in the target codebase's existing environment, using its established patterns and libraries.

The existing app is **Python + NiceGUI**. NiceGUI renders on top of Quasar/Vue, so the practical implementation path is:
- **Preferred:** Rebuild the frontend as a proper SPA (React, Vue, SvelteKit) talking to the Python backend via a thin REST/WS layer. The prototype is already React, so React is the least-friction choice.
- **Alternative:** Stay in NiceGUI and rebuild the UI using `ui.html` + custom CSS + Quasar components. The layouts, tokens and interactions in this handoff translate, but NiceGUI will fight you on density, typography and the command palette. Expect ~60% fidelity.

If the team is open to migrating off NiceGUI, **do it** — the design depends on fine-grained control over layout, typography and keyboard interactions that NiceGUI does not expose cleanly.

---

## Fidelity

**High-fidelity.** Colors, typography, spacing, densities, dark mode, and all interactions are final. Reproduce pixel-for-pixel. The prototype is the source of truth — when the README and the HTML disagree, the HTML wins.

One caveat: the prototype uses a fixed 1440px viewport. In production the layout should be fluid from 1280–1920px using the same grid; mobile is out of scope.

---

## Design System

### Color tokens

All colors are declared as CSS custom properties in `source/styles.css`. Two themes (`[data-theme="light"]` default, `[data-theme="dark"]`) plus five accent swaps (`[data-accent="teal|slate|indigo|amber|rose"]`).

**Light (default)**

| Token | Value | Use |
|---|---|---|
| `--bg` | `#fafaf7` | App background (warm off-white) |
| `--bg-elev` | `#ffffff` | Cards, panels, modals |
| `--bg-sunk` | `#f5f4ef` | Inset surfaces, table headers, inputs at rest |
| `--bg-hover` | `#f0efe9` | Row hover, button hover |
| `--line` | `#e8e6df` | Default borders, dividers |
| `--line-strong` | `#d8d5cc` | Input borders, focused dividers |
| `--ink` | `#15171a` | Primary text, numbers |
| `--ink-2` | `#3a3d43` | Secondary text |
| `--ink-3` | `#6b6f76` | Tertiary / labels |
| `--ink-4` | `#9a9ea5` | Quaternary / disabled |
| `--accent` | `#0f766e` | Primary accent (teal) |
| `--accent-soft` | `#e6f2f0` | Accent backgrounds (chips, badges) |
| `--accent-ink` | `#0a524c` | Accent text on accent-soft |
| `--pos` | `#0f766e` | Paid / positive / match |
| `--neg` | `#b45309` | Overdue / negative |
| `--warn` | `#a16207` | Pending / attention |
| `--info` | `#1e40af` | Informational |

**Dark**

| Token | Value |
|---|---|
| `--bg` | `#0e0f11` |
| `--bg-elev` | `#17181b` |
| `--bg-sunk` | `#0a0b0c` |
| `--bg-hover` | `#1e2024` |
| `--line` | `#26282c` |
| `--line-strong` | `#35383d` |
| `--ink` | `#f2f1ec` |
| `--accent` | `#2dd4bf` |

Accent variants (override `--accent`, `--accent-soft`, `--accent-ink`, `--pos`):
- **slate:** `#475569 / #eef2f5 / #334155`
- **indigo:** `#4f46e5 / #eef0fc / #3730a3`
- **amber:** `#b45309 / #fdf3e4 / #92400e`
- **rose:** `#be185d / #fce8ef / #9d174d`

### Typography

Four sans stacks, swappable via `[data-font]`:
- **inter** (default): Inter 400/500/600
- **plex:** IBM Plex Sans
- **system:** system-ui
- **serif:** Source Serif Pro for body (display-only experiment)

Always used regardless of font swap:
- **Display / numbers on hero cells:** `Instrument Serif` — italic, 48–96px. Editorial feel, **only** on big metric values and page titles on the dashboard.
- **Mono / all numerals in tables + invoices:** `JetBrains Mono` 400/500. Every euro amount, date, hour count, invoice number, BTW number. Tabular-nums.

Scale:

| Class | Size / weight / line-height | Use |
|---|---|---|
| `.t-display` | 64px / 400 / 1.0, Instrument Serif italic | Dashboard hero numbers |
| `.t-h1` | 28px / 500 / 1.2 | Page titles |
| `.t-h2` | 20px / 500 / 1.3 | Section titles |
| `.t-h3` | 15px / 600 / 1.4 | Card titles, table group headers |
| `.t-body` | 14px / 400 / 1.5 | Default body |
| `.t-small` | 13px / 400 / 1.45 | Secondary text, meta |
| `.t-micro` | 11px / 500 / 1.3, letter-spacing 0.06em, uppercase | Labels, column headers |
| `.t-num` | inherit size, JetBrains Mono 500, tabular-nums | All numeric values |

### Spacing & density

CSS vars drive three density modes (`[data-density="compact|normal|spacious"]`):

| Var | compact | normal | spacious |
|---|---|---|---|
| `--pad` | 14 | 20 | 28 |
| `--pad-sm` | 8 | 12 | 16 |
| `--row-h` | 36 | 44 | 52 |

Base spacing scale (hand-use, not tokenised): 4 · 6 · 8 · 12 · 16 · 20 · 24 · 32 · 48 · 64.

### Radii & shadows

| Token | Value |
|---|---|
| `--radius-sm` | 6px — chips, inline badges |
| `--radius` | 10px — cards, buttons, inputs |
| `--radius-lg` | 14px — modals, large panels |
| `--shadow-sm` | `0 1px 0 rgba(20,20,20,0.02), 0 1px 2px rgba(20,20,20,0.04)` |
| `--shadow-md` | `0 1px 0 rgba(20,20,20,0.03), 0 8px 24px -12px rgba(20,20,20,0.08)` |
| `--shadow-lg` | `0 30px 60px -20px rgba(20,20,20,0.18), 0 12px 24px -12px rgba(20,20,20,0.10)` |

Borders are 1px solid `--line`. Almost no shadows on cards — the design leans on thin borders + subtle surface elevation (`--bg-elev` vs `--bg`).

---

## App Shell

A fixed 3-zone layout, full viewport, no scroll on the shell itself (only the main column scrolls).

```
┌────────────────────────────────────────────────────┐
│ 220px sidebar │ topbar 52px                        │
│               ├────────────────────────────────────┤
│               │                                    │
│               │ main (scrolls)                     │
│               │ max-width 1240px, centered,        │
│               │ padding 32px 40px                  │
│               │                                    │
└────────────────────────────────────────────────────┘
```

### Sidebar (220px, `--bg-sunk` background, no right border)

- Top: wordmark "**boekhouding**" in Instrument Serif italic, 22px, `--ink`. Year pill next to it: "2025" in `.t-num` on `--bg-elev` with 1px `--line` border, radius 999px, 4px/10px padding.
- Nav list, vertical, 4px gap:
  - Each item: 36px tall, 12px horizontal padding, 10px radius, 12px gap between icon and label, 14px label.
  - Icon: 16px stroke 1.75, `--ink-3` at rest.
  - Active: background `--bg-elev`, icon + label `--ink`, 1px left accent bar 3px wide in `--accent` (inset via `box-shadow: inset 3px 0 0 var(--accent)`).
  - Hover (non-active): background `--bg-hover`.
- Sections with micro-header labels (`.t-micro`, `--ink-4`, 8px bottom margin, 12px top margin after first section): "werk", "geld", "admin".
- Nav items in order:
  - **werk:** Dashboard (home), Werkdagen (calendar), Facturen (file-text), Klanten (users)
  - **geld:** Kosten (receipt), Bank (landmark), Documenten (folder)
  - **admin:** Jaarafsluiting (archive), Aangifte (file-check), Instellingen (settings)
- Bottom: user card. 52px tall, shows avatar (32px circle, initials in mono), name, company name small. Clicking opens settings.

### Topbar (52px, `--bg` background, bottom 1px `--line`)

- Left: page title in `.t-h2`, + contextual period switcher where relevant (e.g. "Q4 2025 ▾").
- Center: **command bar**. 420px wide, `--bg-sunk`, 1px `--line`, 10px radius, 36px tall. Shows placeholder "Zoek of typ een commando…" + `⌘K` kbd pill right-aligned. Click or ⌘K opens palette.
- Right: notification bell (badge if alerts > 0, dot in `--warn`), "Nieuwe factuur" primary button, theme toggle (sun/moon, 32px icon button).

### Command Palette

Fires on ⌘K / click on command bar. Centered modal, 560px wide, max 480px tall, `--bg-elev`, `--shadow-lg`, radius `--radius-lg`. Appears with 120ms ease-out fade + 8px translate-up.

- Input: 56px tall, 16px font, no border, bottom 1px `--line`, placeholder "Typ een commando of zoek…"
- Results: grouped by "Acties", "Navigatie", "Klanten".
- Group header: `.t-micro`, `--ink-4`, 12px horizontal padding, 8px vertical.
- Row: 40px, 12px padding, icon left (16px, `--ink-3`), label, kbd hint right (e.g. `W`, `⌘N`).
- Highlighted row: `--bg-hover`.
- Keyboard: ↑↓ to move, Enter to activate, Esc to close.

Shortcuts wired (registered on `window`):
- `⌘K` — open palette
- `W` — Werkdagen
- `F` — Facturen
- `D` — Dashboard
- `B` — Bank
- `⌘N` — New invoice
- `Esc` — close modal/palette

---

## Screen: Dashboard

Route: `/` — the home screen. Shows the shape of the tax year at a glance.

### Layout

Vertical stack, 32px gaps. Max 1240px.

1. **Hero strip** (full width, 3 columns: 1fr · 1fr · 1.2fr, 16px gap)
   - **Urencriterium card** (left, 1fr)
   - **Omzet + winst card** (middle, 1fr)
   - **Openstaand + alerts card** (right, 1.2fr)
2. **12-month revenue chart** (full width, 1 card)
3. **Two-col split** (2 columns: 1fr · 1fr, 24px gap)
   - Left: **Recente activiteit** (timeline)
   - Right: **Aankomende deadlines** (list)

### 1a. Urencriterium card

**Most important element of the app.** A ZZP in Nederland needs 1225 declarable hours per year to qualify for zelfstandigenaftrek. Missing it = taxed thousands more. This card must feel consequential.

- Card: `--bg-elev`, 1px `--line`, 24px padding, 20px radius.
- Top label row: `.t-micro` "URENCRITERIUM" in `--ink-4`, status dot right-aligned (8px, `--pos` if on-pace, `--warn` if behind).
- Hero: two numbers side-by-side, baseline-aligned.
  - Big: declarable hours YTD, Instrument Serif italic 72px, tabular-nums.
  - Slash separator: "/" in `--ink-4`, 32px, 12px horizontal margins.
  - Small: "1225" in JetBrains Mono 24px `--ink-3`.
- Progress bar: 6px tall, full width, 16px top margin. `--bg-sunk` track, `--accent` fill, 999px radius. At the exact % of year elapsed, a 2px tall 16px wide `--ink-3` marker sits on top — the pace line. If fill ≥ marker, you're ahead.
- Bottom row: two labels in `.t-small`:
  - Left: "X uur te gaan" (hours remaining)
  - Right: "Y dagen in het jaar — Z% voorbij"

### 1b. Omzet + winst card

- Two stacked rows.
- Top row: label "OMZET 2025" micro + value in `.t-display` 56px + delta below in `.t-small` (`+12% vs 2024` in `--pos`, or `-X%` in `--neg`).
- Hairline `--line` divider.
- Bottom row: label "WINST YTD" + value (display 40px, slightly smaller than omzet). Delta same pattern.

### 1c. Openstaand + alerts card

- Top: "OPENSTAAND" micro + amount in `.t-display` 48px. Subline: "X facturen · Y overdue" — the "Y overdue" part in `--neg` if > 0.
- Alert list below (divided by 1px `--line`):
  - "3 werkdagen nog niet gefactureerd" — icon receipt, link-arrow right
  - "2 bankmutaties zonder match"
  - "1 factuur vervalt deze week"
- Each row 44px, 12px padding, hover `--bg-hover`, cursor pointer. Icon 16px left in `--warn` if attention needed, `--ink-3` if informational.

### 2. Revenue chart

- Card, 24px padding, full width.
- Header row: title `.t-h3` "Omzet per maand" + segment toggle right ("2025 | 2024 | 2023", 32px, `--bg-sunk` bg, radius 8px, active segment `--bg-elev` + `--shadow-sm`).
- Chart area: 200px tall.
- 12 bar pairs (current year + prior year), one pair per month. Bar width 22px, gap 6px between pair, 32px between months.
  - Current year: filled `--accent`.
  - Prior year: outline, 1px `--line-strong`, 2px top radius.
- Y-axis: 3 gridlines at 25/50/100% of max, dashed 1px `--line`, labels on right in `.t-micro` `--ink-4`.
- X-axis labels: 3-letter month abbreviations in `.t-micro`. Current month highlighted with `--ink` and a 1px underline.
- Hover on a pair: tooltip 8px above, `--ink` bg, white text, 11px, 6px radius, shows "Okt 2025: €12.450 · +18%".

### 3a. Recente activiteit

- Card, 20px padding.
- Title `.t-h3` "Recente activiteit" + "Alles tonen →" link right in `.t-small` `--accent`.
- Vertical timeline. 1px `--line` rail at 18px from left, 12 items max.
- Each item: 12px dot on the rail (color by event type), content to the right of the rail with 16px left padding.
  - Dot colors: invoice-sent `--info`, invoice-paid `--pos`, expense-added `--ink-3`, bank-matched `--accent`, hours-logged `--warn`.
- Content rows:
  - Line 1: action in `.t-body`, e.g. "Factuur 2025-0041 verstuurd aan Acme BV"
  - Line 2: `.t-small` `--ink-3` timestamp "2 uur geleden · €3.450"
- 16px vertical spacing between items. Numbers always in mono.

### 3b. Aankomende deadlines

- Card, 20px padding.
- Title `.t-h3` "Aankomende deadlines".
- List, 4–6 items. Each 56px, 12px vertical padding, 1px bottom `--line` (except last).
- Layout per row:
  - Left: date block — day number in Instrument Serif 28px, month abbrev below in `.t-micro`. 56px wide column.
  - Center: title in `.t-body` (e.g. "BTW-aangifte Q4") + subline `.t-small` `--ink-3` ("Indienen + betalen").
  - Right: days-remaining pill in mono, `--bg-sunk` bg, radius 999px, 4px/10px padding. If ≤ 7 days, swap to `--accent-soft` + `--accent-ink`. If overdue, `--neg` bg at 10% opacity + `--neg` text.

---

## Screen: Werkdagen

Route: `/werkdagen`. Log of declarable hours — the raw material for invoicing and for the urencriterium count.

### Layout

1. **Filter bar** — horizontal, 48px tall, `--bg-elev`, 1px `--line`, 12px radius, 16px padding, 16px bottom margin. Contents:
   - Segmented tabs: "Alle", "Ongefactureerd", "Deze maand". 32px tall, same pattern as chart toggle.
   - Search input right: 280px, 36px, mono font, placeholder "Zoek klant of beschrijving".
   - "Nieuwe werkdag" button far right, primary style.
2. **Table** — full width, `--bg-elev`, 1px `--line`, 12px radius, overflow hidden.

### Table

Header row: 40px tall, `--bg-sunk`, bottom 1px `--line`, `.t-micro` column labels in `--ink-3`.

Columns (left → right, widths as fractions of available width):

| Col | Width | Align | Content |
|---|---|---|---|
| Checkbox | 44px | center | 16px square, 4px radius, 1.5px `--line-strong` border. When any row checked, header checkbox becomes indeterminate/checked. |
| Datum | 110px | left | `dd-mm-yyyy` in mono, weekday abbrev below in `.t-micro` `--ink-3` |
| Klant | flex 1 | left | Klant naam in body, project name below in `.t-small` `--ink-3` |
| Beschrijving | flex 1.5 | left | Short description, truncate with ellipsis |
| Uren | 90px | right | Mono, 1 decimal, e.g. "8,0" (Dutch decimal comma) |
| Tarief | 100px | right | Mono, "€ 85,00" |
| Bedrag | 110px | right | Mono, bold-weight 500, e.g. "€ 680,00" |
| Factuur | 120px | left | If invoiced: link pill `--accent-soft` + `--accent-ink` showing "2025-0041". If not: `.t-small` `--ink-4` "— niet gefactureerd" |
| Kebab | 44px | center | 3-dot menu 16px `--ink-3` |

Row: `--row-h` tall (44px normal), 1px bottom `--line`, hover `--bg-hover`. Checked row: `--accent-soft` background, 2px left border `--accent` (inset shadow).

### Floating action bar

Appears at bottom when ≥ 1 row selected. 60px tall, 640px wide, centered, 24px from bottom. `--ink` background, white text, 12px radius, `--shadow-lg`. Slides up 200ms ease-out when first row checked.

Contents:
- Left: count "3 werkdagen geselecteerd"
- Middle: summary "18,5 uur · € 1.572,50" in mono
- Right: two buttons — "Maak factuur" (primary, accent bg) + "Ontkoppel" (ghost)
- Close X far right

---

## Screen: Facturen

Route: `/facturen`. Invoice list with lifecycle management.

### Layout

1. **KPI strip** — 4 cells in a grid (4 columns equal), clickable, act as filters.
   - Each cell: `--bg-elev`, 1px `--line`, 16px radius, 20px padding, 100px tall.
   - Label `.t-micro` `--ink-4` top.
   - Value in `.t-display` 40px.
   - Subline `.t-small` `--ink-3`.
   - Active filter cell: 2px `--accent` border (replaces the `--line`), `--accent-soft` 20% overlay.
   - Cells:
     - **Gefactureerd** — YTD total, count of invoices
     - **Openstaand** — open amount, count
     - **Verlopen** — overdue amount in `--neg`, count in `--neg`
     - **Concept** — draft count
2. **Search + filter bar** — same pattern as Werkdagen. Status tabs: "Alle", "Concept", "Verstuurd", "Betaald", "Verlopen".
3. **Invoice table**:

| Col | Width | Content |
|---|---|---|
| Status | 100px | `<StatusChip>` — see component below |
| Nummer | 130px | `2025-0041` in mono 500 |
| Datum | 110px | In mono |
| Vervaldatum | 110px | In mono; if overdue, text in `--neg` |
| Klant | flex 1 | Name + project small |
| Bedrag | 140px | Mono 500 right-aligned |
| Actie | 120px | Context button: "Verstuur" if draft, "Herinner" if open & near-due, "Markeer betaald" if paid-manual pending, kebab otherwise |

Click row → invoice detail (out of scope for this handoff; full redesign in `factuur_builder.jsx`).

### StatusChip component

Pill, 22px tall, 4px/8px padding, 6px radius, `.t-micro` uppercase. 6px colored dot left.

| Status | Bg | Text | Dot |
|---|---|---|---|
| `concept` | `--bg-sunk` | `--ink-3` | `--ink-4` |
| `verstuurd` | `--accent-soft` | `--accent-ink` | `--accent` |
| `betaald` | `#e6f2e9` (light green) | `#14532d` | `--pos` |
| `verlopen` | `#fbeadb` | `#7c2d12` | `--neg` |

---

## Screen: Factuur-builder

Full-screen overlay (covers sidebar + main). Two-panel layout:

### Left panel (480px, scrollable, `--bg-elev`)

Form fields to build the invoice.

1. **Klant picker** — combobox, 44px, 10px radius. Shows klant name + BTW-nummer below. Chevron right.
2. **Datum + vervaldatum** — two 50/50 inputs, mono.
3. **Factuurnummer** — greyed, auto-generated, mono. Helper text below: "Volgend in reeks · bewerk"
4. **Regel editor** — repeatable rows. Each row 72px, 1px bottom `--line`. Columns: description (flex), aantal (60px, mono), tarief (100px, mono), bedrag (100px, mono, readonly).
   - "+ Regel toevoegen" button below, ghost style.
   - "+ Voeg ongefactureerde werkdagen toe" suggestion card — see below.
5. **Ongefactureerde werkdagen suggestion card**:
   - 16px padding, `--accent-soft` background, `--accent-ink` text, 10px radius, 1px dashed `--accent` border.
   - Title: "3 ongefactureerde werkdagen voor Acme BV" (mono count).
   - Body: total hours + amount.
   - CTA: "Voeg toe aan factuur →" in `--accent-ink`, 500 weight.
6. **BTW-sectie**:
   - Toggle: "BTW-vrijgesteld o.g.v. art. 11 Wet OB" (KOR / small-business exemption). Default ON.
   - When ON: subtotal + "BTW € 0,00" + total = subtotal. Footer note "Kleineondernemersregeling toegepast" in `--ink-3`.
   - When OFF: subtotal + 21% BTW line + total.
7. **Voettekst** — textarea, 80px, mono-serif, pre-filled with bank details + Kvk + BTW number placeholders.
8. **Sticky bottom bar** — 72px, `--bg-elev`, top 1px `--line`. Two buttons: "Opslaan als concept" (ghost) + "Verstuur" (primary, accent).

### Right panel (flex 1, `--bg-sunk`)

Live PDF preview. A4 ratio page (1:√2), shadow-md, centered with 48px padding. Renders the invoice in print typography:

- A4 page background `--bg-elev`, 40mm padding (inner).
- Top: company wordmark + address block right-aligned.
- "FACTUUR" in `.t-h1` 32px, with factuurnummer mono below.
- Two columns: "Aan" (klant) + "Datum / vervaldatum / nummer" right-aligned.
- Table of regels. 3 columns: omschrijving / aantal × tarief / bedrag. Mono numbers, right-align.
- Totals block, right-aligned, 1px `--ink-3` top border above total.
- Footer: IBAN, Kvk, BTW, "Betaling binnen 14 dagen op [IBAN]".
- Art. 11 Wet OB footnote if BTW exempt.

---

## Screen: Kosten (smart inbox)

Route: `/kosten`.

### Layout

1. **Dropzone** — 180px tall, `--bg-sunk`, 2px dashed `--line-strong`, 14px radius, centered content.
   - Drop receipt icon 48px `--ink-3`, label "Sleep bonnetje hierheen of **klik om te uploaden**" in body.
   - Secondary line `.t-small` `--ink-3`: "PDF, JPG, PNG · We lezen bedrag, datum en BTW automatisch uit"
   - On hover/dragover: border → `--accent`, background → `--accent-soft`, dashed → solid.
2. **Category strip** — horizontal bars showing spending per category.
   - Each category: 52px tall row, label left (body + small count), inline bar center (stretches in remaining space), amount right (mono 500).
   - Bar: 8px tall, `--bg-sunk` track, filled in the category's tint (derived from `--ink-3` at 60% by default; specific categories can opt into `--accent`, `--warn`, `--info`).
3. **Recent expenses table** (same table style as Werkdagen):

| Col | Content |
|---|---|
| Datum | dd-mm mono |
| Omschrijving | body + small vendor name |
| Categorie | chip: `--bg-sunk`, `--ink-2`, 6px radius |
| Zakelijk % | slider-like pill: "100%" mono, range 0–100. Click to edit. |
| BTW | mono, e.g. "€ 4,20 (21%)" |
| Bedrag | mono 500 right |
| Bonnetje | paperclip icon — hover shows preview thumbnail |

---

## Screen: Bank

Route: `/bank`. Reconciliation workbench.

### Layout

1. **Match-proposal banner** — sticky at top if ≥ 1 proposal pending.
   - 80px tall, `--bg-elev`, 1px `--line`, 12px radius. 20px padding.
   - Left: icon (shuffle) + title "3 bankmutaties kunnen automatisch gekoppeld worden" + subline "Hoge zekerheid · € 4.870 totaal".
   - Right: "Bekijk voorstel" primary button.
2. **Two-column split** (60/40):
   - **Left: recent transactions** (table):

| Col | Content |
|---|---|
| Datum | mono |
| Omschrijving | vendor/description body + small note |
| Bedrag | mono 500, colored: `--pos` if positive, `--ink` if negative |
| Status | chip: "Gekoppeld aan 2025-0041" (accent-soft) / "Categorie: Software" / "Niet gecategoriseerd" (warn) |

   - **Right: reconcile side panel** (when row selected):
     - `--bg-elev`, 1px `--line`, 16px radius, 24px padding, sticky top 24px.
     - Shows selected tx at top (date, amount in Instrument Serif 40px, description).
     - Section "Voorstellen" lists suggested matches (invoices for incoming, categories for outgoing). Each suggestion: 56px row, radio left, name + small amount right, confidence score as mono % far right. Click a row to commit.
     - "Koppel" primary button at bottom.

---

## Components

These recur across screens. Build them once.

### Button

- Height 36px (normal), 32px (sm), 44px (lg). Radius 10px.
- Font 14px 500, letter-spacing 0.
- **Primary:** `--accent` bg, white text. Hover: darken 8%. Active: darken 12%.
- **Ghost:** transparent bg, 1px `--line-strong` border, `--ink` text. Hover: `--bg-hover`.
- **Subtle:** no border, `--ink-2` text. Hover: `--bg-hover`.
- **Destructive:** `--neg` text on ghost, or `--neg` bg + white on primary-destructive.
- Icon: 16px, 8px gap to label.
- Focus: 2px offset outline `--accent` at 50% opacity.

### Input

- Height 36px, 10px radius, 12px horizontal padding, 1px `--line-strong` border, `--bg-elev` bg.
- Mono font for numeric inputs, sans for text.
- Focus: border `--accent`, 3px halo `--accent` at 15%.
- Placeholder: `--ink-4`.

### Card

- `--bg-elev`, 1px `--line`, 12–16px radius (12 for tables, 16 for hero cards, 20 for dashboard heroes).
- Padding 20–24px.
- **Never use `--shadow-md`** on resting cards — it's noisy. Use only on floating/hovering elements (popovers, menus, the floating action bar, modals).

### Table

See Werkdagen spec. Shared: 40px header row in `--bg-sunk`, body rows at `--row-h`, 1px row dividers in `--line`, hover `--bg-hover`, no zebra striping.

### Chip / Badge

22px pill, 4px/8px padding, 6px radius. `.t-micro` uppercase. Optional 6px leading dot. See StatusChip table above for color combos.

### Modal

- Centered, max-width 560px (or as specified per screen), `--bg-elev`, `--shadow-lg`, 16px radius.
- Backdrop: `rgba(15, 17, 20, 0.4)` in light, `rgba(0, 0, 0, 0.6)` in dark.
- Close with Esc or backdrop click.
- Open: 120ms ease-out, fade + 8px upward translate.

### Kbd

Inline keyboard hint: `<kbd>` styled at 11px mono, `--bg-sunk` bg, 1px `--line` border, 4px radius, 2px/6px padding, vertical-align middle.

---

## Interactions & Behavior

### Navigation

- Sidebar items call `setRoute(name)`. Route is stored in `localStorage.route` so refresh preserves it.
- Keyboard: W/F/D/B shortcuts only fire when no input is focused.
- Back-forward not wired in the prototype; in production, use browser history.

### Command palette

- Opens on ⌘K (mod+K on mac, ctrl+K on windows/linux).
- Fuzzy search across: all nav destinations, "Nieuwe factuur", "Nieuwe werkdag", "Nieuwe klant", all klanten by name, all facturen by number.
- Arrow keys move selection; Enter activates; Esc closes. Tab cycles selection.

### Tweaks panel

The prototype exposes runtime tweaks for theme/accent/density/font via a bottom-right panel. This is **prototype scaffolding only** — do not port the Tweaks panel to production. Instead, expose in Instellingen:
- Theme (light / dark / system)
- Accent color (5 options)
- Density (compact / normal / spacious)
- Font (Inter / IBM Plex / system)

Each is a CSS var mutation on `<html>`, persisted to user settings.

### Animations

- Route change: fade only, 100ms. No slide transitions.
- Row hover: instant (no transition).
- Button hover: 80ms bg transition.
- Modal open: 120ms ease-out.
- Floating action bar: 200ms ease-out transform (translateY).
- Chart hover tooltip: 100ms fade.

No elaborate animations anywhere. The design is calm.

### Number formatting (all Dutch locale)

- Currency: `€ 1.234,56` (space after €, `.` thousands, `,` decimals).
- Dates in tables: `dd-mm-yyyy`.
- Dates in narrative text: `12 okt 2025`.
- Hours: `8,5` (one decimal, comma).
- Percentages: `21%` (no space).
- BTW number: `NL001234567B01` (mono).

Use `Intl.NumberFormat('nl-NL', ...)` and `Intl.DateTimeFormat('nl-NL', ...)`.

---

## State Management

Scope for this handoff is UI structure + visual fidelity. Data model is out of scope but the prototype's mock data in `source/data.jsx` gives a useful shape:

- **Werkdag:** `{ id, datum, klant, project, beschrijving, uren, tarief, factuurnummer?: string }`
- **Factuur:** `{ id, nummer, datum, vervaldatum, klant, regels: [...], subtotaal, btw, totaal, status: 'concept'|'verstuurd'|'betaald'|'verlopen', btwVrijgesteld: boolean }`
- **Uitgave (expense):** `{ id, datum, omschrijving, vendor, categorie, zakelijk: 0..100, bedrag, btw, bonnetje?: url }`
- **Banktransactie:** `{ id, datum, omschrijving, bedrag, matched: boolean, koppeling?: factuurId, categorie?: string }`
- **Klant:** `{ id, naam, kvk, btwNummer, adres, email, defaultTarief }`

Key derived values:
- **Urencriterium progress:** sum of `werkdag.uren` YTD / 1225.
- **Openstaand:** sum of `factuur.totaal` where `status === 'verstuurd'` or `'verlopen'`.
- **Verlopen detection:** any `verstuurd` factuur where `vervaldatum < today` auto-transitions to `verlopen` on read.

---

## Files in this bundle

```
prototype/
  Boekhouding Redesign.html    ← open in a browser, this is the design
source/
  styles.css                    ← design tokens + all styling
  data.jsx                      ← mock data + shared components (StatusChip, Ic icons, formatters)
  dashboard.jsx                 ← Dashboard screen
  pages.jsx                     ← Werkdagen, Facturen, Kosten, Bank
  factuur_builder.jsx           ← Factuur-builder overlay
  app.jsx                       ← Shell, sidebar, topbar, command palette, tweaks
README.md                       ← this file
```

The `source/*.jsx` files are concatenated into the HTML prototype at build time, so they share a global React scope. In a real codebase, split them into proper modules with explicit imports.

---

## Open Questions / Out of Scope

Designs NOT produced in this round (ask if you need them):
- **Klanten** detail page
- **Documenten** (file storage)
- **Jaarafsluiting** wizard — the end-of-year close process. This is probably the most important screen not yet designed; strongly recommended for a v2.
- **Aangifte** (BTW / IB submission) — flows & forms
- **Instellingen** — settings
- **Onboarding** — first-run setup
- **Mobile** — out of scope entirely

All are wired in the sidebar but render a "Binnenkort beschikbaar" placeholder.
