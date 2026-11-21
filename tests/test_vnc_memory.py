import json, multiprocessing as mp, tempfile, unittest
from pathlib import Path
from agents import vnc_memory as M

REG = {"episodes": {"E01": {"used": [{"source": "mixkit", "id": "41739", "scene": "S04"}], "discarded_versions": {"v1": [{"source": "coverr", "id": "x-1"}]}}}}


def C(i, ep_title="soft rain window", sha=None, ph=None, origin=None, source="mixkit"):
    return {"source": source, "id": str(i), "scene": "S01", "title": ep_title, "sha256": sha, "phashes": ph, "origin_id": origin, "dur": 10}


def _worker(args):
    path, ep, cid = args
    ok, b = M.try_reserve(ep, f"run-{ep}", [C(cid)], path=path, reg=REG)
    return ep, ok


class Memory(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.p = Path(self.d) / "ledger.json"

    def test_legacy_id_blocked_and_released_is_free(self):
        ok, b = M.try_reserve("E02", "r1", [C(41739)], self.p, REG)
        self.assertFalse(ok); self.assertIn("id_ja_usado_em_E01", b["mixkit:41739"][0])
        ok, _ = M.try_reserve("E02", "r1", [C(5)], self.p, REG); self.assertTrue(ok)
        self.assertFalse(M.try_reserve("E03", "r2", [C(5)], self.p, REG)[0])      # reservado por E02
        self.assertEqual(M.release("E02", "r1", self.p), 1)
        self.assertTrue(M.try_reserve("E03", "r2", [C(5)], self.p, REG)[0])      # liberado

    def test_exact_file_same_origin_and_visual_duplicates(self):
        M.try_reserve("E02", "r", [C(1, sha="aa", ph=[0, 0, 0], origin="film-9")], self.p, REG); M.confirm("E02", self.p)
        for c, frag in ((C(2, "unrelated clip", sha="aa"), "mesmo_arquivo"), (C(3, "foo bar baz", origin="film-9"), "mesma_filmagem"),
                        (C(4, "other thing", ph=[1, 3, 7]), "visual_igual"), (C(6, "window soft rain", ph=None), "titulo_equivalente")):
            ok, b = M.try_reserve("E03", "r9", [c], self.p, REG); self.assertFalse(ok, frag); self.assertIn(frag, str(b))
        # suspeito (d entre 7 e 10 em >=2 quadros) = bloqueio conservador; distante (>10) = livre
        near = (1 << 9) - 1  # 9 bits de diferenca
        ok, b = M.try_reserve("E03", "r9", [C(7, "zzz yyy xxx", ph=[near, near, near])], self.p, REG); self.assertFalse(ok); self.assertIn("inconclusivo", str(b))
        far = (1 << 30) - 1
        self.assertTrue(M.try_reserve("E03", "r9", [C(8, "ccc ddd eee", ph=[far, far, far])], self.p, REG)[0])

    def test_override_humano_libera_par_suspeito(self):
        M.try_reserve("E02", "r", [C(1, ph=[0, 0, 0])], self.p, REG)
        led = M.load(self.p)
        ov = {frozenset(("mixkit:4", "mixkit:1"))}
        self.assertEqual(M.conflicts(C(4, "other thing", ph=[1, 3, 7]), "E03", led, REG, overrides=ov), [])

    def test_idempotent_same_episode_and_confirmed_never_released(self):
        a = [C(1), C(2)]
        self.assertTrue(M.try_reserve("E02", "r1", a, self.p, REG)[0]); self.assertTrue(M.try_reserve("E02", "r2", a, self.p, REG)[0])
        self.assertEqual(M.confirm("E02", self.p), 2)
        self.assertEqual(M.release("E02", "r2", self.p), 0)
        self.assertEqual({e["state"] for e in M.load(self.p)["entries"].values()}, {"confirmed"})
        self.assertFalse(M.try_reserve("E03", "x", [C(1)], self.p, REG)[0])

    def test_all_or_nothing(self):
        ok, _ = M.try_reserve("E02", "r", [C(1), C(41739)], self.p, REG); self.assertFalse(ok)
        self.assertEqual(M.load(self.p)["entries"], {})

    def test_reselection_releases_dropped_reservation(self):
        M.try_reserve("E02", "r1", [C(1), C(2)], self.p, REG); M.try_reserve("E02", "r2", [C(1), C(3)], self.p, REG)
        st = {k: e["state"] for k, e in M.load(self.p)["entries"].items()}
        self.assertEqual(st["mixkit:2"], "released"); self.assertEqual(st["mixkit:3"], "reserved")

    def test_concurrent_processes_only_one_episode_wins_and_ledger_is_valid_json(self):
        jobs = [(str(self.p), f"E{n}", 77) for n in range(10, 22)]
        with mp.get_context("fork").Pool(6) as pool:
            res = pool.map(_worker, jobs)
        self.assertEqual(sum(ok for _, ok in res), 1)
        led = json.loads(self.p.read_text()); self.assertEqual(len([e for e in led["entries"].values() if e["state"] == "reserved"]), 1)

    def test_persistence_across_processes(self):
        M.try_reserve("E02", "r", [C(1)], self.p, REG)
        self.assertEqual(M.load(self.p)["entries"]["mixkit:1"]["episode"], "E02")
