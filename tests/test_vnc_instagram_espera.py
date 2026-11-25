import unittest
from datetime import datetime, timezone, timedelta
from agents import vnc_instagram as I

AGORA = datetime(2026, 11, 25, 14, 0, tzinfo=timezone.utc)


class Espera(unittest.TestCase):
    def test_sem_horario_publica_agora(self):
        self.assertEqual(I.espera_s({}, AGORA), 0)

    def test_espera_ate_antes_do_alvo(self):
        cfg = {"publicar_em": "2026-11-25T15:00:00Z"}
        self.assertEqual(I.espera_s(cfg, AGORA), 3600 - I.ANTECEDENCIA_S)

    def test_alvo_muito_proximo_ou_levemente_atrasado_publica_ja(self):
        self.assertEqual(I.espera_s({"publicar_em": "2026-11-25T14:01:00Z"}, AGORA), 0)
        self.assertEqual(I.espera_s({"publicar_em": "2026-11-25T13:55:00Z"}, AGORA), 0)

    def test_recusa_passado_distante_futuro_distante_e_formato_ruim(self):
        with self.assertRaises(I.IGError): I.espera_s({"publicar_em": "2026-11-25T12:00:00Z"}, AGORA)
        with self.assertRaises(I.IGError): I.espera_s({"publicar_em": "2026-11-26T14:00:00Z"}, AGORA)
        with self.assertRaises(I.IGError): I.espera_s({"publicar_em": "amanha"}, AGORA)
        with self.assertRaises(I.IGError): I.espera_s({"publicar_em": "2026-11-25T15:00:00"}, AGORA)

    def test_limite_maximo(self):
        ok = (AGORA + timedelta(seconds=I.MAX_ESPERA_S + I.ANTECEDENCIA_S)).isoformat()
        self.assertEqual(I.espera_s({"publicar_em": ok}, AGORA), I.MAX_ESPERA_S)


if __name__ == "__main__":
    unittest.main()
