from pathlib import Path

from benchmarks.arxiv import cache_local_source
from TexSoup.sources import (
    InMemoryTexSource,
    expand_source,
    expand_tex,
    resolve_target,
    scan_command_calls,
)


def test_scan_command_calls_skips_comments_and_starred_names():
    text = (
        r"% \input{ignored}" "\n"
        r"\includegraphics*[width=.5\textwidth]{figures/a.pdf}" "\n"
        r"\input{body}"
    )
    calls = list(scan_command_calls(text, {"includegraphics", "input"}))
    assert [call["base_name"] for call in calls] == ["includegraphics", "input"]
    assert calls[0]["optional_args"] == [r"width=.5\textwidth"]
    assert calls[0]["required_args"] == ["figures/a.pdf"]
    assert calls[1]["required_args"] == ["body"]


def test_scan_command_calls_treats_percent_after_control_symbol_as_comment():
    text = r"Line break \\% \input{hidden}" "\n" r"\input{shown}"

    calls = list(scan_command_calls(text, {"input"}))

    assert [call["required_args"][0] for call in calls] == ["shown"]


def test_expand_tex_does_not_parse_malformed_math(tmp_path):
    (tmp_path / "main.tex").write_text(
        r"\documentclass{article}\begin{document}"
        r"Before $x "
        r"\input{section}"
        r"\bibliography{refs}"
        r"\end{document}",
        encoding="utf-8",
    )
    (tmp_path / "section.tex").write_text(
        r"Section text with $$still malformed.",
        encoding="utf-8",
    )
    (tmp_path / "refs.bbl").write_text(
        r"\begin{thebibliography}{1}\bibitem{x} Ref.\end{thebibliography}",
        encoding="utf-8",
    )

    expanded = expand_tex(tmp_path / "main.tex")

    assert r"\input{section}" not in expanded
    assert r"\bibliography{refs}" not in expanded
    assert "Section text" in expanded
    assert r"\bibitem{x}" in expanded


def test_expand_tex_supports_subfile(tmp_path):
    (tmp_path / "main.tex").write_text(
        r"\documentclass{article}\begin{document}\subfile{appendix}\end{document}",
        encoding="utf-8",
    )
    (tmp_path / "appendix.tex").write_text(
        r"\section{Appendix}\label{sec:app}",
        encoding="utf-8",
    )

    expanded = expand_tex(tmp_path / "main.tex")

    assert r"\subfile" not in expanded
    assert r"\label{sec:app}" in expanded


def test_expand_source_inlines_in_memory_files_and_bibliography():
    files = {
        "main.tex": (
            r"\documentclass{article}\begin{document}"
            r"\input{sections/intro}"
            r"\include{body}"
            r"\subfile{appendix}"
            r"\bibliography{refs}"
            r"\end{document}"
        ),
        "sections/intro.tex": b"Intro from bytes.",
        Path("body.tex"): "Body text.",
        "appendix.tex": r"\section{Appendix}",
        "refs.bbl": (
            r"\begin{thebibliography}{1}"
            r"\bibitem{x} Ref."
            r"\end{thebibliography}"
        ),
    }

    expanded = expand_source(files, "main.tex")

    assert r"\input{sections/intro}" not in expanded
    assert r"\include{body}" not in expanded
    assert r"\subfile{appendix}" not in expanded
    assert r"\bibliography{refs}" not in expanded
    assert "Intro from bytes." in expanded
    assert "Body text." in expanded
    assert r"\section{Appendix}" in expanded
    assert r"\bibitem{x}" in expanded


def test_expand_source_strips_subfile_document_wrappers():
    files = {
        "main.tex": (
            r"\documentclass{article}\begin{document}"
            r"\section{One}\subfile{sections/one}"
            r"\section{Two}\subfile{sections/two}"
            r"\end{document}"
        ),
        "sections/one.tex": (
            r"\documentclass[../main.tex]{subfiles}"
            r"\begin{document}First child.\end{document}"
        ),
        "sections/two.tex": (
            r"\documentclass[../main.tex]{subfiles}"
            r"\begin{document}Second child.\end{document}"
        ),
    }

    expanded = expand_source(files, "main.tex")

    assert "First child." in expanded
    assert "Second child." in expanded
    assert r"\documentclass[../main.tex]{subfiles}" not in expanded
    assert expanded.count(r"\end{document}") == 1


def test_expand_source_uses_visited_for_in_memory_cycles():
    source = InMemoryTexSource({
        "main.tex": r"Main[\input{a}][\input{a}]",
        "a.tex": r"A(\input{nested/b})",
        "nested/b.tex": r"B(\input{../a})",
    })
    visited = set()

    expanded = expand_source(source, "main.tex", visited=visited)

    assert expanded == "Main[A(B())][]"
    assert visited == {"main.tex", "a.tex", "nested/b.tex"}


