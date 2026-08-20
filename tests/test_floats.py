from TexSoup.floats import collect_float_environments


def test_collect_float_environments_from_newfloat_and_floatname():
    tex = (
        r"\newfloat{supfigure}{htbp}{lop}[section]"
        r"\floatname{supfigure}{Supplementary Figure}"
        r"\newfloat{suptable}{htbp}{lot}[section]"
        r"\floatname{suptable}{Supplementary Table}"
    )

    assert collect_float_environments(tex) == {
        "supfigure": "figure",
        "supfigure*": "figure",
        "suptable": "table",
        "suptable*": "table",
    }


def test_collect_float_environments_from_declare_floating_environment():
    tex = r"\DeclareFloatingEnvironment[fileext=los]{scheme}"

    assert collect_float_environments(tex) == {}
