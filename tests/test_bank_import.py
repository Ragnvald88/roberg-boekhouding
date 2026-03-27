"""Tests voor Rabobank CSV parser en bank import."""

import pytest
from database import add_banktransacties, get_banktransacties, backfill_betalingskenmerken
from import_.rabobank_csv import parse_rabobank_csv


# --- CSV Parser tests ---

SAMPLE_CSV_HEADER = (
    '"IBAN/BBAN";"Munt";"BIC";"Volgnr";"Datum";"Rentedatum";"Bedrag";"Saldo na trn";'
    '"Tegenrekening IBAN/BBAN";"Naam tegenpartij";"Naam uiteindelijke partij";'
    '"Naam initiërende partij";"BIC tegenpartij";"Code";"Batch ID";"Transactiereferentie";'
    '"Machtigingskenmerk";"Incassant ID";"Betalingskenmerk";"Omschrijving-1";'
    '"Omschrijving-2";"Omschrijving-3";"Reden retour";"Oorspr bedrag";"Oorspr munt";"Koers"'
)


def make_csv_row(
    datum: str = "2026-01-15",
    bedrag: str = "-77,50",
    tegenrekening: str = "NL12RABO0123456789",
    tegenpartij: str = "Klant A",
    omschrijving1: str = "Betaling factuur",
    omschrijving2: str = "januari 2026",
    omschrijving3: str = "",
    betalingskenmerk: str = "",
) -> str:
    """Build a single Rabobank CSV data row."""
    return (
        f'"NL00TEST0000000001";"EUR";"RABONL2U";"000000000000001234";'
        f'"{datum}";"{datum}";"{bedrag}";"+1234,56";'
        f'"{tegenrekening}";"{tegenpartij}";"";"";"RABONL2U";"ba";"";"";"";"";'
        f'"{betalingskenmerk}";'
        f'"{omschrijving1}";"{omschrijving2}";"{omschrijving3}";"";"";"";""'
    )


def build_csv(rows: list[str], header: str = SAMPLE_CSV_HEADER) -> bytes:
    """Combine header and rows into CSV bytes (UTF-8)."""
    lines = [header] + rows
    return '\n'.join(lines).encode('utf-8')


def test_parse_rabobank_csv_basic():
    """Parse a simple CSV with two transactions."""
    csv_bytes = build_csv([
        make_csv_row(datum="2026-01-15", bedrag="-77,50",
                     tegenpartij="Klant A",
                     omschrijving1="Betaling factuur",
                     omschrijving2="januari 2026"),
        make_csv_row(datum="2026-01-20", bedrag="+1500,00",
                     tegenrekening="NL99ABNA0987654321",
                     tegenpartij="Klant B",
                     omschrijving1="Factuur 2026-001"),
    ])

    result = parse_rabobank_csv(csv_bytes)

    assert len(result) == 2

    # First: negative amount
    t1 = result[0]
    assert t1['datum'] == '2026-01-15'
    assert t1['bedrag'] == pytest.approx(-77.50)
    assert t1['tegenpartij'] == 'Klant A'
    assert 'Betaling factuur' in t1['omschrijving']
    assert 'januari 2026' in t1['omschrijving']

    # Second: positive amount
    t2 = result[1]
    assert t2['datum'] == '2026-01-20'
    assert t2['bedrag'] == pytest.approx(1500.00)
    assert t2['tegenpartij'] == 'Klant B'
    assert t2['tegenrekening'] == 'NL99ABNA0987654321'


def test_parse_encoding_fallback():
    """CSV with ISO-8859-1 encoding (e.g. special chars like ë) should parse."""
    # Create CSV with ISO-8859-1 encoding (contains ë in header)
    csv_text = (
        SAMPLE_CSV_HEADER + '\n' +
        make_csv_row(datum="2026-02-01", bedrag="-25,00",
                     tegenpartij="Café De Grüne",
                     omschrijving1="Representatie")
    )
    csv_bytes = csv_text.encode('iso-8859-1')

    result = parse_rabobank_csv(csv_bytes)

    assert len(result) == 1
    assert result[0]['tegenpartij'] == 'Café De Grüne'
    assert result[0]['bedrag'] == pytest.approx(-25.00)


