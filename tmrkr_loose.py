"""Loose text generation for Fallout 4 MCM/Interface translations."""
from __future__ import annotations

from pathlib import Path

from tmrkr_sst import read_sst, custom_text_mapping


def _decode_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    if raw.startswith(b"\xff\xfe"):
        return raw.decode("utf-16"), "utf-16"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("cp1252"), "cp1252"


def translate_interface_file(source: Path, sst_path: Path, output: Path) -> dict:
    text, _ = _decode_text(source)
    sst = read_sst(sst_path)
    mapping = custom_text_mapping(sst)

    matched = 0
    translatable = 0
    missing: list[str] = []
    out_lines: list[str] = []

    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        newline = line[len(body):]
        if "\t" not in body:
            out_lines.append(line)
            continue
        key, value = body.split("\t", 1)
        if value:
            translatable += 1
        translated = mapping.get(value)
        if translated is None:
            if value and not value.startswith("$"):
                missing.append(value)
            out_lines.append(body + newline)
            continue
        matched += 1
        out_lines.append(key + "\t" + translated + newline)

    output.parent.mkdir(parents=True, exist_ok=True)
    # Keep the _en filename; Interface translation tables use UTF-16 LE with a BOM.
    output.write_bytes(b"\xff\xfe" + "".join(out_lines).encode("utf-16-le"))
    return {
        "source": str(source),
        "sst": str(sst_path),
        "output": str(output),
        "encoding": "utf-16-le",
        "sst_format": sst.format,
        "sst_entries": len(sst.entries),
        "mapping_entries": len(mapping),
        "translatable_lines": translatable,
        "matched": matched,
        "missing_count": len(missing),
        "missing": missing,
    }
