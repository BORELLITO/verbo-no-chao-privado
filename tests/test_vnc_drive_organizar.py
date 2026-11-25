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


if __name__ == "__main__":
    unittest.main()
