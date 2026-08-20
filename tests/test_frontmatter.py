from TexSoup.frontmatter import (
    evaluate_simple_conditionals,
    standardize_frontmatter_source,
)


def test_frontmatter_extracts_handmade_title_authors_keywords_without_maketitle():
    tex = r"""
\documentclass{article}
\begin{document}
\begin{center}
{\Large{\textbf{{A Study on Linear Jaco Graphs}}}}
\end{center}
\large{
\centerline{(Johan Kok, Susanth C, Sunny Joseph Kalayathankal)\footnote{\textbf{Affiliation of authors:}\\
Johan Kok, City of Tshwane\\ e-mail: kokkiek2@tshwane.gov.za}}
\begin{abstract}Useful abstract.\end{abstract}
\noindent {\footnotesize \textbf{Keywords:} Linear function Jaco graph, Hope graph, directed graph}\\ \\
\noindent {\footnotesize \textbf{AMS Classification Numbers:} 05C07}
\section{Introduction}Real body.
\end{document}
"""
    result = standardize_frontmatter_source(tex)

    assert result.frontmatter.title == "A Study on Linear Jaco Graphs"
    assert result.frontmatter.authors == (
        "Johan Kok, Susanth C, Sunny Joseph Kalayathankal",
    )
    assert result.frontmatter.keywords == (
        "Linear function Jaco graph",
        "Hope graph",
        "directed graph",
    )
    assert "Useful abstract" in result.source
    assert "Real body" in result.source
    assert "kokkiek2@tshwane.gov.za" not in result.source
    assert "Affiliation of authors" not in result.source
    assert "AMS Classification" not in result.source


def test_frontmatter_extracts_keywords_inside_abstract_without_body_residue():
    tex = r"""
\documentclass{article}
\title{Movable Categories}
\author{P. Gevorgyan}
\begin{document}
\maketitle
\begin{abstract}
Useful abstract sentence about shape theory. \\ \\ Keywords: Shape theory,
movability, category.\\ \\ AMS classification: 55P55; 54C56
\\
\end{abstract}
Real body starts here.
\end{document}
"""
    result = standardize_frontmatter_source(tex)

    assert result.frontmatter.keywords == (
        "Shape theory",
        "movability",
        "category",
    )
    assert "Useful abstract sentence" in result.source
    assert "Real body starts here" in result.source
    assert "Keywords" not in result.source
    assert "AMS classification" not in result.source


def test_frontmatter_evaluates_simple_blind_conditional_and_drops_page_residue():
    tex = r"""
\documentclass{article}
\newcommand{\blind}{0}
\begin{document}
\if0\blind
{
  \title{\bf Full Paper Title}
  \author{Ada Lovelace}
  \maketitle
} \fi
\if1\blind
{
  \begin{center}{\LARGE\bf Title}\end{center}
} \fi
\begin{abstract}Useful abstract.\end{abstract}
\noindent%
{\it Keywords:} entropy, prior, Bayesian
\vfill
\newpage
\spacingset{1}
\section{Introduction}Real body.
\end{document}
"""
    evaluated = evaluate_simple_conditionals(tex)
    result = standardize_frontmatter_source(tex)

    assert r"\begin{center}{\LARGE\bf Title}" not in evaluated
    assert result.frontmatter.title == "Full Paper Title"
    assert result.frontmatter.authors == ("Ada Lovelace",)
    assert result.frontmatter.keywords == ("entropy", "prior", "Bayesian")
    lead = result.source.split(r"\section{Introduction}", 1)[0]
    assert "Title" not in lead
    assert "100" not in lead
    assert "spacingset" not in lead


def test_frontmatter_drops_nested_italic_keyword_wrapper_without_swallowing_body():
    tex = r"""
\documentclass{article}
\title{Choice Rules}
\author{Ada Lovelace}
\begin{document}
\maketitle
\begin{abstract}Useful abstract.\end{abstract}
JEL Code: D71
{\it{Keywords:
social choice functions, preferences, restricted domain.
}}
\bigskip
\newpage
\section{Introduction}Real body.
\end{document}
"""
    result = standardize_frontmatter_source(tex)

    assert result.frontmatter.keywords == (
        "social choice functions",
        "preferences",
        "restricted domain",
    )
    lead = result.source.split(r"\section{Introduction}", 1)[0]
    assert r"{\it{" not in lead
    assert "Keywords" not in lead
    assert "JEL Code: D71" not in lead
    assert r"\section{Introduction}Real body." in result.source


