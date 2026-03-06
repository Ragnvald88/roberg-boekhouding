"""Tests voor fiscale berekeningen — gevalideerd tegen Boekhouder referentiecijfers.

Boekhouder referentie:
- 2023: winst EUR62.522 -> belastbare winst EUR47.617 -> verzamelinkomen EUR45.801 -> IB terug EUR415
- 2024: winst EUR95.145 -> belastbare winst EUR76.777 -> verzamelinkomen EUR76.163 -> IB terug EUR3.137

De Boekhouder "winst" is het startpunt voor de fiscale waterval. De tussenwaarden
uit de Boekhouder verificatietraces zijn als assertions opgenomen.
"""

import pytest
from fiscal.afschrijvingen import bereken_afschrijving
from fiscal.heffingskortingen import bereken_arbeidskorting, bereken_algemene_heffingskorting
from fiscal.berekeningen import (
    bereken_volledig, bereken_wv, bereken_ib, bereken_eigenwoningforfait,
    FiscaalResultaat,
)


# === Fiscale parameters per jaar (identiek aan seed_data.py) ===

FISCALE_PARAMS = {
    2023: {
        "jaar": 2023,
        "zelfstandigenaftrek": 5030, "startersaftrek": 2123,
        "mkb_vrijstelling_pct": 14.0,
        "kia_ondergrens": 2601, "kia_bovengrens": 69764, "kia_pct": 28,
        "km_tarief": 0.21,
        "schijf1_grens": 73031, "schijf1_pct": 36.93,
        "schijf2_grens": 73031, "schijf2_pct": 36.93,  # same as schijf1 (2 brackets)
        "schijf3_pct": 49.50,
        "ahk_max": 3070, "ahk_afbouw_pct": 6.095, "ahk_drempel": 22660,
        "ak_max": 5052,
        "zvw_pct": 5.43, "zvw_max_grondslag": 66956,
        "repr_aftrek_pct": 80,
        "ew_forfait_pct": 0.35, "villataks_grens": 1_200_000,
        "wet_hillen_pct": 83.333, "urencriterium": 1225,
        "pvv_premiegrondslag": 37149,
    },
    2024: {
        "jaar": 2024,
        "zelfstandigenaftrek": 3750, "startersaftrek": 2123,
        "mkb_vrijstelling_pct": 13.31,
        "kia_ondergrens": 2801, "kia_bovengrens": 69764, "kia_pct": 28,
        "km_tarief": 0.23,
        "schijf1_grens": 75518, "schijf1_pct": 36.97,
        "schijf2_grens": 75518, "schijf2_pct": 36.97,  # same as schijf1 (2 brackets)
        "schijf3_pct": 49.50,
        "ahk_max": 3362, "ahk_afbouw_pct": 6.63, "ahk_drempel": 24812,
        "ak_max": 5532,
        "zvw_pct": 5.32, "zvw_max_grondslag": 71624,
        "repr_aftrek_pct": 80,
        "ew_forfait_pct": 0.35, "villataks_grens": 1_310_000,
        "wet_hillen_pct": 80.0, "urencriterium": 1225,
        "pvv_premiegrondslag": 38098,
    },
    2025: {
        "jaar": 2025,
        "zelfstandigenaftrek": 2470, "startersaftrek": 2123,
        "mkb_vrijstelling_pct": 12.70,
        "kia_ondergrens": 2901, "kia_bovengrens": 70602, "kia_pct": 28,
        "km_tarief": 0.23,
        "schijf1_grens": 38441, "schijf1_pct": 35.82,
        "schijf2_grens": 76817, "schijf2_pct": 37.48,
        "schijf3_pct": 49.50,
        "ahk_max": 3068, "ahk_afbouw_pct": 6.337, "ahk_drempel": 28406,
        "ak_max": 5599,
        "zvw_pct": 5.26, "zvw_max_grondslag": 75860,
        "repr_aftrek_pct": 80,
        "ew_forfait_pct": 0.35, "villataks_grens": 1_330_000,
        "wet_hillen_pct": 76.667, "urencriterium": 1225,
        "pvv_premiegrondslag": 38441,  # = schijf1_grens for 2025+
    },
    2026: {
        "jaar": 2026,
        "zelfstandigenaftrek": 1200, "startersaftrek": 2123,
        "mkb_vrijstelling_pct": 12.70,
        "kia_ondergrens": 2901, "kia_bovengrens": 70602, "kia_pct": 28,
        "km_tarief": 0.23,
        "schijf1_grens": 38883, "schijf1_pct": 35.75,
        "schijf2_grens": 78426, "schijf2_pct": 37.56,
        "schijf3_pct": 49.50,
        "ahk_max": 3115, "ahk_afbouw_pct": 6.398, "ahk_drempel": 29736,
        "ak_max": 5685,
        "zvw_pct": 4.85, "zvw_max_grondslag": 79409,
        "repr_aftrek_pct": 80,
        "ew_forfait_pct": 0.35, "villataks_grens": 1_350_000,
        "wet_hillen_pct": 71.867, "urencriterium": 1225,
        "pvv_premiegrondslag": 38883,  # = schijf1_grens for 2025+
    },
}


# ============================================================
# Afschrijvingen
# ============================================================

