import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import tmrkr
from tmrkr_output import (BASE_MOD, EXCLUDED_PLUGINS, _contained, _provider_target,
                          _translate_interface, _verified_exact_payload)
from tmrkr_mcm import translate_mcm_json
from tmrkr_loose import translate_interface_file


class OutputTests(unittest.TestCase):
    def test_legacy_and_missing_payloads_fall_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = root / "old.esp"
            payload.write_bytes(b"???")
            entry = {"name": "old.esp", "payload": payload.name, "payload_sha256": tmrkr.sha256(payload)}
            self.assertIsNone(_verified_exact_payload(root, entry))
            entry.update(payload_encoding="utf-8", text_roundtrip_verified=True, payload="missing.esp")
            self.assertIsNone(_verified_exact_payload(root, entry))

    def test_verified_payload_still_requires_matching_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = root / "verified.esp"
            payload.write_bytes("한국어".encode())
            entry = {"name": payload.name, "payload": payload.name, "payload_encoding": "utf-8",
                     "text_roundtrip_verified": True, "payload_sha256": tmrkr.sha256(payload)}
            self.assertEqual(_verified_exact_payload(root, entry), payload)
            payload.write_bytes(b"???")
            with self.assertRaisesRegex(ValueError, "Payload hash mismatch"):
                _verified_exact_payload(root, entry)

    def test_release_version(self):
        self.assertEqual(tmrkr.VERSION, "1.0.1")

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
            mapping.write_text(json.dumps({"Hello": "안녕하세요"}, ensure_ascii=False), encoding="utf-8")
            for encoding in ("utf-8", "utf-16"):
                with self.subTest(input_encoding=encoding):
                    source.write_bytes("$A\tHello\r\n$B\tUnknown\r\n".encode(encoding))
                    stats = _translate_interface(source, mapping, output)
                    self.assertEqual(stats["matched"], 1)
                    self.assertEqual(stats["encoding"], "utf-16-le")
                    self.assertEqual(output.read_bytes(), b"\xff\xfe" +
                                     "$A\t안녕하세요\r\n$B\tUnknown\r\n".encode("utf-16-le"))

    def test_loose_interface_uses_utf16_le_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "Safe Travels_en.txt"
            source.write_bytes(b"$A\tHello\r\n$B\tUnknown\r\n")
            output = root / "out.txt"
            sst = SimpleNamespace(format="fixture", entries=[1])
            with patch("tmrkr_loose.read_sst", return_value=sst), \
                    patch("tmrkr_loose.custom_text_mapping", return_value={"Hello": "안녕하세요"}):
                stats = translate_interface_file(source, root / "fixture.sst", output)
            self.assertEqual(stats["encoding"], "utf-16-le")
            self.assertEqual(output.read_bytes(), b"\xff\xfe" +
                             "$A\t안녕하세요\r\n$B\tUnknown\r\n".encode("utf-16-le"))

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
