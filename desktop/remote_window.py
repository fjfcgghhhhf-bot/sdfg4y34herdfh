"""Тонкий клиент: прежние обработчики событий, управление с сайта."""
import threading
from pathlib import Path
from PyQt6.QtCore import Qt,QTimer
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QCheckBox,QLineEdit,QSlider,QComboBox,QPushButton,QFileDialog
from protocol import command,settings,DEFAULT_SETTINGS
from debuff_roulette_advanced import MainWindow,RouletteWheel,EFFECTS,bundled_video
from chess_event import ChessChallenge
from remote_ai import RemoteAIChallenge
from remote_link import RemoteLink

class RemoteWindow(MainWindow):
    def __init__(self,config,store,demo=False,reconfigure=None):
        self.reconfigure_handler=reconfigure
        self.config=config; self.store=store; self.link=None; self.remote_settings=settings(config.get('settings',{}))
        # --demo is a local restriction and cannot be disabled from the web panel.
        self.local_demo=demo
        video=Path(config['video']) if config.get('video') else None
        if video and not video.is_file(): video=None
        super().__init__(demo=demo,video=video)
        self.setMinimumSize(470,620); self.resize(600,800)
        self.setWindowTitle('Рулетка · '+config['username'])
        self.apply_settings(self.remote_settings)
        self.link=RemoteLink(config,self.snapshot,self)
        self.link.command_received.connect(self.receive_command)
        self.link.connected.connect(self.on_connected)
        self.link.disconnected.connect(self.on_disconnected)
        self.link.enrolled.connect(lambda _:self.save_config())
        QTimer.singleShot(100,self.link.connect_server)
    def build_ui(self,demo):
        root=QWidget(); root.setObjectName('root'); self.setCentralWidget(root)
        layout=QVBoxLayout(root); layout.setContentsMargins(20,18,20,18)
        title=self.label('РУЛЕТКА ДЕБАФФОВ','eyebrow'); layout.addWidget(title)
        self.connection_label=self.label('Подключение к панели…','muted',True); layout.addWidget(self.connection_label)
        self.wheel=RouletteWheel(); layout.addWidget(self.wheel,1)
        self.timer_label=self.label('02:00','timer'); self.timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter); layout.addWidget(self.timer_label)
        self.active_label=self.label('Ожидание команды с сайта','active',True); layout.addWidget(self.active_label)
        self.note_label=self.label('F12 — снять эффекты и выйти.','muted',True); layout.addWidget(self.note_label)
        row=QHBoxLayout(); self.connect_button=self.button('Подключиться',self.reconnect); row.addWidget(self.connect_button)
        row.addWidget(self.button('Аварийный выход · F12',self.close,'panic')); layout.addLayout(row)
        self.setup_button=self.button('Адрес / новый код',self.change_connection)
        layout.addWidget(self.setup_button); self.setup_button.hide()
        self.connect_button.setEnabled(False)
        # Hidden settings controls are used by the stable local effect engine.
        self.options=QWidget(root); self.options.hide()
        self.checks=[]
        for effect in EFFECTS:
            box=QCheckBox(self.options); box.setChecked(effect.kind not in ('kill','buy')); self.checks.append(box)
        self.volume=QSlider(self.options); self.volume.setRange(0,100); self.volume.setValue(65)
        self.tp_key=QLineEdit('T',self.options); self.shop_key=QLineEdit('F4',self.options); self.shop_xy=QLineEdit(self.options)
        self.api_key=QLineEdit(self.options); self.ai_model=QComboBox(self.options)
        self.demo_check=QCheckBox(self.options); self.demo_check.setChecked(demo)
        self.start_button=QPushButton(self.options); self.video_label=QLineEdit(self.options); self.focus_label=QLabel(self.options)
        self.refresh_sectors()
    def reconnect(self):
        self.connect_button.setEnabled(False); self.connection_label.setText('Подключение…')
        self.link.connect_server()
    def change_connection(self):
        self.link.disconnect()
        if self.reconfigure_handler and self.reconfigure_handler(self.config):
            self.setWindowTitle('Рулетка · '+self.config['username'])
            self.reconnect()
    def on_connected(self):
        self.connection_label.setText(self.config['username']+' · Управление с сайта · В сети')
        self.active_label.setText('Подключён · таймер на паузе'); self.connect_button.setEnabled(False)
        self.setup_button.hide()
    def on_disconnected(self,reason):
        if self.closed: return
        self.stop_timer(); self.connection_label.setText('Нет связи · управление отключено')
        self.note_label.setText(reason); self.connect_button.setEnabled(True)
        self.setup_button.setVisible(self.reconfigure_handler is not None)
    def save_config(self):
        self.config['settings']=self.remote_settings
        self.config['video']=str(self.video_path) if self.video_path!=bundled_video() else ''
        try: self.store.save(self.config)
        except Exception: self.note_label.setText('Не удалось сохранить настройки клиента.')
    def apply_settings(self,value):
        value=settings(value); self.stop_timer(); self.remote_settings=value
        for effect,box in zip(EFFECTS,self.checks): box.setChecked(effect.kind in value['enabled'])
        self.volume.setValue(value['volume']); self.tp_key.setText(value['tp_key']); self.shop_key.setText(value['shop_key']); self.shop_xy.setText(value['shop_xy'])
        self.demo_check.setChecked(self.local_demo or value['demo']); self.refresh_sectors()
        self.save_config()
    def snapshot(self):
        self.remote_settings['shop_xy']=self.shop_xy.text()
        return {'active':self.active_label.text(),'note':self.note_label.text(),'timer':self.timer_label.text(),
                'running':self.running,'video':self.video_path.name,'settings':self.remote_settings}
    def receive_command(self,item):
        try:
            if not self.link.active or self.closed: raise ValueError('Удалённое управление выключено.')
            data=command(item['command']); action=data['action']
            if action=='settings': self.apply_settings(data['settings'])
            elif action=='start': self.start_timer()
            elif action=='stop': self.stop_timer()
            elif action=='spin': self.begin_spin()
            elif action=='event':
                self.spin=None; self.stop_effect()
                index=next(i for i,e in enumerate(EFFECTS) if e.kind==data['event'])
                self.apply_selected(index,manual=True)
            elif action=='capture_shop':
                self.capture_shop(); QTimer.singleShot(3300,self.save_config)
            elif action=='choose_video': self.choose_video()
            elif action=='preview_video':
                if self.demo_check.isChecked(): self.note_label.setText('Демо: предпросмотр не запускается.')
                else: self.preview_video()
            self.link.ack(item['id'],True,'Команда принята. Результат — в статусе игрока.')
        except Exception as error:
            self.stop_timer(); self.link.ack(item.get('id',''),False,str(error))
    def choose_video(self):
        # Non-modal: F12 and the connection watchdog remain effective.
        if getattr(self,'file_dialog',None): return
        dialog=QFileDialog(self,'Выберите видео для рулетки'); self.file_dialog=dialog
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog,True)
        dialog.setNameFilter('Видео (*.mp4 *.mkv *.mov *.webm)'); dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        def chosen(path):
            self.video_path=Path(path); self.save_config(); self.note_label.setText('Выбрано видео: '+self.video_path.name)
        dialog.fileSelected.connect(chosen)
        def finished(_): self.file_dialog=None; dialog.deleteLater()
        dialog.finished.connect(finished); dialog.open()
    def show_challenge(self,kind):
        self.cancel=threading.Event(); owner=self.cancel
        try:
            challenge=ChessChallenge() if kind=='chess' else RemoteAIChallenge(self.link,self.remote_settings['ai_provider'])
            self.challenge=challenge
            challenge.finished.connect(lambda result,reason:self.challenge_finished(challenge,owner,result,reason))
            challenge.start(); self.note_label.setText('Мини-игра открыта. Esc — отменить; F12 — выйти.')
        except Exception:
            self.stop_effect(); self.note_label.setText('Мини-игра недоступна. Эффект отменён.')
    def closeEvent(self,event):
        if self.link:
            self.link.disconnected.disconnect(self.on_disconnected); self.link.disconnect()
        if getattr(self,'file_dialog',None): self.file_dialog.reject()
        self.save_config()
        super().closeEvent(event)