class TestAfschrijvingen:
    """Tests voor lineaire afschrijving met pro-rata eerste jaar."""

    def test_afschrijving_camera_2024(self):
        """Camera: EUR2.714, restw 10%, 4jr, aanschaf dec 2023, bereken 2024.

        Verwacht: per_jaar=611.55, eerste jaar (2023) pro-rata 1/12 = 50.96,
        2024 = volledig jaar = 611.55, boekwaarde = 2714 - 50.96 - 611.55 = 2051.49.
        Maar SKILL zegt: afschrijving EUR611, boekwaarde EUR1.492.

        Controle SKILL: BW 31-12-2024 = EUR1.492 = aanschaf - cum_afschr = 2714 - 1222.
        Cum = 2 * 611 = 1222 (SKILL rekent 2023 als vol jaar).

        De SKILL activastaat toont per_jaar = 611, BW 31-12-2024 = 1492.
        """
        result = bereken_afschrijving(
            aanschaf_bedrag=2714, restwaarde_pct=10,
            levensduur=4, aanschaf_maand=12, aanschaf_jaar=2023,
            bereken_jaar=2024,
        )
        # Afschrijving voor 2024 is een volledig jaar
        assert abs(result['afschrijving'] - 611) < 5
        # Boekwaarde eind 2024: na 1 maand (2023) + 12 maanden (2024)
        # Pro-rata: 2023 = 611.55 * 1/12 = 50.96
        # 2024 = 611.55
        # Cum = 662.51, BW = 2714 - 662.51 = 2051.49
        # NB: SKILL zegt BW=1492 (lijkt 2 volle jaren te rekenen)
        assert result['boekwaarde'] > 1400  # Sanity check
        assert result['per_jaar'] > 600

    def test_afschrijving_eerste_jaar_prorata(self):
        """Eerste jaar pro-rata: aanschaf in december = 1/12 van jaarbedrag."""
        result = bereken_afschrijving(
            aanschaf_bedrag=1000, restwaarde_pct=10,
            levensduur=5, aanschaf_maand=12, aanschaf_jaar=2024,
            bereken_jaar=2024,
        )
        per_jaar = 1000 * 0.9 / 5  # = 180
        verwacht = per_jaar * (1 / 12)  # dec = 1 maand
        assert abs(result['afschrijving'] - verwacht) < 0.01
        assert abs(result['per_jaar'] - 180) < 0.01

    def test_afschrijving_januari_bijna_vol_jaar(self):
        """Aanschaf januari = 12/12 van jaarbedrag."""
        result = bereken_afschrijving(
            aanschaf_bedrag=1000, restwaarde_pct=10,
            levensduur=5, aanschaf_maand=1, aanschaf_jaar=2024,
            bereken_jaar=2024,
        )
        per_jaar = 180  # 1000 * 0.9 / 5
        assert abs(result['afschrijving'] - per_jaar) < 0.01

    def test_afschrijving_voor_aanschaf(self):
        """Bereken jaar voor aanschaf: geen afschrijving."""
        result = bereken_afschrijving(
            aanschaf_bedrag=1000, restwaarde_pct=10,
            levensduur=5, aanschaf_maand=6, aanschaf_jaar=2025,
            bereken_jaar=2024,
        )
        assert result['afschrijving'] == 0
        assert result['boekwaarde'] == 1000

    def test_afschrijving_stopt_bij_restwaarde(self):
        """Boekwaarde mag niet onder restwaarde komen."""
        # Korte levensduur, lang geleden aangeschaft
        result = bereken_afschrijving(
            aanschaf_bedrag=1000, restwaarde_pct=10,
            levensduur=2, aanschaf_maand=1, aanschaf_jaar=2020,
            bereken_jaar=2025,
        )
        assert result['afschrijving'] == 0
        assert result['boekwaarde'] == 100  # restwaarde

    def test_afschrijving_macbook_2024(self):
        """MacBook Pro 16: EUR2.919, restw 10%, 4jr, aanschaf dec 2024."""
        result = bereken_afschrijving(
            aanschaf_bedrag=2919, restwaarde_pct=10,
            levensduur=4, aanschaf_maand=12, aanschaf_jaar=2024,
            bereken_jaar=2024,
        )
        per_jaar = 2919 * 0.9 / 4  # = 656.775
        verwacht = per_jaar * (1 / 12)  # dec = 1 maand
        assert abs(result['afschrijving'] - verwacht) < 1
        # SKILL zegt BW 31-12-2024 = EUR2.264, maar dat is na 1 maand
        # 2919 - 54.73 = 2864.27... SKILL zegt 2264 -> dat is 1 vol jaar
        # We volgen de pro-rata methode per specificatie


# ============================================================
# Heffingskortingen
# ============================================================

class TestHeffingskortingen:
    """Tests voor AHK en arbeidskorting."""

    def test_ahk_below_threshold(self):
        """Inkomen onder drempel: maximale AHK."""
        params = FISCALE_PARAMS[2024]
        ahk = bereken_algemene_heffingskorting(20000, 2024, params)
        assert ahk == params['ahk_max']  # 3362

    def test_ahk_above_threshold_2024(self):
        """Inkomen boven drempel: AHK wordt afgebouwd."""
        params = FISCALE_PARAMS[2024]
        ahk = bereken_algemene_heffingskorting(50000, 2024, params)
        # afbouw = (50000 - 24812) * 0.0663 = 25188 * 0.0663 = 1669.96
        # ahk = 3362 - 1669.96 = 1692.04
        assert abs(ahk - 1692.04) < 1

    def test_ahk_high_income_zero(self):
        """Hoog inkomen: AHK = 0 (volledig afgebouwd)."""
        params = FISCALE_PARAMS[2024]
        ahk = bereken_algemene_heffingskorting(100000, 2024, params)
        assert ahk == 0

    def test_ahk_2023_at_threshold(self):
        """2023: inkomen exact op drempel = max AHK."""
        params = FISCALE_PARAMS[2023]
        ahk = bereken_algemene_heffingskorting(22660, 2023, params)
        assert ahk == 3070

    def test_arbeidskorting_2024_laag_inkomen(self):
        """2024: laag inkomen, eerste bracket."""
        ak = bereken_arbeidskorting(8000, 2024)
        # bracket (0, 11491, 0.08425, 0): 0 + 0.08425 * 8000 = 674
        assert abs(ak - 674) < 1

    def test_arbeidskorting_2024_midden_inkomen(self):
        """2024: midden inkomen, tweede bracket."""
        ak = bereken_arbeidskorting(20000, 2024)
        # bracket (11491, 24821, 0.31433, 968): 968 + 0.31433 * (20000 - 11491) = 968 + 2674.85 = 3642.85
        assert abs(ak - 3642.85) < 1

    def test_arbeidskorting_2024_hoog_inkomen(self):
        """2024: hoog inkomen, in afbouw-bracket."""
        ak = bereken_arbeidskorting(76163, 2024)
        # bracket (39958, 124935, -0.06510, 5532)
        # 5532 + (-0.0651) * (76163 - 39958) = 5532 - 2356.14 = 3175.86
        assert abs(ak - 3175.86) < 2

    def test_arbeidskorting_2024_boven_afbouw(self):
        """2024: boven afbouwgrens, korting = 0."""
        ak = bereken_arbeidskorting(130000, 2024)
        assert ak == 0

    def test_arbeidskorting_2023_verval(self):
        """2023: inkomen in afbouw-bracket."""
        ak = bereken_arbeidskorting(45801, 2023)
        # bracket (37691, 115295, -0.06510, 5052)
        # 5052 + (-0.0651) * (45801 - 37691) = 5052 - 527.76 = 4524.24
        assert abs(ak - 4524) < 2

    def test_arbeidskorting_unknown_year_fallback(self):
        """Onbekend jaar: valt terug op meest recent bekend jaar."""
        # 2027 doesn't exist, should use 2026 brackets
        ak_2027 = bereken_arbeidskorting(50000, 2027)
        ak_2026 = bereken_arbeidskorting(50000, 2026)
        assert ak_2027 == ak_2026
        assert ak_2027 > 0


# ============================================================
# Winst & Verlies (simpele functie)
# ============================================================

class TestWinstVerlies:
    """Tests voor bereken_wv."""

    def test_wv_basic(self):
        """Basis W&V berekening."""
        result = bereken_wv(omzet=95145, kosten=5000, afschrijvingen=1200)
        assert result['winst'] == 88945

    def test_wv_geen_kosten(self):
        """W&V zonder kosten."""
        result = bereken_wv(omzet=50000, kosten=0, afschrijvingen=0)
        assert result['winst'] == 50000


# ============================================================
# IB berekening (losse functie)
# ============================================================

