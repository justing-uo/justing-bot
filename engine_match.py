"""
Shared utilities for pitting two chess engine modules against each other.

Both engine modules are expected to expose the same interface that
chess_gui.py already relies on:

    engine.get_best_move(board, depth) -> chess.Move
    engine.computer_depth              -> int   (default search depth)

Optional, used if present (mirrors what chess_gui.py does for a single
engine):

    engine.record_move_time(elapsed, time_remaining)
                                        -> None  (updates dynamic depth;
                                                  time_remaining is None
                                                  when the caller doesn't
                                                  track a clock -- e.g. the
                                                  depth-only headless match
                                                  runner)
    engine.reset_dynamic_depth()       -> None  (called at the start of
                                                  each game)
    engine.NODES                       -> int   (node count of last search)

This means chess_engine2.py (or any other variant) just needs to match
that interface -- no changes to this file are needed to test a new
version.

Result reporting
----------------
record_game() appends every finished game as one JSON object per line to
match_results.jsonl (next to this file). Each line holds the engines, the
result, the reason, the full move list (SAN + UCI), the final FEN, and a
short hash of each engine's source file so results can be tied back to
the exact engine version that played. Both engine_vs_engine.py and
chess_battle_gui.py call it.

Print a per-engine tally with:

    python3 engine_match.py                 # games between the engine files
                                            # as they are on disk right now
    python3 engine_match.py --all           # every logged game, any version
    python3 engine_match.py --last 20       # only the 20 most recent games

The default matters for the usual workflow (edit chess_engine2.py, test it
against chess_engine.py, copy the winner over both files): module names stay
the same across versions, so only the fingerprints tell old results apart.
"""

import datetime
import hashlib
import importlib
import json
import math
import os
import sys
import time

import chess

RESULTS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "match_results.jsonl"
)


def load_engine(module_name):
    """Import an engine module by name (e.g. 'chess_engine', 'chess_engine2').

    Reloads the module if it was already imported, so edits to the engine
    file are picked up without restarting the interpreter.
    """
    module = importlib.import_module(module_name)
    importlib.reload(module)
    return module


def reset_dynamic_depth_safe(engine_module):
    """Call engine.reset_dynamic_depth() if the engine defines it."""
    reset = getattr(engine_module, "reset_dynamic_depth", None)
    if callable(reset):
        reset()


def record_move_time_safe(engine_module, elapsed, time_remaining=None):
    """Call engine.record_move_time(elapsed, time_remaining) if the engine
    defines it. time_remaining is None for callers that don't track a
    clock (e.g. the depth-only headless match runner) -- engines that
    define record_move_time are expected to accept that and just skip
    any clock-based depth adjustment in that case."""
    record = getattr(engine_module, "record_move_time", None)
    if callable(record):
        record(elapsed, time_remaining)


def resolve_depth(engine_module, override):
    """Pick a search depth: an explicit override, else the engine's own
    computer_depth, else a conservative fallback."""
    if override:
        return override
    return getattr(engine_module, "computer_depth", 3)


# Depth ceiling for movetime games -- high enough that time, not depth,
# always ends the search.
MOVETIME_MAX_DEPTH = 64


class GameResult:
    def __init__(self, winner, reason, moves, sans, plies,
                 move_times=None, move_nodes=None, completed=True):
        self.winner = winner  # chess.WHITE, chess.BLACK, or None (draw)
        self.reason = reason  # human-readable string
        self.moves = moves  # list[chess.Move]
        self.sans = sans  # list[str]
        self.plies = plies
        self.move_times = move_times or []  # list[float], seconds per ply
        self.move_nodes = move_nodes or []  # list[int], nodes per ply
        self.completed = completed  # False if the game was stopped early


