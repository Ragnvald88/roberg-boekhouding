"""Unit tests for services.dashboard pure helpers."""
from datetime import date

from services.dashboard import (
    ActionRow,
    compute_belasting_reservering_progress,
    prioritise_actions,
)


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


class TestActionRow:
    def test_actionrow_is_frozen_dataclass(self):
        row = ActionRow(
            kind='verlopen_factuur',
            severity='warning',
            message='2 facturen verlopen >30d',
            action_kind='stuur_herinnering',
            link='/facturen',
            age_days=30,
            metadata={},
        )
        assert row.kind == 'verlopen_factuur'
        assert row.severity == 'warning'


class TestPrioritiseActions:
    def _make_row(self, kind, severity, age=0):
        return ActionRow(
            kind=kind, severity=severity, message=f'{kind}-msg',
            action_kind=None, link=None, age_days=age, metadata={},
        )

    def test_critical_first_warning_second_info_last(self):
        rows = [
            self._make_row('a', 'info'),
            self._make_row('b', 'critical'),
            self._make_row('c', 'warning'),
        ]
        result = prioritise_actions(rows, max_items=10)
        assert [r.kind for r in result] == ['b', 'c', 'a']

    def test_within_severity_age_desc(self):
        rows = [
            self._make_row('a', 'warning', age=10),
            self._make_row('b', 'warning', age=30),
            self._make_row('c', 'warning', age=5),
        ]
        result = prioritise_actions(rows, max_items=10)
        assert [r.kind for r in result] == ['b', 'a', 'c']

    def test_max_items_truncates(self):
        rows = [self._make_row(f'r{i}', 'warning', age=i) for i in range(10)]
        result = prioritise_actions(rows, max_items=3)
        assert len(result) == 3

    def test_empty_input(self):
        assert prioritise_actions([], max_items=5) == []

    def test_single_row(self):
        rows = [self._make_row('a', 'info')]
        assert prioritise_actions(rows, max_items=5) == rows

    def test_max_items_zero_returns_empty(self):
        rows = [self._make_row('a', 'critical')]
        assert prioritise_actions(rows, max_items=0) == []

    def test_severity_order_complete(self):
        # critical → warning → info → unknown_severity (treated as info)
        rows = [
            self._make_row('a', 'unknown_severity'),
            self._make_row('b', 'info'),
            self._make_row('c', 'warning'),
            self._make_row('d', 'critical'),
        ]
        result = prioritise_actions(rows, max_items=10)
        # critical first, then warning, then info+unknown (kind ASC tiebreak)
        assert result[0].kind == 'd'
        assert result[1].kind == 'c'

    def test_metadata_passes_through(self):
        rows = [ActionRow(
            kind='a', severity='info', message='m', action_kind=None,
            link=None, age_days=0, metadata={'factuur_id': 42},
        )]
        result = prioritise_actions(rows, max_items=10)
        assert result[0].metadata == {'factuur_id': 42}


class TestTaxCalendar:
    def test_tax_calendar_2026_returns_known_deadlines(self):
        from services.dashboard import tax_calendar
        cal = tax_calendar(2026)
        assert isinstance(cal, list)
        # Must include 1 mei IB-aangifte deadline
        ib_deadline = next((d for d in cal if d['kind'] == 'ib_aangifte'), None)
        assert ib_deadline is not None
        assert ib_deadline['date'] == date(2026, 5, 1)

    def test_tax_calendar_unknown_year_returns_empty(self):
        from services.dashboard import tax_calendar
        # Unknown years (e.g. 1999) return empty list, not error
        assert tax_calendar(1999) == []


