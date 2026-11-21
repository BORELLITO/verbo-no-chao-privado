import unittest
from agents import vnc_vision as V


class Fake:
    """Backend falso: textos -> vetores ortogonais por rotulo; imagem = vetor do 'conteudo'."""
    AX = ["rain", "fog", "person", "city", "text", "cgi", "indoor"]

    def vec(self, t):
        t = t.lower(); v = [0.05] * 7
        for i, k in enumerate(self.AX):
            if k in t or (k == "person" and ("face" in t or "crowd" in t or "person" in t)) or (k == "city" and ("city" in t or "skyscraper" in t or "town" in t)) \
               or (k == "cgi" and ("render" in t or "cartoon" in t or "artificial" in t)) or (k == "text" and ("logo" in t or "text" in t)) or (k == "indoor" and ("indoor" in t or "kitchen" in t)):
                v[i] = 1.0
        return v

    def embed_texts(self, ts): return [self.vec(t) for t in ts]
    def embed_images(self, ims): return [self.vec(i) for i in ims]


class Vision(unittest.TestCase):
    unit = {"queries": ["rain"], "prefer": ["rain"]}

    def ann(self):
        return V.Annotator({}, Fake())

    def test_matching_scene_scores_high_and_passes(self):
        r = self.ann().annotate({"key": "a"}, self.unit, lambda: ["rain"])
        self.assertGreater(r["sem"], 0.6); self.assertIsNone(V.verdict(r))

    def test_wrong_content_scores_low(self):
        a = self.ann(); good = a.annotate({"key": "a"}, self.unit, lambda: ["rain"]); bad = a.annotate({"key": "b"}, self.unit, lambda: ["fog"])
        self.assertGreater(good["sem"], bad["sem"] + 0.3)

    def test_vetoed_classes_eliminate(self):
        a = self.ann()
        for img, cls in (("city", "city"), ("person", "people"), ("cgi", "cgi"), ("text", "text"), ("indoor", "indoor")):
            r = a.annotate({"key": img}, self.unit, lambda img=img: [img]); self.assertIn(cls, V.verdict(r) or "", img)
        r = a.annotate({"key": "person"}, self.unit, lambda: ["person"]); self.assertIsNone(V.verdict(r, allow=("people",)))

    def test_embedding_cache_avoids_reprocessing(self):
        cache = {}; a = V.Annotator(cache, Fake()); a.annotate({"key": "k"}, self.unit, lambda: ["rain"])
        a2 = V.Annotator(cache, Fake()); r = a2.annotate({"key": "k"}, self.unit, lambda: (_ for _ in ()).throw(AssertionError("nao deveria reprocessar")))
        self.assertGreater(r["sem"], 0.6)

    def test_positives_use_plan_and_claude_meaning(self):
        self.assertEqual(V.positives({"meaning_en": "a lone traveller in fog", "queries": ["fog", "mist"], "prefer": ["valley"]})[0], "a cinematic video frame of a lone traveller in fog")
        self.assertEqual(V.positives({}), [V.GENERIC_POS])
