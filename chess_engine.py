
#Simple negamax/alpha-beta chess engine with a transposition table, PVS, killer moves, history heuristic, and quiescence search.



import math
import time

import chess
import chess.polyglot

computer_depth = 5
STARTING_DEPTH = 5

DEPTH_INCREASE_THRESHOLD_PERCENT = 0.01
DEPTH_DECREASE_THRESHOLD_PERCENT = 0.1
MOVES_TO_CONSIDER = 3

move_time_history = []


def record_move_time(elapsed, time_remaining):
    global computer_depth
    move_time_history.append(elapsed)

  
    if time_remaining is None:
        return

    if len(move_time_history) >= MOVES_TO_CONSIDER:
        last_n = move_time_history[-MOVES_TO_CONSIDER:]
        total = sum(last_n)
        if total < time_remaining * DEPTH_INCREASE_THRESHOLD_PERCENT * MOVES_TO_CONSIDER:
            computer_depth += 1
        elif total > time_remaining * DEPTH_DECREASE_THRESHOLD_PERCENT * MOVES_TO_CONSIDER:
            computer_depth = max(1, computer_depth - 1)


def reset_dynamic_depth():
    global computer_depth
    computer_depth = STARTING_DEPTH
    move_time_history.clear()
    reset_search_state()


def reset_search_state():
    TT.clear()
    for ply_killers in killer_moves:
        ply_killers[0] = ply_killers[1] = None
    history_table.clear()


TT = {}
NODES = 0


EXACT, LOWER, UPPER = 0, 1, 2
MATE_SCORE = 100_000
MAX_PLY = 128


LMR_FULL_DEPTH_MOVES = 3
LMR_MIN_DEPTH = 3
LMR_REDUCTION = 2

NULL_MOVE_MIN_DEPTH = 3
NULL_MOVE_REDUCTION = 2

STATIC_NULL_MAX_DEPTH = 2
STATIC_NULL_MARGIN_PER_DEPTH = 90

DELTA_MARGIN = 200

FUTILITY_MAX_DEPTH = 2
FUTILITY_MARGINS = {1: 150, 2: 300}


class SearchAborted(Exception):
    """Raised to unwind the whole search tree once the time budget for
    the current get_best_move() call has run out."""

_search_deadline = None
_time_check_counter = 0
TIME_CHECK_INTERVAL = 256

_root_best_move = None


def _check_time():
    global _time_check_counter
    if _search_deadline is None:
        return
    _time_check_counter += 1
    if _time_check_counter >= TIME_CHECK_INTERVAL:
        _time_check_counter = 0
        if time.time() >= _search_deadline:
            raise SearchAborted()


def set_deadline(deadline):
    global _search_deadline, _time_check_counter
    _search_deadline = deadline
    _time_check_counter = TIME_CHECK_INTERVAL


def clear_deadline():
    global _search_deadline, _time_check_counter
    _search_deadline = None
    _time_check_counter = 0


def _gives_check(board, move):
    from_sq, to_sq = move.from_square, move.to_square
    stm = board.turn
    piece_type = move.promotion or board.piece_type_at(from_sq)

    if piece_type == chess.KING:
        if board.is_castling(move):
            return board.gives_check(move)
    elif (piece_type == chess.PAWN and to_sq == board.ep_square
          and not board.occupied & chess.BB_SQUARES[to_sq]):
        return board.gives_check(move)

    king_bb = board.kings & board.occupied_co[not stm]
    if not king_bb:
        return False
    king_sq = king_bb.bit_length() - 1
    from_bb = chess.BB_SQUARES[from_sq]
    occupied = (board.occupied & ~from_bb) | chess.BB_SQUARES[to_sq]

    if piece_type == chess.PAWN:
        if chess.BB_PAWN_ATTACKS[stm][to_sq] & king_bb:
            return True
    elif piece_type == chess.KNIGHT:
        if chess.BB_KNIGHT_ATTACKS[to_sq] & king_bb:
            return True
    elif piece_type != chess.KING:
        if piece_type != chess.ROOK and (
                chess.BB_DIAG_ATTACKS[to_sq][chess.BB_DIAG_MASKS[to_sq] & occupied] & king_bb):
            return True
        if piece_type != chess.BISHOP and (
                (chess.BB_RANK_ATTACKS[to_sq][chess.BB_RANK_MASKS[to_sq] & occupied]
                 | chess.BB_FILE_ATTACKS[to_sq][chess.BB_FILE_MASKS[to_sq] & occupied])
                & king_bb):
            return True

    ours = board.occupied_co[stm] & ~from_bb
    queens = board.queens
    rooks_queens = (board.rooks | queens) & ours
    if rooks_queens and (
            (chess.BB_RANK_ATTACKS[king_sq][chess.BB_RANK_MASKS[king_sq] & occupied]
             | chess.BB_FILE_ATTACKS[king_sq][chess.BB_FILE_MASKS[king_sq] & occupied])
            & rooks_queens):
        return True
    bishops_queens = (board.bishops | queens) & ours
    if bishops_queens and (
            chess.BB_DIAG_ATTACKS[king_sq][chess.BB_DIAG_MASKS[king_sq] & occupied]
            & bishops_queens):
        return True
    return False


def _lmr_reduction(depth, move_index, in_check, is_capture, is_promotion, gives_check):
    if depth < LMR_MIN_DEPTH:
        return 0
    if move_index < LMR_FULL_DEPTH_MOVES:
        return 0
    if in_check or is_capture or is_promotion or gives_check:
        return 0
    return LMR_REDUCTION

def _has_non_pawn_material(board, color):
    return bool(
        board.pieces_mask(chess.KNIGHT, color)
        | board.pieces_mask(chess.BISHOP, color)
        | board.pieces_mask(chess.ROOK, color)
        | board.pieces_mask(chess.QUEEN, color)
    )

killer_moves = [[None, None] for _ in range(MAX_PLY)]
history_table = {}


PIECE_TYPES = (chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN, chess.KING)


piece_values = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 490,
    chess.QUEEN: 980,
}

