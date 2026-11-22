import unittest

class LogoFrameCount(unittest.TestCase):
    def test_float_noise_keeps_lock_count(self):
        for adur in (55.48, 55.0, 61.37, 67.63, 58.1):
            T = adur + 3.0 + 6.5; t0 = adur + 0.5
            self.assertEqual(int(round((T - t0) * 30, 6)) + 2, 272, adur)

if __name__ == "__main__":
    unittest.main()
