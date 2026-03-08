"""Tests for PDF invoice parser — covers all format variations 2023-2025."""

import pytest
from import_.pdf_parser import (
    parse_dutch_amount, parse_dutch_date,
    parse_dagpraktijk_text, parse_anw_text,
)
from import_.klant_mapping import resolve_klant, resolve_anw_klant


# ── Amount parsing ──────────────────────────────────────────────────

class TestParseDutchAmount:
    def test_thousands_and_decimals(self):
        assert parse_dutch_amount('4.474,68') == 4474.68

    def test_no_thousands(self):
        assert parse_dutch_amount('639,24') == 639.24

    def test_large_amount(self):
        assert parse_dutch_amount('5.963,56') == 5963.56

    def test_small_amount(self):
        assert parse_dutch_amount('9,24') == 9.24

    def test_whole_number_with_comma(self):
        assert parse_dutch_amount('630,00') == 630.00

    def test_whitespace(self):
        assert parse_dutch_amount('  1.278,48  ') == 1278.48


# ── Date parsing ────────────────────────────────────────────────────

class TestParseDutchDate:
    def test_dd_mm_yyyy_dash(self):
        assert parse_dutch_date('23-05-2023') == '2023-05-23'

    def test_d_m_yyyy_dash(self):
        assert parse_dutch_date('2-1-2024') == '2024-01-02'

    def test_dd_mm_yyyy_slash(self):
        assert parse_dutch_date('19/01/2025') == '2025-01-19'

    def test_dd_mm_yy(self):
        assert parse_dutch_date('15-12-23') == '2023-12-15'

    def test_d_mm_yy(self):
        assert parse_dutch_date('3-01-24') == '2024-01-03'


# ── Dagpraktijk parsing: 2023 early format ──────────────────────────

TEXT_2023_EARLY = """\
TestBV
Centrum K14                                                     RH Waarneming
K. Klant1                                                                          Teststraat 1
Hoofdstraat 1                                                                  1234 AB Teststad
1234 AB Plaats14                                                                  0600000000
                                                                test@example.com




Factuurnummer: 2023-00001                                                           Bank: NL
Factuurdatum: 23-05-2023
Vervaldatum: 13-06-2023



Datum        Omschrijving     Eenheid        Aantal   Tarief                            Totaal

08-05-2023   Waarneming       Uur            9        € 70,00                         € 630,00

             Km woon - werk   Afstand (km)   44       € 0,21                             € 9,24

09-05-2023   Waarneming       Uur            9        € 70,00                         € 630,00

             Km woon - werk   Afstand (km)   44       € 0,21                             € 9,24

                                                      Totaal uren                    € 4.410,00

                                                      Totaal kilometer kosten          € 64,68

                                                      Totaal                         € 4.474,68
"""


class TestDagpraktijk2023Early:
    def test_factuurnummer(self):
        r = parse_dagpraktijk_text(TEXT_2023_EARLY, '2023-00001.pdf')
        assert r['factuurnummer'] == '2023-00001'

    def test_factuurdatum(self):
        r = parse_dagpraktijk_text(TEXT_2023_EARLY, '2023-00001.pdf')
        assert r['factuurdatum'] == '2023-05-23'

    def test_totaal(self):
        r = parse_dagpraktijk_text(TEXT_2023_EARLY, '2023-00001.pdf')
        assert r['totaal_bedrag'] == 4474.68

    def test_klant(self):
        r = parse_dagpraktijk_text(TEXT_2023_EARLY, '2023-00001.pdf')
        assert r['klant_name'] == 'Centrum K14'

    def test_work_dates(self):
        r = parse_dagpraktijk_text(TEXT_2023_EARLY, '2023-00001.pdf')
        assert '2023-05-08' in r['work_dates']
        assert '2023-05-09' in r['work_dates']


# ── Dagpraktijk parsing: 2023 late format ───────────────────────────