piece_square_tables = {

    chess.PAWN: [
        100, 100, 100, 100, 100, 100, 100, 100,
        150, 150, 150, 150, 150, 150, 150, 150,
        110, 110, 120, 130, 130, 120, 110, 110,
        105, 105, 110, 125, 125, 110, 105, 105,
        100, 100, 100, 120, 120, 100, 100, 100,
        105,  95,  90, 100, 100,  90,  95, 105,
        105, 110, 110,  80,  80, 110, 110, 105,
        100, 100, 100, 100, 100, 100, 100, 100,
    ],

    chess.KNIGHT: [
        270,280,290,290,290,290,280,270,
        280,300,320,320,320,320,300,280,
        290,320,330,335,335,330,320,290,
        290,325,335,340,340,335,325,290,
        290,320,335,340,340,335,320,290,
        290,325,330,335,335,330,325,290,
        280,300,320,325,325,320,300,280,
        270,280,290,290,290,290,280,270,
    ],

    chess.BISHOP: [
        310,320,320,320,320,320,320,310,
        320,330,330,330,330,330,330,320,
        320,330,335,340,340,335,330,320,
        320,335,335,340,340,335,335,320,
        320,330,340,340,340,340,330,320,
        320,340,340,340,340,340,340,320,
        320,335,330,330,330,330,335,320,
        310,320,320,320,320,320,320,310,
    ],

    chess.ROOK: [
        490,490,490,490,490,490,490,490,
        495,500,500,500,500,500,500,495,
        485,490,490,490,490,490,490,485,
        485,490,490,490,490,490,490,485,
        485,490,490,490,490,490,490,485,
        485,490,490,490,490,490,490,485,
        485,490,490,490,490,490,490,485,
        490,490,490,495,495,490,490,490
    ],

    chess.QUEEN: [
        920,930,930,935,935,930,930,920,
        930,940,940,940,940,940,940,930,
        930,940,945,945,945,945,940,930,
        935,940,945,945,945,945,940,935,
        940,940,945,945,945,945,940,935,
        930,945,945,945,945,945,940,930,
        930,940,945,940,940,940,940,930,
        920,930,930,935,935,930,930,920
    ],

    chess.KING: [
        -30,-40,-40,-50,-50,-40,-40,-30,
        -30,-40,-40,-50,-50,-40,-40,-30,
        -30,-40,-40,-50,-50,-40,-40,-30,
        -30,-40,-40,-50,-50,-40,-40,-30,
        -20,-30,-30,-40,-40,-30,-30,-20,
        -10,-20,-20,-20,-20,-20,-20,-10,
        20, 20,  0,  0,  0,  0, 20, 20,
        20, 30, 10,  0,  0, 10, 30, 20
    ],
}

king_endgame_pst = [
        -50,-40,-30,-20,-20,-30,-40,-50,
        -30,-20,-10,  0,  0,-10,-20,-30,
        -30,-10, 20, 30, 30, 20,-10,-30,
        -30,-10, 30, 40, 40, 30,-10,-30,
        -30,-10, 30, 40, 40, 30,-10,-30,
        -30,-10, 20, 30, 30, 20,-10,-30,
        -30,-30,  0,  0,  0,  0,-30,-30,
        -50,-30,-30,-30,-30,-30,-30,-50
]

pawn_shield_pst = [
          0,   0,   0,   0,   0,   0,   0,   0,
          0,   0,   0,   0,   0,   0,   0,   0,
          0,   0,   0,   0,   0,   0,   0,   0,
          0,   0,   0,   0,   0,   0,   0,   0,
          0,   0,   0,   0,   0,   0,   0,   0,
          0,   0,   0,   0,   0,   0,   0,   0,
         10,  10,  10,  10,  10,  10,  10,  10,
          0,   0,   0,   0,   0,   0,   0,   0,
]


def _popcount(x):
    return bin(x).count("1")


def is_queenless_endgame(board):
    return not board.pieces_mask(chess.QUEEN, chess.WHITE) and not board.pieces_mask(chess.QUEEN, chess.BLACK)


def _queen_counts(board):
    return {
        chess.WHITE: _popcount(board.pieces_mask(chess.QUEEN, chess.WHITE)),
        chess.BLACK: _popcount(board.pieces_mask(chess.QUEEN, chess.BLACK)),
    }


def _attackers_to(board, color, square, occupied):
    """Bitboard of `color`'s pieces that attack `square`, counting only the
    pieces present in `occupied`.

    Mirrors Board._attackers_mask() but takes the occupancy filter into its
    own hands, so a piece already swapped off is invisible both as an
    attacker and as a blocker. Uses only module-level tables that
    python-chess exposes publicly.
    """
    rank_pieces = chess.BB_RANK_MASKS[square] & occupied
    file_pieces = chess.BB_FILE_MASKS[square] & occupied
    diag_pieces = chess.BB_DIAG_MASKS[square] & occupied
    queens_and_rooks = board.queens | board.rooks
    queens_and_bishops = board.queens | board.bishops
    attackers = (
        (chess.BB_KING_ATTACKS[square] & board.kings)
        | (chess.BB_KNIGHT_ATTACKS[square] & board.knights)
        | (chess.BB_RANK_ATTACKS[square][rank_pieces] & queens_and_rooks)
        | (chess.BB_FILE_ATTACKS[square][file_pieces] & queens_and_rooks)
        | (chess.BB_DIAG_ATTACKS[square][diag_pieces] & queens_and_bishops)
        | (chess.BB_PAWN_ATTACKS[not color][square] & board.pawns)
    )
    return attackers & board.occupied_co[color] & occupied


SEE_KING_VALUE = 20_000


_SEE_VALUES = (
    piece_values[chess.PAWN],
    piece_values[chess.KNIGHT],
    piece_values[chess.BISHOP],
    piece_values[chess.ROOK],
    piece_values[chess.QUEEN],
    SEE_KING_VALUE,
)


