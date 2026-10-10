import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from compare_plugin_save import compare, inspect
from tmrkr_plugin_safety import _subrecords


class PrpIndexRemovalTests(unittest.TestCase):
    def check_plugin(self, name):
        root = Path(__file__).resolve().parents[1]
        source = Path(os.environ.get("TMR_PRP_SAMPLE_DIR", "C:/Users/seung/OneDrive/Desktop")) / name
        dll = root / "tools/TmrPluginTranslator/bin/Debug/net9.0/TmrPluginTranslator.dll"
        if not source.is_file() or not dll.is_file() or not shutil.which("dotnet"):
            self.skipTest("Requires the supplied PRP sample and built backend")
        original, records, _, worlds = inspect(source)
        self.assertTrue(worlds)
        full = [v.rstrip(b"\0").decode("utf-8") for s, v in _subrecords(records[("WRLD", "0000003C")])
                if s == b"FULL"][0]
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            mapping = folder / "mapping.json"
            mapping.write_text(json.dumps({"schema_version": 1, "target": name, "mappings": [{
                "owner": "Fallout4.esm", "id": "00003C", "record": "WRLD", "field": "FULL",
                "rec_id": 0, "rec_id_max": 0, "string_id": 0,
                "source": full, "dest": "커먼웰스 번역 검증"}]}), encoding="utf-8")
            output = folder / name
            run = subprocess.run(["dotnet", str(dll), str(source), str(mapping), str(output)],
                                 capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(run.returncode, 0, run.stderr)
            report = json.loads(run.stdout)
            self.assertEqual(report["changed"], 1)
            self.assertEqual(report["plugin_policy_version"], 5)
            self.assertTrue(report["utf8_text_verified"])
            result = compare(source, output)
            self.assertTrue(result["record_key_sets_equal"])
            self.assertTrue(report["world_indexes_absent_verified"])
            self.assertEqual(report["world_indexes_removed"]["OFST"], len(worlds))
            self.assertEqual(report["world_indexes_removed"]["CLSZ"], len(worlds))
            _, saved_records, _, saved_worlds = inspect(output)
            self.assertIn((b"FULL", "커먼웰스 번역 검증".encode() + b"\0"),
                          list(_subrecords(saved_records[("WRLD", "0000003C")])))
            self.assertFalse(saved_worlds)
            for key, body in saved_records.items():
                expected = [(sig, "커먼웰스 번역 검증".encode() + b"\0"
                             if key == ("WRLD", "0000003C") and sig == b"FULL" else value)
                            for sig, value in _subrecords(records[key])
                            if not (key[0] == "WRLD" and sig in (b"OFST", b"CLSZ"))]
                self.assertEqual(list(_subrecords(body)), expected, key)
                if key[0] == "WRLD":
                    self.assertFalse(any(sig in (b"OFST", b"CLSZ") for sig, _ in _subrecords(body)))
        self.assertEqual(source.read_bytes(), original)

    def test_ppf_world_name_translation_removes_both_world_indexes(self):
        self.check_plugin("ppf.esm")

    def test_prp_world_name_translation_removes_both_world_indexes(self):
        self.check_plugin("prp.esp")
