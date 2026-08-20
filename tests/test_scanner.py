from TexSoup.scanner import protected_spans


def test_protected_spans_preserves_raw_commands_after_plain_text():
    tex = (
        "Plain text before raw commands. "
        r"\verb|a%b| and \lstinline[language=TeX]+x%y+ plus \url{x%y}"
        "\n% " r"\verb|hidden|"
    )

    spans = protected_spans(tex)
    protected = [tex[start:end] for start, end in spans]

    assert protected == [
        r"\verb|a%b|",
        r"\lstinline[language=TeX]+x%y+",
        r"\url{x%y}",
    ]


def test_protected_spans_returns_fresh_list_from_cache():
    tex = r"\verb|a%b| and \url{x%y}"
    expected = protected_spans(tex)

    mutated = protected_spans(tex)
    mutated.append((0, 1))

    assert protected_spans(tex) == expected
