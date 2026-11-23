import json, re, subprocess, sys, unittest
from pathlib import Path
R = Path(__file__).resolve().parent.parent
PK = R / "publicacao/pacote_v1.json"; REG = R / "contracts/vnc_publicados_v1.json"; NUM = R / "contracts/vnc_numeracao_v1.json"

class Publisher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run([sys.executable, str(R / "tools/vnc_publisher.py")], check=True, cwd=R, capture_output=True)
        cls.pk = json.loads(PK.read_text(encoding="utf8")); cls.reg = json.loads(REG.read_text(encoding="utf8"))
        cls.num = json.loads(NUM.read_text(encoding="utf8"))

    def test_sem_rede_nem_api_de_publicacao(self):
        src = (R / "tools/vnc_publisher.py").read_text(encoding="utf8")
        for pat in ("requests", "urllib", "socket", "tiktokapis", "googleapis", "graph.facebook", "graph.instagram"):
            self.assertNotIn(pat, src)

    def test_publicados_fora_da_fila(self):
        ids = {x["id"] for x in self.pk["episodios"]}
        for e, st in self.reg["publicados"].items():
            if all(v == "publicado" for k, v in st.items() if k in ("tiktok", "youtube", "instagram")):
                self.assertNotIn(e, ids)

    def test_ninguem_nasce_publicado_nem_aprovado(self):
        for x in self.pk["episodios"]:
            self.assertEqual(x["aprovacao_publicacao"], "PENDENTE_DO_DONO")
            for p in x["plataformas"].values():
                self.assertIn(p["estado"], ("nao_agendado", "agendado", "publicado"))

    def test_legendas_dentro_dos_limites(self):
        for x in self.pk["episodios"]:
            l = x["legendas"]
            self.assertLessEqual(len(l["tiktok"]), 400, x["id"])
            self.assertLessEqual(len(l["youtube_titulo"]), 60, x["id"])
            self.assertLessEqual(len(re.findall(r"#\w+", l["tiktok"])), 5, x["id"])

    def test_ordem_por_quadro_respeita_numeracao_do_dono(self):
        por = {}
        for x in self.pk["episodios"]:
            por.setdefault(x["quadro"], []).append(x["numero"])
        for q, ns in por.items():
            self.assertEqual(ns, sorted(ns), q)

    def test_dois_por_dia_sem_horario_repetido(self):
        hs = [x["sugestao_horario_brt"] for x in self.pk["episodios"]]
        self.assertEqual(len(hs), len(set(hs)))
        dias = [h.split()[0] for h in hs]
        self.assertTrue(all(dias.count(d) <= 2 for d in dias))

if __name__ == "__main__":
    unittest.main()
