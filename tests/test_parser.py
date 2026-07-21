from TexSoup import TexSoup
from TexSoup.data import TexText
import pytest
import time


###############
# BASIC TESTS #
###############


def test_commands_only():
    """Tests that parser for commands-only string works."""
    soup = TexSoup(r"""
    \section{Chikin Tales}
    \subsection{Chikin Fly}
    """)
    children = list(soup.children)
    assert len(children) == 2
    assert str(children[0]) == r'\section{Chikin Tales}'
    assert str(children[1]) == r'\subsection{Chikin Fly}'


def test_commands_envs_only():
    """Tests that parser for commands-environments-only string works."""
    soup = TexSoup(r"""
    \section{Chikin Tales}
    \subsection{Chikin Fly}

    \begin{itemize}
    \item plop
    \item squat
    \end{itemize}
    """)
    children = list(soup.children)
    assert len(children) == 3
    assert str(children[0]) == r'\section{Chikin Tales}'
    assert str(children[1]) == r'\subsection{Chikin Fly}'
    itemize = children[2]
    assert itemize.name == 'itemize'
    items = list(itemize.children)
    assert len(items) == 2


def test_commands_envs_text():
    """Tests that parser for commands, environments, and strings work."""
    soup = TexSoup(r"""
    \begin{document}
    \title{Chikin}
    \date{\today}
    \section
    [Tales]{Chikin Tales}
    \subsection
    {Chikin Fly}

    Here is what chickens do:

    \begin{itemize}
    \item plop
    \item squat
    \end{itemize}
    \end{document}
    """)
    assert len(list(soup.children)) == 1
    doc = soup.children[0]
    assert doc.name == 'document'
    contents, children = list(doc.contents), list(doc.children)
    assert str(children[0]) == r'\title{Chikin}'
    assert str(children[1]) == r'\date{\today}'
    assert str(children[2]) == r'\section[Tales]{Chikin Tales}'
    assert str(children[3]) == r'\subsection{Chikin Fly}'
    assert len(children) == 5
    assert len(contents) == 6
    everything = list(doc.expr.all)
    assert len(everything) == 12


def test_position():
    '''Tests that positions are correctly set.'''
    s = '''0123   \n\\section{Test}\ns p a c e s \n\\cmd{Bye}{Bye}\n'''
    soup = TexSoup(s)
    positions = [n.position for n in soup.all]
    print(positions)
    print([s[i] for i in positions])
    assert positions == [0, 8, 22, 36, 50]
    assert [s[i] for i in positions] == ['0', '\\', '\n', '\\', '\n']


#########
# CASES #
#########


def test_text_preserved():
    """Tests that the parser preserves regular non-expression text."""
    soup = TexSoup(r"""
    \Question \textbf{Question Title}

    Here is what chickens do:

    \sol{They fly!}
    """)
    assert 'Here is what chickens do:' in str(soup)


def test_command_name_parse():
    """Tests that the name of a command is parsed correctly.

    Arguments can be separated from a command name by at most one line break
    and any other whitespace.
    """
    with_space_not_arg = TexSoup(r"""\item (10 points)""")
    assert with_space_not_arg.item is not None
    assert len(list(with_space_not_arg.item.contents)) == 1
    assert with_space_not_arg.item.contents[0] == '(10 points)'

    with_space_with_arg = TexSoup(r"""\section {hula}""")
    assert with_space_with_arg.section.string == 'hula'

    with_linebreak_with_arg = TexSoup(r"""\section
    {hula}""")
    assert with_linebreak_with_arg.section.string == 'hula'


def test_command_env_name_parse():
    """Tests that the begin/end command is parsed correctly."""

    with_space = TexSoup(r"""\begin            {itemize}\end{itemize}""")
    assert len(list(with_space.contents)) == 1

    with_whitespace = TexSoup(r"""\begin
{itemize}\end{itemize}""")
    assert len(list(with_whitespace.contents)) == 1


def test_commands_without_arguments():
    """Tests that commands without arguments are parsed correctly."""
    soup = TexSoup(r"""
    \Question \textbf{Question Title}

    Here is what chickens do:

    \sol{They fly!}

    \Question
    \textbf{Question 2 Title}
    """)
    assert len(list(soup.contents)) == 6
    assert soup[0].name.strip() == 'Question'
    assert len(list(soup.children)) == 5
    assert list(soup.children)[0].name.strip() == 'Question'


def test_unlabeled_environment():
    """Tests that unlabeled environment is parsed and recognized.

    Check that the environment is recognized not as an argument but as an
    unlabeled environment.
    """
    soup = TexSoup(r"""{\color{blue} \textbf{This} \textit{is} some text.}""")
    assert len(list(soup.contents)) == 1, 'Environment not recognized.'


def test_ignore_environment():
    """Tests that "ignore" environments are preserved (e.g., math, verbatim)."""
    soup = TexSoup(r"""
    \begin{equation}\min_x \|Ax - b\|_2^2\end{equation}
    \begin{verbatim}
    \min_x \|Ax - b\|_2^2 + \lambda \|x\|_2^2
    \end{verbatim}
    $$\min_x \|Ax - b\|_2^2 + \lambda \|x\|_1^2$$
    \[[0,1)\]
    \begin{flalign} will break if TexSoup starts parsing math[ \end{flalign}
    \begin{align*} hah [ \end{align*}
    """)
    verbatim = list(list(soup.children)[1].contents)[0]
    assert len(list(soup.contents)) == 6, 'Special environments not recognized.'
    assert str(list(soup.children)[0]) == r'\begin{equation}\min_x \|Ax - b\|_2^2\end{equation}'
    # hacky workaround for odd string types
    assert verbatim[0] == '\n' and verbatim[1:].startswith('   '), 'Whitespace not preserved: {}'.format(verbatim)
    assert str(list(soup.children)[2]) == r'$$\min_x \|Ax - b\|_2^2 + \lambda \|x\|_1^2$$'
    assert str(list(soup.children)[3]) == r'\[[0,1)\]'


