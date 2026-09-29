"""Тонкий клиент: прежние обработчики событий, управление с сайта."""
import threading
import time
import uuid
from pathlib import Path
from PyQt6.QtCore import Qt,QTimer
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QCheckBox,QLineEdit,QSlider,QComboBox,QPushButton,QFileDialog
from protocol import command,settings,DEFAULT_SETTINGS,PROTOCOL_VERSION,PVP_EVENTS
from debuff_roulette_advanced import MainWindow,RouletteWheel,EFFECTS,bundled_video
from chess_event import ChessChallenge
from remote_ai import RemoteAIChallenge
from remote_link import RemoteLink
from multiplayer import Multiplayer
from upgrader import Upgrader
from grayscale import Grayscale
from music_event import MusicEvent,catalog

class RemoteWindow(MainWindow):
    def __init__(self,config,store,demo=False,reconfigure=None):
        self.reconfigure_handler=reconfigure
        self.config=config; self.store=store; self.link=None; self.remote_settings=settings(config.get('settings',{}))
        # --demo is a local restriction and cannot be disabled from the web panel.
        self.local_demo=demo
        self.immune_until=0; self.overrides={}; self.match=None; self.finished_matches=set()
        self.music=None; self.gray=Grayscale(); self.roll_pending=False
        self.tracks=catalog(config.get('music_files',{}))
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
        self.link.state_received.connect(self.receive_state)
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
        self.volume.setValue(value['volume']); self.tp_key.setText('T'); self.shop_key.setText(value['shop_key']); self.shop_xy.setText(value['shop_xy'])
        self.demo_check.setChecked(self.local_demo or value['demo']); self.refresh_sectors()
        self.save_config()
    def snapshot(self):
        self.remote_settings['shop_xy']=self.shop_xy.text()
        return {'protocol':PROTOCOL_VERSION,'tracks':[{'id':key,'title':item['title']} for key,item in self.tracks.items()],
                'active':self.active_label.text(),'note':self.note_label.text(),'timer':self.timer_label.text(),
                'running':self.running,'video':self.video_path.name,'settings':self.remote_settings}
    def receive_command(self,item):
        try:
            if not self.link.active or self.closed: raise ValueError('Удалённое управление выключено.')
            data=command(item['command']); action=data['action']
            if action in ('event','start','spin','preview_video') and self.immune():
                raise ValueError('Действует иммунитет от всех событий.')
            if action=='settings': self.apply_settings(data['settings'])
            elif action=='start': self.start_timer()
            elif action=='stop': self.stop_timer()
            elif action=='spin': self.begin_spin()
            elif action=='event':
                self.spin=None; self.stop_effect()
                self.overrides=data
                index=next(i for i,e in enumerate(EFFECTS) if e.kind==data['event'])
                self.apply_selected(index,manual=True)
            elif action=='capture_shop':
                self.capture_shop(); QTimer.singleShot(3300,self.save_config)
            elif action=='choose_video': self.choose_video()
            elif action=='choose_music': self.choose_music()
            elif action=='music_volume':
                self.remote_settings['music_volume']=data['volume']
                if self.music: self.music.set_volume(data['volume']/100)
                self.save_config(); self.note_label.setText(f"Громкость музыки: {data['volume']}%")
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
        if kind=='chess': self.find_match(kind); return
        self.cancel=threading.Event(); owner=self.cancel
        try:
            challenge=RemoteAIChallenge(self.link,self.remote_settings['ai_provider'])
            challenge.duration=self.effect_duration(kind)
            self.challenge=challenge
            challenge.finished.connect(lambda result,reason:self.challenge_finished(challenge,owner,result,reason))
            challenge.start(); self.note_label.setText('Мини-игра открыта. Esc — отменить; F12 — выйти.')
        except Exception:
            self.stop_effect(); self.note_label.setText('Мини-игра недоступна. Эффект отменён.')

    def effect_duration(self,kind):
        if self.overrides.get('event')==kind and 'duration' in self.overrides: return self.overrides['duration']
        return self.remote_settings['durations'].get(kind,0)

    def immune(self): return self.immune_until>time.monotonic()

    def set_immunity(self,seconds):
        was_immune=self.immune()
        self.immune_until=max(self.immune_until,time.monotonic()+max(0,seconds))
        if seconds>0:
            self.running=False; self.spin=None
            if not was_immune and not self.roll_pending and not isinstance(self.challenge,Upgrader): self.stop_effect()

    def start_timer(self):
        if not self.immune(): super().start_timer()

    def begin_spin(self):
        # Let matches and the upgrader's result animation finish before the next spin.
        if self.immune() or self.match or self.roll_pending or isinstance(self.challenge,Upgrader): return
        super().begin_spin()

    def apply_selected(self,index,manual=False):
        if self.immune(): return
        effect=EFFECTS[index]
        if self.demo_check.isChecked() or effect.kind not in ('upgrader','music','bw'):
            super().apply_selected(index,manual); return
        if not manual and not self.checks[index].isChecked(): return
        self.effect_title=effect.title; self.active_label.setText(effect.title)
        self.cancel=threading.Event(); owner=self.cancel
        try:
            if effect.kind=='upgrader':
                self.roll_pending=True
                def receive(data,elapsed):
                    self.roll_pending=False
                    if owner.is_set() or self.closed: return
                    challenge=Upgrader(data,self.effect_duration('upgrader')); self.challenge=challenge
                    challenge.finished.connect(lambda result,reason:self.challenge_finished(challenge,owner,result,reason))
                    if data.get('immunity'): self.set_immunity(max(0,data['immunity']-elapsed))
                    challenge.start()
                def failed(reason):
                    if owner is self.cancel:
                        self.roll_pending=False; self.note_label.setText(reason)
                chance=self.overrides.get('chance',self.remote_settings['upgrader_chance'])
                self.link.post('/api/client/upgrader',{'session_id':self.link.session_id,'duration':self.effect_duration('upgrader'),'chance':chance},receive,failed)
            elif effect.kind=='bw':
                self.gray.start(self.effect_duration('bw')); self.note_label.setText('Чёрно-белый фильтр. F12 — восстановить цвета и выйти.')
            else:
                key=self.overrides.get('track',self.remote_settings['music_track'])
                if key not in self.tracks: raise ValueError('Трек не найден на этом компьютере. Выберите другой трек на сайте.')
                volume=self.overrides.get('volume',self.remote_settings['music_volume'])
                music=MusicEvent(self.tracks[key]['path'],self.effect_duration('music'),volume/100,self)
                self.music=music
                music.finished.connect(lambda reason:self.music_finished(music,reason)); music.start()
                self.note_label.setText('Играет: '+self.tracks[key]['title'])
        except Exception as error:
            self.stop_effect(); self.note_label.setText(str(error))

    def music_finished(self,music,reason):
        if self.music is music:
            self.music=None; self.active_label.setText(reason); music.deleteLater()

    def choose_music(self):
        if getattr(self,'file_dialog',None): return
        dialog=QFileDialog(self,'Добавить музыку на этом компьютере'); self.file_dialog=dialog
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog,True)
        dialog.setNameFilter('Музыка (*.mp3 *.wav *.ogg *.flac *.m4a)')
        dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        def chosen(paths):
            files=self.config.setdefault('music_files',{})
            for path in paths[:max(0,28-len(files))]:
                if path not in files.values(): files['local_'+uuid.uuid4().hex[:12]]=path
            self.tracks=catalog(files); self.save_config(); self.note_label.setText('Музыка добавлена. Список треков доступен на сайте.')
        dialog.filesSelected.connect(chosen)
        def finished(_): self.file_dialog=None; dialog.deleteLater()
        dialog.finished.connect(finished); dialog.open()

    def show_pong(self): self.find_match('pong')

    def find_match(self,kind):
        owner=self.cancel
        def receive(data,elapsed):
            state=data.get('match')
            if owner.is_set() or self.closed:
                if state: self.link.post('/api/client/match',{'session_id':self.link.session_id,'id':state['id'],'action':'cancel'},lambda *_:None,lambda _:None)
                return
            self.receive_match(state)
        # A fresh owner also prevents a delayed match-find from reopening a stopped game.
        self.cancel=threading.Event(); owner=self.cancel
        self.link.post('/api/client/match/find',{'session_id':self.link.session_id,'kind':kind},receive,
                       lambda reason:self.note_label.setText(reason) if not owner.is_set() else None)

    def receive_state(self,data):
        self.set_immunity(data.get('immunity',0))
        self.receive_match(data.get('match'))

    def receive_match(self,state):
        if not state or self.closed: return
        mid=state['id']
        if self.match and self.match.match_id==mid:
            self.match.receive(state); return
        if mid in self.finished_matches: return
        if state['status']=='ended':
            self.finished_matches.add(mid)
            self.link.post('/api/client/match',{'session_id':self.link.session_id,'id':mid,'action':'ack'},lambda *_:None,lambda _:None); return
        if self.immune() or self.demo_check.isChecked():
            self.finished_matches.add(mid)
            self.link.post('/api/client/match',{'session_id':self.link.session_id,'id':mid,'action':'cancel'},lambda *_:None,lambda _:None)
            self.note_label.setText('Демо: сетевой матч отменён.' if self.demo_check.isChecked() else 'Матч пропущен: иммунитет.'); return
        self.spin=None; self.stop_effect(); self.cancel=threading.Event(); owner=self.cancel
        match=Multiplayer(self.link,state); self.match=match
        self.effect_title='Шахматы · 1 на 1' if state['kind']=='chess' else 'Пинг-понг · 1 на 1'
        self.active_label.setText(self.effect_title); self.note_label.setText('Без таймера. Esc — отмена без поражения; F12 — выход.')
        match.finished.connect(lambda result,reason:self.match_finished(match,owner,result,reason)); match.start()

    def match_finished(self,match,owner,result,reason):
        if self.match is not match: return
        self.finished_matches.add(match.match_id); self.match=None; match.deleteLater()
        self.note_label.setText(reason); self.active_label.setText('Поражение' if result=='loss' else 'Победа' if result=='win' else 'Матч завершён без поражения')
        self.penalty(owner,result,reason)

    def penalty(self,owner,result,reason):
        if result!='loss' or self.immune() or owner.is_set() or self.closed or self.controller.panic.is_set() or self.demo_check.isChecked(): return
        def close_game():
            try:
                if self.immune() or owner.is_set() or not self.link.active: return
                message=self.controller.activate('kill',cancel=owner)
            except Exception: message='Не удалось закрыть Dota 2.'
            self.messages.put((owner,reason+' '+message))
        threading.Thread(target=close_game,daemon=True,name='RemoteMatchLoss').start()

    def challenge_finished(self,challenge,owner,result,reason):
        if self.challenge is not challenge: return
        self.challenge=None; challenge.deleteLater(); self.had_effect=False
        self.note_label.setText(reason); self.active_label.setText(reason)
        self.penalty(owner,result,reason)

    def stop_effect(self):
        self.roll_pending=False; self.overrides={}
        match,self.match=self.match,None
        if match:
            self.finished_matches.add(match.match_id); match.stop(); match.deleteLater()
        music,self.music=self.music,None
        if music: music.stop(); music.deleteLater()
        self.gray.stop()
        super().stop_effect()

    def tick(self):
        super().tick()
        if self.closed: return
        for kind,message in self.gray.poll():
            if kind=='error': self.note_label.setText(message)
            elif kind=='finished': self.active_label.setText('Исходные цвета экрана восстановлены')
        remaining=max(self.gray.remaining(),self.music.remaining() if self.music else 0)
        if remaining>0: self.active_label.setText(f'{self.effect_title}\nОсталось {remaining:.1f} с')
        if self.immune():
            left=max(0,int(self.immune_until-time.monotonic()))
            self.timer_label.setText(f'{left//60:02d}:{left%60:02d}')
            self.active_label.setText('Иммунитет от всех событий')
    def closeEvent(self,event):
        # Send cancellation while the authenticated link still exists.
        if self.match: self.stop_effect()
        if self.link:
            self.link.disconnected.disconnect(self.on_disconnected); self.link.disconnect()
        if getattr(self,'file_dialog',None): self.file_dialog.reject()
        self.save_config()
        super().closeEvent(event)
