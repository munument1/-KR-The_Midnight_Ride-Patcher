using System.Collections;
using System.Reflection;
using System.Text.Json;
using System.Text;
using Mutagen.Bethesda.Plugins.Binary.Parameters;
using Mutagen.Bethesda.Fallout4;
using Mutagen.Bethesda.Plugins;
using Mutagen.Bethesda.Strings;

internal static class Program
{
    private sealed record MappingRow(
        string owner,
        string id,
        string record,
        string field,
        int rec_id,
        int rec_id_max,
        uint string_id,
        string source,
        string dest,
        string? origin = null
    );

    private sealed record MappingFile(
        int schema_version,
        string? sst_format,
        string? source_file,
        string[]? plugins,
        string target,
        MappingRow[] mappings,
        MappingRow[]? fallback_mappings
    );

    private sealed record FallbackBank(
        int schema_version,
        MappingRow[] mappings
    );

    private sealed class ApplyStats
    {
        public int Changed { get; set; }
        public int RecordsConsidered { get; set; }
        public int MissingRecords { get; set; }
        public int UnmatchedStrings { get; set; }
        public int AmbiguousStrings { get; set; }
        public int ZeroFormSkipped { get; set; }

        public void Add(ApplyStats other)
        {
            Changed += other.Changed;
            RecordsConsidered += other.RecordsConsidered;
            MissingRecords += other.MissingRecords;
            UnmatchedStrings += other.UnmatchedStrings;
            AmbiguousStrings += other.AmbiguousStrings;
            ZeroFormSkipped += other.ZeroFormSkipped;
        }
    }

    private static readonly Dictionary<Type, PropertyInfo[]> PropertyCache = new();

    private static bool IsFallout4Object(Type type)
    {
        var ns = type.Namespace ?? "";
        return ns.StartsWith("Mutagen.Bethesda.Fallout4", StringComparison.Ordinal)
            || ns.StartsWith("Mutagen.Bethesda.Strings", StringComparison.Ordinal);
    }

    private static bool ShouldRecurse(Type type)
    {
        if (type.IsPrimitive || type.IsEnum || type == typeof(string) || type == typeof(decimal))
            return false;
        return IsFallout4Object(type) || typeof(IEnumerable).IsAssignableFrom(type);
    }

    private static PropertyInfo[] GetReadableProperties(Type type)
    {
        lock (PropertyCache)
        {
            if (PropertyCache.TryGetValue(type, out var cached))
                return cached;

            var props = type
                .GetProperties(BindingFlags.Instance | BindingFlags.Public)
                .Where(p => p.CanRead
                    && p.GetIndexParameters().Length == 0
                    && p.Name is not ("EditorID" or "TitleString" or "FormKey" or "Registration"))
                .ToArray();
            PropertyCache[type] = props;
            return props;
        }
    }

    private static int ReplaceStrings(
        object? obj,
        IReadOnlyDictionary<string, string> replacements,
        Dictionary<string, int> hits,
        HashSet<object> visited,
        int depth = 0)
    {
        if (obj is null || depth > 20 || obj is string) return 0;

        if (obj is TranslatedString translated)
        {
            var value = translated.String;
            if (value is not null && replacements.TryGetValue(value, out var dest) && dest != value)
            {
                translated.String = dest;
                hits[value] = hits.GetValueOrDefault(value) + 1;
                return 1;
            }
            return 0;
        }

        var type = obj.GetType();
        if (!type.IsValueType && !visited.Add(obj)) return 0;

        var changed = 0;

        if (obj is IList list)
        {
            for (var i = 0; i < list.Count; i++)
            {
                var item = list[i];
                if (item is string s && replacements.TryGetValue(s, out var dest) && dest != s && !list.IsReadOnly)
                {
                    list[i] = dest;
                    hits[s] = hits.GetValueOrDefault(s) + 1;
                    changed++;
                }
                else
                {
                    changed += ReplaceStrings(item, replacements, hits, visited, depth + 1);
                }
            }
            return changed;
        }

        if (obj is IEnumerable enumerable && type != typeof(byte[]))
        {
            foreach (var item in enumerable)
                changed += ReplaceStrings(item, replacements, hits, visited, depth + 1);
            return changed;
        }

        // FormLinks, asset links and other Noggog helper objects do not own
        // translatable Fallout 4 fields. Do not walk their internal graphs.
        if (!IsFallout4Object(type))
            return changed;

        foreach (var property in GetReadableProperties(type))
        {

            object? value;
            try { value = property.GetValue(obj); }
            catch { continue; }
            if (value is null) continue;

            if (property.PropertyType == typeof(string))
            {
                if (!property.CanWrite) continue;
                var s = (string)value;
                if (replacements.TryGetValue(s, out var dest) && dest != s)
                {
                    try
                    {
                        property.SetValue(obj, dest);
                        hits[s] = hits.GetValueOrDefault(s) + 1;
                        changed++;
                    }
                    catch { }
                }
                continue;
            }

            if (value is TranslatedString ts)
            {
                var s = ts.String;
                if (s is not null && replacements.TryGetValue(s, out var dest) && dest != s)
                {
                    ts.String = dest;
                    hits[s] = hits.GetValueOrDefault(s) + 1;
                    changed++;
                }
                continue;
            }

            if (ShouldRecurse(value.GetType()))
                changed += ReplaceStrings(value, replacements, hits, visited, depth + 1);
        }

        return changed;
    }