def test_inline_math():
    """Tests that inline math is rendered correctly."""
    soup = TexSoup(r"""
    \begin{itemize}
    \item This $e^{i\pi} = -1$
    \item How \(e^{i\pi} + 1 = 0\)
    \item Therefore!
    \end{itemize}""")
    assert r'$e^{i\pi} = -1$' in str(soup), 'Math environment not kept intact.'
    assert r'$e^{i\pi} = -1$' in str(list(soup.itemize.children)[0]), 'Environment incorrectly associated.'
    assert r'\(e^{i\pi} + 1 = 0\)' in str(soup), 'Math environment not kept intact.'
    assert r'\(e^{i\pi} + 1 = 0\)' in str(list(soup.itemize.children)[1]), 'Environment incorrectly associated.'


def test_arxiv_math_environment_names():
    """Common arXiv math environments should parse in math mode."""
    from TexSoup.tokens import MATH_ENV_NAMES
    for name in (
        'alignat*', 'aligned', 'BMAT', 'cases', 'gathered', 'IEEEeqnarray',
        'matrix', 'bmatrix', 'pmatrix', 'smallmatrix', 'subarray',
    ):
        assert name in MATH_ENV_NAMES


def test_tolerates_item_inside_math():
    """Tolerance mode should not hard-fail on malformed arXiv math."""
    with pytest.raises(AssertionError):
        TexSoup(r"$\begin{cases}\item x\end{cases}$")
    soup = TexSoup(r"$\begin{cases}\item x\end{cases}$", tolerance=1)
    assert soup.cases
    assert r"\item" in str(soup.cases)


def test_back_to_back_inline_math():
    """Tests that adjacent inline math environments do not nest incorrectly."""
    soup = TexSoup(r"""$1$$2$""")
    children = list(soup.children)
    assert len(children) == 2
    assert str(children[0]) == r'$1$'
    assert str(children[1]) == r'$2$'
    assert str(soup) == r'$1$$2$'


def test_escaped_characters():
    """Tests that special characters are escaped properly.
    Formerly, escaped characters would be rendered as latex commands.
    """
    soup = TexSoup(r"""
    \begin{itemize}
    \item Ice cream costs \$4-\$5 around here. \}\ [\{]
    \end{itemize}""")
    assert str(soup.item).strip() == r'\item Ice cream costs \$4-\$5 around here. \}\ [\{]'
    assert '\\$4-\\$5' in str(soup), 'Escaped characters not properly rendered.'


def test_newline_after_backslash():
    """Tests that newlines after backslashes are preserved."""
    text = 'a\\\nb'
    soup = TexSoup(text)
    assert str(soup) == text


def test_math_environment_weirdness():
    """Tests that math environment interacts correctly with other envs."""
    soup = TexSoup(r"""\begin{a} \end{a}$ b$""")
    assert '$' not in str(soup.a), 'Math env snuck into begin env.'
    soup = TexSoup(r"""\begin{a} $ b$ \end{a}""")
    assert '$' in str(soup.a.contents[0]), 'Math env not found in begin env'
    soup = TexSoup(r"""\begin{verbatim} $ \end{verbatim}""")
    assert soup.verbatim is not None
    # GH48
    soup = TexSoup(r"""a\\$a$""")
    assert '$' in str(soup), 'Math env not correctly parsed after \\\\'
    # GH55
    soup = TexSoup(r"""\begin{env} text\\$formula$ \end{env}""")
    assert '$' in str(soup.env), 'Math env not correctly parsed after \\\\'


def test_tokenize_punctuation_command_names():
    """Tests handling math expressions including bracket modifiers."""
    # GH111 size variant
    soup = TexSoup(r"""$\big(xy\big)$""")
    assert str(list(soup.descendants)[1]) == r'\big(', 'wrong punctuation mark'
    assert str(list(soup.descendants)[3]) == r'\big)', 'wrong punctuation mark'
    # GH111 left-right variant
    soup = TexSoup(r"""$\left[xy\right]$""")
    assert str(list(soup.descendants)[1]) == r'\left[', 'wrong punctuation mark'
    assert str(list(soup.descendants)[3]) == r'\right]', 'wrong punctuation mark'
    # one sided
    soup = TexSoup(r"""$\Big|$""")
    assert str(list(soup.descendants)[1]) == r'\Big|', 'wrong punctuation'
    # set builder
    soup = TexSoup(r"""$\left\{x|y\right\}$""")
    assert str(list(soup.descendants)[1]) == r'\left\{', 'wrong punctuation'
    assert str(list(soup.descendants)[3]) == r'\right\}', 'wrong punctuation'
    # long ones
    soup = TexSoup(r"""$\big\lfloor x \big\rfloor$""")
    assert str(list(soup.descendants)[1]) == r'\big\lfloor', 'wrong punctuation'
    assert str(list(soup.descendants)[3]) == r'\big\rfloor', 'wrong punctuation'
    # overlapping prefixes should prefer the longest punctuation command
    soup = TexSoup(r"""$\left. x \right.|_{0}^{1}$""")
    assert str(list(soup.descendants)[3]) == r'\right.|', 'wrong punctuation'


