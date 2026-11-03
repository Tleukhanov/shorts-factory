"""Programmatic chess board rendering for vertical video.

Chess-specific formats do not need footage: the board *is* the visual. So it is
drawn here rather than sourced, which keeps the pipeline licence-free,
deterministic, and free of anyone else's screen recording.

Rendering is PIL rather than SVG because nothing in the dependency set can
rasterise SVG at runtime and PIL gives direct control over the 1080x1920
vertical frame: the board sits high, a header sits above it and an information
band below, so a 9:16 frame carries the position and the words about it at the
same time instead of only the board.

The pieces are the cburnett set (the default Lichess set), pre-rendered to PNG
from the CC BY-SA 3.0 SVGs in ``assets/cburnett_svg``.  The unicode glyph path
stays as a fallback for installations that strip the PNG assets.
"""

from __future__ import annotations

import dataclasses
import functools
import logging
from pathlib import Path

log = logging.getLogger(__name__)

FRAME_W = 1080
FRAME_H = 1920
BOARD = 1000
# Vertical layout. The board used to be centred, which put 460px of empty black
# above and below it -- measured on a rendered highlight clip, the board
# occupied 52% of a 9:16 frame and a third of the picture did nothing. The board
# now sits high and the freed space below becomes the information band.
HEADER_TOP = 0
HEADER_HEIGHT = 300
BOARD_TOP = HEADER_HEIGHT
INFO_TOP = BOARD_TOP + BOARD + 40
INFO_HEIGHT = FRAME_H - INFO_TOP

# Information band. The sizes are absolute pixels for a 1080x1920 frame: the
# caption sizes above (64/44) were chosen when text was a caption and are
# unreadable once the text is the headline of the frame. Hook is tried largest
# first and steps down until the wrapped block fits the band, so a long hook
# shrinks instead of running off the frame.
INFO_PAD = 60
HOOK_SIZES = (76, 72, 68, 64, 60, 56, 52, 48, 44)
HOOK_MIN_SIZE = HOOK_SIZES[-1]
DETAIL_SIZES = (44, 40, 36, 32)
MOVE_SIZES = (52, 48, 44, 40, 36, 32)
PROGRESS_SIZE = 34
PLAYERS_SIZE = 34
# Whose move it is. A shade above the players line: it is what the viewer reads
# first when the board changes, and at 34px next to a 76px hook it was being
# lost against the background.
TURN_SIZE = 40
BOTTOM_TEXT_SIZE = 44
# Floor for the gap between two band rows. Whatever the rows leave over is shared
# out above this floor, so the band fills its region instead of leaving behind the
# black hole the centred board used to have under itself.
BAND_GAP = 26
_ARROW = "→"
_ARROW_FALLBACK = "->"
# A notation ending in '+' prints against a signed number as "Qd6++0.4" without
# a separator, so the move and the swing it caused are joined by a dot.
_MOVE_SEPARATOR = "   ·   "
_MOVE_STROKE = 2

# Muted palette: the board must not fight the caption text for attention.
# Lichess's brown board. The previous pair was a desaturated grey with a purple
# cast (124,116,108) against a cream, and that mud is most of why the frames read
# as clipart rather than as a chess board: the pieces were fine, the squares
# under them were not. These are the values lichess.org ships as its default.
LIGHT_SQUARE = (240, 217, 181)  # #f0d9b5
DARK_SQUARE = (181, 136, 99)  # #b58863
BOARD_EDGE = (120, 90, 68)
BOARD_FRAME = (138, 111, 77)  # #8a6f4d, the frame used by the trainer
BOARD_FRAME_WIDTH = 10
BOARD_BG = (18, 18, 20)
TEXT_MAIN = (245, 245, 245)
TEXT_DIM = (150, 150, 155)
ACCENT_BAD = (214, 74, 62)
ACCENT_GOOD = (96, 178, 116)
ACCENT_ALT = (90, 190, 215)
HIGHLIGHT = (205, 210, 106)  # #cdd26a, the trainer's last-move highlight
HIGHLIGHT_BAD = (220, 80, 75)
HIGHLIGHT_GOOD = (96, 178, 116)
HIGHLIGHT_ALT = (90, 190, 215)
# Coordinates are drawn in the opposite square colour, exactly like the trainer.
COORD_ON_LIGHT = (181, 136, 99)
COORD_ON_DARK = (240, 217, 181)
# Lichess-style move arrow: green, semi-transparent, thick shaft, solid head.
ARROW_COLOR = (21, 120, 27)  # #15781b
ARROW_BAD = (180, 30, 30)
ARROW_ALT = (0, 120, 160)
ARROW_ALPHA = 200
# Grayscale board for the viral "drama" format: coloured highlights and arrows
# are the only colour on the frame, so they read from across a thumbnail.
MONO_LIGHT_SQUARE = (222, 222, 222)
MONO_DARK_SQUARE = (128, 128, 128)
MONO_BOARD_FRAME = (74, 74, 78)
MONO_BOARD_EDGE = (112, 112, 116)
MONO_COORD_ON_LIGHT = (88, 88, 88)
MONO_COORD_ON_DARK = (205, 205, 205)
# The meme headline sits above the board and is tried largest first, the same
# way the information band fits its hook.
HEADLINE_SIZES = (120, 112, 104, 96, 88, 80, 72)
HEADLINE_STROKE = 9
# Move annotations ("!!", "??", "!?") are a comment mark, not a caption: they
# sit next to the board at a size that survives a phone screen.  The thick dark
# stroke and badge behind them keep the mark readable against the headline.
ANNOTATION_SIZE = 110
ANNOTATION_STROKE = 10
# Lichess analysis badges.  These are the exact annotation vocabulary the
# Lichess study/analysis board uses: !, ?, !!, ??, !?, ?!, #, plus the
# only-move and zugzwang marks.  A move is marked on its *destination* square
# with a small round badge.  The same kind drives the square highlight so a
# blunder reads red everywhere.
BADGE_GOOD = (127, 166, 80)  # #7fa650, Lichess green
BADGE_BRILLIANT = BADGE_GOOD
BADGE_INTERESTING = BADGE_GOOD
BADGE_MISTAKE = (230, 145, 44)  # #e6912c, Lichess orange
BADGE_DUBIOUS = (214, 79, 138)  # #d64f8a, Lichess pink
BADGE_BLUNDER = (202, 52, 49)  # #ca3431, Lichess red
BADGE_MATE = BADGE_BLUNDER
BADGE_ONLY = (74, 74, 74)
BADGE_ZUGZWANG = (74, 74, 74)
BADGE_COLORS = {
    "good": BADGE_GOOD,
    "brilliant": BADGE_BRILLIANT,
    "interesting": BADGE_INTERESTING,
    "mistake": BADGE_MISTAKE,
    "dubious": BADGE_DUBIOUS,
    "blunder": BADGE_BLUNDER,
    "mate": BADGE_MATE,
    "only": BADGE_ONLY,
    "zugzwang": BADGE_ZUGZWANG,
    # Backward-compatible aliases used by the earlier drama frames.
    "great": BADGE_GOOD,
    "best": BADGE_GOOD,
    "excellent": BADGE_GOOD,
    "book": BADGE_ONLY,
    "inaccuracy": BADGE_DUBIOUS,
}
# The glyph may be one or two characters; the renderer fits it to the circle.
BADGE_SYMBOLS = {
    "good": "!",
    "brilliant": "!!",
    "interesting": "!?",
    "mistake": "?",
    "dubious": "?!",
    "blunder": "??",
    "mate": "#",
    "only": "□",
    "zugzwang": "⦿",
    # Backward-compatible aliases.
    "great": "!",
    "best": "!",
    "excellent": "!",
    "book": "B",
    "inaccuracy": "?!",
}
# Diameter as a share of a square.  Lichess's badges are large solid circles
# with a white edge; at 0.26 they read as tiny dots on a phone.
BADGE_SIZE = 0.40
BADGE_BORDER = (255, 255, 255)
# Punch-in bounds for the drama edit.  Past 1.12 the headline and the info band
# lose too many pixels to stay legible on a phone, and below 1.0 there is no
# punch at all.
ZOOM_MIN = 1.0
ZOOM_MAX = 1.12

