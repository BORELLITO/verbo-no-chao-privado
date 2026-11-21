import json, unittest
from pathlib import Path
from agents import vnc_plan as P

ROOT = Path(__file__).resolve().parents[1]
TPL = json.loads((ROOT / "contracts/vnc_arc_template_v1.json").read_text())["scenes"]


def cfg(n=12, text="Você já repetiu a mesma pergunta tantas vezes na chuva, sozinho, em silêncio?"):
    return {"scenes": [{"id": f"S{i:02d}", "block": "x", "text": text} for i in range(1, n + 1)]}


class Plan(unittest.TestCase):
    def test_e01_script_plans_12_units_with_rain_for_rain_text(self):
        c = json.loads((ROOT / "episodes/E01.json").read_text())
        plan, diag = P.build_plan(c, TPL)
        self.assertEqual((len(plan), diag), (12, []))
        self.assertEqual(plan[0]["mood"], "dark"); self.assertIn("rain", plan[0]["queries"])
        self.assertTrue(all(u["end"] > u["start"] for u in plan)); self.assertEqual(plan[3]["start"], plan[2]["end"])

    def test_less_than_12_is_incompatible_and_not_silently_fixed(self):
        plan, diag = P.build_plan(cfg(10), TPL); self.assertTrue(any("INCOMPATIVEL" in d for d in diag))

    def test_placeholder_and_too_short_units_block(self):
        c = cfg(); c["scenes"][1]["text"] = "..."; plan, diag = P.build_plan(c, TPL); self.assertTrue(any("placeholder" in d for d in diag))
        plan, diag = P.build_plan(cfg(text="Sim, claro."), TPL); self.assertTrue(any("ritmo inviavel" in d for d in diag))

    def test_claude_visual_overrides_lexicon_and_is_flagged(self):
        c = cfg(); c["scenes"][0]["visual"] = {"meaning": "silêncio de Deus", "mood": "mid", "queries": ["fog"], "avoid": ["rain"]}
        plan, _ = P.build_plan(c, TPL); self.assertEqual(plan[0]["interpretation"], "claude"); self.assertEqual(plan[0]["queries"][0], "fog"); self.assertEqual(plan[0]["mood"], "mid")
        self.assertEqual(plan[1]["interpretation"], "lexico")

    def test_real_timing_beats_estimate(self):
        plan, _ = P.build_plan(cfg(), TPL, {"S01": 9.0}); self.assertEqual(plan[0]["duration"], 9.0); self.assertEqual(plan[0]["duration_source"], "timing_real")