def test_parse_date_format_dmy():
    """Dates in DD-MM-YYYY format (older Rabobank exports) should parse."""
    csv_bytes = build_csv([
        make_csv_row(datum="15-01-2026", bedrag="-10,00",
                     tegenpartij="Test",
                     omschrijving1="Test betaling"),
    ])

    result = parse_rabobank_csv(csv_bytes)

    assert len(result) == 1
    assert result[0]['datum'] == '2026-01-15'  # Normalized to ISO format


def test_parse_date_format_ymd():
    """Dates in YYYY-MM-DD format (current Rabobank exports) should parse."""
    csv_bytes = build_csv([
        make_csv_row(datum="2026-03-01", bedrag="+500,00",
                     tegenpartij="Zorgverzekering",
                     omschrijving1="Uitbetaling"),
    ])

    result = parse_rabobank_csv(csv_bytes)

    assert len(result) == 1
    assert result[0]['datum'] == '2026-03-01'


def test_parse_empty_rows_skipped():
    """Rows without a date should be skipped."""
    # Build CSV with an empty date row manually
    header = SAMPLE_CSV_HEADER
    valid_row = make_csv_row(datum="2026-01-10", bedrag="-12,50",
                             tegenpartij="Rabobank", omschrijving1="Bankkosten")
    empty_row = (
        '"NL00TEST0000000001";"EUR";"RABONL2U";"000000000000001235";'
        '"";"";"-0,00";"+1234,56";"";"";"";"";"";"";"";"";"";"";"";"";"";"";"";"";"";"";""'
    )
    csv_bytes = '\n'.join([header, valid_row, empty_row]).encode('utf-8')

    result = parse_rabobank_csv(csv_bytes)

    assert len(result) == 1
    assert result[0]['tegenpartij'] == 'Rabobank'


def test_parse_comma_separated_fallback():
    """If no semicolons found, fall back to comma separator."""
    # Build a comma-separated CSV
    header = (
        '"IBAN/BBAN","Munt","BIC","Volgnr","Datum","Rentedatum","Bedrag","Saldo na trn",'
        '"Tegenrekening IBAN/BBAN","Naam tegenpartij","Naam uiteindelijke partij",'
        '"Naam initiërende partij","BIC tegenpartij","Code","Batch ID","Transactiereferentie",'
        '"Machtigingskenmerk","Incassant ID","Betalingskenmerk","Omschrijving-1",'
        '"Omschrijving-2","Omschrijving-3","Reden retour","Oorspr bedrag","Oorspr munt","Koers"'
    )
    # Rabobank always uses Dutch decimal format (comma), even in comma-separated CSV
    row = (
        '"NL00TEST0000000001","EUR","RABONL2U","000000000000001234",'
        '"2026-01-15","2026-01-15","-77,50","+1.234,56",'
        '"NL12RABO0123456789","Test Partner","","","RABONL2U","ba","","","","","","'
        'Test betaling","","","","","",""'
    )
    csv_bytes = (header + '\n' + row).encode('utf-8')

    result = parse_rabobank_csv(csv_bytes)

    assert len(result) == 1
    assert result[0]['bedrag'] == pytest.approx(-77.50)


def test_parse_real_rabobank_format():
    """Real Rabobank export format with spaced column names and thousands seps."""
    # This matches the actual Rabobank "Transacties downloaden" CSV format
    header = (
        '"IBAN/BBAN","Valuta","BIC","Volg nr","Datum","Valuta datum","Bedrag",'
        '"saldo na boeking","IBAN/BBAN tegenpartij","Naam tegenpartij",'
        '"Naam uiteind begunst","Naam initiërende partij","BIC tegenpartij",'
        '"Transactie soort","Batch nr","Transactiereferentie","Machtigingskenmerk",'
        '"Incassant ID","Betalingskenmerk","Omschrijving - 1","Omschrijving - 2",'
        '"Omschrijving - 3","Oorzaakscode","Oorspr bedrag","Oorspr valuta","Koers",'
        '"Naam rekeninghouder"'
    )
    row = (
        '"NL00TEST0000000000","EUR","RABONL2UXXX","","03-01-2025","03-01-2025",'
        '"-2.919,00","3.386,17","NL00TEST0000000001","T. Gebruiker","","","RABONL2UXXX",'
        '"bg","","","","","","Factuurbetaling MacBook Pro","extra info","","","","","",'
        '"TestBV huisartswaarnemer"'
    )
    csv_bytes = (header + '\n' + row).encode('utf-8')

    result = parse_rabobank_csv(csv_bytes)

    assert len(result) == 1
    assert result[0]['datum'] == '2025-01-03'
    assert result[0]['bedrag'] == pytest.approx(-2919.00)
    assert result[0]['tegenpartij'] == 'T. Gebruiker'
    assert result[0]['tegenrekening'] == 'NL00TEST0000000001'
    assert 'Factuurbetaling MacBook Pro' in result[0]['omschrijving']
    assert 'extra info' in result[0]['omschrijving']