def test_item_parsing():
    """Tests that item parsing is valid."""
    soup = TexSoup(r"""\item aaa {\bbb} ccc""")
    assert str(soup.item) == r'\item aaa {\bbb} ccc'
    soup = TexSoup(r"""\begin{itemize}
    \item hello $\alpha$
    \end{itemize}""")
    assert str(soup.item).strip() == r'\item hello $\alpha$'
    soup = TexSoup(r"""\begin{itemize}
    \item
    \item first item
    \end{itemize}""")
    assert len(list(soup.item.contents)) == 0, \
        "Zeroth item should have no contents"
    soup = TexSoup(r"""\begin{itemize}
    \item second item
    \item


    third item
    with third item

    floating text
    \end{itemize}""")
    items = list(soup.find_all('item'))
    content = items[1].contents[0]
    assert 'third item' in content, 'Item does not tolerate starting line breaks (as it should)'
    assert 'with' in content, 'Item does not tolerate line break in middle (as it should)'
    soup = TexSoup(r"""\begin{itemize}
    \item This item contains code!
    \begin{lstlisting}
    Code code code
    \end{lstlisting}
    \item hello
    \end{itemize}""")
    assert ' Code code code' in str(soup.item.lstlisting), 'Item does not correctly parse contained environments.'
    assert '\n    Code code code\n    ' in soup.item.lstlisting.expr.contents
    soup = TexSoup(r"""\begin{itemize}
    \item\label{some-label} waddle
    \item plop
    \end{itemize}""")
    assert str(soup.item.label) == r'\label{some-label}'
    soup = TexSoup(r"""\begin{itemize}\item test\item $\alpha$\end{itemize}""")
    items = list(soup.itemize.contents)
    assert isinstance(items[0].contents[0], TexText)
    assert items[0].contents[0] == ' test'
    assert type(items[1].contents[0]).__name__ == 'TexNode'


def test_item_argument_parsing():
    """Tests that item arguments are correctly associated with item."""
    soup = TexSoup(r"""\item[marker]""")
    assert str(soup.item) == r'\item[marker]'


def test_comment_escaping():
    """Tests that comments can be escaped properly."""
    soup = TexSoup(r"""\caption{ 30 \%}""")
    assert '%' in str(soup.caption), 'Comment not escaped properly'


def test_comment_unparsed():
    """Tests that comments are not parsed."""
    soup = TexSoup(r"""\caption{30} % \caption{...""")
    assert '%' not in str(soup.caption)
    comment = list(soup.contents)[1]
    from TexSoup.tokens import TC
    assert comment.category == TC.Comment


def test_comment_after_escape():
    """Tests that comments after escapes work."""
    soup = TexSoup(r"""\documentclass{article}
    \begin{document}
     \\%
    \end{document}
    """)
    assert len(list(soup.document.contents)) == 2

    soup2 = TexSoup(r"""\documentclass{article}
    \begin{document}

    hi\\%


    there

    \end{document}
    hi\\%""")
    assert len(list(soup2.document.contents)) == 4

    soup3 = TexSoup(r"""
    \documentclass{article}
    \usepackage{graphicx}
    \begin{document}
    \begin{equation}
    \scalebox{2.0}{$x =
    \begin{cases}
    1, & \text{if } y=1 \\
    0, & \text{otherwise}
    \end{cases}$}
    \end{equation}
    \end{document}
    """)
    assert soup3.equation
    assert soup3.scalebox


def test_items_with_labels():
    """Items can have labels with square brackets such as in the description
    environment. See Issue #32."""
    soup = TexSoup(r"""\begin{description}
    \item[Python] a high-level general-purpose interpreted programming language.
    \end{description}""")
    assert "Python" in soup.description.item.args


def test_multiline_args():
    """Tests that macros with arguments are different lines are parsed
    properly. See Issue #31."""
    soup = TexSoup(r"""\mytitle{Essay title}
    {Essay subheading.}""")
    assert "Essay subheading." in soup.mytitle.args
    # Only one newline allowed
    soup = TexSoup(r"""\mytitle{Essay title}

    {Essay subheading.}""")
    assert "Essay subheading." not in soup.mytitle.args
    assert "Essay title" in soup.mytitle.args
    soup = TexSoup(r"""\title{Arguments}
    {appear}
    \subtitle{everywhere}
    in \LaTeX.

    \date{\today}
    """)
    assert "Arguments" in soup.title.args
    assert "appear" in soup.title.args
    assert "everywhere" in soup.subtitle.args
    assert "\n    in " in list(soup.contents)
    assert len(list(soup.contents)) == 6


def test_nested_commands():
    """Tests that nested commands are parsed correctly."""
    soup = TexSoup(r'\emph{Some \textbf{bold} words}')
    assert soup.textbf is not None
    assert len(list(soup.emph.contents)) == 3


def test_def_item():
    """Tests that def with more 'complex' raw replacement body parses."""
    soup = TexSoup(r"""
    \def\itemeqn{\item\abovedisplayskip=2pt\abovedisplayshortskip=0pt~\vspace*{-\baselineskip}}
    """)
    assert soup.item is None
    assert r"\item\abovedisplayskip" in str(soup.find("def"))


