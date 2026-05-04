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

    def test_january_minimal_data(self):
        # Januari (month 1): 1/12 = 8.3% verwacht
        # Jaarbelasting €12000 → verwacht €1000 YTD
        # VA betaald €0 → tekort van €1000 — net op de threshold
        status, diff = compute_belasting_reservering_progress(
            berekend_jaarbelasting=12000.0,
            va_betaald_ytd=0.0,
            today=date(2026, 1, 31),
        )
        # Diff is exactly 1000.0 — niet > 1000 → 'op_koers' (boundary case)
        assert status == 'op_koers'
        assert diff == 1000.0

    def test_december_full_year_check(self):
        # December: 12/12 = 100% verwacht. VA volledig betaald → op_koers
        status, diff = compute_belasting_reservering_progress(
            berekend_jaarbelasting=12000.0,
            va_betaald_ytd=12000.0,
            today=date(2026, 12, 31),
        )
        assert status == 'op_koers'
        assert diff == 0.0
