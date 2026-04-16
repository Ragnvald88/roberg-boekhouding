# Rabobank Directe Bankkoppeling: Haalbaarheidsonderzoek & Voorstel

**Datum:** 2026-04-03
**Status:** Research rapport
**Doel:** Automatisch ophalen van Rabobank-transacties in plaats van handmatige CSV-upload

---

## Executive Summary

Er is **een haalbare route** om Rabobank-transacties automatisch op te halen: via **Enable Banking** als tussenpartij. Dit is de enige realistische optie voor een lokale single-user app. Directe Rabobank API-toegang is niet haalbaar zonder PSD2-licentie of commercieel contract. De integratie vergt eenmalige authenticatie (elke 180 dagen vernieuwen) en kan naast de bestaande CSV-import bestaan.

---

## 1. Huidige Situatie

### Hoe bank-import nu werkt
- Gebruiker download CSV uit Rabo Online Bankieren
- Upload via "Importeer CSV" knop op `/bank` pagina
- Parser (`import_/rabobank_csv.py`) detecteert encoding (UTF-8/ISO-8859-1) en separator (`;` of `,`)
- Velden: datum, bedrag, tegenrekening, tegenpartij, omschrijving (3 velden samengevoegd), betalingskenmerk
- Deduplicatie op basis van `(datum, bedrag, tegenpartij, omschrijving)` count-matching
- CSV wordt gearchiveerd in `data/bank_csv/`
- Na import: automatische factuur-matching (op factuurnummer in omschrijving + bedrag)

### Wat werkt goed
- Robuust en betrouwbaar
- Ondersteunt twee CSV-varianten (oud en nieuw Rabobank-formaat)
- Goede deduplicatie
- Automatische factuur-matching na import

### Wat beter kan
- Handmatige stap: inloggen bij Rabobank, CSV downloaden, uploaden in app
- Risico op vergeten (transacties niet up-to-date)
- Geen real-time inzicht in banksaldo

---

## 2. Onderzochte Opties

### Optie A: Rabobank PSD2 API (Direct)

**Wat het is:** EU-verplichte API voor account-informatie, gebouwd op Berlin Group NextGenPSD2 standaard.

**Vereisten:**
- Geregistreerd als AISP (Account Information Service Provider) bij DNB
- eIDAS QSEAL certificaat van een Qualified Trust Service Provider
- Doorlopende compliance (AML-monitoring, twee bestuurders vereist, jaarlijkse toezichtkosten)

**Kosten:** EUR 6.800-14.000 aanvraagkosten DNB + jaarlijkse toezichtkosten + eIDAS certificaat

**Haalbaarheid: NIET HAALBAAR** -- disproportioneel voor een single-user app. De licentie-eisen zijn ontworpen voor fintech-bedrijven die diensten verlenen aan derden.

---

### Optie B: Rabobank Business Account Insight / Boekhoudkoppeling API

**Wat het is:** Rabobank's eigen API voor boekhoudsoftware-koppelingen. Geen PSD2-licentie nodig.

**Vereisten:**
- EV SSL certificaat (mutual TLS) + EV signing certificaat (JWS)
- Commercieel contract met Rabobank (niet self-service)
- Bedoeld voor softwareplatforms die meerdere klanten bedienen
- Alleen zakelijke rekeningen (Rabo ZZP Rekening kwalificeert)

**Consent:** Onbeperkt geldig (niet de PSD2 90/180-dagen limiet)

**Haalbaarheid: NIET PRAKTISCH** -- Rabobank verwacht een softwareplatform met meerdere gebruikers. EV-certificaten kosten EUR 200-500/jaar, plus weken doorlooptijd. Het commerciele contract is gericht op ISV's, niet op individueel gebruik.

---

### Optie C: GoCardless Bank Account Data (voorheen Nordigen)

**Wat het was:** Gratis aggregatiedienst met PSD2-toegang tot Europese banken. Was de ideale optie.

**Status: DOOD** -- GoCardless accepteert sinds juli 2025 geen nieuwe accounts meer. Bestaande gebruikers werken nog, maar er is geen heropening aangekondigd. De Python SDK is deprecated.

**Haalbaarheid: NIET MOGELIJK** voor nieuwe gebruikers.

