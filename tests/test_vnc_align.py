import json, random, unittest
from pathlib import Path
from agents import vnc_align as A

ROOT = Path(__file__).resolve().parents[1]
REFIT = json.loads((ROOT / "contracts/e01_v3_12_scene_refit_v1.json").read_text(encoding="utf8"))["scenes"]
TW = json.loads((ROOT / "contracts/e01_v3_voice_johnes_word_timing_v1.json").read_text(encoding="utf8"))["words"]
SCENES = [{"id": s["id"][-3:], "text": s["text"]} for s in REFIT]
DUR = 76.67


def asr(shift=0.0, drop=(), jitter=0.0, seed=1):
    r = random.Random(seed)
    return [{"text": w["text"].strip(".,?!"), "start": w["start"] + shift + r.uniform(-jitter, jitter), "end": w["end"] + shift}
            for i, w in enumerate(TW) if i not in drop]


class Align(unittest.TestCase):
    def setUp(self):
        self.canon, self.first = A.words_from_scenes(SCENES)

    def test_scene_split_matches_e01(self):
        self.assertEqual(len(self.canon), 182)
        self.assertEqual(self.first[:4], [0, 16, 20, 34])

    def test_align_recovers_times_and_scene_bounds(self):
        w, s = A.align(self.canon, asr(), DUR)
        self.assertEqual(s["interpolated"], 0)
        sc = A.scenes_from_words(w, self.first, DUR)
        self.assertEqual(sc[0]["start_seconds"], 0.0)
        self.assertEqual(sc[-1]["end_seconds"], DUR)
        for a, b in zip(sc, sc[1:]):
            self.assertEqual(a["end_seconds"], b["start_seconds"])
        for x, y in zip(sc, REFIT):  # fronteiras dentro de 0,5 s das do contrato aprovado (o refit centrava a fronteira na pausa)
            self.assertLess(abs(x["start_seconds"] - y["start_seconds"]), 0.5)

    def test_few_missing_words_are_interpolated_many_are_blocked(self):
        w, s = A.align(self.canon, asr(drop=(30, 77)), DUR)
        self.assertEqual(s["interpolated"], 2)
        with self.assertRaises(A.AlignError):
            A.align(self.canon, asr(drop=tuple(range(40, 70))), DUR)

    def test_cross_check_accepts_close_and_blocks_divergent_models(self):
        a, _ = A.align(self.canon, asr(), DUR); b, _ = A.align(self.canon, asr(shift=0.05, jitter=0.03), DUR)
        self.assertLess(A.cross_check(a, b)["median_abs_start_diff"], 0.15)
        c, _ = A.align(self.canon, asr(shift=0.4), DUR)
        with self.assertRaises(A.AlignError):
            A.cross_check(a, c)

    def test_scenes_must_be_twelve_in_order(self):
        with self.assertRaises(A.AlignError):
            A.words_from_scenes(SCENES[:11])

    def test_auto_captions_from_aligned_words(self):
        from agents.e01_v2_caption_pipeline import make_cues
        canon = [dict(c, block=w["block"]) for c, w in zip(self.canon, TW)]
        w, _ = A.align(canon, asr(), DUR)
        cues = make_cues(w, DUR)
        self.assertGreaterEqual(len(cues), 30)
        self.assertLessEqual(sum(1 for c in cues if c.get("rule_violations")), 2)


if __name__ == "__main__":
    unittest.main()
