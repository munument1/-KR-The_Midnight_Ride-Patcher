import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from xml.sax.saxutils import escape

from test_plugin_safety import plugin, subrecord, world_plugin
from tmrkr_plugin_safety import _subrecords
import zlib


class IndexStripperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('dotnet'):
            raise unittest.SkipTest('Requires dotnet')
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        source = Path(__file__).resolve().parents[1] / 'tools/TmrPluginTranslator/WorldIndexStripper.cs'
        (cls.root / 'Harness.csproj').write_text(
            '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType>'
            '<TargetFramework>net9.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings>'
            '</PropertyGroup><ItemGroup><Compile Include="' + escape(str(source), {'"': '&quot;'}) +
            '" Link="WorldIndexStripper.cs" /></ItemGroup></Project>', encoding='utf-8')
        (cls.root / 'Program.cs').write_text(
            'System.Console.WriteLine(System.Text.Json.JsonSerializer.Serialize('
            'WorldIndexStripper.StripAndVerify(args[0])));', encoding='utf-8')
        result = subprocess.run(['dotnet', 'build', str(cls.root / 'Harness.csproj'), '-v', 'quiet'],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        if result.returncode:
            cls.tmp.cleanup()
            raise RuntimeError(result.stdout + result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_strip(self, data):
        path = self.root / 'fixture.esp'
        path.write_bytes(data)
        run = subprocess.run(['dotnet', str(self.root / 'bin/Debug/net9.0/Harness.dll'), str(path)],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        return run, path.read_bytes()

    def test_compressed_nested_groups_extended_indexes_and_surviving_marker(self):
        # Keep a large unrelated field and its own XXXX intact. Remove exactly
        # the marker associated with each stripped field, even in compressed WRLD.
        def extended(sig, payload):
            return subrecord(b'XXXX', struct.pack('<I', len(payload))) + sig + bytes(2) + payload
        kept = subrecord(b'FULL', '커먼웰스'.encode() + b'\0') + extended(b'MHDT', bytes(70000))
        body = kept + extended(b'OFST', bytes(70000)) + extended(b'CLSZ', bytes(70000))
        for compressed in (False, True):
            data = world_plugin(body, compressed)
            # Nest the fixture's existing top-level group inside a second group.
            children = data[24:]
            nested = plugin(b'') + b'GRUP' + struct.pack('<I', len(children) + 24) + bytes(16) + children
            run, saved = self.run_strip(nested)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout), {'OFST': 1, 'CLSZ': 1, 'XXXX': 2})
            self.assertEqual(struct.unpack_from('<I', saved, 28)[0], len(saved) - 24)
            self.assertEqual(struct.unpack_from('<I', saved, 52)[0], len(saved) - 48)
            size, flags = struct.unpack_from('<II', saved, 76)
            raw = saved[96:96 + size]
            decoded = zlib.decompress(raw[4:]) if flags & 0x40000 else raw
            self.assertEqual(decoded, kept)
            self.assertEqual(list(_subrecords(decoded)), list(_subrecords(kept)))
            again, same = self.run_strip(saved)
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertEqual(same, saved)
            self.assertEqual(json.loads(again.stdout), {'OFST': 0, 'CLSZ': 0, 'XXXX': 0})

    def test_clsz_without_ofst_is_removed_and_text_is_preserved(self):
        kept = subrecord(b'FULL', b'OFST CLSZ\0')
        run, saved = self.run_strip(world_plugin(kept + subrecord(b'CLSZ', b'abc')))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout), {'OFST': 0, 'CLSZ': 1, 'XXXX': 0})
        self.assertEqual(saved, world_plugin(kept))

    def test_invalid_boundaries_do_not_change_file(self):
        for data in (world_plugin(subrecord(b'OFST', bytes(4)))[:-1],
                     world_plugin(subrecord(b'XXXX', struct.pack('<I', 100))),
                     plugin(subrecord(b'OFST', bytes(4)))):
            run, saved = self.run_strip(data)
            self.assertNotEqual(run.returncode, 0)
            self.assertEqual(saved, data)