def test_frontmatter_extracts_and_drops_ieee_keywords_environment():
    tex = r"""
\documentclass{IEEEtran}
\begin{document}
\title{Protocol Proof}
\author{Ada Lovelace}
\maketitle
\begin{abstract}Useful abstract.\end{abstract}
\begin{IEEEkeywords}
Distributed protocols; model checking; Paxos. IEEEkeywords
\end{IEEEkeywords}
\section{Introduction}Real body.
\end{document}
"""
    result = standardize_frontmatter_source(tex)

    assert result.frontmatter.keywords == (
        "Distributed protocols",
        "model checking",
        "Paxos",
    )
    assert "IEEEkeywords" not in result.source
    assert "Real body" in result.source


def test_frontmatter_extracts_ieee_author_blocks_with_orcid_pairs():
    tex = r"""
\documentclass{IEEEtran}
\begin{document}
\title{Towards an Automatic Proof of Lamport's Paxos}
\author{\IEEEauthorblockN{Aman Goel \orcidID{0000-0003-0520-8890}}
\IEEEauthorblockA{
\textit{University of Michigan, Ann Arbor}\\
amangoel@umich.edu}
\and
\IEEEauthorblockN{Karem A. Sakallah \orcidID{0000-0002-5819-9089}}
\IEEEauthorblockA{
\textit{University of Michigan, Ann Arbor}\\
karem@umich.edu}
}
\maketitle
\section{Introduction}Real body.
\end{document}
"""
    result = standardize_frontmatter_source(tex)

    assert result.frontmatter.authors == ("Aman Goel", "Karem A. Sakallah")
    author_text = " ".join(result.frontmatter.authors)
    assert "0000-0003-0520-8890" not in author_text
    assert "University of Michigan" not in author_text
    assert "amangoel@umich.edu" not in author_text


def test_frontmatter_extracts_comma_separated_ieee_author_block_names():
    tex = r"""
\documentclass{IEEEtran}
\title{A Novel Strategy}
\author{\IEEEauthorblockN{Sanat K. Biswas\IEEEauthorrefmark{1},
Li Qiao\IEEEauthorrefmark{2},
Andrew G. Dempster\IEEEauthorrefmark{1}}

\IEEEauthorblockA{\IEEEauthorrefmark{1}
Australian Centre for Space Engineering Research,
The University of New South Wales, NSW, Australia, 2052}

\IEEEauthorblockA{\IEEEauthorrefmark{2}
School of Engineering and Information Technology,
The University of New South Wales, Canberra, ACT, Australia, 2600}}
\begin{document}
\maketitle
\section{Introduction}Real body.
\end{document}
"""
    result = standardize_frontmatter_source(tex)

    assert result.frontmatter.authors == (
        "Sanat K. Biswas",
        "Li Qiao",
        "Andrew G. Dempster",
    )
    for author in result.frontmatter.authors:
        assert not author.endswith(("1", "2"))
    assert all("University" not in author for author in result.frontmatter.authors)


def test_frontmatter_ignores_lstlisting_morekeywords_configuration():
    tex = r"""
\begin{document}
\lstdefinelanguage{affprob}
{
morekeywords={angel,demon, choice, while, do, od},
sensitive = false
}
\lstset{language=affprob}
\section{Introduction}Real body.
\end{document}
"""
    result = standardize_frontmatter_source(tex)

    assert result.frontmatter.keywords == ()
    assert "morekeywords" in result.source
    assert "Real body" in result.source


