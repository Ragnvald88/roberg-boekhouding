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
- Trigger: "Bewerken" in row-menu op een concept factuur (type=factuur)
- Opent: **Volledige invoice_builder** met werkdagen pre-loaded en factuurnummer behouden
- NIET de simpele edit popup — die is alleen voor metadata-wijzigingen
- Concept vergoeding/ANW: simpele edit dialog (geen werkdagen om te laden)
- Consistentie: zelfde builder voor aanmaken en bewerken van werkdag-concepts

### Verstuurd/betaald factuur bewerken
- Trigger: "Bewerken" in row-menu
- Opent: **Simpele edit dialog** (datum, klant, bedrag, status, PDF upload/verwijder)
- Geen invoice builder — verstuurde facturen mogen niet structureel gewijzigd worden

### Factuur versturen
- Trigger: "Verstuur via e-mail" in row-menu (alle statussen met PDF)
- Opent Mail.app via AppleScript met pre-filled **plain-text** body + PDF bijlage
- Body is altijd plain text (HTML content + attachments is kapot in Mail.app). Betaallink wordt als URL in de tekst opgenomen, Mail.app maakt er automatisch een clickbare link van.
- Als er nog geen PDF bestaat, wordt deze automatisch gegenereerd vóór versturen
- Status wordt automatisch 'verstuurd' als factuur concept was

### Factuur status lifecycle
- concept → verstuurd (via email of handmatig markeren)
- concept → betaald (direct, voor imports)
- verstuurd → betaald (handmatig of auto-match via bank import)
- verstuurd → concept (escape hatch voor per-ongeluk versturen; status is advisory, niet authoritative)
- betaald → verstuurd (terugdraaien, "markeer onbetaald")
- Ongeldige transitie: betaald → concept (ValueError)

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

### Nieuwe uitgave toevoegen
- Trigger: "Nieuwe uitgave" button op `/kosten`
- Opent: dialog met categorie, bedrag, omschrijving, datum
- "Dit is een investering" checkbox toont extra velden (levensduur, restwaarde, zakelijk%)
- Bon upload optioneel
- "Opslaan & Nieuw" voor bulk-invoer

### Uitgave bewerken
- Trigger: edit button per rij
- Opent: zelfde dialog, pre-filled
- Bon kan vervangen of verwijderd worden

### Activastaat
- Onder de uitgaven-tabel: overzicht van alle investeringen met afschrijvingsberekening
- "Afschrijving aanpassen" per investering: override levensduur of jaarlijkse bedragen

### Uitgaven importeren vanuit archief
- Trigger: "Importeer" button
- Scant het boekhouding-archief op het NAS voor ongeïmporteerde PDFs
- Klik op bestandsnaam opent pre-filled toevoeg-dialog

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
- Openstaande facturen alert → link naar `/facturen`
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