def see(board, move):
    """Static exchange evaluation for a capture or promotion.

    Swaps the square off using a single running occupancy bitboard. The
    previous version copied the board and pushed every recapture onto the
    copy; since the occupant of the target square can neither attack that
    square nor block a ray to it, the only thing the swap-off actually has
    to track is which attackers have left their origin squares -- which is
    one AND-NOT per capture. Results are unchanged, including the
    least-valuable-attacker tie-break (lowest square index) and the rule
    that the king may not recapture into a still-defended square.
    """
    to_sq = move.to_square

    if not (board.is_capture(move) or move.promotion):
        return 0

    is_en_passant = board.is_en_passant(move)
    if is_en_passant:
        captured_value = piece_values[chess.PAWN]
    else:
        captured_type = board.piece_type_at(to_sq)
        captured_value = piece_values.get(captured_type, 0) if captured_type else 0

    promo_gain = 0
    if move.promotion:
        promo_gain = piece_values.get(move.promotion, 0) - piece_values[chess.PAWN]
        mover_value = piece_values.get(move.promotion, 0)
    else:
        mover_value = piece_values.get(board.piece_type_at(move.from_square), 0)

    occupied = (board.occupied | chess.BB_SQUARES[to_sq]) & ~chess.BB_SQUARES[move.from_square]
    if is_en_passant:
        occupied &= ~chess.BB_SQUARES[to_sq + (-8 if board.turn == chess.WHITE else 8)]

    lva_boards = (board.pawns, board.knights, board.bishops,
                  board.rooks, board.queens, board.kings)

    attacker_values = [mover_value]
    side = not board.turn

    while True:
        attackers = _attackers_to(board, side, to_sq, occupied)
        if not attackers:
            break

        lva_square = None
        for index in range(6):
            subset = attackers & lva_boards[index]
            if subset:
                lva_square = chess.lsb(subset)
                value = _SEE_VALUES[index]
                break
        if lva_square is None:
            break

        if value == SEE_KING_VALUE and _attackers_to(board, not side, to_sq, occupied):
            break

        attacker_values.append(value)
        occupied &= ~chess.BB_SQUARES[lva_square]
        side = not side


    best_continuation = 0
    for v in reversed(attacker_values[:-1]):
        best_continuation = max(0, v - best_continuation)

    return captured_value + promo_gain - best_continuation


def _pst_at(piece_type, color, square, endgame):
    table = king_endgame_pst if (piece_type == chess.KING and endgame) else piece_square_tables[piece_type]
    return table[chess.square_mirror(square)] if color == chess.WHITE else table[square]


SHIELD_ZONE_FILES = [
    frozenset((lo, lo + 1, lo + 2))
    for lo in (min(max(f - 1, 0), 5) for f in range(8))
]


def _shield_zone_files(board, color):
    king_sq = board.king(color)
    if king_sq is None:
        return frozenset()
    return SHIELD_ZONE_FILES[chess.square_file(king_sq)]


def _shield_contribution_for_color(board, color, zone_files):
    sign = 1 if color == chess.WHITE else -1
    total = 0

    for sq in board.pieces(chess.PAWN, color):
        if chess.square_file(sq) in zone_files:
            if color == chess.WHITE:
                total += sign * pawn_shield_pst[sq]
            else:
                total += sign * pawn_shield_pst[chess.square_mirror(sq)]

    return total


def _rights_lost_snapshot(board):
    return {
        color: not (board.has_kingside_castling_rights(color) or board.has_queenside_castling_rights(color))
        for color in (chess.WHITE, chess.BLACK)
    }


def _shield_diff(board):
    if is_queenless_endgame(board):
        return 0
    total = 0
    rights_lost = _rights_lost_snapshot(board)
    for color in (chess.WHITE, chess.BLACK):
        if rights_lost[color]:
            zone_files = _shield_zone_files(board, color)
            total += _shield_contribution_for_color(board, color, zone_files)
    return total


def board_key(board):
    try:
        return board._transposition_key()
    except AttributeError:
        return chess.polyglot.zobrist_hash(board)


TT_CLOCK_THRESHOLD = 80


def tt_key(board):
    base = board_key(board)
    clock = board.halfmove_clock
    if clock >= TT_CLOCK_THRESHOLD:
        return (base, clock)
    return (base, 0)


def _tt_store_score(score, ply):
    if score >= MATE_SCORE - MAX_PLY:
        return score + ply
    elif score <= -MATE_SCORE + MAX_PLY:
        return score - ply
    return score


def _tt_retrieve_score(score, ply):
    if score >= MATE_SCORE - MAX_PLY:
        return score - ply
    elif score <= -MATE_SCORE + MAX_PLY:
        return score + ply
    return score


def _material_pst_score(board):
    score = 0
    endgame = is_queenless_endgame(board)
    for color, sign in ((chess.WHITE, 1), (chess.BLACK, -1)):
        for piece_type in PIECE_TYPES:
            bb = board.pieces_mask(piece_type, color)
            if not bb:
                continue
            for square in chess.scan_reversed(bb):
                score += sign * _pst_at(piece_type, color, square, endgame)
    return score


DOUBLED_PENALTY = 25


def _doubled_pawn_diff(board):
    diff = 0
    for color in (chess.WHITE, chess.BLACK):
        files = [0] * 8
        for sq in board.pieces(chess.PAWN, color):
            files[chess.square_file(sq)] += 1
        penalty = sum(DOUBLED_PENALTY * (c - 1) for c in files if c > 1)
        diff += -penalty if color == chess.WHITE else penalty
    return diff

MATE_DRIVE_EDGE = 80
MATE_DRIVE_PROXIMITY = 30


