from TexSoup.pipeline import prepare_source, read, read_core, standardize_source
from TexSoup.data import TexNode
from TexSoup.tlatex import standardize_tlatex_source


def test_prepare_source_runs_feature_passes_independently():
    tex = r"\def\be{\begin{equation}}\def\ee{\end{equation}}\be x \ee"
    assert r"\begin{equation}" in prepare_source(tex)
    assert prepare_source(tex, expand=False) == tex


def test_standardize_source_expands_definition_command_aliases():
    tex = (
        r"\newcommand{\nc}{\newcommand}"
        r"\nc{\beq}{\begin{equation}}"
        r"\nc{\eeq}{\end{equation}}"
        r"\beq x \eeq"
    )
    standardized = standardize_source(tex)
    assert r"\newcommand{\beq}{\begin{equation}}" in standardized
    assert r"\newcommand{\eeq}{\end{equation}}" in standardized
    assert standardized.endswith(r"\begin{equation} x \end{equation}")


def test_standardize_source_expands_simple_environment_alias_wrappers():
    tex = (
        r"\newenvironment{ex}{\begin{example}\rm}{\end{example}}"
        r"\begin{ex}Body\end{ex}"
    )
    standardized = standardize_source(tex)
    assert r"\newenvironment{ex}" in standardized
    assert r"\begin{example}Body\end{example}" in standardized
    assert r"\begin{ex}" not in standardized
    assert r"\end{ex}" not in standardized


def test_standardize_source_expands_macros_with_one_optional_default():
    tex = (
        r"\newcommand{\pair}[2][left]{#1/#2}"
        r"\pair{right} \pair[up]{down}"
    )
    standardized = standardize_source(tex)
    assert "left/right" in standardized
    assert "up/down" in standardized
    assert r"\pair{right}" not in standardized
    assert r"\pair[up]{down}" not in standardized


def test_standardize_source_collapses_real_shaped_visual_includegraphics_wrappers():
    tex = r"""
\newlength{\spyimagewidth}
\newlength{\spyimageheight}
\newcommand{\spyimage}[2][0.20\linewidth]{%
  % Set the dimensions within the command
  \setlength{\spyimagewidth}{#1}
  \setlength{\spyimageheight}{\spyimagewidth}
  \begin{tikzpicture}[spy using outlines={rectangle, magnification=1.8, size=0.4\spyimagewidth}]
    % Insert the image
    \node[inner sep=0pt, anchor=south west] (image) at (0,0) {\adjustbox{trim={.05\width} {0.2\height} {0.45\width} {0.2\height},clip,width=\spyimagewidth}{\includegraphics{#2}}};
    \coordinate (spy point) at (0.85\spyimagewidth , 0.63\spyimagewidth );
    \coordinate (spy node) at (0.1\spyimagewidth, 0.8\spyimageheight);
    \spy on (spy point) in node at (spy node);
  \end{tikzpicture}%
}
\newcommand{\spyimagelol}[2][0.20\linewidth]{%
  \setlength{\spyimagewidth}{#1}
  \setlength{\spyimageheight}{\spyimagewidth}
  \begin{tikzpicture}[spy using outlines={rectangle, magnification=1.8, size=0.4\spyimagewidth}]
    \node[inner sep=0pt, anchor=south west] (image) at (0,0) {\adjustbox{trim={.1\width} {0.1\height} {0.1\width} {0.1\height},clip,width=\spyimagewidth}{\includegraphics{#2}}};
    \coordinate (spy point) at (0.45\spyimagewidth , 0.43\spyimagewidth );
    \coordinate (spy node) at (0.1\spyimagewidth, 0.8\spyimageheight);
    \spy on (spy point) in node at (spy node);
  \end{tikzpicture}%
}
\newcommand{\spyimagelamp}[2][0.20\linewidth]{%
  \setlength{\spyimagewidth}{#1}
  \setlength{\spyimageheight}{\spyimagewidth}
  \begin{tikzpicture}[spy using outlines={rectangle, magnification=2.7, size=0.4\spyimagewidth}]
    \node[inner sep=0pt, anchor=south west] (image) at (0,0) {\adjustbox{trim={.1\width} {0.1\height} {0.1\width} {0.1\height},clip,width=\spyimagewidth}{\includegraphics{#2}}};
    \coordinate (spy point) at (0.62\spyimagewidth , 0.65\spyimagewidth );
    \coordinate (spy node) at (0.1\spyimagewidth, 0.85\spyimageheight);
    \spy on (spy point) in node at (spy node);
  \end{tikzpicture}%
}
\begin{figure*}
\begin{tabular}{c@{\hskip 0.2em} c@{\hskip 0.2em} c}
\spyimage{1.png} & \spyimage[0.3\linewidth]{1low.png} & \spyimagelol{3RetinexNet} \\
\spyimagelamp{2URetinexNet++.png} & \spyimagelol{3night-enh.png} & \spyimage{1_KinD_plus.png}
\end{tabular}
\end{figure*}
"""
    standardized = standardize_source(tex)
    figure_use = standardized.split(r"\begin{figure*}", 1)[1]
    assert r"\includegraphics{1.png}" in figure_use
    assert r"\includegraphics{1low.png}" in figure_use
    assert r"\includegraphics{3RetinexNet}" in figure_use
    assert r"\includegraphics{2URetinexNet++.png}" in figure_use
    assert r"\includegraphics{3night-enh.png}" in figure_use
    assert r"\includegraphics{1_KinD_plus.png}" in figure_use
    assert r"\spyimage" not in figure_use
    assert r"\spyimagelol" not in figure_use
    assert r"\spyimagelamp" not in figure_use
    assert r"\begin{tikzpicture}" not in figure_use


