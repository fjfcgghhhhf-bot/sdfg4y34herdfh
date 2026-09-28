"""Legal chess: immediate victory on the player's 25th move within 60 seconds."""
import math
import queue
import threading
import time

import chess
from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox
from challenge_base import ChallengeWindow


VALUES = {chess.PAWN:100, chess.KNIGHT:320, chess.BISHOP:335,
          chess.ROOK:500, chess.QUEEN:900, chess.KING:0}
GLYPHS = {'P':'♙','N':'♘','B':'♗','R':'♖','Q':'♕','K':'♔',
          'p':'♟','n':'♞','b':'♝','r':'♜','q':'♛','k':'♚'}


def evaluate(board):
    if board.is_checkmate():
        return -100000
    if board.is_stalemate() or board.is_insufficient_material():
        return 0
    score = 0
    for square, piece in board.piece_map().items():
        centrality = 7-abs(chess.square_file(square)-3.5)-abs(chess.square_rank(square)-3.5)
        value = VALUES[piece.piece_type] + (centrality*5 if piece.piece_type != chess.KING else 0)
        score += value if piece.color == board.turn else -value
    return score


def choose_move(board, cancelled, budget=.35):
    """Two-ply negamax, ordered captures; never touch the live GUI board."""
    deadline = time.monotonic()+budget
    moves = list(board.legal_moves)
    if not moves:
        return None
    best = moves[0]
    best_value = -float('inf')
    moves.sort(key=lambda m: (board.is_capture(m), bool(m.promotion)), reverse=True)
    def search(depth, alpha, beta):
        if cancelled.is_set():
            raise InterruptedError()
        if not depth or board.is_game_over() or time.monotonic() >= deadline:
            return evaluate(board)
        value = -float('inf')
        for move in list(board.legal_moves):
            board.push(move)
            try: score = -search(depth-1, -beta, -alpha)
            finally: board.pop()
            value = max(value, score)
            alpha = max(alpha, value)
            if alpha >= beta or time.monotonic() >= deadline:
                break
        return value
    for move in moves:
        if cancelled.is_set():
            return None
        board.push(move)
        try:
            value = -search(1, -float('inf'), -best_value)
        except InterruptedError:
            return None
        finally:
            board.pop()
        if value > best_value:
            best, best_value = move, value
        if time.monotonic() >= deadline:
            break
    return best


