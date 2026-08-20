"""Parsing mechanisms should not be directly invoked publicly, as they are
subject to change."""

from TexSoup.utils import Token, Buffer, MixedBuffer, CharToLineOffset
from TexSoup.data import *
from TexSoup.data import arg_type
from TexSoup.tokens import (
    TC,
    tokenize,
    SKIP_ENV_NAMES,
    MATH_ENV_NAMES,
    SPECIAL_COMMANDS,
)
import functools
import string
import sys


MODE_MATH = 'mode:math'
MODE_NON_MATH = 'mode:non-math'
MODE_SPECIAL = 'mode:special'
MATH_SIMPLE_ENVS = (
    TexDisplayMathModeEnv,
    TexMathModeEnv,
    TexDisplayMathEnv,
    TexMathEnv
)
MATH_TOKEN_TO_ENV = {env.token_begin: env for env in MATH_SIMPLE_ENVS}
ARG_BEGIN_TO_ENV = {arg.token_begin: arg for arg in arg_type}
ARG_REQUIRED = 'required'
ARG_OPTIONAL = 'optional'
RAW_ARG_ENVS = {
    'array',
    'tabular', 'tabular*',
    'tblr', 'tblr*', 'talltblr', 'talltblr*', 'longtblr', 'longtblr*',
}
VERBATIM_COMMANDS = {'verb', 'verb*'}
SPECIAL_COMMAND_SIGNATURE = (
    (ARG_REQUIRED, 1),
    (ARG_OPTIONAL, 2),
    (ARG_REQUIRED, 1),
)
PRIMITIVE_DEF_SIGNATURE = ((ARG_REQUIRED, 2),)
SIGNATURES = {
    'def': PRIMITIVE_DEF_SIGNATURE,
    'textbf': ((ARG_REQUIRED, 1),),
    'section': ((ARG_OPTIONAL, 1), (ARG_REQUIRED, 1)),
    'label': ((ARG_OPTIONAL, -1), (ARG_REQUIRED, 1)),
    'cap': (),
    'cup': (),
    'in': (),
    'notin': (),
    'infty': (),
    'noindent': (),
    'textbackslash': (),
    'textunderscore': (),
    'newcommand': SPECIAL_COMMAND_SIGNATURE,
    'renewcommand': SPECIAL_COMMAND_SIGNATURE,
    'providecommand': SPECIAL_COMMAND_SIGNATURE,
}
SIGNATURE_MODES = {name: MODE_SPECIAL for name in SPECIAL_COMMANDS}


__all__ = ['read_expr', 'read_tex']


class RawArg(TexGroup):
    r"""A raw argument fragment that stringifies without delimiters.

    Primitive macro definitions have unbraced parameter text between the
    control sequence being defined and the braced replacement body, such as
    ``#1`` in ``\def\figref#1{...}``. ``TexArgs`` only includes ``TexGroup``
    and ``TexCmd`` instances in its public argument list, so this lightweight
    group preserves that parameter text without inventing braces on output.
    """

    begin = ''
    end = ''
    name = 'RawArg'

    def __init__(self, *contents, preserve_whitespace=True, position=-1):
        TexEnv.__init__(
            self, self.name, self.begin, self.end, contents,
            preserve_whitespace=preserve_whitespace, position=position)


def read_tex(buf, skip_envs=(), tolerance=0):
    r"""Parse all expressions in buffer

    :param Buffer buf: a buffer of tokens
    :param Tuple[str] skip_envs: environments to skip parsing
    :param int tolerance: error tolerance level (only supports 0 or 1)
    :return: iterable over parsed expressions
    :rtype: Iterable[TexExpr]
    """
    while buf.hasNext():
        yield read_expr(buf,
                        skip_envs=SKIP_ENV_NAMES + skip_envs,
                        tolerance=tolerance)


def make_read_peek(f):
    r"""Make any reader into a peek function.

    The wrapped function still parses the next sequence of tokens in the
    buffer but rolls back the buffer position afterwards.

    >>> from TexSoup.category import categorize
    >>> from TexSoup.tokens import tokenize
    >>> def read(buf):
    ...     buf.forward(3)
    >>> buf = Buffer(tokenize(categorize(r'\item testing \textbf{hah}')))
    >>> buf.position
    0
    >>> make_read_peek(read)(buf)
    >>> buf.position
    0
    """
    @functools.wraps(f)
    def wrapper(buf, *args, **kwargs):
        start = buf.position
        ret = f(buf, *args, **kwargs)
        buf.backward(buf.position - start)
        return ret
    return wrapper


