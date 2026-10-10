using System.Buffers.Binary;
using System.IO.Compression;
using System.Text;

// Serialized copies are used only to identify approved text edits. All emitted
// records, headers and unrelated subrecords come from the original file.
internal static class OriginalTextWriter
{
    internal sealed record Pair(string Record, string Field, string Source, string Dest);
    private sealed record Field(string Signature, byte[] Value, byte[] Raw);
    private sealed record Edit(string Signature, int Index, byte[] Before, byte[] After);

    public static int Write(string original, string baseline, string translated,
        IEnumerable<Pair> pairs, int expectedChanges, string output)
    {
        var allowed = pairs.ToHashSet();
        var before = Records(File.ReadAllBytes(baseline));
        var after = Records(File.ReadAllBytes(translated));
        if (!before.Keys.ToHashSet().SetEquals(after.Keys))
            throw new InvalidDataException("Serialized record identities changed");
        var edits = new Dictionary<(string, uint), List<Edit>>();
        foreach (var (key, oldBody) in before)
        {
            if (oldBody.SequenceEqual(after[key])) continue;
            var oldFields = Fields(oldBody);
            var newFields = Fields(after[key]);
            if (oldFields.Count != newFields.Count)
                throw new InvalidDataException($"Serialized field layout changed: {key}");
            var occurrences = new Dictionary<string, int>();
            for (var i = 0; i < oldFields.Count; i++)
            {
                var a = oldFields[i]; var b = newFields[i];
                if (a.Signature != b.Signature)
                    throw new InvalidDataException($"Serialized field order changed: {key}");
                var index = occurrences.GetValueOrDefault(a.Signature);
                occurrences[a.Signature] = index + 1;
                if (a.Value.SequenceEqual(b.Value)) continue;
                // Generic object matching can also change developer notes containing
                // dialogue. Only dictionary-approved display fields may be emitted.
                if (!allowed.Any(x => x.Record == key.Item1 && x.Field == a.Signature))
                    continue;
                if (!allowed.Contains(new Pair(key.Item1, a.Signature, Text(a.Value), Text(b.Value))))
                    throw new InvalidDataException($"Unapproved display text change: {key}:{a.Signature}");
                if (!edits.TryGetValue(key, out var list)) edits[key] = list = new();
                list.Add(new Edit(a.Signature, index, a.Value, b.Value));
            }
        }
        var selectedChanges = edits.Values.Sum(x => x.Count);
        if (selectedChanges == 0 || selectedChanges > expectedChanges)
            throw new InvalidDataException("No safe display edits, or more edits than matched translations");
        var source = File.ReadAllBytes(original);
        using var result = new MemoryStream();
        var applied = 0;
        Rewrite(source, 0, source.Length, result, edits, ref applied, 0);
        if (applied != selectedChanges)
            throw new InvalidDataException("Not every approved edit matched the original file");
        File.WriteAllBytes(output, result.ToArray());
        return applied;
    }

    private static string Text(byte[] value)
    {
        if (value.Length == 0 || value[^1] != 0 || value.AsSpan(0, value.Length - 1).Contains((byte)0))
            throw new InvalidDataException("Changed field is not a complete null-terminated string");
        try { return new UTF8Encoding(false, true).GetString(value, 0, value.Length - 1); }
        catch (DecoderFallbackException) { return Encoding.GetEncoding(1252).GetString(value, 0, value.Length - 1); }
    }

    private static byte[] Decode(byte[] body, uint flags)
    {
        if ((flags & 0x40000) == 0) return body;
        if (body.Length < 4) throw new InvalidDataException("Truncated compressed record");
        using var input = new MemoryStream(body, 4, body.Length - 4);
        using var zlib = new ZLibStream(input, CompressionMode.Decompress);
        using var decoded = new MemoryStream(); zlib.CopyTo(decoded);
        if (decoded.Length != BinaryPrimitives.ReadUInt32LittleEndian(body))
            throw new InvalidDataException("Decompressed length mismatch");
        return decoded.ToArray();
    }

