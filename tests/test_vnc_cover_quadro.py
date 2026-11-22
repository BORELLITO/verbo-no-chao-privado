import unittest
import numpy as np
from PIL import Image
from agents import vnc_cover_quadro as Q


def _bg(v=120):
    r = np.random.default_rng(1); a = (r.normal(v, 18, (540, 960, 1)) * np.ones((1, 1, 3))).clip(0, 255).astype("uint8")
    return Image.fromarray(a)


class CapaQuadro(unittest.TestCase):
    def test_gera_1080x1920_e_passa(self):
        img, met = Q.build(_bg(), Q.load_logo(380), "FORA DO CONTEXTO · EPISÓDIO 1", ["TUDO", "POSSO"], "...e o que vem antes?", "Filipenses 4:10-13")
        self.assertEqual(img.size, (1080, 1920)); self.assertEqual(Q.check(img, met), [])

    def test_fundo_liso_reprova_por_nitidez(self):
        img, met = Q.build(Image.new("RGB", (960, 540), (120, 120, 120)), Q.load_logo(380), "K", ["TUDO", "POSSO"], "t", "r")
        met["frame_sharp"] = 0.1
        self.assertTrue(any("nitidez" in e for e in Q.check(img, met)))

    def test_texto_fora_da_area_segura(self):
        img, met = Q.build(_bg(), Q.load_logo(380), "K", ["TUDO", "POSSO"], "t", "r"); met["y_bottom"] = 1700
        self.assertTrue(any("area segura" in e for e in Q.check(img, met)))


if __name__ == "__main__":
    unittest.main()


class CoverNumber(unittest.TestCase):
    def test_kicker_usa_cover_number_sem_mudar_number(self):
        from agents import vnc_cover_gate as CG
        cfg = {"id": "E05", "number": 5, "cover_number": 3}
        m = {"y_top": 880, "y_bottom": 1437, "widths": [500], "kicker": "EPISÓDIO 03", "lines": 3, "band_lum": 0.05, "cover_ids": ["1", "2"]}
        img = Image.new("RGB", (1080, 1920), (20, 20, 20))
        errs = CG.check(cfg, img, m, reg={"covers": {}}, strict=False)
        self.assertFalse([e for e in errs if "kicker" in e])
        m["kicker"] = "EPISÓDIO 05"
        self.assertTrue([e for e in errs + CG.check(cfg, img, m, reg={"covers": {}}, strict=False) if "kicker" in e])


def test_titulo_grande_encolhe_so_quando_precisa():
    from agents import vnc_cover_quadro as Q
    assert Q._fit_big(["PLANOS", "DE PAZ"]).size == 205
    assert Q._fit_big(["NÃO", "JULGUEIS"]).size < 205