def test_standardize_source_turns_inline_logo_graphic_macro_into_text():
    tex = (
        r"\newcommand{\Rlogo}{\protect\includegraphics[height=1.8ex,keepaspectratio]{Rlogo.png}}"
        "\n"
        r"We provide \Rlogo~code and an \Rlogo~package."
    )
    standardized = standardize_source(tex)
    prose = standardized.split("\n", 1)[1]

    assert r"\includegraphics" not in prose
    assert r"R~code" in prose
    assert r"R~package" in prose


def test_standardize_source_expands_label_relation_macros():
    tex = r"\begin{align}a&\labelrel={eq:a} b \\ c&\labelrel\geq{eq:c} d\end{align}"
    standardized = standardize_source(tex)
    assert r"a&=\label{eq:a} b" in standardized
    assert r"c&\geq\label{eq:c} d" in standardized


def test_standardize_source_drops_empty_math_layout_spacers():
    standardized = standardize_source(r"Before $ $\linebreak After $x$ remains.")

    assert r"\linebreak" not in standardized
    assert "$ $" not in standardized
    assert "$x$" in standardized
    assert "Before" in standardized and "After" in standardized


def test_standardize_source_preserves_layout_spacer_text_inside_lstlisting():
    tex = (
        r"\begin{lstlisting}"
        "\n$\\ell_1:$\n$\\quad$\ny \\quad z\n$\\qquad$\n"
        r"\end{lstlisting}"
    )
    standardized = standardize_source(tex)

    assert "$\\ell_1:$\n$\\quad$" in standardized
    assert "$\\qquad$" in standardized


def test_standardize_source_preserves_display_math_delimiters():
    tex = r"Before $$\mbox{$x$ and $y$.}$$ After."
    standardized = standardize_source(tex)

    assert r"$$\mbox{$x$ and $y$.}$$" in standardized


def test_standardize_source_normalizes_tex_prose_typography():
    tex = r"``correct'' --- x--y, 200 \-- 300, and `single'."
    standardized = standardize_source(tex)

    assert standardized == "\"correct\" \u2014 x\u2013y, 200 \u2013 300, and 'single'."


def test_standardize_source_preserves_typography_inside_math_and_raw_spans():
    tex = (
        r"Text -- ok. $a--b$ \[c---d\] "
        r"\begin{equation}``x''--y\end{equation} "
        r"\begin{lstlisting}``raw''--text\end{lstlisting} "
        "% ``comment'' -- unchanged\n"
    )
    standardized = standardize_source(tex)

    assert "Text \u2013 ok." in standardized
    assert r"$a--b$" in standardized
    assert r"\[c---d\]" in standardized
    assert r"\begin{equation}``x''--y\end{equation}" in standardized
    assert r"\begin{lstlisting}``raw''--text\end{lstlisting}" in standardized
    assert "% ``comment'' -- unchanged\n" in standardized


