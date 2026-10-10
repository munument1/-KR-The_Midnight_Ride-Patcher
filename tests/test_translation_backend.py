import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

def sub(sig, data):
    return sig + struct.pack("<H", len(data)) + data


def record(sig, form, body):
    return sig + struct.pack("<III", len(body), 0, form) + bytes(8) + body


def fixture():
    header = record(b"TES4", 0, sub(b"HEDR", struct.pack("<fII", 1.0, 2, 0x800))
                    + sub(b"MAST", b"Fallout4.esm\0") + sub(b"DATA", bytes(8)))
    body = record(b"LCTN", 0x55402, sub(b"EDID", b"RelayTowerZimonjaLocation\0")
                  + sub(b"FULL", b"Outpost Zimonja\0"))
    body += record(b"LCTN", 0x55403, sub(b"EDID", b"SafeLocation\0")
                   + sub(b"FULL", b"Safe Location\0"))
    return header + b"GRUP" + struct.pack("<I", len(body) + 24) + b"LCTN" + bytes(12) + body


def row(id, source, dest):
    return {"owner": "Fallout4.esm", "id": id, "record": "LCTN", "field": "FULL",
            "rec_id": 0, "rec_id_max": 0, "string_id": 0, "source": source, "dest": dest}


class BackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dll = (Path(__file__).resolve().parents[1] / "tools/TmrPluginTranslator"
                   / "bin/Debug/net9.0/TmrPluginTranslator.dll")
        if not cls.dll.is_file() or not shutil.which("dotnet"):
            raise unittest.SkipTest("Build the .NET backend first")

    def run_backend(self, source, mapping, output, fallback=None):
        args = ["dotnet", str(self.dll), str(source), str(mapping)]
        if fallback:
            args.append(str(fallback))
        args.append(str(output))
        result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_utf8_and_zimonja_direct_fallback_and_repeat_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "Synthetic.esp"
            source.write_bytes(fixture())
            mapping = root / "map.json"
            mapping.write_text(json.dumps({"schema_version": 1, "target": source.name,
                "mappings": [row("055402", "Outpost Zimonja", "지몬자 초소"),
                             row("055403", "Safe Location", "안전한 장소")]}), encoding="utf-8")
            bank = root / "bank.json"
            bank.write_text(json.dumps({"schema_version": 1, "mappings": [
                row("055402", "Outpost Zimonja", "지몬자 전초기지")]}), encoding="utf-8")
            output = root / "translated/Synthetic.esp"
            detail = self.run_backend(source, mapping, output, bank)
            self.assertEqual(detail["changed"], 1)
            self.assertEqual(detail["protected_records"], 1)
            self.assertTrue(detail["utf8_text_verified"])
            self.assertIn("안전한 장소".encode(), output.read_bytes())
            self.assertIn(b"Outpost Zimonja\0", output.read_bytes())
            self.assertNotIn("지몬자 초소".encode(), output.read_bytes())
            mapping.write_text(json.dumps({"schema_version": 1, "target": source.name,
                "mappings": [row("055403", "안전한 장소", "다시 번역한 장소")]}), encoding="utf-8")
            second = root / "second/Synthetic.esp"
            self.assertEqual(self.run_backend(output, mapping, second)["changed"], 1)
            self.assertIn("다시 번역한 장소".encode(), second.read_bytes())
            self.assertIn(b"Outpost Zimonja\0", second.read_bytes())

    def test_zimonja_only_does_not_generate_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "Synthetic.esp"
            source.write_bytes(fixture())
            mapping = root / "map.json"
            mapping.write_text(json.dumps({"schema_version": 1, "target": source.name,
                "mappings": [row("055402", "Outpost Zimonja", "지몬자 초소")]}), encoding="utf-8")
            output = root / "out/Synthetic.esp"
            self.assertEqual(self.run_backend(source, mapping, output)["status"], "no_changes")
            self.assertFalse(output.exists())

    def test_localized_string_ids_are_not_rewritten_as_inline_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "Synthetic.esp"
            data = fixture()
            source.write_bytes(data[:8] + struct.pack("<I", 0x80) + data[12:])
            mapping = root / "map.json"
            mapping.write_text(json.dumps({"schema_version": 1, "target": source.name,
                "mappings": [row("055403", "Safe Location", "안전한 장소")]}), encoding="utf-8")
            output = root / "out/Synthetic.esp"
            original = source.read_bytes()
            self.assertEqual(self.run_backend(source, mapping, output)["status"], "skipped_localized_strings")
            self.assertFalse(output.exists())
            self.assertEqual(source.read_bytes(), original)

    def test_original_headers_and_unknown_fields_are_preserved(self):
        import zlib
        from tmrkr_plugin_safety import _subrecords
        for compressed in (False, True):
            with self.subTest(compressed=compressed), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = root / "Synthetic.esp"
                original = fixture()
                # Unknown data is deliberately absent from Mutagen's object model.
                marker = sub(b"ZZZZ", bytes(range(256)) * 3)
                body = sub(b"EDID", b"SafeLocation\0") + sub(b"FULL", b"Safe Location\0") + marker
                packed = struct.pack("<I", len(body)) + zlib.compress(body) if compressed else body
                location = record(b"LCTN", 0x55403, packed)
                if compressed:
                    location = location[:8] + struct.pack("<I", 0x40000) + location[12:]
                group_start = original.index(b"GRUP")
                original = original[:group_start] + b"GRUP" + struct.pack("<I", 24 + len(location)) + b"LCTN" + bytes(12) + location
                source.write_bytes(original)
                mapping = root / "map.json"
                mapping.write_text(json.dumps({"schema_version": 1, "target": source.name,
                    "mappings": [row("055403", "Safe Location", "안전한 장소")]}), encoding="utf-8")
                output = root / "out/Synthetic.esp"
                detail = self.run_backend(source, mapping, output)
                self.assertTrue(detail["original_bytes_preserved"])
                result = output.read_bytes()
                self.assertEqual(result[:group_start], original[:group_start])
                start = group_start + 24
                self.assertEqual(result[start + 8:start + 24], location[8:24])
                data = result[start + 24:]
                if compressed:
                    data = zlib.decompress(data[4:])
                self.assertEqual(list(_subrecords(data)),
                    [(sig, "안전한 장소".encode() + b"\0" if sig == b"FULL" else value)
                     for sig, value in _subrecords(body)])
                self.assertEqual(source.read_bytes(), original)

    def test_legacy_cp1252_source_remains_translatable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "Synthetic.esp"
            # Keep sizes unchanged while inserting a CP1252 character.
            source.write_bytes(fixture().replace(b"Safe Location\0", b"Caf\xe9 Location\0"))
            mapping = root / "map.json"
            mapping.write_text(json.dumps({"schema_version": 1, "target": source.name,
                "mappings": [row("055403", "Café Location", "카페 장소")]}), encoding="utf-8")
            output = root / "out/Synthetic.esp"
            self.assertEqual(self.run_backend(source, mapping, output)["changed"], 1)
            self.assertIn("카페 장소".encode(), output.read_bytes())
