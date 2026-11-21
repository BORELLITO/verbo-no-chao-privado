import json, os, tempfile, unittest
from pathlib import Path
from unittest import mock
from agents import vnc_pipeline_gate as G, vnc_voice as V

POST = {"hook": "Você já esperou demais?", "resumo": "Resumo curto.", "pergunta": "E você?", "hashtags": ["#fé"], "titulo_curto": "Espera?"}
REP = {"errors": [], "style_lock_errors": [], "final": {"w": 1080, "h": 1920, "seconds": 68.0},
       "align": {"words": 150, "interpolated": 1, "cross_check": {"median_abs_start_diff": 0.02, "n_gt_300ms": 2, "total": 150}}, "music": {"seconds": 120},
       "ending": {"variant": "C", "contract_sha256": None, "layers": [{"id": "18111", "license": "Mixkit Stock Video Free License"}, {"id": "48494", "license": "Mixkit Stock Video Free License"}, {"id": "46316", "license": "Mixkit Stock Video Free License"}],
                  "qa": {"contraste_credito": 9.0, "contraste_cta1": 11.0, "contraste_cta2": 6.0, "ultimo_quadro_max": 0}}}
from agents import vnc_endings as _EN
REP["ending"]["contract_sha256"] = _EN.contract_sha()


def mk(number=3, scenes=None, posting=POST):
    d = Path(tempfile.mkdtemp()); (d / "episodes").mkdir(); (d / "assets/voice").mkdir(parents=True)
    c = {"id": "E0%d" % number, "number": number, "title_lines": ["A", "B"], "reference": "Hab 2:1", "scenes": scenes or [{"text": "Olá mundo."}], "posting": json.loads(json.dumps(posting))}
    (d / "episodes" / f"E0{number}.json").write_text(json.dumps(c)); return d, c


class T(unittest.TestCase):
    def ok_review(self, ep): return {"status": "APROVADO_AUTOMATICO", "issues": []}

    def test_post_ok_and_each_block_blocks(self):
        d, _ = mk(); self.assertEqual(G.post("E03", REP, d), [])
        for mut, key in [({"errors": ["S01"]}, "MONTAGEM"), ({"style_lock_errors": ["x"]}, "ESTILO"),
                         ({"final": {"w": 1920, "h": 1080, "seconds": 68}}, "VIDEO"), ({"final": {"w": 1080, "h": 1920, "seconds": 91}}, "VIDEO"),
                         ({"align": {"words": 150, "cross_check": {"median_abs_start_diff": 0.2, "n_gt_300ms": 0, "total": 150}}}, "LEGENDA"),
                         ({"align": {}}, "LEGENDA"), ({"music": {"seconds": 30}}, "MUSICA")]:
            self.assertTrue(any(key in e for e in G.post("E03", {**REP, **mut}, d)), key)

    def test_ending_family_gate(self):
        d, _ = mk(); import copy
        def rep(**kw):
            r = copy.deepcopy(REP); r["ending"].update(kw); return r
        self.assertTrue(any("FINAL" in e and "rotacao" in e for e in G.post("E03", rep(variant="D"), d)))
        self.assertTrue(any("licenca" in e for e in G.post("E03", rep(layers=[]), d)))
        self.assertTrue(any("contrato" in e for e in G.post("E03", rep(contract_sha256="x"), d)))
        self.assertTrue(any("QA" in e for e in G.post("E03", rep(qa={"contraste_cta1": 2.0, "ultimo_quadro_max": 0}), d)))
        self.assertTrue(any("falha" in e for e in G.post("E03", rep(error="boom"), d)))
        d2, _ = mk(2); r2 = copy.deepcopy(REP); r2["ending"] = {"variant": "A"}
        self.assertEqual(G.post("E02", r2, d2), [])
        r2["ending"] = {"variant": "C"}; self.assertTrue(any("legado" in e for e in G.post("E02", r2, d2)))
        r2["ending"] = {"variant": "C", "forced": True}; self.assertEqual(G.post("E02", r2, d2), [])      # ensaio em episodio legado
        self.assertTrue(any("forcada" in e for e in G.post("E03", rep(forced=True), d)))

    def test_legacy_episode_not_strict_on_duration(self):
        d, _ = mk(2); self.assertEqual(G.post("E02", {**REP, "ending": {"variant": "A"}, "final": {"w": 1080, "h": 1920, "seconds": 91}}, d), [])

    def test_pre_blocks_without_voice_then_checks_sha_and_duration(self):
        d, c = mk(); e = G.pre("E03", d, review=self.ok_review); self.assertTrue(any("VOZ" in x for x in e))
        (d / "assets/voice/E03.mp3").write_bytes(b"abc"); e = G.pre("E03", d, review=self.ok_review, seconds=lambda p: 58.0); self.assertTrue(any("sha256" in x for x in e))
        import hashlib; c["audio_sha256"] = hashlib.sha256(b"abc").hexdigest(); (d / "episodes/E03.json").write_text(json.dumps(c))
        self.assertEqual(G.pre("E03", d, review=self.ok_review, seconds=lambda p: 58.0), [])
        self.assertTrue(any("fora de" in x for x in G.pre("E03", d, review=self.ok_review, seconds=lambda p: 81.0)))

    def test_pre_blocks_reproved_script_and_missing_posting(self):
        d, c = mk(posting=None); (d / "assets/voice/E03.mp3").write_bytes(b"abc")
        bad = lambda ep: {"status": "REPROVADO", "issues": [{"code": "GANCHO", "msg": "fraco"}]}
        e = G.pre("E03", d, review=bad, seconds=lambda p: 58.0); self.assertTrue(any("ROTEIRO" in x for x in e) and any("POSTAGEM" in x for x in e))

    def test_posting_limits_and_render(self):
        d, c = mk(); self.assertIn("TIKTOK", G.render_posting_file("E03", c)); c["posting"]["resumo"] = "x" * 3000
        self.assertTrue(any("tiktok" in x for x in G.bloco_postagem(c)))