TEXT_2023_LATE = """\
Datum                  Omschrijving           Eenheid                Aantal                 Tarief                      Bedrag


 TestBV                                                                                          FACTUUR
 huisartswaarnemer
                                                                                            Factuurnummer:              2023-016
 Teststraat 1                                                                                  Factuurdatum:               30-10-2023
 1234 AB Teststad                                                                          Vervaldatum                 13-11-2023

 Tel. 06 000 00 000
 Mail: test@example.com
 KvK: 00000000
 Bank: Rabobank
 IBAN: NL00 TEST 0000 0000 00




 Factuuradres:
 K. Klant1
 Praktijk K14
 Hoofdstraat 1
 1234 AB Plaats14



        Datum              Omschrijving              Eenheid                  Aantal                   Tarief                BEDRAG
        18-10-23           Waarneming                  Uren                     9            €                  70,00   €              630,00
                       Kilometer woon-werk         Afstand (km)                44            €                   0,21   €                9,24
        25-10-23           Waarneming                  Uren                     9            €                  70,00   €              630,00
                       Kilometer woon-werk         Afstand (km)                44            €                   0,21   €                9,24




                                                                                                     Totaal uren        €            1.890,00
                                                                                         Totaal kilometerkosten         €               27,72
                                                                                                       TOTAAL            €       1.917,72
"""


class TestDagpraktijk2023Late:
    def test_factuurnummer(self):
        r = parse_dagpraktijk_text(TEXT_2023_LATE, '2023-016.pdf')
        assert r['factuurnummer'] == '2023-016'

    def test_factuurdatum(self):
        r = parse_dagpraktijk_text(TEXT_2023_LATE, '2023-016.pdf')
        assert r['factuurdatum'] == '2023-10-30'

    def test_totaal(self):
        r = parse_dagpraktijk_text(TEXT_2023_LATE, '2023-016.pdf')
        assert r['totaal_bedrag'] == 1917.72

    def test_klant(self):
        r = parse_dagpraktijk_text(TEXT_2023_LATE, '2023-016.pdf')
        assert r['klant_name'] == 'K. Klant1'


# ── Dagpraktijk parsing: 2024 middle format (footer totaal) ────────

TEXT_2024_MIDDLE = """\
                                                                      TestBV Huisartswaarnemer


  Praktijk K2                                               Test Gebruiker
  K. Klant2                                                         Teststraat 1
  Hoofdstraat 2                                                      1234 AB Teststad
  1234 AB Plaats2                                                   test@example.com
                                                                       KvK: 00000000



 Factuur
 Factuurnummer      : 2024-007
 Factuurdatum       : 28-02-2024
 Vervaldatum        : 13-03-2024


 Datum          Omschrijving                               Aantal      Tarief per eenheid                     Totaal

 13-2-2024      Uurtarief waarneming                       9           € 70,00                              €630,00

                Kilometertarief woon-werk                  108         € 0,23                                €24,84

 16-2-2024      Uurtarief waarneming                       9           € 70,00                              € 630,00

                Kilometertarief woon-werk                  108         € 0,23                                €24,84




         Rekeningnummer:                              Factuurnummer                         Factuurbedrag
     NL00 TEST 0000 0000 00                               2024-007                            €5.378,72
"""


class TestDagpraktijk2024Middle:
    def test_factuurnummer(self):
        r = parse_dagpraktijk_text(TEXT_2024_MIDDLE, '2024-007_Klant2.pdf')
        assert r['factuurnummer'] == '2024-007'

    def test_factuurdatum(self):
        r = parse_dagpraktijk_text(TEXT_2024_MIDDLE, '2024-007_Klant2.pdf')
        assert r['factuurdatum'] == '2024-02-28'

    def test_totaal_from_footer(self):
        r = parse_dagpraktijk_text(TEXT_2024_MIDDLE, '2024-007_Klant2.pdf')
        assert r['totaal_bedrag'] == 5378.72

    def test_klant(self):
        r = parse_dagpraktijk_text(TEXT_2024_MIDDLE, '2024-007_Klant2.pdf')
        assert r['klant_name'] == 'Praktijk K2'


# ── Dagpraktijk parsing: 2024 IBAN-footer format ────────────────────

TEXT_2024_IBAN_FOOTER = """\
FACTUUR

Factuurnummer: 2024-009
Factuurdatum:     28-3-2024

Datum             Omschrijving                          Aantal             Tarief                Totaal
4-3-2024          Uurtarief waarneming                     9               € 70,00              € 630,00
                  Kilometertarief woon-werk               44               € 0,23               € 10,12


          IBAN                                    Factuurnummer                                 Totaal
 NL00 TEST 0000 0000 00                              2024-009                                 € 5.120,96
"""