# cburnett is the default Lichess piece set.  The PNGs are pre-rendered from the
# CC BY-SA 3.0 SVGs that ship next to them; see assets/cburnett_svg/README.md.
_PIECE_DIR = Path(__file__).with_name("assets") / "cburnett"

PIECE_GLYPHS = {
    "K": "♔",
    "Q": "♕",
    "R": "♖",
    "B": "♗",
    "N": "♘",
    "P": "♙",
    "k": "♚",
    "q": "♛",
    "r": "♜",
    "b": "♝",
    "n": "♞",
    "p": "♟",
}

# No single system font is guaranteed to carry both Cyrillic and the chess block:
# on Windows, Segoe UI has Cyrillic and no chess pieces, while Segoe UI Symbol
# has the pieces and no Cyrillic. So the two are resolved separately and a font
# is only accepted for a role once its cmap has actually been verified.
_TEXT_FONTS = (
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)
_PIECE_FONTS = (
    "C:/Windows/Fonts/seguisym.ttf",
    "C:/Windows/Fonts/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
# Badge symbols want weight: at ~30px across, a regular "?" disappears next to
# the piece underneath it.  Bold is tried first, then the regular text faces as
# a fallback for symbols such as the star that a bold file might omit.
_BOLD_FONTS = (
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)
_BADGE_FONTS = _BOLD_FONTS + _TEXT_FONTS
_PROBE_CHAR = "\ue123"  # private-use, guaranteed absent from these fonts


def _load(path: str | Path, size: int):
    from PIL import ImageFont

    return ImageFont.truetype(str(path), size)


def _covers(font, char: str) -> bool:
    """Whether *font* really has *char*, by comparing against an absent codepoint.

    Comparing rendered bitmaps is the only portable check here -- PIL exposes no
    cmap API. A missing glyph renders as .notdef, identical to any other missing
    codepoint, so byte-comparing against a private-use probe is reliable.
    """
    try:
        mask = font.getmask(char)
        ref = font.getmask(_PROBE_CHAR)
        if mask.size != ref.size:
            return True
        return bytes(mask) != bytes(ref)
    except Exception:
        return False


@functools.lru_cache(maxsize=64)
def _piece_image(filename: str, size: int):
    """Load and scale a cburnett piece PNG, or ``None`` when it is missing."""
    try:
        from PIL import Image
    except Exception:
        return None
    path = _PIECE_DIR / filename
    if not path.is_file():
        return None
    try:
        with Image.open(path) as img:
            return img.convert("RGBA").resize((size, size), Image.LANCZOS)
    except Exception:
        log.debug("could not load piece image %s", path, exc_info=True)
        return None


@functools.lru_cache(maxsize=256)
def _first_font(paths: tuple[str, ...], size: int, probe: str):
    # Cached because the band tries a hook at up to nine sizes per frame and
    # loading a TTF is milliseconds each; PIL font objects are immutable once
    # loaded, so the same object can be handed to every draw call.
    for path in paths:
        if not Path(path).is_file():
            continue
        try:
            font = _load(path, size)
        except Exception:
            continue
        if _covers(font, probe):
            return font
    try:
        import matplotlib

        bundled = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf"
        if bundled.is_file():
            font = _load(bundled, size)
            if _covers(font, probe):
                return font
    except Exception:
        log.debug("matplotlib font fallback unavailable", exc_info=True)
    log.warning("No font covering %r found; falling back to PIL default", probe)
    from PIL import ImageFont

    return ImageFont.load_default()


@dataclasses.dataclass(frozen=True)
class FrameInfo:
    """What the viewer is told while the board is on screen.

    Rendered into the band below the board. Every field is optional so a format
    that only wants one line does not have to blank the rest, and so a caller
    that passes nothing keeps the old behaviour exactly.
    """

    hook: str = ""
    """The headline. What is happening, in a viewer question shape."""

    detail: str = ""
    """Supporting line under the hook: why the move matters."""

    progress: str = ""
    """Where we are in the game, e.g. ``24 / 134``."""

    eval_before: str = ""
    """Evaluation before the move, sign from the mover's side."""

    eval_after: str = ""
    """Evaluation after it. Together with *eval_before* this is the proof."""

    players: str = ""
    """Who is playing, e.g. ``Карлусен — Непомнящий``."""

    moved_san: str = ""
    """The move in algebraic notation, e.g. ``Qd6+``."""

    turn_side: str = ""
    """Whose move it is, e.g. ``ход чёрных``.

    Not decoration. A chess position without the side to move says half of
    nothing: the same board with the turn flipped is a completely different game
    state, and a viewer watching a clip with no side named cannot tell a normal
    move from the opponent walking into something. Rendered next to the board, at
    the size of the players line.
    """

    turn_name: str = ""
    """The player to move. Empty when the name is unknown."""


@dataclasses.dataclass(frozen=True)
class FrameSpec:
    """One rendered frame of a board state."""

    fen: str
    top_text: str
    bottom_text: str
    accent: str = "neutral"  # "bad" | "good" | "neutral"
    highlight_squares: tuple[str, ...] = ()
    arrow: tuple[str, str] | None = None
    # Engine evaluation, shown so the claim on screen is checkable rather than
    # asserted. A chess audience verifies, and a number is what they can check.
    eval_text: str | None = None
    # The information band below the board. None keeps the frame exactly as it
    # was before this field existed, so the deciding, opening, endgame and
    # challenge formats are unaffected.
    info: FrameInfo | None = None
    # Optional call-to-action card rendered full-screen instead of a board.
    # Tuple is (top_text, bottom_text).  Used for the final frame of tactics
    # and story formats without needing a separate renderer.
    cta: tuple[str, str] | None = None
    # Sliding-piece animation: (piece_symbol, from_square, to_square, progress).
    # When set, the named piece is drawn at an interpolated position and its
    # source/destination squares are suppressed (see ``hidden_squares``).
    moving: tuple[str, str, str, float] | None = None
    # Squares whose pieces are not drawn on this frame.  Used by the animation
    # so the moving piece does not appear twice.
    hidden_squares: tuple[str, ...] = ()
    # Board palette: ``classic`` keeps the brown Lichess board, ``mono`` draws
    # grayscale squares so coloured highlights and arrows pop.  Additive, so
    # every existing caller keeps the classic look.
    board_style: str = "classic"  # "classic" | "mono"
    # Arrow colour: green for the answer, red for a wrong move, cyan for an
    # alternative line.  The old constant stays the default.
    arrow_color: str = "good"  # "good" | "bad" | "alt"
    # A large centred meme headline drawn above the board, e.g. "НАЙДИ МАТ".
    # Optional: None leaves the frame exactly as before.
    headline: str | None = None
    headline_color: str = "bad"  # "bad" | "good" | "neutral"
    # A move comment mark rendered as a badge at the board's top-right, e.g.
    # "!!" for the answer or "??" for a trap.  Optional: None draws nothing.
    # Kept for callers from before the square badges existed; a frame that sets
    # ``badge`` never draws this, because the badge is the chess.com vocabulary.
    annotation: str | None = None
    annotation_color: str = "bad"  # "bad" | "good" | "neutral"
    # Chess.com-style badge on a named square: ``(square, kind)``, e.g.
    # ``("e4", "blunder")`` or ``("d5", "brilliant")``.  The kind chooses both
    # the circle colour and its symbol (see :data:`BADGE_COLORS` and
    # :data:`BADGE_SYMBOLS`).  An unknown square or kind is skipped silently.
    badge: tuple[str, str] | None = None
    # Camera punch: 1.0 is no zoom.  Values above 1 crop a smaller window around
    # ``zoom_center`` and scale it back up, which is what makes the drama edit's
    # wrong-move and answer beats land.  Clamped to ZOOM_MAX when rendered so a
    # stray config value cannot turn the board into unreadable pixels.
    zoom: float = 1.0
    # Pixel centre of the punch, defaulting to the board centre.  Only the board
    # is zoomed for CTA frames, which return before this is ever read.
    zoom_center: tuple[float, float] | None = None


def _accent_color(accent: str):
    """Fill for text that follows an accent name.

    The chess.com badge kinds are accepted here too, so a frame can say
    ``accent="brilliant"`` once instead of repeating a colour in every caller.
    """
    return {
        **BADGE_COLORS,
        "bad": ACCENT_BAD,
        "good": ACCENT_GOOD,
        "alt": ACCENT_ALT,
    }.get(accent, TEXT_MAIN)


def _highlight_color(accent: str):
    """Square highlight colour for an accent name.

    ``neutral`` keeps the trainer's yellow, so old frames are untouched; the
    drama format uses the accent itself so a red wrong-move frame and a green
    answer frame are distinguishable at a glance.  Badge-kind names map to the
    badge colour, which is what makes the highlight and the circle agree.
    """
    return {
        **BADGE_COLORS,
        "bad": HIGHLIGHT_BAD,
        "alt": HIGHLIGHT_ALT,
    }.get(accent, HIGHLIGHT)


def _badge_color(kind: str):
    """RGB for a badge kind, or ``None`` when the kind is unknown."""
    return BADGE_COLORS.get(kind)


def _badge_square(square: str) -> tuple[int, int] | None:
    """``(col, row)`` for a square name, or ``None`` when it is not a square.

    Deliberately does not consult a board: a badge on a square that happens to
    be empty is still meaningful, and a malformed name from a config or a caller
    must be skipped rather than crash the render.
    """
    try:
        name = str(square).strip().lower()
        if len(name) != 2 or not ("a" <= name[0] <= "h") or not ("1" <= name[1] <= "8"):
            return None
        return ord(name[0]) - ord("a"), 8 - int(name[1])
    except (TypeError, ValueError):
        return None


def _fit_badge_font(draw, symbol: str, radius: float):
    """The largest bold font whose *symbol* fits inside a badge *radius*."""
    size = max(10, int(round(radius * 1.5)))
    inner = radius * 1.65  # a little inside the white ring
    font = _first_font(_BADGE_FONTS, size, symbol)
    while size > 9 and _text_extent(draw, symbol, font)[0] > inner:
        size -= 1
        font = _first_font(_BADGE_FONTS, size, symbol)
    return font


def _draw_badge(
    draw,
    square: str,
    kind: str,
    board_left: int,
    board_top: int,
    step: float,
) -> None:
    """Draw a chess.com-style circle badge on the top-right of *square*.

    The circle straddles the square's corner rather than sitting in its middle:
    that is where the reference Short puts ``??``, ``!!`` and the star, and it
    keeps the piece on the destination square fully visible.
    """
    colour = _badge_color(kind)
    symbol = BADGE_SYMBOLS.get(kind)
    cell = _badge_square(square)
    if colour is None or symbol is None or cell is None:
        return

    col, row = cell
    x0 = board_left + col * step
    y0 = board_top + row * step
    radius = step * BADGE_SIZE / 2.0
    cx = x0 + step * 0.93
    cy = y0 + step * 0.07
    border = max(2, min(4, int(round(radius * 0.2))))

    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        fill=colour,
        outline=BADGE_BORDER,
        width=border,
    )
    font = _fit_badge_font(draw, symbol, radius)
    draw.text((cx, cy), symbol, font=font, fill=(255, 255, 255), anchor="mm")


