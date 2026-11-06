"""
GUI editor for the opening book (see opening_book.py).

Play out the moves you want in the book directly on the board -- every
move you make is added to the book at the position it was played from
and saved to disk immediately. Existing book moves for the current
position are listed on the side; click one to step into that line, or
remove it without navigating there.

Put this file beside chess_gui.py and opening_book.py:

    chess_engine.py
    chess_gui.py
    opening_book.py
    opening_book_editor.py

Run standalone:
    python3 opening_book_editor.py

Or launch it from chess_gui.py via the "Edit Opening Book..." button
(which shares its live book with this editor, so changes made here take
effect immediately without reloading).
"""

import sys
from pathlib import Path

import chess
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from chess_gui import BoardWidget, BACKGROUND, PANEL, TEXT, MUTED
import opening_book


class BookEditorWindow(QMainWindow):
    def __init__(self, book=None, path=None):
        super().__init__()

        self.setWindowTitle("Opening Book Editor")
        self.setMinimumSize(940, 700)

        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background: {BACKGROUND};
                color: {TEXT};
            }}

            QPushButton {{
                background: #3a2c20;
                color: {TEXT};
                border: 1px solid #5a4633;
                padding: 8px;
                border-radius: 4px;
            }}

            QPushButton:hover {{
                background: #4a3828;
            }}

            QPushButton:disabled {{
                color: {MUTED};
            }}
        """)

        self.path = Path(path) if path is not None else opening_book.DEFAULT_BOOK_PATH

        # Edit the SAME dict object the main window plays from, if one
        # was passed in -- edits here are then visible there immediately,
        # with no reload step needed. Standalone runs just load their own.
        self.book = book if book is not None else opening_book.load_book(self.path)

        self.board = chess.Board()
        self.path_moves = []  # chess.Move objects played so far in this editor
        self.path_sans = []

        self._build_ui()
        self._refresh()

    # -----------------------------------------------------------------
    # UI construction
    # -----------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        main = QHBoxLayout(central)
        main.setContentsMargins(18, 18, 18, 18)
        main.setSpacing(18)

        self.board_widget = BoardWidget(self.board)
        self.board_widget.free_color_selection = True  # move either side here
        self.board_widget.move_requested.connect(self._move_played)
        main.addWidget(self.board_widget, 1)

        panel = QWidget()
        panel.setFixedWidth(300)
        panel.setStyleSheet(f"background: {PANEL};")

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 20, 18, 20)
        layout.setSpacing(10)

        title = QLabel("Opening Book Editor")
        title.setStyleSheet(f"color: {TEXT}; font-size: 19px; font-weight: bold;")
        layout.addWidget(title)

        help_text = QLabel(
            "Play a move on the board to add it to the book at this "
            "position and step into it. Every change saves immediately."
        )
        help_text.setWordWrap(True)
        help_text.setStyleSheet(f"color: {MUTED};")
        layout.addWidget(help_text)

        layout.addSpacing(10)

        breadcrumb_title = QLabel("Current line")
        breadcrumb_title.setStyleSheet("font-weight: bold;")
        layout.addWidget(breadcrumb_title)

        self.breadcrumb_label = QLabel()
        self.breadcrumb_label.setWordWrap(True)
        self.breadcrumb_label.setStyleSheet(f"color: {MUTED};")
        layout.addWidget(self.breadcrumb_label)

        nav_row = QHBoxLayout()
        self.start_button = QPushButton("Start Position")
        self.start_button.clicked.connect(self._go_to_start)
        nav_row.addWidget(self.start_button)

        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self._go_back)
        nav_row.addWidget(self.back_button)
        layout.addLayout(nav_row)

        layout.addSpacing(14)

        moves_title = QLabel("Book moves at this position")
        moves_title.setStyleSheet("font-weight: bold;")
        layout.addWidget(moves_title)

        # Scrollable list, one row per existing book move at the current
        # position -- rebuilt after every navigation or edit.
        self.moves_container = QWidget()
        self.moves_layout = QVBoxLayout(self.moves_container)
        self.moves_layout.setContentsMargins(0, 0, 0, 0)
        self.moves_layout.setSpacing(6)
        self.moves_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.moves_container)
        scroll.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(scroll, 1)

        layout.addSpacing(10)

        self.reload_button = QPushButton("Reload from Disk")
        self.reload_button.clicked.connect(self._reload)
        layout.addWidget(self.reload_button)

        self.save_status = QLabel("")
        self.save_status.setWordWrap(True)
        self.save_status.setStyleSheet(f"color: {MUTED};")
        layout.addWidget(self.save_status)

        main.addWidget(panel)

    # -----------------------------------------------------------------
    # Navigation
    # -----------------------------------------------------------------

    def _go_to_start(self):
        self.board = chess.Board()
        self.path_moves = []
        self.path_sans = []
        self._refresh()

    def _go_back(self):
        if not self.path_moves:
            return
        self.path_moves.pop()
        self.path_sans.pop()
        self.board = chess.Board()
        for m in self.path_moves:
            self.board.push(m)
        self._refresh()

    def _step_into(self, move):
        san = self.board.san(move)
        self.board.push(move)
        self.path_moves.append(move)
        self.path_sans.append(san)
        self._refresh()

    # -----------------------------------------------------------------
    # Editing
    # -----------------------------------------------------------------

    def _move_played(self, candidates):
        if len(candidates) == 1:
            move = candidates[0]
        else:
            move = self._promotion_dialog(candidates)
            if move is None:
                self._refresh()  # re-render to clear the board's selection
                return

        san = self.board.san(move)
        opening_book.add_move(self.book, self.board, move)
        self._save()

        self.board.push(move)
        self.path_moves.append(move)
        self.path_sans.append(san)
        self._refresh()

    def _remove_move(self, move):
        opening_book.remove_move(self.book, self.board, move)
        self._save()
        self._refresh()

    def _promotion_dialog(self, candidates):
        choices = {
            chess.QUEEN: "Queen",
            chess.ROOK: "Rook",
            chess.BISHOP: "Bishop",
            chess.KNIGHT: "Knight",
        }

        box = QMessageBox(self)
        box.setWindowTitle("Promote")
        box.setText("Choose promotion:")

        buttons = {}
        for piece_type, name in choices.items():
            button = box.addButton(name, QMessageBox.AcceptRole)
            buttons[button] = piece_type

        box.exec()

        clicked = box.clickedButton()
        if clicked not in buttons:
            return None

        promotion = buttons[clicked]
        return next(m for m in candidates if m.promotion == promotion)

    def _save(self):
        try:
            opening_book.save_book(self.book, self.path)
            self.save_status.setText(f"Saved to {self.path.name}")
        except OSError as exc:
            self.save_status.setText(f"Save failed: {exc}")

    def _reload(self):
        self.book = opening_book.load_book(self.path)
        self.save_status.setText("Reloaded from disk.")
        self._refresh()

    # -----------------------------------------------------------------
    # Rendering
    # -----------------------------------------------------------------

    def _refresh(self):
        last_move = self.path_moves[-1] if self.path_moves else None
        self.board_widget.set_position(self.board, chess.WHITE, last_move)
        self.back_button.setEnabled(bool(self.path_moves))

        self.breadcrumb_label.setText(
            " ".join(self.path_sans) if self.path_sans else "(start position)"
        )

        self._rebuild_moves_list()

    def _rebuild_moves_list(self):
        # Clear existing rows, keeping the trailing stretch item.
        while self.moves_layout.count() > 1:
            item = self.moves_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        moves = opening_book.moves_for_position(self.book, self.board)

        if not moves:
            empty = QLabel("No book moves here yet -- play one on the board to add it.")
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color: {MUTED};")
            self.moves_layout.insertWidget(self.moves_layout.count() - 1, empty)
            return

        for move in moves:
            san = self.board.san(move)

            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)

            step_button = QPushButton(san)
            step_button.clicked.connect(lambda checked=False, m=move: self._step_into(m))
            row.addWidget(step_button, 1)

            remove_button = QPushButton("\u2715")
            remove_button.setFixedWidth(32)
            remove_button.clicked.connect(lambda checked=False, m=move: self._remove_move(m))
            row.addWidget(remove_button)

            self.moves_layout.insertWidget(self.moves_layout.count() - 1, row_widget)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Opening Book Editor")

    window = BookEditorWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
