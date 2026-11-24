import json, unittest
from pathlib import Path
from agents import vnc_drive as D

def cfg(e): return json.loads(Path(f"episodes/{e}.json").read_text(encoding="utf8"))

class Plan(unittest.TestCase):
    def test_dores_usa_numero_de_capa(self):
        p = D.plan(cfg("E05")); self.assertEqual((p["quadro"], p["folder"]), ("QUADRO - DORES DA VIDA", "DORES DA VIDA 3 - MEDO E UMA MÃO FIRME"))
        self.assertEqual(D.plan(cfg("E03"))["folder"], "DORES DA VIDA 4 - ESPERANÇA ENTRE RUÍNAS")
        self.assertEqual(D.plan(cfg("E04"))["files"]["video"], "DORES DA VIDA 5 - DESCANSO PRA QUEM ESTÁ CANSADO.mp4")
    def test_quadro(self):
        p = D.plan(cfg("E07")); self.assertEqual((p["quadro"], p["folder"]), ("QUADRO - FORA DO CONTEXTO", "FORA DO CONTEXTO 2 - PLANO DE PAZ"))
        self.assertEqual(D.plan(cfg("E06"))["folder"], "FORA DO CONTEXTO 1 - TUDO POSSO")
        self.assertEqual(D.plan(cfg("E06"))["files"]["cover"], "FORA DO CONTEXTO 1 - TUDO POSSO - CAPA.jpg")
    def test_dores_1_e_2(self):
        self.assertEqual(D.plan(cfg("E01"))["folder"], "DORES DA VIDA 1 - QUANDO VOCÊ PERGUNTA E NADA MUDA")
        self.assertEqual(D.plan(cfg("E02"))["folder"], "DORES DA VIDA 2 - QUANDO A RESPOSTA DEMORA")
    def test_postagem_tem_titulo_em_maiusculas(self):
        t = D.posting_text(cfg("E07"), D.plan(cfg("E07"))); self.assertIn("ALGUÉM JÁ TE DISSE: CALMA, DEUS TEM UM PLANO PRA VOCÊ? 🙏", t); self.assertIn("Fora do Contexto, episódio 2.", t); self.assertIn("DORES DA VIDA 3", D.posting_text(cfg("E05"), D.plan(cfg("E05"))))
    def test_env_rclone(self):
        e = D.rclone_env({"GDRIVE_CLIENT_ID": "i", "GDRIVE_CLIENT_SECRET": "s", "GDRIVE_REFRESH_TOKEN": "r"})
        self.assertEqual(e["RCLONE_CONFIG_GD_SCOPE"], "drive.file"); self.assertIn('"refresh_token": "r"', e["RCLONE_CONFIG_GD_TOKEN"])

if __name__ == "__main__":
    unittest.main()