---

### Optie D: Enable Banking (AANBEVOLEN)

**Wat het is:** Finse Open Banking aggregator die onder eigen AISP-licentie opereert. Jij als gebruiker hoeft geen eigen licentie te hebben.

**Rabobank-ondersteuning:** Bevestigd. Authenticatie via Rabo Bankieren app (QR-code op desktop, app-switch op mobiel).

**Pricing model:**
- **Gratis voor eigen gebruik** via "Linked Accounts" -- je registreert je eigen rekening(en) en krijgt restricted production access
- Geen contract, KYB of compliance-documentatie nodig voor eigen gebruik
- Alleen je eigen gelinkte rekeningen zijn toegankelijk (geen derden)

**Consent:** 180 dagen geldig. Daarna opnieuw authenticeren via Rabo Bankieren app.

**Technische integratie:**
- REST API met JWT (RS256) authenticatie
- Private key wordt gegenereerd bij app-registratie
- Python: `PyJWT` + `requests` -- geen speciale SDK nodig
- Sandbox beschikbaar voor testen

**Rate limits:** 4 achtergrond-requests per dag per bank (PSD2-beperking). Voldoende voor dagelijkse sync.

**Haalbaarheid: HAALBAAR** -- dit is de enige realistische optie.

---

### Optie E: Andere Aggregators

| Service | Rabobank | Gratis tier | Status |
|---------|----------|-------------|--------|
| Salt Edge | Ja | Verwijderd okt 2025 | Enterprise-only |
| Tink (Visa) | Ja | Nee | Enterprise-only, sales vereist |
| Yapily | Ja | Nee | Vereist eigen eIDAS cert |
| Plaid | Ja | Onbekend | Mogelijk betaald, sales vereist |
| Bizcuit | Ja | Nee | B2B software-integratie |

**Haalbaarheid: GEEN HAALBAAR ALTERNATIEF** naast Enable Banking.

---

### Optie F: Browser Automatisering

**Wat het is:** Selenium/Playwright om Rabobank Online Bankieren te automatiseren en CSV te downloaden.

**Probleem:** Rabobank vereist 2FA via Rabo Bankieren app (QR-code scan). Dit is niet te automatiseren zonder fysieke telefooninteractie. Bovendien is browser-scraping fragiel en in strijd met de gebruiksvoorwaarden van Rabobank.

**Haalbaarheid: NIET HAALBAAR**

---

## 3. Aanbevolen Aanpak: Enable Banking Integratie

### Architectuur

```
Gebruiker klikt "Koppel Rabobank"
        |
        v
App redirect naar Enable Banking auth URL
        |
        v
Enable Banking redirect naar Rabobank
        |
        v
Gebruiker authenticeert via Rabo Bankieren app (QR)
        |
        v
Redirect terug naar app (http://127.0.0.1:8085/bank-callback?code=...)
        |
        v
App wisselt code in voor session_id + account_uid
        |
        v
Session + account opgeslagen in database
        |
        v
"Sync transacties" haalt nieuwe transacties op via API
        |
        v
Transacties worden verwerkt via bestaande import-logica
        |
        v
Automatische factuur-matching (bestaande functionaliteit)
```

### Technische Flow (Python)

