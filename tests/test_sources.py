from TexSoup.sources import expand_pgfplotstabletypeset, expand_source


def test_expand_pgfplotstabletypeset_inlines_local_csv_as_tabular():
    tex = r"\pgfplotstabletypeset[col sep=comma]{tables/scores.csv}"
    source = {
        "main.tex": tex,
        "tables/scores.csv": b"model,score\nA,0.91\nB,0.83\n",
    }

    expanded = expand_pgfplotstabletypeset(tex, source)

    assert r"\pgfplotstabletypeset" not in expanded
    assert r"\begin{tabular}{ll}" in expanded
    assert r"model & score" in expanded
    assert r"A & 0.91" in expanded
    assert r"B & 0.83" in expanded


def test_expand_pgfplotstabletypeset_resolves_unique_basename_after_input_flattening():
    tex = r"\pgfplotstabletypeset{c1.csv}"
    source = {
        "main.tex": tex,
        "tables/generated/c1.csv": b"setting,value\nsoft,12\nhard,19\n",
    }

    expanded = expand_pgfplotstabletypeset(tex, source)

    assert "setting & value" in expanded
    assert "soft & 12" in expanded
    assert "hard & 19" in expanded


def test_expand_pgfplotstabletypeset_expands_visible_csv_cell_macros():
    tex = (
        r"\newcommand{\dtname}[1]{\textsl{#1}}"
        r"\pgfplotstabletypeset{c1.csv}"
    )
    source = {
        "main.tex": tex,
        "tables/c1.csv": (
            b"name,score\n"
            b"\\dtname{Syn-1},0.91\n"
            b"\\dtname{Twitter-\\#},0.82\n"
        ),
    }

    expanded = expand_pgfplotstabletypeset(tex, source)
    table = expanded[expanded.index(r"\begin{tabular}"):]

    assert r"\dtname" not in table
    assert r"\textbackslash{}" not in table
    assert r"Syn-1 & 0.91" in table
    assert r"Twitter-\# & 0.82" in table


def test_expand_pgfplotstabletypeset_collects_visible_macros_from_source_files():
    tex = r"\pgfplotstabletypeset{c1.csv}"
    source = {
        "main.tex": tex,
        "defs.tex": r"\newcommand{\dtname}[1]{\textsl{#1}}",
        "tables/c1.csv": b"name,score\n\\dtname{Sidecar},1.0\n",
    }

    expanded = expand_pgfplotstabletypeset(tex, source)

    assert r"\dtname" not in expanded
    assert "Sidecar & 1.0" in expanded


def test_expand_source_resolves_iffileexists_let_alias_to_includegraphics():
    source = {
        "main.tex": (
            r"\IfFileExists{ajr.sty}{\let\inPlot\input}{\let\inPlot\includegraphics}"
            r"\begin{figure}\inPlot{figures/plot.pdf}\caption{Plot.}\end{figure}"
        ),
        "figures/plot.pdf": b"%PDF",
    }

    expanded = expand_source(source, "main.tex")

    assert r"\IfFileExists" not in expanded
    assert r"\let\inPlot" not in expanded
    assert r"\inPlot" not in expanded
    assert r"\includegraphics{figures/plot.pdf}" in expanded


def test_expand_source_resolves_iffileexists_present_branch_before_let_alias():
    source = {
        "main.tex": (
            r"\IfFileExists{ajr.sty}{\let\inPlot\input}{\let\inPlot\includegraphics}"
            r"\inPlot{plot-body}"
        ),
        "ajr.sty": "",
        "plot-body.tex": "Visible body.",
    }

    expanded = expand_source(source, "main.tex")

    assert r"\IfFileExists" not in expanded
    assert r"\inPlot" not in expanded
    assert "Visible body." in expanded
