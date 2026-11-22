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

    def test_final_words_omitted_by_asr_are_anchored_after_previous(self):
        # E09: o ASR omitiu "ou B" no fim; ancorar apos a ultima palavra reconhecida (limite de 2) em vez de bloquear
        a = asr(); n = len(a)
        w, s = A.align(self.canon, a[:n - 2], DUR)
        self.assertEqual(s["trailing_interpolated"], 2)
        self.assertEqual(w[-1]["alignment"], "INTERPOLATED_TRAILING")
        self.assertLessEqual(w[-2]["end"], w[-1]["start"] + 0.05)
        self.assertLessEqual(w[-1]["end"], DUR)

    def test_too_many_final_words_omitted_still_blocks(self):
        a = asr(); n = len(a)
        with self.assertRaises(A.AlignError): A.align(self.canon, a[:n - 3], DUR)

    def test_word_before_long_pause_is_anchored_not_blocked(self):
        # palavra omitida pelo ASR antes de uma pausa longa (narracao com pausas dramaticas) deve ser ancorada na vizinha anterior
        a = asr(); i = 10
        a[i + 1] = dict(a[i + 1], start=a[i]["end"] + 2.5, end=a[i]["end"] + 2.9)
        for k in range(i + 2, len(a)): a[k] = dict(a[k], start=a[k]["start"] + 2.5, end=a[k]["end"] + 2.5)
        w, s = A.align(self.canon, [x for j, x in enumerate(a) if j != i], DUR + 3)
        self.assertEqual(s["edge_interpolated"], 1); self.assertEqual(w[i]["alignment"], "INTERPOLATED_EDGE")
        self.assertLessEqual(w[i]["end"], w[i + 1]["start"])

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

    def test_check_model_tolerates_unrecognized_words(self):
        a, _ = A.align(self.canon, asr(), DUR)
        b, s = A.align(self.canon, asr(drop=tuple(range(15, 25))), DUR, strict=False)
        self.assertEqual(s["unmatched"], 10)
        self.assertEqual(A.cross_check(a, b)["compared"], 172)

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


class TrailingMeasured(unittest.TestCase):
    def _sig(self, sr=16000, dur=3.0, bursts=((1.0, 1.3), (2.0, 2.4))):
        import math
        n = int(sr * dur); s = [0.0] * n
        for a, b in bursts:
            for i in range(int(a * sr), int(b * sr)): s[i] = 0.2 * math.sin(2 * math.pi * 200 * i / sr)
        return s, sr

    def _words(self):
        return [{"text": "fim", "start": 0.5, "end": 0.9, "alignment": "EXACT"},
                {"text": "ou", "start": 0.92, "end": 1.2, "alignment": "INTERPOLATED_TRAILING"},
                {"text": "B.", "start": 1.22, "end": 1.5, "alignment": "INTERPOLATED_TRAILING"}]

    def test_two_bursts_give_one_word_each(self):
        s, sr = self._sig(); w, r = A.refine_trailing(self._words(), s, sr, 3.0)
        self.assertEqual(r["trailing_measured"], 2)
        self.assertAlmostEqual(w[1]["start"], 1.0, delta=0.03); self.assertAlmostEqual(w[2]["start"], 2.0, delta=0.03)
        self.assertEqual(w[2]["alignment"], "TRAILING_MEASURED_ENERGY")

    def test_single_burst_split_by_weight(self):
        s, sr = self._sig(bursts=((2.0, 2.4),)); w, _ = A.refine_trailing(self._words(), s, sr, 3.0)
        self.assertAlmostEqual(w[1]["start"], 2.0, delta=0.03); self.assertAlmostEqual(w[2]["end"], 2.4, delta=0.03)
        self.assertLessEqual(w[1]["end"], w[2]["start"] + 1e-6)

    def test_silence_after_last_word_blocks(self):
        s, sr = self._sig(bursts=())
        with self.assertRaises(A.AlignError): A.refine_trailing(self._words(), s, sr, 3.0)

    def test_previous_word_tail_is_not_a_new_word(self):
        s, sr = self._sig(bursts=((0.5, 0.95), (2.0, 2.4)))
        w, _ = A.refine_trailing(self._words(), s, sr, 3.0)
        self.assertGreaterEqual(w[1]["start"], 1.9)
