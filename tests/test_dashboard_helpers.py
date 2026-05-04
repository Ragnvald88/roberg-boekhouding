"""Unit tests for services.dashboard pure helpers."""
from datetime import date

from services.dashboard import compute_belasting_reservering_progress


class TestComputeBelastingReserveringProgress:
    """Test the YTD vs prorated belasting-reservering check."""

    def test_op_koers_when_va_matches_prorated_expected(self):
        # 31 mei: days_elapsed=151, days_in_year=365 → expected ≈ €4965.
        # VA=€5000 → diff ≈ -€35 → op_koers (binnen [-2000, 1000] threshold).
        status, diff = compute_belasting_reservering_progress(
            berekend_jaarbelasting=12000.0,
            va_betaald_ytd=5000.0,
            today=date(2026, 5, 31),
        )
        assert status == 'op_koers'
        assert -1000 <= diff <= 1000

    def test_tekort_when_va_significantly_below_prorated(self):
        # 31 mei, VA betaald slechts €2000 → expected ≈ €4965 → diff ≈ €2965 → tekort.
        status, diff = compute_belasting_reservering_progress(
            berekend_jaarbelasting=12000.0,
            va_betaald_ytd=2000.0,
            today=date(2026, 5, 31),
        )
        assert status == 'tekort'
        assert diff > 1000

    def test_overreservering_when_va_significantly_above_prorated(self):
        # 31 mei, VA betaald €10000 → expected ≈ €4965 → diff ≈ -€5035 → overreservering.
        status, diff = compute_belasting_reservering_progress(
            berekend_jaarbelasting=12000.0,
            va_betaald_ytd=10000.0,
            today=date(2026, 5, 31),
        )
        assert status == 'overreservering'
        assert diff < -2000

    def test_january_first_day_negligible_expected(self):
        # 1 jan: days_elapsed=1, days_in_year=365 (2026 is geen leap)
        # Expected = 12000 × 1/365 ≈ €33. VA=€0 → diff=€33 → 'op_koers'.
        # Day-precision proration was introduced post-Codex T1.3-review:
        # month-based formule gaf 1/12 expected op 1 jan = conceptueel fout.
        # Niet exact zero (we tellen `today` mee — see docstring), wel
        # negligible (~€33 op €12k jaarbelasting).
        status, diff = compute_belasting_reservering_progress(
            berekend_jaarbelasting=12000.0,
            va_betaald_ytd=0.0,
            today=date(2026, 1, 1),
        )
        assert status == 'op_koers'
        assert 30 < diff < 40  # ≈ €33

    def test_exact_threshold_tekort_boundary(self):
        # diff exact = 1000.0 → 'op_koers' (threshold is `>`, niet `>=`).
        # Construct: berekend × days/365 - VA = 1000 → 12000 × 365/365 - 11000 = 1000.
        status, diff = compute_belasting_reservering_progress(
            berekend_jaarbelasting=12000.0,
            va_betaald_ytd=11000.0,
            today=date(2026, 12, 31),  # full year elapsed
        )
        assert diff == 1000.0
        assert status == 'op_koers'  # exact-1000 NOT tekort

    def test_exact_threshold_overreservering_boundary(self):
        # diff exact = -2000.0 → 'op_koers' (threshold is `<`, niet `<=`).
        status, diff = compute_belasting_reservering_progress(
            berekend_jaarbelasting=12000.0,
            va_betaald_ytd=14000.0,
            today=date(2026, 12, 31),
        )
        assert diff == -2000.0
        assert status == 'op_koers'  # exact -2000 NOT overreservering

    def test_january_full_month_partial_year(self):
        # 31 jan: days_elapsed=31, days_in_year=365
        # Expected = 12000 × 31/365 ≈ €1019. VA=€0 → diff=€1019 → 'tekort'.
        # Net boven threshold (>1000) — bewust strict om reservering-pace
        # te flagged op tijd.
        status, diff = compute_belasting_reservering_progress(
            berekend_jaarbelasting=12000.0,
            va_betaald_ytd=0.0,
            today=date(2026, 1, 31),
        )
        assert status == 'tekort'
        assert 1000 < diff < 1100  # ≈ €1019

    def test_leap_year_uses_366_days(self):
        # 2024 = leap year. 31 dec → days_elapsed=366, days_in_year=366
        # Expected = 12000 × 366/366 = 12000. VA=€12000 → diff=0 → 'op_koers'.
        status, diff = compute_belasting_reservering_progress(
            berekend_jaarbelasting=12000.0,
            va_betaald_ytd=12000.0,
            today=date(2024, 12, 31),
        )
        assert status == 'op_koers'
        assert diff == 0.0

    def test_december_full_year_check(self):
        # December: days_elapsed=365, days_in_year=365 (2026)
        # Expected = 12000. VA volledig betaald → op_koers.
        status, diff = compute_belasting_reservering_progress(
            berekend_jaarbelasting=12000.0,
            va_betaald_ytd=12000.0,
            today=date(2026, 12, 31),
        )
        assert status == 'op_koers'
        assert diff == 0.0


class TestComputeJaareindeProjectieDisplay:
    """Tests for the hero-tile data-shape (1 number — winst-projectie)."""

    def test_high_confidence_full_year_exact(self):
        # Eind dec, basis_maanden=12 → kosten extrapolated = ytd × 1.0
        from services.dashboard import compute_jaareinde_projectie_display
        result = compute_jaareinde_projectie_display(
            extrapolated_omzet=120_000.0,
            kosten_ytd=30_000.0,
            confidence='high',
            basis_maanden=12,
        )
        assert result['winst_projectie'] == 90_000.0
        assert result['confidence'] == 'high'
        assert result['basis_maanden'] == 12

    def test_medium_confidence_mid_year(self):
        from services.dashboard import compute_jaareinde_projectie_display
        # Juli, basis_maanden=6, ytd_omzet ≈ 60k → projectie 120k
        result = compute_jaareinde_projectie_display(
            extrapolated_omzet=120_000.0,
            kosten_ytd=18_000.0,  # halfjaar kosten
            confidence='medium',
            basis_maanden=6,
        )
        # Kosten worden ook geëxtrapoleerd naar 12mo: 18k × 12/6 = 36k
        # Winst = 120k - 36k = 84k
        assert result['winst_projectie'] == 84_000.0
        assert result['confidence'] == 'medium'

    def test_low_confidence_early_year(self):
        from services.dashboard import compute_jaareinde_projectie_display
        # Januari, basis_maanden=1
        result = compute_jaareinde_projectie_display(
            extrapolated_omzet=130_000.0,
            kosten_ytd=2_500.0,
            confidence='low',
            basis_maanden=1,
        )
        # Kosten extrapoleren: 2500 × 12/1 = 30000
        assert result['winst_projectie'] == 100_000.0
        assert result['confidence'] == 'low'

    def test_zero_basis_maanden_falls_back_to_ytd_omzet(self):
        from services.dashboard import compute_jaareinde_projectie_display
        # Edge case: basis_maanden=0 zou divide-by-zero geven
        result = compute_jaareinde_projectie_display(
            extrapolated_omzet=0.0,
            kosten_ytd=0.0,
            confidence='low',
            basis_maanden=0,
        )
        assert result['winst_projectie'] == 0.0
        assert result['confidence'] == 'low'