class BoardView(QWidget):
    clicked = pyqtSignal(int)

    def __init__(self, board):
        super().__init__()
        self.board, self.selected = board, None
        self.setMinimumSize(128,128)

    def geometry_board(self):
        size = min(self.width(),self.height())-28
        return (self.width()-size)/2, (self.height()-size)/2, size/8

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x,y,s = self.geometry_board()
        col = int((event.position().x()-x)//s)
        row = int((event.position().y()-y)//s)
        if 0<=col<8 and 0<=row<8:
            self.clicked.emit(chess.square(col,7-row))

    def paintEvent(self, event):
        p=QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        x,y,s=self.geometry_board()
        destinations = {m.to_square for m in self.board.legal_moves
                        if m.from_square==self.selected}
        for row in range(8):
            for col in range(8):
                square=chess.square(col,7-row)
                rect=QRectF(x+col*s,y+row*s,s,s)
                p.fillRect(rect,QColor('#8497b5' if (row+col)%2 else '#e7edf5'))
                if square==self.selected:
                    p.fillRect(rect,QColor('#c7a75b'))
                if square in destinations:
                    p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor('#558c6e'))
                    p.drawEllipse(rect.center(),s*.10,s*.10)
                piece=self.board.piece_at(square)
                if piece:
                    p.setPen(QPen(QColor('#101522')))
                    p.setFont(QFont('Segoe UI Symbol',max(8,int(s*.58))))
                    p.drawText(rect,Qt.AlignmentFlag.AlignCenter,GLYPHS[piece.symbol()])
        p.setPen(QColor('#e7edf5')); p.setFont(QFont('Segoe UI',9))
        for i in range(8):
            p.drawText(QRectF(x+i*s,y+8*s,s,16),Qt.AlignmentFlag.AlignCenter,'abcdefgh'[i])
            p.drawText(QRectF(x-17,y+i*s,15,s),Qt.AlignmentFlag.AlignCenter,str(8-i))


class ChessChallenge(ChallengeWindow):
    screen_height_fraction = .5

    def __init__(self):
        super().__init__('Шахматы — 25 ходов до победы')
        self.resize(650,760)
        self.board=chess.Board()
        self.moves=0
        self.bot_busy=False
        self.cancelled=threading.Event()
        self.results=queue.Queue()
        layout=QVBoxLayout(self)
        layout.setContentsMargins(8,8,8,8)
        layout.setSpacing(4)
        self.status=QLabel('Вы играете белыми. Ваш 25-й ход — мгновенная победа. Лимит: 60 секунд.')
        self.status.setWordWrap(True); layout.addWidget(self.status)
        self.counter=QLabel(); layout.addWidget(self.counter)
        self.view=BoardView(self.board); layout.addWidget(self.view,1)
        self.view.clicked.connect(self.select_square)
        row=QHBoxLayout(); row.addWidget(QLabel('Пешка →'))
        self.promotion=QComboBox()
        for text,kind in [('Ферзя',chess.QUEEN),('Ладью',chess.ROOK),('Слона',chess.BISHOP),('Коня',chess.KNIGHT)]:
            self.promotion.addItem(text,kind)
        row.addWidget(self.promotion)
        stop=QPushButton('Отменить · Esc'); stop.clicked.connect(self.stop); row.addWidget(stop)
        layout.addLayout(row)
        hint=QLabel('Фигура → клетка. F12 — аварийный выход.')
        hint.setWordWrap(True)
        hint.setToolTip('Считаются только ваши ходы. Победа/ничья начинают новую партию '
                        'с сохранением счётчика и таймера.')
        layout.addWidget(hint)

    def start(self):
        self.open_window(); self.start_clock(); self.tick()

    def select_square(self, square):
        if self.done or self.remaining()<=0:
            self.tick(); return
        if self.bot_busy or self.board.turn != chess.WHITE:
            return
        piece=self.board.piece_at(square)
        if piece and piece.color==chess.WHITE:
            self.view.selected=square; self.view.update(); return
        if self.view.selected is None:
            return
        move=chess.Move(self.view.selected,square)
        if self.board.piece_type_at(move.from_square)==chess.PAWN and chess.square_rank(square)==7:
            move.promotion=self.promotion.currentData()
        if move not in self.board.legal_moves:
            self.status.setText('Этот ход запрещён правилами. Выберите подсвеченную клетку.')
            return
        self.board.push(move); self.moves+=1; self.view.selected=None
        self.view.update()
        if self.moves>=25:
            self.finish('win','Шахматы: 25 ходов сделаны — автоматическая победа! Dota 2 остаётся открытой.')
            return
        if self.check_outcome():
            return
        self.bot_busy=True; self.status.setText('Компьютер обдумывает ход…')
        board=self.board.copy(); fen=self.board.fen()
        results,cancelled=self.results,self.cancelled
        def work():
            try: results.put((fen,choose_move(board,cancelled),None))
            except Exception: results.put((fen,None,'Не удалось рассчитать ход компьютера.'))
        threading.Thread(target=work,daemon=True,name='ChessBot').start()

    def check_outcome(self):
        outcome=self.board.outcome()
        if outcome is None:
            return False
        if outcome.winner==chess.BLACK:
            self.finish('loss','Шахматы: компьютер выиграл партию.')
        else:
            self.board.reset(); self.view.selected=None; self.view.update()
            self.status.setText('Партия закончена без поражения. Новая доска; ходы и время сохранены.')
        return True

    def tick(self):
        if self.done or self.deadline is None:
            return
        if self.remaining()<=0:
            # Count only moves committed before the wall-clock deadline.
            lost=self.board.outcome()
            fail=(lost is not None and lost.winner==chess.BLACK) or self.moves<25
            self.finish('loss' if fail else 'win',f'Шахматы: {self.moves} ходов за минуту. '+
                        ('Условие не выполнено.' if fail else 'Испытание пройдено.'))
            return
        try:
            while True:
                fen,move,error=self.results.get_nowait()
                if fen!=self.board.fen(): continue
                self.bot_busy=False
                if error or move is None or move not in self.board.legal_moves:
                    self.finish('error',error or 'Компьютер не смог сделать допустимый ход.'); return
                self.board.push(move); self.view.update()
                if self.check_outcome():
                    if self.done: return
                else:
                    self.status.setText('Шах! Защитите короля.' if self.board.is_check() else 'Ваш ход — белые.')
        except queue.Empty:
            pass
        self.counter.setText(f'Осталось: {math.ceil(self.remaining())} с     Ваши ходы: {self.moves} / 25')

    def cleanup(self):
        self.cancelled.set()