def test_def_without_braces():
    """Tests that def without braces around the new command parses correctly."""
    soup = TexSoup(r"\def\acommandname{replacement text}")
    assert len(soup.find("def").args) == 2
    assert str(soup.find("def").args[0]) == r"\acommandname"
    assert str(soup.find("def").args[1]) == "{replacement text}"


def test_grouping_optional_argument():
    """Tests that grouping occurs correctly"""
    soup = TexSoup(r"\begin{Theorem}[The argopt contains {$]\int_\infty$} the square bracket]\end{Theorem}")
    assert len(soup.Theorem.args) == 1


def test_zero_argument_signatures():
    """Tests that specific commands that do not take arguments are parsed correctly."""
    soup = TexSoup(r"$\cap[\cup[\in[\notin[\infty[$")
    assert len(soup.find("cap").args) == 0
    assert len(soup.find("cup").args) == 0
    assert len(soup.find("in").args) == 0
    assert len(soup.find("notin").args) == 0
    assert len(soup.find("infty").args) == 0

    soup = TexSoup(r"\begin{equation} \cup [0, \infty) \end{equation}")
    assert len(soup.find("cup").args) == 0


##############
# FORMATTING #
##############


def test_basic_whitespace():
    """Tests that basic text maintains whitespace."""
    soup = TexSoup("""
    Here is some text
    with a line break
    and awko      taco spacing
    """)
    assert len(str(soup).split('\n')) == 5, 'Line breaks not persisted.'


def test_whitespace_in_command():
    """Tests that whitespace in commands are maintained."""
    soup = TexSoup(r"""
    \begin{article}
    \title {This title contains    a space}
    \section {This title contains
    line break}
    \end{article}
    """)
    assert '    ' in soup.article.title.string
    assert '\n' in soup.article.section.string


def test_math_environment_whitespace():
    """Tests that math environments are untouched."""
    soup = TexSoup(r"""$$\lambda
    \Sigma$$ But don't mind me \$3.00""")
    children, contents = list(soup.children), list(soup.contents)
    assert '\n' in str(children[0]), 'Whitesapce not preserved in math env.'
    assert len(children) == 1 and children[0].name == '$$', 'Math env wrong'
    assert r'\$' == contents[2], 'Dollar sign not escaped!'
    soup = TexSoup(r"""\gamma = \beta\begin{notescaped}\gamma = \beta\end{notescaped}
    \begin{equation*}\beta = \gamma\end{equation*}""")
    assert str(soup.find('equation*')) == r'\begin{equation*}\beta = \gamma\end{equation*}'
    assert str(soup).startswith(r'\gamma = \beta')
    assert str(soup.notescaped) == r'\begin{notescaped}\gamma = \beta\end{notescaped}'


def test_non_letter_commands():
    """
    Tests that non-letters are still captured as an escaped sequence
    (whether valid or not).
    """
    for punctuation in '!@#$%^&*_+-=~`<>,./?;:|':
        tex = r"""
        \begin{{document}}
        \lstinline{{\{} Word [a-z]+}}
        \end{{document}}
        """.format(punctuation)
        soup = TexSoup(tex)
        assert str(soup) == tex


def test_no_arg_text_symbol_before_literal_bracket():
    """No-arg text symbols must not consume a following literal bracket."""
    tex = (
        r"\begin{figure}"
        r"\captionof{table}{Cap}"
        r"\resizebox{1\textwidth}{!}{"
        r"\begin{tabularx}{x}{l c l}"
        r"Instruction & Layer & Top Tokens \\"
        r"JSON Format & 18 & \texttt{\textunderscore [\{, \textunderscore json, \textunderscore JSON } \\"
        r"\end{tabularx}}"
        r"\label{table:x}"
        r"\end{figure}"
        r"\section{After}"
    )
    soup = TexSoup(tex, tolerance=1)

    assert r"\section{After}" not in str(soup.figure)
    assert str(soup.figure).endswith(r"\end{figure}")
    assert soup.section.string == "After"
    assert not soup.find("textunderscore").args


def test_math_environment_escape():
    """Tests $ escapes in math environment."""
    soup = TexSoup(r"$ \$ $")
    contents = list(soup.contents)
    assert r'\$' in contents[0][0], \
        'Dollar sign not escaped! Contents: %s' % contents


def test_punctuation_command_structure():
    """Tests that commands for punctuation work."""
    soup = TexSoup(r"""\right. \right[ \right( \right|
    \right\langle \right\lfloor \right\lceil \right\ulcorner \big{ \bigg{
    \Big{ \Bigg}""")
    assert len(list(soup.contents)) == 12
    assert len(list(soup.children)) == 12


def test_non_punctuation_command_structure():
    """Tests that normal commands do not include punctuation in the command.

    However, the asterisk is one exception.
    """
    soup = TexSoup(r"""\mycommand, hello""")
    contents = list(soup.contents)
    assert r'\mycommand' == str(contents[0]), 'Comma considered part of the command.'

    soup = TexSoup(r"""\hspace*{0.2in} hello \hspace*{2in} world""")
    assert len(list(soup.contents)) == 4, '* not recognized as part of command.'


