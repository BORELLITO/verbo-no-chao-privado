import hashlib, json, tempfile, unittest
from pathlib import Path
from agents import vnc_media as M

ROOT = Path(__file__).resolve().parents[1]


class Media(unittest.TestCase):
    def test_assinatura_cloudinary(self):
        # formato oficial: parametros ordenados, k=v unidos por &, segredo anexado, sha1
        esperado = hashlib.sha1(b"public_id=vnc/x&timestamp=123SEGREDO").hexdigest()
        self.assertEqual(M.assinar({"timestamp": 123, "public_id": "vnc/x", "api_key": None}, "SEGREDO"), esperado)

    def test_public_id_estavel_e_sem_id_interno_ruim(self):
        a = M.public_id("E03", "ab" * 32)
        self.assertEqual(a, M.public_id("E03", "ab" * 32))
        self.assertEqual(a, "vnc/dores4-abababababab"[:len("vnc/dores4-") + 10])
        self.assertNotIn("E03", a)

    def test_capa_public_id_e_url(self):
        self.assertEqual(M.public_id_capa("E03", "ab" * 32), "vnc/dores4-capa-abababababab"[:len("vnc/dores4-capa-") + 10])
        self.assertEqual(M.url_capa("c", "vnc/x"), "https://res.cloudinary.com/c/image/upload/vnc/x.jpg")

    def test_localizar_capa_pasta_do_quadro(self):
        e, nome = M.episodio("E03")
        with tempfile.TemporaryDirectory() as t:
            d = Path(t) / nome / f"EPISÓDIO {e['numero']} - {e['titulo']}"
            d.mkdir(parents=True)
            f = d / f"EPISÓDIO {e['numero']} - {e['titulo']} - CAPA.jpg"
            f.write_bytes(b"x")
            self.assertEqual(M.localizar_capa("E03", t), f)
            with self.assertRaises(M.MediaError):
                M.localizar_capa("E04", t)

    def test_url_publica(self):
        self.assertEqual(M.url_publica("c", "vnc/x"), "https://res.cloudinary.com/c/video/upload/vnc/x.mp4")

    def test_localizar_usa_pasta_do_quadro(self):
        e, nome = M.episodio("E03")
        with tempfile.TemporaryDirectory() as t:
            d = Path(t) / nome / f"EPISÓDIO {e['numero']} - {e['titulo']}"
            d.mkdir(parents=True)
            f = d / f"EPISÓDIO {e['numero']} - {e['titulo']}.mp4"
            f.write_bytes(b"x")
            self.assertEqual(M.localizar("E03", t), f)
            with self.assertRaises(M.MediaError):
                M.localizar("E04", t)

    def test_fila_inteira_cabe_no_limite_do_plano(self):
        self.assertLess(60 * 1024 * 1024, M.LIMITE_BYTES)  # maior mp4 medido ~57 MB

    def test_workflow_so_com_segredos_cloudinary_e_sem_rede_social(self):
        t = (ROOT / ".github/workflows/vnc-media.yml").read_text(encoding="utf8")
        self.assertNotRegex(t, r"(?m)^\s*(schedule:|- cron:|workflow_dispatch)")
        self.assertNotIn("BUFFER_API_KEY", t)
        self.assertNotIn("api.buffer.com", (ROOT / "agents/vnc_media.py").read_text(encoding="utf8"))


if __name__ == "__main__":
    unittest.main()


def test_todo_episodio_hospedado_tem_capa_hospedada():
    m = json.loads((ROOT / "publicacao/midia_v1.json").read_text(encoding="utf8"))
    assert set(m["public_ids"]) <= set(m["capas"])