def _mating_drive(board):
    """Edge-and-approach bonus when the opponent is down to a bare king.

    Returns a score from White's point of view, and exactly 0 unless one
    side has nothing but its king while the other holds a rook or queen --
    so it never perturbs an ordinary position.
    """

    black_side = board.occupied_co[chess.BLACK]
    white_side = board.occupied_co[chess.WHITE]

    if black_side & (black_side - 1) == 0:
        strong, weak, sign = chess.WHITE, chess.BLACK, 1
    elif white_side & (white_side - 1) == 0:
        strong, weak, sign = chess.BLACK, chess.WHITE, -1
    else:
        return 0

    if not ((board.queens | board.rooks) & board.occupied_co[strong]):
        return 0

    weak_king = board.king(weak)
    strong_king = board.king(strong)
    if weak_king is None or strong_king is None:
        return 0

    weak_file = chess.square_file(weak_king)
    weak_rank = chess.square_rank(weak_king)
    edge = (3 - min(weak_file, 7 - weak_file)) + (3 - min(weak_rank, 7 - weak_rank))
    between = (abs(chess.square_file(strong_king) - weak_file)
               + abs(chess.square_rank(strong_king) - weak_rank))

    return sign * (MATE_DRIVE_EDGE * edge + MATE_DRIVE_PROXIMITY * (14 - between))


PASSED_PAWN_BONUS = (0, 10, 15, 25, 45, 75, 120, 0)  ß
ISOLATED_PAWN_PENALTY = 12
PAWN_CACHE_MAX = 200_000

_ADJACENT_FILES = [
    (chess.BB_FILES[f - 1] if f > 0 else 0) | (chess.BB_FILES[f + 1] if f < 7 else 0)
    for f in range(8)
]


def _passed_mask(color, square):
    """Squares ahead of `square` (from `color`'s side) on its own and the
    adjacent files -- an enemy pawn on any of them stops it being passed."""
    f, r = chess.square_file(square), chess.square_rank(square)
    files = chess.BB_FILES[f] | _ADJACENT_FILES[f]
    ahead = 0
    ranks = range(r + 1, 8) if color == chess.WHITE else range(0, r)
    for rr in ranks:
        ahead |= chess.BB_RANKS[rr]
    return files & ahead


_PASSED_MASKS = {
    color: [_passed_mask(color, sq) for sq in chess.SQUARES]
    for color in (chess.WHITE, chess.BLACK)
}
_PAWN_CACHE = {}


def _pawn_structure_score(white_pawns, black_pawns):
    """Passed / isolated pawn score from White's point of view."""
    key = (white_pawns, black_pawns)
    score = _PAWN_CACHE.get(key)
    if score is not None:
        return score

    score = 0
    for sq in chess.scan_forward(white_pawns):
        if not black_pawns & _PASSED_MASKS[chess.WHITE][sq]:
            score += PASSED_PAWN_BONUS[chess.square_rank(sq)]
        if not white_pawns & _ADJACENT_FILES[chess.square_file(sq)]:
            score -= ISOLATED_PAWN_PENALTY
    for sq in chess.scan_forward(black_pawns):
        if not white_pawns & _PASSED_MASKS[chess.BLACK][sq]:
            score -= PASSED_PAWN_BONUS[7 - chess.square_rank(sq)]
        if not black_pawns & _ADJACENT_FILES[chess.square_file(sq)]:
            score += ISOLATED_PAWN_PENALTY

    if len(_PAWN_CACHE) >= PAWN_CACHE_MAX:
        _PAWN_CACHE.clear()
    _PAWN_CACHE[key] = score
    return score


def _board_pawn_score(board):
    pawns = board.pawns
    return _pawn_structure_score(pawns & board.occupied_co[chess.WHITE],
                                 pawns & board.occupied_co[chess.BLACK])

ROOK_OPEN_FILE_BONUS = 25
ROOK_HALF_OPEN_FILE_BONUS = 12


def _rook_file_score(board):
    """Open / half-open file bonus for rooks, from White's point of view."""
    rooks = board.rooks
    if not rooks:
        return 0
    pawns = board.pawns
    white = board.occupied_co[chess.WHITE]
    score = 0
    for sq in chess.scan_forward(rooks):
        file_mask = chess.BB_FILES[chess.square_file(sq)]
        if not pawns & file_mask:
            bonus = ROOK_OPEN_FILE_BONUS
        else:
            own = white if chess.BB_SQUARES[sq] & white else board.occupied_co[chess.BLACK]
            if pawns & own & file_mask:
                continue
            bonus = ROOK_HALF_OPEN_FILE_BONUS
        score += bonus if chess.BB_SQUARES[sq] & white else -bonus
    return score


def evaluate(board):
    if board.is_checkmate():
        return -MATE_SCORE if board.turn == chess.WHITE else MATE_SCORE
    if board.is_stalemate() or board.is_insufficient_material() or board.is_fifty_moves() or board.is_repetition():
        return 0
    return (_material_pst_score(board) + _doubled_pawn_diff(board)
            + _bishop_pair_diff(board) + _shield_diff(board)
            + _mating_drive(board) + _board_pawn_score(board)
            + _rook_file_score(board))


def evaluate_relative(board):
    e = evaluate(board)
    return e if board.turn == chess.WHITE else -e


def _castle_squares(color, kingside):
    if color == chess.WHITE:
        return (chess.E1, chess.G1, chess.H1, chess.F1) if kingside else (chess.E1, chess.C1, chess.A1, chess.D1)
    else:
        return (chess.E8, chess.G8, chess.H8, chess.F8) if kingside else (chess.E8, chess.C8, chess.A8, chess.D8)


def _compute_castling_delta(color, kingside, endgame):
    king_from, king_to, rook_from, rook_to = _castle_squares(color, kingside)
    king_delta = _pst_at(chess.KING, color, king_to, endgame) - _pst_at(chess.KING, color, king_from, endgame)
    rook_delta = _pst_at(chess.ROOK, color, rook_to, endgame) - _pst_at(chess.ROOK, color, rook_from, endgame)
    sign = 1 if color == chess.WHITE else -1
    return sign * (king_delta + rook_delta)


CASTLING_DELTA = {
    endgame_flag: {
        color: {kingside_flag: _compute_castling_delta(color, kingside_flag, endgame_flag) for kingside_flag in (True, False)}
        for color in (chess.WHITE, chess.BLACK)
    }
    for endgame_flag in (False, True)
}