def test_standardize_source_preserves_typography_inside_structural_arguments():
    tex = (
        r"Range 48--64 and ``quoted''. "
        r"\label{sec:old--new} See \ref{sec:old--new}, "
        r"\cite[pp.~48--64]{Smith--Jones2020}, "
        r"\includegraphics[width=.4\textwidth]{figs/a--b---c.png}, "
        r"\input{sections/a--b}."
    )
    standardized = standardize_source(tex)

    assert "Range 48\u201364 and \"quoted\"." in standardized
    assert r"\label{sec:old--new}" in standardized
    assert r"\ref{sec:old--new}" in standardized
    assert r"\cite[pp.~48--64]{Smith--Jones2020}" in standardized
    assert r"\includegraphics[width=.4\textwidth]{figs/a--b---c.png}" in standardized
    assert r"\input{sections/a--b}" in standardized


def test_standardize_source_expands_common_math_aliases():
    tex = r"$\Bar{u} = \bigO(10 c/\omega_p) + \bar{u}$"
    standardized = standardize_source(tex)

    assert r"\Bar" not in standardized
    assert r"\bar{u} = \mathcal{O}(10 c/\omega_p) + \bar{u}" in standardized


def test_standardize_source_prefers_source_defined_bigo_macro():
    tex = r"\newcommand{\bigO}{\mathsf{O}}$\bigO(n)$"
    standardized = standardize_source(tex)

    assert r"\mathsf{O}(n)" in standardized
    assert r"\mathcal{O}(n)" not in standardized


def test_read_core_is_macro_expansion_free():
    tex = r"\def\be{\begin{equation}}\def\ee{\end{equation}}\be x \ee"
    tree = read_core(tex)
    soup = TexNode(tree, src=tex)
    assert soup.find("equation") is None
    assert soup.find("be") is not None


def test_read_core_is_environment_alias_expansion_free():
    tex = (
        r"\newenvironment{ex}{\begin{example}\rm}{\end{example}}"
        r"\begin{ex}Body\end{ex}"
    )
    tree = read_core(tex)
    soup = TexNode(tree, src=tex)
    assert soup.find("example") is None
    assert soup.find("ex") is not None


def test_public_read_can_opt_in_to_standardization():
    tex = r"\def\be{\begin{equation}}\def\ee{\end{equation}}\be x \ee"
    tree, prepared = read(tex, expand=True)
    soup = TexNode(tree, src=prepared)
    assert soup.find("equation") is not None
    assert r"\begin{equation}" in prepared


def test_public_read_is_lossless_by_default():
    tex = r"\def\foo{OK}\foo"
    tree, prepared = read(tex)
    soup = TexNode(tree, src=prepared)
    assert prepared == tex
    assert str(soup).endswith(r"\foo")
    assert soup.find("foo") is not None


def test_standardize_source_exposes_tlatex_spec_lines():
    tex = (
        r"\tlatex"
        r"\@x{\makebox[10pt][r]{\scriptsize 1\hspace{0.8em}} "
        r"\textcolor{purple}{{\textsc{constants }}} \svalue , \sacceptor}"
        r"\@pvspace{4.0pt}"
        r"\@x{\@s{2}\.{\land} \A\, A \.{\in} \sacceptor \.{:} ok}"
    )
    standardized = standardize_source(tex)
    assert "constants" in standardized
    assert r"\@x{" not in standardized
    assert r"\@s{" not in standardized
    assert r"\@pvspace" not in standardized
    assert r"\land" in standardized
    assert r"\in" in standardized


def test_standardize_tlatex_is_dormant_before_tlatex_marker():
    tex = r"\newcommand{\@x}[1]{layout #1}\@x{Not a source spec line yet}"
    assert standardize_tlatex_source(tex) == tex
