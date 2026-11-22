import unittest
from agents import vnc_style as ST


class QuadroColor(unittest.TestCase):
    def test_sem_cor_nao_muda(self):
        at = "Dialogue: 0,0:00:01.00,0:00:02.00,Caption,,0,0,0,,{\\1c&H00F2B0C4&}oi"
        self.assertEqual(ST.apply_quadro_color(at, None), at)

    def test_troca_so_destaque_das_legendas(self):
        at = "Style: CTA2,x,50,&H00F2B0C4,&H00F2B0C4\nDialogue: 0,0,1,Caption,,0,0,0,,{\\1c&H00F2B0C4&}oi"
        out = ST.apply_quadro_color(at, "&H0066B3FF")
        self.assertIn("{\\1c&H0066B3FF&}oi", out)
        self.assertIn("Style: CTA2,x,50,&H00F2B0C4,&H00F2B0C4", out)

    def test_cor_invalida(self):
        for c in ("laranja", "&H00F2B0C4", "#FFB366"):
            with self.assertRaises(ValueError): ST.apply_quadro_color("x", c)


if __name__ == "__main__":
    unittest.main()
