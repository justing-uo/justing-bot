"""
PySide6 GUI for the existing Python chess engine.

Put this file beside your engine:

    chess_engine.py
    chess_gui.py

Run:
    python3 chess_gui.py

The chess engine itself is imported directly and is not rewritten.
"""

import sys
import time

import chess
from PySide6.QtCore import QObject, QThread, Signal, Qt, QTimer
from PySide6.QtGui import QFont, QPainter, QColor, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import chess_engine as engine
import opening_book


# ---------------------------------------------------------------------------
# Appearance
# ---------------------------------------------------------------------------

LIGHT = QColor("#b6b6b6")
DARK = QColor("#636363")
LAST = QColor("#c8b458")
SELECTED = QColor("#d6a84f")
LEGAL = QColor("#607b4b")

BACKGROUND = "#1c1611"
PANEL = "#241b14"
TEXT = "#f1e7d2"
MUTED = "#b9a98f"

PIECES = {
    "P": "♙", "N": "♘", "B": "♗", "R": "♖", "Q": "♕", "K": "♔",
    "p": "♟", "n": "♞", "b": "♝", "r": "♜", "q": "♛", "k": "♚",
}


# ---------------------------------------------------------------------------
# Board widget
# ---------------------------------------------------------------------------

class BoardWidget(QWidget):
    move_requested = Signal(object)

    def __init__(self, board):
        super().__init__()
        self.board = board
        self.human_color = chess.WHITE
        self.selected = None
        self.targets = set()
        self.last_move = None

        # Normally only pieces of self.human_color can be picked up (see
        # mousePressEvent), matching "you play one side, the engine plays
        # the other." The opening book editor sets this to True so either
        # side can be moved regardless of self.human_color, since it's
        # building book lines rather than playing a game -- board
        # orientation still follows self.human_color either way.
        self.free_color_selection = False

        self.setMinimumSize(600, 600)

    def set_position(self, board, human_color, last_move=None):
        self.board = board
        self.human_color = human_color
        self.last_move = last_move
        self.selected = None
        self.targets.clear()
        self.update()

    def _geometry(self):
        size = min(self.width(), self.height())
        x0 = (self.width() - size) / 2
        y0 = (self.height() - size) / 2
        return x0, y0, size / 8

    def _screen_square(self, x, y):
        x0, y0, sq = self._geometry()
        file = int((x - x0) / sq)
        row = int((y - y0) / sq)

        if not (0 <= file < 8 and 0 <= row < 8):
            return None

        if self.human_color == chess.WHITE:
            return chess.square(file, 7 - row)

        return chess.square(7 - file, row)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        x0, y0, sq = self._geometry()

        # Board squares.
        for row in range(8):
            for file in range(8):
                if self.human_color == chess.WHITE:
                    square = chess.square(file, 7 - row)
                else:
                    square = chess.square(7 - file, row)

                color = LIGHT if (file + row) % 2 == 0 else DARK

                if self.last_move and square in (
                    self.last_move.from_square,
                    self.last_move.to_square,
                ):
                    color = LAST

                if square == self.selected:
                    color = SELECTED

                painter.fillRect(
                    int(x0 + file * sq),
                    int(y0 + row * sq),
                    int(sq + 1),
                    int(sq + 1),
                    color,
                )

        # Legal move indicators.
        for square in self.targets:
            file = chess.square_file(square)
            rank = chess.square_rank(square)

            if self.human_color == chess.WHITE:
                display_file = file
                display_row = 7 - rank
            else:
                display_file = 7 - file
                display_row = rank

            cx = x0 + (display_file + 0.5) * sq
            cy = y0 + (display_row + 0.5) * sq

            painter.setPen(Qt.NoPen)

            if self.board.piece_at(square):
                painter.setBrush(Qt.NoBrush)
                painter.setPen(
                    QPen(LEGAL, max(3, int(sq * 0.055)))
                )
                painter.drawEllipse(
                    int(x0 + display_file * sq + 5),
                    int(y0 + display_row * sq + 5),
                    int(sq - 10),
                    int(sq - 10),
                )
            else:
                painter.setBrush(LEGAL)
                r = max(5, sq * 0.105)
                painter.drawEllipse(
                    int(cx - r),
                    int(cy - r),
                    int(2 * r),
                    int(2 * r),
                )

        # Pieces.
        font = QFont("Arial Unicode MS")
        font.setPointSize(max(28, int(sq * 0.67)))

        for square, piece in self.board.piece_map().items():
            file = chess.square_file(square)
            rank = chess.square_rank(square)

            if self.human_color == chess.WHITE:
                display_file = file
                display_row = 7 - rank
            else:
                display_file = 7 - file
                display_row = rank

            cx = x0 + (display_file + 0.5) * sq
            cy = y0 + (display_row + 0.5) * sq

            painter.setFont(font)
            painter.setPen(
                QColor("#16120f")
                if piece.color == chess.BLACK
                else QColor("#fffaf0")
            )

            painter.drawText(
                int(cx - sq / 2),
                int(cy - sq / 2),
                int(sq),
                int(sq),
                Qt.AlignCenter,
                PIECES[piece.symbol()],
            )

        # Coordinates.
        coord_font = QFont("Helvetica")
        coord_font.setBold(True)
        coord_font.setPointSize(max(8, int(sq * 0.12)))
        painter.setFont(coord_font)

        for file in range(8):
            painter.setPen(
                DARK if (file + 7) % 2 == 0 else LIGHT
            )
            painter.drawText(
                int(x0 + file * sq + 5),
                int(y0 + 8 * sq - 5),
                int(sq - 8),
                18,
                Qt.AlignLeft | Qt.AlignBottom,
                "abcdefgh"[file]
                if self.human_color == chess.WHITE
                else "hgfedcba"[file],
            )

        for row in range(8):
            painter.setPen(
                DARK if row % 2 == 0 else LIGHT
            )
            label = (
                str(8 - row)
                if self.human_color == chess.WHITE
                else str(row + 1)
            )
            painter.drawText(
                int(x0 + 8 * sq - 20),
                int(y0 + row * sq + 5),
                15,
                int(sq - 8),
                Qt.AlignRight | Qt.AlignTop,
                label,
            )

        painter.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or not self.isEnabled():
            return

        square = self._screen_square(
            event.position().x(),
            event.position().y(),
        )

        if square is None:
            return

        piece = self.board.piece_at(square)
        selectable_color = self.board.turn if self.free_color_selection else self.human_color

        # Nothing selected: select a friendly piece.
        if self.selected is None:
            if piece and piece.color == selectable_color:
                self.selected = square
                self.targets = {
                    m.to_square
                    for m in self.board.legal_moves
                    if m.from_square == square
                }
                self.update()
            return

        # Clicking another friendly piece changes selection.
        if piece and piece.color == selectable_color:
            self.selected = square
            self.targets = {
                m.to_square
                for m in self.board.legal_moves
                if m.from_square == square
            }
            self.update()
            return

        candidates = [
            m for m in self.board.legal_moves
            if m.from_square == self.selected
            and m.to_square == square
        ]

        if candidates:
            self.selected = None
            self.targets.clear()
            self.update()
            self.move_requested.emit(candidates)
        else:
            self.selected = None
            self.targets.clear()
            self.update()


