"""PDF text extraction and parsing for dagpraktijk and ANW invoices.

Handles all invoice format variations found across 2023-2026:
- 2023 early: 5-digit numbers, "RH Waarneming" header, klant on line 2
- 2023 late: 3-digit numbers, "Factuuradres:" section
- 2024 early-mid: "Factuuradres:" or left-side klant, Eenheid column
- 2024 middle: Footer table with "Factuurbedrag" instead of "Totaal"
- 2024-2025 late: "TestBV Huisartswaarnemer" header, "Totaalbedrag"
- 2025 Klant2: combined uren+reiskosten on single line (3 euro amounts)
- 2025-2026 app-generated: "Nummer:", "Factuur aan:", "BETAALINFORMATIE"
- 2026 Klant15: multi-line description wrapping, date on different line
- ANW self-billing: "FACTUURNUMMER :", dienst table, consistent across years
"""

import re
import subprocess
from pathlib import Path


def extract_pdf_text(pdf_path: Path) -> str:
    """Extract text from PDF using pdftotext with layout preservation."""
    try:
        result = subprocess.run(
            ['pdftotext', '-layout', str(pdf_path), '-'],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        raise RuntimeError(
            'pdftotext niet gevonden — installeer poppler '
            '(brew install poppler)')
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            'pdftotext timeout na 30 seconden — bestand mogelijk corrupt')
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(f'pdftotext fout: {stderr or "onbekend"}')
    return result.stdout


def parse_dutch_amount(s: str) -> float:
    """Parse Dutch currency format to float.

    Examples: '1.234,56' → 1234.56, '639,24' → 639.24, '9.24' → 9.24
    """
    s = s.strip()
    if not s:
        return 0.0
    # Remove thousands separators (dots followed by 3 digits)
    # But keep decimal separator (comma)
    # Pattern: dots that are thousands separators have 3 digits after them
    # Strategy: replace all dots, then replace comma with dot
    if ',' in s:
        # Has a comma = decimal separator. Dots are thousands separators.
        s = s.replace('.', '').replace(',', '.')
    else:
        # No comma. Check if dot is a thousands separator (exactly 3 digits after)
        # e.g., '1.234' = 1234, but '9.24' = 9.24 (decimal)
        if re.match(r'^\d{1,3}(\.\d{3})+$', s):
            s = s.replace('.', '')
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def parse_dutch_date(s: str) -> str:
    """Parse Dutch date formats to ISO YYYY-MM-DD.

    Handles: DD-MM-YYYY, D-M-YYYY, DD/MM/YYYY, DD-MM-YY
    """
    s = s.strip().replace('/', '-')
    parts = s.split('-')
    if len(parts) != 3:
        return s

    day, month, year = parts
    if len(year) == 2:
        year = '20' + year
    if len(year) != 4:
        return s

    return f"{year}-{int(month):02d}-{int(day):02d}"


def _extract_factuurnummer(text: str) -> str | None:
    """Extract factuurnummer from invoice text.

    Tries multiple patterns in order of specificity.
    """
    for line in text.split('\n'):
        # Pattern 1: "Factuurnummer: YYYY-NNNNN" or "Factuurnummer : YYYY-NNNNN"
        m = re.search(r'Factuurnummer\s*:\s*(\d{4}-\d{2,5})', line)
        if m:
            return m.group(1)

        # Pattern 2: "Nummer: YYYY-NNN" (2025 app-generated)
        m = re.search(r'Nummer:\s*(\d{4}-\d{3})', line)
        if m:
            return m.group(1)

    # Pattern 3: "Factuur YYYY-NNN" (2025-002 format, on its own line)
    for line in text.split('\n'):
        m = re.match(r'\s*Factuur\s+(\d{4}-\d{3})\b', line)
        if m and 'Factuuradres' not in line and 'Factuurdatum' not in line:
            return m.group(1)

    return None


def _extract_factuurdatum(text: str) -> str | None:
    """Extract factuurdatum and convert to YYYY-MM-DD."""
    for line in text.split('\n'):
        m = re.search(r'Factuurdatum[:\s]+([0-9][-/0-9]+)', line)
        if m:
            return parse_dutch_date(m.group(1))
    return None


