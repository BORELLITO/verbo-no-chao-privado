import copy, json, unittest, tempfile
from pathlib import Path
from agents import vnc_gates as g

ROOT = Path(__file__).resolve().parents[1]
SEL = json.loads((ROOT / "contracts/e01_v5_scene_clip_selection_landscape.json").read_text(encoding="utf8"))
REG = g.load_registry()


class Gates(unittest.TestCase):
    def test_e01_approved_selection_passes(self):
        self.assertEqual(g.check_selection(SEL, "E01", REG), [])

    def test_workflows_and_forbidden_calls_clean(self):
        self.assertEqual(g.check_workflows(), [])
        self.assertEqual(g.scan_forbidden(), [])

    def test_clip_from_other_episode_is_blocked(self):
        sel = copy.deepcopy(SEL); reg = copy.deepcopy(REG)
        errs = g.check_selection(sel, "E02", g.register("E02", sel, reg))
        self.assertTrue(any("ja usado/descartado em E01" in e for e in errs))

    def test_discarded_clip_of_other_episode_is_blocked(self):
        reg = copy.deepcopy(REG); sel = copy.deepcopy(SEL)
        sel["clips"][0] = {"scene": "S01", "source": "pexels", "id": "19967985"}  # descartado no E01 v3
        g.register("E02", sel, reg)
        self.assertTrue(any("E01" in e for e in g.check_selection(sel, "E02", reg)))

    def test_duplicate_inside_episode_blocked(self):
        sel = copy.deepcopy(SEL); sel["clips"][1] = dict(sel["clips"][0], scene="S02")
        reg = copy.deepcopy(REG); g.register("E09", sel, reg)
        self.assertTrue(any("repetido dentro" in e for e in g.check_selection(sel, "E09", reg)))

    def test_unregistered_clip_blocked(self):
        sel = copy.deepcopy(SEL); sel["clips"][0] = {"scene": "S01", "source": "coverr", "id": "coverr-novo-123"}
        self.assertTrue(any("nao registrado" in e for e in g.check_selection(sel, "E01", REG)))

    def test_bad_source_scene_count_and_publication(self):
        sel = copy.deepcopy(SEL); sel["clips"] = sel["clips"][:11]
        self.assertTrue(any("cenas_invalidas" in e for e in g.check_selection(sel, "E01", REG)))
        sel = copy.deepcopy(SEL); sel["clips"][0]["source"] = "youtube"
        self.assertTrue(any("fonte nao permitida" in e for e in g.check_selection(sel, "E01", REG)))
        sel = copy.deepcopy(SEL); sel["publication_authorized"] = True
        self.assertTrue(any("publicacao" in e for e in g.check_selection(sel, "E01", REG)))

    def test_music_repeat_blocked(self):
        self.assertTrue(g.check_music("543", "E02", REG))
        self.assertEqual(g.check_music("543", "E01", REG), [])
        self.assertEqual(g.check_music("999", "E02", REG), [])

    def test_workflow_gate_detects_violations(self):
        with tempfile.TemporaryDirectory() as d:
            w = Path(d, ".github/workflows"); w.mkdir(parents=True)
            (w / "x.yml").write_text("on:\n  schedule:\n    - cron: '0 * * * *'\njobs:\n  a:\n    steps:\n      - uses: actions/checkout@v4\n")
            e = " ".join(g.check_workflows(Path(d)))
            for k in ("cron/schedule", "contents: read", "timeout-minutes", "SHA fixo", "concurrency"):
                self.assertIn(k, e)

    def test_forbidden_voice_and_publish_calls_detected(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "agents").mkdir(); (Path(d) / ".github/workflows").mkdir(parents=True)
            (Path(d) / "agents/a.py").write_text("u='https://api.elevenlabs.io/v1/text-to-speech/x'\nv='https://open.tiktokapis.com/v2/post'\n")
            e = " ".join(g.scan_forbidden(Path(d)))
            self.assertIn("R4_voz_nova", e); self.assertIn("publicacao", e)

    def test_episode_config_e01_ok_and_template_rejected(self):
        self.assertEqual(g.check_episode_config("E01", SEL), [])
        import shutil, tempfile
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "episodes").mkdir(); shutil.copy(ROOT / "episodes/_MODELO_EPISODIO.json", Path(d) / "episodes/E02.json")
            e = " ".join(g.check_episode_config("E02", SEL, Path(d)))
            self.assertIn("audio_sha256 completo", e); self.assertIn("scenes S01..S12", e); self.assertIn("capa", e)
        self.assertEqual(g.check_episode_config("E77", SEL), ["falta episodes/E77.json"])

    def test_runflow_config_is_consistent(self):
        c = json.loads((ROOT / "run/runflow.json").read_text())
        if set(c["stages"]) != {"curate"}:  # curadoria roda antes de existir a selecao
            self.assertTrue((ROOT / c["selection"]).exists())
        self.assertTrue(set(c["stages"]) <= {"gates", "build", "sync", "cover", "curate"})
        self.assertTrue((ROOT / "episodes" / f"{c['episode']}.json").exists())


if __name__ == "__main__":
    unittest.main()
