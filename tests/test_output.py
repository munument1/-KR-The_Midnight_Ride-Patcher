import json
import tempfile
import unittest
from pathlib import Path

import tmrkr
from tmrkr_output import BASE_MOD, EXCLUDED_PLUGINS, _contained, _provider_target, _translate_interface
from tmrkr_mcm import translate_mcm_json


class OutputTests(unittest.TestCase):
    def test_release_version(self):
        self.assertEqual(tmrkr.VERSION, "1.0.2")

    def test_removed_ptr_plugins_stay_excluded(self):
        self.assertIn("ptrfo4001_t60pistol.esl", EXCLUDED_PLUGINS)
        self.assertIn("ptrfo4002_vangraff.esl", EXCLUDED_PLUGINS)

    def test_provider_target_preserves_original_mod_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            winner = {"provider": "Previsibines Repair Pack - Full (1.11.191)", "path": "prp.esp"}
            self.assertEqual(
                _provider_target(stage, winner),
                (stage / "mods" / "Previsibines Repair Pack - Full (1.11.191)" / "prp.esp").resolve(),
            )
            game = {"provider": "game:Data", "path": "Interface/Translate_en.txt"}
            self.assertEqual(
                _provider_target(stage, game),
                (stage / "mods" / BASE_MOD / "Interface" / "Translate_en.txt").resolve(),
            )

    def test_contained_rejects_parent_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                _contained(root, "../escape.txt")

    def test_interface_translation_keeps_unknown_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "MCM_en.txt"
            mapping = root / "map.json"
            output = root / "out.txt"
            source.write_text("$A\tHello\n$B\tUnknown\n", encoding="utf-8")
            mapping.write_text(json.dumps({"Hello": "안녕하세요"}, ensure_ascii=False), encoding="utf-8")
            stats = _translate_interface(source, mapping, output)
            self.assertEqual(stats["matched"], 1)
            self.assertIn("$A\t안녕하세요", output.read_text(encoding="utf-8"))
            self.assertIn("$B\tUnknown", output.read_text(encoding="utf-8"))

    def test_mcm_merge_preserves_new_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "config.json"
            mapping = root / "map.json"
            output = root / "out.json"
            source.write_text(json.dumps({"title": "Old", "newSetting": "Keep me"}), encoding="utf-8")
            mapping.write_text(json.dumps({
                "old": {"translated": "새 제목", "status": "TRANSLATED"}
            }, ensure_ascii=False), encoding="utf-8")
            stats = translate_mcm_json(source, mapping, output)
            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(stats["matched"], 1)
            self.assertEqual(data["title"], "새 제목")
            self.assertEqual(data["newSetting"], "Keep me")


if __name__ == "__main__":
    unittest.main()
