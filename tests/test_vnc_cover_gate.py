import json, tempfile, unittest
from pathlib import Path
import numpy as np
from PIL import Image
from agents import vnc_cover_gate as G

CFG = {"id": "E03", "number": 3}
M = {"y_top": 880, "y_bottom": 1500, "widths": [700, 650, 500, 400, 600], "kicker": "EPISÓDIO 03", "lines": 3, "band_lum": 0.10, "cover_ids": ["a", "b"]}


def cover(seed=1, top=60, bot=180):
    g = np.random.default_rng(seed); a = np.zeros((1920, 1080, 3)); a[:960] = top; a[960:] = bot
    a += g.normal(0, 25, a.shape); return Image.fromarray(a.clip(0, 255).astype("uint8"))


class T(unittest.TestCase):
    def test_ok_and_each_failure(self):
        im = cover(); self.assertEqual(G.check(CFG, im, M, reg={"covers": {}}), [])
        bad = lambda **k: G.check(CFG, im, {**M, **k}, reg={"covers": {}})
        self.assertTrue(any("area segura" in e for e in bad(y_bottom=1700)))
        self.assertTrue(any("larga" in e for e in bad(widths=[1000])))
        self.assertTrue(any("kicker" in e for e in bad(kicker="EPISÓDIO 02")))
        self.assertTrue(any("linhas" in e for e in bad(lines=2)))
        self.assertTrue(any("contraste" in e for e in bad(band_lum=0.7)))
        self.assertTrue(any("diferentes" in e for e in bad(cover_ids=["a", "a"])))
        self.assertTrue(any("formato" in e for e in G.check(CFG, Image.new("RGB", (100, 100)), M, reg={"covers": {}})))
        self.assertTrue(any("tristeza" in e for e in G.check(CFG, cover(top=200, bot=60), M, reg={"covers": {}})))
        self.assertTrue(any("nitidez" in e for e in G.check(CFG, Image.fromarray(np.full((1920, 1080, 3), 100, "uint8")), M, reg={"covers": {}})))

    def test_non_repetition_hash_and_ids(self):
        d = Path(tempfile.mkdtemp()); p = d / "c.jpg"; cover(1).save(p); G.register("E02", p, ["x", "y"], d / "r.json"); reg = G.load_registry(d / "r.json")
        self.assertTrue(any("parecida" in e for e in G.check(CFG, Image.open(p), M, reg=reg)))
        self.assertTrue(any("ja usado" in e for e in G.check(CFG, cover(9, 90, 150), {**M, "cover_ids": ["x", "z"]}, reg=reg)))
        self.assertEqual([e for e in G.check(CFG, cover(5, 40, 220), M, reg=reg) if "parecida" in e], [])   # outra imagem passa

    def test_real_e02_cover_passes_calibration(self):
        p = Path("/tmp/e02out/capa_vertical.jpg")
        if not p.exists(): self.skipTest("capa E02 nao disponivel")
        self.assertEqual(G.check({"id": "E02", "number": 2}, Image.open(p), {**M, "kicker": "EPISÓDIO 02", "band_lum": 0.16}, strict=False), [])


if __name__ == "__main__": unittest.main()