def _move_facts(board, move):
    mover_color = board.turn
    piece_type = board.piece_type_at(move.from_square)
    captured_type = board.piece_type_at(move.to_square)
    captured_square = move.to_square if captured_type is not None else None

    is_castling = piece_type == chess.KING and board.is_castling(move)

    is_en_passant = False
    if (piece_type == chess.PAWN and captured_type is None
            and board.ep_square == move.to_square
            and board.is_en_passant(move)):
        is_en_passant = True
        captured_type = chess.PAWN
        captured_square = chess.square(chess.square_file(move.to_square),
                                       chess.square_rank(move.from_square))

    return (mover_color, piece_type, captured_type, captured_square,
            is_castling, is_en_passant)


def _compute_move_delta(board, move, facts):
    mover_color, piece_type, captured_type, captured_square, is_castling, _ = facts
    sign = 1 if mover_color == chess.WHITE else -1

    if is_castling:
        endgame = (_QUEEN_COUNTS[chess.WHITE] + _QUEEN_COUNTS[chess.BLACK]) == 0
        kingside = chess.square_file(move.to_square) > chess.square_file(move.from_square)
        return CASTLING_DELTA[endgame][mover_color][kingside]

    endgame_before = (_QUEEN_COUNTS[chess.WHITE] + _QUEEN_COUNTS[chess.BLACK]) == 0

    delta = 0

    delta -= sign * (_pst_at(piece_type, mover_color, move.from_square, endgame_before))

    queen_removed = False

    if captured_square is not None:
        opp_sign = -sign
        delta -= opp_sign * (_pst_at(captured_type, not mover_color, captured_square, endgame_before))
        queen_removed = captured_type == chess.QUEEN

    queen_added = move.promotion == chess.QUEEN
    if queen_removed or queen_added:
        queen_count_before = _QUEEN_COUNTS[chess.WHITE] + _QUEEN_COUNTS[chess.BLACK]
        queen_count_after = queen_count_before - (1 if queen_removed else 0) + (1 if queen_added else 0)
        endgame_after = queen_count_after == 0
    else:
        endgame_after = endgame_before

    dest_type = move.promotion if move.promotion else piece_type
    delta += sign * (_pst_at(dest_type, mover_color, move.to_square, endgame_after))

    if endgame_after != endgame_before:
        for color, csign in ((chess.WHITE, 1), (chess.BLACK, -1)):
            if piece_type == chess.KING and color == mover_color:
                continue
            king_sq = board.king(color)
            if king_sq is None:
                continue
            old_val = _pst_at(chess.KING, color, king_sq, endgame_before)
            new_val = _pst_at(chess.KING, color, king_sq, endgame_after)
            delta += csign * (new_val - old_val)

    return delta


def _doubled_penalty_for_count(c):
    return DOUBLED_PENALTY * (c - 1) if c > 1 else 0


def _pawn_file_counts(board):
    counts = {chess.WHITE: [0] * 8, chess.BLACK: [0] * 8}
    for color in (chess.WHITE, chess.BLACK):
        for sq in board.pieces(chess.PAWN, color):
            counts[color][chess.square_file(sq)] += 1
    return counts


def _compute_doubled_delta(board, move, facts):
    mover_color, piece_type, captured_type, captured_square, is_castling, _ = facts
    if is_castling:
        return 0, []

    score_delta = 0
    changes = []

    def touch(color, file, count_delta):
        nonlocal score_delta
        old_c = _PAWN_FILES[color][file]
        new_c = old_c + count_delta
        pen_diff = _doubled_penalty_for_count(new_c) - _doubled_penalty_for_count(old_c)
        score_delta += -pen_diff if color == chess.WHITE else pen_diff
        _PAWN_FILES[color][file] = new_c
        changes.append((color, file, count_delta))

    if piece_type == chess.PAWN:
        touch(mover_color, chess.square_file(move.from_square), -1)
        if not move.promotion:
            touch(mover_color, chess.square_file(move.to_square), +1)

    if captured_type == chess.PAWN:
        touch(not mover_color, chess.square_file(captured_square), -1)

    return score_delta, changes


BISHOP_PAIR_BONUS = 50


def _bishop_pair_bonus_for_count(c):
    return BISHOP_PAIR_BONUS if c >= 2 else 0


def _bishop_counts(board):
    return {
        chess.WHITE: _popcount(board.pieces_mask(chess.BISHOP, chess.WHITE)),
        chess.BLACK: _popcount(board.pieces_mask(chess.BISHOP, chess.BLACK)),
    }


def _bishop_pair_diff(board):
    counts = _bishop_counts(board)
    return (
        _bishop_pair_bonus_for_count(counts[chess.WHITE])
        - _bishop_pair_bonus_for_count(counts[chess.BLACK])
    )


def _compute_piece_counts_delta(board, move, facts):
    mover_color, _piece_type, captured_type, _captured_square, _c, _ep = facts
    score_delta = 0
    changes = []

    def touch(color, piece_type, count_delta):
        nonlocal score_delta
        counts = _BISHOP_COUNTS if piece_type == chess.BISHOP else _QUEEN_COUNTS
        old_c = counts[color]
        new_c = old_c + count_delta
        if piece_type == chess.BISHOP:
            bonus_diff = _bishop_pair_bonus_for_count(new_c) - _bishop_pair_bonus_for_count(old_c)
            score_delta += bonus_diff if color == chess.WHITE else -bonus_diff
        counts[color] = new_c
        changes.append((color, piece_type, count_delta))

    if captured_type == chess.BISHOP or captured_type == chess.QUEEN:
        touch(not mover_color, captured_type, -1)

    if move.promotion in (chess.BISHOP, chess.QUEEN):
        touch(mover_color, move.promotion, +1)

    return score_delta, changes


