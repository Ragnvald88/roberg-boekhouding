# Self-Critique of AUDIT_2026-04-26.md

I re-verified each finding against the actual code. Below is what holds up, what I got wrong, and what I missed. The original audit was directionally useful but had three concrete errors and one significant gap.

## Verdict: ~70% of the audit is correct. Three items need retraction.

---

## Errors that need retracting

### ❌ B6 "Backup/restore UI missing" — **WRONG, retract entirely**
Verified `pages/instellingen.py:139–600`: there's already a **Backup tab** with a working "Download backup" button that uses `VACUUM INTO` exactly as I described. I recommended building a feature that already exists. This was a sloppy miss — I should have grep'd for "VACUUM" or read the Instellingen page before claiming the gap.

**Impact on report**: Remove B6 entirely. The remaining priority list drops from 8 to 7 items.

### ❌ A5 "Modal close-after-refresh race" — **WRONG, retract**
I cited this as "fragile, verify it's held." Actually verified `components/invoice_builder.py:1010–1018` and `1108–1114`: the code explicitly comments `# F-3: refresh the parent table BEFORE closing the dialog` and runs `on_save()` then `dlg.close()` in the right order. CLAUDE.md documents this as an invariant *to maintain* — and it **is** maintained. There is no current bug.

**Impact**: Remove A5 entirely.

### ⚠️ A1 "get_data_counts inflates by concept" — **DOWNGRADE from P1 to P3**
I called this P1 (wrong number on dashboard). Re-checked: `get_data_counts` is consumed by `components/fiscal_utils.py:53` and ultimately surfaces as a "you have N facturen this year" label on `/jaarafsluiting` (line 464). It does not flow into any revenue/KPI/financial number. Worst case: the count line on jaarafsluiting reads "5 facturen" when 1 is concept. Annoying, not a real bug.

There is, however, a related real-but-minor bug at `pages/jaarafsluiting.py:243` — the checklist's `n_facturen == 0` warning won't fire if you only have concept facturen, which is the wrong direction. Also P3.

---

## Things I missed (should have been in the audit)

### 🆕 Stale `/bank` link in `get_health_alerts` *(P2 — concrete bug)*
`database.py:2623` — the uncategorized-bank alert links to `/bank`, which is now a soft-redirect to `/transacties` (since the consolidation in `pages/bank.py:12`). Result: user clicks "Bekijk", lands on `/transacties` **without** the `?status=ongecategoriseerd` filter, and has to re-filter manually. Trivial fix: change link to `/transacties?status=ongecategoriseerd`. This is a more concrete instance of A8 and I should have spotted it directly.

### 🆕 Codex review never produced output
The Codex CLI run timed out at >5 minutes without flushing any output through the `tail -200` pipe, and I killed it. **The fiscal engine (IB tariffs, ZVW grondslag, KIA thresholds, MKB-vrijstelling, tariefsaanpassing, afschrijving pro-rata) is not deeply verified by this audit.** The three Explore agents covered structural concerns (year-locks, sign conventions, SQL filters) but did not deep-dive the math in `fiscal/berekeningen.py`. This is the single biggest gap in the audit. Either: (a) re-run Codex with a smaller scoped prompt (one fiscal file at a time, no `tail` pipe), or (b) accept that fiscal correctness is verified only by `tests/test_fiscal.py` and the existing 884-test suite — which is a reasonable position given the test coverage.

### 🆕 Effort estimates were optimistic
- B5 herinnering workflow (1d) → realistically 1.5–2d once you account for log table + migration + UI + reminder-aware health alert.
- B8 UBL/Peppol export (1.5d) → realistically 2–3d. Peppol BIS Billing 3.0 has schema-validation requirements I waved past. UBL invoice spec is non-trivial (tax categories, customization IDs). I'd actually demote this to "later" unless a real B2B customer asks for it — there's no current pressure.
- B6 retracted (was 0.5d).

Total revised: **~7 dev days, not 8** — and items 1–4 still capture most of the value.

---

## Things I got right (verified)