class TestDagpraktijk2024IBANFooter:
    def test_totaal(self):
        r = parse_dagpraktijk_text(TEXT_2024_IBAN_FOOTER, '2024-009_Winsum.pdf')
        assert r['totaal_bedrag'] == 5120.96

    def test_factuurnummer(self):
        r = parse_dagpraktijk_text(TEXT_2024_IBAN_FOOTER, '2024-009_Winsum.pdf')
        assert r['factuurnummer'] == '2024-009'


# ── Dagpraktijk parsing: 2024-2025 late format ──────────────────────

TEXT_2024_LATE = """\
                                                              TestBV Huisartswaarnemer

Praktijk K6                                                      Test Gebruiker
K. Klant3                                                                        Teststraat 1
Hoofdstraat 3                                                                 1234 AB Teststad
9363 EV Marum                                                                      Tel: 06 000 7791
                                                                                   KvK: 00000000
                                                                                   NL00TEST 0000 0000 00




FACTUUR

Factuurnummer: 2024-040
Factuurdatum:    20-12-2024
Vervaldatum:     2-1-2025

Datum            Omschrijving                        Aantal         Tarief               Totaal
5-12-2024        Waarneming dagpraktijk                9            € 70,00              € 630,00
                 Kilometertarief woon-werk             54           € 0,23               € 12,42
12-12-2024       Waarneming dagpraktijk                9            € 70,00              € 630,00
                 Kilometertarief woon-werk             54           € 0,23               € 12,42
19-12-2024       Waarneming dagpraktijk                9            € 70,00              € 630,00
                 Kilometertarief woon-werk             54           € 0,23               € 12,42




                                                                    Totaalbedrag         € 1.927,26
"""


class TestDagpraktijk2024Late:
    def test_factuurnummer(self):
        r = parse_dagpraktijk_text(TEXT_2024_LATE, '2024-040.pdf')
        assert r['factuurnummer'] == '2024-040'

    def test_factuurdatum(self):
        r = parse_dagpraktijk_text(TEXT_2024_LATE, '2024-040.pdf')
        assert r['factuurdatum'] == '2024-12-20'

    def test_totaal(self):
        r = parse_dagpraktijk_text(TEXT_2024_LATE, '2024-040.pdf')
        assert r['totaal_bedrag'] == 1927.26

    def test_klant(self):
        r = parse_dagpraktijk_text(TEXT_2024_LATE, '2024-040.pdf')
        assert r['klant_name'] == "Praktijk K6"

    def test_work_dates(self):
        r = parse_dagpraktijk_text(TEXT_2024_LATE, '2024-040.pdf')
        assert '2024-12-05' in r['work_dates']
        assert '2024-12-12' in r['work_dates']
        assert '2024-12-19' in r['work_dates']


# ── Dagpraktijk parsing: 2025 app-generated format ──────────────────

TEXT_2025_APP = """\
TestBV huisartswaarnemer
Test Gebruiker                                                       FACTUUR
Teststraat 1                                                              Nummer: 2025-045
1234 AB Teststad
                                                                      Factuurdatum: 16-12-2025
Tel: 06 0000 0000                                                      Vervaldatum: 29-12-2025
test@example.com
KvK: 00000000
IBAN: NL00 TEST 0000 0000 00


Factuur aan:

K. Klant7
Hoofdstraat 3
9363 EV Marum



Datum                   Omschrijving                            Aantal      Tarief      Totaal
27-11-2025              Waarneming dagpraktijk                    7         € 77,50     € 542,50
                        Reiskosten (retour Groningen – Marum)     52        € 0,23      € 11,96




                                                                           Totaal € 554,46

                                                                             * Vrijgesteld van BTW




BETAALINFORMATIE
IBAN:                   NL00 TEST 0000 0000 00
Ten name van:           TestBV huisartswaarnemer
Onder vermelding van:   2025-045
Te betalen bedrag:      € 554,46
Betaaltermijn:          14 dagen
"""


class TestDagpraktijk2025App:
    def test_factuurnummer(self):
        r = parse_dagpraktijk_text(TEXT_2025_APP, '2025-045.pdf')
        assert r['factuurnummer'] == '2025-045'

    def test_factuurdatum(self):
        r = parse_dagpraktijk_text(TEXT_2025_APP, '2025-045.pdf')
        assert r['factuurdatum'] == '2025-12-16'

    def test_totaal(self):
        r = parse_dagpraktijk_text(TEXT_2025_APP, '2025-045.pdf')
        assert r['totaal_bedrag'] == 554.46

    def test_klant(self):
        r = parse_dagpraktijk_text(TEXT_2025_APP, '2025-045.pdf')
        assert r['klant_name'] == 'K. Klant7'

    def test_work_dates(self):
        r = parse_dagpraktijk_text(TEXT_2025_APP, '2025-045.pdf')
        assert '2025-11-27' in r['work_dates']


