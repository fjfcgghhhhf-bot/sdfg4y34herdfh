"""Панель добровольных испытаний. SQLite, REST, только фиксированные команды."""
import functools
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from collections import OrderedDict
from datetime import timedelta

from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash
from protocol import EVENTS, DEFAULT_SETTINGS, command, username, settings

ONLINE_SECONDS=8

def digest(value): return hashlib.sha256(value.encode()).hexdigest()

def create_app(config=None):
    app=Flask(__name__)
    app.config.update(SECRET_KEY=os.environ.get('SECRET_KEY',''),
        ADMIN_PASSWORD=os.environ.get('ADMIN_PASSWORD',''),
        DATABASE=os.environ.get('DATABASE_PATH','data/roulette.sqlite3'),
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict',
        SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE','1')=='1',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8), MAX_CONTENT_LENGTH=131072,
        AI_PROVIDER=os.environ.get('AI_PROVIDER','gemini'))
    if config: app.config.update(config)
    if len(app.config['SECRET_KEY'])<32 or len(app.config['ADMIN_PASSWORD'])<16:
        raise RuntimeError('Задайте SECRET_KEY (32+ символа) и ADMIN_PASSWORD (16+ символов).')
    if os.environ.get('RENDER'): app.wsgi_app=ProxyFix(app.wsgi_app,x_for=1,x_proto=1)
    admin_hash=generate_password_hash(app.config.pop('ADMIN_PASSWORD'))
    Path(app.config['DATABASE']).parent.mkdir(parents=True,exist_ok=True)
    def db():
        if 'db' not in g:
            g.db=sqlite3.connect(app.config['DATABASE'],timeout=10)
            g.db.row_factory=sqlite3.Row
            g.db.execute('PRAGMA foreign_keys=ON')
        return g.db
    @app.teardown_appcontext
    def close_db(error=None):
        if 'db' in g: g.pop('db').close()
    with app.app_context():
        db().executescript('''PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS clients (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT UNIQUE NOT NULL,
            token_hash TEXT UNIQUE NOT NULL, last_seen REAL DEFAULT 0,
            session_id TEXT DEFAULT '', status TEXT DEFAULT '{}', revoked INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS invites (hash TEXT PRIMARY KEY, expires REAL NOT NULL, used INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS commands (
            id TEXT PRIMARY KEY, client_id TEXT NOT NULL REFERENCES clients(id), session_id TEXT NOT NULL,
            payload TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued', detail TEXT DEFAULT '', updated REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS command_queue ON commands(client_id,status,created);
        CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, created REAL, text TEXT);
        ''')
        # A restart never replays old commands or pretends clients are still online.
        db().execute("UPDATE commands SET status='expired' WHERE status='queued'")
        db().execute("UPDATE clients SET last_seen=0,session_id=''")
        db().commit()
    limits=OrderedDict(); rate_lock=threading.Lock()
    def rate(key,count,seconds):
        now=time.monotonic()
        with rate_lock:
            hits=[x for x in limits.get(key,[]) if now-x<seconds]
            if len(hits)>=count: return False
            hits.append(now); limits[key]=hits; limits.move_to_end(key)
            while len(limits)>5000: limits.popitem(last=False)
        return True
    def fail(text,status=400): return jsonify(error=text),status
    def body():
        value=request.get_json(silent=True)
        if not isinstance(value,dict): raise ValueError('Ожидается объект JSON.')
        return value
    def audit(text):
        db().execute('INSERT INTO audit(created,text) VALUES (?,?)',(time.time(),text[:300]))
        db().execute('DELETE FROM audit WHERE id NOT IN (SELECT id FROM audit ORDER BY id DESC LIMIT 300)')
    def csrf_ok():
        expected=session.get('csrf')
        provided=request.headers.get('X-CSRF-Token','') or request.form.get('csrf','')
        return isinstance(expected,str) and bool(expected) and secrets.compare_digest(expected,provided)
    def admin(fn):
        @functools.wraps(fn)
        def wrapped(*a,**kw):
            if not session.get('admin'): return fail('Войдите в панель.',401)
            if request.method!='GET' and not csrf_ok(): return fail('Обновите страницу: проверка запроса не пройдена.',403)
            return fn(*a,**kw)
        return wrapped
    def client(fn):
        @functools.wraps(fn)
        def wrapped(*a,**kw):
            token=request.headers.get('Authorization','').removeprefix('Bearer ')
            row=db().execute('SELECT * FROM clients WHERE token_hash=? AND revoked=0',(digest(token),)).fetchone()
            if not row: return fail('Клиент отключён. Подключитесь заново с новым кодом.',401)
            g.client=row
            return fn(*a,**kw)
        return wrapped
    @app.before_request
    def guard():
        if request.method not in ('GET','HEAD','OPTIONS') and request.headers.get('Origin'):
            origin=request.headers['Origin']
            # Privacy policies and sandboxed browsers can send Origin:null even
            # for our own form. Only session-bound, CSRF-protected panel routes
            # may use this fallback. Never allow an explicit foreign origin.
            panel_route=(request.endpoint in ('login','logout') or request.path.startswith('/api/admin/'))
            opaque_with_csrf=origin=='null' and panel_route and csrf_ok()
            if origin.rstrip('/')!=request.host_url.rstrip('/') and not opaque_with_csrf:
                if request.endpoint=='login':
                    session.setdefault('csrf',secrets.token_urlsafe(32))
                    return render_template('login.html',error='Обновите страницу входа и повторите попытку.'),403
                return fail('Другой источник запроса запрещён.',403)
    @app.after_request
    def headers(response):
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        # no-referrer can suppress Origin on form POSTs in some browsers.
        # Same-origin retains it for our forms without leaking it to other sites.
        response.headers['Referrer-Policy']='same-origin'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
        if request.is_secure: response.headers['Strict-Transport-Security']='max-age=31536000'
        return response
    @app.errorhandler(ValueError)
    def value_error(error): return fail(str(error))
    @app.errorhandler(HTTPException)
    def http_error(error): return fail('Запрос не принят сервером.',error.code)
    @app.errorhandler(Exception)
    def internal_error(error):
        app.logger.error('Внутренняя ошибка: %s',type(error).__name__)
        return fail('Ошибка сервера. Эффекты будут сняты при потере связи.',500)

    @app.get('/healthz')
    def health(): return jsonify(status='работает')
    @app.route('/login',methods=['GET','POST'])
    def login():
        session.setdefault('csrf',secrets.token_urlsafe(32))
        error=''
        if request.method=='POST':
            if not csrf_ok(): error='Обновите страницу и повторите вход.'
            elif not rate(('login',request.remote_addr),8,60): error='Слишком много попыток. Подождите минуту.'
            elif check_password_hash(admin_hash,request.form.get('password','')):
                session.clear(); session.update(admin=True,csrf=secrets.token_urlsafe(32)); session.permanent=True
                return redirect(url_for('index'))
            else: error='Неверный пароль.'
        return render_template('login.html',error=error)
    @app.post('/logout')
    @admin
    def logout(): session.clear(); return jsonify(ok=True)
    @app.get('/')
    def index():
        if not session.get('admin'): return redirect(url_for('login'))
        return render_template('index.html')
    @app.get('/api/admin/state')
    @admin
    def state():
        now=time.time(); rows=[]
        db().execute("UPDATE commands SET status='expired' WHERE status='queued' AND expires<?",(now,))
        db().commit()
        for r in db().execute('SELECT * FROM clients ORDER BY name_key'):
            rows.append({'id':r['id'],'name':r['name'],'online':not r['revoked'] and now-r['last_seen']<ONLINE_SECONDS,
                'last_seen':r['last_seen'],'revoked':bool(r['revoked']),'status':json.loads(r['status'])})
        logs=[dict(r) for r in db().execute('SELECT c.id,u.name,c.payload,c.status,c.detail,c.created FROM commands c JOIN clients u ON u.id=c.client_id ORDER BY c.created DESC LIMIT 60')]
        return jsonify(clients=rows,events=[dict(id=e[0],title=e[1],seconds=e[2],category=e[3]) for e in EVENTS],
                       commands=logs,defaults=DEFAULT_SETTINGS,providers={'gemini':bool(os.environ.get('GEMINI_API_KEY')),'groq':bool(os.environ.get('GROQ_API_KEY'))})
    @app.post('/api/admin/invite')
    @admin
    def invite():
        code=secrets.token_urlsafe(12)
        db().execute('DELETE FROM invites WHERE expires<? OR used=1',(time.time(),))
        db().execute('INSERT INTO invites(hash,expires) VALUES (?,?)',(digest(code),time.time()+600))
        audit('Создан одноразовый код подключения на 10 минут.'); db().commit()
        return jsonify(code=code,expires_in=600)
    @app.post('/api/enroll')
    def enroll():
        if not rate(('enroll',request.remote_addr),12,60): return fail('Подождите минуту.',429)
        data=body(); name=username(data.get('username')); code=str(data.get('code',''))
        connection=db(); connection.execute('BEGIN IMMEDIATE')
        inv=connection.execute('SELECT * FROM invites WHERE hash=? AND used=0 AND expires>?',(digest(code),time.time())).fetchone()
        if not inv: return fail('Код недействителен или истёк.',403)
        if connection.execute('SELECT id FROM clients WHERE name_key=? AND revoked=0',(name.casefold(),)).fetchone():
            return fail('Этот ник уже занят.',409)
        # Revoked identities retain their audit trail but release the nickname.
        connection.execute("UPDATE clients SET name_key=id WHERE name_key=? AND revoked=1",(name.casefold(),))
        cid=secrets.token_hex(16); token=secrets.token_urlsafe(32)
        connection.execute('INSERT INTO clients(id,name,name_key,token_hash) VALUES (?,?,?,?)',(cid,name,name.casefold(),digest(token)))
        connection.execute('UPDATE invites SET used=1 WHERE hash=?',(digest(code),))
        audit('Подключён игрок: '+name); connection.commit()
        return jsonify(client_id=cid,token=token,username=name)
    @app.post('/api/client/session')
    @client
    def connect():
        sid=secrets.token_hex(24)
        db().execute("UPDATE commands SET status='expired' WHERE client_id=? AND status='queued'",(g.client['id'],))
        db().execute('UPDATE clients SET session_id=?,last_seen=?,status=? WHERE id=?',
                     (sid,time.time(),json.dumps({'active':'Подключён · пауза'},ensure_ascii=False),g.client['id']))
        db().commit(); return jsonify(session_id=sid)
    def valid_session(data):
        return bool(g.client['session_id']) and secrets.compare_digest(g.client['session_id'],str(data.get('session_id','')))
    @app.post('/api/client/poll')
    @client
    def poll():
        data=body()
        if not valid_session(data): return fail('Сеанс устарел. Переподключение.',409)
        value=data.get('status',{})
        if not isinstance(value,dict): raise ValueError('Неверный статус.')
        clean={k:str(value.get(k,''))[:350] for k in ('active','note','timer','video')}
        clean['running']=value.get('running') is True
        clean['settings']=settings(value.get('settings',{}))
        now=time.time(); connection=db(); connection.execute('BEGIN IMMEDIATE')
        connection.execute('UPDATE clients SET last_seen=?,status=? WHERE id=?',(now,json.dumps(clean,ensure_ascii=False),g.client['id']))
        for ack in data.get('acks',[])[:30]:
            if not isinstance(ack,dict): continue
            state=ack.get('status')
            if state not in ('accepted','rejected'): continue
            connection.execute("UPDATE commands SET status=?,detail=?,updated=? WHERE id=? AND client_id=? AND session_id=? AND status='delivered'",
                (state,str(ack.get('detail',''))[:300],now,str(ack.get('id','')),g.client['id'],g.client['session_id']))
        connection.execute("UPDATE commands SET status='expired' WHERE status='queued' AND expires<?",(now,))
        row=connection.execute("SELECT * FROM commands WHERE client_id=? AND session_id=? AND status='queued' ORDER BY created LIMIT 1",(g.client['id'],g.client['session_id'])).fetchone()
        commands=[]
        if row:
            # At most once: never resend a delivered input action after a lost reply.
            connection.execute("UPDATE commands SET status='delivered',updated=? WHERE id=?",(now,row['id']))
            commands=[{'id':row['id'],'command':json.loads(row['payload']),'ttl':max(0,row['expires']-now)}]
        connection.execute('DELETE FROM commands WHERE created<?',(now-86400,))
        connection.commit()
        return jsonify(commands=commands,session_id=g.client['session_id'])
    @app.post('/api/admin/command')
    @admin
    def send():
        if not rate('admin_commands',90,60): return fail('Слишком много команд.',429)
        data=body(); payload=command(data.get('command')); targets=data.get('targets'); now=time.time()
        if targets!='all' and (not isinstance(targets,list) or not targets or len(targets)>100): raise ValueError('Выберите игроков.')
        connection=db(); connection.execute('BEGIN IMMEDIATE')
        rows=connection.execute('SELECT * FROM clients WHERE revoked=0 AND last_seen>? AND session_id<>?',(now-ONLINE_SECONDS,'')).fetchall()
        rows=[r for r in rows if targets=='all' or r['id'] in targets]
        if not rows: return fail('Нет выбранных игроков в сети.',409)
        sent=[]
        for r in rows:
            # The newest command replaces queued commands, avoiding effect backlogs.
            connection.execute("UPDATE commands SET status='superseded' WHERE client_id=? AND status='queued'",(r['id'],))
            cid=secrets.token_hex(16)
            connection.execute('INSERT INTO commands(id,client_id,session_id,payload,created,expires,updated) VALUES (?,?,?,?,?,?,?)',
                               (cid,r['id'],r['session_id'],json.dumps(payload,ensure_ascii=False),now,now+8,now))
            sent.append(cid)
        audit(f"Команда {payload['action']}: игроков {len(sent)}"); connection.commit()
        return jsonify(sent=len(sent),ids=sent)
    @app.post('/api/admin/revoke')
    @admin
    def revoke():
        cid=str(body().get('client_id',''))
        db().execute("UPDATE clients SET revoked=1,last_seen=0,session_id='' WHERE id=?",(cid,))
        db().execute("UPDATE commands SET status='expired' WHERE client_id=? AND status='queued'",(cid,))
        audit('Отозвано подключение игрока.'); db().commit(); return jsonify(ok=True)
    @app.post('/api/client/ai')
    @client
    def ai():
        data=body()
        if not valid_session(data) or time.time()-g.client['last_seen']>ONLINE_SECONDS: return fail('Нет активного подключения.',409)
        if not rate(('ai',g.client['id']),30,60): return fail('Лимит сообщений ИИ.',429)
        from ai_gateway import respond
        try: return jsonify(respond(data))
        except ValueError as error: return fail(str(error),400)
        except Exception: return fail('ИИ временно недоступен. Событие отменено без закрытия Dota.',502)
    return app
