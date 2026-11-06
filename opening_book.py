"""
A simple, human-editable opening book -- kept entirely separate from
chess_engine.py. The engine itself never imports or knows about this
module; chess_gui.py is what wires the two together for computer moves.

The book maps positions to a list of candidate moves in UCI notation.
Positions are keyed by EPD (a FEN without the halfmove/fullmove clocks --
board placement, side to move, castling rights, en passant target), so
transpositions are recognized correctly. When a position has more than
one candidate move, one is chosen at random each time it's reached.

The book lives in a plain JSON file (opening_book.json, next to this file
by default) that you can hand-edit directly -- it's just
{"<epd>": ["<uci>", "<uci>", ...], ...} -- or manage through the
"Opening Book" editor in opening_book_editor.py / chess_gui.py.
"""

import json
import random
from pathlib import Path

import chess

DEFAULT_BOOK_PATH = Path(__file__).resolve().parent / "opening_book.json"

# A handful of common openings, several plies deep, used to seed
# opening_book.json the first time it's needed. Written here as SAN lines
# purely because they're easy for a human to read/extend in this file;
# _build_starter_book() converts them to the EPD -> [uci, ...] format
# actually used at runtime.
_STARTER_LINES = [
    "e4 e5 Nf3 Nc6 Bb5",                  # Ruy Lopez
    "e4 e5 Nf3 Nc6 Bc4 Bc5",              # Italian Game
    "e4 e5 Nf3 Nc6 d4 exd4 Nxd4",         # Scotch Game
    "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3",  # Sicilian, Open
    "e4 c5 Nc3 Nc6 g3",                   # Sicilian, Closed
    "e4 e6 d4 d5 Nc3",                    # French Defense
    "e4 c6 d4 d5 Nc3",                    # Caro-Kann Defense
    "e4 d5 exd5 Qxd5 Nc3",                # Scandinavian Defense
    "d4 d5 c4 e6",                        # Queen's Gambit Declined
    "d4 d5 c4 c6",                        # Slav Defense
    "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6",         # King's Indian Defense
    "d4 Nf6 c4 e6 Nc3 Bb4",               # Nimzo-Indian Defense
    "d4 d5 Nf3 Nf6 Bf4",                  # London System
    "c4 e5 Nc3 Nf6",                      # English Opening
    "Nf3 d5 g3",                          # Reti Opening
]


def _build_starter_book():
    book = {}
    for line in _STARTER_LINES:
        board = chess.Board()
        for san in line.split():
            epd = board.epd()
            move = board.parse_san(san)
            uci = move.uci()
            moves = book.setdefault(epd, [])
            if uci not in moves:
                moves.append(uci)
            board.push(move)
    return book


def load_book(path=DEFAULT_BOOK_PATH):
    """Load the book from `path`. If the file doesn't exist yet, seed it
    with the built-in starter lines and write it out immediately so
    there's something on disk to hand-edit right away."""
    path = Path(path)

    if not path.exists():
        book = _build_starter_book()
        save_book(book, path)
        return book

    try:
        with open(path, "r") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

    # Defensive parsing: tolerate a hand-edited file with a bare string
    # instead of a list, stray whitespace, non-dict garbage, etc., rather
    # than crashing the GUI on load.
    book = {}
    if isinstance(raw, dict):
        for epd, moves in raw.items():
            if isinstance(moves, str):
                moves = [moves]
            if not isinstance(moves, list):
                continue
            cleaned = [m.strip() for m in moves if isinstance(m, str) and m.strip()]
            if cleaned:
                book[epd] = cleaned
    return book


def save_book(book, path=DEFAULT_BOOK_PATH):
    """Write `book` to `path` as pretty-printed JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(book, f, indent=2, sort_keys=True)


def moves_for_position(book, board):
    """Legal chess.Move objects the book offers for `board`'s current
    position, in the order they're stored. Entries that are no longer
    legal (e.g. left over from hand-editing, or a malformed UCI string)
    are silently skipped rather than raising."""
    entry = book.get(board.epd())
    if not entry:
        return []

    result = []
    for uci in entry:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            continue
        if move in board.legal_moves:
            result.append(move)
    return result


def choose_move(book, board, rng=random):
    """A random legal book move for `board`'s current position, or None
    if the position isn't in the book (or has no legal entries left)."""
    candidates = moves_for_position(book, board)
    if not candidates:
        return None
    return rng.choice(candidates)


def add_move(book, board, move):
    """Add `move` (a chess.Move, legal in `board`) to the book at the
    current position, in place. No-op if it's already there."""
    epd = board.epd()
    uci = move.uci()
    moves = book.setdefault(epd, [])
    if uci not in moves:
        moves.append(uci)


def remove_move(book, board, move):
    """Remove `move` from the book at the current position, in place, if
    present. Cleans up the position entry entirely once it's empty."""
    epd = board.epd()
    moves = book.get(epd)
    if not moves:
        return
    uci = move.uci()
    if uci in moves:
        moves.remove(uci)
    if not moves:
        book.pop(epd, None)