def test_allow_unclosed_non_curly_braces():
    """Tests that non-curly-brace 'delimiters' can be unclosed

    Non-curly-brace delimiters only cause parse errors when parsing arguments
    for a command.
    """
    soup = TexSoup("[)")
    assert len(list(soup.contents)) == 2

    soup = TexSoup(r"""
    \documentclass{article}
        \usepackage[utf8]{inputenc}
    \begin{document}
        \textbf{[}
    \end{document}
    """)
    assert soup.textbf.string == '['

    soup = TexSoup("[regular text]")
    contents = list(soup.contents)
    assert isinstance(contents[0], str)

    soup = TexSoup("{regular text}[")
    contents = list(soup.contents)
    assert isinstance(contents[1], str)


##########
# BUFFER #
##########


def test_buffer():
    from TexSoup.utils import Buffer, Token
    b = Buffer('abcdef')
    assert b.forward_until(lambda s: s in 'def') == 'abc'
    assert b.forward_until(lambda s: s in 'f') == 'de'
    assert b.backward(5) == 'abcde'
    assert b.forward_until(lambda s: s not in 'abc') == 'abc'
    assert b.forward_until(lambda s: s in 'def') == ''
    assert b.backward(3) == 'abc'
    assert b.num_forward_until(lambda s: s in 'def') == 3
    assert b.forward(3) == 'abc'
    assert b.num_forward_until(lambda s: s in 'g') == 3
    assert b.forward(3) == 'def'
    assert b.num_forward_until(lambda s: s in 'z') == 0
    assert b.backward(6) == 'abcdef'
    assert b.num_forward_until(lambda s: s not in 'abc') == 3

    b = Buffer('cd')
    b.push(Token('ab', 0))
    assert next(b) == 'ab'
    assert next(b) == 'c'

    b = Buffer('cd')
    _ = b.peek()
    b.replace(1, Token('ab', 0))
    assert next(b) == 'ab'
    assert next(b) == 'd'


def test_to_buffer():
    from TexSoup.utils import to_buffer
    f = to_buffer(convert_out=False)(lambda x: x[:])
    assert f('asdf') == 'asdf'
    g = to_buffer(convert_out=False)(lambda x: x)
    assert not g('').hasNext()
    assert next(g('asdf')) == 'a'
    h = to_buffer()(lambda x: x)
    assert str(f('asdf')) == 'asdf'

##########
# ERRORS #
##########


def test_unclosed_commands():
    """Tests that unclosed commands result in an error."""
    with pytest.raises(TypeError):
        TexSoup(r"""\textit{hello""")

    with pytest.raises(TypeError):
        TexSoup(r"""\textit{hello %}""")

    with pytest.raises(TypeError):
        TexSoup(r"""\textit{hello \\%}""")


def test_unclosed_environments():
    """Tests that unclosed environment results in error."""
    with pytest.raises(EOFError):
        TexSoup(r"""\begin{itemize}\item haha""")


def test_unclosed_math_environments():
    """Tests that unclosed math environment results in error."""
    with pytest.raises(EOFError):
        TexSoup(r"""$$\min_x \|Xw-y\|_2^2""")

    with pytest.raises(EOFError):
        TexSoup(r"""$\min_x \|Xw-y\|_2^2""")


def test_tolerance_math_unclosed():
    """Tolerance mode keeps malformed math as recoverable content."""
    soup = TexSoup(r"""before $\min_x \|Xw-y\|_2^2 after""", tolerance=1)
    assert r"\min_x" in str(soup)
    assert len(list(soup.children)) == 1


def test_tolerance_mixed_dollar_paren_math_closes_locally():
    """A source typo like ``$...\\)`` must not swallow later document text."""
    soup = TexSoup(
        r"where $i\in[k]\setminus I\). After $\phi$ remains local.",
        tolerance=1,
    )
    math_nodes = [
        node for node in soup.descendants
        if getattr(node, "name", None) == "$"
    ]

    assert len(math_nodes) == 2
    assert all("After" not in str(node) for node in math_nodes)
    assert "After" in str(soup)


def test_arg_parse():
    """Test arg parsing errors."""
    from TexSoup.data import TexGroup
    with pytest.raises(TypeError):
        TexGroup.parse('{]')

    with pytest.raises(TypeError):
        TexGroup.parse(r'\section[{')


###################
# FAULT TOLERANCE #
###################


def test_tolerance_env_unclosed():
    """Test that unclosed envs are tolerated"""
    with pytest.raises(EOFError):
        TexSoup(r"""
        \begin{enva}
        \begin{envb}
        \end{enva}
        \end{envb}""")

    soup = TexSoup(r"""
    \begin{enva}
    \begin{envb}
    \end{enva}
    \end{envb}""", tolerance=1)
    assert len(list(soup.enva.contents)) == 1
    assert soup.end

def test_special_command():
    """Test that we tolerate unclosed environments when in special mode."""
    # source:
    # https://github.com/alvinwan/TexSoup/issues/135#issuecomment-1705749106
    texsrc = r"""
    \documentclass[useAMS,usenatbib]{mnras}
    \newcommand{\beq}{\begin{equation}}
    \newcommand{\eeq}{\end{equation}}

    \begin{document}
    \begin{itemize}
    \item something
    \end{itemize}

    \end{document}
    """
    soup = TexSoup(texsrc)
    assert soup


def test_def_replacement_body_raw():
    """Primitive macro replacement bodies should not parse nested TeX."""
    soup = TexSoup(r"\def\foo{\begin{equation}}", tolerance=0)
    assert str(soup.find("def")) == r"\def\foo{\begin{equation}}"
    assert soup.find("equation") is None


