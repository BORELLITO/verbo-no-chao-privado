"""Guarda do repo privado: os workflows legados do E01 (provedores de video/voz, sondas one-shot) foram aposentados e NAO existem aqui.
O conjunto de workflows e fechado: qualquer novo exige revisao (editar a lista abaixo no mesmo commit). Sem agendamento, sem despacho manual
fora dos dois permitidos, segredos so da lista, e nenhum workflow chama provedores de geracao de video."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"
PERMITIDOS = {"vnc-curate.yml", "vnc-drive-backfill.yml", "vnc-drive.yml", "vnc-ingest-voice.yml", "vnc-overlays.yml", "vnc-runflow.yml", "vnc-voice.yml", "vnc-buffer.yml", "vnc-media.yml", "vnc-tests.yml", "vnc-qa-lab.yml"}
DISPATCH_OK = {"vnc-drive-backfill.yml", "vnc-drive.yml"}
SEGREDOS_OK = {"ELEVENLABS_API_KEY", "GDRIVE_CLIENT_ID", "GDRIVE_CLIENT_SECRET", "GDRIVE_REFRESH_TOKEN", "COVERR_API_KEY", "PEXELS_API_KEY", "PIXABAY_API_KEY", "GITHUB_TOKEN", "BUFFER_API_KEY", "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET"}
PROVEDORES_PROIBIDOS = ("gradio_client", "huggingface_hub", "generate_video", "ltx", "zerogpu")


class WorkflowAllowlist(unittest.TestCase):
    def test_conjunto_fechado(self):
        self.assertEqual({p.name for p in WF.glob("*.yml")} - PERMITIDOS, set(), "workflow novo fora da allowlist")
        self.assertFalse(list(WF.glob("verbo-no-chao-e01-*")), "workflow legado do E01 nao pode existir no repo privado")

    def test_sem_agendamento_e_despacho_so_onde_permitido(self):
        for p in WF.glob("*.yml"):
            t = p.read_text(encoding="utf8")
            self.assertNotRegex(t, r"(?m)^\s*(schedule:|- cron:)", p.name)
            if "workflow_dispatch" in t: self.assertIn(p.name, DISPATCH_OK, p.name)

    def test_segredos_e_provedores(self):
        for p in WF.glob("*.yml"):
            t = p.read_text(encoding="utf8")
            self.assertEqual(set(re.findall(r"secrets\.([A-Z0-9_]+)", t)) - SEGREDOS_OK, set(), p.name)
            for x in PROVEDORES_PROIBIDOS: self.assertNotIn(x, t.lower(), f"{p.name}: {x}")

    def test_pushes_em_main_apenas(self):
        for p in WF.glob("*.yml"):
            self.assertNotIn("pull_request_target", p.read_text(encoding="utf8"), p.name)


if __name__ == "__main__":
    unittest.main()