def _extract_totaal_bedrag(text: str) -> float | None:
    """Extract totaal bedrag using multiple strategies.

    Tries in order: Totaalbedrag, Te betalen bedrag, Factuurbedrag,
    Totaal verschuldigd, then last standalone TOTAAL/Totaal line.
    """
    lines = text.split('\n')

    # Strategy 1: "Totaalbedrag €X"
    for line in lines:
        m = re.search(r'Totaalbedrag\s+€\s*([\d.,]+)', line)
        if m:
            return parse_dutch_amount(m.group(1))

    # Strategy 2: "Te betalen bedrag: €X" (2025 app-generated)
    for line in lines:
        m = re.search(r'Te betalen bedrag[:\s]+€\s*([\d.,]+)', line)
        if m:
            return parse_dutch_amount(m.group(1))

    # Strategy 3: "Factuurbedrag" (2024 middle format — header/data on separate lines)
    for i, line in enumerate(lines):
        if 'Factuurbedrag' in line:
            # Amount might be on same line or next line
            m = re.search(r'€\s*([\d.,]+)', line)
            if m:
                return parse_dutch_amount(m.group(1))
            # Check next line for the amount
            if i + 1 < len(lines):
                m = re.search(r'€\s*([\d.,]+)', lines[i + 1])
                if m:
                    return parse_dutch_amount(m.group(1))

    # Strategy 3b: Footer table "IBAN | Factuurnummer | Totaal" header, amount on next 1-3 lines
    for i, line in enumerate(lines):
        if 'IBAN' in line and 'Totaal' in line:
            for offset in range(1, 4):
                if i + offset < len(lines):
                    m = re.search(r'€\s*([\d.,]+)', lines[i + offset])
                    if m:
                        return parse_dutch_amount(m.group(1))

    # Strategy 4: "Totaal verschuldigd €X" (Klant4/Klant5 format)
    for line in lines:
        m = re.search(r'Totaal verschuldigd\s+€\s*([\d.,]+)', line)
        if m:
            return parse_dutch_amount(m.group(1))

    # Strategy 5: "Eindtotaal €X" (early DDG declaratie format)
    for line in lines:
        m = re.search(r'Eindtotaal\s+€\s*([\d.,]+)', line)
        if m:
            return parse_dutch_amount(m.group(1))

    # Strategy 6: Last standalone TOTAAL/Totaal € line
    # Skip "Totaal uren", "Totaal kilometer", "TOTAAL UREN SPECIFICATIE"
    for line in reversed(lines):
        if re.search(r'totaal\s+(uren|km|kilo|spec)', line, re.IGNORECASE):
            continue
        m = re.search(r'(?:TOTAAL|Totaal)\s+€\s*([\d.,]+)', line)
        if m:
            return parse_dutch_amount(m.group(1))

    return None


def _extract_klant_name(text: str) -> str | None:
    """Extract klant name from invoice text.

    Tries multiple strategies based on format variations.
    """
    lines = text.split('\n')
    skip_words = (
        'TestBV', 'huisartswaarnemer', 'Test Gebruiker', 'Teststraat 1',
        '1234 AB', '1234AB', 'Datum', 'FACTUUR', 'Tel', 'KvK', 'IBAN',
        'Mail:', 'Bank:', 'testuser', '06 000', '0643',
    )

    # Strategy 1: "Factuur aan:" section (2025 app-generated, 2024-041)
    for i, line in enumerate(lines):
        if 'Factuur aan:' in line:
            for j in range(i + 1, min(i + 4, len(lines))):
                candidate = lines[j].strip()
                if candidate and not any(s in candidate for s in skip_words):
                    return candidate
            break

    # Strategy 2: "Factuuradres:" section (2023 late, 2024 early)
    for i, line in enumerate(lines):
        if 'Factuuradres:' in line:
            for j in range(i + 1, min(i + 5, len(lines))):
                candidate = lines[j].strip()
                if candidate and not any(s in candidate for s in skip_words):
                    return candidate
            break

    # Strategy 3: "Aan:" section (2024-041 style)
    for i, line in enumerate(lines):
        if line.strip() == 'Aan:':
            for j in range(i + 1, min(i + 4, len(lines))):
                candidate = lines[j].strip()
                if candidate and not any(s in candidate for s in skip_words):
                    return candidate
            break

    # Strategy 4: "Factuur aan:" at start of line (ANW format)
    for i, line in enumerate(lines):
        m = re.match(r'\s*Factuur aan:\s*(.+)', line)
        if m:
            name = m.group(1).strip()
            if name and not any(s in name for s in skip_words):
                return name

    # Strategy 5: First non-header left-side text (2023 early, 2024 middle, Klant4)
    for line in lines[0:8]:
        parts = re.split(r'\s{5,}', line.strip())
        left = parts[0].strip() if parts else ''
        if left and not any(s in left for s in skip_words) and len(left) > 3:
            # Avoid picking up address lines (postcodes, streets)
            if re.match(r'^\d{4}\s', left):
                continue
            # Skip lines that look like street addresses (word + number at end)
            if re.match(r'^[A-Z][a-z]+\w*\s+\d+\s*$', left):
                continue
            # Skip T.a.v. lines
            if left.startswith('T.a.v'):
                continue
            return left

    # Strategy 6: Indented left-side text (2025-002 format with big right-side header)
    for line in lines[5:20]:
        stripped = line.strip()
        if stripped and not any(s in stripped for s in skip_words):
            # Must look like a practice/person name (not an address or code)
            if re.match(r'^(Huisarts|Dokter|Dhr\.|Mw\.|S\.|M\.|HAP|Gezond)', stripped):
                return stripped

    return None