def play_game(
    white_engine,
    black_engine,
    white_depth=None,
    black_depth=None,
    max_plies=300,
    on_move=None,
    should_stop=None,
    movetime=None,
    opening=None,
):
    """Play one game between two engine modules.

    white_engine / black_engine: imported engine modules (see load_engine).
    white_depth / black_depth: optional depth override for each side.
    movetime: optional seconds per move, passed to get_best_move as its
        time_limit. With a movetime the depth is only a ceiling (default
        MOVETIME_MAX_DEPTH), so the clock decides how deep each search goes.
    opening: optional list of chess.Move played before the engines take
        over (logged with 0.0s / 0 nodes). Fixed openings are what make
        repeated games between deterministic engines differ at all.
    on_move(board, move, san, elapsed, nodes, mover_color): optional
        callback invoked after each move (e.g. to update a GUI).
    should_stop: optional callable returning True to abort the game early.
    """
    board = chess.Board()
    moves = []
    sans = []
    move_times = []
    move_nodes = []

    reset_dynamic_depth_safe(white_engine)
    reset_dynamic_depth_safe(black_engine)

    for move in opening or ():
        sans.append(board.san(move))
        board.push(move)
        moves.append(move)
        move_times.append(0.0)
        move_nodes.append(0)

    # claim_draw: stop at the first threefold repetition / fifty-move draw
    # instead of playing on to fivefold / seventy-five moves.
    while not board.is_game_over(claim_draw=True) and len(moves) < max_plies:
        if should_stop and should_stop():
            return GameResult(
                None, "Stopped by user.", moves, sans, len(moves),
                move_times, move_nodes, completed=False,
            )

        mover_color = board.turn
        engine_module = white_engine if mover_color == chess.WHITE else black_engine
        depth_override = white_depth if mover_color == chess.WHITE else black_depth

        start = time.time()
        if movetime is not None:
            depth = depth_override or MOVETIME_MAX_DEPTH
            move = engine_module.get_best_move(board, depth, movetime)
        else:
            depth = resolve_depth(engine_module, depth_override)
            move = engine_module.get_best_move(board, depth)
        elapsed = time.time() - start
        nodes = getattr(engine_module, "NODES", 0)

        if move is None or move not in board.legal_moves:
            winner = chess.BLACK if mover_color == chess.WHITE else chess.WHITE
            side = "White" if mover_color == chess.WHITE else "Black"
            return GameResult(
                winner,
                f"{side} engine returned no legal move.",
                moves,
                sans,
                len(moves),
                move_times,
                move_nodes,
            )

        san = board.san(move)
        board.push(move)
        moves.append(move)
        sans.append(san)
        move_times.append(elapsed)
        move_nodes.append(nodes)

        # This headless runner has no clock -- time_remaining defaults to
        # None, and engines that support dynamic depth are expected to
        # just record the elapsed time without adjusting depth in that case.
        record_move_time_safe(engine_module, elapsed)

        if on_move:
            on_move(board, move, san, elapsed, nodes, mover_color)

    outcome = board.outcome(claim_draw=True)
    if outcome is None:
        winner, reason = None, f"Move limit ({max_plies} plies) reached."
    else:
        winner = outcome.winner
        reason = {
            chess.Termination.CHECKMATE: "Checkmate.",
            chess.Termination.STALEMATE: "Stalemate.",
            chess.Termination.INSUFFICIENT_MATERIAL: "Insufficient material.",
            chess.Termination.FIFTY_MOVES: "50-move rule.",
            chess.Termination.SEVENTYFIVE_MOVES: "50-move rule.",
            chess.Termination.THREEFOLD_REPETITION: "Repetition.",
            chess.Termination.FIVEFOLD_REPETITION: "Repetition.",
        }.get(outcome.termination, outcome.termination.name)

    return GameResult(winner, reason, moves, sans, len(moves), move_times, move_nodes)


# ---------------------------------------------------------------------------
# Result reporting
# ---------------------------------------------------------------------------

def engine_fingerprint(engine_module):
    """Short hash of an engine module's source file, so logged games can be
    matched to the exact engine version that played them."""
    return _file_fingerprint(getattr(engine_module, "__file__", None))


