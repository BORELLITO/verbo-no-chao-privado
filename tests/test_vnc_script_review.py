import copy, json, unittest
from agents import vnc_script_review as R

BLK = ["opening", "connection", "connection", "connection", "biblical_reference", "biblical_reference", "biblical_reference", "reflection", "reflection", "application", "application", "conclusion"]
TXT = ["Você já esperou tanto por uma resposta que quase parou de perguntar?", "Esperar cansa, e cansa mais quando nada parece se mover no tempo.", "Há dias em que olhamos o horizonte.",
       "E a resposta nem sempre vem no ritmo da nossa pressa.", "No capítulo dois, o profeta decide ficar de vigia depois de clamar contra a injustiça.",
       "Ele diz que vai esperar para ver o que Deus lhe dirá.", "A visão deve ser escrita com clareza; se demorar, deve ser aguardada.",
       "O texto não promete que tudo se resolve depressa; esperar também é confiança.", "A injustiça continua real, e a fé do profeta não depende de ela sumir hoje.",
       "Talvez hoje você precise colocar em palavras o que carrega.", "E seguir fazendo o que é justo, no passo pequeno ao seu alcance.", "Esperar não é desistir; é permanecer de pé com esperança."]


def cfg():
    return {"id": "E09", "title_lines": ["a", "b", "c"], "reference": "Habacuque 2:1–3", "cta": ["x", "y"],
            "scenes": [{"id": f"S{i+1:02d}", "block": BLK[i], "text": TXT[i], "visual": {"queries": ["fog"], "mood": "dark", "meaning": "paisagem"}} for i in range(12)]}


VERSE = "Estarei em pé sobre a minha torre de vigia e esperarei para ver o que Deus me dirá. Escreve a visão com clareza; ela tem um tempo determinado, e se tardar, espera-a."
GET = lambda u: json.dumps({"verses": [{"text": VERSE}]}).encode()


class Review(unittest.TestCase):
    def rv(self, c, **k):
        return R.review("E09", c, getter=GET, others=k.get("others", {}), offline=k.get("offline", False))

    def codes(self, r):
        return {i["code"] for i in r["issues"]}

    def test_good_script_passes_and_verifies_bible(self):
        r = self.rv(cfg()); self.assertEqual(r["status"], "APROVADO_AUTOMATICO", r["issues"]); self.assertTrue(r["checks"]["texto_biblico_verificado"])

    def test_miracle_and_prosperity_fail(self):
        c = cfg(); c["scenes"][8]["text"] = "Deus vai resolver tudo e você vai receber prosperidade, é garantido!"
        r = self.rv(c); self.assertEqual(r["status"], "REPROVADO"); self.assertIn("TOM", self.codes(r))

    def test_wrong_structure(self):
        c = cfg(); c["scenes"].pop(); self.assertIn("ESTRUTURA", self.codes(self.rv(c)))

    def test_invalid_reference(self):
        c = cfg(); c["reference"] = "Habacuque 9:1"; self.assertIn("BIBLIA", self.codes(self.rv(c)))
        c["reference"] = "Livro 0:0–0"; self.assertIn("BIBLIA", self.codes(self.rv(c)))

    def test_unrelated_biblical_scenes_fail_lexical_link(self):
        c = cfg()
        for i in (4, 5, 6): c["scenes"][i]["text"] = "No capítulo dois, o texto fala de pássaros cantando bonito perto das flores azuis amarelas."
        c["scenes"][4]["text"] += " Injustiça."
        self.assertIn("BIBLIA", self.codes(self.rv(c)))

    def test_bible_source_down_is_not_verified_not_invented(self):
        r = R.review("E09", cfg(), getter=lambda u: (_ for _ in ()).throw(OSError()), others={})
        self.assertFalse(r["checks"]["texto_biblico_verificado"]); self.assertIn("NAO VERIFICADO", r["checks"]["nota_biblia"])

    def test_fallback_to_acf_json_when_api_down(self):
        data = [{"chapters": []} for _ in range(66)]; data[list(R.BOOKS).index("habacuque")] = {"chapters": [["x"], [VERSE, "b", "c"]]}
        def g(u):
            if "bible-api" in u: raise OSError("down")
            return json.dumps(data).encode()
        r = R.review("E09", cfg(), getter=g, others={}); self.assertTrue(r["checks"]["texto_biblico_verificado"])

    def test_repetition_between_episodes(self):
        o = copy.deepcopy(cfg()); o["id"] = "E01"
        r = self.rv(cfg(), others={"E01": o}); self.assertIn("REPETICAO", self.codes(r))

    def test_missing_visual_plan_and_placeholder(self):
        c = cfg(); c["scenes"][2]["visual"] = {}; c["scenes"][3]["text"] = "..."
        r = self.rv(c); self.assertIn("TEXTO", self.codes(r)); self.assertTrue(any(a["code"] == "VISUAL" for a in r["avisos"]))

    def test_duration_rule_65_70s(self):
        c = cfg(); c["scenes"][8]["text"] += " " + " ".join(["palavra"] * 60)
        self.assertIn("DURACAO", self.codes(self.rv(c)))

    def test_hook_rules(self):
        for t in ("No capítulo dois de Habacuque, o profeta decide ficar de vigia depois de clamar por justiça?", "Esperar cansa muita gente e todo mundo sabe disso hoje em dia, não é mesmo, pessoal?", "O profeta esperou."):
            c = cfg(); c["scenes"][0]["text"] = t; self.assertIn("GANCHO", self.codes(self.rv(c)), t)

    def test_legacy_e01_only_warns(self):
        c = cfg(); c["number"] = 2; c["scenes"][0]["text"] = "Em Habacuque, o profeta decide ficar de vigia?"
        r = self.rv(c); self.assertNotIn("GANCHO", self.codes(r)); self.assertTrue(any(a["code"] == "GANCHO" for a in r["avisos"]))

    def test_tone_exclamation_and_no_hook(self):
        c = cfg(); c["scenes"][0]["text"] = "Pare de esperar!"
        self.assertTrue({"GANCHO", "TOM"} <= self.codes(self.rv(c)))

    def test_real_e02_is_reviewable_offline(self):
        r = R.review("E02", offline=True); self.assertIn(r["status"], ("APROVADO_AUTOMATICO", "REPROVADO"))


if __name__ == "__main__":
    unittest.main()


class HookVariationT(unittest.TestCase):
    def test_hook_opening_must_differ_from_previous_episodes(self):
        import copy
        c = copy.deepcopy(cfg()); c["number"] = 3; c["id"] = "E03"
        o = copy.deepcopy(cfg()); o["id"] = "E02"; o["number"] = 2; o["reference"] = "Salmos 13:1-3"
        r = R.review("E03", cfg=c, others={"E02": o}, offline=True)
        self.assertTrue(any(i["code"] == "GANCHO" and "abre igual" in i["msg"] for i in r["issues"]))
        o["scenes"][0]["text"] = "Nem toda espera significa abandono, voce sabia?"
        r = R.review("E03", cfg=c, others={"E02": o}, offline=True)
        self.assertFalse(any("abre igual" in i["msg"] for i in r["issues"]))