class TestSeasonalActionRows:
    def test_april_emits_ib_aangifte_deadline(self):
        from services.dashboard import _seasonal_action_rows
        rows = _seasonal_action_rows(today=date(2026, 4, 15))
        ib_rows = [r for r in rows if r.kind == 'ib_aangifte_deadline']
        assert len(ib_rows) == 1
        assert ib_rows[0].severity == 'warning'  # 16 days remaining
        assert '16 dagen' in ib_rows[0].message

    def test_late_april_critical_severity(self):
        from services.dashboard import _seasonal_action_rows
        rows = _seasonal_action_rows(today=date(2026, 4, 25))
        ib_rows = [r for r in rows if r.kind == 'ib_aangifte_deadline']
        assert ib_rows[0].severity == 'critical'  # 6 days

    def test_july_emits_no_seasonal_rows(self):
        from services.dashboard import _seasonal_action_rows
        rows = _seasonal_action_rows(today=date(2026, 7, 15))
        # July: no IB-deadline, no VA-laatste-termijn, no jaarafsluiting
        assert rows == []

    def test_december_emits_va_laatste_termijn(self):
        from services.dashboard import _seasonal_action_rows
        rows = _seasonal_action_rows(today=date(2026, 12, 15))
        va_rows = [r for r in rows if r.kind == 'va_laatste_termijn']
        assert len(va_rows) == 1


class TestLoadDashboardWidgetsConfig:
    def test_null_input_returns_defaults(self):
        from services.dashboard import (
            load_dashboard_widgets_config, DEFAULT_WIDGETS,
        )
        result = load_dashboard_widgets_config(None)
        # All keys present
        for key in DEFAULT_WIDGETS:
            assert key in result['widgets']
        # Default-on for I-1..I-4
        assert result['widgets']['I-1'] is True
        assert result['widgets']['I-4'] is True

    def test_invalid_json_returns_defaults(self):
        from services.dashboard import load_dashboard_widgets_config
        result = load_dashboard_widgets_config('not valid json')
        assert result['widgets']['I-1'] is True

    def test_unknown_keys_ignored(self):
        from services.dashboard import load_dashboard_widgets_config
        config_in = '{"schema_version": 1, "widgets": {"I-99": true}}'
        result = load_dashboard_widgets_config(config_in)
        assert 'I-99' not in result['widgets']

    def test_missing_keys_use_defaults(self):
        from services.dashboard import load_dashboard_widgets_config
        # Only specifies I-5; rest must use defaults
        config_in = '{"schema_version": 1, "widgets": {"I-5": true}}'
        result = load_dashboard_widgets_config(config_in)
        assert result['widgets']['I-5'] is True  # explicit
        assert result['widgets']['I-1'] is True  # default-on
        assert result['widgets']['I-6'] is False  # default-off

    def test_schema_version_mismatch_falls_through_to_defaults(self):
        from services.dashboard import load_dashboard_widgets_config
        config_in = '{"schema_version": 99, "widgets": {"I-1": false}}'
        result = load_dashboard_widgets_config(config_in)
        # Falls through to defaults — I-1 default-on
        assert result['widgets']['I-1'] is True


class TestComputeSphPrognose:
    def test_zero_winst_zero_premium(self):
        from services.dashboard import compute_sph_prognose
        result = compute_sph_prognose(winst_extrapolatie=0.0, jaar=2026)
        assert result['pensioengrondslag'] == 0.0
        assert result['jaarverplichting'] == 0.0

    def test_winst_below_franchise_zero_premium(self):
        from services.dashboard import compute_sph_prognose
        # Winst 10k < franchise 19172 → grondslag 0 → premium 0
        result = compute_sph_prognose(winst_extrapolatie=10_000.0, jaar=2026)
        assert result['pensioengrondslag'] == 0.0
        assert result['jaarverplichting'] == 0.0

    def test_mid_winst_above_franchise(self):
        from services.dashboard import compute_sph_prognose
        # Winst 80k → grondslag = 80000-19172 = 60828 → premium = 60828 × 0.2394
        result = compute_sph_prognose(winst_extrapolatie=80_000.0, jaar=2026)
        assert result['pensioengrondslag'] == 60_828
        assert abs(result['jaarverplichting'] - 14562.22) < 0.01

    def test_winst_above_cap_clamped(self):
        from services.dashboard import compute_sph_prognose
        # Winst 200k → grondslag clamped at cap 137800
        # 137800 × 0.2394 = 32989.32 (cap × rate, geen franchise-aftrek
        # nadat min() geclampt heeft)
        result = compute_sph_prognose(winst_extrapolatie=200_000.0, jaar=2026)
        assert result['pensioengrondslag'] == 137_800
        assert abs(result['jaarverplichting'] - 32989.32) < 0.01
