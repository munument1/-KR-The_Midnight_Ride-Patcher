using Mutagen.Bethesda.Plugins.Records;

internal static class TranslationSafety
{
    public const int PolicyVersion = 5;

    public static bool IsProtected(IMajorRecord record)
    {
        var key = record.FormKey;
        if (string.Equals(key.ModKey.FileName, "Fallout4.esm", StringComparison.OrdinalIgnoreCase)
            && key.ID is 0x055402 or 0x02495A or 0x00DCEC)
            return true;
        // Covers mod-owned Zimonja markers without relying on load-order IDs.
        return record.EditorID?.Contains("Zimonja", StringComparison.OrdinalIgnoreCase) == true;
    }
}