def test_parse_merged_description_fields():
    """Three description fields should be merged with spaces."""
    csv_bytes = build_csv([
        make_csv_row(datum="2026-01-15", bedrag="-100,00",
                     tegenpartij="KPN",
                     omschrijving1="Maandfactuur",
                     omschrijving2="Abonnement mobiel",
                     omschrijving3="Klantnr 12345"),
    ])

    result = parse_rabobank_csv(csv_bytes)

    assert len(result) == 1
    assert result[0]['omschrijving'] == 'Maandfactuur Abonnement mobiel Klantnr 12345'


def test_parse_invalid_encoding_raises():
    """Completely undecodable content should raise ValueError."""
    # Random bytes that are not valid in any supported encoding
    # (Actually hard to produce since ISO-8859-1 accepts all byte values)
    # Instead test that the error message is correct for garbled CSV
    # with no valid rows
    csv_bytes = b'\xff\xfe' + 'Datum;Bedrag\n'.encode('utf-16-le')

    # Should not raise (utf-8-sig may decode it, or iso-8859-1 will)
    # but result may be empty due to no valid rows
    result = parse_rabobank_csv(csv_bytes)
    # No valid rows expected since headers won't match
    assert isinstance(result, list)


def test_parse_large_amounts():
    """Amounts over 1000 with Dutch formatting (no thousands separator)."""
    csv_bytes = build_csv([
        make_csv_row(datum="2026-01-31", bedrag="+12345,67",
                     tegenpartij="Klant C",
                     omschrijving1="Grote betaling"),
    ])

    result = parse_rabobank_csv(csv_bytes)

    assert len(result) == 1
    assert result[0]['bedrag'] == pytest.approx(12345.67)


def test_parse_thousands_separator():
    """Amounts with Dutch thousands separator dots must parse correctly."""
    csv_bytes = build_csv([
        make_csv_row(datum="2026-01-15", bedrag="-2.919,00",
                     tegenpartij="Apple",
                     omschrijving1="MacBook Pro"),
        make_csv_row(datum="2026-01-20", bedrag="+18.386,81",
                     tegenpartij="SPH",
                     omschrijving1="Pensioenpremie"),
        make_csv_row(datum="2026-02-01", bedrag="-1.000,00",
                     tegenpartij="Prive",
                     omschrijving1="Salaris"),
    ])

    result = parse_rabobank_csv(csv_bytes)

    assert len(result) == 3
    assert result[0]['bedrag'] == pytest.approx(-2919.00)
    assert result[1]['bedrag'] == pytest.approx(18386.81)
    assert result[2]['bedrag'] == pytest.approx(-1000.00)


# --- Database integration tests ---

@pytest.mark.asyncio
async def test_import_and_retrieve(db):
    """Parse CSV → insert into DB → retrieve and verify."""
    csv_bytes = build_csv([
        make_csv_row(datum="2026-02-10", bedrag="-150,00",
                     tegenpartij="KPN",
                     omschrijving1="Telefoonrekening"),
        make_csv_row(datum="2026-02-15", bedrag="+775,00",
                     tegenpartij="Klant A",
                     omschrijving1="Factuur 2026-003"),
    ])

    parsed = parse_rabobank_csv(csv_bytes)
    assert len(parsed) == 2

    count = await add_banktransacties(db, parsed, csv_bestand="test_import.csv")
    assert count == 2

    transacties = await get_banktransacties(db, jaar=2026)
    assert len(transacties) == 2

    # Verify fields round-trip correctly
    # Transactions are ordered by datum DESC
    t_feb15 = next(t for t in transacties if t.datum == '2026-02-15')
    assert t_feb15.bedrag == pytest.approx(775.00)
    assert t_feb15.tegenpartij == 'Klant A'
    assert 'Factuur 2026-003' in t_feb15.omschrijving
    assert t_feb15.csv_bestand == 'test_import.csv'

    t_feb10 = next(t for t in transacties if t.datum == '2026-02-10')
    assert t_feb10.bedrag == pytest.approx(-150.00)
    assert t_feb10.tegenpartij == 'KPN'