def test_frontmatter_drops_layout_and_classification_residue_from_lead():
    tex = r"""
\documentclass{article}
\usepackage[strict]{changepage}
\def\keywords{\begin{adjustwidth}{1cm}{1cm}\par\footnotesize\noindent{\bf Keywords:}}
\def\endkeywords{\end{adjustwidth}\smallskip}
\begin{document}
\title{Forest Labels}
\author{Ada Lovelace}
\maketitle
\vskip 1.5em
\begin{abstract}Useful abstract.\end{abstract}
\begin{keywords}
Antimagic labeling; rooted trees
\end{keywords}
\begin{MSC}
05C78; 05C05
\end{MSC}
\section{Introduction}Real body.
\end{document}
"""
    result = standardize_frontmatter_source(tex)

    assert result.frontmatter.keywords == ("Antimagic labeling", "rooted trees")
    assert "Useful abstract" in result.source
    assert "Real body" in result.source
    lead = result.source.split(r"\section{Introduction}", 1)[0]
    assert "1.5em" not in lead
    assert "adjustwidth" not in " ".join(result.frontmatter.keywords)
    assert "05C78" not in lead


def test_frontmatter_drops_twocolumn_publisher_template_before_real_section():
    tex = r"""
\documentclass{article}
\begin{document}
\titlespacing*{\section}{0pt}{4pt}{4pt}
\fancyfoot[LO,RE]{\includegraphics{head_foot/LF}}
\twocolumn[
  \begin{@twocolumnfalse}
  {\includegraphics{head_foot/journal_name}\\
   \includegraphics{head_foot/header_bar}}\par
  \begin{tabular}{m{4cm}p{10cm}}
  \includegraphics{head_foot/DOI} & \LARGE{Template Title}\\
  \includegraphics{head_foot/dates} & Abstract-like publisher lead.
  \end{tabular}
  \end{@twocolumnfalse}
]
\renewcommand*\rmdefault{bch}\normalfont\upshape
\section*{}
\vspace{-1cm}
\footnotetext{\textit{$^{a}$ Institute; E-mail: author@example.org}}
\section{Introduction}Real body.
\footnotetext{\textit{$^{b}$ Second institute.}}
\end{document}
"""
    result = standardize_frontmatter_source(tex)

    assert r"\section{Introduction}Real body." in result.source
    assert "head_foot" not in result.source
    assert "journal_name" not in result.source
    assert "header_bar" not in result.source
    assert "0pt" not in result.source
    assert "E-mail" not in result.source
    assert "Second institute" not in result.source


def test_frontmatter_preserves_post_maketitle_pre_section_body():
    tex = r"""
\documentclass{article}
\title{Hydrogen Strategy}
\author{Ada Lovelace}
\affil{Department, University, ada@example.com}
\begin{document}
\maketitle
\begin{center}
\begin{minipage}{0.7\textwidth}
\textbf{Summary} \\
Europe risks little by setting green hydrogen targets.
\end{minipage}
\end{center}

Intro paragraph before the first section.

\begin{figure}
\includegraphics{figures/fig1}
\caption{Ranges of green hydrogen production.}
\label{fig:lit-review-ranges}
\end{figure}

\section{Methods}Real body.
\end{document}
"""
    result = standardize_frontmatter_source(tex)
    body = result.source.split(r"\begin{document}", 1)[1]
    lead = body.split(r"\section{Methods}", 1)[0]

    assert result.frontmatter.title == "Hydrogen Strategy"
    assert result.frontmatter.authors == ("Ada Lovelace",)
    assert r"\maketitle" not in lead
    assert r"\affil" not in lead
    assert "ada@example.com" not in lead
    assert "Summary" in lead
    assert "Europe risks little by setting green hydrogen targets." in lead
    assert "Intro paragraph before the first section." in lead
    assert r"\includegraphics{figures/fig1}" in lead


def test_centered_minipage_body_is_not_inferred_as_title():
    tex = r"""
\begin{document}
\begin{center}
\begin{minipage}{0.7\textwidth}
\textbf{Summary} \\
Useful text before the first section.
\end{minipage}
\end{center}
\section{Intro}Body.
\end{document}
"""
    result = standardize_frontmatter_source(tex)

    assert result.frontmatter.title == ""
    assert "Useful text before the first section." in result.source