def current_fingerprint(module_name):
    """Fingerprint of <module_name>.py next to this file, as it is on disk
    now (without importing it)."""
    here = os.path.dirname(os.path.abspath(__file__))
    return _file_fingerprint(os.path.join(here, f"{module_name}.py"))


def _file_fingerprint(path):
    if not path:
        return None
    try:
        with open(path, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()[:10]
    except OSError:
        return None


def _result_string(winner, completed):
    if not completed:
        return "*"
    if winner == chess.WHITE:
        return "1-0"
    if winner == chess.BLACK:
        return "0-1"
    return "1/2-1/2"


def record_game(
    white_engine,
    black_engine,
    winner,
    reason,
    moves,
    source,
    completed=True,
    move_times=None,
    move_nodes=None,
    extra=None,
    path=None,
):
    """Append one finished game to match_results.jsonl.

    white_engine / black_engine: the engine modules that played.
    winner: chess.WHITE, chess.BLACK, or None for a draw.
    moves: list[chess.Move] from the starting position.
    source: which runner played the game (e.g. "engine_vs_engine").
    completed: False for games that were stopped/aborted -- they're logged
        with result "*" and left out of the tally.
    extra: optional dict of runner-specific info (depths, time control...).

    Never raises: a logging failure is reported on stderr so it can't
    interrupt a match.
    """
    board = chess.Board()
    sans = []
    for move in moves:
        sans.append(board.san(move))
        board.push(move)

    white_name = white_engine.__name__
    black_name = black_engine.__name__
    result = _result_string(winner, completed)
    if result == "1-0":
        winner_name = white_name
    elif result == "0-1":
        winner_name = black_name
    else:
        winner_name = None

    record = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "source": source,
        "white": white_name,
        "black": black_name,
        "white_version": engine_fingerprint(white_engine),
        "black_version": engine_fingerprint(black_engine),
        "result": result,
        "winner": winner_name,
        "reason": reason,
        "plies": len(moves),
        "moves_san": " ".join(sans),
        "moves_uci": " ".join(m.uci() for m in moves),
        "final_fen": board.fen(),
    }
    if move_times:
        record["total_time_white"] = round(sum(move_times[0::2]), 3)
        record["total_time_black"] = round(sum(move_times[1::2]), 3)
        record["move_times"] = [round(t, 3) for t in move_times]
    if move_nodes:
        record["move_nodes"] = list(move_nodes)
    if extra:
        record.update(extra)

    try:
        with open(path or RESULTS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(f"Could not write match result: {exc}", file=sys.stderr)
    return record


def load_results(path=None):
    """Read every logged game from match_results.jsonl (skipping bad lines)."""
    records = []
    try:
        with open(path or RESULTS_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except FileNotFoundError:
        pass
    return records


def _elo_from_score(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return -400.0 * math.log10(1.0 / p - 1.0) + 0.0  # + 0.0: no "-0"


def _score_from_elo(elo):
    return 1.0 / (1.0 + 10.0 ** (-elo / 400.0))


def sprt(wins, draws, losses, elo0=0.0, elo1=25.0, alpha=0.05, beta=0.05):
    """Sequential probability ratio test for early stopping.

    Weighs H0 "the new engine is elo0 stronger" (normally 0: no better)
    against H1 "it is elo1 stronger", using the standard normal
    approximation to the game-score log-likelihood ratio (as in cutechess /
    fishtest's GSPRT). alpha is the chance of accepting H1 when H0 is true
    (promoting a change that isn't better); beta the chance of the reverse
    (rejecting a change that is elo1 better). 0.05 each = 95% confidence.

    Returns (llr, lower_bound, upper_bound, verdict) where verdict is
    "H1" (better -- stop and promote), "H0" (not better -- stop and
    revert), or None (keep playing).
    """
    lower = math.log(beta / (1 - alpha))
    upper = math.log((1 - beta) / alpha)
    n = wins + draws + losses
    if n == 0:
        return 0.0, lower, upper, None
    x = (wins + 0.5 * draws) / n
    variance = (wins * (1 - x) ** 2 + draws * (0.5 - x) ** 2 + losses * x ** 2) / n
    if variance <= 0:
        # Every game had the same result so far -- no spread to judge by yet.
        return 0.0, lower, upper, None
    s0, s1 = _score_from_elo(elo0), _score_from_elo(elo1)
    llr = n * (s1 - s0) * (2 * x - s0 - s1) / (2 * variance)
    verdict = "H1" if llr >= upper else "H0" if llr <= lower else None
    return llr, lower, upper, verdict


def score_to_elo(wins, draws, losses):
    """Elo difference implied by a W/D/L record, with a 95% error margin.

    Rough guide: an interval that includes 0 means the match hasn't shown
    either side to be stronger yet.
    """
    n = wins + draws + losses
    if n == 0:
        return 0.0, float("inf")
    p = (wins + 0.5 * draws) / n
    variance = (wins * (1 - p) ** 2 + draws * (0.5 - p) ** 2 + losses * p ** 2) / n
    se = math.sqrt(variance / n)
    low, high = _elo_from_score(p - 1.96 * se), _elo_from_score(p + 1.96 * se)
    return _elo_from_score(p), (high - low) / 2


def summarize_results(records):
    """Return a printable per-engine tally for a list of logged games."""
    decisive = ("1-0", "0-1", "1/2-1/2")
    stats = {}
    reasons = {}
    counted = 0
    for r in records:
        if r.get("result") not in decisive:
            continue
        counted += 1
        reasons[r.get("reason")] = reasons.get(r.get("reason"), 0) + 1
        for color in ("white", "black"):
            name = r[color]
            s = stats.setdefault(
                name, {"games": 0, "score": 0.0, "wins": 0, "losses": 0,
                       "draws": 0, "white_score": 0.0, "black_score": 0.0},
            )
            s["games"] += 1
            if r["result"] == "1/2-1/2":
                points = 0.5
                s["draws"] += 1
            elif r["winner"] == name:
                points = 1.0
                s["wins"] += 1
            else:
                points = 0.0
                s["losses"] += 1
            s["score"] += points
            s[f"{color}_score"] += points

    lines = [f"Games counted: {counted}"]
    for name, s in sorted(stats.items()):
        pct = 100.0 * s["score"] / s["games"] if s["games"] else 0.0
        lines.append(
            f"  {name}: {s['score']:g}/{s['games']} ({pct:.1f}%)  "
            f"+{s['wins']} ={s['draws']} -{s['losses']}  "
            f"[as White {s['white_score']:g}, as Black {s['black_score']:g}]"
        )
    if len(stats) == 2:
        (a, _), (b, sb) = sorted(stats.items())
        elo, margin = score_to_elo(sb["wins"], sb["draws"], sb["losses"])
        lines.append(f"  {b} vs {a}: {elo:+.0f} +/- {margin:.0f} Elo (95%)")
    if reasons:
        lines.append("Endings:")
        for reason, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {reason}: {n}")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Summarize match_results.jsonl")
    parser.add_argument("--last", type=int, default=None,
                        help="Only summarize the N most recent games")
    parser.add_argument("--file", default=None,
                        help="Results file (default: match_results.jsonl)")
    parser.add_argument("--all", action="store_true",
                        help="Include games played by older engine versions")
    args = parser.parse_args()

    records = load_results(args.file)
    if not args.all:
        before = len(records)
        records = [
            r for r in records
            if r.get("white_version") == current_fingerprint(r.get("white"))
            and r.get("black_version") == current_fingerprint(r.get("black"))
        ]
        versions = {
            name: current_fingerprint(name)
            for name in ("chess_engine", "chess_engine2")
        }
        print("Current versions: " + ", ".join(
            f"{name} [{v}]" for name, v in versions.items()))
        if len(set(versions.values())) == 1:
            print("(Both files are identical -- this is a self-play baseline.)")
        if before > len(records):
            print(f"Skipping {before - len(records)} game(s) from older "
                  f"versions (use --all to include them).")
    if args.last:
        records = records[-args.last:]
    print(summarize_results(records))
