import copy, json, tempfile, unittest
from pathlib import Path
from agents import vnc_script_review as R

BLK = ["opening", "connection", "connection", "connection", "biblical_reference", "biblical_reference", "biblical_reference", "reflection", "reflection", "application", "application", "conclusion"]
TXT = ["Tudo posso naquele que me fortalece: você sabe onde isso foi escrito?", "Essa frase está em camisetas, quadros e metas de conquista.",
       "Mas a carta aos Filipenses foi escrita por alguém preso.", "A carta, atribuída a Paulo, agradece a ajuda enviada pela igreja.",
       "No capítulo quatro, o autor diz que aprendeu a viver com fartura e com falta.", "E é aí que vem a frase: tudo posso naquele que me fortalece.",
       "Ali, ela fala de situações: ter muito e ter pouco.", "Isso não diminui o versículo. Mostra de onde ele nasceu.", "O próprio texto diz de onde vinha a força: de Cristo.",
       "Da próxima vez, lembre também da cela, e não só do troféu.", "Talvez haja coisas que você não vença esta semana. Às vezes, só dá para aguentar.",
       "Para você, essa frase sempre foi sobre vencer ou sobre aguentar? Responda A ou B."]


def cfg():
    return {"id": "E99", "number": 99, "title_lines": ["Fora do", "contexto:", "tudo posso"], "reference": "Filipenses 4:10–13", "cta": ["x", "y"],
            "anchor_verse": {"ref": "Filipenses 4:13", "texto": "Tudo posso naquele que me fortalece", "traducao": "ARA"},
            "scenes": [{"id": f"S{i+1:02d}", "block": BLK[i], "text": TXT[i], "visual": {"queries": ["fog"], "mood": "dark", "meaning": "paisagem"}} for i in range(12)]}


class Anchor(unittest.TestCase):
    def rv(self, c):
        return R.review("E99", c, others={}, offline=True)

    def codes(self, r):
        return {i["code"] for i in r["issues"]}

    def test_good_script_is_pending_independent_review_not_approved(self):
        r = self.rv(cfg()); self.assertEqual(r["status"], "PENDENTE_REVISAO_INDEPENDENTE", r["issues"]); self.assertEqual(r["checks"]["revisao_independente"], "ausente")

    def test_original_bug_old_script_is_rejected(self):
        c = cfg(); old = ["Você leu o versículo do tudo posso ao contrário?", "Ele aparece em camisas, quadros e metas pessoais.", TXT[2], TXT[3], TXT[4],
                          "Aí vem o tudo posso. O contexto fala de suportar a fome e a falta.", "O tudo dele inclui permanecer de pé, mesmo na falta."]
        for i, t in enumerate(old): c["scenes"][i]["text"] = t
        r = self.rv(c); self.assertEqual(r["status"], "REPROVADO"); cs = self.codes(r)
        self.assertIn("ANCORA", cs); self.assertIn("GANCHO", cs); self.assertIn("REFERENTE", cs)

    def test_fora_do_contexto_without_anchor_is_rejected(self):
        c = cfg(); del c["anchor_verse"]; self.assertIn("ANCORA", self.codes(self.rv(c)))

    def test_anchor_text_must_match_checked_wording(self):
        c = cfg(); c["anchor_verse"]["texto"] = "Posso todas as coisas em Cristo que me fortalece"
        self.assertIn("ANCORA", self.codes(self.rv(c)))   # ARA conferida e outra

    def test_anchor_must_be_quoted_in_first_three_scenes(self):
        c = cfg(); c["scenes"][0]["text"] = "Você sabe onde essa frase famosa foi escrita?"; c["scenes"][5]["text"] = "E é aí que vem a frase: tudo posso naquele que me fortalece."
        r = self.rv(c); self.assertIn("ANCORA", self.codes(r))

    def test_noun_fragment_is_rejected(self):
        c = cfg(); c["scenes"][6]["text"] = "O tudo dele inclui permanecer de pé, mesmo na falta."
        self.assertIn("ANCORA", self.codes(self.rv(c)))

    def test_independent_review_must_match_hash_and_verdict(self):
        c = cfg(); sha = R.sha_roteiro(c)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "episodes").mkdir()
            self.assertEqual(R.revisao_independente("E06", c, root)[0], False)
            f = root / "episodes" / "E06_revisao_independente.json"
            f.write_text(json.dumps({"roteiro_sha": sha, "veredito": "APROVADO", "revisor_independente": "subagente"}))
            self.assertTrue(R.revisao_independente("E06", c, root)[0])
            c2 = copy.deepcopy(c); c2["scenes"][3]["text"] += " Mudou."
            self.assertFalse(R.revisao_independente("E06", c2, root)[0])   # roteiro mudou depois da revisao
            f.write_text(json.dumps({"roteiro_sha": sha, "veredito": "REPROVADO", "revisor_independente": "x"}))
            self.assertFalse(R.revisao_independente("E06", c, root)[0])


if __name__ == "__main__":
    unittest.main()
