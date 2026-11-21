import json, unittest
from pathlib import Path
from agents import vnc_style as ST
from agents import vnc_align as A

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "episodes/E01.json").read_text(encoding="utf8"))
ADUR, T = 76.67, 76.67 + 9.5


def e01_ass():
    from agents.e01_v3_voice_captions import build
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        build(Path(d)); return (Path(d) / "e01-v3-johnes-karaoke-qa.ass").read_text(encoding="utf8")


class StyleLock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = e01_ass(); cls.fin = ST.finalize_ass(cls.raw, ADUR, T, CFG["reference"], CFG["cta"], 0.07, True)

    def test_constants_match_lock(self):
        self.assertEqual(ST.check_constants(), [])

    def test_e01_final_ass_passes(self):
        self.assertEqual(ST.check_final_ass(self.fin, ADUR, T), [])

    def test_other_duration_and_texts_pass(self):  # episodio novo: outra duracao e outros textos, mesmo padrao
        raw = self.raw
        fin = ST.finalize_ass(raw, 61.2, 61.2 + 9.5, "Salmo 23:1–4", ["Curta e inscreva-se", "E você?\\NComente."], 0.0, True)
        self.assertEqual([e for e in ST.check_final_ass(fin, 61.2, 70.7) if "depois do fim" not in e], [])

    def test_filter_chain_independent_of_duration_but_locked(self):
        def chk(f, ad, t, t0, ass): return ST.check_filter(f, ass, ad, t, t0)
        a = ST.final_filter(76.67, T, 77.17, "/x/a.ass"); b = ST.final_filter(55.0, 64.5, 55.5, "/y/b.ass")
        self.assertEqual(chk(a, 76.67, T, 77.17, "/x/a.ass"), []); self.assertEqual(chk(b, 55.0, 64.5, 55.5, "/y/b.ass"), [])
        self.assertTrue(chk(a.replace("loudnorm=I=-16", "loudnorm=I=-14"), 76.67, T, 77.17, "/x/a.ass"))
        self.assertTrue(chk(a.replace("overlay=eof_action=pass:format=gbrp[ov]", "overlay=eof_action=pass[ov]"), 76.67, T, 77.17, "/x/a.ass"))
        self.assertTrue(chk(a.replace("ratio=6", "ratio=2"), 76.67, T, 77.17, "/x/a.ass"))

    def test_violations_are_caught(self):
        for old, new in ((",2,180,180,576,1", ",2,180,180,500,1"), ("&H00F2B0C4", "&H00FFFFFF"), ("Atkinson Hyperlegible Next,107", "Arial,107"),
                         ("{\\fad(800,900)}", "{\\fad(100,100)}")):
            self.assertTrue(ST.check_final_ass(self.fin.replace(old, new), ADUR, T), old)
        self.assertTrue(ST.check_final_ass(ST.finalize_ass(self.raw, ADUR, T, "x", ["a", "b"], 0.07, False), ADUR, T))  # QA presente

    def test_whisper_generated_captions_follow_same_style(self):
        from agents.e01_v2_caption_pipeline import make_cues, export_ass
        refit = json.loads((ROOT / "contracts/e01_v3_12_scene_refit_v1.json").read_text(encoding="utf8"))["scenes"]
        tw = json.loads((ROOT / "contracts/e01_v3_voice_johnes_word_timing_v1.json").read_text(encoding="utf8"))["words"]
        canon, _ = A.words_from_scenes([{"id": s["id"][-3:], "text": s["text"]} for s in refit])
        canon = [dict(c, block=w["block"]) for c, w in zip(canon, tw)]
        words, _ = A.align(canon, [{"text": w["text"], "start": w["start"], "end": w["end"]} for w in tw], ADUR)
        fin = ST.finalize_ass(export_ass(make_cues(words, ADUR), ADUR), ADUR, T, "Ref 1:1", ["a", "b"], 0.0, True)
        self.assertEqual(ST.check_final_ass(fin, ADUR, T), [])


if __name__ == "__main__":
    unittest.main()


class LogoLock(unittest.TestCase):
    def test_logo_signature_detects_shift_and_resize(self):
        import shutil, tempfile
        from PIL import Image
        src = Path("/tmp/lg_after")
        if not src.exists():
            try:
                import agents.vnc_master_build as m
            except ImportError:
                self.skipTest("renderizacao da logo so no runner de build (o proprio build confere a assinatura)")
            m.make_logo_layers(76.67, 86.17, 77.17, src)
        self.assertEqual(ST.check_logo(src, 76.67, 86.17), [])
        with tempfile.TemporaryDirectory() as d:
            shutil.copytree(src, Path(d) / "x")
            im = Image.open(Path(d) / "x/static.png"); sh = Image.new("RGBA", im.size, (0, 0, 0, 0)); sh.alpha_composite(im, (0, 12)); sh.save(Path(d) / "x/static.png")
            self.assertTrue(ST.check_logo(Path(d) / "x", 76.67, 86.17))