def _arrow_color(name: str):
    """RGB for an arrow name: green (good), red (bad), cyan (alt)."""
    return {"bad": ARROW_BAD, "alt": ARROW_ALT}.get(name, ARROW_COLOR)


def _headline_color(name: str):
    """Fill for the headline: red, green, or white."""
    return {"bad": ACCENT_BAD, "good": ACCENT_GOOD}.get(name, TEXT_MAIN)


def _annotation_color(name: str):
    """Fill for a move annotation: red for a blunder, green for a good move."""
    return {"bad": ACCENT_BAD, "good": ACCENT_GOOD}.get(name, TEXT_MAIN)


def _fit_headline(draw, text: str, width: int):
    """The largest headline size whose ink fits *width*, shrinking until it does."""
    font = _first_font(_TEXT_FONTS, HEADLINE_SIZES[-1], "Х")
    for size in HEADLINE_SIZES:
        font = _first_font(_TEXT_FONTS, size, "Х")
        if _text_extent(draw, text, font)[0] <= width:
            return font
    extent = _text_extent(draw, text, font)[0]
    if extent > width:
        size = max(24, int(HEADLINE_SIZES[-1] * width / extent))
        font = _first_font(_TEXT_FONTS, size, "Х")
    return font


def _square_centres(size: int):
    """(file, rank) -> pixel centre, with rank 8 at the top."""
    out = {}
    step = size / 8.0
    for row in range(8):
        rank = 8 - row
        for col in range(8):
            file = chr(ord("a") + col)
            out[(file, rank)] = (col * step + step / 2, row * step + step / 2)
    return out