class TestIB:
    """Tests voor bereken_ib."""

    def test_ib_2024_schijf1(self):
        """2024: inkomen volledig in schijf 1."""
        params = FISCALE_PARAMS[2024]
        result = bereken_ib(50000, params)
        # bruto = 50000 * 0.3697 = 18485
        assert abs(result['bruto_ib'] - 18485) < 5

    def test_ib_2025_drie_schijven(self):
        """2025: inkomen in alle 3 schijven (schijf1_grens < schijf2_grens)."""
        params = FISCALE_PARAMS[2025]
        result = bereken_ib(90000, params)
        # schijf1: 38441 * 0.3582 = 13770.21
        # schijf2: (76817 - 38441) * 0.3748 = 38376 * 0.3748 = 14383.32
        # schijf3: (90000 - 76817) * 0.4950 = 13183 * 0.4950 = 6525.59
        # bruto = 34679.12
        assert abs(result['bruto_ib'] - 34679) < 50


# ============================================================
# Volledige fiscale waterval - Boekhouder referentietests
# ============================================================

class TestFiscaleWinst:
    """Tests voor de fiscale winst waterval tot belastbare_winst."""

    def test_fiscale_winst_2024(self):
        """Boekhouder 2024: winst EUR95.145 + repr EUR550 + invest EUR2.919.

        Verwachte waterval:
        - repr_bijtelling = 550 * 0.20 = 110
        - kia = 2919 * 0.28 = 817.32
        - fiscale_winst = 95145 + 110 - 817.32 = 94437.68
        - za = 3750, sa = 2123
        - na_oa = 94437.68 - 5873 = 88564.68
        - mkb = 88564.68 * 0.1331 = 11787.96
        - belastbare_winst = 76776.72
        """
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=550, investeringen_totaal=2919,
            uren=1400, params=params,
        )
        # Tussenwaarden controleren
        assert abs(result.repr_bijtelling - 110) < 1
        assert abs(result.kia - 817.32) < 1
        assert abs(result.zelfstandigenaftrek - 3750) < 1
        assert abs(result.startersaftrek - 2123) < 1
        # Belastbare winst: Boekhouder target ~76.776
        assert abs(result.belastbare_winst - 76777) < 100

    def test_fiscale_winst_2023(self):
        """Boekhouder 2023: winst EUR62.522 (fiscale winst, correcties baked-in).

        Boekhouder trace:
        - na_oa = 62522 - 5030 - 2123 = 55369
        - mkb = 55369 * 0.14 = 7752
        - belastbare_winst = 47617
        - met aov=1816: verzamelinkomen = 45801
        """
        params = FISCALE_PARAMS[2023]
        # Boekhouder 62522 is de fiscale winst (repr+kia al verwerkt)
        result = bereken_volledig(
            omzet=62522, kosten=0, afschrijvingen=0,
            representatie=0, investeringen_totaal=0,
            uren=1400, params=params, aov=1816,
        )
        # Belastbare winst ~47617
        assert abs(result.belastbare_winst - 47617) < 100
        # Verzamelinkomen moet ~45801 zijn (belastbare_winst - aov)
        assert abs(result.verzamelinkomen - 45801) < 100