def test_def_with_parameter_text_preserves_args_and_string():
    """Primitive macro parameter text should stay unbraced in output."""
    source = r"\def\figref#1{figure~\ref{#1}}"
    soup = TexSoup(source)
    command = soup.find("def")
    assert str(command) == source
    assert [str(arg) for arg in command.args] == [
        r"\figref", "#1", r"{figure~\ref{#1}}"]
    assert command.args[1].string == "#1"
    assert command.args[2].string == r"figure~\ref{#1}"


def test_macro_definition_replacement_bodies_are_raw_and_fast():
    """Representative math macro files should parse without recursive bodies."""
    source = "\n".join(
        r"\newcommand{\macro%d}[1]{\begin{equation}$#1\end{split}}" % i
        for i in range(300)
    )
    source += "\n" + r"\DeclareMathOperator{\badop}{arg\,max$}"

    start = time.perf_counter()
    soup = TexSoup(source, tolerance=0)
    elapsed = time.perf_counter() - start

    assert elapsed < 2.0
    assert soup.count("newcommand") == 300
    assert soup.DeclareMathOperator is not None
    assert soup.find("equation") is None


def test_environment_definition_bodies_are_raw():
    source = (
        r"\newenvironment{algenv}[2]"
        r"{\begin{algorithm}\caption{#1}\label{#2}}"
        r"{\end{algorithm}}"
    )
    soup = TexSoup(source, tolerance=0)
    command = soup.find("newenvironment")
    assert command is not None
    assert str(command) == source
    assert soup.find("algorithm") is None
    assert soup.find("label") is None
    assert [str(arg) for arg in command.args] == [
        "{algenv}",
        "[2]",
        r"{\begin{algorithm}\caption{#1}\label{#2}}",
        r"{\end{algorithm}}",
    ]


def test_document_environment_definition_bodies_are_raw():
    source = (
        r"\NewDocumentEnvironment{box}{m}"
        r"{\begin{figure}\label{#1}}"
        r"{\end{figure}}"
    )
    soup = TexSoup(source, tolerance=0)
    command = soup.find("NewDocumentEnvironment")
    assert command is not None
    assert str(command) == source
    assert soup.find("figure") is None
    assert soup.find("label") is None


def test_simple_environment_macros_expand_before_parsing():
    r"""Common paper aliases like \be/\ee should expose real environments."""
    soup = TexSoup(
        r"\def\be{\begin{equation}}\def\ee{\end{equation}}"
        r"\begin{document}Before \be x=1 \ee after\end{document}",
        expand_macros=True,
    )
    assert soup.equation is not None
    assert "x=1" in str(soup.equation)


def test_simple_newenvironment_wrappers_expand_before_parsing():
    r"""Simple environment wrappers should expose their target environments."""
    soup = TexSoup(
        r"\newenvironment{ex}{\begin{example}\rm}{\end{example}}"
        r"\begin{document}Before \begin{ex}Body\end{ex} after\end{document}",
        expand_macros=True,
    )
    assert soup.example is not None
    assert "Body" in str(soup.example)
    assert soup.find("ex") is None


def test_simple_definition_command_aliases_expand_before_parsing():
    r"""Paper aliases like \nc for \newcommand should still define macros."""
    soup = TexSoup(
        r"\newcommand{\nc}{\newcommand}"
        r"\nc{\beq}{\begin{equation}}"
        r"\nc{\eeq}{\end{equation}}"
        r"\begin{document}Before \beq x=1 \eeq after\end{document}",
        expand_macros=True,
    )
    assert soup.equation is not None
    assert "x=1" in str(soup.equation)


def test_simple_macro_expansion_can_be_disabled():
    source = (
        r"\def\be{\begin{equation}}\def\ee{\end{equation}}"
        r"\be x=1 \ee"
    )
    soup = TexSoup(source, expand_macros=False)
    assert soup.equation is None
    assert soup.be is not None


def test_simple_argument_macros_expand_refs_and_math_wrappers():
    soup = TexSoup(
        r"\newcommand{\figref}[1]{Figure~\ref{#1}}"
        r"\newcommand{\pfrac}[2]{\left(\frac{\partial #1}{\partial #2}\right)}"
        r"See \figref{fig:a}. $\pfrac{f}{x}$",
        expand_macros=True,
    )
    assert soup.ref is not None
    assert soup.ref.string == "fig:a"
    assert r"\frac{\partial f}{\partial x}" in str(soup)


def test_label_relation_macros_expand_before_parsing():
    soup = TexSoup(
        r"\begin{align}"
        r"a&\labelrel={eq:a} b \\"
        r"c&\labelrel\sleq{eq:c} d"
        r"\end{align}",
        expand_macros=True,
    )
    labels = [label.string for label in soup.find_all("label")]
    assert labels == ["eq:a", "eq:c"]
    assert r"\labelrel" not in str(soup)
    assert r"\sleq" in str(soup)


def test_simple_macro_expansion_handles_control_symbol_targets():
    soup = TexSoup(
        r"\renewcommand{\(}{\left(}\renewcommand{\)}{\right)}"
        r"\begin{align}\(x+y\)\end{align}",
        expand_macros=True,
    )
    assert soup.align is not None
    assert r"\left(x+y\right)" in str(soup.align)


def test_macro_expansion_handles_optional_defaults_and_skips_comments():
    source = (
        r"\newcommand{\maybe}[2][x]{#1#2}"
        "\n% \\def\\be{\\begin{equation}}\n"
        r"\maybe{y} \be z \ee"
    )
    soup = TexSoup(source, expand_macros=True)
    assert soup.equation is None
    assert soup.maybe is None
    assert "xy" in str(soup)
    assert soup.be is not None


