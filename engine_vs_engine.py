#!/usr/bin/env python3
"""
Play two chess engine modules against each other headlessly and report a
win/loss/draw tally.

Put this file beside your engine files:

    chess_engine.py
    chess_engine2.py
    engine_match.py
    engine_vs_engine.py
    opening_book.py / opening_book.json

Usage:
    python3 engine_vs_engine.py
    python3 engine_vs_engine.py --engine1 chess_engine --engine2 chess_engine2 --games 20
    python3 engine_vs_engine.py --depth1 3 --depth2 4 --max-moves 200
    python3 engine_vs_engine.py --movetime 0.1 --games 200 --jobs 6
    python3 engine_vs_engine.py --movetime 0.1 --games 1000 --jobs 8 --sprt
    python3 engine_vs_engine.py --no-swap   # engine1 is always White
    python3 engine_vs_engine.py --no-book   # every game from the start position

Openings: by default each game starts by walking opening_book.json (the
same book and random choice the battle GUI uses) until the book runs out.
Games are played in pairs -- the same book opening twice, with colors
swapped -- so neither engine is handed the easier side of an opening by
luck. --seed makes the sequence of openings repeatable.

--movetime gives each engine a fixed number of seconds per move instead
of a fixed depth, which is the fair way to compare versions that differ
in speed. --jobs plays several games at once in separate processes.

--sprt stops the match early once the result is decided at 95%
confidence: either engine2 is better than engine1 (by about --elo1, default
25 Elo) or it isn't (--elo0, default 0). --games is then just the cap; a
match that reaches it undecided is reported as inconclusive. A big
improvement or a clear regression is typically decided in 100-300 games;
a change worth only a few Elo may never be.

By default engine1 and engine2 alternate colors each game (engine1 is
White on odd-numbered games), which is the standard way to cancel out any
first-move advantage over a match.
"""

import argparse
import multiprocessing
import queue
import random
import sys

import chess

from engine_match import (
    RESULTS_PATH,
    load_engine,
    play_game,
    record_game,
    score_to_elo,
    sprt,
)
from opening_book import DEFAULT_BOOK_PATH, choose_move, load_book


def book_opening(book, rng):
    """Walk the book from the start position, picking randomly at each
    step, until it has no move for the position reached."""
    board = chess.Board()
    moves = []
    while True:
        move = choose_move(book, board, rng=rng)
        if move is None:
            return moves
        board.push(move)
        moves.append(move)


# --- Worker processes (used for --jobs > 1, and inline for --jobs 1) ---

_ENGINES = {}


def _init_worker(engine1_name, engine2_name):
    _ENGINES[engine1_name] = load_engine(engine1_name)
    _ENGINES[engine2_name] = load_engine(engine2_name)


def _play_one(job):
    white = _ENGINES[job["white_name"]]
    black = _ENGINES[job["black_name"]]
    opening = [chess.Move.from_uci(u) for u in job["opening"]]
    result = play_game(
        white, black,
        white_depth=job["white_depth"],
        black_depth=job["black_depth"],
        max_plies=job["max_plies"],
        movetime=job["movetime"],
        opening=opening,
    )
    return job, {
        "winner": result.winner,
        "reason": result.reason,
        "moves": [m.uci() for m in result.moves],
        "plies": result.plies,
        "completed": result.completed,
        "move_times": result.move_times,
        "move_nodes": result.move_nodes,
    }