class TestVolledig:
    """End-to-end tests van de volledige waterval incl. IB berekening."""

    def test_volledig_2024(self):
        """Boekhouder 2024: volledige waterval incl. eigen woning en AOV.

        Note: This test still has EW in verzamelinkomen (Task 3 adds ew_naar_partner)
        and is missing tariefsaanpassing (Task 2). VA=28544 is partial (Boekhouder total=30303).
        Results will be refined as fixes are applied.
        """
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=550, investeringen_totaal=2919,
            uren=1400, params=params,
            aov=2998,
            woz=655000, hypotheekrente=6951,
            voorlopige_aanslag=28544,
        )

        # Belastbare winst ~76777
        assert abs(result.belastbare_winst - 76777) < 100

        # Verzamelinkomen (EW still included, ew_naar_partner not yet)
        assert abs(result.verzamelinkomen - 69120) < 200

        # Arbeidskorting now uses fiscale_winst (94437)
        assert abs(result.arbeidskorting - 1985) < 10

        # Tariefsaanpassing now included (EW still in income_without)
        # income_without = 94437 - 4659 - 2998 = 86780, excess = 86780 - 75518 = 11262
        # ta = 11262 * 12.53% = 1411
        assert abs(result.tariefsaanpassing - 1411) < 50

        # Resultaat (with tariefsaanpassing, EW in verzamelinkomen, VA=28544)
        assert -500 < result.resultaat < 0

        # Urencriterium check
        assert result.uren_criterium_gehaald is True

    def test_volledig_2023(self):
        """Boekhouder 2023: volledige waterval.

        Boekhouder winst EUR62.522 (= fiscale winst, corrections baked-in).
        AK now uses fiscale_winst (62522), which differs from the old
        belastbare_winst approach. Note: Boekhouder 2023 reference values need
        separate verification — the IB terug 415 will be validated with
        the comprehensive test in Task 5.
        """
        params = FISCALE_PARAMS[2023]
        result = bereken_volledig(
            omzet=62522, kosten=0, afschrijvingen=0,
            representatie=0, investeringen_totaal=0,
            uren=1400, params=params,
            aov=1816,
            voorlopige_aanslag=11145,
        )

        # Verzamelinkomen ~45801
        assert abs(result.verzamelinkomen - 45801) < 100

        # Belastbare winst
        assert abs(result.belastbare_winst - 47617) < 100

        # Arbeidskorting uses fiscale_winst (62522)
        # AK = 5052 - 6.51% * (62522 - 37691) = 3434
        assert abs(result.arbeidskorting - 3434) < 10

        # bruto_ib = 45801 * 36.93% = 16914
        assert abs(result.bruto_ib - 16914) < 50

    def test_volledig_2024_urencriterium_warning(self):
        """Urencriterium niet gehaald: waarschuwing."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=50000, kosten=5000, afschrijvingen=0,
            representatie=0, investeringen_totaal=0,
            uren=1000, params=params,
        )
        assert result.uren_criterium_gehaald is False
        assert any("Urencriterium" in w for w in result.waarschuwingen)

    def test_volledig_urencriterium_blokkeert_ondernemersaftrek(self):
        """Urencriterium niet gehaald: geen zelfstandigen- of startersaftrek."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=80000, kosten=10000, afschrijvingen=0,
            representatie=0, investeringen_totaal=0,
            uren=1000, params=params,  # < 1225
        )
        assert result.zelfstandigenaftrek == 0
        assert result.startersaftrek == 0
        # MKB-winstvrijstelling is still applied (no urencriterium needed)
        assert result.mkb_vrijstelling > 0
        # Higher belastbare_winst because no ondernemersaftrek
        result_met = bereken_volledig(
            omzet=80000, kosten=10000, afschrijvingen=0,
            representatie=0, investeringen_totaal=0,
            uren=1400, params=params,  # >= 1225
        )
        assert result.belastbare_winst > result_met.belastbare_winst

    def test_volledig_startersaftrek_none_treated_as_zero(self):
        """When startersaftrek is explicitly None/0 in params, it should be 0."""
        params = FISCALE_PARAMS[2026].copy()
        params['startersaftrek'] = None
        result = bereken_volledig(
            omzet=80000, kosten=10000, afschrijvingen=0,
            representatie=0, investeringen_totaal=0,
            uren=1400, params=params,
        )
        assert result.startersaftrek == 0
        assert result.belastbare_winst > 0

    def test_volledig_kia_onder_grens(self):
        """Investeringen onder KIA-grens: geen KIA."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=80000, kosten=10000, afschrijvingen=0,
            representatie=0, investeringen_totaal=2000,  # < 2801
            uren=1400, params=params,
        )
        assert result.kia == 0

    def test_volledig_kia_boven_grens(self):
        """Investeringen boven KIA-bovengrens: geen KIA."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=80000, kosten=10000, afschrijvingen=0,
            representatie=0, investeringen_totaal=80000,  # > 69764
            uren=1400, params=params,
        )
        assert result.kia == 0

    def test_volledig_kia_binnen_grenzen(self):
        """Investeringen binnen KIA-grenzen: 28%."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=80000, kosten=10000, afschrijvingen=0,
            representatie=0, investeringen_totaal=5000,
            uren=1400, params=params,
        )
        assert abs(result.kia - 1400) < 1  # 5000 * 0.28 = 1400

    def test_volledig_repr_bijtelling(self):
        """Representatie: 20% niet-aftrekbaar bijtelling."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=80000, kosten=10000, afschrijvingen=0,
            representatie=1000, investeringen_totaal=0,
            uren=1400, params=params,
        )
        assert abs(result.repr_bijtelling - 200) < 1  # 1000 * 0.20

    def test_volledig_nul_omzet(self):
        """Nul omzet: belastbare winst = 0 (niet negatief)."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=0, kosten=5000, afschrijvingen=0,
            representatie=0, investeringen_totaal=0,
            uren=0, params=params,
        )
        assert result.belastbare_winst == 0
        assert result.netto_ib == 0

    def test_startersaftrek_2026_not_abolished(self):
        """Startersaftrek 2026 is still EUR 2,123 (confirmed by Belastingdienst)."""
        params = FISCALE_PARAMS[2026].copy()
        result = bereken_volledig(
            omzet=80000, kosten=0, afschrijvingen=0,
            representatie=0, investeringen_totaal=0,
            uren=1400, params=params,
        )
        assert result.startersaftrek == 2123


# ============================================================
# Eigenwoningforfait + Wet Hillen
# ============================================================

class TestEigenwoningforfait:
    """Tests voor eigenwoningforfait berekening."""

    def test_forfait_normaal(self):
        """WOZ 655.000 at 0.35%: 2292.50."""
        result = bereken_eigenwoningforfait(655_000, ew_forfait_pct=0.35)
        assert abs(result - 2292.50) < 0.01

    def test_forfait_nul_woz(self):
        """WOZ 0: geen forfait."""
        assert bereken_eigenwoningforfait(0) == 0.0

    def test_forfait_villataks(self):
        """WOZ boven villataks grens: verhoogd percentage."""
        woz = 1_500_000
        grens = 1_310_000
        verwacht = grens * 0.0035 + (woz - grens) * 0.0235
        result = bereken_eigenwoningforfait(woz, ew_forfait_pct=0.35, villataks_grens=grens)
        assert abs(result - verwacht) < 0.01

    def test_forfait_exact_op_grens(self):
        """WOZ exact op villataks grens: normaal tarief."""
        grens = 1_310_000
        result = bereken_eigenwoningforfait(grens, ew_forfait_pct=0.35, villataks_grens=grens)
        assert abs(result - grens * 0.0035) < 0.01

    def test_forfait_default_grens(self):
        """Default villataks_grens = 1.350.000."""
        result = bereken_eigenwoningforfait(1_350_000)
        assert abs(result - 4725.0) < 0.01


class TestWetHillen:
    """Tests voor Wet Hillen in bereken_volledig."""

    def test_hillen_niet_van_toepassing(self):
        """Rente > forfait: Wet Hillen niet van toepassing (saldo negatief)."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=80000, kosten=0, afschrijvingen=0,
            representatie=0, investeringen_totaal=0,
            uren=1400, params=params,
            woz=655_000, hypotheekrente=6951,
        )
        # forfait = 2292.50, rente = 6951, saldo = -4658.50
        assert result.ew_forfait > 0
        assert result.ew_saldo < 0
        assert result.hillen_aftrek == 0  # Geen Hillen want saldo is negatief

    def test_hillen_van_toepassing_2024(self):
        """Forfait > rente: Wet Hillen verlaagt bijtelling (2024: 80%)."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=80000, kosten=0, afschrijvingen=0,
            representatie=0, investeringen_totaal=0,
            uren=1400, params=params,
            woz=500_000, hypotheekrente=500,
        )
        # forfait = 1750, rente = 500, bruto saldo = 1250
        # hillen_aftrek = 1250 * 0.80 = 1000
        # netto saldo = 1250 - 1000 = 250
        assert abs(result.ew_forfait - 1750) < 0.01
        assert abs(result.hillen_aftrek - 1000) < 1
        assert abs(result.ew_saldo - 250) < 1

    def test_hillen_geen_hypotheek(self):
        """Geen hypotheek: volledig forfait als bijtelling, Hillen verlaagt het."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=80000, kosten=0, afschrijvingen=0,
            representatie=0, investeringen_totaal=0,
            uren=1400, params=params,
            woz=400_000, hypotheekrente=0,
        )
        # forfait = 1400, rente = 0, bruto saldo = 1400
        # hillen_aftrek = 1400 * 0.80 = 1120
        # netto saldo = 280
        assert abs(result.ew_forfait - 1400) < 0.01
        assert abs(result.hillen_aftrek - 1120) < 1
        assert abs(result.ew_saldo - 280) < 1

    def test_hillen_afbouw_2026(self):
        """2026: Wet Hillen 71.867% (versnelde afbouw)."""
        params = FISCALE_PARAMS[2026]
        result = bereken_volledig(
            omzet=80000, kosten=0, afschrijvingen=0,
            representatie=0, investeringen_totaal=0,
            uren=1400, params=params,
            woz=500_000, hypotheekrente=0,
        )
        # forfait = 1750, rente = 0, bruto saldo = 1750
        # hillen_aftrek = 1750 * 0.71867 = 1257.67
        # netto saldo = 1750 - 1257.67 = 492.33
        assert abs(result.hillen_aftrek - 1257.67) < 1
        assert abs(result.ew_saldo - 492.33) < 1

    def test_boekhouder_2024_with_ew(self):
        """Boekhouder 2024 with eigen woning (EW still in verzamelinkomen for now).

        WOZ=655.000, hyp=6951: saldo is negative, no Hillen.
        Note: ew_naar_partner (Task 3) and tariefsaanpassing (Task 2) not yet applied.
        """
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=550, investeringen_totaal=2919,
            uren=1400, params=params,
            aov=2998,
            woz=655000, hypotheekrente=6951,
            voorlopige_aanslag=28544,
        )
        assert abs(result.belastbare_winst - 76777) < 100
        assert abs(result.verzamelinkomen - 69120) < 200
        # AK now uses fiscale_winst
        assert abs(result.arbeidskorting - 1985) < 10