def test_macro_expansion_treats_percent_after_control_symbol_as_comment():
    from TexSoup.macros import expand_macros

    source = (
        r"\def\foo{OK}" "\n"
        r"\\% \def\foo{BAD}" "\n"
        r"\foo"
    )

    assert expand_macros(source).endswith("OK")


def test_macro_expansion_obeys_definition_order():
    from TexSoup.macros import expand_macros

    source = (
        r"\foo "
        r"\def\foo{A}\foo "
        r"\def\foo{B}\foo "
        r"\providecommand{\foo}{C}\foo"
    )
    assert expand_macros(source) == (
        r"\foo "
        r"\def\foo{A}A "
        r"\def\foo{B}B "
        r"\providecommand{\foo}{C}B"
    )


def test_macro_expansion_skips_verbatim_like_payloads():
    source = (
        r"\def\foo{BAR}"
        r"\begin{verbatim}\foo\end{verbatim} "
        r"\verb|\foo| "
        r"\lstinline[language=TeX]|\foo| "
        r"\url{\foo} "
        r"\foo"
    )
    soup = TexSoup(source, expand_macros=True)
    assert r"\foo" in str(soup.verbatim)
    assert r"\verb|\foo|" in str(soup)
    assert r"\lstinline[language=TeX]|\foo|" in str(soup)
    assert r"\url{\foo}" in str(soup)
    assert str(soup).endswith("BAR")


def test_special_command_signatures():
    """Macro-definition commands should consume their control sequence names."""
    for source, name in (
            (r"\newcommand\a[1]{Hello #1}", 'newcommand'),
            (r"\renewcommand\a[1]{Hello #1}", 'renewcommand'),
            (r"\providecommand\a[1]{Hello #1}", 'providecommand')):
        soup = TexSoup(source)
        children = list(soup.children)
        assert len(children) == 1
        assert children[0].name == name
        assert len(children[0].args) == 3
        assert str(children[0].args[0]) == r'\a'
        assert str(children[0].args[1]) == '[1]'
        assert str(children[0].args[2]) == '{Hello #1}'

    soup = TexSoup(r"\newcommand\a[2][default]{Hello #1 #2}")
    children = list(soup.children)
    assert len(children) == 1
    assert children[0].name == 'newcommand'
    assert [str(arg) for arg in children[0].args] == [
        r'\a', '[2]', '[default]', '{Hello #1 #2}']

    soup = TexSoup(r"\newcommand{\foo}[1]{\textbf{#1}}")
    children = list(soup.children)
    assert len(children) == 1
    assert [str(arg) for arg in children[0].args] == [
        r'{\foo}', '[1]', r'{\textbf{#1}}']

    soup = TexSoup(r"\renewcommand{\(}{\left(}\renewcommand{\)}{\right)}")
    assert [str(arg) for arg in soup.renewcommand.args] == [
        r'{\(}', r'{\left(}']

    soup = TexSoup(r"\def\({\left(}\def\){\right)}")
    assert [str(arg) for arg in soup.find_all('def')[0].args] == [
        r'\(', r'{\left(}']


def test_label_supports_optional_type_argument():
    soup = TexSoup(r"\label[definition]{def:a}", expand_macros=False)
    label = soup.find("label")
    assert [str(arg) for arg in label.args] == ["[definition]", "{def:a}"]
    assert label.args[-1].string == "def:a"


def test_makeatletter_command_names():
    """``\\makeatletter`` should allow ``@`` inside command names."""
    soup = TexSoup(r"\makeatletter\def\@internal{Hello}\makeatother")
    assert list(map(str, soup.contents)) == [
        r'\makeatletter',
        r'\def\@internal{Hello}',
        r'\makeatother',
    ]

    soup = TexSoup(r"\def\@internal{Hello}")
    assert list(map(str, soup.contents)) == [
        r'\def{\@}{internal}',
        r'{Hello}',
    ]


def test_brackets_issue():
    """Test that mismatched square brackets in math mode are not a problem."""
    soup = TexSoup(r"$\cmd [0,1)$")
    assert soup


def test_nested_inline_math_delimiters_inside_math_mode_are_text():
    """Some arXiv sources use ``\\(`` / ``\\)`` inside display math as
    delimiter-like tokens. They should not open a nested math environment."""
    soup = TexSoup(
        r"\begin{align}"
        r"\mathcal{V}^{a}=\mathcal{V}^{\mu}"
        r"\(\dfrac{\partial}{\partial p^\mu}\)^{a}"
        r"\end{align}",
        tolerance=1,
    )
    assert soup.align is not None
    assert r"\(\dfrac" in str(soup.align)


def test_verbatim_like_commands():
    """Verbatim-like commands should keep raw contents unparsed."""
    soup = TexSoup(r"A \verb|df$col| column")
    parts = list(soup.all)
    assert str(parts[1]) == r'\verb|df$col|'
    assert parts[1].name == 'verb'
    assert len(parts[1].args) == 0
    assert parts[1].contents[0] == '|df$col|'
    assert str(parts[2]) == ' column'

    soup = TexSoup(r"A \verb+code+ example")
    parts = list(soup.all)
    assert str(parts[1]) == r'\verb+code+'
    assert parts[1].contents[0] == '+code+'
    assert str(parts[2]) == ' example'

    soup = TexSoup(r"\url{https://test.lab/test?var=test$}")
    assert str(soup.url) == r"\url{https://test.lab/test?var=test$}"
    assert str(soup.url.args[0]) == r"{https://test.lab/test?var=test$}"
    soup = TexSoup(
        r"\url{en.wikipedia.org/wiki/Zermelo%E2%80%93Fraenkel_set_theory}")
    assert str(soup.url) == (
        r"\url{en.wikipedia.org/wiki/Zermelo%E2%80%93Fraenkel_set_theory}")
    assert str(soup.url.args[0]) == (
        r"{en.wikipedia.org/wiki/Zermelo%E2%80%93Fraenkel_set_theory}")


