import unittest
from agents import vnc_drive_organizar as O


class DriveOrganizar(unittest.TestCase):
    def test_plano_separa_quadros_e_destinos(self):
        m = O.plano({"estoque": ["E03", "E07"], "postados": ["E01", "E06"]})
        por = {x["ep"]: x for x in m}
        self.assertEqual(por["E03"]["para"], "VERBO NO CHÃO/ESTOQUE/QUADRO - DORES DA VIDA/DORES DA VIDA 4 - ESPERANÇA ENTRE RUÍNAS")
        self.assertEqual(por["E07"]["para"], "VERBO NO CHÃO/ESTOQUE/QUADRO - FORA DO CONTEXTO/FORA DO CONTEXTO 2 - PLANO DE PAZ")
        self.assertTrue(por["E01"]["de"].startswith("VERBO NO CHÃO/QUADRO - DORES DA VIDA/DORES DA VIDA 1"))
        self.assertEqual(por["E06"]["destino"], "POSTADOS")

    def test_rejeita_duplicado_vazio_e_desconhecido(self):
        with self.assertRaises(O.DriveOrgError): O.plano({"estoque": ["E03"], "postados": ["E03"]})
        with self.assertRaises(O.DriveOrgError): O.plano({})
        with self.assertRaises(O.DriveOrgError): O.plano({"estoque": ["E99"]})

    def test_organizar_exige_liberacao(self):
        with self.assertRaises(O.DriveOrgError): O.organizar({}, {}, [])


    def test_origem_prefere_estoque_e_cai_no_legado(self):
        chamadas = []
        orig_ex, orig_rc = O._existe, O.D.rc
        try:
            m = O.plano({"postados": ["E03"]})
            O.D.rc = lambda a, e: chamadas.append(a) or ""
            O._existe = lambda path, env: path == m[0]["de_estoque"]
            r = O.organizar({"liberado_pelo_dono": True}, {}, m)
            self.assertEqual(r[0]["resultado"], "movido")
            self.assertIn(["moveto", "gd:" + m[0]["de_estoque"], "gd:" + m[0]["para"]], chamadas)
            chamadas.clear(); O._existe = lambda path, env: path == m[0]["de"]
            O.organizar({"liberado_pelo_dono": True}, {}, m)
            self.assertIn(["moveto", "gd:" + m[0]["de"], "gd:" + m[0]["para"]], chamadas)
        finally:
            O._existe, O.D.rc = orig_ex, orig_rc

if __name__ == "__main__":
    unittest.main()
