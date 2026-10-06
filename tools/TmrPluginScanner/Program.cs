using System.Collections;
using System.Reflection;
using System.Text.Json;
using Mutagen.Bethesda.Fallout4;
using Mutagen.Bethesda.Plugins;
using Mutagen.Bethesda.Plugins.Binary.Parameters;
using Mutagen.Bethesda.Strings;

internal static class Program
{
    private sealed record Row(string formKey, string record, string path, string kind, string text);

    private static readonly HashSet<string> SkipNames = new(StringComparer.OrdinalIgnoreCase)
    {
        "EditorID","FormKey","Registration","TitleString","Model","Icon","MessageIcon",
        "MaleModel","FemaleModel","FileName","Filename","Path","SourceFile","Archive"
    };

    private static bool Recurse(Type type)
    {
        if (type.IsPrimitive || type.IsEnum || type == typeof(string) || type == typeof(decimal))
            return false;
        var ns = type.Namespace ?? "";
        return ns.StartsWith("Mutagen.Bethesda.Fallout4", StringComparison.Ordinal)
            || ns.StartsWith("Mutagen.Bethesda.Strings", StringComparison.Ordinal)
            || ns.StartsWith("Noggog", StringComparison.Ordinal)
            || typeof(IEnumerable).IsAssignableFrom(type);
    }

    private static bool LooksInternal(string path, string value)
    {
        if (string.IsNullOrWhiteSpace(value)) return true;
        if (value.Length > 20000) return true;
        var lower = path.ToLowerInvariant();
        if (lower.Contains("editorid") || lower.Contains("model") || lower.Contains("filename")
            || lower.Contains("filepath") || lower.Contains("script") || lower.Contains("condition"))
            return true;
        if (value.Contains("\\") && (value.EndsWith(".nif", StringComparison.OrdinalIgnoreCase)
            || value.EndsWith(".dds", StringComparison.OrdinalIgnoreCase)
            || value.EndsWith(".bgsm", StringComparison.OrdinalIgnoreCase)
            || value.EndsWith(".ba2", StringComparison.OrdinalIgnoreCase)))
            return true;
        return false;
    }

    private static void Collect(object? obj, string path, List<Row> rows, string formKey, string record,
        HashSet<object> visited, int depth = 0)
    {
        if (obj is null || depth > 18) return;

        if (obj is TranslatedString ts)
        {
            var value = ts.String;
            if (!string.IsNullOrWhiteSpace(value) && !LooksInternal(path, value))
                rows.Add(new Row(formKey, record, path, "translated", value));
            return;
        }

        var type = obj.GetType();
        if (!type.IsValueType && !visited.Add(obj)) return;

        if (obj is IEnumerable enumerable && type != typeof(byte[]))
        {
            var i = 0;
            foreach (var item in enumerable)
            {
                Collect(item, $"{path}[{i}]", rows, formKey, record, visited, depth + 1);
                i++;
            }
        }

        foreach (var p in type.GetProperties(BindingFlags.Instance | BindingFlags.Public))
        {
            if (!p.CanRead || p.GetIndexParameters().Length != 0 || SkipNames.Contains(p.Name)) continue;
            object? value;
            try { value = p.GetValue(obj); } catch { continue; }
            if (value is null) continue;
            var childPath = string.IsNullOrEmpty(path) ? p.Name : path + "." + p.Name;

            if (value is TranslatedString translated)
            {
                var s = translated.String;
                if (!string.IsNullOrWhiteSpace(s) && !LooksInternal(childPath, s))
                    rows.Add(new Row(formKey, record, childPath, "translated", s));
                continue;
            }

            if (value is string direct)
            {
                // Keep direct strings only for property names that are commonly visible to players.
                var n = p.Name.ToLowerInvariant();
                if ((n.Contains("name") || n.Contains("text") || n.Contains("description")
                    || n.Contains("prompt") || n.Contains("response") || n.Contains("label")
                    || n.Contains("message")) && !LooksInternal(childPath, direct))
                    rows.Add(new Row(formKey, record, childPath, "direct", direct));
                continue;
            }

            if (Recurse(value.GetType()))
                Collect(value, childPath, rows, formKey, record, visited, depth + 1);
        }
    }

    public static int Main(string[] args)
    {
        if (args.Length < 2 || args.Length > 3)
        {
            Console.Error.WriteLine("usage: TmrPluginScanner <plugin> <output-json> [--keys-only]");
            return 2;
        }

        var input = Path.GetFullPath(args[0]);
        var output = Path.GetFullPath(args[1]);
        var keysOnly = args.Length == 3 && args[2] == "--keys-only";
        var modKey = ModKey.FromFileName(Path.GetFileName(input));
        var mod = Fallout4Mod.CreateFromBinary(new ModPath(modKey, input), Fallout4Release.Fallout4,
            new BinaryReadParameters { StringsParam = TranslationEncoding.Read() });

        var rows = new List<Row>();
        if (!keysOnly)
        {
            foreach (var record in mod.EnumerateMajorRecords())
            {
                Collect(record, "", rows, record.FormKey.ToString(), record.GetType().Name,
                    new HashSet<object>(ReferenceEqualityComparer.Instance));
            }
        }

        var unique = rows
            .GroupBy(r => new { r.formKey, r.record, r.path, r.kind, r.text })
            .Select(g => g.First())
            .ToList();

        Directory.CreateDirectory(Path.GetDirectoryName(output)!);
        var allRecords = mod.EnumerateMajorRecords().ToArray();
        File.WriteAllText(output, JsonSerializer.Serialize(new {
            plugin = modKey.FileName,
            masters = mod.ModHeader.MasterReferences.Select(x => x.Master.FileName).ToArray(),
            records = allRecords.Length,
            formKeys = allRecords.Select(x => x.FormKey.ToString()).ToArray(),
            strings = unique.Count,
            rows = unique
        }, new JsonSerializerOptions { WriteIndented = true }));

        Console.WriteLine(JsonSerializer.Serialize(new {
            plugin = modKey.FileName,
            records = mod.EnumerateMajorRecords().Count(),
            strings = unique.Count
        }));
        return 0;
    }
}
