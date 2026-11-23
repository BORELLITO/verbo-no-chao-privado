import io, json, unittest, urllib.error
from agents import vnc_buffer as B, vnc_gates as G

class FakeResp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False

def opener_ok(data):
    def f(req, timeout=0):
        f.last = req; return FakeResp(json.dumps({"data": data}).encode())
    return f

class Buffer(unittest.TestCase):
    def test_due_utc_brasilia(self):
        self.assertEqual(B.due_utc("2026-11-23 12:00"), "2026-11-23T15:00:00.000Z")
        self.assertEqual(B.due_utc("2026-11-23 19:00"), "2026-11-23T22:00:00.000Z")

    def test_chave_ausente_bloqueia(self):
        with self.assertRaises(B.BufferError): B.gql("query{a}", "")

    def test_chave_nunca_vaza_em_erro(self):
        def boom(req, timeout=0): raise urllib.error.HTTPError("u", 401, "x", {}, None)
        try: B.gql("query{a}", "SEGREDO123", opener=boom)
        except B.BufferError as e: self.assertNotIn("SEGREDO123", str(e))

    def test_bearer_no_header(self):
        o = opener_ok({"account": {"organizations": []}}); B.probe("K", opener=o)
        self.assertEqual(o.last.get_header("Authorization"), "Bearer K")

    def test_pedidos_so_nao_agendados_e_um_por_rede(self):
        pk = json.load(open(B.ROOT / "publicacao/pacote_v1.json", encoding="utf8"))
        ped = B.montar_pedidos(pk, {r: "c" for r in B.SERVICOS}, lambda e: "u")
        self.assertEqual(len(ped), len(pk["episodios"]) * 3)
        for p in ped:
            self.assertEqual(p["input"]["mode"], "customScheduled")
            self.assertTrue(p["input"]["dueAt"].endswith("Z"))
            self.assertLessEqual(len(p["input"]["text"]), 2200)
        pk["episodios"][0]["plataformas"]["tiktok"]["estado"] = "agendado"
        self.assertEqual(len(B.montar_pedidos(pk, {"tiktok": "c"}, lambda e: "u")), len(pk["episodios"]) - 1)

    def test_needs_approval_obrigatorio_no_pedido(self):
        pk = json.load(open(B.ROOT / "publicacao/pacote_v1.json", encoding="utf8"))
        for p in B.montar_pedidos(pk, {"tiktok": "c"}, lambda e: "u"):
            self.assertIs(p["input"]["needsApproval"], False)

    def test_introspect_deep_segue_tipos_aninhados(self):
        resp = {"PostInputMetaData": {"kind": "INPUT_OBJECT", "name": "PostInputMetaData", "enumValues": None, "inputFields": [
                    {"name": "youtube", "type": {"name": "YT", "kind": "INPUT_OBJECT", "ofType": None}}]},
                "YT": {"kind": "INPUT_OBJECT", "name": "YT", "enumValues": None, "inputFields": [
                    {"name": "title", "type": {"name": None, "kind": "NON_NULL", "ofType": {"name": "String", "kind": "SCALAR", "ofType": None}}}]}}
        def op(req, timeout=0):
            n = json.loads(req.data)["variables"]["n"]
            return FakeResp(json.dumps({"data": {"__type": resp.get(n)}}).encode())
        out = B.introspect_deep("K", raiz=("PostInputMetaData",), opener=op)
        self.assertEqual(out["YT"]["title"], "String")

    def test_metadados_por_rede_e_titulo_youtube(self):
        pk = json.load(open(B.ROOT / "publicacao/pacote_v1.json", encoding="utf8"))
        for p in B.montar_pedidos(pk, {r: "c" for r in B.SERVICOS}, lambda e: "u"):
            m = p["input"]["metadata"]
            if p["rede"] == "youtube":
                self.assertLessEqual(len(m["youtube"]["title"]), 60); self.assertFalse(m["youtube"]["madeForKids"])
            if p["rede"] == "instagram": self.assertEqual(m["instagram"]["type"], "reel")
            self.assertEqual(list(m), [p["rede"]])

    def test_schedule_bloqueado(self):
        with self.assertRaises(B.BufferError): B.agendar()

    def test_trava_do_motor_so_libera_este_modulo(self):
        self.assertEqual(G.scan_forbidden(), [])
        self.assertEqual(G.check_workflows(), [])
        wf = (B.ROOT / ".github/workflows/vnc-buffer.yml").read_text(encoding="utf8")
        self.assertNotIn("schedule", wf.replace("agendamento", ""))
        self.assertIn('"probe","introspect","introspect_deep","introspect_query","dry"', wf)
        self.assertNotIn("api.buffer.com", wf)

if __name__ == "__main__":
    unittest.main()


def test_introspect_query_somente_leitura():
    from agents import vnc_buffer as b
    chamadas = []

    def opener(req, *a, **k):
        chamadas.append(req.data.decode())
        import io, json as _j
        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *x): return False
        return R(_j.dumps({"data": {"__type": {"kind": "OBJECT", "name": "Query", "fields": [
            {"name": "posts", "args": [{"name": "input", "type": {"name": "PostsInput", "kind": "INPUT_OBJECT", "ofType": None}}],
             "type": {"name": "PostConnection", "kind": "OBJECT", "ofType": None}}]}}}).encode())
    out = b.introspect_query("k", opener=opener)
    assert out["Query"]["posts"]["args"] == {"input": "PostsInput"}
    assert all("mutation" not in c.lower() for c in chamadas)
