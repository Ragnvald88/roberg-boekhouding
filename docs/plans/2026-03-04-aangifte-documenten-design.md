# Design: Belastingaangifte Documenten Pagina

**Datum**: 2026-03-04
**Status**: Goedgekeurd, klaar voor implementatie

## Samenvatting
Nieuwe pagina `/aangifte` voor het verzamelen en organiseren van alle documenten die nodig zijn voor de IB-aangifte. Inclusief partner-inkomen invoer, checklist met voortgangsindicator, en gestructureerde bestandsopslag.

## Referentie: bestanden uit 2024/Aangifte map
- WOZ_Taxatieverslag_beschikking_2024.pdf
- Jaaroverzicht-AEGON-Hypotheek (2x, twee hypotheken)
- Jaaropgave_Annelie_2024.pdf (partner, loondienst)
- UPO_ABP_RGebruiker.pdf + UPU_ABP_Nijholt.pdf (pensioen)
- DUO_Overzicht_2024.pdf (studieschuld)
- financieel_jaaroverzicht (3x privé + 1x zakelijk)
- Boekhouder_Aangifte_inkomstenbelasting_2024.pdf (definitieve aangifte)
- Jaaroverzicht_uren_kilometers_2024.pdf (uit app)

## Pagina layout
- Jaar-selector bovenaan
- Voortgangsbalk (X/Y verplichte documenten)
- Partner inkomen sectie (bruto loon + loonheffing, per jaar opgeslagen)
- Documenten checklist per categorie met upload/download/delete per item

## Document categorieën (vaste lijst)

| Categorie | Documenttype | Meerdere | Verplicht |
|-----------|-------------|:-:|:-:|
| eigen_woning | WOZ-beschikking | nee | ja |
| eigen_woning | Hypotheek jaaroverzicht | ja | ja |
| inkomen_partner | Jaaropgave partner | ja | ja |
| pensioen | UPO eigen pensioen | nee | nee |
| pensioen | UPO partner | nee | nee |
| bankzaken | Jaaroverzicht privérekening | ja | nee |
| bankzaken | Jaaroverzicht zakelijke rekening | ja | nee |
| bankzaken | Jaaroverzicht spaarrekening | ja | nee |
| studieschuld | DUO overzicht | nee | nee |
| belastingdienst | Voorlopige aanslag | nee | nee |
| onderneming | Jaaroverzicht uren/km | auto | ja |
| onderneming | Winst & verlies | auto | ja |
| definitieve_aangifte | Ingediende aangifte | nee | nee |

"auto" = gegenereerd door app (link naar jaarafsluiting), geen upload.

## Bestandsopslag
```
data/aangifte/{jaar}/{categorie}/{bestandsnaam}
```
Voorbeeld: `data/aangifte/2024/eigen_woning/WOZ_Taxatieverslag_2024.pdf`

## Database

Nieuwe tabel:
```sql
CREATE TABLE aangifte_documenten (
    id INTEGER PRIMARY KEY,
    jaar INTEGER NOT NULL,
    categorie TEXT NOT NULL,
    documenttype TEXT NOT NULL,
    bestandsnaam TEXT NOT NULL,
    bestandspad TEXT NOT NULL,
    upload_datum TEXT NOT NULL,
    notitie TEXT DEFAULT ''
);
```

Uitbreiding fiscale_params:
```sql
partner_bruto_loon REAL DEFAULT 0
partner_loonheffing REAL DEFAULT 0
```

## YAGNI
- Geen OCR/parsing van PDFs
- Geen MijnBelastingdienst integratie
- Geen Box 3 vermogensberekening
- Geen automatische koppeling partner-inkomen → fiscale berekening