def _extract_work_dates(text: str) -> list[str]:
    """Extract individual work dates from invoice line items.

    Returns list of YYYY-MM-DD dates.
    """
    dates = []
    for line in text.split('\n'):
        # Match date at start of line (with optional leading spaces)
        # followed by "Waarneming" or "Uurtarief" or "Scheemda" etc.
        m = re.match(
            r'\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\s+'
            r'(?:Waarneming|Uurtarief|Scheemda|.+?dagpraktijk)',
            line,
        )
        if m:
            try:
                dates.append(parse_dutch_date(m.group(1)))
            except (ValueError, IndexError):
                pass
    return dates


def detect_invoice_type(text: str) -> str:
    """Detect whether PDF text is from a dagpraktijk or ANW invoice.

    Returns 'dagpraktijk', 'anw', or 'unknown'.
    """
    if 'FACTUURNUMMER' in text:
        return 'anw'
    if 'Factuur uitgereikt door afnemer' in text:
        return 'anw'
    if 'Declaratienummer' in text and 'Dienst ID' in text:
        return 'anw'
    if re.search(r'(?:Factuurnummer|Nummer)\s*:', text):
        return 'dagpraktijk'
    if 'Waarneming' in text:
        return 'dagpraktijk'
    return 'unknown'


def _derive_km_from_reiskosten(reiskosten: float) -> tuple[float, float]:
    """Derive km count and km_tarief from a reiskosten amount.

    Tries common km rates (0.23, 0.21) to find one that yields a round km count.
    """
    for rate in [0.23, 0.21]:
        km = reiskosten / rate
        if abs(km - round(km)) < 0.01:
            return round(km), rate
    return round(reiskosten / 0.23), 0.23


def extract_dagpraktijk_line_items(text: str) -> list[dict]:
    """Extract structured work day line items from dagpraktijk invoice.

    Handles all format variations:
    - 2024 old: DD-MM-YY dates, "Uren"/"Afstand (km)" columns, separate rows
    - 2025 Klant7: DD/MM/YYYY, "Kilometertarief", separate rows
    - 2025 Klant2: DD/MM/YYYY, 3 euro amounts (tarief+reiskosten+totaal) per line
    - 2026 standard: DD-MM-YYYY, "Reiskosten (retour ...)", separate rows
    - Klant15: multi-line description, date may be on different line than amounts

    Returns list of dicts with keys: datum, uren, tarief, km, km_tarief.
    """
    items = []
    current_date = None
    current_item = None

    km_keywords = ('kilometer', 'reiskosten', 'reisvergoeding', 'afstand')

    for line in text.split('\n'):
        stripped = line.strip()
        if not stripped:
            continue

        lower = stripped.lower()

        # Skip header / summary / footer lines
        if lower.startswith('totaal') or lower.startswith('vrijgesteld'):
            continue
        if lower.startswith('datum') and 'omschrijving' in lower:
            continue
        if any(kw in lower for kw in (
            'betaalinformatie', 'gelieve', 'iban:', 'ten name van',
            'betaaltermijn', 'rekeningnummer',
        )):
            continue

        # Check for a date anywhere in the line
        date_match = re.search(r'(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})', stripped)

        # Find all euro amounts in the line
        euro_amounts = re.findall(r'€\s*([\d.,]+)', stripped)

        # Find the "antal" (last number before the first € sign)
        antal_match = None
        if euro_amounts:
            first_euro_pos = stripped.index('€')
            before_euro = stripped[:first_euro_pos].rstrip()
            antal_match = re.search(r'(\d+(?:[.,]\d+)?)\s*$', before_euro)

        if not antal_match or not euro_amounts:
            # No parseable amount pattern — track date if present
            if date_match:
                new_date = parse_dutch_date(date_match.group(1))
                if new_date and new_date > '2000':
                    current_date = new_date
            continue

        antal = float(antal_match.group(1).replace(',', '.'))

        # Update current_date if this line has a date
        if date_match:
            new_date = parse_dutch_date(date_match.group(1))
            if new_date and new_date > '2000':
                current_date = new_date

        is_km = any(kw in lower for kw in km_keywords)

        if is_km:
            # km line — update the current item
            if current_item:
                current_item['km'] = antal
                current_item['km_tarief'] = parse_dutch_amount(euro_amounts[0])
        elif current_date:
            # uren line — start a new item
            if current_item:
                items.append(current_item)

            tarief = parse_dutch_amount(euro_amounts[0])
            current_item = {
                'datum': current_date,
                'uren': antal,
                'tarief': tarief,
                'km': 0.0,
                'km_tarief': 0.0,
            }

            # Klant2 2025 combined format: 3 euro amounts = tarief, reiskosten, totaal
            # Validate: antal * tarief + reiskosten ≈ total (within €1) to distinguish
            # from Klant4-style lines where 3 amounts have different semantics
            if len(euro_amounts) >= 3:
                reiskosten = parse_dutch_amount(euro_amounts[1])
                total_on_line = parse_dutch_amount(euro_amounts[2])
                expected_total = antal * tarief + reiskosten
                if reiskosten > 0 and abs(expected_total - total_on_line) < 1.0:
                    km, km_tarief = _derive_km_from_reiskosten(reiskosten)
                    current_item['km'] = km
                    current_item['km_tarief'] = km_tarief

    if current_item:
        items.append(current_item)

    return items