def _shield_pawn_event(board, move, facts):
    mover_color, piece_type, captured_type, captured_square, _c, _ep = facts

    is_pawn_move = piece_type == chess.PAWN
    pawn_from = move.from_square if is_pawn_move else None
    pawn_to = move.to_square if (is_pawn_move and not move.promotion) else None

    if captured_type == chess.PAWN:
        captured_color = not mover_color
        captured_sq = captured_square
    else:
        captured_color = None
        captured_sq = None

    return mover_color, pawn_from, pawn_to, captured_color, captured_sq


def _shield_point_update(pawn_event, color, zone_files):
    mover_color, pawn_from, pawn_to, captured_color, captured_sq = pawn_event
    sign = 1 if color == chess.WHITE else -1
    delta = 0

    if (
        mover_color == color
        and pawn_from is not None
        and chess.square_file(pawn_from) in zone_files
    ):
        if color == chess.WHITE:
            shield_value = pawn_shield_pst[pawn_from]
        else:
            shield_value = pawn_shield_pst[chess.square_mirror(pawn_from)]

        delta -= sign * shield_value

    if (
        mover_color == color
        and pawn_to is not None
        and chess.square_file(pawn_to) in zone_files
    ):
        if color == chess.WHITE:
            shield_value = pawn_shield_pst[pawn_to]
        else:
            shield_value = pawn_shield_pst[chess.square_mirror(pawn_to)]

        delta += sign * shield_value

    if (
        captured_color == color
        and captured_sq is not None
        and chess.square_file(captured_sq) in zone_files
    ):
        if color == chess.WHITE:
            shield_value = pawn_shield_pst[captured_sq]
        else:
            shield_value = pawn_shield_pst[chess.square_mirror(captured_sq)]

        delta -= sign * shield_value

    return delta


_INC_SCORE = 0
_INC_DOUBLED = 0
_INC_BISHOP_PAIR = 0
_INC_SHIELD = 0
_INC_STACK = []
_PAWN_FILES = {chess.WHITE: [0] * 8, chess.BLACK: [0] * 8}
_BISHOP_COUNTS = {chess.WHITE: 0, chess.BLACK: 0}
_QUEEN_COUNTS = {chess.WHITE: 0, chess.BLACK: 0}
_RIGHTS_LOST = {chess.WHITE: False, chess.BLACK: False}
_SHIELD_CONTRIB = {chess.WHITE: 0, chess.BLACK: 0}


def reset_incremental_eval(board):
    global _INC_SCORE, _INC_DOUBLED, _INC_BISHOP_PAIR, _INC_SHIELD, _INC_STACK
    global _PAWN_FILES, _BISHOP_COUNTS, _QUEEN_COUNTS, _RIGHTS_LOST, _SHIELD_CONTRIB
    _PAWN_FILES = _pawn_file_counts(board)
    _BISHOP_COUNTS = _bishop_counts(board)
    _QUEEN_COUNTS = _queen_counts(board)
    _RIGHTS_LOST = _rights_lost_snapshot(board)

    _INC_SCORE = _material_pst_score(board)
    _INC_DOUBLED = _doubled_pawn_diff(board)
    _INC_BISHOP_PAIR = (
        _bishop_pair_bonus_for_count(_BISHOP_COUNTS[chess.WHITE])
        - _bishop_pair_bonus_for_count(_BISHOP_COUNTS[chess.BLACK])
    )

    _SHIELD_CONTRIB = {chess.WHITE: 0, chess.BLACK: 0}
    queenless = (_QUEEN_COUNTS[chess.WHITE] + _QUEEN_COUNTS[chess.BLACK]) == 0
    if not queenless:
        for color in (chess.WHITE, chess.BLACK):
            if _RIGHTS_LOST[color]:
                zone_files = _shield_zone_files(board, color)
                _SHIELD_CONTRIB[color] = _shield_contribution_for_color(board, color, zone_files)
    _INC_SHIELD = _SHIELD_CONTRIB[chess.WHITE] + _SHIELD_CONTRIB[chess.BLACK]

    _INC_STACK = []


def push_move(board, move):
    global _INC_SCORE, _INC_DOUBLED, _INC_BISHOP_PAIR, _INC_SHIELD, _RIGHTS_LOST

    facts = _move_facts(board, move)
    mover_color = facts[0]
    is_king_move = facts[1] == chess.KING

    queenless_before = (_QUEEN_COUNTS[chess.WHITE] + _QUEEN_COUNTS[chess.BLACK]) == 0

    rights_lost_before = _RIGHTS_LOST
    castling_rights_before = board.castling_rights
    pawn_event = _shield_pawn_event(board, move, facts)

    delta = _compute_move_delta(board, move, facts)
    doubled_delta, pawn_file_changes = _compute_doubled_delta(board, move, facts)
    piece_count_delta, piece_count_changes = _compute_piece_counts_delta(board, move, facts)

    board.push(move)

    _INC_SCORE += delta
    _INC_DOUBLED += doubled_delta
    _INC_BISHOP_PAIR += piece_count_delta

    queenless_after = (_QUEEN_COUNTS[chess.WHITE] + _QUEEN_COUNTS[chess.BLACK]) == 0

    if board.castling_rights == castling_rights_before:
        rights_lost_after = rights_lost_before
    else:
        rights_lost_after = _rights_lost_snapshot(board)

    prev_shield_contrib = dict(_SHIELD_CONTRIB)
    shield_delta = 0

    for color in (chess.WHITE, chess.BLACK):
        was_active = rights_lost_before[color] and not queenless_before
        is_active = rights_lost_after[color] and not queenless_after

        if not was_active and not is_active:
            continue

        king_moved_this_color = mover_color == color and is_king_move

        if was_active != is_active or king_moved_this_color:
            new_contrib = 0
            if is_active:
                zone_files = _shield_zone_files(board, color)
                new_contrib = _shield_contribution_for_color(board, color, zone_files)
            shield_delta += new_contrib - _SHIELD_CONTRIB[color]
            _SHIELD_CONTRIB[color] = new_contrib
        else:
            zone_files = _shield_zone_files(board, color)
            point_delta = _shield_point_update(pawn_event, color, zone_files)
            shield_delta += point_delta
            _SHIELD_CONTRIB[color] += point_delta

    _INC_SHIELD += shield_delta
    _RIGHTS_LOST = rights_lost_after

    _INC_STACK.append((
        delta, doubled_delta, pawn_file_changes,
        piece_count_delta, piece_count_changes,
        shield_delta, prev_shield_contrib, rights_lost_before,
    ))


