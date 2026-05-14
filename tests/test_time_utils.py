import unittest

from bot.time_utils import close_ts_after


class TimeUtilsTest(unittest.TestCase):
    def test_close_ts_after_rounds_to_next_five_minute_boundary(self):
        self.assertEqual(close_ts_after(0), 300)
        self.assertEqual(close_ts_after(299), 300)
        self.assertEqual(close_ts_after(300), 600)


if __name__ == "__main__":
    unittest.main()

