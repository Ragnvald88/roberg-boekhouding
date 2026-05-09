"""Save-flow regression-tests + source-pin tests voor werkdag_form.

NiceGUI dialog is niet headless te renderen, dus we testen save-flow via
de pure helpers en source-pins voor visuele/structurele invarianten.
"""

import inspect
from types import SimpleNamespace

from domain.codes import derive_activiteit


def _fake_werkdag(**overrides):
    base = dict(
        id=1, datum='2026-05-09', klant_id=10, klant_naam='Test',
        code='WERKDAG', activiteit='Waarneming dagpraktijk',
        locatie='Praktijk', uren=8.0, km=0, tarief=90.0, km_tarief=0.23,
        urennorm=1, opmerking='', factuurnummer='',
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# === Save-flow voor activiteit-derivation ===

class TestSaveFlowLegacyCode:

    def test_known_code_uses_canonical_label(self):
        """code='WERKDAG' → activiteit='Waarneming dagpraktijk' (canonical wins)."""
        result = derive_activiteit(
            code='WERKDAG',
            current_activiteit='Custom legacy tekst',
        )
        assert result == 'Waarneming dagpraktijk'

    def test_legacy_code_preserves_historic_activiteit(self):
        """Edit-save van WDAGPRAKTIJK_77,50 mag activiteit-tekst NIET overschrijven."""
        wd = _fake_werkdag(code='WDAGPRAKTIJK_77,50', activiteit='Praktijk Dr. X')
        result = derive_activiteit(
            code=wd.code,
            current_activiteit=wd.activiteit,
        )
        assert result == 'Praktijk Dr. X'
        # Negatief: NIET de generieke fallback
        assert result != 'Waarneming dagpraktijk'

    def test_empty_code_preserves_freetext_activiteit(self):
        """code='' edit-save: activiteit blijft 'Vrije tekst'."""
        wd = _fake_werkdag(code='', activiteit='Vrije tekst')
        result = derive_activiteit(
            code=wd.code,
            current_activiteit=wd.activiteit,
        )
        assert result == 'Vrije tekst'

    def test_save_flow_imports_derive_activiteit(self):
        """Source-pin: werkdag_form moet derive_activiteit importeren."""
        import components.werkdag_form
        source = inspect.getsource(components.werkdag_form)
        assert 'derive_activiteit' in source, \
            'werkdag_form moet derive_activiteit gebruiken voor activiteit-bepaling'


# === Pattern-mode source-pin ===

class TestPatternMode:

    def test_pattern_mode_disables_inputs(self):
        """In pattern-mode (pattern_id is set) zijn klant/code/uren/etc disabled.

        Source-pin: vereist code-pad dat klant_select/code_select met
        .props('disable') én uren_input/tarief_input/km_input/km_tarief_input
        met .props('readonly') configureert wanneer pattern_id is not None.
        """
        import components.werkdag_form
        source = inspect.getsource(components.werkdag_form)
        # Verwacht een if-blok dat op pattern_id triggered en disable/readonly toepast
        assert "pattern_id is not None" in source, \
            'Pattern-mode disabled-state moet expliciet op pattern_id branchen'
        assert ".props('disable')" in source or ".props('readonly')" in source, \
            'Pattern-mode moet inputs disabled/readonly maken'

    def test_pattern_mode_button_label_bevestigen(self):
        """Footer-knop label is 'Bevestigen' ipv 'Opslaan' in pattern-mode."""
        import components.werkdag_form
        source = inspect.getsource(components.werkdag_form)
        assert "'Bevestigen'" in source, \
            'Pattern-mode footer moet "Bevestigen" knop tonen'

    def test_pattern_mode_no_opslaan_en_nieuw(self):
        """Source-pin: 'Opslaan & Nieuw' knop wordt NIET aangemaakt in pattern-mode.

        Bestaand: button is gegateerd op `not is_edit and pattern_id is None`.
        Test pinneert dat deze guard intact blijft.
        """
        import components.werkdag_form
        source = inspect.getsource(components.werkdag_form)
        assert "not is_edit and pattern_id is None" in source, \
            'Opslaan & Nieuw moet niet getoond worden in pattern-mode'


# === Visuele redesign source-pins ===

class TestVisualRedesign:

    def test_imports_format_datum_lang(self):
        import components.werkdag_form
        source = inspect.getsource(components.werkdag_form)
        assert 'format_datum_lang' in source, \
            'werkdag_form moet format_datum_lang importeren voor de header-subtitle'

    def test_imports_build_code_options(self):
        import components.werkdag_form
        source = inspect.getsource(components.werkdag_form)
        assert 'build_code_options' in source, \
            'werkdag_form moet build_code_options gebruiken voor activiteit-dropdown'

    def test_no_ui_separator_calls(self):
        """Sprint K-redesign: geen ui.separator() meer — sections vervangen lijnen."""
        import components.werkdag_form
        source = inspect.getsource(components.werkdag_form)
        assert 'ui.separator()' not in source, \
            'ui.separator() is verwijderd — gebruik .settings-section blokken'

    def test_uses_werkdag_dialog_card_class(self):
        """Source-pin: nieuwe CSS class wordt op de outer card gezet."""
        import components.werkdag_form
        source = inspect.getsource(components.werkdag_form)
        assert 'werkdag-dialog-card' in source, \
            'werkdag-dialog-card class moet op de outer card staan voor styling'

    def test_uses_settings_section_thrice(self):
        """Drie sections (Basis / Werk / Vergoeding) gebruiken settings-section."""
        import components.werkdag_form
        source = inspect.getsource(components.werkdag_form)
        assert source.count("settings-section w-full") >= 3, \
            'Verwacht 3+ settings-section blokken (Basis/Werk/Vergoeding)'

    def test_default_focus_on_klant_in_add_mode(self):
        """Add-mode zonder klant-prefill: focus op klant_select.

        Source-pin: code-pad triggert .run_method('focus') of vergelijkbare
        focus-call op klant_select wanneer not is_edit en geen prefill klant_id.
        """
        import components.werkdag_form
        source = inspect.getsource(components.werkdag_form)
        assert 'klant_select.run_method' in source or ".props('autofocus')" in source, \
            'Add-mode moet focus op klant_select zetten via run_method of autofocus'