def _bounded_results(pool, jobs, max_in_flight):
    """Yield (job, result) pairs as games finish, keeping only
    max_in_flight games queued in the pool at a time. Handing the pool all
    jobs up front would leave hundreds queued when --sprt stops early."""
    done = queue.Queue()
    pending = iter(jobs)
    in_flight = 0

    def submit():
        nonlocal in_flight
        job = next(pending, None)
        if job is not None:
            pool.apply_async(_play_one, (job,),
                             callback=done.put, error_callback=done.put)
            in_flight += 1

    for _ in range(max_in_flight):
        submit()
    while in_flight:
        item = done.get()
        in_flight -= 1
        if isinstance(item, BaseException):
            raise item
        submit()
        yield item


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--engine1", default="chess_engine",
        help="Module name of engine 1 (default: chess_engine)",
    )
    parser.add_argument(
        "--engine2", default="chess_engine2",
        help="Module name of engine 2 (default: chess_engine2)",
    )
    parser.add_argument(
        "--games", type=int, default=10,
        help="Number of games to play (default: 10)",
    )
    parser.add_argument(
        "--depth1", type=int, default=None,
        help="Search depth for engine1 (default: engine's own computer_depth)",
    )
    parser.add_argument(
        "--depth2", type=int, default=None,
        help="Search depth for engine2 (default: engine's own computer_depth)",
    )
    parser.add_argument(
        "--movetime", type=float, default=None,
        help="Seconds per move for both engines; depth becomes only a ceiling",
    )
    parser.add_argument(
        "--max-moves", type=int, default=300,
        help="Max plies per game before calling it a draw (default: 300)",
    )
    parser.add_argument(
        "--no-swap", action="store_true",
        help="Keep engine1 as White for every game instead of alternating",
    )
    parser.add_argument(
        "--book", default=str(DEFAULT_BOOK_PATH),
        help="Opening book JSON (default: opening_book.json)",
    )
    parser.add_argument(
        "--no-book", action="store_true",
        help="Start every game from the initial position",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Random seed for opening selection (default: random)",
    )
    parser.add_argument(
        "--jobs", type=int, default=1,
        help="Games to play in parallel (default: 1)",
    )
    parser.add_argument(
        "--sprt", action="store_true",
        help="Stop early once engine2 is shown better or not better (95%% confidence)",
    )
    parser.add_argument(
        "--elo0", type=float, default=0.0,
        help="SPRT: Elo gain that counts as 'not better' (default: 0)",
    )
    parser.add_argument(
        "--elo1", type=float, default=25.0,
        help="SPRT: Elo gain that counts as 'better' (default: 25)",
    )
    args = parser.parse_args()

    if args.engine1 == args.engine2:
        print(
            "engine1 and engine2 are the same module name -- scores will "
            "be combined into a single tally.",
            file=sys.stderr,
        )

    try:
        engine1 = load_engine(args.engine1)
        engine2 = load_engine(args.engine2)
    except ImportError as exc:
        print(f"Could not import an engine module: {exc}", file=sys.stderr)
        sys.exit(1)
    modules = {args.engine1: engine1, args.engine2: engine2}

    book = None if args.no_book else load_book(args.book)
    rng = random.Random(args.seed)

    jobs = []
    opening = []
    for game_num in range(1, args.games + 1):
        engine1_is_white = args.no_swap or (game_num % 2 == 1)
        # New opening for each pair of games; the second game of the pair
        # replays it with colors swapped.
        if game_num % 2 == 1:
            opening = book_opening(book, rng) if book else []

        if engine1_is_white:
            white_name, black_name = args.engine1, args.engine2
            white_depth, black_depth = args.depth1, args.depth2
        else:
            white_name, black_name = args.engine2, args.engine1
            white_depth, black_depth = args.depth2, args.depth1

        jobs.append({
            "game_num": game_num,
            "white_name": white_name,
            "black_name": black_name,
            "white_depth": white_depth,
            "black_depth": black_depth,
            "max_plies": args.max_moves,
            "movetime": args.movetime,
            "opening": [m.uci() for m in opening],
        })

    score = {args.engine1: 0.0, args.engine2: 0.0}
    wins = {args.engine1: 0, args.engine2: 0}
    draws = 0
    finished = 0
    verdict = None

    if args.jobs > 1:
        pool = multiprocessing.Pool(
            args.jobs, initializer=_init_worker,
            initargs=(args.engine1, args.engine2),
        )
        results = _bounded_results(pool, jobs, args.jobs)
    else:
        pool = None
        _init_worker(args.engine1, args.engine2)
        results = map(_play_one, jobs)

    stopped_cleanly = False
    try:
        for job, result in results:
            finished += 1
            white_name, black_name = job["white_name"], job["black_name"]
            winner = result["winner"]

            record_game(
                modules[white_name], modules[black_name],
                winner, result["reason"],
                [chess.Move.from_uci(u) for u in result["moves"]],
                source="engine_vs_engine",
                completed=result["completed"],
                move_times=result["move_times"],
                move_nodes=result["move_nodes"],
                extra={
                    "game_num": job["game_num"],
                    "white_depth": job["white_depth"],
                    "black_depth": job["black_depth"],
                    "movetime": job["movetime"],
                    "max_plies": job["max_plies"],
                    "opening_plies": len(job["opening"]),
                },
            )

            if winner is None:
                draws += 1
                score[args.engine1] += 0.5
                score[args.engine2] += 0.5
                outcome = f"Draw ({result['reason']})"
            elif winner == chess.WHITE:
                wins[white_name] += 1
                score[white_name] += 1
                outcome = f"{white_name} wins as White ({result['reason']})"
            else:
                wins[black_name] += 1
                score[black_name] += 1
                outcome = f"{black_name} wins as Black ({result['reason']})"

            sprt_text = ""
            if args.sprt:
                llr, lower, upper, verdict = sprt(
                    wins[args.engine2], draws, wins[args.engine1],
                    args.elo0, args.elo1,
                )
                sprt_text = f"  LLR {llr:+.2f} [{lower:.2f}, {upper:.2f}]"

            print(
                f"Game {job['game_num']} ({finished}/{args.games}): {outcome}  "
                f"[{result['plies']} plies]{sprt_text}",
                flush=True,
            )
            if verdict is not None:
                break
        stopped_cleanly = True
    finally:
        if pool is not None:
            if stopped_cleanly:
                # At most --jobs games are still in progress (see
                # _bounded_results); let them finish rather than killing
                # workers mid-write. Their results are discarded.
                pool.close()
                pool.join()
            else:
                pool.terminate()

    print()
    print("=" * 50)
    print(f"Final score after {finished} games:")
    print(f"  {args.engine1}: {score[args.engine1]:g}  ({wins[args.engine1]} wins)")
    print(f"  {args.engine2}: {score[args.engine2]:g}  ({wins[args.engine2]} wins)")
    print(f"  Draws: {draws}")
    if finished and args.engine1 != args.engine2:
        elo, margin = score_to_elo(wins[args.engine2], draws, wins[args.engine1])
        print(f"  {args.engine2} vs {args.engine1}: {elo:+.0f} +/- {margin:.0f} Elo")
    if args.sprt:
        if verdict == "H1":
            print(f"  SPRT: {args.engine2} is BETTER (95% confidence) -- stopped early")
        elif verdict == "H0":
            print(f"  SPRT: {args.engine2} is NOT better (95% confidence) -- stopped early")
        else:
            print(f"  SPRT: inconclusive after {finished} games")
    print("=" * 50)
    print(f"Results logged to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