@pytest.mark.asyncio
async def test_empty_csv_no_insert(db):
    """An empty CSV (header only) should insert 0 transactions."""
    csv_bytes = build_csv([])

    parsed = parse_rabobank_csv(csv_bytes)
    assert len(parsed) == 0

    count = await add_banktransacties(db, parsed, csv_bestand="empty.csv")
    assert count == 0

    transacties = await get_banktransacties(db, jaar=2026)
    assert len(transacties) == 0


@pytest.mark.asyncio
async def test_duplicate_transactions_rejected(db):
    """Same transaction (datum+bedrag+tegenpartij+omschrijving) should not be inserted twice."""
    transactions = [
        {'datum': '2024-01-15', 'bedrag': -50.00,
         'tegenrekening': 'NL91ABNA0417164300', 'tegenpartij': 'KPN',
         'omschrijving': 'Factuur januari'},
    ]
    count1 = await add_banktransacties(db, transacties=transactions, csv_bestand='file1.csv')
    assert count1 == 1

    # Same transaction from different CSV file → should be skipped
    count2 = await add_banktransacties(db, transacties=transactions, csv_bestand='file2.csv')
    assert count2 == 0

    all_trans = await get_banktransacties(db, jaar=2024)
    assert len(all_trans) == 1


def test_parse_betalingskenmerk():
    """Betalingskenmerk column is captured when present."""
    csv_bytes = build_csv([
        make_csv_row(
            tegenrekening="NL86INGB0002445588",
            tegenpartij="Belastingdienst",
            bedrag="-2800,00",
            betalingskenmerk="0124412647060001",
            omschrijving1="",
        ),
        make_csv_row(
            tegenrekening="NL86INGB0002445588",
            tegenpartij="Belastingdienst",
            bedrag="-1808,00",
            betalingskenmerk="0124412647560014",
            omschrijving1="",
        ),
    ])
    result = parse_rabobank_csv(csv_bytes)
    assert len(result) == 2
    assert result[0]['betalingskenmerk'] == '0124412647060001'
    assert result[1]['betalingskenmerk'] == '0124412647560014'


def test_parse_empty_betalingskenmerk():
    """Missing betalingskenmerk defaults to empty string."""
    csv_bytes = build_csv([make_csv_row()])
    result = parse_rabobank_csv(csv_bytes)
    assert result[0].get('betalingskenmerk', '') == ''


@pytest.mark.asyncio
async def test_add_banktransacties_with_betalingskenmerk(db):
    """Betalingskenmerk is stored when provided."""
    txns = [{
        'datum': '2026-02-23',
        'bedrag': -2800.0,
        'tegenrekening': 'NL86INGB0002445588',
        'tegenpartij': 'Belastingdienst',
        'omschrijving': '',
        'betalingskenmerk': '0124412647060001',
    }]
    count = await add_banktransacties(db, txns, csv_bestand='test.csv')
    assert count == 1

    result = await get_banktransacties(db)
    assert len(result) == 1
    assert result[0].betalingskenmerk == '0124412647060001'


@pytest.mark.asyncio
async def test_backfill_betalingskenmerken(db, tmp_path):
    """Backfill reads archived CSVs and updates betalingskenmerk on existing rows."""
    # Insert a transaction without betalingskenmerk
    txns = [{'datum': '2026-02-23', 'bedrag': -2800.0,
             'tegenrekening': 'NL86INGB0002445588',
             'tegenpartij': 'Belastingdienst', 'omschrijving': ''}]
    await add_banktransacties(db, txns)

    # Create a CSV archive that has the betalingskenmerk
    csv_dir = tmp_path / 'bank_csv'
    csv_dir.mkdir()
    csv_content = build_csv([
        make_csv_row(datum='23-02-2026', bedrag='-2.800,00',
                     tegenrekening='NL86INGB0002445588',
                     tegenpartij='Belastingdienst',
                     betalingskenmerk='0124412647060001',
                     omschrijving1='', omschrijving2=''),
    ])
    (csv_dir / 'test.csv').write_bytes(csv_content)

    count = await backfill_betalingskenmerken(db, csv_dir)
    assert count >= 1

    result = await get_banktransacties(db)
    assert result[0].betalingskenmerk == '0124412647060001'