# ---------------------------------------------------------------------------
# Background engine worker
# ---------------------------------------------------------------------------
#
# A fresh QThread used to be created for every single engine move. When a
# move computes quickly (which happens often -- shallow searches, forced
# recaptures, and especially the fast mate-in-N searches common right at
# the end of a game), a new QThread can get created and torn down faster
# than Qt can safely finish destroying the previous one, which crashes
# with "QThread: Destroyed while thread is still running". Instead there
# is ONE worker thread for the whole lifetime of the window: each move is
# dispatched to it via a queued signal (ChessWindow.compute_requested ->
# EngineWorker.compute) and the result comes back the same way
# (EngineWorker.finished / .failed).

class EngineWorker(QObject):
    finished = Signal(object, float, int)
    failed = Signal(str)

    def compute(self, board, depth):
        try:
            start = time.time()

            move = engine.get_best_move(
                board,
                depth,
            )

            elapsed = time.time() - start
            nodes = getattr(engine, "NODES", 0)

            self.finished.emit(move, elapsed, nodes)

        except Exception as exc:
            self.failed.emit(
                f"{type(exc).__name__}: {exc}"
            )


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class ChessWindow(QMainWindow):
    # Cross-thread dispatch signal: emitted in the main thread, delivered
    # (automatically queued by Qt) to EngineWorker.compute() running on
    # self.thread. See the EngineWorker comment above for why this exists
    # instead of a new QThread per move.
    compute_requested = Signal(object, int)

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Python Chess Engine")
        self.setMinimumSize(940, 700)

        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background: {BACKGROUND};
                color: {TEXT};
            }}

            QComboBox, QSpinBox {{
                background: #30251b;
                color: {TEXT};
                border: 1px solid #5a4633;
                padding: 7px;
                border-radius: 4px;
            }}

            QPushButton {{
                background: #3a2c20;
                color: {TEXT};
                border: 1px solid #5a4633;
                padding: 9px;
                border-radius: 4px;
            }}

            QPushButton:hover {{
                background: #4a3828;
            }}
        """)

        self.board = chess.Board()
        self.human_color = chess.WHITE
        self.last_move = None

        # --- Move history / navigation state -----------------------------
        # self.moves / self.sans are parallel lists, one entry per ply
        # played so far. self.snapshots[0] is the starting position and
        # self.snapshots[k] is the position after the k-th ply. These are
        # independent of self.board's own move_stack so we can freely
        # display any past position without disturbing the live game.
        self.moves = []
        self.sans = []
        self.snapshots = [self.board.copy()]
        self.view_index = 0  # which snapshot is currently displayed

        self.thinking = False
        self.thread = None
        self.worker = None

        # The window opens in a "not started yet" state: the board is
        # shown but disabled, clocks are displayed but not ticking, and
        # nothing happens until the person clicks "Start Game" (or hits
        # R). Without this, a time control would start silently counting
        # down the instant the window appeared, before anyone had a
        # chance to even look at the board.
        self.game_started = False

        # Set once a real engine search is actually launched, and only
        # then is its result allowed to reach engine.record_move_time --
        # see _start_engine / _engine_finished. An opening-book move
        # finishes a ply without ever setting this, so its (near-zero,
        # not-actually-thinking) time can never be mistaken for genuine
        # engine think time.
        self.awaiting_search_result = False

        # --- Chess clock ---------------------------------------------------
        # The GUI owns the clocks.  The engine is NOT given the remaining
        # time yet; its search simply runs while the engine clock ticks.
        self.time_control_minutes = 3
        self.time_control_increment = 0
        self.white_time = 3 * 60.0
        self.black_time = 3 * 60.0
        self.clock_running = False
        self.clock_side = chess.WHITE
        self.clock_last_update = time.monotonic()
        self.clock_expired = False

        self.clock_timer = QTimer(self)
        self.clock_timer.setInterval(50)
        self.clock_timer.timeout.connect(self._clock_tick)

        # Loaded once and shared by reference with the book editor window
        # (see open_book_editor), so edits made there take effect
        # immediately without this window needing to reload anything.
        self.book = opening_book.load_book()
        self.book_editor_window = None

        # One worker thread for the lifetime of this window. Every engine
        # move is dispatched to it via compute_requested rather than
        # creating a new QThread per move (see EngineWorker above).
        self.worker = EngineWorker()
        self.thread = QThread(self)
        self.worker.moveToThread(self.thread)
        self.worker.finished.connect(self._engine_finished)
        self.worker.failed.connect(self._engine_failed)
        self.compute_requested.connect(self.worker.compute)
        self.thread.start()

        self._build_ui()
        self._reset_clocks(start_timer=False)
        self.status.setText(
            "Set your options, then click \u201cStart Game\u201d to begin."
        )
        self._refresh()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        main = QHBoxLayout(central)
        main.setContentsMargins(18, 18, 18, 18)
        main.setSpacing(18)

        # Board.
        self.board_widget = BoardWidget(self.board)
        self.board_widget.move_requested.connect(
            self._human_move
        )
        main.addWidget(self.board_widget, 1)

        # Side panel.
        panel = QWidget()
        panel.setFixedWidth(260)
        panel.setStyleSheet(
            f"background: {PANEL};"
        )

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 20, 18, 20)
        layout.setSpacing(10)

        title = QLabel("Python Chess Engine")
        title.setStyleSheet(
            f"""
            color: {TEXT};
            font-size: 19px;
            font-weight: bold;
            """
        )
        layout.addWidget(title)

        subtitle = QLabel(
            "justing"
        )
        subtitle.setStyleSheet(
            f"color: {MUTED};"
        )
        layout.addWidget(subtitle)

        layout.addSpacing(15)

        side_label = QLabel("Play as")
        side_label.setStyleSheet(
            "font-weight: bold;"
        )
        layout.addWidget(side_label)

        self.side_box = QComboBox()
        self.side_box.addItems([
            "White",
            "Black",
        ])
        self.side_box.currentIndexChanged.connect(
            self._side_changed
        )
        layout.addWidget(self.side_box)

        time_label = QLabel("Time control")
        time_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(time_label)

        self.time_control_box = QComboBox()
        self.time_controls = [
            ("0.25 + 1", 0.25, 1),
            ("1 + 0", 1, 0),
            ("1 + 1", 1, 1),
            ("3 + 0", 3, 0),
            ("3 + 2", 3, 2),
            ("5 + 0", 5, 0),
            ("5 + 3", 5, 3),
            ("10 + 0", 10, 0),
            ("10 + 5", 10, 5),
            ("15 + 10", 15, 10),
            ("60 + 30", 60, 30),
        ]
        self.time_control_box.addItems([name for name, _, _ in self.time_controls])
        self.time_control_box.setCurrentIndex(3)  # 3 + 0
        self.time_control_box.currentIndexChanged.connect(self._time_control_changed)
        layout.addWidget(self.time_control_box)

        self.white_clock = QLabel()
        self.black_clock = QLabel()
        for clock in (self.white_clock, self.black_clock):
            clock.setAlignment(Qt.AlignCenter)
            clock.setMinimumHeight(46)
            clock.setStyleSheet(
                f"background: #30251b; color: {TEXT}; "
                "font-size: 20px; font-weight: bold; border-radius: 5px;"
            )

        layout.addWidget(self.black_clock)
        layout.addWidget(self.white_clock)

        layout.addSpacing(12)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(80)
        self.status.setStyleSheet(
            f"""
            color: {TEXT};
            font-size: 11pt;
            """
        )
        layout.addWidget(self.status)

        self.start_button = QPushButton(
            "Start Game"
        )
        self.start_button.clicked.connect(
            self.new_game
        )
        layout.addWidget(self.start_button)

        self.new_button = QPushButton(
            "New Game"
        )
        self.new_button.clicked.connect(
            self.new_game
        )
        self.new_button.setVisible(False)
        layout.addWidget(self.new_button)

        layout.addSpacing(12)

        self.book_checkbox = QCheckBox(
            "Use Opening Book"
        )
        self.book_checkbox.setChecked(True)
        layout.addWidget(self.book_checkbox)

        self.book_button = QPushButton(
            "Edit Opening Book..."
        )
        self.book_button.clicked.connect(
            self.open_book_editor
        )
        layout.addWidget(self.book_button)

        layout.addSpacing(12)

        moves_label = QLabel("Moves")
        moves_label.setStyleSheet(
            "font-weight: bold;"
        )
        layout.addWidget(moves_label)

        self.start_label = QLabel(
            "\u23ee  Start position"
        )
        self.start_label.setStyleSheet(
            f"color: {MUTED}; text-decoration: underline;"
        )
        self.start_label.setCursor(Qt.PointingHandCursor)
        self.start_label.mousePressEvent = (
            lambda event: self._goto_ply(0)
        )
        layout.addWidget(self.start_label)

        self.move_table = QTableWidget(0, 3)
        self.move_table.setHorizontalHeaderLabels(
            ["#", "White", "Black"]
        )
        self.move_table.verticalHeader().setVisible(False)
        self.move_table.horizontalHeader().setStretchLastSection(True)
        self.move_table.setColumnWidth(0, 30)
        self.move_table.setColumnWidth(1, 85)
        self.move_table.setEditTriggers(
            QTableWidget.NoEditTriggers
        )
        self.move_table.setSelectionMode(
            QTableWidget.NoSelection
        )
        self.move_table.setFocusPolicy(Qt.NoFocus)
        self.move_table.setFixedHeight(230)
        self.move_table.setStyleSheet(f"""
            QTableWidget {{
                background: #2a2015;
                color: {TEXT};
                gridline-color: #4a3828;
                border: 1px solid #5a4633;
                border-radius: 4px;
            }}
            QHeaderView::section {{
                background: #3a2c20;
                color: {MUTED};
                border: none;
                padding: 4px;
            }}
        """)
        self.move_table.cellClicked.connect(
            self._table_cell_clicked
        )
        layout.addWidget(self.move_table)

        layout.addStretch()

        main.addWidget(panel)

    # -----------------------------------------------------------------
    # View / history management
    # -----------------------------------------------------------------

    def _apply_view(self):
        """Render whichever snapshot self.view_index points to, and
        keep the board read-only unless it's the live position."""
        board_to_show = self.snapshots[self.view_index]
        last = (
            self.moves[self.view_index - 1]
            if self.view_index > 0
            else None
        )

        self.board_widget.set_position(
            board_to_show,
            self.human_color,
            last,
        )

        self._update_board_enabled()
        self._rebuild_move_table()

    def _update_board_enabled(self):
        is_live = self.view_index == len(self.moves)
        game_over = self.board.is_game_over()

        self.board_widget.setEnabled(
            self.game_started and is_live and not self.thinking and not game_over
        )
        if hasattr(self, "time_control_box"):
            self.time_control_box.setEnabled(not self.thinking)

    def _update_status_for_view(self):
        if not self.game_started:
            return

        if self.view_index != len(self.moves):
            self.status.setText(
                f"Viewing move {self.view_index} of "
                f"{len(self.moves)}\n(read-only — click the "
                f"latest move to return)"
            )
            return

        if self.board.is_game_over() or self.thinking:
            return

        if self.board.turn == self.human_color:
            self.status.setText("Your turn")
        else:
            self.status.setText("Engine to move")

    def _goto_ply(self, ply):
        ply = max(0, min(ply, len(self.moves)))

        if ply == self.view_index:
            return

        self.view_index = ply
        self._apply_view()
        self._update_status_for_view()

    def _table_cell_clicked(self, row, column):
        if column == 1:
            ply = row * 2 + 1
        elif column == 2:
            ply = row * 2 + 2
        else:
            return

        if ply > len(self.moves):
            return

        self._goto_ply(ply)

    def _rebuild_move_table(self):
        table = self.move_table
        table.blockSignals(True)

        row_count = (len(self.moves) + 1) // 2
        table.setRowCount(row_count)

        for row in range(row_count):
            white_ply = row * 2 + 1
            black_ply = row * 2 + 2

            num_item = table.item(row, 0)
            if num_item is None:
                num_item = QTableWidgetItem()
                num_item.setFlags(Qt.ItemIsEnabled)
                table.setItem(row, 0, num_item)
            num_item.setText(str(row + 1))
            num_item.setBackground(QColor(PANEL))

            white_item = table.item(row, 1)
            if white_item is None:
                white_item = QTableWidgetItem()
                white_item.setFlags(Qt.ItemIsEnabled)
                table.setItem(row, 1, white_item)
            white_item.setText(self.sans[white_ply - 1])
            white_item.setBackground(
                SELECTED if white_ply == self.view_index
                else QColor("#2a2015")
            )

            black_item = table.item(row, 2)
            if black_item is None:
                black_item = QTableWidgetItem()
                black_item.setFlags(Qt.ItemIsEnabled)
                table.setItem(row, 2, black_item)
            has_black = black_ply <= len(self.moves)
            black_item.setText(
                self.sans[black_ply - 1] if has_black else ""
            )
            black_item.setBackground(
                SELECTED if has_black and black_ply == self.view_index
                else QColor("#2a2015")
            )

        table.blockSignals(False)

        if row_count:
            table.scrollToBottom()

    def _refresh(self):
        """Snap the view to the live position and refresh everything."""
        self.view_index = len(self.moves)
        self._apply_view()
        self._update_status_for_view()

    def _side_changed(self, index):
        if self.thinking:
            return

        self.human_color = (
            chess.WHITE
            if index == 0
            else chess.BLACK
        )

        if self.game_started:
            self.new_game()
        else:
            # Just re-render at the new orientation; don't start the game
            # (and definitely don't start the clock) just from picking a
            # side in the pre-game setup screen.
            self._refresh()

    def _time_control_changed(self, index):
        if self.thinking:
            return

        _, minutes, increment = self.time_controls[index]
        if minutes is None:
            self.time_control_minutes = None
            self.time_control_increment = 0
        else:
            self.time_control_minutes = minutes
            self.time_control_increment = increment

        if self.game_started:
            self.new_game()
        else:
            # Update the clock display to show the newly selected time
            # control, but leave it stopped -- this is still pre-game.
            self._reset_clocks(start_timer=False)

    def _reset_clocks(self, start_timer=True):
        if self.time_control_minutes is None:
            self.white_time = None
            self.black_time = None
            self.clock_running = False
            self.clock_timer.stop()
        else:
            seconds = self.time_control_minutes * 60.0
            self.white_time = seconds
            self.black_time = seconds
            self.clock_side = chess.WHITE
            self.clock_last_update = time.monotonic()
            self.clock_running = start_timer
            self.clock_expired = False
            if start_timer:
                self.clock_timer.start()
            else:
                self.clock_timer.stop()
        self._update_clock_labels()

    def _update_clock_labels(self):
        self.white_clock.setText(self._format_clock(self.white_time))
        self.black_clock.setText(self._format_clock(self.black_time))

        if self.time_control_minutes is None:
            active_style = f"background: #30251b; color: {TEXT}; font-size: 20px; font-weight: bold; border-radius: 5px;"
            self.white_clock.setStyleSheet(active_style)
            self.black_clock.setStyleSheet(active_style)
            return

        normal = f"background: #30251b; color: {TEXT}; font-size: 20px; font-weight: bold; border-radius: 5px;"
        active = f"background: #4a3828; color: {TEXT}; font-size: 20px; font-weight: bold; border: 2px solid #c8b458; border-radius: 5px;"
        low = f"background: #4a3828; color: #ffcf70; font-size: 20px; font-weight: bold; border-radius: 5px;"

        self.white_clock.setStyleSheet(
            active if self.clock_running and self.clock_side == chess.WHITE
            else low if self.white_time is not None and self.white_time < 10
            else normal
        )
        self.black_clock.setStyleSheet(
            active if self.clock_running and self.clock_side == chess.BLACK
            else low if self.black_time is not None and self.black_time < 10
            else normal
        )

    @staticmethod
    def _format_clock(seconds):
        if seconds is None:
            return "--:--"
        seconds = max(0.0, seconds)
        total_centiseconds = int(seconds * 100)
        whole_seconds, centiseconds = divmod(total_centiseconds, 100)
        minutes, secs = divmod(whole_seconds, 60)
        if minutes >= 1:
            return f"{minutes:02d}:{secs:02d}"
        return f"{secs:02d}.{centiseconds:02d}"

    def _clock_tick(self):
        if not self.clock_running or self.time_control_minutes is None or self.clock_expired:
            return

        now = time.monotonic()
        elapsed = now - self.clock_last_update
        self.clock_last_update = now

        if self.clock_side == chess.WHITE:
            self.white_time -= elapsed
            if self.white_time <= 0:
                self.white_time = 0.0
                self._time_forfeit(chess.WHITE)
                return
        else:
            self.black_time -= elapsed
            if self.black_time <= 0:
                self.black_time = 0.0
                self._time_forfeit(chess.BLACK)
                return

        self._update_clock_labels()

    def _stop_clock_for_move(self, mover):
        if self.time_control_minutes is None or not self.clock_running:
            return

        # Apply any time since the last QTimer tick immediately, so the
        # clock is accurate at the exact moment a move is made.
        now = time.monotonic()
        elapsed = now - self.clock_last_update
        self.clock_last_update = now

        if mover == chess.WHITE:
            self.white_time -= elapsed
        else:
            self.black_time -= elapsed

        # If the mover's clock expired before the move was completed, the
        # increment is not awarded.
        if mover == chess.WHITE and self.white_time <= 0:
            self.white_time = 0.0
            self._time_forfeit(chess.WHITE)
            return
        if mover == chess.BLACK and self.black_time <= 0:
            self.black_time = 0.0
            self._time_forfeit(chess.BLACK)
            return

        # Increment is awarded after a successfully completed move.
        if mover == chess.WHITE:
            self.white_time += self.time_control_increment
        else:
            self.black_time += self.time_control_increment

        self.clock_side = not mover
        self.clock_last_update = time.monotonic()
        self._update_clock_labels()

    def _time_forfeit(self, expired_side):
        if self.clock_expired:
            return

        self.clock_expired = True
        self.clock_running = False
        self.clock_timer.stop()
        self._update_clock_labels()

        winner = "Black" if expired_side == chess.WHITE else "White"
        text = f"{winner} wins on time."
        self.status.setText(text)
        self.board_widget.setEnabled(False)

        # If the engine is still searching, its result will be ignored when
        # it eventually returns.  We deliberately do not try to kill the
        # Python worker thread here.
        QMessageBox.information(self, "Time", text)

    def _human_move(self, candidates):
        if (
            self.thinking
            or self.board.turn != self.human_color
            or self.view_index != len(self.moves)
        ):
            return

        if len(candidates) == 1:
            move = candidates[0]
        else:
            move = self._promotion_dialog(
                candidates
            )

            if move is None:
                self._refresh()
                return

        san = self.board.san(move)
        mover = self.board.turn
        self._stop_clock_for_move(mover)
        if self.clock_expired:
            return
        self.board.push(move)
        self.moves.append(move)
        self.sans.append(san)
        self.snapshots.append(self.board.copy())
        self.last_move = move

        self._refresh()

        if self._game_over():
            return

        self._start_engine()

    def _promotion_dialog(self, candidates):
        choices = {
            chess.QUEEN: "Queen",
            chess.ROOK: "Rook",
            chess.BISHOP: "Bishop",
            chess.KNIGHT: "Knight",
        }

        box = QMessageBox(self)
        box.setWindowTitle(
            "Promote"
        )
        box.setText(
            "Choose promotion:"
        )

        buttons = {}

        for piece_type, name in choices.items():
            button = box.addButton(
                name,
                QMessageBox.AcceptRole,
            )
            buttons[button] = piece_type

        box.exec()

        clicked = box.clickedButton()

        if clicked not in buttons:
            return None

        promotion = buttons[clicked]

        return next(
            m for m in candidates
            if m.promotion == promotion
        )

    def _start_engine(self):
        if self.board.is_game_over():
            return

        # Reset first; only a genuine search launched below sets this back
        # to True. If a book move is played instead, it stays False, so
        # _engine_finished (which shouldn't even fire in that case) can
        # never mistake a book move for a real, timed engine search.
        self.awaiting_search_result = False

        if self.book_checkbox.isChecked():
            book_move = opening_book.choose_move(self.book, self.board)
            if book_move is not None:
                self._play_book_move(book_move)
                return
            # Not in the book (or no legal entries left here) -- fall
            # through to a normal engine search below.

        self.thinking = True
        self._update_board_enabled()

        # Drive the search from the engine's own (possibly auto-increased)
        # depth. This is intentionally never shown to or editable by the
        # user.
        depth = engine.computer_depth

        self.status.setText(
            "Engine thinking..."
        )

        # Give the engine its own copy. This is important because the GUI
        # should never mutate the same chess.Board while the search is
        # running.
        search_board = self.board.copy(
            stack=True
        )

        self.awaiting_search_result = True
        self.compute_requested.emit(search_board, depth)

    def _play_book_move(self, move):
        """Play a move straight from the opening book -- no search, no
        background thread, just push it like a completed engine move.
        Deliberately never touches engine.record_move_time: a book move's
        near-instant "elapsed" time isn't genuine engine think time (see
        _start_engine's awaiting_search_result, which stays False here)."""
        san = self.board.san(move)
        mover = self.board.turn
        self._stop_clock_for_move(mover)
        if self.clock_expired:
            return
        self.board.push(move)
        self.moves.append(move)
        self.sans.append(san)
        self.snapshots.append(self.board.copy())
        self.last_move = move

        self.status.setText(
            f"Book move: {move.uci()}"
        )

        self.view_index = len(self.moves)
        self._apply_view()
        self._game_over()

    def _engine_finished(
        self,
        move,
        elapsed,
        nodes,
    ):
        self.thinking = False

        if not self.awaiting_search_result:
            # This ply was already resolved another way (in practice: an
            # opening-book move) before this search result arrived. It
            # doesn't represent real engine think time, so it must not
            # reach engine.record_move_time -- just drop it.
            return

        self.awaiting_search_result = False

        if self.clock_expired:
            return

        if (
            move is None
            or move not in self.board.legal_moves
        ):
            self._update_board_enabled()
            self.status.setText(
                "Engine returned no legal move."
            )
            self._game_over()
            return

        mover = self.board.turn
        self._stop_clock_for_move(mover)
        if self.clock_expired:
            return

        engine_color = self.board.turn
        
        san = self.board.san(move)
        self.board.push(move)
        self.moves.append(move)
        self.sans.append(san)
        self.snapshots.append(self.board.copy())
        self.last_move = move

        time_remaining = (
            self.white_time
            if engine_color == chess.WHITE
            else self.black_time
        )

        engine.record_move_time(elapsed, time_remaining)

        self.view_index = len(self.moves)
        self._apply_view()
        self._game_over()

    def _engine_failed(self, message):
        self.thinking = False
        self._update_board_enabled()

        QMessageBox.critical(
            self,
            "Engine Error",
            message,
        )

        self.status.setText(
            "Engine error."
        )

    def _game_over(self):
        if not self.board.is_game_over():
            return False

        # Stop the clock the moment the game ends on the board, so it
        # doesn't keep ticking after checkmate/stalemate/draw is reached
        # (as opposed to _time_forfeit, which handles the clock running
        # out first).
        self.clock_running = False
        self.clock_timer.stop()
        self._update_clock_labels()

        if self.board.is_checkmate():
            winner = (
                "White"
                if self.board.turn == chess.BLACK
                else "Black"
            )
            text = (
                f"{winner} wins by checkmate."
            )

        elif self.board.is_stalemate():
            text = "Draw by stalemate."

        elif self.board.is_insufficient_material():
            text = (
                "Draw by insufficient material."
            )

        elif self.board.is_fifty_moves():
            text = (
                "Draw by the 50-move rule."
            )

        elif self.board.is_repetition():
            text = (
                "Draw by repetition."
            )

        else:
            text = (
                f"Game over: "
                f"{self.board.result()}"
            )

        self.status.setText(text)

        QMessageBox.information(
            self,
            "Game Over",
            text,
        )

        self.board_widget.setEnabled(
            False
        )

        return True

    def undo(self):
        if (
            self.thinking
            or not self.moves
        ):
            return

        # Normally undo both the engine's move and the user's preceding
        # move, returning to the user's previous position.
        pop_count = 2 if len(self.moves) >= 2 else 1

        for _ in range(pop_count):
            self.board.pop()
            self.moves.pop()
            self.sans.pop()
            self.snapshots.pop()

        self.last_move = (
            self.moves[-1] if self.moves else None
        )

        self._reset_clocks()
        if self.time_control_minutes is not None:
            self.clock_side = self.board.turn
            self.clock_last_update = time.monotonic()
            self._update_clock_labels()
        self._refresh()

    def new_game(self):
        if self.thinking:
            return

        engine.reset_dynamic_depth()

        self.board = chess.Board()
        self.moves = []
        self.sans = []
        self.snapshots = [self.board.copy()]
        self.last_move = None

        self.game_started = True
        self.start_button.setVisible(False)
        self.new_button.setVisible(True)

        # White always moves first regardless of which color the human is
        # playing, so the clock always starts on White here -- _reset_clocks
        # already takes care of that.
        self._reset_clocks(start_timer=True)
        self._refresh()

        if self.human_color != chess.WHITE:
            self._start_engine()

    def open_battle_window(self):
        # Imported lazily to avoid a circular import (chess_battle_gui
        # itself imports BoardWidget and colors from this module).
        from chess_battle_gui import BattleWindow

        self.battle_window = BattleWindow()
        self.battle_window.show()

    def open_book_editor(self):
        # Imported lazily for the same reason as chess_battle_gui above.
        from opening_book_editor import BookEditorWindow

        # Pass self.book itself (not a copy) so edits made in the editor
        # are visible here immediately, with no reload step needed.
        self.book_editor_window = BookEditorWindow(book=self.book)
        self.book_editor_window.show()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_U:
            self.undo()
        elif event.key() == Qt.Key_R:
            self.new_game()
        elif event.key() == Qt.Key_Left:
            self._goto_ply(self.view_index - 1)
        elif event.key() == Qt.Key_Right:
            self._goto_ply(self.view_index + 1)
        elif event.key() == Qt.Key_Home:
            self._goto_ply(0)
        elif event.key() == Qt.Key_End:
            self._goto_ply(len(self.moves))
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.clock_timer.stop()

        self.thread.quit()
        # If an engine move is mid-computation the thread's event loop
        # can't act on quit() until that call returns, so give it a real
        # window to finish rather than a token wait.
        if not self.thread.wait(5000):
            self.thread.terminate()
            self.thread.wait()

        event.accept()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = QApplication(sys.argv)
    app.setApplicationName(
        "Python Chess Engine"
    )

    window = ChessWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()