    private static void CountStrings(
        object? obj,
        IReadOnlySet<string> wanted,
        Dictionary<string, int> counts,
        HashSet<object> visited,
        int depth = 0)
    {
        if (obj is null || depth > 20) return;

        if (obj is string direct)
        {
            if (wanted.Contains(direct))
                counts[direct] = counts.GetValueOrDefault(direct) + 1;
            return;
        }

        if (obj is TranslatedString translated)
        {
            var value = translated.String;
            if (value is not null && wanted.Contains(value))
                counts[value] = counts.GetValueOrDefault(value) + 1;
            return;
        }

        var type = obj.GetType();
        if (!type.IsValueType && !visited.Add(obj)) return;

        if (obj is IEnumerable enumerable && type != typeof(byte[]))
        {
            foreach (var item in enumerable)
                CountStrings(item, wanted, counts, visited, depth + 1);
            return;
        }

        if (!IsFallout4Object(type))
            return;

        foreach (var property in GetReadableProperties(type))
        {
            object? value;
            try { value = property.GetValue(obj); }
            catch { continue; }
            if (value is null) continue;

            if (value is string text)
            {
                if (wanted.Contains(text))
                    counts[text] = counts.GetValueOrDefault(text) + 1;
                continue;
            }

            if (value is TranslatedString ts)
            {
                var translatedText = ts.String;
                if (translatedText is not null && wanted.Contains(translatedText))
                    counts[translatedText] = counts.GetValueOrDefault(translatedText) + 1;
                continue;
            }

            if (ShouldRecurse(value.GetType()))
                CountStrings(value, wanted, counts, visited, depth + 1);
        }
    }

