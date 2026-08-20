from TexSoup.comments import apply_comment_package, collect_comment_directives, strip_tex_comments


def test_strip_tex_comments_preserves_inline_verbatim_percent():
    tex = r"Visible % hidden" "\n" r"\verb|a%b| and \url{x%y}"

    stripped = strip_tex_comments(tex)

    assert "hidden" not in stripped
    assert r"\verb|a%b|" in stripped
    assert r"\url{x%y}" in stripped


def test_strip_tex_comments_treats_percent_after_control_symbol_as_comment():
    tex = r"Line break \\% hidden \input{stale}" "\n" "Shown"

    stripped = strip_tex_comments(tex)

    assert "hidden" not in stripped
    assert r"\input{stale}" not in stripped
    assert "Shown" in stripped


def test_strip_tex_comments_does_not_revive_commented_verbatim_env():
    tex = (
        "% \\begin{verbatim}\n"
        "% hidden\n"
        "% \\end{verbatim}\n"
        "Shown"
    )

    stripped = strip_tex_comments(tex)

    assert "hidden" not in stripped
    assert "Shown" in stripped


def test_apply_comment_package_excludes_and_unwraps_declared_envs():
    tex = (
        r"% \excludecomment{kept}" "\n"
        r"\excludecomment{draft}" "\n"
        r"\includecomment{kept}" "\n"
        r"\begin{draft}Hidden \label{bad}\end{draft}" "\n"
        r"\begin{kept}Shown \label{ok}\end{kept}" "\n"
    )

    transformed = apply_comment_package(tex)

    assert "Hidden" not in transformed
    assert r"\label{bad}" not in transformed
    assert "Shown" in transformed
    assert r"\label{ok}" in transformed
    assert r"\begin{kept}" not in transformed
    assert r"\excludecomment{draft}" not in transformed
    assert r"\excludecomment" not in strip_tex_comments(transformed)


def test_collect_comment_directives_respects_last_declaration():
    tex = r"\excludecomment{paper}\includecomment{paper}"

    state, spans = collect_comment_directives(tex)

    assert state == {"paper": True}
    assert len(spans) == 2


def test_comment_environment_is_always_excluded():
    tex = r"Before \begin{comment}Hidden\end{comment} After"

    assert apply_comment_package(tex) == "Before  After"