def read_expr(src, skip_envs=(), tolerance=0, mode=MODE_NON_MATH):
    r"""Read next expression from buffer

    :param Buffer src: a buffer of tokens
    :param Tuple[str] skip_envs: environments to skip parsing
    :param int tolerance: error tolerance level (only supports 0 or 1)
    :param str mode: math or not math mode
    :return: parsed expression
    :rtype: [TexExpr, Token]
    """
    c = next(src)
    if c.category in MATH_TOKEN_TO_ENV.keys():
        if mode == MODE_MATH:
            return TexText(c, position=c.position)
        expr = MATH_TOKEN_TO_ENV[c.category]([], position=c.position)
        return read_math_env(src, expr, tolerance=tolerance)
    elif c.category == TC.Escape:
        name, args = read_command(src, tolerance=tolerance, mode=mode)
        if name in VERBATIM_COMMANDS:
            expr = TexCmd(
                name, read_verbatim_contents(src, tolerance=tolerance),
                args=args, position=c.position)
        elif name == 'item':
            if mode == MODE_MATH and tolerance > 0:
                expr = TexCmd(name, args=args, position=c.position)
            else:
                assert mode != MODE_MATH, r'Command \item invalid in math mode.'
                contents = read_item(src, tolerance=tolerance)
                expr = TexCmd(name, contents, args, position=c.position)
        # if we are in "special" mode, we do not attempt to match the `\begin`
        # and `\end`
        elif name == 'begin' and mode != MODE_SPECIAL:
            assert args, 'Begin command must be followed by an env name.'
            expr = TexNamedEnv(
                args[0].string, args=args[1:], position=c.position)
            if expr.name in MATH_ENV_NAMES:
                mode = MODE_MATH
            if expr.name in skip_envs:
                read_skip_env(src, expr)
            else:
                read_env(src, expr, skip_envs=skip_envs,tolerance=tolerance, mode=mode)
        else:
            expr = TexCmd(name, args=args, position=c.position)
        return expr
    if c.category == TC.GroupBegin:
        return read_arg(src, c, tolerance=tolerance)

    assert isinstance(c, Token)
    return TexText(c, position=c.position)


################
# ENVIRONMENTS #
################


def read_item(src, tolerance=0):
    r"""Read the item content. Assumes escape has just been parsed.

    There can be any number of whitespace characters between \item and the
    first non-whitespace character. Any amount of whitespace between subsequent
    characters is also allowed.

    \item can also take an argument.

    :param Buffer src: a buffer of tokens
    :param int tolerance: error tolerance level (only supports 0 or 1)
    :return: contents of the item and any item arguments

    >>> from TexSoup.category import categorize
    >>> from TexSoup.tokens import tokenize
    >>> def read_item_from(string, skip=2):
    ...     buf = tokenize(categorize(string))
    ...     _ = buf.forward(skip)
    ...     return read_item(buf)
    >>> read_item_from(r'\item aaa {bbb} ccc\end{itemize}')
    [' aaa ', BraceGroup('bbb'), ' ccc']
    >>> read_item_from(r'\item aaa \textbf{itemize}\item no')
    [' aaa ', TexCmd('textbf', [BraceGroup('itemize')])]
    >>> read_item_from(r'\item WITCH [nuuu] DOCTORRRR 👩🏻‍⚕️')
    [' WITCH ', '[', 'nuuu', ']', ' DOCTORRRR 👩🏻‍⚕️']
    >>> read_item_from(r'''\begin{itemize}
    ... \item
    ... \item first item
    ... \end{itemize}''', skip=8)
    ['\n']
    >>> read_item_from(r'''\def\itemeqn{\item}''', skip=7)
    []
    """
    extras = []

    while src.hasNext():
        if src.peek().category == TC.Escape:
            cmd_name, _ = make_read_peek(read_command)(
                src, skip=1, arg_spec=(), tolerance=tolerance)
            if cmd_name in ('end', 'item'):
                return extras
        elif src.peek().category == TC.GroupEnd:
            break
        extras.append(read_expr(src, tolerance=tolerance))
    return extras


def unclosed_env_handler(src, expr, end):
    """Handle unclosed environments.

    Currently raises an end-of-file error. In the future, this can be the hub
    for unclosed-environment fault tolerance.

    :param Buffer src: a buffer of tokens
    :param TexExpr expr: expression for the environment
    :param int tolerance: error tolerance level (only supports 0 or 1)
    :param end str: Actual end token (as opposed to expected)
    """
    clo = CharToLineOffset(str(src))
    explanation = 'Instead got %s' % end if end else 'Reached end of file.'
    line, offset = clo(src.position)
    raise EOFError('[Line: %d, Offset: %d] "%s" env expecting %s. %s' % (
        line, offset, expr.name, expr.end, explanation))


def split_display_math_switch(src):
    """Split a queued ``$$`` token into two ``$`` tokens in place.

    This is needed for inputs like ``$1$$2$`` where the middle ``$$`` should
    be interpreted as closing one inline math environment and opening the next.
    """
    token = src.peek()
    if token.category != TC.DisplayMathSwitch:
        return

    first = Token('$', token.position)
    first.category = TC.MathSwitch
    second = Token('$', token.position + 1)
    second.category = TC.MathSwitch

    src.replace(1, first, second)