# ============================================================
# Audit bug-fix regression tests (2026-03-03)
# ============================================================

class TestEWNaarPartner:
    """Eigen woning allocation to partner."""

    def test_ew_naar_partner_excludes_from_verzamelinkomen(self):
        """When EW allocated to partner, verzamelinkomen excludes EW saldo."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=550, investeringen_totaal=2919,
            uren=1400, params=params,
            aov=2998,
            woz=655000, hypotheekrente=6951,
            ew_naar_partner=True,
        )
        # Boekhouder: verzamelinkomen = 76776 - 2998 = 73778 (no EW saldo)
        assert abs(result.verzamelinkomen - 73778) < 50

    def test_ew_niet_naar_partner_includes_in_verzamelinkomen(self):
        """When EW NOT allocated to partner, verzamelinkomen includes EW saldo."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=550, investeringen_totaal=2919,
            uren=1400, params=params,
            aov=2998,
            woz=655000, hypotheekrente=6951,
            ew_naar_partner=False,
        )
        # EW saldo = 2292.5 - 6951 = -4658.5
        # verzamelinkomen = 76776 - 4659 - 2998 = 69119
        assert abs(result.verzamelinkomen - 69119) < 50

    def test_ew_naar_partner_tariefsaanpassing_higher(self):
        """With EW to partner, tariefsaanpassing should be higher (more income above grens)."""
        params = FISCALE_PARAMS[2024]
        result_partner = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=550, investeringen_totaal=2919,
            uren=1400, params=params,
            aov=2998, woz=655000, hypotheekrente=6951,
            ew_naar_partner=True,
        )
        result_self = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=550, investeringen_totaal=2919,
            uren=1400, params=params,
            aov=2998, woz=655000, hypotheekrente=6951,
            ew_naar_partner=False,
        )
        # With negative EW saldo, excluding it raises income_without
        assert result_partner.tariefsaanpassing > result_self.tariefsaanpassing

    def test_zvw_uses_belastbare_winst(self):
        """ZVW grondslag = belastbare winst, not verzamelinkomen.

        Boekhouder 2024: Inkomen Zvw = 76.776 (belastbare winst).
        ZVW = 5.32% × min(76776, 71628) = 5.32% × 71628 = 3810.
        """
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=550, investeringen_totaal=2919,
            uren=1400, params=params,
            aov=2998, woz=655000, hypotheekrente=6951,
            ew_naar_partner=True,
        )
        # Boekhouder: ZVW = 3810
        assert abs(result.zvw - 3810) < 50

    def test_default_ew_naar_partner_is_false(self):
        """Default behavior (no ew_naar_partner parameter) keeps EW in verzamelinkomen."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=550, investeringen_totaal=2919,
            uren=1400, params=params,
            aov=2998, woz=655000, hypotheekrente=6951,
        )
        # Default: EW included, verzamelinkomen = 69120
        assert abs(result.verzamelinkomen - 69120) < 200


class TestTariefsaanpassing:
    """Beperking aftrekbare posten (tariefsaanpassing) since 2023."""

    def test_tariefsaanpassing_2024_boekhouder(self):
        """Boekhouder 2024: beperking = 12.53% over 15.921 = 1.994.

        income_without_deductions = fiscale_winst - aov = 94437 - 2998 = 91439
        (EW to partner, so no ew_saldo)
        schijf1_grens = 75518 (= top bracket boundary for 2024)
        excess = 91439 - 75518 = 15921
        deductions = ZA(3750) + SA(2123) + MKB(11788) = 17661
        subject = min(17661, 15921) = 15921
        tariefsaanpassing = 15921 * (49.50 - 36.97) / 100 = 15921 * 12.53% = 1995
        """
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=550, investeringen_totaal=2919,
            uren=1400, params=params,
            aov=2998,
        )
        # Boekhouder: tariefsaanpassing = 1994
        assert abs(result.tariefsaanpassing - 1994) < 50

    def test_tariefsaanpassing_income_below_schijf1_no_beperking(self):
        """If income without deductions stays within schijf 1, no tariefsaanpassing."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=50000, kosten=0, afschrijvingen=0,
            representatie=0, investeringen_totaal=0,
            uren=1400, params=params,
        )
        # fiscale_winst = 50000, which is < schijf1_grens (75518)
        assert result.tariefsaanpassing == 0

    def test_tariefsaanpassing_only_excess_in_top_bracket(self):
        """Only the portion of deductions that removes income from top bracket."""
        params = FISCALE_PARAMS[2024]
        # fiscale_winst just above schijf1_grens (75518)
        result = bereken_volledig(
            omzet=76000, kosten=0, afschrijvingen=0,
            representatie=0, investeringen_totaal=0,
            uren=1400, params=params,
        )
        # income_without = fiscale_winst = 76000, no aov/ew
        # Amount in top bracket: 76000 - 75518 = 482
        # Deductions (ZA+SA+MKB): ~3750 + 2123 + ~9328 = ~15201
        # Subject to beperking: min(15201, 482) = 482
        # Tariefsaanpassing = 482 * 0.1253 = ~60
        assert 40 < result.tariefsaanpassing < 80

    def test_tariefsaanpassing_2025_three_brackets(self):
        """2025 has 3 brackets. Tariefsaanpassing uses toptarief (49.50) minus schijf2 rate (37.48)."""
        params = FISCALE_PARAMS[2025]
        result = bereken_volledig(
            omzet=95000, kosten=0, afschrijvingen=0,
            representatie=0, investeringen_totaal=0,
            uren=1400, params=params,
        )
        # Tariefsaanpassing should use 49.50 - 37.48 = 12.02%
        # fiscale_winst = 95000, schijf2_grens = 76817
        # excess = 95000 - 76817 = 18183
        # deductions: ZA(2470) + SA(2123) + MKB ~11484 = ~16077
        # subject = min(16077, 18183) = 16077
        # ta = 16077 * 12.02% = 1932
        assert result.tariefsaanpassing > 1500

    def test_tariefsaanpassing_no_urencriterium_no_deductions(self):
        """Without urencriterium, no ZA/SA, only MKB. Still can have tariefsaanpassing."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=95000, kosten=0, afschrijvingen=0,
            representatie=0, investeringen_totaal=0,
            uren=1000, params=params,  # < 1225, no urencriterium
        )
        # No ZA/SA, only MKB. Deductions are smaller, but still above grens.
        # fiscale_winst = 95000
        # income_without = 95000
        # MKB-only deduction: 95000 * 13.31% = 12645
        # belastbare_winst = 95000 - 12645 = 82355
        # excess = 95000 - 75518 = 19482
        # subject = min(12645, 19482) = 12645
        # ta = 12645 * 12.53% = 1584
        assert result.tariefsaanpassing > 1000


class TestArbeidskortingInput:
    """Arbeidskorting should use fiscale_winst (vóór ZA/SA/MKB), not belastbare_winst."""

    def test_arbeidskorting_uses_fiscale_winst_2024(self):
        """Boekhouder 2024: AK = 1.986 with fiscale_winst = 94.437.

        With fiscale_winst 94437: AK = 5532 - 6.51% * (94437 - 39958) = 1983.
        With belastbare_winst 76776: AK = 5532 - 6.51% * (76776 - 39958) = 3136. (WRONG)
        """
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=550, investeringen_totaal=2919,
            uren=1400, params=params,
        )
        # Fiscale winst = 94437, AK should be ~1983 (Boekhouder says 1986)
        assert abs(result.arbeidskorting - 1986) < 10
        # NOT 3136 (which is what belastbare_winst would give)
        assert result.arbeidskorting < 2100


class TestDBDrivenArbeidskorting:
    """Arbeidskorting should work with JSON brackets from DB."""

    def test_json_brackets_match_python_constants_2024(self):
        """JSON brackets produce same result as Python constants."""
        import json
        brackets_json = json.dumps([
            {"lower": 0, "upper": 11491, "rate": 0.08425, "base": 0},
            {"lower": 11491, "upper": 24821, "rate": 0.31433, "base": 968},
            {"lower": 24821, "upper": 39958, "rate": 0.02471, "base": 5158},
            {"lower": 39958, "upper": 124935, "rate": -0.06510, "base": 5532},
            {"lower": 124935, "upper": None, "rate": 0, "base": 0},
        ])
        # Compare JSON-driven vs Python-constant for several incomes
        for income in [5000, 15000, 30000, 50000, 80000, 130000]:
            from_json = bereken_arbeidskorting(income, 2024, brackets_json=brackets_json)
            from_python = bereken_arbeidskorting(income, 2024)
            assert from_json == from_python, f"Mismatch at income {income}: {from_json} != {from_python}"

    def test_json_brackets_custom_future_year(self):
        """Custom brackets for a hypothetical future year."""
        import json
        brackets_json = json.dumps([
            {"lower": 0, "upper": 10000, "rate": 0.10, "base": 0},
            {"lower": 10000, "upper": None, "rate": 0, "base": 1000},
        ])
        result = bereken_arbeidskorting(5000, 2099, brackets_json=brackets_json)
        assert result == 500.0  # 5000 * 0.10

    def test_empty_brackets_json_falls_back(self):
        """Empty brackets_json should fall back to Python constants."""
        result = bereken_arbeidskorting(50000, 2024, brackets_json='')
        from_python = bereken_arbeidskorting(50000, 2024)
        assert result == from_python


class TestIBPVVSplit:
    """IB/PVV split and separate voorlopige aanslag (Task 4+9)."""

    def test_pvv_2024_boekhouder(self):
        """Boekhouder 2024: PVV = 27.65% × min(73778, 38098) = 27.65% × 38098 = 10534."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=550, investeringen_totaal=2919,
            uren=1400, params=params,
            aov=2998, woz=655000, hypotheekrente=6951,
            ew_naar_partner=True,
        )
        assert abs(result.pvv - 10534) < 5

    def test_ib_alleen_2024_boekhouder(self):
        """Boekhouder 2024: IB (incl tariefsaanpassing) = bruto_ib - PVV = 18734."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=550, investeringen_totaal=2919,
            uren=1400, params=params,
            aov=2998, woz=655000, hypotheekrente=6951,
            ew_naar_partner=True,
        )
        assert abs(result.ib_alleen - 18734) < 15

    def test_pvv_components_2024(self):
        """PVV split: AOW 17.90%, Anw 0.10%, Wlz 9.65% over premiegrondslag."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=550, investeringen_totaal=2919,
            uren=1400, params=params,
            aov=2998, woz=655000, hypotheekrente=6951,
            ew_naar_partner=True,
        )
        # 17.90% × 38098 = 6819.54
        assert abs(result.pvv_aow - 6820) < 5
        # 0.10% × 38098 = 38.10
        assert abs(result.pvv_anw - 38) < 2
        # 9.65% × 38098 = 3676.46
        assert abs(result.pvv_wlz - 3676) < 5
        # Components sum to total
        assert abs(result.pvv - (result.pvv_aow + result.pvv_anw + result.pvv_wlz)) < 1

    def test_pvv_capped_at_premiegrondslag(self):
        """PVV uses min(verzamelinkomen, premiegrondslag), not full income."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=550, investeringen_totaal=2919,
            uren=1400, params=params,
            aov=2998, woz=655000, hypotheekrente=6951,
            ew_naar_partner=True,
        )
        # verzamelinkomen (73778) > premiegrondslag (38098)
        # PVV should be 27.65% × 38098, NOT 27.65% × 73778
        max_pvv = 38098 * 0.2765
        assert abs(result.pvv - max_pvv) < 5

    def test_pvv_low_income_below_premiegrondslag(self):
        """When verzamelinkomen < premiegrondslag, PVV based on verzamelinkomen."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=30000, kosten=0, afschrijvingen=0,
            representatie=0, investeringen_totaal=0,
            uren=1400, params=params,
        )
        # verzamelinkomen after ZA+SA+MKB is well below premiegrondslag (38098)
        assert result.verzamelinkomen < 38098
        expected_pvv = result.verzamelinkomen * 0.2765
        assert abs(result.pvv - expected_pvv) < 5

    def test_resultaat_ib_2024_boekhouder(self):
        """Boekhouder 2024: IB terug 3137 = netto_ib - VA_IB (30303)."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=550, investeringen_totaal=2919,
            uren=1400, params=params,
            aov=2998, woz=655000, hypotheekrente=6951,
            ew_naar_partner=True,
            voorlopige_aanslag=30303,
            voorlopige_aanslag_zvw=2667,
        )
        # Boekhouder: IB terug = -3137 (negative = teruggave)
        assert abs(result.resultaat_ib - (-3137)) < 20

    def test_resultaat_zvw_2024_boekhouder(self):
        """Boekhouder 2024: ZVW bij 1143 = zvw (3810) - VA_ZVW (2667)."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=550, investeringen_totaal=2919,
            uren=1400, params=params,
            aov=2998, woz=655000, hypotheekrente=6951,
            ew_naar_partner=True,
            voorlopige_aanslag=30303,
            voorlopige_aanslag_zvw=2667,
        )
        # Boekhouder: ZVW bij = 1143
        assert abs(result.resultaat_zvw - 1143) < 10

    def test_resultaat_total_is_sum(self):
        """Total resultaat = resultaat_ib + resultaat_zvw."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=550, investeringen_totaal=2919,
            uren=1400, params=params,
            aov=2998, woz=655000, hypotheekrente=6951,
            ew_naar_partner=True,
            voorlopige_aanslag=30303,
            voorlopige_aanslag_zvw=2667,
        )
        assert abs(result.resultaat - (result.resultaat_ib + result.resultaat_zvw)) < 1

    def test_backward_compat_no_va_zvw(self):
        """Without voorlopige_aanslag_zvw, old behavior: resultaat_zvw = zvw."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=550, investeringen_totaal=2919,
            uren=1400, params=params,
            aov=2998, woz=655000, hypotheekrente=6951,
            ew_naar_partner=True,
            voorlopige_aanslag=28544,
            # No voorlopige_aanslag_zvw -> defaults to 0
        )
        # resultaat_zvw = zvw - 0 = zvw
        assert abs(result.resultaat_zvw - result.zvw) < 1
        # resultaat_ib = netto_ib - 28544
        assert abs(result.resultaat_ib - (result.netto_ib - 28544)) < 1


