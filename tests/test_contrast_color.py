"""Unit tests for components.utils.contrast_text_color."""

import pytest

from components.utils import contrast_text_color


class TestContrastTextColor:
    """WCAG-based contrast text-color decision."""

    def test_pure_white_background_returns_black(self):
        assert contrast_text_color('#FFFFFF') == 'black'

    def test_pure_black_background_returns_white(self):
        assert contrast_text_color('#000000') == 'white'

    def test_dark_teal_returns_white(self):
        # --accent token #0F766E (teal-700, donker, luminance ~0.142)
        assert contrast_text_color('#0F766E') == 'white'

    def test_light_teal_tint_returns_black(self):
        # licht teal tint #B2EBE6 (luminance ~0.746)
        assert contrast_text_color('#B2EBE6') == 'black'

    def test_dark_purple_returns_white(self):
        # --wd-anw color #7E22CE (paars, donker, luminance ~0.100)
        assert contrast_text_color('#7E22CE') == 'white'

    def test_light_gray_returns_black(self):
        # Apple system gray #F5F5F7 (licht, luminance ~0.914)
        assert contrast_text_color('#F5F5F7') == 'black'

    def test_mid_gray_threshold(self):
        # Middel-grijs #808080 valt net boven threshold (luminance ~0.216)
        # → 0.216 > 0.179 → 'black'
        assert contrast_text_color('#808080') == 'black'

    def test_lowercase_hex_works(self):
        assert contrast_text_color('#0f766e') == 'white'

    def test_mixed_case_hex_works(self):
        # mixed-case parsing — donkere paars-purple #7E22CE → 'white'
        assert contrast_text_color('#7e22Ce') == 'white'

    def test_invalid_format_no_hash_raises(self):
        with pytest.raises(ValueError, match='must be #RRGGBB'):
            contrast_text_color('FFFFFF')

    def test_invalid_format_short_raises(self):
        with pytest.raises(ValueError, match='must be #RRGGBB'):
            contrast_text_color('#FFF')

    def test_invalid_format_long_raises(self):
        with pytest.raises(ValueError, match='must be #RRGGBB'):
            contrast_text_color('#FFFFFFFF')

    def test_invalid_chars_raises(self):
        with pytest.raises(ValueError, match='non-hex chars'):
            contrast_text_color('#GGGGGG')

    def test_non_string_raises(self):
        with pytest.raises(ValueError, match='must be #RRGGBB'):
            contrast_text_color(0xFFFFFF)  # type: ignore[arg-type]

    def test_quasar_positive_green_black_text(self):
        # #059669 (Quasar positive) — luminance ~0.229 > 0.179 → 'black'
        # (groen heeft hoge G-coefficient 0.7152 in WCAG → telt zwaarder)
        assert contrast_text_color('#059669') == 'black'

    def test_quasar_warning_amber_black_text(self):
        # #D97706 (Quasar warning) — luminance ~0.280 > 0.179 → 'black'
        assert contrast_text_color('#D97706') == 'black'
