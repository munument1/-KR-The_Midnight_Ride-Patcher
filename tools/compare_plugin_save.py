"""Compare OFST cell targets and decoded record bodies before/after saving.

Development diagnostic; this does not certify in-game stability.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tmrkr_plugin_safety import _subrecords, offset_tables


def inspect(path):
    offset_tables(path)  # Validate boundaries first.
    data = path.read_bytes()
    records, positions, worlds = {}, {}, {}
    pos = 0
    while pos < len(data):
        signature, size, flags, form = struct.unpack_from("<4sIII", data, pos)
        if signature == b"GRUP":
            pos += 24
            continue
        body = data[pos + 24:pos + 24 + size]
        if flags & 0x40000:
            body = zlib.decompress(body[4:])
        key = (signature.decode("ascii"), f"{form:08X}")
        records[key] = body
        positions[pos] = key
        if signature == b"WRLD":
            for sub, value in _subrecords(body):
                if sub == b"OFST":
                    worlds[key[1]] = (pos, value)
        pos += 24 + size
    return data, records, positions, worlds


def compare(original, output):
    a, ar, ap, aw = inspect(original)
    b, br, bp, bw = inspect(output)
    changed = [key for key in ar.keys() & br.keys() if ar[key] != br[key]]
    result = {
        "original": str(original.resolve()), "output": str(output.resolve()),
        "original_sha256": hashlib.sha256(a).hexdigest(),
        "output_sha256": hashlib.sha256(b).hexdigest(),
        "original_size": len(a), "output_size": len(b),
        "record_key_sets_equal": ar.keys() == br.keys(),
        "changed_decoded_records_by_type": dict(Counter(key[0] for key in changed)),
        "OFST": [],
    }
    for world, (base, table) in aw.items():
        new_world = bw.get(world)
        indexed_values = [(i, x[0]) for i, x in enumerate(struct.iter_unpack("<I", table)) if x[0]]
        values = [value for _, value in indexed_values]
        before = [(i, ap.get(base + value)) for i, value in indexed_values]
        cell_targets = [(i, key) for i, key in before if key and key[0] == "CELL"]
        # PRP WRLD offsets are relative to the start of their owning WRLD record.
        new_values = [x[0] for x in struct.iter_unpack("<I", new_world[1])] if new_world else []
        after_correct = sum(i < len(new_values) and bp.get(new_world[0] + new_values[i]) == key
                            for i, key in cell_targets) if new_world else 0
        result["OFST"].append({
            "world": world, "entries": len(values),
            "original_entries_pointing_to_cells": len(cell_targets),
            "entries_still_pointing_to_same_cell_after_save": after_correct,
            "table_bytes_unchanged": bool(new_world and new_world[1] == table),
        })
    location = ("LCTN", "00055402")
    if location in ar and location in br:
        old = list(_subrecords(ar[location]))
        new = list(_subrecords(br[location]))
        result["zimonja"] = {
            "non_FULL_subrecords_equal": [x for x in old if x[0] != b"FULL"]
                == [x for x in new if x[0] != b"FULL"],
            "original_FULL": [v.rstrip(b"\0").decode("utf-8") for s, v in old if s == b"FULL"],
            "output_FULL": [v.rstrip(b"\0").decode("utf-8") for s, v in new if s == b"FULL"],
        }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("original", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.original, args.output)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
