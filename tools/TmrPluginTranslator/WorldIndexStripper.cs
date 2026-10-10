using System.Buffers.Binary;
using System.IO.Compression;
using System.Text;

// Match xTranslator 1.7.3's temporary WRLD index removal policy after serialization.
internal static class WorldIndexStripper
{
    internal sealed record Result(int OFST, int CLSZ, int XXXX);
    private sealed class Counts { public int Ofst, Clsz, Xxxx; }

    public static void ValidateInput(string path) => Rewrite(File.ReadAllBytes(path), new Counts());

    public static Result StripAndVerify(string path)
    {
        var counts = new Counts();
        var bytes = Rewrite(File.ReadAllBytes(path), counts);
        var remaining = new Counts();
        Rewrite(bytes, remaining);
        if (remaining.Ofst != 0 || remaining.Clsz != 0)
            throw new InvalidDataException("WRLD world indexes remain after stripping");
        if (counts.Ofst + counts.Clsz != 0)
        {
            var temporary = path + ".indexes-" + Guid.NewGuid().ToString("N");
            try { File.WriteAllBytes(temporary, bytes); File.Move(temporary, path, true); }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
            var saved = new Counts();
            Rewrite(File.ReadAllBytes(path), saved);
            if (saved.Ofst + saved.Clsz != 0)
                throw new InvalidDataException("Saved WRLD world indexes remain");
        }
        return new Result(counts.Ofst, counts.Clsz, counts.Xxxx);
    }

    private static byte[] Rewrite(byte[] bytes, Counts counts)
    {
        if (bytes.Length < 24 || Encoding.ASCII.GetString(bytes, 0, 4) != "TES4")
            throw new InvalidDataException("Missing TES4 header");
        using var output = new MemoryStream();
        WriteRange(bytes, 0, bytes.Length, output, counts, 0);
        return output.ToArray();
    }

    private static void WriteRange(byte[] bytes, int start, int end, Stream output, Counts counts, int depth)
    {
        if (depth > 64) throw new InvalidDataException("Excessive group nesting");
        for (var pos = start; pos < end;)
        {
            if (end - pos < 24) throw new InvalidDataException("Truncated record/group header");
            var header = bytes.AsSpan(pos, 24).ToArray();
            var signature = Encoding.ASCII.GetString(header, 0, 4);
            var size = checked((int)BinaryPrimitives.ReadUInt32LittleEndian(header.AsSpan(4)));
            if (signature == "GRUP")
            {
                if (size < 24 || size > end - pos) throw new InvalidDataException("Invalid group size");
                using var children = new MemoryStream();
                WriteRange(bytes, pos + 24, pos + size, children, counts, depth + 1);
                BinaryPrimitives.WriteUInt32LittleEndian(header.AsSpan(4), checked((uint)children.Length + 24));
                output.Write(header); children.Position = 0; children.CopyTo(output);
                pos += size;
                continue;
            }
            if (size > end - pos - 24) throw new InvalidDataException("Invalid record size");
            var body = bytes.AsSpan(pos + 24, size).ToArray();
            if (signature is "WRLD" or "TES4")
            {
                var compressed = (BinaryPrimitives.ReadUInt32LittleEndian(header.AsSpan(8)) & 0x40000) != 0;
                var decoded = body;
                if (compressed)
                {
                    if (body.Length < 4 || signature == "TES4") throw new InvalidDataException("Invalid compressed header");
                    using var input = new MemoryStream(body, 4, body.Length - 4);
                    using var zlib = new ZLibStream(input, CompressionMode.Decompress);
                    using var unpacked = new MemoryStream(); zlib.CopyTo(unpacked);
                    decoded = unpacked.ToArray();
                    if (decoded.Length != BinaryPrimitives.ReadUInt32LittleEndian(body))
                        throw new InvalidDataException("Decompressed size mismatch");
                }
                var before = counts.Ofst + counts.Clsz;
                var filtered = Filter(decoded, signature, counts);
                if (counts.Ofst + counts.Clsz != before)
                {
                    body = filtered;
                    if (compressed)
                    {
                        using var packed = new MemoryStream();
                        using (var writer = new BinaryWriter(packed, Encoding.UTF8, true)) writer.Write(filtered.Length);
                        using (var zlib = new ZLibStream(packed, CompressionLevel.Optimal, true)) zlib.Write(filtered);
                        body = packed.ToArray();
                    }
                    BinaryPrimitives.WriteUInt32LittleEndian(header.AsSpan(4), checked((uint)body.Length));
                }
            }
            output.Write(header); output.Write(body);
            pos += 24 + size;
        }
    }

    private static byte[] Filter(byte[] body, string record, Counts counts)
    {
        using var output = new MemoryStream();
        for (var pos = 0; pos < body.Length;)
        {
            var start = pos;
            if (body.Length - pos < 6) throw new InvalidDataException("Truncated subrecord");
            var sig = Encoding.ASCII.GetString(body, pos, 4);
            var length = (uint)BinaryPrimitives.ReadUInt16LittleEndian(body.AsSpan(pos + 4));
            pos += 6;
            var extended = sig == "XXXX";
            if (extended)
            {
                if (length != 4 || body.Length - pos < 10) throw new InvalidDataException("Invalid XXXX marker");
                length = BinaryPrimitives.ReadUInt32LittleEndian(body.AsSpan(pos)); pos += 4;
                sig = Encoding.ASCII.GetString(body, pos, 4); pos += 6;
                if (sig == "XXXX") throw new InvalidDataException("Repeated XXXX marker");
            }
            if (length > body.Length - pos) throw new InvalidDataException("Invalid subrecord size");
            pos += checked((int)length);
            if (sig is "OFST" or "CLSZ")
            {
                if (record != "WRLD") throw new NotSupportedException("TES4 world indexes are unsupported");
                if (sig == "OFST") counts.Ofst++; else counts.Clsz++;
                if (extended) counts.Xxxx++;
            }
            else output.Write(body, start, pos - start);
        }
        return output.ToArray();
    }
}
