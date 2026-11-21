import json, unittest
import numpy as np
from agents import vnc_curate as C

HTML = '''<a href="/free-stock-video/soft-rain-and-sun-shine-25375/"><img src="https://assets.mixkit.co/videos/25375/25375-thumb-360-0.jpg"></a>
<video src="https://assets.mixkit.co/videos/25375/25375-360.mp4"></video>
<a href="/free-stock-video/young-woman-making-call-in-rain-100855/"></a><video src="https://assets.mixkit.co/opaco123"></video>
<a href="/free-stock-video/window-on-a-rainy-day-2846/"></a><video src="https://assets.mixkit.co/videos/2846/2846-360.mp4"></video>
<a href="/free-stock-video/window-on-a-rainy-day-2846/"></a>'''


def frames(kind, n=12, h=90, w=160, seed=0):
    r = np.random.default_rng(seed); xx = np.linspace(0, 6, w)[None, :, None]; base = (90 + 40 * np.sin(xx + np.zeros((h, 1, 3)))).astype(np.uint8)
    if kind == "static":
        return [base.copy() for _ in range(n)]
    if kind == "moving":
        return [np.roll(base, i * 2, axis=1) for i in range(n)]
    if kind == "cuts":
        return [np.roll(base, i * 2, axis=1) if i != 6 else (255 - base) for i in range(n)]


class Curate(unittest.TestCase):
    def test_parse_listing_standard_urls_only_and_unique(self):
        got = C.parse_listing(HTML)
        self.assertEqual([g["id"] for g in got], ["25375", "2846"])
        self.assertEqual(got[0]["preview"], "https://assets.mixkit.co/videos/25375/25375-360.mp4")

    def test_title_filters(self):
        self.assertTrue(C.title_ok("window on a rainy day")[0])
        self.assertFalse(C.title_ok("young woman making call in rain")[0])
        self.assertFalse(C.title_ok("traffic on a rainy night")[0])
        self.assertFalse(C.title_ok("hands holding a candle")[0])
        self.assertTrue(C.title_ok("hands holding a candle", allow=["hands"])[0])

    def test_registry_exclusion(self):
        reg = {"episodes": {"E01": {"used": [{"source": "mixkit", "id": "41739"}, {"source": "coverr", "id": "x"}], "discarded_versions": {"v3": [{"source": "mixkit", "id": "9"}]}}}}
        self.assertEqual(C.used_ids(reg, "E02"), {"41739", "9"})

    def test_metrics_and_rejections(self):
        m_static = C.metrics_from_frames(frames("static")); m_move = C.metrics_from_frames(frames("moving")); m_cut = C.metrics_from_frames(frames("cuts"))
        self.assertIsNotNone(C.reject_reason(m_static, "mid", 8, 20, 1920, 1080))
        self.assertIn("estatico", C.reject_reason(m_static, "mid", 8, 20, 1920, 1080))
        self.assertIn("cortes", C.reject_reason(m_cut, "mid", 8, 20, 1920, 1080))
        self.assertIsNone(C.reject_reason(dict(m_move, brightness=90), "mid", 8, 20, 1920, 1080))
        self.assertIn("curto", C.reject_reason(dict(m_move, brightness=90), "mid", 8, 5, 1920, 1080))
        self.assertIn("vertical", C.reject_reason(dict(m_move, brightness=90), "mid", 8, 20, 1080, 1920))
        self.assertIn("brilho", C.reject_reason(dict(m_move, brightness=230), "dark", 8, 20, 1920, 1080))

    def test_score_prefers_mood_fit_and_keywords(self):
        m = {"brightness": 70, "saturation": 40, "motion": 5, "cut_ratio": 2, "sharp": 8}
        self.assertGreater(C.score(m, "dark", 2), C.score(dict(m, brightness=140), "dark", 0))

    def test_near_duplicates_removed(self):
        base = frames("moving")[3].mean(axis=2); other = np.flipud(base) * 0.3 + 90
        a = {"score": 2, "phash": C.dhash(base)}; b = {"score": 1.9, "phash": C.dhash(base * 0.98)}; c = {"score": 1.0, "phash": C.dhash(other)}
        top = C.pick_top([a, b, c])
        self.assertIn(a, top); self.assertNotIn(b, top)

    def test_template_covers_12_scenes_and_arc(self):
        from pathlib import Path
        t = json.loads((Path(C.ROOT) / "contracts/vnc_arc_template_v1.json").read_text(encoding="utf8"))["scenes"]
        self.assertEqual([s["id"] for s in t], [f"S{i:02d}" for i in range(1, 13)])
        self.assertTrue(all(s["mood"] in C.MOODS and s["queries"] for s in t))


if __name__ == "__main__":
    unittest.main()


def test_global_exclude_blocks_rosary_and_green_screen():
    from agents import vnc_curate as C
    assert not C.title_ok("hands holding rosary", allow=["hands"])[0]
    assert not C.title_ok("hand on green background", allow=["hands"])[0]
    assert C.title_ok("hands at sunset", allow=["hands"])[0]


class Manifest(unittest.TestCase):
    def _m(self):
        cl = [{"scene": f"S{i:02d}", "source": "mixkit", "id": str(i), "page": "p", "license": "L", "license_ok": True, "license_evidence": "e", "interval": [0, 5], "sha256": "s", "phashes": [1],
               "justification": "j", "scores": {}, "segment": {}} for i in range(1, 13)]
        return {"episode": "E02", "run_id": "1", "engine_version": "v", "status": "OK", "segments": [], "clips": cl, "reservation_state": "reserved", "qa": {}}

    def test_manifest_contract(self):
        m = self._m(); self.assertEqual(C.validate_manifest(m), [])
        m["clips"][3]["license_ok"] = False; self.assertTrue(C.validate_manifest(m))
        m = self._m(); m["clips"].pop(); self.assertIn("menos de 12 clipes", C.validate_manifest(m))
        m = self._m(); m["clips"][1]["id"] = "1"; self.assertIn("clipe repetido", C.validate_manifest(m))

    def test_license_check(self):
        self.assertTrue(C.license_check('<a href="https://mixkit.co/license/#videoFree">Mixkit Stock Video Free License</a>')[0])
        self.assertFalse(C.license_check("<html>nada</html>")[0])


class Vetos(unittest.TestCase):
    def test_plural_and_religious_or_urban_vetos(self):
        for t in ("houston skyscrapers", "burning incenses inside of a pot", "lady praying in front of a large altar", "aerial city skyline"):
            self.assertFalse(C.title_ok(t, allow=["hands"])[0], t)
        for t in ("heavy rain from an open window", "wheat field at sunrise", "mountains fog"):
            self.assertTrue(C.title_ok(t)[0], t)


class Narrativa(unittest.TestCase):
    def test_gate_needs_theme_not_loose_keyword(self):
        from agents import vnc_select as S
        ut = S.themes_of(["candle", "fire", "flame"])
        self.assertTrue(C.narrative_ok(S.title_themes("candles in the dark"), ut))
        self.assertFalse(C.narrative_ok(S.title_themes("houston buildings"), ut))
        self.assertFalse(C.narrative_ok(S.title_themes("handwriting a note"), S.themes_of(["hands", "holding"])))
        self.assertTrue(C.narrative_ok(S.title_themes("hands holding a candle"), S.themes_of(["hands"])))
        self.assertFalse(C.title_ok("scrabble by fire")[0])
