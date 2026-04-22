# Product Flows — Verwacht Gedrag

Dit document beschrijft hoe de app zich hoort te gedragen vanuit het perspectief
van de gebruiker (huisartswaarnemer, maandelijkse boekhouding, minimale klikken).
Gebruik dit als bron voor `/ux-review`.

---

## Facturen

### Nieuwe factuur aanmaken
- Trigger: "Nieuwe factuur" button op `/facturen`
- Opent: **Volledige invoice_builder** (full-screen, twee panelen: links formulier, rechts live preview)
- Klant-dropdown gesorteerd op meest recent gefactureerd (niet alfabetisch)
- Bij klant selectie: ongefactureerde werkdagen suggesties verschijnen, klik importeert ze
- "Opslaan als concept" slaat op zonder PDF, status='concept'
- "Genereer factuur" maakt PDF + factuurrecord, linkt werkdagen

### Concept factuur bewerken
- Trigger: "Bewerken" in row-menu
- Voorwaarde: status=concept EN niet geïmporteerd (type≠anw EN bron≠import)
- Opent: **ALTIJD de volledige invoice_builder**. Er is geen tweede edit-pad meer.
- Werkdag-concepts: werkdagen pre-loaded, factuurnummer behouden
- Vergoeding-concepts: regels_json pre-loaded voor vrije line-item bewerking

### Verstuurd/betaald factuur "bewerken"
- "Bewerken" is verborgen voor verstuurd/betaald facturen — de invoice builder is alleen voor concepts.
- Om toch te kunnen aanpassen: klik "Markeer als concept" in het row-menu. Dit zet de factuur terug naar concept (met waarschuwingspopup; bij betaald wordt de betaaldatum gewist) via een twee-staps-transitie onder water (betaald → verstuurd → concept).
- Daarna verschijnt "Bewerken" weer en gaat de factuur naar de invoice builder.
- Rationale: voorkomt per-ongeluk aanpassen van afgeronde facturen, terwijl flexibiliteit behouden blijft.

### Geïmporteerde facturen (type=anw of bron=import)
- **Bevroren**: geen "Bewerken" en geen "Markeer als concept" — ongeacht status.
- Wel beschikbaar: Preview, Download PDF, Toon in Finder, Markeer betaald/onbetaald, Verwijderen.
- Rationale: imports weerspiegelen externe facturen — structurele mutatie zou de waarheid vertekenen.