def read_raw(src, token, stop, tolerance=0, on_unclosed=None):
    """Read raw token text until ``stop`` reports completion.

    This helper is used by verbatim-like parsers that need to consume raw text
    without recursively parsing expressions. ``stop`` is responsible for
    deciding whether the current token finishes the raw segment and may return
    a suffix to be pushed back into the buffer for later parsing.

    :param Buffer src: a buffer of tokens
    :param Token token: first token segment to consume
    :param Callable stop: returns ``(text, remainder, done)`` for each token
    :param int tolerance: error tolerance level (only supports 0 or 1)
    :param Callable on_unclosed: error callback invoked when EOF is reached
        before ``stop`` reports completion
    :rtype: Tuple[str, List[Token]]
    """
    contents = []
    consumed = []

    while token is not None:
        consumed.append(token)
        text, remainder, done = stop(token)
        contents.append(text)
        if done:
            if remainder:
                src.push(Token(
                    remainder,
                    token.position + len(token) - len(remainder),
                    token.category))
            return ''.join(contents), consumed
        if not src.hasNext():
            break
        token = next(src)

    if tolerance == 0 and on_unclosed is not None:
        on_unclosed(consumed)
    return ''.join(contents), consumed


def read_raw_brace_arg(src, tolerance=0):
    """Read a brace-delimited argument without parsing its contents.

    Advances the buffer until the matching closing brace while preserving all
    interior text literally. Nested braces are tracked so the returned group
    still respects balanced brace structure.

    :param Buffer src: a buffer of tokens
    :param int tolerance: error tolerance level (only supports 0 or 1)
    :rtype: BraceGroup
    """
    if not (src.hasNext() and src.peek().category == TC.GroupBegin):
        return None

    begin = next(src)
    depth = 1

    def stop(token):
        nonlocal depth
        if token.category == TC.GroupBegin:
            depth += 1
        elif token.category == TC.GroupEnd:
            depth -= 1
            if depth == 0:
                return '', None, True
        elif token.category == TC.Comment:
            token_text = str(token)
            for index, char in enumerate(token_text):
                if char == '{':
                    depth += 1
                elif char == '}':
                    depth -= 1
                    if depth == 0:
                        return token_text[:index], token_text[index + 1:], True
        return str(token), None, False

    def on_unclosed(consumed):
        clo = CharToLineOffset(str(src))
        line, offset = clo(begin.position)
        raise TypeError(
            '[Line: %d, Offset %d] Malformed argument. First and last elements '
            'must match a valid argument format. In this case, TexSoup'
            ' could not find matching punctuation for: %s.\n'
            'Just finished parsing: %s' %
            (line, offset, begin, [begin] + consumed))

    token = next(src) if src.hasNext() else None
    contents, _ = read_raw(
        src, token, stop, tolerance=tolerance, on_unclosed=on_unclosed)
    return BraceGroup(contents, position=begin.position)


def read_verbatim_contents(src, tolerance=0):
    """Read raw delimited contents for ``\\verb``-style commands.

    ``\\verb`` chooses its delimiter from the next character after the command
    name and then consumes raw text until that same delimiter appears again.
    Any text after the closing delimiter is pushed back into the buffer so it
    can be parsed normally.

    :param Buffer src: a buffer of tokens
    :param int tolerance: error tolerance level (only supports 0 or 1)
    :rtype: List[TexText]
    """
    if not src.hasNext():
        return []

    token = next(src)
    token_text = str(token)
    delimiter = token_text[:1]
    if not delimiter:
        return []

    position = token.position
    contents = [delimiter]

    def stop(token):
        token_text = str(token)
        if delimiter in token_text:
            index = token_text.index(delimiter)
            remainder = token_text[index + 1:]
            return token_text[:index + 1], remainder, True
        return token_text, None, False

    def on_unclosed(_):
        raise EOFError(r'Unclosed \verb command.')

    token = Token(token_text[1:], token.position + 1, token.category)
    raw_text, _ = read_raw(
        src, token, stop, tolerance=tolerance, on_unclosed=on_unclosed)
    contents.append(raw_text)
    return [TexText(''.join(contents), position=position)]


