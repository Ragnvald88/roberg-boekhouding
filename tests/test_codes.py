"""Tests voor domain.codes pure helpers — humanize, build_code_options, derive_activiteit."""

from domain.codes import (
    CODES,
    humanize_legacy_code,
    build_code_options,
    derive_activiteit,
)


# === humanize_legacy_code ===

class TestHumanizeLegacyCode:

    def test_empty_string_returns_geen(self):
        assert humanize_legacy_code('') == '(geen)'

    def test_wdagpraktijk_int(self):
        assert humanize_legacy_code('WDAGPRAKTIJK_70') == 'Praktijkdienst (€ 70/u)'

    def test_wdagpraktijk_decimal(self):
        assert humanize_legacy_code('WDAGPRAKTIJK_77,50') == 'Praktijkdienst (€ 77,50/u)'

    def test_anw_single_segment(self):
        assert humanize_legacy_code('ANW_WEEKEND') == 'ANW · weekend'

    def test_anw_multi_segment_keeps_2letter_caps(self):
        assert humanize_legacy_code('ANW_DR_WERKDAG_NACHT_ACHTERWACHT') == \
            'ANW · DR · werkdag · nacht · achterwacht'

    def test_anw_gr_segment(self):
        assert humanize_legacy_code('ANW_GR_WEEKEND_DAG') == 'ANW · GR · weekend · dag'

    def test_aw_werkdag(self):
        assert humanize_legacy_code('AW-WK-A') == 'AW · werkdag · A'

    def test_aw_weekend(self):
        assert humanize_legacy_code('AW-WKND-A') == 'AW · weekend · A'

    def test_titlecased_freetext_unchanged(self):
        assert humanize_legacy_code('Admin') == 'Admin'

    def test_long_uppercase_titlecased(self):
        assert humanize_legacy_code('REISTIJD') == 'Reistijd'

    def test_short_uppercase_acronym_unchanged(self):
        assert humanize_legacy_code('AQUI') == 'AQUI'

    def test_smoke_all_db_codes_non_empty(self):
        """Alle 26 codes uit live DB (snapshot 2026-05-09) leveren non-empty string op."""
        db_codes = [
            'WDAGPRAKTIJK_70', 'WDAGPRAKTIJK_77,50', 'Admin', '', 'WERKDAG',
            'ANW_WEEKEND', 'WDAGPRAKTIJK_80', 'ANW_GR_WEEKEND_DAG', 'ANW_AVOND',
            'ANW_DR_WEEKEND_DAG', 'NSCHL', 'AW-WK-A',
            'ANW_DR_WERKDAG_AVOND_ACHTERWACHT', 'ANW_DR_WEEKEND_ACHTERWACHT',
            'ANW_NACHT', 'ANW_DR_WERKDAG_AVOND', 'ANW_GR_WERKDAG_AVOND',
            'AW-WKND-A', 'AW-WK-E', 'ANW_GR_WEEKEND_AVOND', 'REISTIJD',
            'AW-WK-H', 'AQUI', 'ANW_DR_WERKDAG_NACHT_ACHTERWACHT',
            'ANW_DR_WERKDAG_NACHT', 'ANW_DR_WEEKEND_AVOND',
        ]
        for c in db_codes:
            result = humanize_legacy_code(c)
            assert isinstance(result, str)
            assert result != '', f'humanize_legacy_code({c!r}) returned empty'


# === build_code_options ===

class TestBuildCodeOptions:

    def test_none_returns_codes_dict(self):
        result = build_code_options(None)
        assert result == CODES

    def test_known_code_returns_codes_dict(self):
        result = build_code_options('WERKDAG')
        assert result == CODES
        assert 'WERKDAG' in result

    def test_legacy_code_added_with_humanized_label(self):
        result = build_code_options('WDAGPRAKTIJK_77,50')
        assert result['WDAGPRAKTIJK_77,50'] == 'Praktijkdienst (€ 77,50/u)'
        # Original CODES entries still present
        assert result['WERKDAG'] == 'Waarneming dagpraktijk'

    def test_empty_string_added_as_geen(self):
        result = build_code_options('')
        assert result[''] == '(geen)'

    def test_unknown_acronym_added_with_humanizer_fallback(self):
        result = build_code_options('AQUI')
        assert result['AQUI'] == 'AQUI'

    def test_does_not_mutate_codes_dict(self):
        """Belangrijk: CODES is module-level, mag NIET muteren."""
        before = dict(CODES)
        build_code_options('WDAGPRAKTIJK_99')
        assert CODES == before


# === derive_activiteit ===

class TestDeriveActiviteit:

    def test_known_code_returns_canonical_label(self):
        assert derive_activiteit('WERKDAG', None) == 'Waarneming dagpraktijk'

    def test_known_code_canonical_wins_over_current(self):
        """Canonical CODES-label heeft voorrang op current_activiteit voor known codes."""
        assert derive_activiteit('WERKDAG', 'Custom tekst') == 'Waarneming dagpraktijk'

    def test_legacy_code_preserves_historic_activiteit(self):
        """Legacy code + historische activiteit → behoud historische tekst (geen overschrijving)."""
        assert derive_activiteit('WDAGPRAKTIJK_77,50', 'Praktijk Dr. X') == 'Praktijk Dr. X'

    def test_legacy_code_no_history_falls_back_to_humanizer(self):
        assert derive_activiteit('WDAGPRAKTIJK_77,50', None) == 'Praktijkdienst (€ 77,50/u)'

    def test_empty_code_preserves_current(self):
        assert derive_activiteit('', 'Vrije tekst') == 'Vrije tekst'

    def test_empty_code_no_current_returns_empty(self):
        assert derive_activiteit('', None) == ''
