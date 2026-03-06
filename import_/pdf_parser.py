"""PDF text extraction and parsing for dagpraktijk and ANW invoices.

Handles all invoice format variations found across 2023-2025:
- 2023 early: 5-digit numbers, "RH Waarneming" header, klant on line 2
- 2023 late: 3-digit numbers, "Factuuradres:" section
- 2024 early-mid: "Factuuradres:" or left-side klant
- 2024 middle: Footer table with "Factuurbedrag" instead of "Totaal"
- 2024-2025 late: "TestBV Huisartswaarnemer" header, "Totaalbedrag"
- 2025 app-generated: "Nummer:", "Factuur aan:", "BETAALINFORMATIE"
- ANW self-billing: "FACTUURNUMMER :", dienst table, consistent across years
"""

import re
import subprocess
from pathlib import Path


def extract_pdf_text(pdf_path: Path) -> str:
    """Extract text from PDF using pdftotext with layout preservation."""
    result = subprocess.run(
        ['pdftotext', '-layout', str(pdf_path), '-'],
        capture_output=True, text=True,
    )
    return result.stdout


def parse_dutch_amount(s: str) -> float:
    """Parse Dutch currency format to float.

    Examples: '1.234,56' → 1234.56, '639,24' → 639.24, '9.24' → 9.24
    """
    s = s.strip()
    # Remove thousands separators (dots followed by 3 digits)
    # But keep decimal separator (comma)
    # Pattern: dots that are thousands separators have 3 digits after them
    # Strategy: replace all dots, then replace comma with dot
    if ',' in s:
        # Has a comma = decimal separator. Dots are thousands separators.
        s = s.replace('.', '').replace(',', '.')
    else:
        # No comma — the amount is a whole number or uses dots as decimal
        # In Dutch format, whole numbers don't have a dot
        # But '9.24' could be a decimal... In our context:
        # Amounts like '9.24' are from line items (not totals)
        # This is ambiguous. We treat dot-only as potential decimal if < 3 digits after dot.
        pass
    return float(s)


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
        'filename': filename,
    }
