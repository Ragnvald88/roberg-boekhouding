# Fiscal engine

## Basisregels

- **BTW-vrijgesteld** (art. 11 Wet OB) → kosten INCL BTW, geen BTW-aangifte
- **Urencriterium**: 1.225 uur/jaar. Achterwacht (urennorm=0) telt NIET mee
- **Pensioenpremie SPH**: WEL bedrijfskosten
- **AOV**: GEEN bedrijfskosten → Box 1 inkomensvoorziening
- **KIA**: 28% bij investeringen >= ondergrens, per-item drempel configureerbaar per jaar
- **Afschrijvingen**: lineair, restwaarde 10%, eerste jaar pro-rata per maand
- **Representatie**: 80%-regeling, 20% bijtelling op fiscale winst
- **Factuur vereisten**: naam+adres+KvK, factuurnummer YYYY-NNN, vervaldatum 14d, BTW-vrijstellingstekst
- **Factuur datum = issue date** (defaults to today; werkdag dates stay on the line items)
- **ANW diensten**: km tracked but `km_tarief=0` (travel included in ANW tarief)
- **Belastingdienst IBAN**: NL86INGB0002445588

## Engine regels

- **Arbeidskorting input** = fiscale_winst (vóór ZA/SA/MKB), NOT belastbare_winst
- **Tariefsaanpassing**: sinds 2023, deductions at basistarief only
- **Eigen woning**: configurable `ew_naar_partner`. Default True (Boekhouder practice)
- **ZVW grondslag** = belastbare_winst, NOT verzamelinkomen
- **PVV** = 27.65% over min(verzamelinkomen, premiegrondslag)
- **Box 3 rendementen**: must use DEFINITIEVE percentages (not voorlopig)

## Fiscale params (geen hardcoded fallbacks)

Alle jaar-afhankelijke waarden uit DB (`fiscale_params`). Ontbrekende keys → loud `ValueError`, aangifte-pagina toont error-card met link naar Instellingen.

**Alle** velden editable via `/instellingen` (round-2 review): KIA-bracket-velden (`kia_plateau_bedrag`, `kia_plateau_eind`, `kia_afbouw_eind`, `kia_afbouw_pct`), ZA/SA toggles, PVV-percentages, Box 3, partner-toggles (`ew_naar_partner`, `box3_fiscaal_partner`), en de **Arbeidskorting brackets editor**. Gebruiker kan voor elk nieuw belastingjaar via "Jaar toevoegen" een copy-from-vorig-jaar maken en relevante percentages overtypen — geen code-wijziging nodig.

**Uitzondering**: `services/agenda.py:_get_km_tarief_for_year` heeft fallback `0.23` ALLEEN als geen `fiscale_params` row bestaat — bewuste planning-context-uitzondering. /agenda is planning-tool, niet aangifte-engine. Voor aangifte-pagina's blijft de loud-fail-regel onverkort.

## KIA bracket-functie (round-2 review)

Boven `kia_bovengrens`: vast plateau-bedrag (`kia_plateau_bedrag` tot `kia_plateau_eind`), daarna lineaire afbouw (`kia_afbouw_pct` per euro tot `kia_afbouw_eind`), boven `kia_afbouw_eind` is KIA = 0.

Backward-compat: jaren waar bracket-velden 0 zijn (legacy seeds) vallen terug op oude cliff-gedrag (KIA = 0 boven bovengrens) zodat Boekhouder-pinned tests groen blijven.

## `villataks_pct` als named constant

`fiscal/constants.VILLATAKS_PCT_DEFAULT = 2.35` met expliciete bron-comment (Belastingdienst Wet IB 2001 art. 3.112 lid 2). `bereken_eigenwoningforfait` parameter default + `bereken_volledig` fallback gebruiken de constante. Triggert alleen voor WOZ > €1.35M; als BD het percentage ooit jaar-afhankelijk maakt → migreer naar `fiscale_params`.

## Werkdag tarief (round-2)

In edit-mode herstelt `werkdag_form` zowel `km` als `tarief` naar de gestockte werkdag-waarde NA `_load_klant_data` (die zet de klant-default). Voorkomt dat een tarief-wijziging bij de klant een oudere werkdag stilletjes hertarifeert.

## Klant-aliases (PDF-import resolutie)

`resolve_klant(db_path, pdf_name, filename_suffix)` en `resolve_anw_klant(db_path, filename)` in `import_/klant_mapping.py` zijn async DB-queries op `klant_aliases` (geen module-level state meer). 4 strategies voor `resolve_klant`:
1. Exact suffix
2. Exact pdf_text
3. Directe `klanten.naam = ? COLLATE NOCASE`
4. Fuzzy bidirectional substring met `length(pattern) >= 3` en `ORDER BY length(pattern) DESC, klant_id ASC`

ANW-resolutie alleen fuzzy met `instr(LOWER(?), LOWER(pattern))`.

CRUD-helpers in `database.py`: `get/add/delete_klant_alias`, `update_klant_alias_target` (optimistic-lock), `remember_alias` (race-vrij INSERT-first met `IntegrityError`-catch + conflict-detectie), `process_remember_alias` (orchestrator met `on_conflict` callback voor UI-resolutie).

## PDF-parser skip-words

`derive_skip_words(bg)` in `import_/skip_words.py` produceert tuple van GENERIC tokens + tokens uit `bedrijfsgegevens` row (eigen naam, bedrijfsnaam, adres, email + local-part, postcode + plaats split, telefoon-fragmenten via `_normalize_phone_digits` met +31/0031 strip). `_extract_klant_name(text, skip_words=None)` accepteert optionele override; case-insensitive substring matching. `pages/facturen.py` import-flow injecteert `derive_skip_words(bg)` per dialog.

## Atomic PDF write (K2)

`components/utils.write_pdf_atomic(html, output_path, base_url=None)` rendert via WeasyPrint naar unieke `tempfile.mkstemp`-tmpfile in dezelfde directory en doet `os.replace`. Bij crash wordt de tmp opgeruimd via `contextlib.suppress(OSError)` zodat de original render-error niet door een unlink-fail wordt gemaskeerd; bestaande PDF blijft intact. Toegepast in `pages/jaarafsluiting.py:export_pdf` voor jaarcijfers; `components/invoice_generator.py:generate_invoice` heeft hetzelfde patroon inline (heeft `doc` object i.p.v. html string).

## Documenten upload safety (K1)

`pages/documenten.py` heeft 2 helpers:
- `_safe_documenten_basename` loud-fails (ValueError) op path components, NUL bytes, leading dots, of niet-toegestane extensies (.pdf/.jpg/.jpeg/.png)
- `_safe_atomic_write(dest_dir, name, content)` is idempotent (returns `(path, is_new=False)` bij identieke content), kiest `_2.pdf`/`_3.pdf` collision-suffix, schrijft via `tempfile.mkstemp` + `os.replace`, cleanup in `contextlib.suppress(OSError)`

Alle 3 upload-handlers in `/documenten` plus `pages/aangifte.py:handle_upload` (subdir-conventie `AANGIFTE_DIR/jaar/categorie/` behouden) volgen 4-staps-volgorde: year-lock preflight → sanitize → atomic write → DB-row → cleanup-on-fail (alleen als `is_new=True`).