```python
# 1. Eenmalig: JWT genereren
import jwt as pyjwt
from datetime import datetime, timezone, timedelta
import requests

private_key = open("data/enablebanking_key.pem", "rb").read()
APP_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"  # uit bedrijfsgegevens

iat = int(datetime.now().timestamp())
token = pyjwt.encode(
    {"iss": "enablebanking.com", "aud": "api.enablebanking.com",
     "iat": iat, "exp": iat + 3600},
    private_key, algorithm="RS256",
    headers={"kid": APP_ID}
)
headers = {"Authorization": f"Bearer {token}"}

# 2. Start autorisatie (eenmalig per 180 dagen)
body = {
    "access": {"valid_until": (datetime.now(timezone.utc) + timedelta(days=180)).isoformat()},
    "aspsp": {"name": "Rabobank", "country": "NL"},
    "state": str(uuid.uuid4()),
    "redirect_url": "http://127.0.0.1:8085/bank-callback",
    "psu_type": "business",  # of "personal"
}
r = requests.post("https://api.enablebanking.com/auth", json=body, headers=headers)
auth_url = r.json()["url"]
# -> redirect gebruiker naar auth_url

# 3. Na callback: session aanmaken
r = requests.post("https://api.enablebanking.com/sessions",
                   json={"code": callback_code}, headers=headers)
session = r.json()
session_id = session["session_id"]
account_uid = session["accounts"][0]["uid"]

# 4. Transacties ophalen (dagelijks)
params = {"date_from": "2026-01-01"}  # of laatste sync-datum
while True:
    r = requests.get(f"https://api.enablebanking.com/accounts/{account_uid}/transactions",
                     params=params, headers=headers)
    data = r.json()
    for txn in data["transactions"]:
        # Map naar bestaand formaat:
        # txn["transactionAmount"]["amount"] -> bedrag
        # txn["bookingDate"] -> datum
        # txn["creditorName"] / txn["debtorName"] -> tegenpartij
        # txn["creditorAccount"]["iban"] / txn["debtorAccount"]["iban"] -> tegenrekening
        # txn["remittanceInformationUnstructured"] -> omschrijving
        pass
    if not data.get("continuation_key"):
        break
    params["continuation_key"] = data["continuation_key"]
```

### Benodigde Wijzigingen in de App

#### Database
Nieuwe tabel of uitbreiding van `bedrijfsgegevens` voor:
- `enablebanking_session_id` TEXT
- `enablebanking_account_uid` TEXT
- `enablebanking_consent_valid_until` TEXT (ISO date)
- `enablebanking_last_sync` TEXT (ISO datetime)

Private key opslaan als bestand in `data/` (niet in database).

#### Nieuwe bestanden
- `import_/enablebanking.py` -- API client (JWT auth, session management, transaction fetch)
- Private key bestand: `data/enablebanking_key.pem`

#### Wijzigingen in bestaande bestanden
- `pages/bank.py` -- Nieuwe UI-sectie:
  - "Koppel Rabobank" knop (start OAuth flow)
  - "Sync transacties" knop (haal nieuwe transacties op)
  - Status-indicator (gekoppeld/niet gekoppeld, consent verloopt op X)
  - Callback route `@ui.page('/bank-callback')`
- `database.py` -- Functies voor session/consent opslag
- `requirements.txt` / `pyproject.toml` -- Toevoegen: `PyJWT`, `cryptography`

#### Hergebruik bestaande logica
- `add_banktransacties()` -- bestaande deduplicatie werkt ook voor API-data
- `find_factuur_matches()` / `apply_factuur_matches()` -- automatische matching na sync
- Mapping van Enable Banking Berlin Group velden naar het bestaande `banktransacties` schema

### Veldmapping

| Enable Banking (Berlin Group) | App (banktransacties) | Notities |
|-------------------------------|----------------------|----------|
| `bookingDate` | `datum` | ISO format, directe match |
| `transactionAmount.amount` | `bedrag` | Float, negatief=uit |
| `creditorAccount.iban` / `debtorAccount.iban` | `tegenrekening` | Afhankelijk van richting |
| `creditorName` / `debtorName` | `tegenpartij` | Afhankelijk van richting |
| `remittanceInformationUnstructured` | `omschrijving` | Primaire omschrijving |
| (niet standaard beschikbaar) | `betalingskenmerk` | Mogelijk in structured remittance info |
| `'api_sync'` | `csv_bestand` | Markering dat het via API kwam |

**Aandachtspunt `betalingskenmerk`:** Dit veld wordt nu uit de Rabobank CSV gehaald en gebruikt voor VA-betalingen classificatie (IB vs ZVW). In de Berlin Group standaard zit dit mogelijk in `remittanceInformationStructured` of moet het uit de ongestructureerde omschrijving geparsed worden. Dit vereist testen met echte Rabobank-data via de sandbox.

---

## 4. Implementatieplan (Globaal)

### Fase 1: Proof of Concept (sandbox)
1. Account aanmaken op enablebanking.com
2. Sandbox-applicatie registreren
3. Test-connectie met Rabobank sandbox
4. Verifieer welke transactievelden Rabobank daadwerkelijk teruggeeft
5. Test veldmapping naar bestaand schema
6. **Go/no-go beslissing** op basis van data-kwaliteit

