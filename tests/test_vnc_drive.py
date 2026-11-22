import json, unittest
from pathlib import Path
from agents import vnc_drive as D

def cfg(e): return json.loads(Path(f"episodes/{e}.json").read_text(encoding="utf8"))

class Plan(unittest.TestCase):
    def test_dores_usa_numero_de_capa(self):
        p = D.plan(cfg("E05")); self.assertEqual((p["quadro"], p["folder"]), ("Dores da Vida", "EP 03 – Medo e uma mão firme"))
        p = D.plan(cfg("E03")); self.assertEqual(p["folder"], "EP 04 – Esperança entre ruínas")
        p = D.plan(cfg("E04")); self.assertEqual(p["files"]["video"], "EP 05 - Descanso para quem está cansado.mp4")
    def test_quadro(self):
        p = D.plan(cfg("E07")); self.assertEqual((p["quadro"], p["folder"]), ("Fora do Contexto", "#2 – Planos de paz (Jeremias 29:11)"))
        self.assertEqual(D.plan(cfg("E06"))["folder"], "#1 – O tudo posso (Filipenses 4:10–13)")
    def test_legado_sem_cover_number(self):
        self.assertEqual(D.plan(cfg("E02"))["folder"], "EP 02 – Quando a resposta demora")
    def test_postagem_tem_titulo_em_maiusculas(self):
        t = D.posting_text(cfg("E07"), D.plan(cfg("E07"))); self.assertIn("FORA DO CONTEXTO #2: PLANOS DE PAZ | JEREMIAS 29:11", t); self.assertIn("EP", D.posting_text(cfg("E05"), D.plan(cfg("E05"))))
    def test_env_rclone(self):
        e = D.rclone_env({"GDRIVE_CLIENT_ID": "i", "GDRIVE_CLIENT_SECRET": "s", "GDRIVE_REFRESH_TOKEN": "r"})
        self.assertEqual(e["RCLONE_CONFIG_GD_SCOPE"], "drive.file"); self.assertIn('"refresh_token": "r"', e["RCLONE_CONFIG_GD_TOKEN"])

if __name__ == "__main__":
    unittest.main()
