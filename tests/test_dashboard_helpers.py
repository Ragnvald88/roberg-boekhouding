"""Unit tests for services.dashboard pure helpers."""
from datetime import date

from services.dashboard import compute_belasting_reservering_progress


class TestComputeBelastingReserveringProgress:
    """Test the YTD vs prorated belasting-reservering check."""

    def test_op_koers_when_va_matches_prorated_expected(self):
        # Mei (month 5): 5/12 = 41.6% van jaarbelasting verwacht
        # Jaarbelasting €12000 → verwacht €5000 YTD
        # VA betaald €5000 → exactly op-koers (diff = 0)
        status, diff = compute_belasting_reservering_progress(
            berekend_jaarbelasting=12000.0,
            va_betaald_ytd=5000.0,
            today=date(2026, 5, 31),
        )
        assert status == 'op_koers'
        assert -1000 <= diff <= 1000

    def test_tekort_when_va_significantly_below_prorated(self):
        # Same month, VA betaald slechts €2000 → tekort van €3000
        status, diff = compute_belasting_reservering_progress(
            berekend_jaarbelasting=12000.0,
            va_betaald_ytd=2000.0,
            today=date(2026, 5, 31),
        )
        assert status == 'tekort'
        assert diff > 1000

    def test_overreservering_when_va_significantly_above_prorated(self):
        # Same month, VA betaald €10000 → overreservering van €5000
        status, diff = compute_belasting_reservering_progress(
            berekend_jaarbelasting=12000.0,
            va_betaald_ytd=10000.0,
            today=date(2026, 5, 31),
        )
        assert status == 'overreservering'
        assert diff < -2000

    def test_january_first_day_zero_expected(self):
        # 1 jan: days_elapsed=1, days_in_year=365 (2026 is geen leap)
        # Expected = 12000 × 1/365 ≈ €33. VA=€0 → diff=€33 → 'op_koers'.
        # Day-precision proration was introduced post-Codex T1.3-review:
        # month-based formule gaf 1/12 expected op 1 jan = conceptueel fout.
        status, diff = compute_belasting_reservering_progress(
            berekend_jaarbelasting=12000.0,
            va_betaald_ytd=0.0,
            today=date(2026, 1, 1),
        )
        assert status == 'op_koers'
        assert 30 < diff < 40  # ≈ €33

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