# ── Dagpraktijk parsing: 2025-002 (non-standard nummer) ────────────

TEXT_2025_002 = """\
                                                                               TestBV huisartswaarnemer
                                                                               Teststraat 1
                                                                               1234AB Teststad


                                                                               test@example.com
                                                                               0600000000


                                                                               KvK: 00000000
                                                                               Bank: NL00 TEST 0000 0000 00


          Praktijk K6 Plaats3
          T.a.v. M.S.A. Janssen
          Hoofdstraat 3
          9363EV Marum


                                                                               Factuurdatum:        24-01-2025
Factuur 2025-002                                                               Vervaldatum:         07-02-2025
           Omschrijving                                                     Bedrag                      Totaal

Factuur
                                                                             Totaal                 € 2.129,76
"""


class TestDagpraktijk2025_002:
    def test_factuurnummer(self):
        r = parse_dagpraktijk_text(TEXT_2025_002, '2025-002_Klant6.pdf')
        assert r['factuurnummer'] == '2025-002'

    def test_factuurdatum(self):
        r = parse_dagpraktijk_text(TEXT_2025_002, '2025-002_Klant6.pdf')
        assert r['factuurdatum'] == '2025-01-24'

    def test_totaal(self):
        r = parse_dagpraktijk_text(TEXT_2025_002, '2025-002_Klant6.pdf')
        assert r['totaal_bedrag'] == 2129.76

    def test_klant(self):
        r = parse_dagpraktijk_text(TEXT_2025_002, '2025-002_Klant6.pdf')
        assert r['klant_name'] == "Praktijk K6 Plaats3"


# ── Dagpraktijk: special "verschil" invoice (Klant4) ───────────────

TEXT_KLANT4 = """\
Dhr. K. Klant4                                                                                                  Teststraat 1
Hoofdstraat 4                                                                                              1234 AB Teststad

                                     FACTUUR
Betreft:              Factuur aanvullende vergoeding dienstovername 25-12-23
Factuurnummer:        2024-003
Factuurdatum:         9-1-2024
Vervaldatum:          23-1-2024

        25-12-23           Scheemda Avondconsult         Uren        3      € 131,87        € 180,00              € 48,13

                                                       Totaal verschuldigd                                €          144,39
"""


class TestDagpraktijkKlant4:
    def test_factuurnummer(self):
        r = parse_dagpraktijk_text(TEXT_KLANT4, '2024-003_Klant4.pdf')
        assert r['factuurnummer'] == '2024-003'

    def test_factuurdatum(self):
        r = parse_dagpraktijk_text(TEXT_KLANT4, '2024-003_Klant4.pdf')
        assert r['factuurdatum'] == '2024-01-09'

    def test_totaal(self):
        r = parse_dagpraktijk_text(TEXT_KLANT4, '2024-003_Klant4.pdf')
        assert r['totaal_bedrag'] == 144.39

    def test_klant(self):
        r = parse_dagpraktijk_text(TEXT_KLANT4, '2024-003_Klant4.pdf')
        assert r['klant_name'] == 'Dhr. K. Klant4'


# ── ANW parsing: HAP MiddenLand ─────────────────────────────────────

TEXT_ANW_DRENTHE = """\
Factuur aan: HAP MiddenLand spoedpost

FACTUUR
Factuur uitgereikt door afnemer.

FACTUURNUMMER : 22470-23-01
FACTUURDATUM : 16-10-2023
PERIODE : SEPTEMBER

UREN SPECIFICATIE

  Dienst ID     Dienst         Datum    Starttijd      Eindtijd   Uren    Tarief Naam       Tarief             Btw    Subtotaal
  320442        W4-A       30-09-2023      12:30         17:00     4.50      Weekend       € 116,36     Vrijgesteld    € 523,62

   Totaal                                                          4.50                                                € 523,62

                                                                              TOTAAL UREN SPECIFICATIE                  € 523,62

                                                                                         BTW VRIJGESTELD                          -

                                                                                                      TOTAAL            € 523,62
"""


