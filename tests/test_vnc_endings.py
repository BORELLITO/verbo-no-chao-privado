import json, unittest
import numpy as np
from agents import vnc_endings as E, vnc_style as ST


class T(unittest.TestCase):
    def test_contract_valid(self):
        self.assertEqual(E.check_contract(), [])

    def test_rotation_legacy_and_no_consecutive_repeat(self):
        self.assertEqual([E.choose("E01"), E.choose("E02")], ["A", "A"])
        seq = [E.choose(f"E{n:02d}") for n in range(3, 40)]
        self.assertEqual(seq[:6], ["C", "D", "E", "C", "D", "E"])
        self.assertTrue(all(a != b for a, b in zip(seq, seq[1:])))

    def test_layers_per_variant_distinct_and_known(self):
        c = E.load_contract(); ids = {v: set(E.layer_ids(v, c).values()) for v in c["variants"]}
        self.assertTrue(all(len(x) == 3 for x in ids.values()))
        self.assertEqual(E.layer_ids("A"), {})

    def test_contract_mutations_are_caught(self):
        c = json.loads(json.dumps(E.load_contract())); c["duration_s"] = 8.0
        self.assertTrue(E.check_contract(c))
        c = json.loads(json.dumps(E.load_contract())); c["variants"]["D"]["layers"]["rain"]["window"] = [3, 2, 1, 0, 0.5]
        self.assertTrue(any("janela" in e for e in E.check_contract(c)))
        c = json.loads(json.dumps(E.load_contract())); c["order"] = ["C", "D"]
        self.assertTrue(any("ordem" in e for e in E.check_contract(c)))

    def test_horizon_detection(self):
        g = np.full((1920, 1080), 200.0, np.float32); g[880:] = 90.0
        y = E.detect_horizon(g); self.assertTrue(abs(y - 880) <= 8)
        self.assertIsNone(E.detect_horizon(np.full((1920, 1080), 120.0, np.float32)))      # sem borda -> sol sobe sem recorte
        g2 = np.tile(np.linspace(0, 255, 1920, dtype=np.float32)[:, None], (1, 1080)); self.assertIsNone(E.detect_horizon(g2))   # gradiente suave nao e horizonte

    def test_tail_ass_keeps_only_cta_lines_relative(self):
        fam = "Fam"; hdr = "[Script Info]\nPlayResX: 1080\n\n[V4+ Styles]\nFormat: x\n" + "\n".join(s.format(fam=fam) for s in ST.STYLE_TEMPLATES) + "\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        adur = 80.0; T = adur + 9.5
        def ln(st, d, t): return f"Dialogue: 2,{ST.ts(adur + d['start'])},{ST.ts(T - d['end_from_T'])},{st},,0,0,0,,{{\\fad({d['fad'][0]},{d['fad'][1]})}}{t}\n"
        fin = hdr + "Dialogue: 0,0:00:01.00,0:00:02.00,Caption,,0,0,0,,oi\n" + ln("Credit", ST.CREDIT, "Hab") + ln("CTA1", ST.CTA1, "a") + ln("CTA2", ST.CTA2, "b")
        out, n = E.tail_ass(fin, adur); self.assertEqual(n, 3); self.assertNotIn("Caption,,", out)
        self.assertIn("Dialogue: 2,0:00:03.40", out); self.assertIn("Dialogue: 2,0:00:04.50", out); self.assertIn("Dialogue: 2,0:00:06.00", out)

    def test_contrast_math(self):
        self.assertAlmostEqual(E.contrast(1.0, 0.0), 21.0, places=1)
        self.assertGreater(E.contrast(E._lum(np.array(E.TEXT_RGB["cta1"], np.float64)), 0.03), 4.5)

    def test_flow_never_touches_style_lock_files(self):
        import hashlib; from pathlib import Path
        self.assertEqual(E.check_contract(), [])
        self.assertEqual(ST.TAIL_HOLD + ST.TAIL_BLACK, E.load_contract()["duration_s"])


if __name__ == "__main__":
    unittest.main()
