"""Preflight checks before copying or rewriting Fallout 4 plugins."""
from pathlib import Path
import struct
import zlib

PLUGIN_POLICY_VERSION = 5


def _subrecords(body: bytes):
    pos = 0
    extended = None
    while pos < len(body):
        if len(body) - pos < 6:
            raise ValueError("Truncated subrecord header")
        signature, short_size = struct.unpack_from("<4sH", body, pos)
        pos += 6
        if signature == b"XXXX":
            if extended is not None or short_size != 4 or len(body) - pos < 4:
                raise ValueError("Invalid XXXX size marker")
            extended = struct.unpack_from("<I", body, pos)[0]
            pos += 4
            continue
        length = short_size if extended is None else extended
        extended = None
        if length > len(body) - pos:
            raise ValueError("Subrecord exceeds record body")
        yield signature, body[pos:pos + length]
        pos += length
    if extended is not None:
        raise ValueError("Dangling XXXX size marker")


def offset_tables(path: Path) -> list[dict]:
    """Inspect TES4 and nested WRLD records, including zlib compression."""
    tables = []
    with path.open("rb") as stream:
        ends = [path.stat().st_size]
        first = True
        while ends:
            pos = stream.tell()
            if pos == ends[-1]:
                ends.pop()
                continue
            if ends[-1] - pos < 24:
                raise ValueError("Truncated record/group header")
            header = stream.read(24)
            signature = header[:4]
            size, flags, form_id = struct.unpack_from("<III", header, 4)
            if first and signature != b"TES4":
                raise ValueError("Missing Fallout 4 TES4 header")
            first = False
            if signature == b"GRUP":
                if size < 24 or pos + size > ends[-1]:
                    raise ValueError("Invalid GRUP boundary")
                ends.append(pos + size)
                continue
            if pos + 24 + size > ends[-1]:
                raise ValueError("Record exceeds group/file boundary")
            if signature not in (b"TES4", b"WRLD"):
                stream.seek(size, 1)
                continue
            body = stream.read(size)
            if flags & 0x00040000:
                if signature == b"TES4" or len(body) < 4:
                    raise ValueError("Unsupported/truncated compressed header")
                expected = struct.unpack_from("<I", body)[0]
                try:
                    body = zlib.decompress(body[4:])
                except zlib.error as exc:
                    raise ValueError("Invalid compressed record") from exc
                if len(body) != expected:
                    raise ValueError("Decompressed record size mismatch")
            for sub_signature, value in _subrecords(body):
                if sub_signature in (b"OFST", b"CLSZ"):
                    tables.append({"record": signature.decode("ascii"), "signature": sub_signature.decode("ascii"),
                                   "form_id": f"{form_id:08X}",
                                   "record_offset": pos, "size": len(value)})
                    tables[-1]["compressed"] = bool(flags & 0x40000)
        if first:
            raise ValueError("Missing Fallout 4 TES4 header")
    return tables


def plugin_skip_reason(path: Path) -> str | None:
    tables = offset_tables(path)
    if any(t["record"] != "WRLD" for t in tables):
        return "Unsupported TES4 world index; only WRLD OFST/CLSZ are stripped"
    return None
