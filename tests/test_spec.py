from TexSoup import TexSoup
from TexSoup.pipeline import prepare_source, read_core
from TexSoup.spec import to_spec


def test_core_tree_spec_is_macro_expansion_free():
    tex = r"\def\be{\begin{equation}}\def\ee{\end{equation}}\be x \ee"
    spec = to_spec(read_core(tex), include_positions=False)
    names = [item.get("name") for item in spec["contents"]]
    assert names == ["def", "def", "be", None, "ee"]
    assert spec["contents"][3] == {
        "kind": "text",
        "text": " x ",
        "category": "Text",
    }
    assert "equation" not in names


def test_prepared_tree_spec_exposes_expanded_structure():
    tex = r"\def\be{\begin{equation}}\def\ee{\end{equation}}\be x \ee"
    spec = to_spec(read_core(prepare_source(tex)), include_positions=False)
    names = [item.get("name") for item in spec["contents"]]
    assert names == ["def", "def", "equation"]
    assert spec["contents"][2]["contents"][0] == {
        "kind": "text",
        "text": " x ",
        "category": "Text",
    }


def test_public_tree_spec_is_stable_for_commands_groups_and_comments():
    soup = TexSoup(
        r"\section[Short]{Title \emph{One}}"
        "\n% hidden\n"
        r"\begin{itemize}\item Body\end{itemize}",
        expand_macros=False,
    )
    spec = to_spec(soup, include_positions=False)
    assert spec["contents"][0] == {
        "kind": "command",
        "name": "section",
        "args": [
            {"kind": "group", "group": "bracket",
             "contents": [{"kind": "text", "text": "Short", "category": "Text"}]},
            {"kind": "group", "group": "brace",
             "contents": [
                 {"kind": "text", "text": "Title ", "category": "Text"},
                 {"kind": "command", "name": "emph",
                  "args": [{"kind": "group", "group": "brace",
                            "contents": [
                                {"kind": "text", "text": "One",
                                 "category": "Text"}]}]},
             ]},
        ],
    }
    assert spec["contents"][1] == {
        "kind": "text", "text": "\n", "category": "MergedSpacer"}
    assert spec["contents"][2] == {
        "kind": "text", "text": "% hidden", "category": "Comment"}
    assert spec["contents"][3] == {
        "kind": "text", "text": "\n", "category": "MergedSpacer"}
    assert spec["contents"][4]["name"] == "itemize"