### Factuur versturen
- Trigger: "Verstuur via e-mail" in row-menu (alle statussen met PDF)
- Opent Mail.app via **NSSharingService** (Cocoa Share-Sheet compose-API) met pre-filled HTML body + PDF bijlage
- Body is HTML met een clickable `<a href="…">deze link</a>` op de betaallink. AppleScript `html content` werkt sinds macOS 14 niet meer (Apple markeerde 'm "Does nothing at all") — NSSharingService is de moderne vervanger die HTML + attachment wél samen accepteert.
- Als er nog geen PDF bestaat, wordt deze automatisch gegenereerd vóór versturen
- Status wordt automatisch 'verstuurd' als factuur concept was

### Factuur status lifecycle
- concept → verstuurd (via email of handmatig markeren)
- concept → betaald (direct, voor imports)
- verstuurd → betaald (handmatig of auto-match via bank import)
- verstuurd → concept (escape hatch voor per-ongeluk versturen; status is advisory, niet authoritative)
- betaald → verstuurd (terugdraaien, "markeer onbetaald")
- Ongeldige DB-transitie: betaald → concept (ValueError in `update_factuur_status`)
- "Markeer als concept" UI: wrapt betaald → verstuurd → concept achter één klik met waarschuwingspopup

De state machine is bewust los. Een `verstuurd` flag betekent niet dat de factuur écht verstuurd is — het kan een mis-klik zijn. De gebruiker moet altijd terug kunnen naar concept om te corrigeren. NIET aanscherpen zonder expliciete vraag.

### PDF import
- Trigger: "Importeer" button op `/facturen`
- Upload meerdere PDFs tegelijk
- Auto-detectie: dagpraktijk vs ANW formaat
- Auto-resolutie klantnaam via klant_mapping
- Duplicaat-check op factuurnummer
- Optioneel: werkdagen aanmaken, markeren als betaald

### Factuur preview
- Trigger: "Preview" in row-menu (alleen als PDF bestaat)
- Opent: full-screen dialog met PDF in iframe
- Download button beschikbaar

### Aanvullende facturen-acties (row menu)
- **Markeer als verstuurd**: voor concept facturen — flipt status zonder e-mail te versturen, voor handmatige workflow
- **Markeer als concept**: voor verstuurd/betaald facturen (niet voor imports) — terugzetten naar bewerkbaar met waarschuwingspopup
- **Herinnering versturen**: alleen voor verlopen facturen — opent Mail.app met herinnering body en bestaande PDF
- **Toon in Finder**: macOS reveal van de PDF in Finder
- **Download PDF**: directe download (alternatief voor preview-dialog)

### Facturen-pagina extra UI
- KPI-strip bovenaan: Gefactureerd / Openstaand / Verlopen totalen voor het jaar
- Filter-bar: jaar, klant, status, type — alle combineerbaar

---

## Werkdagen

### Nieuwe werkdag toevoegen
- Trigger: "Nieuwe werkdag" button op `/werkdagen`
- Opent: werkdag dialog (formulier met klant, datum, code, uren, tarief, km)
- Locatie-selectie laadt km automatisch uit klant_locaties
- Achterwacht codes (urennorm=0) krijgen automatisch uren=0
- Opslaan voegt werkdag toe en refresht tabel

### Werkdag bewerken
- Trigger: edit button per rij
- Opent: zelfde werkdag dialog, pre-filled met bestaande data
- Werkdagen die al gefactureerd zijn: bewerkbaar maar factuurnummer blijft

### Factuur maken van selectie
- Trigger: werkdagen selecteren (checkboxes) → "Maak factuur van selectie" button
- Navigeert naar `/facturen` en opent invoice builder met geselecteerde werkdagen

### Exports
- CSV export van gefilterde werkdagen
- Urenregistratie CSV (voor Belastingdienst, alleen urennorm=1)
- Km-logboek CSV (voor Belastingdienst)

---

## Kosten

Bank-transactie-centrische reconciliatie. Bank-debits en manuele (contant) uitgaven verschijnen in één geünificeerde lijst; PDFs worden aan een bank-tx gekoppeld via `uitgaven.bank_tx_id`.

### Pagina-structuur
- Twee tabs: **Transacties** (default, reconciliatie-lijst) en **Investeringen** (activastaat + afschrijvingen, ongewijzigd).
- Boven de tabel: KPI-strip (4 kaarten: Totaal · Te verwerken · Afschrijvingen · Investeringen) + oranje reconciliatie-inbox (top-4 recente rijen die aandacht nodig hebben) + filterbalk (jaar · status · categorie · zoek · Lijst/Per maand toggle).
- Onder de tabel: categorie-breakdown kaart met horizontale balken per categorie.

### Row status
Elke rij heeft één status (sequentieel afgeleid):
- **Ongecategoriseerd** — bank-tx zonder linked uitgave, of uitgave zonder categorie
- **Ontbreekt** — uitgave heeft categorie maar geen PDF
- **Compleet** — categorie + PDF
- Manuele cash-uitgaven krijgen een extra `contant`-badge

### Inline categoriseren
- Elke rij heeft een categorie-dropdown in de tabel (q-btn-dropdown).
- Klik → categorie zetten roept onder water `ensure_uitgave_for_banktx` voor bank-only rijen (lazy-create uitgave) of `update_uitgave` voor bestaande. Year-locked, toast bij year-lock-error.

### Nieuwe uitgave toevoegen (cash-bonnetje)
- Trigger: "Nieuwe uitgave" button op `/kosten`. Alleen voor cash/contant-uitgaven die niet via de bank lopen; bank-uitgaven verschijnen automatisch via CSV-import en worden inline gekoppeld.
- Opent: dialog met categorie, bedrag, omschrijving, datum.
- "Dit is een investering" checkbox toont extra velden (levensduur, restwaarde, zakelijk%).
- Bon upload optioneel.
- "Opslaan & Nieuw" voor bulk-invoer.
- Aangemaakte uitgave heeft `bank_tx_id = NULL`.

### Detail bekijken / bewerken
- Trigger: `more_horiz` button in de row acties-kolom, of klik op een inbox-kaart, of "attach file" button.
- Opent Detail-dialog met drie tabs:
  - **Detail**: bedrag (locked voor bank-linked, editable voor manual), IBAN read-only, categorie, omschrijving/notitie, Investering-toggle met levensduur/restwaarde/zakelijk%, Ontkoppel-knop (alleen bij bank-link).
  - **Factuur**: iframe-preview van bestaande PDF (base64 data URI) + Download/Verwijder — of upload-zone + archief-suggesties uit `find_pdf_matches_for_banktx` met directe Koppel-knop.
  - **Historie**: laatste 12 maanden rijen met dezelfde tegenpartij, met "terugkerende kost"-tip bij ≥3 hits binnen 120 dagen.
- Footer: Annuleren · Verwijder (alleen bij bestaande uitgave) · Opslaan.
- Alle mutaties year-locked.

### Bulk-acties
- Selecteer meerdere rijen → zwarte bulk-balk verschijnt met: **Categorie wijzigen** (lazy-create voor bank-only), **Markeer als privé** (alleen bank-rijen, via `mark_banktx_genegeerd`), **Verwijderen** (alleen uitgave-rijen).
- Per-row year-lock; rijen in afgesloten jaar worden overgeslagen met summary-toast (`N bijgewerkt, M overgeslagen (jaar afgesloten)`).

### Per-maand view
- Toggle rechts in de filterbalk. Rijen worden gegroepeerd per maand met een header-rij die maand-totaal toont. Header-rijen zijn uitgesloten van bulk-selectie.

### Privé / niet-zakelijke bank-transacties
- Per-rij of via bulk "Markeer als privé" zet `banktransacties.genegeerd = 1`. Die rij verdwijnt uit de Kosten-weergave en telt niet mee in KPIs. Bedoeld voor eigen geld-overboekingen, ATM, incidentele privé-debits op de zakelijke rekening.

### Uitgaven importeren vanuit archief
- Trigger: "Importeer" button.
- Scant het boekhouding-archief op het NAS voor ongeïmporteerde PDFs per jaar, gegroepeerd per categorie-folder.
- Bij elke ongeïmporteerde PDF pre-computed de dialog een bank-tx match via `find_banktx_matches_for_pdf`. Bij match toont hij `↔ {tegenpartij} · {datum} · {bedrag}` caption.
- Klik op bestandsnaam opent pre-filled toevoeg-dialog; bij match wordt `bank_tx_id` automatisch meegegeven zodat save direct koppelt.
- Unmatched PDFs worden standalone uitgaven (bank_tx_id NULL).

### Investeringen-tab (activastaat)
- Overzicht van alle investeringen met afschrijvingsberekening (lineair, restwaarde 10%, eerste jaar pro-rata per maand).
- "Afschrijving aanpassen" per investering: override levensduur of jaarlijkse bedragen. Voorgaande jaren (< huidig jaar) zijn vergrendeld — reeds aangegeven bij Belastingdienst.
- Tab wordt lazy-geladen: eerste klik triggert de activastaat-render.

---

## Bank

### CSV import
- Trigger: upload widget bovenaan `/bank` pagina
- Accepteert Rabobank CSV formaat
- Auto-archiveert CSV naar `data/bank_csv/`
- Duplicaat-detectie op (datum, bedrag, tegenpartij, omschrijving)
- **Match-voorstel**: na import toont een preview-dialoog met voorgestelde factuur↔banktransactie matches
- Hoge-zekerheid matches (nummer-match) staan default aangevinkt; lage-zekerheid (bedrag-only, ambiguïteit) tonen ⚠ en moeten expliciet worden aangevinkt
- Pas na klik "Toepassen" worden matches doorgevoerd via `update_factuur_status`

### Transactie categoriseren
- Inline categorie-dropdown per rij
- Categorieën: kosten-categorieën + Omzet/Prive/Belasting/AOV
- **Inline categorie-dropdown** (geen popup-dialog) is bewust: bulk-categoriseren is een hot path en een dialog per rij zou tedious zijn.
- **Suggesties**: ongecategoriseerde transacties van een eerder gecategoriseerde tegenpartij tonen een toverstaf-knop (`auto_fix_high`) naast de dropdown. Een klik past de meest-gebruikte categorie toe. Bij gelijke counts wint de meest recente (`MAX(datum) DESC`). Bron: `get_categorie_suggestions` in `database.py`.

### Bulk acties
- Selecteer rijen → "Verwijder selectie"
- Bevestigingsdialog voorkomt per-ongeluk verwijderen

---

## Dashboard

### KPI kaarten
- Bruto omzet (klikbaar → `/werkdagen`)
- Bedrijfswinst (klikbaar → `/aangifte`)
- Belasting prognose (klikbaar → `/aangifte`)
- Uren richting urencriterium (klikbaar → `/werkdagen`)
- Sparklijn charts tonen maandelijks verloop

### Aandachtspunten
- Ongefactureerde werkdagen alert → link naar `/werkdagen`
- Openstaande facturen alert (met oudste-dagen teller) → link naar `/facturen`
- **Health alerts** (uit `get_health_alerts`): uncategorized banktransacties, verlopen facturen (>14 dagen), concept facturen, ontbrekende fiscale parameters. Ieder met severity (warning/info) en "Bekijk"-knop naar relevante pagina.
- VA betalingen tracking via betalingskenmerk

---

## Aangifte

### 5 tabs voor belastingaangifte
1. **Winst**: invulhulp met copy-buttons, ZA/SA toggles
2. **Prive & aftrek**: WOZ, hypotheek, AOV, lijfrente, VA inputs — auto-save op blur
3. **Box 3**: vermogensinput, partner toggle, auto-save op blur (consistent met Prive-tab)
4. **Overzicht**: complete IB/PVV/ZVW berekening met copy-buttons
5. **Documenten**: upload checklist per documenttype

### Consistentie
- Alle number inputs auto-saven op blur (geen apart "opslaan" button nodig)
- Copy buttons kopiëren raw integer waarde (voor invullen bij Belastingdienst)

---

## Jaarafsluiting

### Jaarcijfers rapport
- 5 tabs: Balans, W&V, Toelichting, Controles, Document
- "Bewerken" toggle voor handmatige balans-aanpassingen
- "Markeer als definitief" maakt een echte snapshot (JSON) van alle fiscale data + balans + parameters. Latere wijzigingen aan werkdagen/facturen/uitgaven muteren de definitieve cijfers niet
- **Pre-flight checklist**: bij klik op "Markeer als definitief" verschijnt eerst een dialoog met data-integriteit warnings (ongefactureerde werkdagen, facturen zonder werkdagen, ontbrekende VA-beschikking, etc.). Bron: `compute_checklist_issues` in `pages/jaarafsluiting.py`. Gebruiker kan doorgaan ("Toch markeren als definitief") — soft gate, geen harde blok.
- "Open vergrendeling" knop: maakt het jaar weer bewerkbaar, historische snapshot blijft bewaard. Bij opnieuw markeren wordt de snapshot overschreven
- "Exporteer PDF" genereert jaarcijfers PDF

### Controles tab
- Data-integriteit checks met links naar relevante pagina's
- Vb: "3 werkdagen zonder factuur" → link naar `/werkdagen`

---

## Instellingen

### Bedrijfsgegevens
- Alle velden bewerkbaar, logo upload
- Wijzigingen verschijnen op volgende factuur

### Fiscale parameters
- Per jaar bewerkbaar (IB schijven, ZA/SA/MKB, KIA, heffingskortingen, etc.)
- Input-validatie: percentages moeten > 0, schijfgrenzen monotoon, ontbrekende verplichte velden worden geweigerd
- "Jaar toevoegen" kopieert van meest recente jaar (vereist minstens één bestaand jaar)

### Backup
- Download ZIP met atomaire database-snapshot (`VACUUM INTO`) + alle bestanden
- Snapshot is veilig tijdens gebruik — geen WAL races
- Database locatie: `~/Library/Application Support/Boekhouding/data/` (lokaal, niet cloud-sync)

### PDF archivering
- Factuur-PDFs worden bij generatie automatisch gekopieerd naar SynologyDrive financieel archief
- Locatie: `~/Library/CloudStorage/SynologyDrive-Main/02_Financieel/Boekhouding_Waarneming/Inkomen en Uitgaven/{jaar}/Inkomsten/{Dagpraktijk|ANW_Diensten}/`
- Best-effort: als SynologyDrive offline is, werkt de app normaal door (alleen warning in log)

---

## Klanten

### CRUD
- Toevoegen via dialog (ook vanuit invoice builder)
- Bewerken: zelfde dialog, pre-filled
- Deactiveren (toggle) of verwijderen (alleen als geen facturen/werkdagen gelinkt)

---

## Cross-page consistenties

- Alle tabellen: `ui.table` (geen AG Grid), meervoudige selectie
- Alle formulieren: via `ui.dialog()` popup
- Alle datums: DD-MM-YYYY weergave, YYYY-MM-DD opslag
- Alle bedragen: `format_euro()` uit `components/utils.py`
- Alle destructieve acties: bevestigingsdialog
- Blocking I/O: altijd `asyncio.to_thread()` voor bestands-operaties
- Jaar-filter: beschikbaar op elke pagina met tijdgebonden data