def test_expand_source_supports_bare_input_and_missing_policy():
    files = {
        "main.tex": "Before \\input sections/intro \\input{missing} After",
        "sections/intro.tex": "Intro",
    }

    expanded = expand_source(files, "main.tex", missing_input="drop")

    assert r"\input" not in expanded
    assert "Before Intro" in expanded
    assert "After" in expanded


def test_expand_source_can_wrap_lstinputlisting():
    files = {
        "main.tex": r"\lstinputlisting[language=pseudo]{code.dsl}",
        "code.dsl": "first\nsecond",
    }

    expanded = expand_source(files, "main.tex", expand_listings=True)

    assert r"\lstinputlisting" not in expanded
    assert r"\begin{lstlisting}" in expanded
    assert "first\nsecond" in expanded


def test_expand_source_can_wrap_inputminted():
    files = {
        "main.tex": r"\inputminted[linenos=false]{php}{Examples/variable.tex}",
        "Examples/variable.tex": r"$d = $_POST;",
    }

    expanded = expand_source(files, "main.tex", expand_listings=True)

    assert r"\inputminted" not in expanded
    assert r"\begin{minted}[linenos=false]{php}" in expanded
    assert r"$d = $_POST;" in expanded
    assert r"\end{minted}" in expanded


def test_expand_source_uses_root_and_unique_suffix_fallbacks():
    files = {
        "paper/main.tex": r"A \input{shared} B \input{chapter}",
        "shared.tex": "Shared",
        "sections/chapter.tex": "Chapter",
    }

    expanded = expand_source(files, "paper/main.tex")

    assert r"\input" not in expanded
    assert "Shared" in expanded
    assert "Chapter" in expanded


def test_expand_source_supports_dotful_tex_basenames():
    files = {
        "main.tex": r"Intro: \input{1.intro} Method: \input{sections/2.method}",
        "1.intro.tex": "Intro text.",
        "sections/2.method.tex": "Method text.",
    }

    expanded = expand_source(files, "main.tex", missing_input="drop")

    assert r"\input" not in expanded
    assert "Intro: Intro text." in expanded
    assert "Method: Method text." in expanded


def test_expand_source_supports_unique_case_insensitive_in_memory_target():
    files = {
        "main.tex": r"Before \input{StrategyHd} After",
        "StrategyHD.tex": "Strategy text.",
    }

    expanded = expand_source(files, "main.tex", missing_input="drop")

    assert r"\input" not in expanded
    assert "Before Strategy text. After" in expanded


def test_expand_source_does_not_resolve_lowercase_input_to_uppercase_file():
    files = {
        "main.tex": r"Before \input{Exp} Middle \input{exp} After",
        "Exp.tex": "Experiment text.",
    }

    expanded = expand_source(files, "main.tex", missing_input="drop")

    assert r"\input" not in expanded
    assert expanded.count("Experiment text.") == 1
    assert "Before Experiment text. Middle  After" in expanded


def test_resolve_target_supports_dotful_tex_basenames(tmp_path):
    target = tmp_path / "1.intro.tex"
    target.write_text("Intro", encoding="utf-8")

    resolved = resolve_target(tmp_path, "1.intro")

    assert resolved == target.resolve()


def test_expand_source_preserves_separator_after_input_replacement():
    files = {
        "main.tex": (
            r"\input{defs}" "\n"
            r"% a comment that should remain" "\n"
            r"\newcommand{\next}{ok}"
        ),
        "defs.tex": r"\newcommand{\fromdefs}{ok}% trailing percent",
    }

    expanded = expand_source(files, "main.tex")

    assert "% a comment that should remain" in expanded
    assert "trailing percent\n% a comment" in expanded
    assert r"\newcommand{\next}{ok}" in expanded


def test_cache_local_source_replaces_stale_directory(tmp_path):
    source = tmp_path / "2101.00001.gz"
    source.write_bytes(b"source")
    cache_dir = tmp_path / "cache"
    stale = cache_dir / "2101.00001" / "local-source"
    stale.mkdir(parents=True)
    (stale / "old").write_text("stale", encoding="utf-8")

    cached = cache_local_source("2101.00001", source, cache_dir)

    assert cached == stale
    assert cached.is_symlink() or cached.is_file()
    assert cached.read_bytes() == b"source"


def test_resolve_target_ignores_directories(tmp_path):
    (tmp_path / "figures").mkdir()
    assert resolve_target(tmp_path, "figures") is None

    (tmp_path / "section.tex").write_text("text", encoding="utf-8")
    assert resolve_target(tmp_path, "section") == (tmp_path / "section.tex").resolve()
