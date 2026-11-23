import json, shutil, tempfile, unittest
from pathlib import Path
from agents import vnc_naming as N

class Numeracao(unittest.TestCase):
    def test_registro_confere_com_episodios(self):
        self.assertEqual(N.check(), [])
    def test_quadros_numerados_do_1_ao_n(self):
        for q in ("DORES", "FORA"):
            nums = sorted(e["numero"] for e in N.load()["episodios"] if e["quadro"] == q)
            self.assertEqual(nums, list(range(1, len(nums) + 1)))
            self.assertEqual(N.next_number(q), len(nums) + 1)
    def test_nomes_oficiais(self):
        self.assertEqual(N.label("E05"), "DORES DA VIDA 3 — MEDO E UMA MÃO FIRME")
        self.assertEqual(N.label("E07"), "FORA DO CONTEXTO 2 — PLANO DE PAZ")
        self.assertEqual(N.files("E04")["cover"], "DORES DA VIDA 5 - DESCANSO PRA QUEM ESTÁ CANSADO - CAPA.jpg")
    def test_episodio_fora_do_registro_trava(self):
        self.assertTrue(N.check_episode("E99"))
    def _clone(self):
        d = Path(tempfile.mkdtemp()); (d / "contracts").mkdir(); (d / "episodes").mkdir()
        shutil.copy(N.REG, d / "contracts" / "vnc_numeracao_v1.json")
        for p in (N.ROOT / "episodes").glob("E0[1-7].json"): shutil.copy(p, d / "episodes" / p.name)
        return d
    def test_detecta_numero_repetido_ou_buraco(self):
        d = self._clone(); r = json.loads((d / "contracts" / "vnc_numeracao_v1.json").read_text(encoding="utf8"))
        for e in r["episodios"]:
            if e["id"] == "E07": e["numero"] = 4
        (d / "contracts" / "vnc_numeracao_v1.json").write_text(json.dumps(r, ensure_ascii=False), encoding="utf8")
        self.assertTrue(any("numeracao" in x for x in N.check(d)))
    def test_detecta_capa_com_numero_errado(self):
        d = self._clone(); p = d / "episodes" / "E03.json"; c = json.loads(p.read_text(encoding="utf8")); c["cover_number"] = 9
        p.write_text(json.dumps(c, ensure_ascii=False), encoding="utf8")
        self.assertTrue(any("numero na capa" in x for x in N.check(d)))
    def test_doc_em_dia(self):
        self.assertEqual((N.ROOT / "EPISODIOS.md").read_text(encoding="utf8"), N.doc())

if __name__ == "__main__":
    unittest.main()


def test_karaoke_por_quadro():
    reg = N.load()
    assert reg["quadros"]["FORA"]["karaoke"] == "laranja" and reg["quadros"]["DORES"]["karaoke"] == "lilas"
    assert N.check() == []


class Padrao(unittest.TestCase):
    def test_kicker_igual_nos_dois_quadros_sem_zero(self):
        self.assertEqual(N.kicker("E03"), "DORES DA VIDA · EPISÓDIO 4")
        self.assertEqual(N.kicker("E08"), "FORA DO CONTEXTO · EPISÓDIO 3")

    def test_horario_fixo_por_quadro(self):
        self.assertEqual((N.horario("DORES"), N.horario("FORA")), ("12:00", "19:00"))

    def test_pacote_e_calendario_respeitam_o_padrao(self):
        self.assertEqual(N.check_publicacao(), [])

    def test_repositorio_inteiro_no_padrao(self):
        self.assertEqual(N.check(), [])

    def test_titulo_curto_proibido_e_titulo_da_capa_igual_ao_oficial(self):
        import json, tempfile, shutil
        from pathlib import Path
        with tempfile.TemporaryDirectory() as t:
            r = Path(t); shutil.copytree(N.ROOT / "contracts", r / "contracts"); shutil.copytree(N.ROOT / "episodes", r / "episodes")
            p = r / "episodes" / "E08.json"; c = json.loads(p.read_text(encoding="utf8"))
            c["posting"]["titulo_curto"] = "x"; c["cover_quadro"]["big"] = ["NÃO", "JULGAR"]
            p.write_text(json.dumps(c, ensure_ascii=False), encoding="utf8")
            errs = N.check_episode("E08", r)
            self.assertTrue(any("titulo_curto" in e for e in errs)); self.assertTrue(any("titulo grande da capa" in e for e in errs))