def _text_extent(draw, text: str, font) -> tuple[int, int]:
    """Ink width and height of *text* in *font*, measured not assumed.

    Width is the right edge rather than right-minus-left so a glyph with a
    negative left bearing is not mistaken for something that fits. Every size
    decision in the band is taken from this, because a nominal pixel size says
    nothing about how wide Cyrillic or a wrapped hook actually comes out.
    """
    if not text:
        return (0, 0)
    _, y0, x1, y1 = draw.textbbox((0, 0), text, font=font)
    return (x1, y1 - y0)


def _text_anchor_box(draw, text: str, font) -> tuple[int, int]:
    """(lead, extent) of *text* drawn from an ascender-anchored origin.

    PIL reports an ascender anchor's ink as (y0, y1) measured down from the anchor
    line, so a layout can advance by the real distance from one anchor line to the
    bottom of the next row's ink. Advancing by ink *height* instead would drop the
    leading in front of every row, and the band then spaces unevenly and walks off
    the bottom of the frame: that was measured, not assumed.
    """
    if not text:
        return (0, 0)
    _, y0, _, y1 = draw.textbbox((0, 0), text, font=font, anchor="la")
    return (y0, y1)


def _line_step(draw, font) -> int:
    """Baseline-to-baseline distance for *font*: one line of a block."""
    try:
        ascent, descent = font.getmetrics()
        return max(1, ascent + descent)
    except Exception:
        return max(1, _text_extent(draw, "ХAy", font)[1])


def _block_extent(draw, font, lines: list[str], step: int) -> int:
    """Distance from a block's anchor line to the bottom of its last line."""
    if not lines:
        return 0
    return (len(lines) - 1) * step + _text_anchor_box(draw, lines[-1], font)[1]


def _fit_font(draw, text: str, width: int, sizes: tuple[int, ...]):
    """The largest font in *sizes* whose *text* fits *width*, else the smallest.

    Shrinking rather than wrapping, because these fields are meant to be one
    line: a split evaluation is harder to read on a phone than a smaller one.
    """
    font = _first_font(_TEXT_FONTS, sizes[-1], "Х")
    for size in sizes:
        font = _first_font(_TEXT_FONTS, size, "Х")
        if _text_extent(draw, text, font)[0] <= width:
            break
    return font