def test_mintinline_keeps_code_arg_raw_without_swallowing_body():
    """Inline minted code can contain literal dollars."""
    soup = TexSoup(
        r"Before \mintinline{php}{$_POST} after.",
        tolerance=1,
        expand_macros=False,
    )
    parts = list(soup.all)

    assert str(soup) == r"Before \mintinline{php}{$_POST} after."
    assert str(parts[1]) == r"\mintinline{php}{$_POST}"
    assert [str(arg) for arg in parts[1].args] == ["{php}", r"{$_POST}"]
    assert str(parts[2]) == " after."


def test_listing_style_arguments_raw():
    """listings/mdframed key-value configs may use TeX-active characters such
    as $$ as literal delimiters; they are not math expressions."""
    soup = TexSoup(
        r"\lstdefinestyle{Terraform}{moredelim=[il][\color{gray}]{$$},}"
        r"\lstset{style=Terraform, postbreak=\mbox{\textcolor{red}{$\hookrightarrow$}}}"
        r"\mdfdefinestyle{box}{backgroundcolor=yellow!10}"
    )
    assert "$$" in str(soup.lstdefinestyle)
    assert r"$\hookrightarrow$" in str(soup.lstset)
    assert soup.mdfdefinestyle is not None


def test_tblr_layout_argument_is_raw_table_metadata():
    soup = TexSoup(
        r"\begin{tblr}[]{colspec={|X[6]X[5]|}, rows={font=\tiny}}"
        r"A & B\\"
        r"\end{tblr}",
        tolerance=1,
        expand_macros=False,
    )

    assert soup.tblr is not None
    assert [str(arg) for arg in soup.tblr.args] == [
        "[]",
        r"{colspec={|X[6]X[5]|}, rows={font=\tiny}}",
    ]
    assert "A & B" in str(soup.tblr)


def test_custom_prompt_boxes_are_skipped_like_verbatim():
    """Model prompt boxes often wrap listings that contain literal dollars and
    TeX-looking text. Parse the box as raw payload rather than LaTeX."""
    soup = TexSoup(
        r"\begin{AIBoxNoTitle}{\begin{lstlisting}"
        r'Model Output: ["Your bank balance is $1,234.56."]'
        r"\end{lstlisting}}\end{AIBoxNoTitle}"
    )
    assert "$1,234.56" in str(soup.AIBoxNoTitle)


def test_tcblisting_is_skipped_like_verbatim():
    """Prompt/listing boxes contain raw prompt text and literal dollars."""
    soup = TexSoup(
        r"\begin{tcblisting}{colback=usercolor, listing only}"
        r"User: return JSON with price $1.23."
        r"\end{tcblisting}"
        r"After.",
        tolerance=1,
        expand_macros=False,
    )
    box = soup.find("tcblisting")

    assert box is not None
    assert "$1.23" in str(box)
    assert str(soup).endswith("After.")


def test_minted_inside_float_does_not_swallow_following_body():
    tex = (
        r"\begin{wrapfigure}{R}{0.5\textwidth}"
        "\n"
        r"\begin{minted}[fontsize=\tiny,escapeinside=<>]{php}"
        "\n"
        r"$x = 1;"
        "\n"
        r"\end{minted}"
        "\n"
        r"\caption{Cap}\label{fig:x}"
        "\n"
        r"\end{wrapfigure}"
        "\n"
        "After."
    )
    soup = TexSoup(tex, tolerance=1, expand_macros=False)
    wrap = soup.find("wrapfigure")

    assert wrap is not None
    assert soup.find("minted") is not None
    assert "After." not in str(wrap)
    assert str(soup).endswith("After.")
    assert r"$x = 1;" in str(soup.find("minted"))


def test_author_argument_raw():
    """Author blocks often contain affiliation math and nested thanks macros.
    They should not be allowed to leave the whole document in math mode."""
    soup = TexSoup(
        r"\author{Fan Liu$^{1}$ \thanks{$^{\dagger}$Correspondence}\\ "
        r"$^{1}$AI Thrust}"
        r"\begin{document}Body\end{document}"
    )
    assert r"$^{\dagger}$" in str(soup.author)
    assert soup.document is not None


def test_tabular_column_spec_raw():
    """Tabular-style column specs should not parse `$` as nested math."""
    soup = TexSoup(r"""
    \begin{table}
      \begin{tabular}{l >{$}r<{$}}
        i & 7078.2747\\
      \end{tabular}
    \end{table}
    """)
    assert soup.tabular
    assert str(soup.tabular.args[0]) == r"{l >{$}r<{$}}"

    soup = TexSoup(r"$\begin{array}{l >{$}r<{$}} x & 1 \end{array}$")
    assert soup.array
    assert str(soup.array.args[0]) == r"{l >{$}r<{$}}"