class VoiceT(unittest.TestCase):
    def setUp(self): os.environ["ELEVENLABS_API_KEY"] = "k"
    def test_no_key_existing_voice_no_credit_check_and_generate(self):
        d, c = mk(scenes=[{"text": "Olá mundo."}]); api = mock.Mock(return_value=b"MP3DATA")
        del os.environ["ELEVENLABS_API_KEY"]; self.assertEqual(V.run("E03", "check", d, api, lambda k: 9999, lambda p: 1), 4); os.environ["ELEVENLABS_API_KEY"] = "k"
        self.assertEqual(V.run("E03", "check", d, api, lambda k: 5, lambda p: 1), 7)
        self.assertEqual(V.run("E03", "check", d, api, lambda k: 9999, lambda p: 1), 0); self.assertFalse((d / "assets/voice/E03.mp3").exists())
        
        with mock.patch.object(G, "pre_voice", return_value=[]): self.assertEqual(V.run("E03", "generate", d, api, lambda k: 9999, lambda p: 58), 0)
        self.assertEqual((d / "assets/voice/E03.mp3").read_bytes(), b"MP3DATA"); self.assertEqual(len(json.loads((d / "episodes/E03.json").read_text())["audio_sha256"]), 64)
        self.assertEqual(V.run("E03", "generate", d, api, lambda k: 9999, lambda p: 58), 5)   # nunca regenera


if __name__ == "__main__": unittest.main()


class ExtraT(unittest.TestCase):
    def test_youtube_title_60_and_hashtags(self):
        d, c = mk(); c["posting"]["titulo_curto"] = "x" * 70; self.assertTrue(any("youtube_titulo" in e for e in G.bloco_postagem(c)))
        d, c = mk(); c["posting"]["hashtags"] = ["#a"] * 6; self.assertTrue(any("hashtags" in e for e in G.bloco_postagem(c)))

    def test_pre_voice_blocks_without_selection_and_voice_generate_spends_nothing(self):
        d, c = mk(); ok = lambda ep: {"status": "APROVADO_AUTOMATICO", "issues": []}
        e = G.pre_voice("E03", d, review=ok); self.assertTrue(any("CLIPES" in x for x in e))
        os.environ["ELEVENLABS_API_KEY"] = "k"; api = mock.Mock(return_value=b"X")
        with mock.patch.object(G, "pre_voice", return_value=["CLIPES: x"]):
            self.assertEqual(V.run("E03", "generate", d, api, lambda k: 9999, lambda p: 58), 8)
        api.assert_not_called(); self.assertFalse((d / "assets/voice/E03.mp3").exists())