def pop_move(board):
    global _INC_SCORE, _INC_DOUBLED, _INC_BISHOP_PAIR, _INC_SHIELD, _SHIELD_CONTRIB, _RIGHTS_LOST
    board.pop()
    (delta, doubled_delta, pawn_file_changes,
     piece_count_delta, piece_count_changes,
     shield_delta, prev_shield_contrib, rights_lost_before) = _INC_STACK.pop()

    _INC_SCORE -= delta
    _INC_DOUBLED -= doubled_delta
    _INC_BISHOP_PAIR -= piece_count_delta
    _INC_SHIELD -= shield_delta
    _SHIELD_CONTRIB = prev_shield_contrib
    _RIGHTS_LOST = rights_lost_before

    for color, file, count_delta in reversed(pawn_file_changes):
        _PAWN_FILES[color][file] -= count_delta
    for color, piece_type, count_delta in reversed(piece_count_changes):
        counts = _BISHOP_COUNTS if piece_type == chess.BISHOP else _QUEEN_COUNTS
        counts[color] -= count_delta


def _is_drawn(board):
    """Drawn by material, the fifty-move counter, or repetition."""
    return (board.is_insufficient_material()
            or board.is_fifty_moves()
            or board.is_repetition())


def _static_eval_relative(board):
    """The incremental evaluation, from the side to move's point of view.

    Assumes the position is not terminal -- callers that have not already
    ruled that out should go through evaluate_relative_fast().
    """
    total_white = (_INC_SCORE + _INC_DOUBLED + _INC_BISHOP_PAIR + _INC_SHIELD
                   + _mating_drive(board) + _board_pawn_score(board)
                   + _rook_file_score(board))
    return total_white if board.turn == chess.WHITE else -total_white


def evaluate_relative_fast(board):
    """Terminal-aware static evaluation, from the side to move's view.

    The mate/stalemate pair used to be asked as is_checkmate() then
    is_stalemate(), which is two legal-move generations and two check tests
    for the same underlying question -- "are there any legal moves, and if
    not, am I in check?". Asking it once that way is equivalent and costs
    one partial generation instead of two.
    """
    if next(board.generate_legal_moves(), None) is None:
        return -MATE_SCORE if board.is_check() else 0
    if _is_drawn(board):
        return 0
    return _static_eval_relative(board)


def _move_score(board, move, tt_move, killer1, killer2, history, stm):
    if tt_move is not None and move == tt_move:
        return 20_000_000

    if board.occupied_co[not stm] & chess.BB_SQUARES[move.to_square]:
        v = piece_values.get(board.piece_type_at(move.to_square), 0)
        a = piece_values.get(board.piece_type_at(move.from_square), 0)

        if v < a and see(board, move) < 0:
            return 600_000 + 10 * v - a
        return 1_000_000 + 10 * v - a

    if board.ep_square == move.to_square and board.is_en_passant(move):
        return 1_000_000 + 9 * piece_values[chess.PAWN]

    if move.promotion:
        return 900_000 + piece_values.get(move.promotion, 900)

    if move == killer1:
        return 800_000
    if move == killer2:
        return 700_000

    return history.get((stm, move.from_square, move.to_square), 0)


def order_moves(board, moves, tt_move, ply):
    k1, k2 = killer_moves[ply] if ply < MAX_PLY else (None, None)
    stm = board.turn
    moves.sort(key=lambda m: _move_score(board, m, tt_move, k1, k2, history_table, stm), reverse=True)
    return moves


def is_endgame(board):
    return (
        len(board.piece_map()) < 10 or
        board.is_insufficient_material()
    )