def read_math_env(src, expr, tolerance=0):
    r"""Read the environment from buffer.

    Advances the buffer until right after the end of the environment. Adds
    parsed content to the expression automatically.

    :param Buffer src: a buffer of tokens
    :param TexExpr expr: expression for the environment
    :rtype: TexExpr

    >>> from TexSoup.category import categorize
    >>> from TexSoup.tokens import tokenize
    >>> buf = tokenize(categorize(r'\min_x \|Xw-y\|_2^2'))
    >>> read_math_env(buf, TexMathModeEnv())
    Traceback (most recent call last):
        ...
    EOFError: [Line: 0, Offset: 7] "$" env expecting $. Reached end of file.
    """
    contents = []
    while src.hasNext():
        if expr.token_end == TC.MathSwitch \
                and src.peek().category == TC.DisplayMathSwitch:
            split_display_math_switch(src)
        if _math_env_closes_on(src.peek().category, expr.token_end, tolerance):
            break
        contents.append(read_expr(src, tolerance=tolerance, mode=MODE_MATH))
    if not src.hasNext() or not _math_env_closes_on(src.peek().category, expr.token_end, tolerance):
        if tolerance > 0:
            expr.append(*contents)
            return expr
        unclosed_env_handler(src, expr, src.peek())
    next(src)
    expr.append(*contents)
    return expr


def _math_env_closes_on(category, token_end, tolerance=0):
    if category == token_end:
        return True
    if tolerance <= 0:
        return False
    return (
        (token_end == TC.MathSwitch and category == TC.MathGroupEnd)
        or (token_end == TC.MathGroupEnd and category == TC.MathSwitch)
        or (token_end == TC.DisplayMathSwitch and category == TC.DisplayMathGroupEnd)
        or (token_end == TC.DisplayMathGroupEnd and category == TC.DisplayMathSwitch)
    )


def read_skip_env(src, expr):
    r"""Read the environment from buffer, WITHOUT parsing contents

    Advances the buffer until right after the end of the environment. Adds
    UNparsed content to the expression automatically.

    :param Buffer src: a buffer of tokens
    :param TexExpr expr: expression for the environment
    :rtype: TexExpr

    >>> from TexSoup.category import categorize
    >>> from TexSoup.tokens import tokenize
    >>> buf = tokenize(categorize(r' \textbf{aa \end{foobar}ha'))
    >>> read_skip_env(buf, TexNamedEnv('foobar'))
    TexNamedEnv('foobar', [' \\textbf{aa '], [])
    >>> buf = tokenize(categorize(r' \textbf{aa ha'))
    >>> read_skip_env(buf, TexNamedEnv('foobar'))  #doctest:+ELLIPSIS
    Traceback (most recent call last):
        ...
    EOFError: ...
    """
    def condition(s): return s.startswith('\\end{%s}' % expr.name)
    contents = [src.forward_until(condition, peek=False)]
    if not src.startswith('\\end{%s}' % expr.name):
        unclosed_env_handler(src, expr, src.peek((0, 6)))
    src.forward(5)
    expr.append(*contents)
    return expr


def read_env(src, expr, skip_envs=(), tolerance=0, mode=MODE_NON_MATH):
    r"""Read the environment from buffer.

    Advances the buffer until right after the end of the environment. Adds
    parsed content to the expression automatically.

    :param Buffer src: a buffer of tokens
    :param TexExpr expr: expression for the environment
    :param int tolerance: error tolerance level (only supports 0 or 1)
    :param str mode: math or not math mode
    :rtype: TexExpr

    >>> from TexSoup.category import categorize
    >>> from TexSoup.tokens import tokenize
    >>> buf = tokenize(categorize(' tingtang \\end\n{foobar}walla'))
    >>> read_env(buf, TexNamedEnv('foobar'))
    TexNamedEnv('foobar', [' tingtang '], [])
    >>> buf = tokenize(categorize(' tingtang \\end\n\n{foobar}walla'))
    >>> read_env(buf, TexNamedEnv('foobar')) #doctest: +ELLIPSIS
    Traceback (most recent call last):
        ...
    EOFError: [Line: 0, Offset: 1] ...
    >>> buf = tokenize(categorize(' tingtang \\end\n\n{nope}walla'))
    >>> read_env(buf, TexNamedEnv('foobar'), tolerance=1)  # error tolerance
    TexNamedEnv('foobar', [' tingtang '], [])
    """
    contents = []
    args = None
    while src.hasNext():
        if src.peek().category == TC.Escape:
            name, _ = make_read_peek(read_command)(
                src, skip=1, arg_spec=(), tolerance=tolerance, mode=mode)
            if name == 'end':
                _, args = make_read_peek(read_command)(
                    src, skip=1, tolerance=tolerance, mode=mode)
                break
        contents.append(read_expr(src, skip_envs=skip_envs, tolerance=tolerance, mode=mode))
    error = not src.hasNext() or not args or args[0].string != expr.name
    if error and tolerance == 0:
        unclosed_env_handler(src, expr, src.peek((0, 6)))
    elif not error:
        src.forward(5)
    expr.append(*contents)
    return expr


############
# COMMANDS #
############


