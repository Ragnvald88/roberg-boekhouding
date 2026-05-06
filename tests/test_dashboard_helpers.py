"""Unit tests for services.dashboard pure helpers."""
from datetime import date

from services.dashboard import (
    ActionRow,
    prioritise_actions,
)


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


class TestShouldShowPriveZone:
    """Test the Privé-zone visibility/collapse helper (Sprint H T5.1).

    Auto-detect path renders only when AOV-data exists; user-override
    forces render regardless of AOV-state, optionally collapsed.
    """

    def test_no_aov_no_override_hidden(self):
        from services.dashboard import should_show_prive_zone
        # Auto-detect path: no AOV → don't render
        assert should_show_prive_zone(0, None) == (False, False)

    def test_has_aov_no_override_visible(self):
        from services.dashboard import should_show_prive_zone
        # Auto-detect path: AOV exists → render visible
        assert should_show_prive_zone(5, None) == (True, False)

    def test_user_override_collapsed_renders_collapsed(self):
        from services.dashboard import should_show_prive_zone
        # User explicit collapsed (even with no AOV) → render but collapsed
        assert should_show_prive_zone(0, True) == (True, True)
        assert should_show_prive_zone(5, True) == (True, True)

    def test_user_override_visible_renders_visible(self):
        from services.dashboard import should_show_prive_zone
        # User explicit visible (even with no AOV) → render visible
        assert should_show_prive_zone(0, False) == (True, False)
        assert should_show_prive_zone(5, False) == (True, False)