def _wrap(draw, text: str, font, width: int) -> list[str]:
    """Greedy word wrap of *text* to *width* px, never returning an over-wide line.

    A single token wider than the band (a long URL, a run with no spaces in it)
    is broken by character instead of running past the padding, so no caller ever
    has to clip the result.
    """
    lines: list[str] = []
    for para in text.splitlines() or [""]:
        current = ""
        for word in para.split(" "):
            trial = f"{current} {word}".strip()
            if not current or _text_extent(draw, trial, font)[0] <= width:
                current = trial
                continue
            lines.append(current)
            current = word
        lines.append(current)

    out: list[str] = []
    for line in lines:
        if not line or _text_extent(draw, line, font)[0] <= width:
            out.append(line)
            continue
        chunk = ""
        for char in line:
            if chunk and _text_extent(draw, chunk + char, font)[0] > width:
                out.append(chunk)
                chunk = char
            else:
                chunk += char
        out.append(chunk)
    return [line for line in out if line] or [""]


def _fit_hook(draw, text: str, width: int, room: int):
    """The hook at the largest size in :data:`HOOK_SIZES` whose ink fits *room*.

    Returns ``(font, lines, lead, ink)``. A hook too long even at the smallest
    size keeps the leading lines that do fit: the opening of a hook carries the
    question and the tail is what a phone viewer can afford to lose. This is the
    only place the band may lose content, and losing it beats a frame that
    overflows or a render that raises on a long string.
    """
    for size in HOOK_SIZES:
        font = _first_font(_TEXT_FONTS, size, "Х")
        lines = _wrap(draw, text, font, width)
        step = _line_step(draw, font)
        lead = _text_anchor_box(draw, lines[0], font)[0]
        extent = _block_extent(draw, font, lines, step)
        if extent - lead <= room:
            return font, lines, lead, extent - lead

    font = _first_font(_TEXT_FONTS, HOOK_MIN_SIZE, "Х")
    lines = _wrap(draw, text, font, width)
    step = _line_step(draw, font)
    lead = _text_anchor_box(draw, lines[0], font)[0]
    keep = max(1, (room + lead) // step)
    if len(lines) > keep:
        log.debug("Hook clipped to %d of %d lines to fit the band", keep, len(lines))
        lines = lines[:keep]
    extent = _block_extent(draw, font, lines, step)
    return font, lines, lead, max(1, extent - lead)


def _draw_run(draw, x: int, y: int, text: str, font, fill) -> int:
    """Draw one coloured run at *x* and return where the next one starts."""
    if not text:
        return x
    draw.text((x, y), text, font=font, fill=fill, anchor="la")
    return x + _text_extent(draw, text, font)[0]


def _eval_runs(info: FrameInfo, arrow: str) -> list[tuple[str, str]]:
    """The evaluation line as (text, colour) pairs.

    Both sides present reads as a swing -- before, arrow, after in the accent --
    because the drop is the story and a bare pair of numbers does not show it.
    """
    before, after = info.eval_before.strip(), info.eval_after.strip()
    if before and after:
        return [(before, "dim"), (f"  {arrow}  ", "dim"), (after, "accent")]
    if after:
        return [(after, "accent")]
    if before:
        return [(before, "dim")]
    return []


def _move_runs(info: FrameInfo, san: str, arrow: str) -> list[tuple[str, str]]:
    """The move line as (text, colour) pairs: the notation, then the swing.

    One line, because a move and the evaluation it caused belong together: read
    across, ``Qd6+  ·  +0.4 → -2.1``. The dot matters -- without a separator a
    notation ending in '+' prints against a signed number as ``Qd6++0.4``.
    """
    runs = _eval_runs(info, arrow)
    parts: list[tuple[str, str]] = []
    if san:
        parts.append((san, "move"))
    if san and runs:
        parts.append((_MOVE_SEPARATOR, "dim"))
    parts.extend(runs)
    return parts


def _band_row(draw, kind: str, font, payload):
    """One measured band row: ``(kind, font, lead, ink height, payload)``.

    *lead* is how far below an ascender anchor the ink starts and *ink* is how
    tall it is. Measuring both is what lets the band space rows by the black a
    viewer actually sees between them instead of by nominal font size.
    """
    if kind == "hook":
        step = _line_step(draw, font)
        lead = _text_anchor_box(draw, payload[0], font)[0]
        ink = _block_extent(draw, font, payload, step) - lead
    elif kind == "move":
        parts = [text for text, _ in payload if text]
        lead = min(_text_anchor_box(draw, part, font)[0] for part in parts)
        ink = max(_text_anchor_box(draw, part, font)[1] for part in parts) - lead
    else:
        lead, extent = _text_anchor_box(draw, payload, font)
        ink = extent - lead

    return (kind, font, lead, max(1, ink), payload)


def _draw_band_row(draw, row, y: int, accent) -> None:
    """Draw one band row whose ink starts at *y*."""
    kind, font, _, _, payload = row
    if kind == "progress":
        draw.text((FRAME_W - INFO_PAD, y), payload, font=font, fill=TEXT_DIM, anchor="ra")
    elif kind == "hook":
        step = _line_step(draw, font)
        for i, line in enumerate(payload):
            draw.text((INFO_PAD, y + i * step), line, font=font, fill=accent, anchor="la")
    elif kind == "move":
        x = INFO_PAD
        for text, colour in payload:
            if colour == "move":
                # A stroke in the fill colour is what makes the notation read as
                # bold: only one text font family is loaded, and a heavy headline
                # beat deserves the weight more than a second font file does.
                draw.text(
                    (x, y),
                    text,
                    font=font,
                    fill=TEXT_MAIN,
                    anchor="la",
                    stroke_width=2,
                    stroke_fill=TEXT_MAIN,
                )
                x += _text_extent(draw, text, font)[0] + _MOVE_STROKE
            else:
                x = _draw_run(draw, x, y, text, font, accent if colour == "accent" else TEXT_DIM)
    else:
        draw.text((INFO_PAD, y), payload, font=font, fill=TEXT_DIM, anchor="la")


def _render_info_band(draw, spec: FrameSpec, bottom_limit: int) -> None:
    """Draw the information band between :data:`INFO_TOP` and *bottom_limit*.

    Every row is measured before anything is placed, and what the rows do not use
    is shared out as equal gaps -- including the tail below the last row. Both
    steps are the point of moving the board up: the band has to occupy its
    region, or the frame still carries the dead black that the centred board
    measured at 460px above itself and 459px below.
    """
    info = spec.info
    if info is None:
        return

    width = FRAME_W - 2 * INFO_PAD
    accent = _accent_color(spec.accent)
    region = bottom_limit - INFO_TOP

    hook = info.hook.strip()
    detail = info.detail.strip()
    progress = info.progress.strip()
    players = info.players.strip()
    san = info.moved_san.strip()
    # Whose move it is, above the players line: which side is playing is the first
    # thing wanted from a board that has just changed.
    turn = " · ".join(p for p in (info.turn_side.strip(), info.turn_name.strip()) if p)
    # Coverage is a property of the font file rather than of the size, so it is
    # settled once: an arrow that rendered as tofu would cost more than it said.
    probe_font = _first_font(_TEXT_FONTS, MOVE_SIZES[0], "Х")
    arrow = _ARROW if _covers(probe_font, _ARROW) else _ARROW_FALLBACK
    runs = _move_runs(info, san, arrow)

    # Reading order is progress, hook, detail, move and evaluation, players. The
    # hook is sized after the rest are measured because its size decides how much
    # height is left for them.
    above: list[tuple] = []
    below: list[tuple] = []
    # One progress counter per frame, not two. ``info.progress`` counts plies
    # ("58 / 70"); the frame's own top_text counted moves ("30 / 35"), and the
    # delivered clips showed both at once in different units, reading as two
    # disagreeing facts about one position. The band owns it now.
    if not progress:
        progress = _legacy_progress(spec.top_text)
    if progress:
        font = _first_font(_TEXT_FONTS, PROGRESS_SIZE, "Х")
        above.append(_band_row(draw, "progress", font, progress))
    if detail:
        font = _fit_font(draw, detail, width, DETAIL_SIZES)
        below.append(_band_row(draw, "detail", font, detail))
    if runs:
        font = _fit_font(draw, "".join(text for text, _ in runs), width, MOVE_SIZES)
        below.append(_band_row(draw, "move", font, runs))
    if turn:
        font = _first_font(_TEXT_FONTS, TURN_SIZE, "Х")
        above.append(_band_row(draw, "turn", font, turn))
    if players:
        font = _first_font(_TEXT_FONTS, PLAYERS_SIZE, "Х")
        below.append(_band_row(draw, "players", font, players))

    rows = above
    if hook:
        # The hook may take the region minus the fixed ink and one minimum gap
        # per slot, the tail included. A gap in front of a row also has to cover
        # that row's leading, so the largest lead below the hook is charged here.
        leads = [row[2] for row in below] or [0]
        room = region - sum(row[3] for row in below) - (BAND_GAP + max(leads)) * (len(below) + 2)
        font, lines, lead, ink = _fit_hook(draw, hook, width, room)
        rows = above + [_band_row(draw, "hook", font, lines)]
    rows = rows + below

    if not rows:
        return

    # Every gap in the band gets the same share of the height left over: the ones
    # between rows and the tail under the last one. Black at the bottom of the
    # band is the same dead space as black between two lines of it.
    share = (region - sum(row[3] for row in rows)) // len(rows)

    y = INFO_TOP - rows[0][2]
    for i, row in enumerate(rows):
        y = min(y, max(INFO_TOP, bottom_limit - row[3] - row[2]))
        _draw_band_row(draw, row, y, accent)
        # The next row's leading is subtracted so the black between two rows is
        # the share itself and not the share plus one font's worth of leading.
        nxt = rows[i + 1][2] if i + 1 < len(rows) else 0
        y += row[2] + row[3] + max(1, share - nxt)


def _legacy_progress(top_text: str) -> str:
    """Move counter from the pre-band caption, for frames with no ``info``.

    Formats before the band carried their position in ``top_text`` as ``30 / 35``
    -- moves, not plies. It is still the only progress on those frames, so it is
    kept rather than dropped; frames that have a band take their count from
    ``info.progress`` and never from here.
    """
    text = (top_text or "").strip()
    if "/" not in text:
        return ""
    head, _, tail = text.partition("/")
    if not head.strip().isdigit() or not tail.strip().isdigit():
        return ""
    return f"ход {head.strip()} / {tail.strip()}"


def _render_cta(spec: FrameSpec, out_path: str | Path) -> Path:
    """Render a full-screen call-to-action card."""
    from PIL import Image, ImageDraw

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (FRAME_W, FRAME_H), BOARD_BG)
    draw = ImageDraw.Draw(img)
    top, bottom = spec.cta or ("", "")

    draw.text(
        (FRAME_W // 2, FRAME_H // 2 - 60),
        top,
        fill=TEXT_MAIN,
        font=_first_font(_TEXT_FONTS, 76, "Х"),
        anchor="mm",
    )
    if bottom:
        draw.text(
            (FRAME_W // 2, FRAME_H // 2 + 60),
            bottom,
            fill=TEXT_DIM,
            font=_first_font(_TEXT_FONTS, 44, "Х"),
            anchor="mm",
        )
    img.save(out)
    return out


def _apply_zoom(spec: FrameSpec, img):
    """Punch the frame in around ``spec.zoom_center``, clamped to :data:`ZOOM_MAX`.

    A crop-and-scale rather than a redraw: the board is already rendered at the
    final size, and scaling the finished pixels keeps the highlights and arrows
    in the same place the viewer just saw them.  The crop window is clamped
    inside the frame so an off-centre punch never leaves a black edge.
    """
    from PIL import Image

    zoom = max(ZOOM_MIN, min(ZOOM_MAX, float(spec.zoom)))
    if zoom == ZOOM_MIN:
        return img

    centre = spec.zoom_center or (FRAME_W / 2, BOARD_TOP + BOARD / 2)
    crop_w = int(round(FRAME_W / zoom))
    crop_h = int(round(FRAME_H / zoom))
    left = int(round(centre[0] - crop_w / 2))
    top = int(round(centre[1] - crop_h / 2))
    left = max(0, min(FRAME_W - crop_w, left))
    top = max(0, min(FRAME_H - crop_h, top))
    return img.crop((left, top, left + crop_w, top + crop_h)).resize(
        (FRAME_W, FRAME_H), Image.LANCZOS
    )


def render_frame(spec: FrameSpec, out_path: str | Path) -> Path:
    """Render *spec* to a PNG and return its path."""
    if spec.cta is not None:
        return _render_cta(spec, out_path)

    from PIL import Image, ImageDraw

    board_top = BOARD_TOP
    board_left = (FRAME_W - BOARD) // 2

    img = Image.new("RGB", (FRAME_W, FRAME_H), BOARD_BG)
    draw = ImageDraw.Draw(img)

    if spec.headline:
        # The meme headline owns the header: top_text would collide with it, and
        # the drama format has no caption to lose.
        font = _fit_headline(draw, spec.headline, FRAME_W - 80)
        draw.text(
            (FRAME_W // 2, 150),
            spec.headline,
            fill=_headline_color(spec.headline_color),
            font=font,
            anchor="mm",
            stroke_width=HEADLINE_STROKE,
            stroke_fill=(14, 14, 16),
        )
    else:
        draw.text(
            (FRAME_W // 2, 120),
            spec.top_text,
            fill=_accent_color(spec.accent),
            font=_first_font(_TEXT_FONTS, 64, "Х"),
            anchor="mm",
        )
    if spec.bottom_text:
        draw.text(
            (FRAME_W // 2, FRAME_H - 180),
            spec.bottom_text,
            fill=TEXT_DIM,
            font=_first_font(_TEXT_FONTS, BOTTOM_TEXT_SIZE, "Х"),
            anchor="mm",
        )
    if spec.eval_text:
        # Sits under the hook, above the board: present but never competing with
        # the question.
        draw.text(
            (FRAME_W // 2, 232),
            spec.eval_text,
            fill=TEXT_DIM,
            font=_first_font(_TEXT_FONTS, 40, "Х"),
            anchor="mm",
        )

    step = BOARD / 8.0
    highlight = {s.lower() for s in spec.highlight_squares}
    mono = spec.board_style == "mono"
    light_square = MONO_LIGHT_SQUARE if mono else LIGHT_SQUARE
    dark_square = MONO_DARK_SQUARE if mono else DARK_SQUARE
    frame_colour = MONO_BOARD_FRAME if mono else BOARD_FRAME
    edge_colour = MONO_BOARD_EDGE if mono else (60, 60, 64)
    coord_on_light = MONO_COORD_ON_LIGHT if mono else COORD_ON_LIGHT
    coord_on_dark = MONO_COORD_ON_DARK if mono else COORD_ON_DARK
    highlight_colour = _highlight_color(spec.accent)

    # A thin frame around the board, like the trainer's wooden edge.
    draw.rectangle(
        [
            board_left - BOARD_FRAME_WIDTH,
            board_top - BOARD_FRAME_WIDTH,
            board_left + BOARD + BOARD_FRAME_WIDTH,
            board_top + BOARD + BOARD_FRAME_WIDTH,
        ],
        fill=frame_colour,
    )

    tinted = spec.accent in {
        "blunder",
        "mate",
        "brilliant",
        "good",
        "mistake",
        "dubious",
        "interesting",
        "only",
        "zugzwang",
    }
    for row in range(8):
        for col in range(8):
            file = chr(ord("a") + col)
            rank = 8 - row
            name = f"{file}{rank}"
            x0 = board_left + col * step
            y0 = board_top + row * step
            light = (row + col) % 2 == 1
            fill = light_square if light else dark_square
            draw.rectangle([x0, y0, x0 + step, y0 + step], fill=fill)
            if name in highlight:
                if tinted:
                    # A Lichess-style translucent tint keeps the square and the
                    # piece readable; a solid fill reads as a warning card.
                    tile = Image.new("RGBA", (int(step), int(step)), (*highlight_colour, 150))
                    img.paste(tile, (int(round(x0)), int(round(y0))), tile)
                else:
                    draw.rectangle([x0, y0, x0 + step, y0 + step], fill=highlight_colour)

    # Coordinates live in the square corner, in the opposite square colour, so
    # they stay readable without a separate gutter.
    coord_font = _first_font(_TEXT_FONTS, max(18, int(step * 0.17)), "1")
    for row in range(8):
        rank = 8 - row
        y0 = board_top + row * step
        light = row % 2 == 1
        colour = coord_on_light if light else coord_on_dark
        draw.text(
            (board_left + 7, y0 + step - 8),
            str(rank),
            fill=colour,
            font=coord_font,
            anchor="ls",
        )
    for col in range(8):
        file = chr(ord("a") + col)
        x0 = board_left + col * step
        y0 = board_top + 7 * step
        light = (7 + col) % 2 == 1
        colour = coord_on_light if light else coord_on_dark
        draw.text(
            (x0 + step - 7, y0 + step - 6),
            file,
            fill=colour,
            font=coord_font,
            anchor="rs",
        )

    try:
        import chess

        board = chess.Board(spec.fen)
        pieces = board.piece_map()
    except Exception:
        log.debug("FEN parse failed while drawing", exc_info=True)
        pieces = {}

    # 0.92 fills roughly the same share of the square as Lichess/chess.com.
    glyph_font = _first_font(_PIECE_FONTS, int(step * 0.92), "\u2654")
    piece_size = int(step * 0.92)
    hidden = {s.lower() for s in spec.hidden_squares}

    def _draw_piece(px: float, py: float, symbol: str, white: bool) -> None:
        filename = f"w{symbol}.png" if white else f"b{symbol.upper()}.png"
        image = _piece_image(filename, piece_size)
        if image is not None:
            img.paste(
                image,
                (int(round(px - piece_size / 2)), int(round(py - piece_size / 2))),
                image,
            )
            return
        glyph = PIECE_GLYPHS[symbol]
        if white:
            draw.text(
                (px, py + step * 0.02),
                glyph,
                fill=(252, 250, 246),
                font=glyph_font,
                anchor="mm",
                stroke_width=5,
                stroke_fill=(40, 38, 36),
            )
        else:
            draw.text(
                (px, py + step * 0.02), glyph, fill=(38, 36, 34), font=glyph_font, anchor="mm"
            )

    for (file, rank), (cx, cy) in _square_centres(BOARD).items():
        square = f"{file}{rank}"
        if square in hidden:
            continue
        piece = pieces.get(chess_square(file, rank)) if _chess_ok() else None
        if piece is None:
            continue
        _draw_piece(board_left + cx, board_top + cy, piece.symbol(), bool(piece.color))

    if spec.moving is not None:
        try:
            symbol, src, dst, progress = spec.moving
            centres = _square_centres(BOARD)
            a = centres[(src[0], int(src[1]))]
            b = centres[(dst[0], int(dst[1]))]
            t = max(0.0, min(1.0, float(progress)))
            px = board_left + a[0] + (b[0] - a[0]) * t
            py = board_top + a[1] + (b[1] - a[1]) * t
            _draw_piece(px, py, symbol, symbol.isupper())
        except Exception:
            log.debug("Moving piece skipped", exc_info=True)

    if spec.arrow:
        centres = _square_centres(BOARD)
        try:
            a = centres[(spec.arrow[0][0], int(spec.arrow[0][1]))]
            b = centres[(spec.arrow[1][0], int(spec.arrow[1][1]))]
            p1 = (board_left + a[0], board_top + a[1])
            p2 = (board_left + b[0], board_top + b[1])
            dx, dy = p2[0] - p1[0], p2[1] - p1[1]
            length = (dx * dx + dy * dy) ** 0.5
            if length > 1.0:
                ux, uy = dx / length, dy / length
                head_len = 38.0
                head_half = 22.0
                base = (p2[0] - ux * head_len, p2[1] - uy * head_len)
                left = (base[0] - uy * head_half, base[1] + ux * head_half)
                right = (base[0] + uy * head_half, base[1] - ux * head_half)
                overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
                odraw = ImageDraw.Draw(overlay)
                colour = (*_arrow_color(spec.arrow_color), ARROW_ALPHA)
                odraw.line([p1, base], fill=colour, width=18)
                odraw.ellipse(
                    [p1[0] - 9, p1[1] - 9, p1[0] + 9, p1[1] + 9],
                    fill=colour,
                )
                odraw.polygon([p2, left, right], fill=colour)
                img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
                draw = ImageDraw.Draw(img)
        except Exception:
            log.debug("Arrow skipped", exc_info=True)

    draw.rectangle(
        [board_left, board_top, board_left + BOARD, board_top + BOARD],
        outline=edge_colour,
        width=3,
    )

    if spec.badge is not None:
        # Badges belong on the destination square, so they are drawn above the
        # pieces and the board edge and can overlap both without being clipped.
        _draw_badge(draw, spec.badge[0], spec.badge[1], board_left, board_top, step)

    if spec.annotation and spec.badge is None:
        # A comment mark belongs to the board, so it sits in the top-right just
        # above the pieces rather than in the caption band.  The dark badge is
        # what keeps it legible when a headline reaches the same corner.
        ann_font = _first_font(_TEXT_FONTS, ANNOTATION_SIZE, "!")
        ax = board_left + BOARD - 40
        ay = board_top + 10
        bbox = draw.textbbox(
            (ax, ay),
            spec.annotation,
            font=ann_font,
            anchor="rs",
            stroke_width=ANNOTATION_STROKE,
        )
        draw.rounded_rectangle(
            (bbox[0] - 14, bbox[1] - 10, bbox[2] + 14, bbox[3] + 10),
            radius=20,
            fill=(14, 14, 16),
        )
        draw.text(
            (ax, ay),
            spec.annotation,
            font=ann_font,
            fill=_annotation_color(spec.annotation_color),
            anchor="rs",
            stroke_width=ANNOTATION_STROKE,
            stroke_fill=(14, 14, 16),
        )

    if spec.info is not None:
        # bottom_text keeps its own anchor; the band stops above it so players
        # never print through it, and with no bottom_text the band owns the
        # bottom of the frame.
        bottom_limit = FRAME_H
        if spec.bottom_text:
            _, y0, _, _ = draw.textbbox(
                (FRAME_W // 2, FRAME_H - 180),
                spec.bottom_text,
                font=_first_font(_TEXT_FONTS, BOTTOM_TEXT_SIZE, "Х"),
                anchor="mm",
            )
            bottom_limit = min(bottom_limit, y0 - BAND_GAP)
        _render_info_band(draw, spec, bottom_limit)

    # The punch runs last so every highlight, arrow and text pixel is scaled
    # together as one picture.  CTA frames returned above, so the club card is
    # never zoomed.
    img = _apply_zoom(spec, img)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def _chess_ok() -> bool:
    try:
        import chess  # noqa: F401

        return True
    except ImportError:
        return False


def chess_square(file: str, rank: int):
    import chess

    return chess.square(chess.FILE_NAMES.index(file), rank - 1)