- **A2 concept-stale escalation** — confirmed, severity is hard-coded `info` regardless of age (`database.py:2647`).
- **A3 stale werkdagen alert missing** — confirmed, `get_health_alerts` checks 4 categories, none for werkdagen.
- **A4 herinnering escalation** — confirmed, single 14-day cutoff with no >30/45/60d escalation.
- **A7 year selector resets** — confirmed, `app.storage.user` only used for `selected_werkdagen` handoff (werkdagen.py:332/380), no global jaar state in layout.
- **A8 unfiltered click-throughs** — confirmed, alerts navigate to bare `/facturen` and `/werkdagen`.
- **B2 hero KPI strip** — confirmed by reading `pages/dashboard.py:230–290`. The 3 cards are Bruto omzet, Bedrijfswinst, Belasting prognose. No openstaand, no te-factureren, no aangifte countdown. The most-actionable number for a working huisarts is buried.

The strongest cluster of the audit remains: **persistent year context (A7) + dashboard KPI restructure (B2/A8) + the missing alerts (A3/A4) + escalation on A2**. That's still where I'd start.

---

## Items where I'm honest about my uncertainty

- **A6 sign-validation in `add_uitgave`/`update_uitgave`** — defensive concern, not a known bug. The codebase IS internally consistent (lazy-create enforces ABS, readers use ABS). Whether to harden is a judgement call; I'd defer until something breaks.
- **A10 bedrijfsgegevens precheck** — I claimed first-invoice-creation crashes silently if Bedrijfsgegevens are incomplete. I didn't actually trigger this path. The claim might overstate the issue: invoice_builder pulls `bg` at line 183 and uses individual fields (`bg.naam`, `bg.adres`) downstream. Empty strings probably render an ugly-but-not-crashing PDF, not a silent crash. **Status: unverified, possibly overstated.** Should re-test before fixing.
- **A11 mark_banktx_genegeerd cascade** — depends on whether the use case "mark a factuur-matched banktx as private" is even reachable in the UI. If the UI doesn't expose the toggle on matched rows, this is a non-issue. Needs UI flow verification.
- **A14 render-time tests for /aangifte and /jaarafsluiting** — claim is "no tests exist." Actually `tests/test_aangifte.py` and `tests/test_jaarafsluiting_snapshot.py` exist; whether they cover the failure-render path I care about (missing fiscale_params, partial snapshot) needs reading the test files.
- **A15 `$parent.$emit`** — already nuanced as "verify in production."

---

## Revised priority list (updated)

| # | Item | Cost | Value | Notes |
|---|---|---|---|---|
| 1 | A2 + A3 + A4 alert improvements | 0.5 d | High | Adds stale-werkdagen + concept-aging + reminder-trigger |
| 2 | A7 persistent year context (B1) | 0.5 d | High | Fixes 5 derivative aesthetic issues |
| 3 | B2 dashboard hero strip + B4 deadline countdown | 1 d | High | Biggest perceived improvement |
| 4 | New: fix `/bank` stale link in alerts (also A8) | 0.25 d | Medium | Concrete bug, trivial fix |
| 5 | B3 tax-set-aside YTD widget | 0.5 d | High | Visible reserve number |
| 6 | B5 herinnering workflow (revised estimate) | 1.5 d | High | Add log table + migration |
| 7 | A14 verify and add render-tests for failure paths | 0.5 d | Medium | Defense |
| 8 | B7 klant statement page | 1 d | Medium | |
| 9 | A6 sign-validation harden (optional) | 0.5 d | Defensive | Defer until needed |
| 10 | B8 UBL export (revised estimate, low urgency) | 2–3 d | Defer | No current pressure |

**~5.25 dev days for items 1–7** (down from ~6.5d). Items 1–3 alone are ~2 days and capture the bulk of perceived value.

---

## Bottom line

The audit's *structural* picture (where work is needed: dashboard, alerts, year context, herinnering tracking) is correct. The *specific findings* needed verification — three claims didn't survive contact with the actual code. The biggest weakness is that the fiscal engine wasn't deeply re-verified; if you want full confidence there, that's a separate focused review with Codex on one file at a time.

Recommendation: **accept the corrected priority list (items 1–4, ~2.25 days) as the next sprint**, defer 5–7 to the sprint after, and treat 8–10 as nice-to-have. Skip B6 (already done) and A5 (no current bug).