def extract_anw_diensten(text: str) -> list[dict]:
    """Extract dienst records grouped by date from ANW self-billing invoice.

    Parses the UREN SPECIFICATIE table. Groups multiple time segments
    (Overleg/Avond/Nacht) per date into a single record.

    Returns list of dicts with keys: datum, dienst_code, uren, bedrag.
    """
    diensten_by_date: dict[str, dict] = {}
    current_code = None
    current_date = None

    for line in text.split('\n'):
        stripped = line.strip()
        if not stripped:
            continue

        # Skip header, summary, and non-data lines
        if 'Dienst ID' in stripped and 'Datum' in stripped:
            continue
        if stripped.startswith('Totaal') or 'TOTAAL' in stripped:
            continue
        # Only skip standalone BTW summary lines, not data rows with "Vrijgesteld"
        if re.match(r'\s*BTW\s+VRIJGESTELD', stripped, re.IGNORECASE):
            continue
        if stripped in ('Naam', 'FACTUUR', 'UREN SPECIFICATIE', 'CONCEPT'):
            continue

        # Pattern 1: Full dienst line with dienst_id and code
        m = re.match(
            r'(\d{5,7})\s+'           # dienst_id
            r'(\S+)\s+'               # dienst code
            r'(\d{2}-\d{2}-\d{4})\s+' # datum
            r'(\d{2}:\d{2})\s+'       # starttijd
            r'(\d{2}:\d{2})\s+'       # eindtijd
            r'([\d.]+)\s+'            # uren
            r'(\w+)\s+'               # tarief naam
            r'€\s*([\d.,]+)\s+'       # tarief
            r'\w+\s+'                 # btw status
            r'€\s*([\d.,]+)',         # subtotaal
            stripped,
        )
        if m:
            current_code = m.group(2)
            datum = parse_dutch_date(m.group(3))
            if datum:
                current_date = datum
            uren = float(m.group(6))
            bedrag = parse_dutch_amount(m.group(9))

            if current_date:
                if current_date not in diensten_by_date:
                    diensten_by_date[current_date] = {
                        'datum': current_date,
                        'dienst_code': current_code,
                        'uren': 0.0,
                        'bedrag': 0.0,
                    }
                diensten_by_date[current_date]['uren'] += uren
                diensten_by_date[current_date]['bedrag'] += bedrag
            continue

        # Pattern 2: Continuation line (no dienst_id / code / date)
        m = re.match(
            r'(\d{2}:\d{2})\s+'       # starttijd
            r'(\d{2}:\d{2})\s+'       # eindtijd
            r'([\d.]+)\s+'            # uren
            r'(\w+)\s+'               # tarief naam
            r'€\s*([\d.,]+)\s+'       # tarief
            r'\w+\s+'                 # btw status
            r'€\s*([\d.,]+)',         # subtotaal
            stripped,
        )
        if m and current_date:
            uren = float(m.group(3))
            bedrag = parse_dutch_amount(m.group(6))

            if current_date not in diensten_by_date:
                diensten_by_date[current_date] = {
                    'datum': current_date,
                    'dienst_code': current_code or '',
                    'uren': 0.0,
                    'bedrag': 0.0,
                }
            diensten_by_date[current_date]['uren'] += uren
            diensten_by_date[current_date]['bedrag'] += bedrag

    return sorted(diensten_by_date.values(), key=lambda d: d['datum'])


