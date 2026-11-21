import copy, json, tempfile, unittest
from pathlib import Path
from agents import vnc_theology_gate as TH

F = lambda u, t="comentario": {"titulo": "t", "url": u, "tipo": t, "nota": "n"}
VERSES = {"Lamentações 3:22-23": "As misericórdias do Senhor são a causa de não sermos consumidos; novas são cada manhã"}


def base():
    cfg = {"id": "E03", "number": 3, "reference": "Lam 3:22-23", "scenes": [
        {"id": "S01", "block": "opening", "text": "Onde está a esperança?"},
        {"id": "S02", "block": "biblical_reference", "text": "As misericórdias se renovam a cada manhã."}]}
    d = {"episode": "E03", "referencia": "Lam 3:22-23", "parecer": "APROVADO",
         "alegacoes": [{"id": "A1", "cenas": ["S02"], "tipo": "textual", "versiculos": ["Lamentações 3:22-23"], "palavras_chave_no_texto": ["misericórdias", "manhã"], "veredito": "SUPORTADO",
                        "fontes": [F("https://a.org/x")], "risco": "baixo"},
                       {"id": "A2", "cenas": ["S01"], "tipo": "aplicacao", "versiculos": [], "veredito": "SUPORTADO", "fontes": [F("https://b.org/x")], "risco": "baixo"}],
         "omissoes_de_contexto": [{"item": "juizo", "decisao": "aceitavel", "justificativa": "recorte declarado na referencia do episodio"}]}
    return cfg, d


def mk(cfg, d, seal=True):
    r = Path(tempfile.mkdtemp()); (r / "episodes").mkdir()
    if seal: d["cenas_hash"] = TH.scene_hashes(cfg)
    (r / "episodes/E03.json").write_text(json.dumps(cfg)); (r / "episodes/E03_teologia.json").write_text(json.dumps(d)); return r


class T(unittest.TestCase):
    def run_(self, cfg, d, **k):
        return TH.check_theology("E03", mk(cfg, d, **k), verses=lambda v: VERSES.get(v))

    def test_ok(self):
        cfg, d = base(); self.assertEqual(self.run_(cfg, d)[0], "APROVADO_TEOLOGICO")

    def test_missing_dossier(self):
        cfg, d = base(); r = mk(cfg, d); (r / "episodes/E03_teologia.json").unlink()
        self.assertEqual(TH.check_theology("E03", r)[0], "PENDENTE_PESQUISA")

    def test_stale_hash_after_script_edit(self):
        cfg, d = base(); r = mk(cfg, d); cfg["scenes"][1]["text"] = "Texto novo."; (r / "episodes/E03.json").write_text(json.dumps(cfg))
        st, errs, _ = TH.check_theology("E03", r, verses=lambda v: VERSES.get(v)); self.assertEqual(st, "REPROVADO"); self.assertTrue(any("hash" in e for e in errs))

    def test_unsupported_claim_and_missing_keyword_and_unverified_text(self):
        cfg, d = base(); d["alegacoes"][0]["veredito"] = "NAO_SUPORTADO"; self.assertEqual(self.run_(cfg, d)[0], "REPROVADO")
        cfg, d = base(); d["alegacoes"][0]["palavras_chave_no_texto"] = ["prosperidade"]; self.assertTrue(any("palavras-chave" in e for e in self.run_(cfg, d)[1]))
        cfg, d = base(); r = mk(cfg, d); st, errs, _ = TH.check_theology("E03", r, verses=lambda v: None); self.assertTrue(any("NAO VERIFICADO" in e for e in errs))

    def test_historical_needs_two_domains_and_scholarly_source(self):
        cfg, d = base(); cfg["scenes"][0]["text"] = "Jerusalém caiu em 586."
        d["alegacoes"].append({"id": "A3", "cenas": ["S01"], "tipo": "historica", "veredito": "SUPORTADO", "fontes": [F("https://a.org/1"), F("https://a.org/2")], "risco": "baixo"})
        errs = self.run_(cfg, d)[1]; self.assertTrue(any("dominios distintos" in e for e in errs))

    def test_date_without_historical_claim_and_author_without_hedge(self):
        cfg, d = base(); cfg["scenes"][0]["text"] = "Em 586 Jeremias escreveu isto."; errs = self.run_(cfg, d)[1]
        self.assertTrue(any("data/periodo" in e for e in errs) and any("autor" in e for e in errs))

    def test_cautela_requires_mitigation_and_omissions_and_parecer(self):
        cfg, d = base(); d["alegacoes"][0]["veredito"] = "SUPORTADO_COM_CAUTELA"; self.assertTrue(any("mitigacao" in e for e in self.run_(cfg, d)[1]))
        cfg, d = base(); d["omissoes_de_contexto"] = []; self.assertEqual(self.run_(cfg, d)[0], "REPROVADO")
        cfg, d = base(); d["parecer"] = "PENDENTE"; self.assertEqual(self.run_(cfg, d)[0], "REPROVADO")

    def test_uncovered_content_scene(self):
        cfg, d = base(); d["alegacoes"] = d["alegacoes"][1:]; self.assertTrue(any("sem alegacao" in e for e in self.run_(cfg, d)[1]))

    def test_legacy_not_strict(self):
        self.assertFalse(TH.strict("E02")); self.assertTrue(TH.strict("E03"))

    def test_aesthetic_bound_to_video_sha(self):
        cfg, d = base(); r = mk(cfg, d)
        crit = {"coerencia_texto_imagem": True, "luz_no_arco": True, "legenda_legivel": True, "sem_pessoas_ou_marcas": True}
        a = {"video_sha256": "abc", "cenas": [{"cena": s["id"], "veredito": "APROVADO", "criterios": crit, "nota": "ok"} for s in cfg["scenes"]],
             **{k: {"veredito": "APROVADO"} for k in ("final", "capa", "ritmo_e_transicoes", "audio_voz_e_trilha")}}
        (r / "episodes/E03_estetica.json").write_text(json.dumps(a))
        self.assertEqual(TH.check_aesthetic("E03", "abc", r)[0], "APROVADO_ESTETICO")
        self.assertEqual(TH.check_aesthetic("E03", "zzz", r)[0], "REPROVADO")
        a["cenas"][0]["criterios"]["luz_no_arco"] = False; (r / "episodes/E03_estetica.json").write_text(json.dumps(a))
        self.assertEqual(TH.check_aesthetic("E03", "abc", r)[0], "REPROVADO")


if __name__ == "__main__":
    unittest.main()