# TODO: handle macro-weirdness e.g., \def\blah[#1][[[[[[[[#2{"#1 . #2"}
def read_args(src, arg_spec=None, args=None, tolerance=0,
        mode=MODE_NON_MATH):
    r"""Read all arguments from buffer.

    This function assumes that the command name has already been parsed.
    When an explicit argument specification is provided, arguments are read
    according to an ordered sequence of ``(kind, count)`` pairs, where
    ``kind`` is either ``required`` or ``optional``. If no specification is
    provided, TexSoup falls back to its generic command-argument heuristic.

    :param Buffer src: a buffer of tokens
    :param Iterable[Tuple[str, Optional[int]]] arg_spec: ordered arg phases
    :param TexArgs args: existing arguments to extend
    :param int tolerance: error tolerance level (only supports 0 or 1)
    :param str mode: math or not math mode
    :return: parsed arguments
    :rtype: TexArgs

    >>> from TexSoup.category import categorize
    >>> from TexSoup.tokens import tokenize
    >>> test = lambda s, *a, **k: read_args(tokenize(categorize(s)), *a, **k)
    >>> test('[walla]{walla}{ba]ng}')  # 'regular' arg parse
    [BracketGroup('walla'), BraceGroup('walla'), BraceGroup('ba', ']', 'ng')]
    >>> test('\t[wa]\n{lla}\n\n{b[ing}')  # interspersed spacers + 2 newlines
    [BracketGroup('wa'), BraceGroup('lla')]
    >>> test('\t[\t{a]}bs', ((ARG_REQUIRED, 2),))  # use char as arg
    [BraceGroup('['), BraceGroup('a', ']')]
    >>> test('\n[hue]\t[\t{a]}', ((ARG_OPTIONAL, 1), (ARG_REQUIRED, 2)))
    [BracketGroup('hue'), BraceGroup('['), BraceGroup('a', ']')]
    >>> test('\t\\item')
    []
    >>> test('   \t    \n\t \n{bingbang}')
    []
    >>> test('[tempt]{ing}[WITCH]{doctorrrr}', ())
    []
    """
    args = args or TexArgs()
    readers = {
        ARG_OPTIONAL: read_arg_optional,
        ARG_REQUIRED: read_arg_required,
    }

    if arg_spec is None:
        n_optional = 0 if mode == MODE_MATH else -1
        arg_spec = (
            (ARG_OPTIONAL, n_optional),
            (ARG_REQUIRED, -1),
            (ARG_OPTIONAL, n_optional),
            (ARG_REQUIRED, -1),
        )

    for arg_kind, count in arg_spec:
        readers[arg_kind](src, args, count, tolerance=tolerance, mode=mode)
    return args


def read_arg_optional(
        src, args, n_optional=-1, tolerance=0, mode=MODE_NON_MATH):
    """Read next optional argument from buffer.

    If the command has remaining optional arguments, look for:

       a. A spacer. Skip the spacer if it exists.
       b. A bracket delimiter. If the optional argument is bracket-delimited,
          the contents of the bracket group are used as the argument.

    :param Buffer src: a buffer of tokens
    :param TexArgs args: existing arguments to extend
    :param int n_optional: Number of optional arguments. If < 0, all valid
                           bracket groups will be captured.
    :param int tolerance: error tolerance level (only supports 0 or 1)
    :param str mode: math or not math mode
    :return: number of remaining optional arguments
    :rtype: int
    """
    while n_optional != 0:
        spacer = read_spacer(src)
        if not (src.hasNext() and src.peek().category == TC.BracketBegin):
            if spacer:
                src.backward(1)
            break
        args.append(read_arg(src, next(src), tolerance=tolerance, mode=mode))
        n_optional -= 1
    return n_optional


def read_arg_required(
        src, args, n_required=-1, tolerance=0, mode=MODE_NON_MATH):
    r"""Read next required argument from buffer.

    If the command has remaining required arguments, look for:

       a. A spacer. Skip the spacer if it exists.
       b. A curly-brace delimiter. If the required argument is brace-delimited,
          the contents of the brace group are used as the argument.
       c. Spacer or not, if a brace group is not found, simply use the next
          character, unless it is a backslash, in which case use the full command name

    :param Buffer src: a buffer of tokens
    :param TexArgs args: existing arguments to extend
    :param int n_required: Number of required arguments. If < 0, all valid
                           brace groups will be captured.
    :param int tolerance: error tolerance level (only supports 0 or 1)
    :param str mode: math or not math mode
    :return: number of remaining optional arguments
    :rtype: int

    >>> from TexSoup.category import categorize
    >>> from TexSoup.tokens import tokenize
    >>> buf = tokenize(categorize('{wal]la}\n{ba ng}\n'))
    >>> args = TexArgs()
    >>> read_arg_required(buf, args)  # 'regular' arg parse
    -3
    >>> args
    [BraceGroup('wal', ']', 'la'), BraceGroup('ba ng')]
    >>> buf.hasNext() and buf.peek().category == TC.MergedSpacer
    True
    """
    while n_required != 0 and src.hasNext():
        spacer = read_spacer(src)

        if src.hasNext() and src.peek().category == TC.GroupBegin:
            args.append(read_arg(
                src, next(src), tolerance=tolerance, mode=mode))
            n_required -= 1
            continue
        elif src.hasNext() and n_required > 0:
            next_token = next(src)
            if next_token.category == TC.Escape:
                name, _ = read_command(
                    src, arg_spec=(), tolerance=tolerance, mode=mode)
                args.append(TexCmd(name, position=next_token.position))
            else:
                args.append('{%s}' % next_token)
            n_required -= 1
            continue

        if spacer:
            src.backward(1)
        break
    return n_required


