"""Tests for pages.agenda._pill_color_style — defensive klant-color render guard.

Sprint D S4: pure signature `_pill_color_style(klant_color, toggle)` — geen
pill-mock nodig. Verifieert alle defensive-guards uit Codex risk #1 +
contrast-text-color round-trip.
"""

from pages.agenda import _pill_color_style


class TestPillColorStyle:
    """Defensive klant-color overlay helper."""

    def test_toggle_off_returns_empty(self):
        assert _pill_color_style('#0F766E', False) == ''

    def test_none_color_returns_empty(self):
        assert _pill_color_style(None, True) == ''

    def test_non_string_returns_empty(self):
        assert _pill_color_style(123, True) == ''  # type: ignore[arg-type]

    def test_short_hex_returns_empty(self):
        assert _pill_color_style('#FFF', True) == ''

    def test_long_hex_returns_empty(self):
        assert _pill_color_style('#FFFFFFFF', True) == ''

    def test_no_hash_prefix_returns_empty(self):
        assert _pill_color_style('FFFFFF', True) == ''

    def test_malformed_chars_returns_empty(self):
        assert _pill_color_style('#GGGGGG', True) == ''

    def test_empty_string_returns_empty(self):
        assert _pill_color_style('', True) == ''

    def test_dark_color_returns_white_text(self):
        # Teal-700 (Sprint A dagpraktijk-accent) — dark → white
        result = _pill_color_style('#0F766E', True)
        assert 'background: #0F766E' in result
        assert 'color: white' in result

    def test_light_color_returns_black_text(self):
        # Lichte grijs — light → black
        result = _pill_color_style('#F5F5F7', True)
        assert 'background: #F5F5F7' in result
        assert 'color: black' in result

    def test_toggle_off_with_invalid_color_still_empty(self):
        # toggle wint van color-validity check (early return)
        assert _pill_color_style('not-a-color', False) == ''

    def test_returned_style_is_terminated_with_semicolon(self):
        # CSS hygiene: trailing semicolon zodat style-string concat niet breekt
        result = _pill_color_style('#000000', True)
        assert result.endswith(';')
