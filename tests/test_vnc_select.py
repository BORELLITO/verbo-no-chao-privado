import unittest
from agents import vnc_select as S


def cl(i, title, bright=100, ph=0, dur=15, sat=60, sharp=8, kw=1, motion=5):
    return {"id": str(i), "title": title, "phash": ph, "dur": dur, "kw_hit": kw, "mood_range": (70, 150), "mood_ok": True,
            "m": {"brightness": bright, "saturation": sat, "sharp": sharp, "motion": motion, "cut_ratio": 1}}


class Select(unittest.TestCase):
    plan = [{"scene": f"S{i:02d}", "duration": 6, "emotion": "espera"} for i in range(1, 4)]

    def test_no_repeat_and_global_beats_greedy(self):
        # a melhor opcao isolada da S02 repete o enquadramento da S01 -> a global troca por uma variada
        by = {"S01": [cl(1, "rain window", ph=0)], "S02": [cl(2, "rain drops", ph=1, kw=3), cl(3, "foggy valley", ph=(1 << 40) - 1, kw=2)], "S03": [cl(4, "mountain peak", ph=(1 << 50) - 1)]}
        seq, u, _ = S.select_sequence(self.plan, by)
        self.assertEqual([c["id"] for c in seq], ["1", "3", "4"])

    def test_unique_clips_even_if_in_two_scenes(self):
        shared = cl(1, "sea waves")
        by = {"S01": [shared], "S02": [shared, cl(2, "lake calm", ph=(1 << 33) - 1)], "S03": [cl(3, "sun rise", ph=(1 << 22) - 1)]}
        seq, _, _ = S.select_sequence(self.plan, by)
        self.assertEqual(len({c["id"] for c in seq}), 3)

    def test_block_when_scene_has_no_candidate_or_exhausted(self):
        self.assertIsNone(S.select_sequence(self.plan, {"S01": [cl(1, "a b")], "S02": [], "S03": [cl(2, "c d")]})[0])
        self.assertIsNone(S.select_sequence(self.plan, {"S01": [cl(1, "a b")], "S02": [cl(1, "a b")], "S03": [cl(2, "c d")]})[0])


class Themes(unittest.TestCase):
    def test_themes_of(self):
        self.assertEqual(S.themes_of(["dark-clouds", "rain"]), {"dark", "cloud", "rain"})
        self.assertIn("candle", S.themes_of(["candles"]))