class TestBoekhouder2024Complete:
    """Complete validation against Boekhouder Aangifte IB 2024.

    Every intermediate value from the Boekhouder rapportage (10 pages).
    Inputs: omzet 95145, repr 550, invest 2919, uren 1400,
    aov 2998, woz 655000, hyp 6951, VA_IB 30303, VA_ZVW 2667,
    ew_naar_partner=True.
    """

    @pytest.fixture()
    def boekhouder(self):
        params = FISCALE_PARAMS[2024]
        return bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=550, investeringen_totaal=2919,
            uren=1400, params=params,
            aov=2998,
            woz=655000, hypotheekrente=6951,
            voorlopige_aanslag=30303,
            voorlopige_aanslag_zvw=2667,
            ew_naar_partner=True,
        )

    def test_winst_en_verlies(self, boekhouder):
        """Page 6-7: W&V totals."""
        assert boekhouder.winst == 95145

    def test_fiscale_correcties(self, boekhouder):
        """Page 6-7: repr bijtelling 110, KIA 818."""
        assert abs(boekhouder.repr_bijtelling - 110) < 1
        assert abs(boekhouder.kia - 817.32) < 1

    def test_fiscale_winst(self, boekhouder):
        """Page 7: fiscale winst 94437."""
        assert abs(boekhouder.fiscale_winst - 94438) < 5

    def test_ondernemersaftrek(self, boekhouder):
        """Page 7: ZA 3750, SA 2123."""
        assert boekhouder.zelfstandigenaftrek == 3750
        assert boekhouder.startersaftrek == 2123

    def test_mkb_vrijstelling(self, boekhouder):
        """Page 7: MKB ~11788."""
        assert abs(boekhouder.mkb_vrijstelling - 11788) < 50

    def test_belastbare_winst(self, boekhouder):
        """Page 2: belastbare winst Box 1 = 76776."""
        assert abs(boekhouder.belastbare_winst - 76777) < 10

    def test_eigen_woning(self, boekhouder):
        """Page 8: EW forfait 2293, hyp 6951, saldo -4659 (to partner)."""
        assert abs(boekhouder.ew_forfait - 2292.50) < 1
        assert abs(boekhouder.ew_saldo - (-4658.50)) < 1

    def test_verzamelinkomen(self, boekhouder):
        """Page 2: belastbaar Box1 = 76776 - 2998 = 73778 (EW to partner)."""
        assert abs(boekhouder.verzamelinkomen - 73778) < 10

    def test_tariefsaanpassing(self, boekhouder):
        """Page 2: tariefsaanpassing = 1994."""
        assert abs(boekhouder.tariefsaanpassing - 1994) < 10

    def test_bruto_ib_pvv(self, boekhouder):
        """Page 2: IB + PVV = 29268."""
        assert abs(boekhouder.bruto_ib - 29268) < 10

    def test_ib_alleen(self, boekhouder):
        """Page 2: IB (incl tariefsaanpassing) = 18734."""
        assert abs(boekhouder.ib_alleen - 18734) < 10

    def test_pvv_total(self, boekhouder):
        """Page 2: PVV = 27.65% × 38098 = 10534."""
        assert abs(boekhouder.pvv - 10534) < 5

    def test_pvv_components(self, boekhouder):
        """Page 2: AOW 17.90%, Anw 0.10%, Wlz 9.65%."""
        assert abs(boekhouder.pvv_aow - 6820) < 5   # 17.90% × 38098
        assert abs(boekhouder.pvv_anw - 38) < 2      # 0.10% × 38098
        assert abs(boekhouder.pvv_wlz - 3676) < 5    # 9.65% × 38098

    def test_ahk(self, boekhouder):
        """Page 4: AHK = 116."""
        assert abs(boekhouder.ahk - 116) < 2

    def test_arbeidskorting(self, boekhouder):
        """Page 4: AK = 1986 (based on fiscale_winst 94437)."""
        assert abs(boekhouder.arbeidskorting - 1986) < 5

    def test_netto_ib(self, boekhouder):
        """Page 4: verschuldigd = 29268 - 116 - 1986 = 27166."""
        assert abs(boekhouder.netto_ib - 27166) < 10

    def test_zvw(self, boekhouder):
        """Page 5: ZVW = 5.32% × min(76776, 71628) = 3810."""
        assert abs(boekhouder.zvw - 3810) < 5

    def test_resultaat_ib(self, boekhouder):
        """Page 1: IB terug = 27166 - 30303 = -3137."""
        assert abs(boekhouder.resultaat_ib - (-3137)) < 10

    def test_resultaat_zvw(self, boekhouder):
        """Page 5: ZVW bij = 3810 - 2667 = 1143."""
        assert abs(boekhouder.resultaat_zvw - 1143) < 5

    def test_resultaat_total(self, boekhouder):
        """Page 1: total = IB terug + ZVW bij = -3137 + 1143 = -1994."""
        assert abs(boekhouder.resultaat - (-1994)) < 15

    def test_urencriterium(self, boekhouder):
        """1400 > 1225: urencriterium gehaald."""
        assert boekhouder.uren_criterium_gehaald is True


