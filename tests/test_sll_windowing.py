import unittest
from sll_windowing import window_rectangle


class WorkAreaTests(unittest.TestCase):
    def test_toast_is_bottom_right_above_any_taskbar_and_on_negative_monitors(self):
        for area in ((0, 0, 1920, 1040), (0, 40, 800, 600), (-1280, -720, 0, -48), (60, 0, 1920, 1040)):
            with self.subTest(area=area):
                width, height, x, y = window_rectangle(area, (420, 180), decoration=(0, 0), position="bottom_right")
                self.assertEqual(x+width, area[2]-12)
                self.assertEqual(y+height, area[3]-12)
                self.assertGreaterEqual(x, area[0])
                self.assertGreaterEqual(y, area[1])

    def test_small_scaled_secondary_and_taskbar_areas_contain_entire_window(self):
        for area in ((0, 0, 1280, 672), (0, 40, 800, 600), (-1280, -720, 0, -48), (60, 0, 1920, 1040)):
            with self.subTest(area=area):
                width, height, x, y = window_rectangle(area, (1140, 840))
                self.assertGreaterEqual(x, area[0])
                self.assertGreaterEqual(y, area[1])
                self.assertLessEqual(x+width+16, area[2])
                self.assertLessEqual(y+height+48, area[3])
                self.assertLessEqual(abs((x+width+16-area[0]) - (area[2]-x)), 1)
