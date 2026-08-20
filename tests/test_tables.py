from TexSoup import TexSoup
from TexSoup.tables import (
    clean_table_fragment,
    strip_leading_table_colspec,
    table_body_contents,
)


def test_table_body_contents_removes_repeated_tabular_star_arguments():
    soup = TexSoup(
        r"\begin{tabular*}{0.48\columnwidth}{@{\extracolsep{\fill}}*2c}"
        r"System & Value\\KX Cnc & 31.2"
        r"\end{tabular*}"
    )
    env = soup.find("tabular*")

    contents = table_body_contents(env)
    body = "".join(str(item) for item in contents)

    assert "System & Value" in body
    assert "0.48" not in body
    assert "extracolsep" not in body


def test_clean_table_fragment_drops_layout_and_unwraps_visible_text():
    raw = (
        r"{@{\extracolsep{\fill}}*2c}"
        r"\noalign{\smallskip}Model & "
        r"\multirow{2}{*}{\rotatebox[origin=c]{90}{EPR}}\\"
        r"Caption & \parbox[t]{68mm}{Useful caption text}\\"
        r"\multicolumn{1}{c}{Visible value}\rule{0pt}{2ex}"
    )

    clean = clean_table_fragment(strip_leading_table_colspec(raw))

    assert "Model" in clean
    assert "EPR" in clean
    assert "Useful caption text" in clean
    assert "Visible value" in clean
    for contaminant in (
        "extracolsep",
        "noalign",
        "smallskip",
        "multirow",
        "rotatebox",
        "origin=c",
        "parbox",
        "68mm",
        "multicolumn",
        "0pt",
    ):
        assert contaminant not in clean


def test_clean_table_fragment_drops_alignment_commands_inside_wrappers():
    raw = r"\hline\multirow{2}{1em}{\centering$x$} & value\\"

    clean = clean_table_fragment(raw)

    assert "$x$" in clean
    assert "value" in clean
    for contaminant in ("multirow", "1em", "centering", "hline"):
        assert contaminant not in clean