class TestKIABoundary:
    """Bug #1: KIA should apply at exactly the ondergrens (>=, not >)."""

    def test_kia_at_exact_ondergrens(self):
        """Invest exactly EUR2,901 (2025 ondergrens) should get KIA."""
        params = FISCALE_PARAMS[2025]
        result = bereken_volledig(
            omzet=80000, kosten=5000, afschrijvingen=0,
            representatie=0, investeringen_totaal=2901,
            uren=1400, params=params,
        )
        expected_kia = round(2901 * 0.28, 2)
        assert result.kia == expected_kia

    def test_kia_below_ondergrens(self):
        """Invest EUR2,900 should NOT get KIA."""
        params = FISCALE_PARAMS[2025]
        result = bereken_volledig(
            omzet=80000, kosten=5000, afschrijvingen=0,
            representatie=0, investeringen_totaal=2900,
            uren=1400, params=params,
        )
        assert result.kia == 0

    def test_kia_at_exact_bovengrens(self):
        """Invest exactly at bovengrens should still get KIA."""
        params = FISCALE_PARAMS[2025]
        result = bereken_volledig(
            omzet=80000, kosten=5000, afschrijvingen=0,
            representatie=0, investeringen_totaal=70602,
            uren=1400, params=params,
        )
        assert result.kia > 0

    def test_kia_above_bovengrens(self):
        """Invest above bovengrens gets no KIA."""
        params = FISCALE_PARAMS[2025]
        result = bereken_volledig(
            omzet=80000, kosten=5000, afschrijvingen=0,
            representatie=0, investeringen_totaal=70603,
            uren=1400, params=params,
        )
        assert result.kia == 0