def negamax(board, depth, alpha, beta, ply):
    global NODES
    NODES += 1
    _check_time()

    original_alpha = alpha

    if board.is_repetition(2):
        return 0

    key = tt_key(board)
    entry = TT.get(key)
    tt_move = entry[3] if entry is not None else None

    if entry is not None and entry[0] >= depth:
        edepth, estored_score, flag, emove = entry
        escore = _tt_retrieve_score(estored_score, ply)
        if flag == EXACT:
            return escore
        elif flag == LOWER:
            if escore > alpha:
                alpha = escore
        elif flag == UPPER:
            if escore < beta:
                beta = escore
        if alpha >= beta:
            return escore

    in_check = board.is_check()

    static_eval = None

    if (
        not in_check
        and depth <= STATIC_NULL_MAX_DEPTH
        and beta < MATE_SCORE - MAX_PLY
        and beta > -MATE_SCORE + MAX_PLY
    ):
        static_eval = evaluate_relative_fast(board)
        if static_eval - STATIC_NULL_MARGIN_PER_DEPTH * depth >= beta:
            return beta

    if (
        depth >= NULL_MOVE_MIN_DEPTH
        and not in_check
        and beta < MATE_SCORE - MAX_PLY
        and alpha > -MATE_SCORE + MAX_PLY
        and _has_non_pawn_material(board, board.turn)
    ):
        board.push(chess.Move.null())
        try:
            null_score = -negamax(
                board, depth - 1 - NULL_MOVE_REDUCTION, -beta, -beta + 1, ply + 1
            )
        finally:
            board.pop()

        if null_score >= beta:
            return beta
    
    if depth <= 0:
        if next(board.generate_legal_moves(), None) is None:
            return (-MATE_SCORE + ply) if in_check else 0


        return quiescence(board, alpha, beta, ply, has_legal_move=True)

    moves = list(board.generate_legal_moves())
    if not moves:
        return (-MATE_SCORE + ply) if in_check else 0

    moves = order_moves(board, moves, tt_move, ply)

    best_score = -math.inf
    best_move = moves[0]
    stm = board.turn
    them = board.occupied_co[not stm]
    ep_square = board.ep_square

    for i, move in enumerate(moves):

        is_capture = bool(them & chess.BB_SQUARES[move.to_square]) or (
            ep_square == move.to_square and board.is_en_passant(move))
        is_promotion = move.promotion is not None
        gives_check = _gives_check(board, move)


        if (
            depth <= FUTILITY_MAX_DEPTH
            and not in_check
            and not is_capture
            and not is_promotion
            and not gives_check
            and i > 0
        ):
            if static_eval is None:
                static_eval = evaluate_relative_fast(board)
            if static_eval + FUTILITY_MARGINS[depth] <= alpha:
                continue

        push_move(board, move)
        try:
            extension = 1 if gives_check else 0

            if i == 0:
                score = -negamax(board, depth - 1 + extension, -beta, -alpha, ply + 1)

            else:
                reduction = _lmr_reduction(depth, i, in_check, is_capture, is_promotion, gives_check)
                search_depth = depth - 1 + extension - reduction

                score = -negamax(
                    board,
                    search_depth,
                    -alpha - 1,
                    -alpha,
                    ply + 1
                )

                if reduction and score > alpha:
                    score = -negamax(
                        board,
                        depth - 1 + extension,
                        -alpha - 1,
                        -alpha,
                        ply + 1
                    )

                if alpha < score < beta:
                    score = -negamax(
                        board,
                        depth - 1 + extension,
                        -beta,
                        -alpha,
                        ply + 1
                    )
        finally:
            pop_move(board)


        if ply == 1 and score > alpha:
            global _root_best_move
            _root_best_move = move

        if score > best_score:
            best_score, best_move = score, move

        if score > alpha:
            alpha = score

        if alpha >= beta:
            if not is_capture and ply < MAX_PLY:
                if move != killer_moves[ply][0]:
                    killer_moves[ply][1] = killer_moves[ply][0]
                    killer_moves[ply][0] = move
                history_table[(stm, move.from_square, move.to_square)] = (
                    history_table.get((stm, move.from_square, move.to_square), 0) + depth * depth
                )
            break

    if entry is None or depth >= entry[0]:
        if best_score <= original_alpha:
            flag = UPPER
        elif best_score >= beta:
            flag = LOWER
        else:
            flag = EXACT
        TT[key] = (depth, _tt_store_score(best_score, ply), flag, best_move)

    return best_score


def get_best_move(board, depth, time_limit=None):
    global _search_deadline, _time_check_counter, _root_best_move

    start_time = time.time()
    best_move = None
    last_score = 0

    reset_incremental_eval(board)

    _search_deadline = (start_time + time_limit) if time_limit is not None else None
    _time_check_counter = 0

    try:
        for d in range(1, depth + 1):
            for ply_killers in killer_moves:
                ply_killers[0] = ply_killers[1] = None
            _root_best_move = None

            if d <= 2:
                alpha, beta = -math.inf, math.inf
            else:
                window = 50
                alpha, beta = last_score - window, last_score + window

            while True:
                score = negamax(board, d, alpha, beta, ply=1)
                if score <= alpha:
                    alpha = -math.inf
                    continue
                if score >= beta:
                    beta = math.inf
                    continue
                break

            last_score = score
            entry = TT.get(tt_key(board))
            if entry is not None and entry[3] is not None:
                best_move = entry[3]

            if time_limit is not None and time.time() - start_time > time_limit:
                break
    except SearchAborted:

        if _root_best_move is not None:
            best_move = _root_best_move
    finally:
        _search_deadline = None

    if best_move is None:

        best_move = next(board.generate_legal_moves(), None)

    return best_move


def quiescence(board, alpha, beta, ply, has_legal_move=False):
    """Search captures and promotions until the position is quiet.

    has_legal_move lets the caller say it has already confirmed the
    position is not mate or stalemate, which saves repeating a legal-move
    generation that has just been done.
    """
    global NODES
    NODES += 1
    _check_time()

    in_check = board.is_check()

    if in_check:
        def cap_score(m):
            if board.is_en_passant(m):
                return 1_000_000
            v = piece_values.get(board.piece_type_at(m.to_square), 0)
            a = piece_values.get(board.piece_type_at(m.from_square), 0)
            return 10 * v - a

        moves = list(board.generate_legal_moves())
        if not moves:
            return -MATE_SCORE + ply

        moves.sort(key=cap_score, reverse=True)

        best = -math.inf
        for move in moves:
            push_move(board, move)
            try:
                score = -quiescence(board, -beta, -alpha, ply + 1)
            finally:
                pop_move(board)

            if score > best:
                best = score
            if score > alpha:
                alpha = score
            if alpha >= beta:
                return beta

        return best

    if has_legal_move:
        stand_pat = 0 if _is_drawn(board) else _static_eval_relative(board)
    else:
        stand_pat = evaluate_relative_fast(board)

    if stand_pat >= beta:
        return beta
    if stand_pat > alpha:
        alpha = stand_pat

    them = board.occupied_co[not board.turn]
    ep_square = board.ep_square
    to_mask = them | chess.BB_RANK_1 | chess.BB_RANK_8
    if ep_square is not None:
        to_mask |= chess.BB_SQUARES[ep_square]

    scored_captures = [
        (see(board, m), m)
        for m in board.generate_legal_moves(chess.BB_ALL, to_mask)
        if (them & chess.BB_SQUARES[m.to_square]) or m.promotion
        or (ep_square == m.to_square and board.is_en_passant(m))
    ]
    scored_captures.sort(key=lambda t: t[0], reverse=True)

    for see_value, move in scored_captures:
        if see_value < 0:
            continue

        if stand_pat + see_value + DELTA_MARGIN <= alpha and not move.promotion \
                and _has_non_pawn_material(board, not board.turn):
            continue

        push_move(board, move)
        try:
            score = -quiescence(board, -beta, -alpha, ply + 1)
        finally:
            pop_move(board)

        if score >= beta:
            return beta
        if score > alpha:
            alpha = score

    return alpha