    private static Dictionary<(string, uint), byte[]> Records(byte[] data)
    {
        var result = new Dictionary<(string, uint), byte[]>();
        for (var pos = 0; pos < data.Length;)
        {
            if (data.Length - pos < 24) throw new InvalidDataException("Truncated header");
            var sig = Encoding.ASCII.GetString(data, pos, 4);
            var size = checked((int)BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(pos + 4)));
            if (sig == "GRUP") { pos += 24; continue; }
            if (size > data.Length - pos - 24) throw new InvalidDataException("Invalid record size");
            var form = BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(pos + 12));
            var flags = BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(pos + 8));
            result.Add((sig, form), Decode(data.AsSpan(pos + 24, size).ToArray(), flags));
            pos += 24 + size;
        }
        return result;
    }

    private static List<Field> Fields(byte[] body)
    {
        var fields = new List<Field>();
        for (var pos = 0; pos < body.Length;)
        {
            var start = pos;
            if (body.Length - pos < 6) throw new InvalidDataException("Truncated subrecord");
            var sig = Encoding.ASCII.GetString(body, pos, 4);
            var length = (uint)BinaryPrimitives.ReadUInt16LittleEndian(body.AsSpan(pos + 4));
            pos += 6;
            if (sig == "XXXX")
            {
                if (length != 4 || body.Length - pos < 10) throw new InvalidDataException("Invalid XXXX");
                length = BinaryPrimitives.ReadUInt32LittleEndian(body.AsSpan(pos)); pos += 4;
                sig = Encoding.ASCII.GetString(body, pos, 4); pos += 6;
                if (sig == "XXXX") throw new InvalidDataException("Repeated XXXX");
            }
            if (length > body.Length - pos) throw new InvalidDataException("Invalid subrecord size");
            var value = body.AsSpan(pos, checked((int)length)).ToArray();
            pos += checked((int)length);
            fields.Add(new Field(sig, value, body.AsSpan(start, pos - start).ToArray()));
        }
        return fields;
    }

    private static void Rewrite(byte[] data, int start, int end, Stream output,
        Dictionary<(string, uint), List<Edit>> edits, ref int applied, int depth)
    {
        if (depth > 64) throw new InvalidDataException("Excessive group nesting");
        for (var pos = start; pos < end;)
        {
            if (end - pos < 24) throw new InvalidDataException("Truncated record header");
            var header = data.AsSpan(pos, 24).ToArray();
            var sig = Encoding.ASCII.GetString(header, 0, 4);
            var size = checked((int)BinaryPrimitives.ReadUInt32LittleEndian(header.AsSpan(4)));
            if (sig == "GRUP")
            {
                if (size < 24 || size > end - pos) throw new InvalidDataException("Invalid group size");
                using var children = new MemoryStream();
                Rewrite(data, pos + 24, pos + size, children, edits, ref applied, depth + 1);
                BinaryPrimitives.WriteUInt32LittleEndian(header.AsSpan(4), checked((uint)children.Length + 24));
                output.Write(header); children.Position = 0; children.CopyTo(output);
                pos += size; continue;
            }
            if (size > end - pos - 24) throw new InvalidDataException("Invalid record size");
            var body = data.AsSpan(pos + 24, size).ToArray();
            var form = BinaryPrimitives.ReadUInt32LittleEndian(header.AsSpan(12));
            if (edits.TryGetValue((sig, form), out var changes))
            {
                var flags = BinaryPrimitives.ReadUInt32LittleEndian(header.AsSpan(8));
                if ((flags & 0x80) != 0 && sig == "TES4")
                    throw new InvalidDataException("Localized plugin header cannot be edited");
                var fields = Fields(Decode(body, flags));
                using var changed = new MemoryStream();
                var occurrences = new Dictionary<string, int>();
                foreach (var field in fields)
                {
                    var index = occurrences.GetValueOrDefault(field.Signature);
                    occurrences[field.Signature] = index + 1;
                    var edit = changes.SingleOrDefault(x => x.Signature == field.Signature && x.Index == index);
                    if (edit is null) { changed.Write(field.Raw); continue; }
                    if (Text(field.Value) != Text(edit.Before))
                        throw new InvalidDataException($"Original text does not match: {sig}:{form:X8}:{field.Signature}");
                    using var writer = new BinaryWriter(changed, Encoding.UTF8, true);
                    if (edit.After.Length > ushort.MaxValue || Encoding.ASCII.GetString(field.Raw, 0, 4) == "XXXX")
                    {
                        writer.Write(Encoding.ASCII.GetBytes("XXXX")); writer.Write((ushort)4);
                        writer.Write(edit.After.Length);
                        writer.Write(Encoding.ASCII.GetBytes(field.Signature)); writer.Write((ushort)0);
                    }
                    else
                    {
                        writer.Write(Encoding.ASCII.GetBytes(field.Signature));
                        writer.Write((ushort)edit.After.Length);
                    }
                    writer.Write(edit.After); applied++;
                }
                body = changed.ToArray();
                if ((flags & 0x40000) != 0)
                {
                    using var packed = new MemoryStream();
                    using (var writer = new BinaryWriter(packed, Encoding.UTF8, true)) writer.Write(body.Length);
                    using (var zlib = new ZLibStream(packed, CompressionLevel.Optimal, true)) zlib.Write(body);
                    body = packed.ToArray();
                }
                BinaryPrimitives.WriteUInt32LittleEndian(header.AsSpan(4), checked((uint)body.Length));
            }
            output.Write(header); output.Write(body); pos += 24 + size;
        }
    }
}
