"""Real ESP serialization tests against the built or deployed C# backend."""
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import zlib


def sub(tag, data):
    return tag.encode("ascii") + struct.pack("<H", len(data)) + data


def record(tag, data, formid=0, flags=0):
    return tag.encode("ascii") + struct.pack("<IIIIHH", len(data), flags, formid, 0, 131, 0) + data


def plugin(tag, payload, localized=False, compressed=False):
    header = record("TES4", sub("HEDR", struct.pack("<fII", 1.0, 1, 0x801)), flags=0x80 if localized else 0)
    if compressed:
        payload = struct.pack("<I", len(payload)) + zlib.compress(payload)
    item = record(tag, payload, 0x800, 0x40000 if compressed else 0)
    if tag == "INFO":
        # FO4 nests INFO under DIAL (type 7), itself under QUST (type 10).
        topic = record("DIAL", sub("EDID", b"EncodingProbeTopic\0")
                       + sub("QNAM", struct.pack("<I", 0x802))
                       + sub("TIFC", struct.pack("<I", 1)), 0x801)
        children = b"GRUP" + struct.pack("<IIIII", len(item) + 24, 0x801, 7, 0, 0) + item
        quest = record("QUST", sub("EDID", b"EncodingProbeQuest\0"), 0x802)
        quest_children = b"GRUP" + struct.pack("<IIIII", len(topic) + len(children) + 24, 0x802, 10, 0, 0) + topic + children
        header = record("TES4", sub("HEDR", struct.pack("<fII", 1.0, 3, 0x803)))
        return header + b"GRUP" + struct.pack("<I", len(quest) + len(quest_children) + 24) + b"QUST" + bytes(12) + quest + quest_children
    return header + b"GRUP" + struct.pack("<I", len(item) + 24) + tag.encode("ascii") + bytes(12) + item


def fields(data):
    """Independent byte-level parser, so passing Mutagen verification is insufficient."""
    values = []
    pos = 0
    while pos < len(data):
        tag = data[pos:pos + 4].decode("ascii")
        size, flags = struct.unpack_from("<II", data, pos + 4)
        if tag == "GRUP":
            values.extend(fields(data[pos + 24:pos + size]))
            pos += size
            continue
        payload = data[pos + 24:pos + 24 + size]
        if flags & 0x40000:
            payload = zlib.decompress(payload[4:])
        index = 0
        while index < len(payload):
            field = payload[index:index + 4].decode("ascii")
            length = struct.unpack_from("<H", payload, index + 4)[0]
            values.append((tag, field, payload[index + 6:index + 6 + length]))
            index += 6 + length
        pos += 24 + size
    return values


class PluginEncodingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        default = Path(__file__).resolve().parents[2] / "TranslationData/Backend/TmrPluginTranslator.exe"
        backend = Path(os.environ.get("TMR_TRANSLATOR", default)).resolve()
        if not backend.is_file():
            raise unittest.SkipTest("Build the translator and set TMR_TRANSLATOR to its DLL or EXE")
        cls.command = (["dotnet", str(backend)] if backend.suffix == ".dll" else [str(backend)])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="tmrkr-encoding-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.name = "EncodingProbe.esp"

    def row(self, source, dest, tag="MISC", field="FULL", index=0):
        return {"owner": self.name.lower(), "id": "000800", "record": tag, "field": field,
                "rec_id": index, "rec_id_max": index, "string_id": 0, "source": source, "dest": dest}

    def translate(self, source, rows, mode="direct", suffix="output"):
        direct = self.root / f"{suffix}-map.json"
        direct.write_text(json.dumps({"schema_version": 1, "target": self.name, "mappings": rows},
                                     ensure_ascii=False), encoding="utf-8")
        bank = self.root / f"{suffix}-bank.json"
        bank.write_text(json.dumps({"schema_version": 1, "mappings": rows}, ensure_ascii=False), encoding="utf-8")
        output = self.root / suffix / self.name
        args = ([str(direct), str(output)] if mode == "direct" else ["-", str(bank), str(output)])
        run = subprocess.run(self.command + [str(source)] + args, encoding="utf-8", errors="strict",
                             capture_output=True, timeout=90)
        self.assertEqual(run.returncode, 0, run.stderr)
        report = json.loads(run.stdout.strip().splitlines()[-1])
        self.assertEqual(report["status"], "translated", report)
        self.assertTrue(report["text_roundtrip_verified"])
        self.assertGreater(report["verified_strings"], 0)
        self.assertEqual(report["translation_encoding"], "utf-8")
        return output

    def make_input(self, payload, tag="MISC", **options):
        path = self.root / "input" / self.name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(plugin(tag, payload, **options))
        return path

    def misc(self, value):
        return sub("EDID", b"EncodingProbeItem\0") + sub("FULL", value + b"\0") + sub("DATA", struct.pack("<If", 1, 1.0))

    def texts(self, path, field="FULL"):
        return [v for tag, f, v in fields(path.read_bytes()) if tag != "TES4" and f == field]

    def test_direct_and_fallback_store_korean_utf8(self):
        source = self.make_input(self.misc(b"Encoding Test"))
        for mode in ("direct", "fallback"):
            with self.subTest(mode=mode):
                output = self.translate(source, [self.row("Encoding Test", "한국어 테스트")], mode, mode)
                self.assertEqual(self.texts(output), ["한국어 테스트".encode() + b"\0"])
                self.assertEqual(self.texts(output, "EDID"), [b"EncodingProbeItem\0"])

    def test_cp1252_punctuation_and_compressed_record(self):
        original = "Trader’s Café – Supplies"
        source = self.make_input(self.misc(original.encode("cp1252")), compressed=True)
        output = self.translate(source, [self.row(original, "상인의 물품 — 보급품")])
        self.assertEqual(self.texts(output), ["상인의 물품 — 보급품".encode() + b"\0"])

    def test_existing_utf8_korean_can_be_read_and_retranslated(self):
        source = self.make_input(self.misc("기존 한국어".encode()))
        output = self.translate(source, [self.row("기존 한국어", "수정된 한국어")])
        self.assertEqual(self.texts(output), ["수정된 한국어".encode() + b"\0"])

    def test_dialogue_does_not_translate_identical_script_notes(self):
        original = "Hey, buddy! You lookin' to earn some caps?"
        payload = sub("ENAM", bytes.fromhex("84 00 00 00"))
        payload += sub("TRDA", bytes.fromhex("00 00 00 00 01 00 00 00 00 01 00 00 ff ff ff ff ff ff ff ff"))
        for field in ("NAM1", "NAM2", "NAM3", "NAM4"):
            payload += sub(field, original.encode() + b"\0")
        source = self.make_input(payload, tag="INFO")
        for mode in ("direct", "fallback"):
            with self.subTest(mode=mode):
                output = self.translate(source,
                    [self.row(original, "이봐, 형씨! 병뚜껑 좀 벌어볼 생각 있어?", "INFO", "NAM1")],
                    mode, mode)
                self.assertEqual(self.texts(output, "NAM1"),
                    ["이봐, 형씨! 병뚜껑 좀 벌어볼 생각 있어?".encode() + b"\0"])
                for field in ("NAM2", "NAM3", "NAM4"):
                    self.assertEqual(self.texts(output, field), [original.encode() + b"\0"])

    def test_indexed_objectives_preserve_different_translations(self):
        payload = sub("EDID", b"EncodingProbeQuest\0") + sub("FULL", b"Test Quest\0")
        payload += sub("QOBJ", struct.pack("<H", 10)) + sub("NNAM", b"Objective\0")
        payload += sub("QOBJ", struct.pack("<H", 20)) + sub("NNAM", b"Objective\0")
        source = self.make_input(payload, tag="QUST")
        rows = [self.row("Objective", "첫 번째 목표", "QUST", "NNAM", 0),
                self.row("Objective", "두 번째 목표", "QUST", "NNAM", 1)]
        output = self.translate(source, rows)
        self.assertEqual(self.texts(output, "NNAM"),
                         ["첫 번째 목표".encode() + b"\0", "두 번째 목표".encode() + b"\0"])

    def test_localized_english_sidecar_stores_and_reads_korean_utf8(self):
        payload = sub("EDID", b"EncodingProbeItem\0") + sub("FULL", struct.pack("<I", 7))
        payload += sub("DATA", struct.pack("<If", 1, 1.0))
        source = self.make_input(payload, localized=True)
        strings = source.parent / "Strings"
        strings.mkdir()
        text = b"Encoding Test\0"
        (strings / "EncodingProbe_en.STRINGS").write_bytes(struct.pack("<IIII", 1, len(text), 7, 0) + text)
        output = self.translate(source, [self.row("Encoding Test", "한국어 테스트")])
        tables = list((output.parent / "Strings").glob("*_en.STRINGS"))
        self.assertEqual(len(tables), 1)
        data = tables[0].read_bytes()
        count = struct.unpack_from("<I", data)[0]
        stringid, offset = struct.unpack_from("<II", data, 8)
        self.assertEqual(struct.unpack("<I", self.texts(output)[0])[0], stringid)
        stored = data[8 + 8 * count + offset:].split(b"\0", 1)[0]
        self.assertEqual(stored, "한국어 테스트".encode())
        second = self.translate(output, [self.row("한국어 테스트", "두 번째 번역")], suffix="second")
        self.assertTrue(second.is_file())


if __name__ == "__main__":
    unittest.main()