class TestANWDrenthe:
    def test_factuurnummer(self):
        r = parse_anw_text(TEXT_ANW_DRENTHE, '2023-09_DokterDrenthe.pdf')
        assert r['factuurnummer'] == '22470-23-01'

    def test_factuurdatum(self):
        r = parse_anw_text(TEXT_ANW_DRENTHE, '2023-09_DokterDrenthe.pdf')
        assert r['factuurdatum'] == '2023-10-16'

    def test_totaal(self):
        r = parse_anw_text(TEXT_ANW_DRENTHE, '2023-09_DokterDrenthe.pdf')
        assert r['totaal_bedrag'] == 523.62

    def test_klant(self):
        r = parse_anw_text(TEXT_ANW_DRENTHE, '2023-09_DokterDrenthe.pdf')
        assert r['klant_name'] == 'HAP MiddenLand spoedpost'

    def test_periode(self):
        r = parse_anw_text(TEXT_ANW_DRENTHE, '2023-09_DokterDrenthe.pdf')
        assert r['periode'] == 'SEPTEMBER'

    def test_dienst_dates(self):
        r = parse_anw_text(TEXT_ANW_DRENTHE, '2023-09_DokterDrenthe.pdf')
        assert '2023-09-30' in r['dienst_dates']


# ── ANW parsing: DDG / Groningen ────────────────────────────────────

TEXT_ANW_DDG = """\
Factuur aan: HAP NoordOost

APRIL 2024
Factuur uitgereikt door afnemer.

FACTUURNUMMER : 27075-24-01
FACTUURDATUM : 02-05-2024
PERIODE : APRIL

UREN SPECIFICATIE

  Dienst ID     Dienst         Datum    Starttijd   Eindtijd   Uren    Tarief Naam       Tarief             Btw    Subtotaal
  566434        GA2*       21-04-2024      17:00      23:00     6.00      Weekend       € 124,00     Vrijgesteld    € 744,00
  568604       DAC.1*      28-04-2024      17:00      21:00     4.00      Weekend       € 124,00     Vrijgesteld    € 496,00

   Totaal                                                      10.00                                               € 1.240,00

                                                                           TOTAAL UREN SPECIFICATIE                € 1.240,00

                                                                                                   TOTAAL          € 1.240,00
"""


class TestANWDDG:
    def test_factuurnummer(self):
        r = parse_anw_text(TEXT_ANW_DDG, 'Groningen_05-24.pdf')
        assert r['factuurnummer'] == '27075-24-01'

    def test_totaal(self):
        r = parse_anw_text(TEXT_ANW_DDG, 'Groningen_05-24.pdf')
        assert r['totaal_bedrag'] == 1240.00

    def test_dienst_dates(self):
        r = parse_anw_text(TEXT_ANW_DDG, 'Groningen_05-24.pdf')
        assert '2024-04-21' in r['dienst_dates']
        assert '2024-04-28' in r['dienst_dates']


# ── Klant resolution ───────────────────────────────────────────────

MOCK_KLANTEN = {
    'HAP K14': 1,
    'Klant2': 3,
    'HAP MiddenLand': 4,
    'HAP NoordOost': 5,
    "HAP K6": 6,
    'Praktijk K9': 7,
    'Praktijk K13': 8,
    'Praktijk K12': 9,
    'Praktijk K11': 10,
    'K. Klant7': 11,
    'Praktijk K10': 12,
    'K. Klant4': 14,
    'K. Klant5': 15,
    'K. Klant8': 16,
}


# ── ANW parsing: DDG declaratie format ──────────────────────────────

TEXT_ANW_DDG_DECLARATIE = """\
                                                        T. Gebruiker




Declaratienummer : 232137
Declaratiedatum : 05-11-2023                            Locatie      : HAP HAP NoordOost
Betreft          : Afrekening oktober 2023              Naam         : T. Gebruiker


Reguliere diensten
Datum      Omschrijving                                                 Uren    Tarief       Bedrag
18-10-2023 Stadskanaal Avondvisitedienst week - 17:00-23:00             5,00   100,84        504,20
                                                                                             504,20

Extra uren
Datum      Omschrijving                                                 Uren    Tarief       Bedrag
31-10-2023 Overig - Overleg - Overdracht 1x 17-18u 18:00-19:00 uur      1,00   100,84        100,84
                                                                                             100,84




Eindtotaal                                                                                   € 605,04
"""