def parse_dagpraktijk_pdf(pdf_path: Path) -> dict:
    """Parse a dagpraktijk (self-created) invoice PDF.

    Returns dict with keys:
        factuurnummer: str | None
        factuurdatum: str | None (YYYY-MM-DD)
        totaal_bedrag: float | None
        klant_name: str | None (as found in PDF, needs mapping)
        work_dates: list[str] (YYYY-MM-DD)
        filename: str
    """
    text = extract_pdf_text(pdf_path)
    return parse_dagpraktijk_text(text, pdf_path.name)


def parse_dagpraktijk_text(text: str, filename: str = '') -> dict:
    """Parse dagpraktijk invoice from already-extracted text."""
    return {
        'factuurnummer': _extract_factuurnummer(text),
        'factuurdatum': _extract_factuurdatum(text),
        'totaal_bedrag': _extract_totaal_bedrag(text),
        'klant_name': _extract_klant_name(text),
        'work_dates': _extract_work_dates(text),
        'line_items': extract_dagpraktijk_line_items(text),
        'filename': filename,
    }


def parse_anw_pdf(pdf_path: Path) -> dict:
    """Parse an ANW (self-billing) invoice PDF.

    Returns dict with keys:
        factuurnummer: str | None
        factuurdatum: str | None (YYYY-MM-DD)
        totaal_bedrag: float | None
        klant_name: str | None
        periode: str | None
        dienst_dates: list[str] (YYYY-MM-DD)
        filename: str
    """
    text = extract_pdf_text(pdf_path)
    return parse_anw_text(text, pdf_path.name)


def parse_anw_text(text: str, filename: str = '') -> dict:
    """Parse ANW invoice from already-extracted text."""
    lines = text.split('\n')

    # Factuurnummer: "FACTUURNUMMER : 22470-23-01" or "Declaratienummer : 232137"
    factuurnummer = None
    for line in lines:
        m = re.search(r'FACTUURNUMMER\s*:\s*(\S+)', line)
        if m:
            factuurnummer = m.group(1)
            break
        m = re.search(r'Declaratienummer\s*:\s*(\S+)', line)
        if m:
            factuurnummer = m.group(1)
            break

    # Factuurdatum or Declaratiedatum
    factuurdatum = None
    for line in lines:
        m = re.search(r'(?:FACTUURDATUM|Declaratiedatum)\s*:\s*([0-9][-/0-9]+)', line)
        if m:
            factuurdatum = parse_dutch_date(m.group(1))
            break

    # Periode
    periode = None
    for line in lines:
        m = re.search(r'PERIODE\s*:\s*(\w+)', line)
        if m:
            periode = m.group(1)
            break

    # Totaal: last "TOTAAL €X" line (skip "TOTAAL UREN SPECIFICATIE")
    totaal_bedrag = _extract_totaal_bedrag(text)

    # Klant: "Factuur aan:" or "Locatie :" line
    klant_name = None
    for line in lines:
        m = re.match(r'\s*Factuur aan:\s*(.+)', line)
        if m:
            klant_name = m.group(1).strip()
            break
        # DDG declaratie format: "Locatie : HAP HAP NoordOost"
        m = re.search(r'Locatie\s*:\s*(?:HAP\s+)?(.+)', line)
        if m:
            klant_name = m.group(1).strip()
            break

    # Dienst dates from specification table
    dienst_dates = []
    for line in lines:
        # Match: dienst_id  dienst_code  DD-MM-YYYY  start  end ...
        m = re.search(r'\b(\d{2}-\d{2}-\d{4})\b', line)
        if m and ('Dienst' not in line or re.search(r'\d{6}', line)):
            # Only if line has a dienst ID (6-digit number) or comes after header
            if re.search(r'^\s*\d{5,7}\s', line):
                try:
                    dienst_dates.append(parse_dutch_date(m.group(1)))
                except (ValueError, IndexError):
                    pass

    return {
        'factuurnummer': factuurnummer,
        'factuurdatum': factuurdatum,
        'totaal_bedrag': totaal_bedrag,
        'klant_name': klant_name,
        'periode': periode,
        'dienst_dates': dienst_dates,
        'line_items': extract_anw_diensten(text),
        'filename': filename,
    }