def read_arg(src, c, tolerance=0, mode=MODE_NON_MATH):
    r"""Read the argument from buffer.

    Advances buffer until right before the end of the argument.

    :param Buffer src: a buffer of tokens
    :param str c: argument token (starting token)
    :param int tolerance: error tolerance level (only supports 0 or 1)
    :param str mode: math or not math mode
    :return: the parsed argument
    :rtype: TexGroup

    >>> from TexSoup.category import categorize
    >>> from TexSoup.tokens import tokenize
    >>> s = r'''{\item\abovedisplayskip=2pt\abovedisplayshortskip=0pt~\vspace*{-\baselineskip}}'''
    >>> buf = tokenize(categorize(s))
    >>> read_arg(buf, next(buf))
    BraceGroup(TexCmd('item'))
    >>> buf = tokenize(categorize(r'{\incomplete! [complete]'))
    >>> read_arg(buf, next(buf), tolerance=1)
    BraceGroup(TexCmd('incomplete'), '! ', '[', 'complete', ']')
    """
    content = [c]
    arg = ARG_BEGIN_TO_ENV[c.category]
    while src.hasNext():
        if src.peek().category == arg.token_end:
            src.forward()
            return arg(*content[1:], position=c.position)
        else:
            content.append(read_expr(src, tolerance=tolerance, mode=mode))

    if tolerance == 0:
        clo = CharToLineOffset(str(src))
        line, offset = clo(c.position)
        raise TypeError(
            '[Line: %d, Offset %d] Malformed argument. First and last elements '
            'must match a valid argument format. In this case, TexSoup'
            ' could not find matching punctuation for: %s.\n'
            'Just finished parsing: %s' %
            (line, offset, c, content))
    return arg(*content[1:], position=c.position)


def read_spacer(buf):
    r"""Extracts the next spacer, if there is one, before non-whitespace

    Define a spacer to be a contiguous string of only whitespace, with at most
    one line break.

    >>> from TexSoup.category import categorize
    >>> from TexSoup.tokens import tokenize
    >>> read_spacer(Buffer(tokenize(categorize('   \t    \n'))))
    '   \t    \n'
    >>> read_spacer(Buffer(tokenize(categorize('   \t    \n\t \n  \t\n'))))
    '   \t    \n\t '
    >>> read_spacer(Buffer(tokenize(categorize('{'))))
    ''
    >>> read_spacer(Buffer(tokenize(categorize('   \t    \na'))))
    ''
    >>> read_spacer(Buffer(tokenize(categorize('   \t    \n\t \n  \t\na'))))
    '   \t    \n\t '
    """
    if buf.hasNext() and buf.peek().category == TC.MergedSpacer:
        return next(buf)
    return ''


def read_begin_env_args(buf, tolerance=0, mode=MODE_NON_MATH):
    r"""Read ``\begin`` arguments, with raw parsing for column specs.

    The first required argument is always the environment name. Certain
    environments, such as ``tabular`` and ``array``, expect their following
    column-spec argument to be treated as raw text because syntax like
    ``>{$}`` is metadata rather than nested math to parse.

    :param Buffer buf: a buffer of tokens
    :param int tolerance: error tolerance level (only supports 0 or 1)
    :param str mode: math or not math mode
    :rtype: TexArgs
    """
    args = TexArgs()
    read_arg_required(buf, args, 1, tolerance=tolerance, mode=mode)
    if not args:
        return args

    env_name = str(args[0].string)
    if env_name in SKIP_ENV_NAMES:
        return args

    if env_name in RAW_ARG_ENVS:
        read_arg_optional(buf, args, 1, tolerance=tolerance, mode=mode)
        spacer = read_spacer(buf)
        raw_arg = read_raw_brace_arg(buf, tolerance=tolerance)
        if raw_arg is None and spacer:
            buf.backward(1)
        else:
            if spacer:
                args.append(spacer)
            if raw_arg is not None:
                args.append(raw_arg)
        return args

    return read_args(buf, args=args, tolerance=tolerance, mode=mode)


