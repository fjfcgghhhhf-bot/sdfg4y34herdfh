"""Windows-клиент. Запуск только с видимым согласием участника."""
import argparse
import ctypes
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys

BASE=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
sys.path.insert(0,str(BASE/'desktop'))
from PyQt6.QtCore import QLocale,QTranslator
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication,QDialog,QVBoxLayout,QLabel,QLineEdit,QCheckBox,QDialogButtonBox,QMessageBox
from client_store import Store,server_url
from protocol import username
from debuff_roulette_advanced import STYLE
from remote_window import RemoteWindow

def setup(config):
    dialog=QDialog(); dialog.setWindowTitle('Подключение к рулетке'); dialog.setObjectName('root'); dialog.resize(470,400)
    layout=QVBoxLayout(dialog)
    layout.addWidget(QLabel('Подключение к панели испытаний'))
    layout.addWidget(QLabel('Адрес сайта')); url=QLineEdit(config.get('server',os.environ.get('ROULETTE_SERVER_URL',''))); url.setPlaceholderText('https://имя.onrender.com'); layout.addWidget(url)
    layout.addWidget(QLabel('Ваш ник')); nick=QLineEdit(config.get('username','')); layout.addWidget(nick)
    layout.addWidget(QLabel('Одноразовый код от администратора')); code=QLineEdit(); code.setEchoMode(QLineEdit.EchoMode.Password); layout.addWidget(code)
    consent=QCheckBox('Разрешаю управление событиями на этом ПК.'); layout.addWidget(consent)
    text=QLabel('Панель может закрывать Dota 2, временно блокировать ввод, выключать монитор и запускать мини-игры. F12 снимает эффекты и закрывает клиент.'); text.setWordWrap(True); layout.addWidget(text)
    error=QLabel(); error.setWordWrap(True); layout.addWidget(error)
    buttons=QDialogButtonBox(); accept=buttons.addButton('Подключиться',QDialogButtonBox.ButtonRole.AcceptRole); buttons.addButton('Отмена',QDialogButtonBox.ButtonRole.RejectRole); layout.addWidget(buttons)
    def save():
        try:
            if not consent.isChecked(): raise ValueError('Подтвердите разрешение удалённого управления.')
            result={'server':server_url(url.text()),'username':username(nick.text()),'code':code.text().strip()}
            if not result['code']: raise ValueError('Введите одноразовый код с панели.')
            config.clear(); config.update(result); dialog.accept()
        except ValueError as exc: error.setText(str(exc))
    accept.clicked.connect(save); buttons.rejected.connect(dialog.reject)
    return dialog.exec()==QDialog.DialogCode.Accepted

def consent(config):
    box=QMessageBox(); box.setWindowTitle('Разрешить управление?')
    box.setText(f"Игрок: {config['username']}\nСайт: {config['server']}\n\nРазрешить события рулетки в этом сеансе? Это включает временную блокировку ввода, выключение монитора и закрытие Dota 2.\n\nF12 — снять эффекты и выйти.")
    yes=box.addButton('Разрешить на этот запуск',QMessageBox.ButtonRole.AcceptRole)
    box.addButton('Отмена',QMessageBox.ButtonRole.RejectRole); box.exec()
    return box.clickedButton() is yes

def main():
    parser=argparse.ArgumentParser(description='Клиент удалённой рулетки Dota 2')
    parser.add_argument('--configure',action='store_true',help='Повторное подключение с новым кодом')
    parser.add_argument('--demo',action='store_true',help='Принудительное демо: эффекты не выполняются')
    args=parser.parse_args()
    if sys.platform!='win32': raise SystemExit('Клиент работает только в Windows.')
    if not ctypes.windll.shell32.IsUserAnAdmin():
        arguments=sys.argv[1:] if getattr(sys,'frozen',False) else [str(Path(__file__).resolve()),*sys.argv[1:]]
        shell=ctypes.windll.shell32
        shell.ShellExecuteW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_int]
        shell.ShellExecuteW.restype=ctypes.c_void_p
        result=shell.ShellExecuteW(None,'runas',sys.executable,subprocess.list2cmdline(arguments),None,1)
        return 0 if result and result>32 else 1
    app=QApplication(sys.argv[:1]); QLocale.setDefault(QLocale('ru_RU')); app.setFont(QFont('Segoe UI',10)); app.setStyleSheet(STYLE)
    translations=[]
    for name in ('qtbase_ru','qtmultimedia_ru'):
        tr=QTranslator(app)
        assets=BASE/'assets' if getattr(sys,'frozen',False) else BASE/'desktop'/'assets'
        if tr.load(str(assets/(name+'.qm'))): app.installTranslator(tr); translations.append(tr)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True); kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_wchar_p]; kernel.CreateMutexW.restype=ctypes.c_void_p; kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    mutex=kernel.CreateMutexW(None,False,'Local\\DebuffRouletteAdvancedV2')
    if not mutex or ctypes.get_last_error()==183:
        QMessageBox.information(None,'Рулетка','Закройте предыдущий экземпляр рулетки через F12.'); return 1
    window=None
    try:
        store=Store()
        try: config=store.load()
        except Exception: config={}
        if args.configure or not config.get('token'):
            if not setup(config): return 0
        elif not consent(config): return 0
        window=RemoteWindow(config,store,demo=args.demo,reconfigure=setup)
        def error_hook(*_):
            window.stop_timer()
            if window.link: window.link.disconnect('Ошибка клиента. Эффекты сняты.')
        sys.excepthook=error_hook; window.show(); return app.exec()
    except Exception:
        QMessageBox.critical(None,'Рулетка','Не удалось запустить клиент. Проверьте подключение и права.'); return 1
    finally:
        if window and not window.closed: window.stop_effect(); window.controller.close()
        kernel.CloseHandle(mutex)

if __name__=='__main__':
    multiprocessing.freeze_support()
    raise SystemExit(main())
