"""Contrast checks for the Southland Labs input and action palette."""
import unittest

import sll_theme as theme


def contrast(foreground, background):
    def luminance(color):
        channels = [int(color[offset:offset + 2], 16) / 255 for offset in (1, 3, 5)]
        linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
                  for value in channels]
        return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    light, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


class ThemeContrastTests(unittest.TestCase):
    def test_caret_and_input_text_remain_readable_on_dark_fields(self):
        self.assertGreaterEqual(contrast(theme.INK, theme.FIELD), 7)
        self.assertGreaterEqual(contrast(theme.INK, theme.SELECTION), 4.5)

    def test_secondary_text_remains_readable_on_each_panel(self):
        for surface in (theme.PAGE, theme.SURFACE, theme.RAISED):
            with self.subTest(surface=surface):
                self.assertGreaterEqual(contrast(theme.MUTED, surface), 4.5)

    def test_primary_action_text_remains_readable_on_hover(self):
        for color in (theme.ACCENT, theme.ACCENT_HOVER):
            with self.subTest(color=color):
                self.assertGreaterEqual(contrast(theme.ACCENT_INK, color), 7)


if __name__ == "__main__":
    unittest.main()