### Fase 2: Productie-integratie
1. Linked account activeren (eigen Rabobank-rekening)
2. `import_/enablebanking.py` module bouwen
3. Database-migratie voor session-opslag
4. UI-uitbreiding op bank-pagina
5. Callback-route implementeren
6. Sync-functionaliteit met bestaande dedup/matching

### Fase 3: Polish
1. Consent-verloop waarschuwing (bijv. 14 dagen voor expiry)
2. Error handling (rate limits, network failures, expired consent)
3. Optioneel: automatische dagelijkse sync bij app-start

---

## 5. Risico's en Aandachtspunten

| Risico | Impact | Mitigatie |
|--------|--------|-----------|
| Enable Banking stopt gratis tier | Geen API-toegang meer | CSV-import blijft als fallback; kosten evalueren |
| Rabobank wijzigt authenticatie | Tijdelijk geen sync | Enable Banking handelt dit af (zij onderhouden de koppeling) |
| Betalingskenmerk niet in API-data | VA-classificatie werkt niet automatisch | Handmatige correctie of parsing uit omschrijving |
| 4 requests/dag limiet | Max 4x sync per dag | Ruim voldoende voor boekhouding |
| 180-dagen consent verloopt | Moet opnieuw authenticeren | Waarschuwing in UI tonen |
| Enable Banking service-uitval | Tijdelijk geen sync | CSV-import als fallback |

---

## 6. Kosten

| Component | Kosten |
|-----------|--------|
| Enable Banking (linked accounts, eigen gebruik) | Gratis |
| `PyJWT` + `cryptography` Python packages | Gratis (open source) |
| Ontwikkeltijd | ~2-3 sessies |
| Doorlopende kosten | Geen |

---

## 7. Aanbeveling

### Aanbevolen: Enable Banking integratie NAAST bestaande CSV-import

**Waarom:**
1. **Gratis** voor eigen gebruik via linked accounts
2. **Geen licentie nodig** -- Enable Banking is de gelicentieerde AISP
3. **Rabobank bevestigd ondersteund** met sandbox-omgeving
4. **Eenvoudige technische integratie** -- REST API + JWT, geen complexe SDK
5. **Lage risico's** -- CSV-import blijft als fallback bestaan
6. **180 dagen consent** -- slechts 2x per jaar opnieuw authenticeren

**Eerste stap:** Maak een account aan op enablebanking.com, registreer een sandbox-app, en test de Rabobank-koppeling. Dit kost ~30 minuten en geeft direct inzicht in de data-kwaliteit voordat er code geschreven wordt.

### Niet aanbevolen
- Directe Rabobank API (licentie-eisen disproportioneel)
- GoCardless/Nordigen (gesloten voor nieuwe gebruikers)
- Browser automatisering (2FA-barriere, fragiel, ToS-schending)
- Andere aggregators (te duur of enterprise-only)

---

## Bronnen

- [Rabobank Developer Portal](https://docs.developer.rabobank.com/)
- [Rabobank PSD2 Account Information](https://developer.rabobank.nl/overview/account-information)
- [Rabobank Business Account Insight](https://developer.rabobank.nl/overview/business-account-insight)
- [Rabobank Boekhoudkoppeling](https://www.rabobank.nl/en/business/embedded-services/products/accountinformatie/bookkeeping-api)
- [Enable Banking - Nederland](https://enablebanking.com/docs/markets/nl)
- [Enable Banking - Quick Start](https://enablebanking.com/docs/api/quick-start/)
- [Enable Banking - FAQ](https://enablebanking.com/docs/faq/)
- [Enable Banking Python voorbeelden](https://github.com/enablebanking/OpenBankingPythonExamples)
- [GoCardless Bank Account Data (gesloten)](https://bankaccountdata.gocardless.com/new-signups-disabled)
- [DNB PSD2 Licentie-eisen](https://www.dnb.nl/en/sector-information/open-book-supervision/open-book-supervision-sectors/payment-institutions/)
- [Open Banking Tracker - Rabobank](https://www.openbankingtracker.com/provider/rabobank-nl)
