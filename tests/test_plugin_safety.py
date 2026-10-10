import json
from pathlib import Path
import struct
import subprocess
import shutil
import zlib
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import tmrkr
from tmrkr_output import build_output
from tmrkr_plugin_safety import plugin_skip_reason


def subrecord(signature, body):
    return signature + struct.pack("<H", len(body)) + body


def plugin(body):
    return b"TES4" + struct.pack("<II", len(body), 0) + bytes(12) + body


def world_plugin(body, compressed=False):
    flags = 0x40000 if compressed else 0
    if compressed:
        body = struct.pack("<I", len(body)) + zlib.compress(body)
    record = b"WRLD" + struct.pack("<II", len(body), flags) + bytes(12) + body
    group = b"GRUP" + struct.pack("<I", len(record) + 24) + bytes(16) + record
    return plugin(b"") + group


class PluginSafetyTests(unittest.TestCase):
    def test_backend_direct_call_blocks_ofst_without_writing(self):
        dll = (Path(__file__).resolve().parents[1] / "tools" / "TmrPluginTranslator"
               / "bin" / "Debug" / "net9.0" / "TmrPluginTranslator.dll")
        if not dll.is_file() or not shutil.which("dotnet"):
            self.skipTest("Build the .NET backend first to run direct-call integration")
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "ppf.esm"
            output = Path(tmp) / "out" / "ppf.esm"
            bodies = [subrecord(b"OFST", bytes(4)),
                      subrecord(b"XXXX", struct.pack("<I", 70000))
                      + b"OFST\0\0" + bytes(70000)]
            for body in bodies:
                source.write_bytes(plugin(body))
                run = subprocess.run(["dotnet", str(dll), str(source), "-", str(output)],
                                     capture_output=True, text=True, timeout=30)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(json.loads(run.stdout)["status"], "skipped_unsafe_offsets")
                self.assertFalse(output.parent.exists())
                self.assertEqual(source.read_bytes(), plugin(body))
    def test_worldspace_offsets_in_groups_and_compressed_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "ppf.esm"
            for compressed in [False, True]:
                source.write_bytes(world_plugin(subrecord(b"OFST", bytes(4)), compressed))
                self.assertIsNone(plugin_skip_reason(source))
                source.write_bytes(world_plugin(subrecord(b"FULL", b"OFST\0"), compressed))
                self.assertIsNone(plugin_skip_reason(source))
            data = world_plugin(subrecord(b"OFST", bytes(4)))
            source.write_bytes(data[:-1])
            with self.assertRaises(ValueError):
                plugin_skip_reason(source)

    def test_header_detection(self):
        cases = [
            (subrecord(b"OFST", bytes(4)), True),
            (subrecord(b"OFST", b""), True),
            (subrecord(b"CNAM", b"OFST is just author text\0"), False),
            (subrecord(b"HEDR", bytes(12)), False),
            (subrecord(b"XXXX", struct.pack("<I", 70000))
             + b"OFST\0\0" + bytes(70000), True),
            (subrecord(b"XXXX", struct.pack("<I", 4))
             + b"CNAM\0\0OFST", False),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "ppf.esm"
            for body, expected in cases:
                with self.subTest(body=body[:20]):
                    source.write_bytes(plugin(body))
                    self.assertEqual(bool(plugin_skip_reason(source)), expected)

    def test_invalid_headers_fail_closed(self):
        cases = [
            b"", b"NOPE" + bytes(20), plugin(b"abc"),
            plugin(b"CNAM\x05\x00x"),
            plugin(subrecord(b"XXXX", struct.pack("<I", 5))),
            plugin(subrecord(b"XXXX", b"x")),
            plugin(subrecord(b"XXXX", struct.pack("<I", 5))
                   + subrecord(b"XXXX", struct.pack("<I", 5))),
            b"TES4" + struct.pack("<II", 100, 0) + bytes(12),
            b"TES4" + struct.pack("<II", 0, 0x40000) + bytes(12),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "ppf.esm"
            for data in cases:
                with self.subTest(data=data[:30]):
                    source.write_bytes(data)
                    with self.assertRaises(ValueError):
                        plugin_skip_reason(source)

    def test_output_blocks_exact_and_fallback_before_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "ppf.esm"
            source.write_bytes(plugin(subrecord(b"OFST", bytes(4))))
            base = root / "base"
            (base / "Interface").mkdir(parents=True)
            (base / "Strings").mkdir()
            (base / "Strings" / "base_en.strings").write_bytes(b"base")
            catalog_dir = root / "catalog"
            catalog_dir.mkdir()
            # Deliberately invalid payload path: guard must execute before use.
            entry = {"name": "ppf.esm", "source_sha256": tmrkr.sha256(source),
                     "baseline_status": "translated", "payload": "missing.esm"}
            winner = {"provider": "PRP", "path": "ppf.esm"}
            installation = SimpleNamespace(root=root, profile="test", active=["ppf.esm"],
                                           providers={"ppf.esm": [winner]}, warnings=[],
                                           source=lambda _: source)
            for index, entries in enumerate(([entry], [])):
                with self.subTest(exact=bool(entries)):
                    (catalog_dir / "catalog.json").write_text(json.dumps(
                        {"schema_version": 1, "plugins": entries}), encoding="utf-8")
                    output = root / f"Output{index}"
                    with patch("tmrkr_output.tmrkr.Installation", return_value=installation), \
                            patch("tmrkr_output._run_fallback") as backend:
                        report = build_output(root, base, catalog_dir, output)
                        backend.assert_not_called()
                    self.assertEqual(report["plugins"][0]["status"], "skipped_unsafe_plugin")
                    self.assertTrue(report["warnings"])
                    self.assertFalse(list(output.rglob("*.esm")))
                    self.assertFalse((output / "mods" / "PRP").exists())
                    self.assertEqual(source.read_bytes(), plugin(subrecord(b"OFST", bytes(4))))

    def test_old_exact_payload_is_rebuilt_even_when_source_hash_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "Synthetic.esp"
            source.write_bytes(plugin(subrecord(b"HEDR", bytes(12))))
            base = root / "base"
            (base / "Interface").mkdir(parents=True)
            (base / "Strings").mkdir()
            (base / "Strings/base_en.strings").write_bytes(b"base")
            catalog_dir = root / "catalog"
            catalog_dir.mkdir()
            entry = {"name": source.name, "source_sha256": tmrkr.sha256(source),
                     "baseline_status": "translated", "payload": "old-missing-payload.esp",
                     "plugin_policy_version": 3}
            (catalog_dir / "catalog.json").write_text(json.dumps(
                {"schema_version": 1, "plugins": [entry]}), encoding="utf-8")
            winner = {"provider": "Example", "path": source.name}
            installation = SimpleNamespace(root=root, profile="test", active=[source.name],
                providers={source.name.casefold(): [winner]}, warnings=[], source=lambda _: source)
            with patch("tmrkr_output.tmrkr.Installation", return_value=installation), \
                    patch("tmrkr_output._run_fallback", return_value=(
                        {"status": "no_changes", "plugin_policy_version": 5}, None)) as backend:
                report = build_output(root, base, catalog_dir, root / "Output")
                backend.assert_called_once()
                self.assertEqual(report["plugins"][0]["status"], "updated_no_match")

    def test_current_policy_payload_with_remaining_world_index_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "Synthetic.esp"
            source.write_bytes(world_plugin(subrecord(b"CLSZ", bytes(4))))
            base = root / "base"
            (base / "Interface").mkdir(parents=True)
            (base / "Strings").mkdir()
            (base / "Strings/base_en.strings").write_bytes(b"base")
            catalog_dir = root / "catalog"
            catalog_dir.mkdir()
            payload = catalog_dir / source.name
            payload.write_bytes(source.read_bytes())
            entry = {"name": source.name, "source_sha256": tmrkr.sha256(source),
                     "baseline_status": "translated", "payload": payload.name,
                     "payload_sha256": tmrkr.sha256(payload), "plugin_policy_version": 5}
            (catalog_dir / "catalog.json").write_text(json.dumps(
                {"schema_version": 1, "plugins": [entry]}), encoding="utf-8")
            winner = {"provider": "Example", "path": source.name}
            installation = SimpleNamespace(root=root, profile="test", active=[source.name],
                providers={source.name.casefold(): [winner]}, warnings=[], source=lambda _: source)
            with patch("tmrkr_output.tmrkr.Installation", return_value=installation):
                with self.assertRaisesRegex(ValueError, "Unstripped world-index payload"):
                    build_output(root, base, catalog_dir, root / "Output")


if __name__ == "__main__":
    unittest.main()