    private static bool TryResolveIndexedTarget(
        Mutagen.Bethesda.Plugins.Records.IMajorRecord record,
        MappingRow row,
        out TranslatedString? target)
    {
        target = null;

        if (record is Quest quest)
        {
            switch (row.field)
            {
                case "FULL":
                    target = quest.Name;
                    return true;
                case "NNAM":
                    if (row.rec_id >= 0 && row.rec_id < quest.Objectives.Count)
                        target = quest.Objectives[row.rec_id].DisplayText;
                    return true;
                case "CNAM":
                {
                    var index = 0;
                    foreach (var stage in quest.Stages)
                    {
                        foreach (var log in stage.LogEntries)
                        {
                            if (log.Entry is null) continue;
                            if (index == row.rec_id)
                            {
                                target = log.Entry;
                                return true;
                            }
                            index++;
                        }
                    }
                    return true;
                }
            }
        }

        if (record is InstanceNamingRules namingRules && row.field == "WNAM")
        {
            var index = 0;
            foreach (var ruleSet in namingRules.RuleSets)
            {
                foreach (var nameRule in ruleSet.Names)
                {
                    if (index == row.rec_id)
                    {
                        target = nameRule.Name;
                        return true;
                    }
                    index++;
                }
            }
            return true;
        }

        if (record is Terminal terminal)
        {
            switch (row.field)
            {
                case "FULL":
                    target = terminal.Name;
                    return true;
                case "NAM0":
                    target = terminal.HeaderText;
                    return true;
                case "WNAM":
                    target = terminal.WelcomeText;
                    return true;
                case "BTXT":
                    if (row.rec_id >= 0 && row.rec_id < terminal.BodyTexts.Count)
                        target = terminal.BodyTexts[row.rec_id].Text;
                    return true;
                case "ITXT":
                    if (row.rec_id >= 0 && row.rec_id < terminal.MenuItems.Count)
                        target = terminal.MenuItems[row.rec_id].ItemText;
                    return true;
                case "UNAM":
                {
                    var index = 0;
                    foreach (var item in terminal.MenuItems)
                    {
                        if (item.DisplayText is null) continue;
                        if (index == row.rec_id)
                        {
                            target = item.DisplayText;
                            return true;
                        }
                        index++;
                    }
                    return true;
                }
                case "RNAM":
                {
                    var index = 0;
                    foreach (var item in terminal.MenuItems)
                    {
                        if (item.ResponseText is null) continue;
                        if (index == row.rec_id)
                        {
                            target = item.ResponseText;
                            return true;
                        }
                        index++;
                    }
                    return true;
                }
            }
        }

        return false;
    }

    private static MappingRow[] ApplyIndexedRows(
        Mutagen.Bethesda.Plugins.Records.IMajorRecord record,
        MappingRow[] rows,
        bool strict,
        ApplyStats stats,
        List<object> strictUnmatched)
    {
        var generic = new List<MappingRow>();

        foreach (var row in rows)
        {
            if (!TryResolveIndexedTarget(record, row, out var target))
            {
                generic.Add(row);
                continue;
            }

            if (target is null)
            {
                stats.UnmatchedStrings++;
                if (strict)
                {
                    strictUnmatched.Add(new {
                        formKey = record.FormKey.ToString(),
                        record = row.record,
                        field = row.field,
                        rec_id = row.rec_id,
                        source = row.source,
                        reason = "indexed target missing"
                    });
                }
                continue;
            }

            var current = target.String;
            if (!string.Equals(current, row.source, StringComparison.Ordinal))
            {
                // A duplicate mapping may already have set the same destination.
                if (string.Equals(current, row.dest, StringComparison.Ordinal))
                    continue;

                stats.UnmatchedStrings++;
                if (strict)
                {
                    strictUnmatched.Add(new {
                        formKey = record.FormKey.ToString(),
                        record = row.record,
                        field = row.field,
                        rec_id = row.rec_id,
                        source = row.source,
                        current,
                        reason = "indexed source mismatch"
                    });
                }
                continue;
            }

            if (!string.Equals(current, row.dest, StringComparison.Ordinal))
            {
                target.String = row.dest;
                stats.Changed++;
            }
        }

        return generic.ToArray();
    }