def read_raw_command_args(buf, tolerance=0, mode=MODE_NON_MATH):
    r"""Read a command's next brace argument as raw text.

    This is used for commands like ``\url`` whose argument contents should not
    be recursively parsed.

    :param Buffer buf: a buffer of tokens
    :param int tolerance: error tolerance level (only supports 0 or 1)
    :param str mode: math or not math mode
    :rtype: TexArgs
    """
    del mode
    args = TexArgs()
    spacer = read_spacer(buf)
    raw_arg = read_raw_brace_arg(buf, tolerance=tolerance)
    if raw_arg is None and spacer:
        buf.backward(1)
    else:
        if spacer:
            args.append(spacer)
        if raw_arg is not None:
            args.append(raw_arg)
    return args


def read_raw_required_args(buf, n_required, tolerance=0):
    args = TexArgs()
    while n_required > 0:
        spacer = read_spacer(buf)
        raw_arg = read_raw_brace_arg(buf, tolerance=tolerance)
        if raw_arg is None:
            if spacer:
                buf.backward(1)
            break
        if spacer:
            args.append(spacer)
        args.append(raw_arg)
        n_required -= 1
    return args


def append_raw_brace_arg(buf, args, tolerance=0):
    """Append the next brace-delimited argument without parsing its contents."""
    spacer = read_spacer(buf)
    raw_arg = read_raw_brace_arg(buf, tolerance=tolerance)
    if raw_arg is None:
        if spacer:
            buf.backward(1)
        return False
    if spacer:
        args.append(spacer)
    args.append(raw_arg)
    return True


def read_single_raw_arg(buf, tolerance=0, mode=MODE_NON_MATH):
    del mode
    return read_raw_required_args(buf, 1, tolerance=tolerance)


def read_named_style_args(buf, tolerance=0, mode=MODE_NON_MATH):
    del mode
    return read_raw_required_args(buf, 2, tolerance=tolerance)


def read_mintinline_args(buf, tolerance=0, mode=MODE_NON_MATH):
    r"""Read ``\mintinline`` options plus language/code args.

    The code argument is verbatim-like; parsing it recursively lets literal
    characters such as ``$`` open math spans that can swallow the rest of a
    document.
    """
    args = TexArgs()
    read_arg_optional(buf, args, 1, tolerance=tolerance, mode=mode)
    append_raw_brace_arg(buf, args, tolerance=tolerance)
    append_raw_brace_arg(buf, args, tolerance=tolerance)
    return args


MATH_CONTROL_SEQUENCE_TOKENS = {
    TC.MathSwitch,
    TC.DisplayMathSwitch,
    TC.MathGroupBegin,
    TC.MathGroupEnd,
    TC.DisplayMathGroupBegin,
    TC.DisplayMathGroupEnd,
}


def read_macro_target_arg(buf, args, tolerance=0, mode=MODE_NON_MATH):
    r"""Read the control sequence being defined without parsing it as math."""
    spacer = read_spacer(buf)
    raw_arg = read_raw_brace_arg(buf, tolerance=tolerance)
    if raw_arg is not None:
        if spacer:
            args.append(spacer)
        args.append(raw_arg)
        return
    if spacer:
        buf.backward(1)
    read_arg_required(buf, args, 1, tolerance=tolerance, mode=mode)


def read_latex_definition_args(buf, tolerance=0, mode=MODE_NON_MATH):
    r"""Read LaTeX macro-definition arguments with a raw replacement body."""
    args = TexArgs()
    read_macro_target_arg(buf, args, tolerance=tolerance, mode=mode)
    read_arg_optional(buf, args, 2, tolerance=tolerance, mode=mode)
    append_raw_brace_arg(buf, args, tolerance=tolerance)
    return args


def read_math_operator_definition_args(buf, tolerance=0, mode=MODE_NON_MATH):
    r"""Read ``\DeclareMathOperator`` arguments with a raw printed form."""
    args = TexArgs()
    read_macro_target_arg(buf, args, tolerance=tolerance, mode=mode)
    append_raw_brace_arg(buf, args, tolerance=tolerance)
    return args


def read_environment_definition_args(buf, tolerance=0, mode=MODE_NON_MATH):
    r"""Read ``\newenvironment``-style declarations with raw bodies."""
    args = TexArgs()
    read_macro_target_arg(buf, args, tolerance=tolerance, mode=mode)
    read_arg_optional(buf, args, 2, tolerance=tolerance, mode=mode)
    append_raw_brace_arg(buf, args, tolerance=tolerance)
    append_raw_brace_arg(buf, args, tolerance=tolerance)
    return args


def read_document_environment_definition_args(buf, tolerance=0, mode=MODE_NON_MATH):
    r"""Read xparse document-environment declarations with raw bodies."""
    args = TexArgs()
    read_macro_target_arg(buf, args, tolerance=tolerance, mode=mode)
    append_raw_brace_arg(buf, args, tolerance=tolerance)
    append_raw_brace_arg(buf, args, tolerance=tolerance)
    append_raw_brace_arg(buf, args, tolerance=tolerance)
    return args


