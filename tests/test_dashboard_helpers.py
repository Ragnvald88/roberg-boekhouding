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