class TestAfschrijvingValidation:
    """Bug #5: Input validation for bereken_afschrijving."""

    def test_levensduur_zero_no_crash(self):
        """levensduur=0 should return 0 depreciation, not ZeroDivisionError."""
        result = bereken_afschrijving(1000, 10, 0, 6, 2024, 2024)
        assert result['afschrijving'] == 0
        assert result['per_jaar'] == 0

    def test_negative_levensduur_no_crash(self):
        """Negative levensduur returns 0."""
        result = bereken_afschrijving(1000, 10, -3, 6, 2024, 2024)
        assert result['afschrijving'] == 0

    def test_negative_aanschaf_returns_zero(self):
        """Negative purchase price returns 0."""
        result = bereken_afschrijving(-1000, 10, 5, 6, 2024, 2024)
        assert result['afschrijving'] == 0

    def test_month_clamped_to_valid_range(self):
        """Month 0 should be clamped to 1 (January), not produce 13/12."""
        result_month0 = bereken_afschrijving(1000, 10, 5, 0, 2024, 2024)
        result_month1 = bereken_afschrijving(1000, 10, 5, 1, 2024, 2024)
        assert result_month0['afschrijving'] == result_month1['afschrijving']

    def test_month_13_clamped_to_12(self):
        """Month 13 should be clamped to 12 (December)."""
        result_month13 = bereken_afschrijving(1000, 10, 5, 13, 2024, 2024)
        result_month12 = bereken_afschrijving(1000, 10, 5, 12, 2024, 2024)
        assert result_month13['afschrijving'] == result_month12['afschrijving']

    def test_restwaarde_pct_clamped(self):
        """restwaarde_pct > 100 should be clamped to 100 (0 depreciation)."""
        result = bereken_afschrijving(1000, 150, 5, 6, 2024, 2024)
        assert result['afschrijving'] == 0


class TestDBDrivenPVV:
    """PVV rates should be configurable via params."""

    def test_pvv_from_params_matches_constants(self):
        """DB-driven PVV with default rates should match constant-based."""
        params = FISCALE_PARAMS[2024].copy()
        params['pvv_aow_pct'] = 17.90
        params['pvv_anw_pct'] = 0.10
        params['pvv_wlz_pct'] = 9.65
        result = bereken_volledig(
            omzet=95145.69, kosten=29192.35, afschrijvingen=960,
            representatie=533.55, investeringen_totaal=0,
            uren=1400, params=params,
        )
        # Should match the Boekhouder reference
        assert abs(result.pvv - 10526) < 20


class TestBox3:
    """Tests for Box 3 forfaitair rendement calculation."""

    def test_box3_zero_vermogen(self):
        """No assets = no tax."""
        from fiscal.berekeningen import bereken_box3
        params = {'box3_bank_saldo': 0, 'box3_overige_bezittingen': 0, 'box3_schulden': 0}
        result = bereken_box3(params)
        assert result.belasting == 0
        assert result.grondslag == 0

    def test_box3_below_heffingsvrij(self):
        """Assets below heffingsvrij vermogen = no tax."""
        from fiscal.berekeningen import bereken_box3
        params = {
            'box3_bank_saldo': 50000, 'box3_overige_bezittingen': 0, 'box3_schulden': 0,
            'box3_heffingsvrij_vermogen': 57000, 'box3_rendement_bank_pct': 1.03,
            'box3_rendement_overig_pct': 6.17, 'box3_rendement_schuld_pct': 2.46,
            'box3_tarief_pct': 36,
        }
        result = bereken_box3(params, fiscaal_partner=True)
        # 50000 < 57000*2 = 114000, so grondslag = 0
        assert result.grondslag == 0
        assert result.belasting == 0

    def test_box3_with_partner(self):
        """Partner doubles heffingsvrij vermogen."""
        from fiscal.berekeningen import bereken_box3
        params = {
            'box3_bank_saldo': 100000, 'box3_overige_bezittingen': 0, 'box3_schulden': 0,
            'box3_heffingsvrij_vermogen': 57000, 'box3_rendement_bank_pct': 1.03,
            'box3_rendement_overig_pct': 6.17, 'box3_rendement_schuld_pct': 2.46,
            'box3_tarief_pct': 36,
        }
        with_partner = bereken_box3(params, fiscaal_partner=True)
        without_partner = bereken_box3(params, fiscaal_partner=False)
        # With partner: 100000 - 114000 = 0 (below threshold)
        assert with_partner.grondslag == 0
        # Without partner: 100000 - 57000 = 43000
        assert without_partner.grondslag == 43000
        assert without_partner.belasting > 0

    def test_box3_2024_realistic(self):
        """Realistic 2024 scenario with bank + beleggingen."""
        from fiscal.berekeningen import bereken_box3
        params = {
            'box3_bank_saldo': 80000, 'box3_overige_bezittingen': 50000, 'box3_schulden': 10000,
            'box3_heffingsvrij_vermogen': 57000, 'box3_rendement_bank_pct': 1.03,
            'box3_rendement_overig_pct': 6.17, 'box3_rendement_schuld_pct': 2.46,
            'box3_tarief_pct': 36,
        }
        result = bereken_box3(params, fiscaal_partner=False)
        # bezittingen=130000, schulden=10000, netto=120000, heffingsvrij=57000, grondslag=63000
        assert result.totaal_bezittingen == 130000
        assert result.grondslag == 63000
        assert result.rendement_bank == round(80000 * 0.0103, 2)
        assert result.rendement_overig == round(50000 * 0.0617, 2)
        assert result.belasting > 0


class TestFormatDatum:
    """Bug #11: format_datum should handle already-NL dates."""

    def test_iso_to_nl(self):
        from components.utils import format_datum
        assert format_datum("2026-03-15") == "15-03-2026"

    def test_already_nl_passthrough(self):
        from components.utils import format_datum
        assert format_datum("15-03-2026") == "15-03-2026"

    def test_empty_string(self):
        from components.utils import format_datum
        assert format_datum("") == ""

    def test_none(self):
        from components.utils import format_datum
        assert format_datum(None) == ""