def read_primitive_definition_args(buf, tolerance=0, mode=MODE_NON_MATH):
    r"""Read primitive ``\def``-style arguments with a raw replacement body."""
    spacer = read_spacer(buf)
    can_read_raw_definition = (
        buf.hasNext()
        and (buf.peek().category == TC.Escape
             or buf.peek().category in MATH_CONTROL_SEQUENCE_TOKENS))
    if spacer:
        buf.backward(1)
    if not can_read_raw_definition:
        return read_args(
            buf, arg_spec=PRIMITIVE_DEF_SIGNATURE, tolerance=tolerance,
            mode=mode)

    args = TexArgs()
    if buf.peek().category in MATH_CONTROL_SEQUENCE_TOKENS:
        token = next(buf)
        args.append(RawArg(str(token), position=token.position))
    else:
        read_arg_required(buf, args, 1, tolerance=tolerance, mode=mode)

    params = []
    position = -1
    while buf.hasNext() and buf.peek().category != TC.GroupBegin:
        token = next(buf)
        if position < 0:
            position = token.position
        params.append(str(token))
    if params:
        args.append(RawArg(''.join(params), position=position))

    append_raw_brace_arg(buf, args, tolerance=tolerance)
    return args


SPECIAL_ARG_READERS = {
    'author': read_single_raw_arg,
    'begin': read_begin_env_args,
    'DeclareMathOperator': read_math_operator_definition_args,
    'DeclareMathOperator*': read_math_operator_definition_args,
    'DeclareDocumentEnvironment': read_document_environment_definition_args,
    'def': read_primitive_definition_args,
    'edef': read_primitive_definition_args,
    'gdef': read_primitive_definition_args,
    'lstdefinestyle': read_named_style_args,
    'lstset': read_single_raw_arg,
    'mdfdefinestyle': read_named_style_args,
    'mintinline': read_mintinline_args,
    'NewDocumentEnvironment': read_document_environment_definition_args,
    'newenvironment': read_environment_definition_args,
    'newenvironment*': read_environment_definition_args,
    'newcommand': read_latex_definition_args,
    'newcommand*': read_latex_definition_args,
    'providecommand': read_latex_definition_args,
    'providecommand*': read_latex_definition_args,
    'provideenvironment': read_environment_definition_args,
    'provideenvironment*': read_environment_definition_args,
    'renewcommand': read_latex_definition_args,
    'renewcommand*': read_latex_definition_args,
    'RenewDocumentEnvironment': read_document_environment_definition_args,
    'renewenvironment': read_environment_definition_args,
    'renewenvironment*': read_environment_definition_args,
    'url': read_raw_command_args,
    'xdef': read_primitive_definition_args,
}


def read_command(buf, arg_spec=None, skip=0,
                 tolerance=0, mode=MODE_NON_MATH):
    r"""Parses command and all arguments. Assumes escape has just been parsed.

    No whitespace is allowed between escape and command name. e.g.,
    :code:`\ textbf` is a backslash command, then text :code:`textbf`. Only
    :code:`\textbf` is the bold command.

    >>> from TexSoup.category import categorize
    >>> from TexSoup.tokens import tokenize
    >>> buf = Buffer(tokenize(categorize('\\sect  \t    \n\t{wallawalla}')))
    >>> next(buf)
    '\\'
    >>> read_command(buf)
    ('sect', [BraceGroup('wallawalla')])
    >>> buf = Buffer(tokenize(categorize('\\sect  \t   \n\t \n{bingbang}')))
    >>> _ = next(buf)
    >>> read_command(buf)
    ('sect', [])
    >>> buf = Buffer(tokenize(categorize('\\sect{ooheeeee}')))
    >>> _ = next(buf)
    >>> read_command(buf)
    ('sect', [BraceGroup('ooheeeee')])
    >>> buf = Buffer(tokenize(categorize(r'\item aaa {bbb} ccc\end{itemize}')))
    >>> read_command(buf, skip=1)
    ('item', [])
    >>> buf.peek()
    ' aaa '

    # >>> buf = Buffer(tokenize(categorize('\\sect abcd')))
    # >>> _ = next(buf)
    # >>> read_command(buf)
    # ('sect', ('a',))
    """
    for _ in range(skip):
        next(buf)

    name = next(buf)
    if arg_spec is None and name.text in SPECIAL_ARG_READERS:
        return name, SPECIAL_ARG_READERS[name.text](
            buf, tolerance=tolerance, mode=mode)

    if arg_spec is None:
        signature = SIGNATURES.get(name)
    else:
        signature = arg_spec

    arg_mode = SIGNATURE_MODES.get(name.text, mode)
    args = read_args(buf, arg_spec=signature, tolerance=tolerance, mode=arg_mode)
    return name, args