class TestANWDDGDeclaratie:
    def test_factuurnummer(self):
        r = parse_anw_text(TEXT_ANW_DDG_DECLARATIE, '2023-10_DDG.pdf')
        assert r['factuurnummer'] == '232137'

    def test_factuurdatum(self):
        r = parse_anw_text(TEXT_ANW_DDG_DECLARATIE, '2023-10_DDG.pdf')
        assert r['factuurdatum'] == '2023-11-05'

    def test_totaal(self):
        r = parse_anw_text(TEXT_ANW_DDG_DECLARATIE, '2023-10_DDG.pdf')
        assert r['totaal_bedrag'] == 605.04

    def test_klant(self):
        r = parse_anw_text(TEXT_ANW_DDG_DECLARATIE, '2023-10_DDG.pdf')
        assert r['klant_name'] == 'HAP NoordOost'


# ── Klant resolution ───────────────────────────────────────────────

class TestResolveKlant:
    def test_suffix_winsum(self):
        name, kid = resolve_klant(None, 'Winsum', MOCK_KLANTEN)
        assert name == 'HAP K14'
        assert kid == 1

    def test_suffix_klant2(self):
        name, kid = resolve_klant(None, 'Klant2', MOCK_KLANTEN)
        assert name == 'Klant2'
        assert kid == 3

    def test_suffix_vlagtwedde_maps_to_klant2(self):
        name, kid = resolve_klant(None, 'Vlagtwedde', MOCK_KLANTEN)
        assert name == 'Klant2'
        assert kid == 3

    def test_suffix_marum_maps_to_klant6(self):
        name, kid = resolve_klant(None, 'Marum', MOCK_KLANTEN)
        assert name == "HAP K6"
        assert kid == 6

    def test_pdf_name_gezondheidscentrum_winsum(self):
        name, kid = resolve_klant('Centrum K14', None, MOCK_KLANTEN)
        assert name == 'HAP K14'
        assert kid == 1

    def test_pdf_name_s_klant1(self):
        name, kid = resolve_klant('K. Klant1', None, MOCK_KLANTEN)
        assert name == 'HAP K14'
        assert kid == 1

    def test_pdf_name_klant6_no_apostrophe(self):
        name, kid = resolve_klant("Praktijk K6", None, MOCK_KLANTEN)
        assert name == "HAP K6"
        assert kid == 6

    def test_pdf_name_klant12_no_initials(self):
        name, kid = resolve_klant('Praktijk K12', None, MOCK_KLANTEN)
        assert name == 'Praktijk K12'
        assert kid == 9

    def test_pdf_name_doknord(self):
        name, kid = resolve_klant('HAP NoordOost', None, MOCK_KLANTEN)
        assert name == 'HAP NoordOost'
        assert kid == 5

    def test_suffix_takes_precedence(self):
        """Suffix should win over PDF name when both available."""
        name, kid = resolve_klant('Some Other Name', 'Klant7', MOCK_KLANTEN)
        assert name == 'K. Klant7'
        assert kid == 11

    def test_unknown_returns_none(self):
        name, kid = resolve_klant('Unknown Practice', None, MOCK_KLANTEN)
        assert name is None
        assert kid is None


class TestResolveANWKlant:
    def test_drenthe_2023(self):
        name, kid = resolve_anw_klant('2023-09_DokterDrenthe.pdf', MOCK_KLANTEN)
        assert name == 'HAP MiddenLand'
        assert kid == 4

    def test_drenthe_2024(self):
        name, kid = resolve_anw_klant('Drenthe_02-24.pdf', MOCK_KLANTEN)
        assert name == 'HAP MiddenLand'
        assert kid == 4

    def test_drenthe_2025(self):
        name, kid = resolve_anw_klant('0225_HAP_Drenthe.pdf', MOCK_KLANTEN)
        assert name == 'HAP MiddenLand'
        assert kid == 4

    def test_groningen_2024(self):
        name, kid = resolve_anw_klant('Groningen_05-24.pdf', MOCK_KLANTEN)
        assert name == 'HAP NoordOost'
        assert kid == 5

    def test_groningen_2025(self):
        name, kid = resolve_anw_klant('0225_HAP_Groningen.pdf', MOCK_KLANTEN)
        assert name == 'HAP NoordOost'
        assert kid == 5

    def test_gr_too_short_no_match(self):
        """'Gr' pattern removed — too broad (matched 'background.pdf' etc.)."""
        name, kid = resolve_anw_klant('2512_Gr_Factuur.pdf', MOCK_KLANTEN)
        assert name is None
        assert kid is None