    private static Dictionary<string, string> BuildReplacements(
        IEnumerable<MappingRow> rows,
        bool strict,
        FormKey formKey,
        ApplyStats stats,
        List<object> strictAmbiguous)
    {
        var replacements = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var sourceGroup in rows.GroupBy(row => row.source, StringComparer.Ordinal))
        {
            var destinations = sourceGroup
                .Select(x => x.dest)
                .Distinct(StringComparer.Ordinal)
                .ToArray();

            if (destinations.Length != 1)
            {
                stats.AmbiguousStrings++;
                if (strict)
                {
                    strictAmbiguous.Add(new {
                        formKey = formKey.ToString(),
                        source = sourceGroup.Key,
                        destinations
                    });
                }
                continue;
            }
            replacements[sourceGroup.Key] = destinations[0];
        }
        return replacements;
    }

    private static ApplyStats ApplyZeroDirectRows(
        MappingRow[] rows,
        IReadOnlyDictionary<FormKey, Mutagen.Bethesda.Plugins.Records.IMajorRecord> records,
        List<string> strictMissingRecords,
        List<object> strictUnmatched,
        List<object> strictAmbiguous)
    {
        var stats = new ApplyStats();
        foreach (var group in rows.GroupBy(
            row => $"{row.owner}:{row.record}",
            StringComparer.OrdinalIgnoreCase))
        {
            var first = group.First();
            var wantedSources = group.Select(x => x.source).ToHashSet(StringComparer.Ordinal);
            var candidates = new List<Mutagen.Bethesda.Plugins.Records.IMajorRecord>();

            foreach (var candidate in records.Values)
            {
                var counts = wantedSources.ToDictionary(x => x, _ => 0, StringComparer.Ordinal);
                CountStrings(
                    candidate,
                    wantedSources,
                    counts,
                    new HashSet<object>(ReferenceEqualityComparer.Instance));
                if (counts.Values.Any(x => x > 0))
                {
                    candidates.Add(candidate);
                    // FormID 0 has no stable identity. Once two candidates exist,
                    // the mapping is inherently ambiguous and further scanning is wasted.
                    if (candidates.Count > 1) break;
                }
            }

            if (candidates.Count != 1)
            {
                stats.ZeroFormSkipped += group.Count();
                stats.UnmatchedStrings += group.Count();
                continue;
            }

            var record = candidates[0];
            stats.RecordsConsidered++;
            var replacements = BuildReplacements(group, true, record.FormKey, stats, strictAmbiguous);
            var hits = replacements.Keys.ToDictionary(x => x, _ => 0, StringComparer.Ordinal);
            ReplaceStrings(
                record,
                replacements,
                hits,
                new HashSet<object>(ReferenceEqualityComparer.Instance));

            foreach (var pair in hits)
            {
                stats.Changed += pair.Value;
                if (pair.Value == 0)
                {
                    stats.UnmatchedStrings++;
                    strictUnmatched.Add(new {
                        formKey = record.FormKey.ToString(),
                        record = first.record,
                        source = pair.Key
                    });
                }
            }
        }
        return stats;
    }

    private static (ApplyStats Direct, ApplyStats Fallback) ApplyCombinedNormalRows(
        MappingRow[] directRows,
        MappingRow[] fallbackRows,
        IReadOnlyDictionary<FormKey, Mutagen.Bethesda.Plugins.Records.IMajorRecord> records,
        List<string> strictMissingRecords,
        List<object> strictUnmatched,
        List<object> strictAmbiguous)
    {
        var directStats = new ApplyStats();
        var fallbackStats = new ApplyStats();

        var directByRecord = directRows
            .GroupBy(row => $"{row.id}:{row.owner}", StringComparer.OrdinalIgnoreCase)
            .ToDictionary(g => g.Key, g => g.ToArray(), StringComparer.OrdinalIgnoreCase);
        var fallbackByRecord = fallbackRows
            .GroupBy(row => $"{row.id}:{row.owner}", StringComparer.OrdinalIgnoreCase)
            .ToDictionary(g => g.Key, g => g.ToArray(), StringComparer.OrdinalIgnoreCase);

        var recordKeys = new HashSet<string>(directByRecord.Keys, StringComparer.OrdinalIgnoreCase);
        recordKeys.UnionWith(fallbackByRecord.Keys);

        foreach (var recordKey in recordKeys)
        {
            directByRecord.TryGetValue(recordKey, out var directGroup);
            fallbackByRecord.TryGetValue(recordKey, out var fallbackGroup);
            directGroup ??= Array.Empty<MappingRow>();
            fallbackGroup ??= Array.Empty<MappingRow>();

            var first = directGroup.FirstOrDefault() ?? fallbackGroup[0];
            var formKey = FormKey.Factory($"{first.id}:{first.owner}");

            if (!records.TryGetValue(formKey, out var record))
            {
                // xTranslator dictionaries commonly retain entries for records
                // that no longer exist in a newer plugin revision. Treat these
                // as unused dictionary rows rather than a hard failure.
                if (directGroup.Length > 0)
                    directStats.MissingRecords++;
                if (fallbackGroup.Length > 0)
                    fallbackStats.MissingRecords++;
                continue;
            }

            if (directGroup.Length > 0) directStats.RecordsConsidered++;
            if (fallbackGroup.Length > 0) fallbackStats.RecordsConsidered++;

            // QUST/TERM have repeated field arrays where identical English text can
            // legitimately map to different translations. Match those exactly by
            // xTranslator's REC:FIELD + rec_id semantics before generic source matching.
            var directGeneric = ApplyIndexedRows(
                record, directGroup, true, directStats, strictUnmatched);
            var fallbackGeneric = ApplyIndexedRows(
                record, fallbackGroup, false, fallbackStats, strictUnmatched);

            var directReplacements = BuildReplacements(
                directGeneric, true, formKey, directStats, strictAmbiguous);
            var fallbackReplacements = BuildReplacements(
                fallbackGeneric, false, formKey, fallbackStats, strictAmbiguous);

            // Mod-specific SST always wins for an identical source string.
            foreach (var source in directReplacements.Keys)
                fallbackReplacements.Remove(source);

            var combined = new Dictionary<string, string>(directReplacements, StringComparer.Ordinal);
            foreach (var pair in fallbackReplacements)
                combined[pair.Key] = pair.Value;

            if (combined.Count == 0) continue;

            var hits = combined.Keys.ToDictionary(x => x, _ => 0, StringComparer.Ordinal);
            ReplaceStrings(
                record,
                combined,
                hits,
                new HashSet<object>(ReferenceEqualityComparer.Instance));

            foreach (var source in directReplacements.Keys)
            {
                var count = hits[source];
                directStats.Changed += count;
                if (count == 0)
                {
                    directStats.UnmatchedStrings++;
                    strictUnmatched.Add(new {
                        formKey = formKey.ToString(),
                        record = first.record,
                        source
                    });
                }
            }

            foreach (var source in fallbackReplacements.Keys)
            {
                var count = hits[source];
                fallbackStats.Changed += count;
                if (count == 0)
                    fallbackStats.UnmatchedStrings++;
            }
        }

        return (directStats, fallbackStats);
    }

    public static async Task<int> Main(string[] args)
    {
        if (args.Length is not (3 or 4))
        {
            Console.Error.WriteLine(
                "usage: TmrPluginTranslator <input-plugin> <mapping-json> <output-plugin>\n" +
                "   or: TmrPluginTranslator <input-plugin> <direct-map-or-dash> <fallback-bank> <output-plugin>");
            return 2;
        }

        var input = Path.GetFullPath(args[0]);
        var directPathArg = args[1];
        var fallbackPath = args.Length == 4 ? Path.GetFullPath(args[2]) : null;
        var output = Path.GetFullPath(args.Length == 4 ? args[3] : args[2]);
        if (string.Equals(input, output, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Input and output paths must differ");

        try { WorldIndexStripper.ValidateInput(input); }
        catch (NotSupportedException exc)
        {
            Console.WriteLine(JsonSerializer.Serialize(new {
                status = "skipped_unsafe_offsets",
                input,
                changed = 0,
                reason = exc.Message
            }));
            return 0;
        }

        MappingFile mapping;
        if (directPathArg == "-")
        {
            var inferred = ModKey.FromFileName(Path.GetFileName(input));
            mapping = new MappingFile(1, null, null, null, inferred.FileName, Array.Empty<MappingRow>(), null);
        }
        else
        {
            var mapPath = Path.GetFullPath(directPathArg);
            mapping = JsonSerializer.Deserialize<MappingFile>(
                File.ReadAllText(mapPath),
                new JsonSerializerOptions { PropertyNameCaseInsensitive = true })
                ?? throw new InvalidDataException("Could not parse mapping JSON");
        }

        if (mapping.schema_version != 1)
            throw new InvalidDataException($"Unsupported mapping schema {mapping.schema_version}");

        var modKey = ModKey.FromFileName(Path.GetFileName(input));
        if (!string.Equals(modKey.FileName, mapping.target, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException($"Mapping target {mapping.target} does not match {modKey}");

        // Localized fields contain string-table IDs rather than inline text.
        // Do not turn these into inline strings or reuse an old serialized payload.
        using (var stream = File.OpenRead(input))
        using (var reader = new BinaryReader(stream))
        {
            stream.Position = 8;
            if ((reader.ReadUInt32() & 0x80) != 0)
            {
                Console.WriteLine(JsonSerializer.Serialize(new {
                    status = "skipped_localized_strings",
                    input,
                    changed = 0,
                    reason = "Localized string-table plugins require separate validated sidecar translation; original preserved."
                }));
                return 0;
            }
        }

        var utf8Read = new BinaryReadParameters {
            StringsParam = new StringsReadParameters {
                NonLocalizedEncodingOverride = new MutagenEncodingWrapper(Encoding.UTF8)
            }
        };
        Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
        var sourceRead = new BinaryReadParameters {
            StringsParam = new StringsReadParameters {
                NonLocalizedEncodingOverride = new MutagenEncodingFallbackWrapper(
                    new MutagenEncodingWrapper(new UTF8Encoding(false, true)),
                    new MutagenEncodingWrapper(Encoding.GetEncoding(1252)))
            }
        };
        var mod = Fallout4Mod.CreateFromBinary(
            new ModPath(modKey, input),
            Fallout4Release.Fallout4, sourceRead);

        var inputMasters = mod.ModHeader.MasterReferences.Select(x => x.Master).ToArray();
        var records = mod.EnumerateMajorRecords().ToDictionary(x => x.FormKey);
        var eligibleRecords = records.Where(x => !TranslationSafety.IsProtected(x.Value))
            .ToDictionary(x => x.Key, x => x.Value);
        var protectedRecords = records.Count - eligibleRecords.Count;
        var missingRecords = new List<string>();
        var unmatched = new List<object>();
        var ambiguous = new List<object>();

        var directRows = mapping.mappings ?? Array.Empty<MappingRow>();
        MappingRow[] fallbackRows;
        if (fallbackPath is null)
        {
            fallbackRows = mapping.fallback_mappings ?? Array.Empty<MappingRow>();
        }
        else
        {
            var bank = JsonSerializer.Deserialize<FallbackBank>(
                File.ReadAllText(fallbackPath),
                new JsonSerializerOptions { PropertyNameCaseInsensitive = true })
                ?? throw new InvalidDataException("Could not parse fallback bank");
            if (bank.schema_version != 1)
                throw new InvalidDataException($"Unsupported fallback schema {bank.schema_version}");

            // Filter the global bank to records that actually exist in this plugin
            // before grouping. This keeps update/new-plugin fallback fast.
            fallbackRows = bank.mappings.Where(row =>
            {
                if (row.id == "000000") return false;
                try
                {
                    return records.ContainsKey(FormKey.Factory($"{row.id}:{row.owner}"));
                }
                catch
                {
                    return false;
                }
            }).ToArray();
        }

        var zeroDirect = directRows.Where(x => x.id == "000000").ToArray();
        var normalDirect = directRows.Where(x => x.id != "000000").ToArray();
        var normalFallback = fallbackRows.Where(x => x.id != "000000").ToArray();

        var zeroDirectStats = ApplyZeroDirectRows(
            zeroDirect, eligibleRecords, missingRecords, unmatched, ambiguous);

        var combinedStats = ApplyCombinedNormalRows(
            normalDirect,
            normalFallback,
            eligibleRecords,
            missingRecords,
            unmatched,
            ambiguous);

        combinedStats.Direct.Add(zeroDirectStats);
        combinedStats.Fallback.ZeroFormSkipped += fallbackRows.Count(x => x.id == "000000");

        var directStats = combinedStats.Direct;
        var fallbackStats = combinedStats.Fallback;

        // xTranslator dictionaries may retain old/unused rows. Missing records and
        // source mismatches are therefore audit data, not fatal errors. Ambiguous
        // mappings remain fatal because choosing one could apply the wrong text.
        if (ambiguous.Count != 0)
            throw new InvalidDataException($"Ambiguous direct mappings: {JsonSerializer.Serialize(ambiguous)}");

        var totalChanged = directStats.Changed + fallbackStats.Changed;
        if (totalChanged == 0)
        {
            Console.WriteLine(JsonSerializer.Serialize(new {
                status = "no_changes",
                plugin_policy_version = TranslationSafety.PolicyVersion,
                protected_records = protectedRecords,
                input,
                target = mapping.target,
                records = records.Count,
                direct_mappings = directRows.Length,
                fallback_mappings = fallbackRows.Length,
                direct = directStats,
                fallback = fallbackStats,
                unused_direct_records = missingRecords.Count,
                unmatched_direct = unmatched.Count,
                unmatched_direct_examples = unmatched.Take(20).ToArray()
            }));
            return 0;
        }

        Directory.CreateDirectory(Path.GetDirectoryName(output)!);
        if (File.Exists(output)) File.Delete(output);

        var scratch = Path.Combine(Path.GetDirectoryName(output)!, ".serialize-" + Guid.NewGuid().ToString("N"));
        var baselinePath = Path.Combine(scratch, "baseline", Path.GetFileName(input));
        var translatedPath = Path.Combine(scratch, "translated", Path.GetFileName(input));
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(baselinePath)!);
            Directory.CreateDirectory(Path.GetDirectoryName(translatedPath)!);
            var originalMod = Fallout4Mod.CreateFromBinary(
                new ModPath(modKey, input), Fallout4Release.Fallout4, sourceRead);
            await originalMod.BeginWrite.ToPath(baselinePath)
                .WithLoadOrderFromHeaderMasters().WithNoDataFolder().WithUtf8Encoding()
                .WithExplicitOverridingMasterList(inputMasters).WithMastersListOrdering(inputMasters)
                .NoMastersListContentCheck().WriteAsync();
            await mod.BeginWrite.ToPath(translatedPath)
                .WithLoadOrderFromHeaderMasters().WithNoDataFolder().WithUtf8Encoding()
                .WithExplicitOverridingMasterList(inputMasters).WithMastersListOrdering(inputMasters)
                .NoMastersListContentCheck().WriteAsync();
            totalChanged = OriginalTextWriter.Write(input, baselinePath, translatedPath,
                directRows.Concat(fallbackRows).Select(x =>
                    new OriginalTextWriter.Pair(x.record, x.field, x.source, x.dest)),
                totalChanged, output);
        }
        finally
        {
            if (File.Exists(baselinePath)) File.Delete(baselinePath);
            if (File.Exists(translatedPath)) File.Delete(translatedPath);
            Directory.Delete(scratch, true);
        }

        WorldIndexStripper.Result strippedIndexes;
        try { strippedIndexes = WorldIndexStripper.StripAndVerify(output); }
        catch
        {
            File.Delete(output);
            throw;
        }

        var verify = Fallout4Mod.CreateFromBinary(
            new ModPath(modKey, output),
            Fallout4Release.Fallout4, utf8Read);

        var verifyMasters = verify.ModHeader.MasterReferences.Select(x => x.Master).ToArray();
        if (!inputMasters.SequenceEqual(verifyMasters))
            throw new InvalidDataException("Master list/order changed during translation");

        var verifyRecords = verify.EnumerateMajorRecords().ToDictionary(x => x.FormKey);
        if (verifyRecords.Count != records.Count)
            throw new InvalidDataException(
                $"Fresh read record count mismatch: {records.Count} -> {verifyRecords.Count}");

        foreach (var key in records.Keys)
            if (!verifyRecords.ContainsKey(key))
                throw new InvalidDataException($"Fresh read missing record: {key}");

        // OriginalTextWriter checks complete source/destination bytes for every
        // emitted display field. Generic object-only changes (e.g. actor notes)
        // are intentionally not emitted and must not be expected on fresh read.

        Console.WriteLine(JsonSerializer.Serialize(new {
            status = "translated",
            plugin_policy_version = TranslationSafety.PolicyVersion,
            protected_records = protectedRecords,
            utf8_text_verified = true,
            original_bytes_preserved = true,
            world_indexes_removed = strippedIndexes,
            world_indexes_absent_verified = true,
            input,
            output,
            target = mapping.target,
            records = records.Count,
            direct_mappings = directRows.Length,
            fallback_mappings = fallbackRows.Length,
            direct = directStats,
            fallback = fallbackStats,
            changed = totalChanged,
            unused_direct_records = missingRecords.Count,
            unmatched_direct = unmatched.Count,
            unmatched_direct_examples = unmatched.Take(20).ToArray(),
            master_order_preserved = true,
            fresh_read = true
        }));
        return 0;
    }
}
