using System.Text;
using Mutagen.Bethesda;
using Mutagen.Bethesda.Strings;
using Mutagen.Bethesda.Strings.DI;

internal static class TranslationEncoding
{
    // Reject invalid UTF-8 before trying legacy English text. Encoding.UTF8's
    // replacement fallback would otherwise silently corrupt CP1252 punctuation.
    public static readonly IMutagenEncoding Utf8 =
        new MutagenEncodingWrapper(new UTF8Encoding(false, true));
    public static readonly IMutagenEncoding Input = new MutagenEncodingFallbackWrapper(
        Utf8, new MutagenEncodingWrapper(CodePagesEncodingProvider.Instance.GetEncoding(1252)!));

    private sealed class EnglishEncodingProvider(IMutagenEncoding encoding) : IMutagenEncodingProvider
    {
        public IMutagenEncoding GetEncoding(GameRelease release, Language language) =>
            language == Language.English ? encoding : MutagenEncoding.GetEncoding(release, language);
    }

    public static readonly IMutagenEncodingProvider OutputProvider = new EnglishEncodingProvider(Utf8);

    public static StringsReadParameters Read(bool output = false) => new()
    {
        NonLocalizedEncodingOverride = output ? Utf8 : Input,
        EncodingProvider = new EnglishEncodingProvider(output ? Utf8 : Input),
        TargetLanguage = Language.English
    };
}
