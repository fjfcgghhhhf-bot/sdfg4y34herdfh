'use strict';
const $=id=>document.getElementById(id), selected=new Set();
let snapshot=null, initialized=false, pending=false, refreshing=false;
const csrf=document.querySelector('meta[name="csrf-token"]').content;
const names={start:'Запустить таймер',stop:'Снять эффекты',spin:'Крутить рулетку',settings:'Настройки',capture_shop:'Запомнить ТП',choose_video:'Выбрать видео',choose_music:'Добавить музыку',music_volume:'Громкость музыки',preview_video:'Предпросмотр видео',open_url:'Открыть сайт'};
const states={queued:'Ожидает',delivered:'Доставлена',accepted:'Принята',rejected:'Отклонена',expired:'Истекла',superseded:'Заменена'};
const icons={swap:'⇄',invert:'↔',tp:'⌂',window:'▣',video:'▶',keyboard:'⌨',mouse:'◉',both:'⊘',kill:'×',buy:'＋',reverse:'↻',cmd:'>_',monitor:'▰',pong:'Ⅱ',desktop:'▤',cubes:'◆',chess:'♞',ai:'✦',upgrader:'↗',music:'♫',bw:'◐'};
function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
function toast(text){$('toast').textContent=text;$('toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('toast').hidden=true,5500);}
async function api(url,data){const r=await fetch(url,{method:data===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:data===undefined?undefined:JSON.stringify(data)});const result=await r.json();if(r.status===401){location.href='/login';throw Error('Сеанс завершён.');}if(!r.ok)throw Error(result.error||'Ошибка запроса.');return result;}
function targets(){return $('allUsers').checked?'all':[...selected];}
function chosen(){return snapshot?snapshot.clients.filter(c=>c.online&&($('allUsers').checked||selected.has(c.id))):[];}
function selection(){const players=chosen(),count=players.length;$('selectedCount').textContent=`${count} выбрано`;const available=players.filter(c=>!c.immunity&&(!c.match||c.match.status==='ended'));
 document.querySelectorAll('[data-action],.event-trigger,#saveSettings,#applyMusicVolume,#openWebsite').forEach(b=>b.disabled=!count||pending);
 $('websiteRecipients').textContent=count?`Откроется у выбранных игроков: ${count}.`:'Выберите получателей в списке игроков.';
 document.querySelectorAll('[data-pvp]').forEach(b=>{b.disabled=pending||available.length<2||available.length%2!==0||available.length!==count;});
 $('targetLabel').textContent=count?($('allUsers').checked?'Все игроки в сети':players.map(c=>c.name).join(', ')):'Выберите игроков слева';
 const options=new Map([['default','Серёга Пират — Where Is My Mind'],['video','Дорожка Subway Surfers'],['bearwolf','Пенис (BEARWOLF cover)']]);
 if(players.length===1)for(const track of players[0].status.tracks||[])options.set(track.id,track.title);
 const select=$('musicTrack'),old=select.value,signature=JSON.stringify([...options]);
 if(select.dataset.signature!==signature){select.replaceChildren();for(const [id,title] of options){const option=node('option',title);option.value=id;select.append(option);}select.dataset.signature=signature;if(options.has(old))select.value=old;}
}
async function send(command){if(pending)return;pending=true;selection();try{const r=await api('/api/admin/command',{targets:targets(),command});toast(r.matches?`Матчи созданы: ${r.matches.length}.`:`Команда отправлена: ${r.sent} игрокам.`);await refresh();}catch(e){toast(e.message);}finally{pending=false;selection();}}
function config(value){const defaults=snapshot.defaults,v={...defaults,...value};$('volume').value=v.volume;$('volumeValue').textContent=v.volume+'%';$('musicVolume').value=v.music_volume??65;$('musicVolumeValue').textContent=$('musicVolume').value+'%';setUpgraderChance(v.upgrader_chance??50);$('shopKey').value=v.shop_key;$('shopXY').value=v.shop_xy;$('demo').checked=v.demo;$('aiProvider').value=v.ai_provider;
 document.querySelectorAll('[data-enabled]').forEach(e=>e.checked=v.enabled.includes(e.dataset.enabled));
 document.querySelectorAll('[data-duration]').forEach(e=>e.value=v.durations?.[e.dataset.duration]??defaults.durations[e.dataset.duration]);
 if([...$('musicTrack').options].some(x=>x.value===v.music_track))$('musicTrack').value=v.music_track;
}
function setUpgraderChance(value){const chance=Math.max(0,Math.min(100,Number(value)||0));$('upgraderChance').value=chance;$('upgraderChanceNumber').value=chance;$('upgraderChance').style.setProperty('--chance',chance+'%');}
function eventControls(events){for(const e of events){const card=node('article',undefined,'event-card'+(e.id==='kill'?' critical':''));
 const head=node('div',undefined,'event-head');head.append(node('span',icons[e.id]||'◆','event-icon'),node('span',e.category,'tag'));card.append(head,node('h3',e.title));
 if(e.id==='upgrader'){
  card.classList.add('upgrader-card');const controls=node('div',undefined,'chance-control'),line=node('div',undefined,'chance-heading'),label=node('label','Шанс победы'),percent=node('div',undefined,'chance-percent'),number=node('input'),range=node('input');
  label.htmlFor='upgraderChance';number.id='upgraderChanceNumber';number.type='number';number.min='0';number.max='100';number.step='1';number.value='50';number.required=true;number.setAttribute('aria-label','Шанс победы в апгрейдере, процентов');
  range.id='upgraderChance';range.type='range';range.min='0';range.max='100';range.step='1';range.value='50';range.style.setProperty('--chance','50%');range.setAttribute('aria-label','Шанс победы в апгрейдере');range.oninput=()=>setUpgraderChance(range.value);number.oninput=()=>{if(number.validity.valid&&number.value!==''){range.value=number.value;range.style.setProperty('--chance',number.value+'%');}};number.onchange=()=>{if(number.reportValidity())setUpgraderChance(number.value);};
  percent.append(number,node('span','%'));line.append(label,percent);controls.append(line,range,node('small','Больше шанс — шире нижняя зона.'));card.append(controls);
 }
 const foot=node('div',undefined,'event-foot');
 if(e.limits){const label=node('label',undefined,'duration-control'),input=node('input');input.type='number';input.min=e.limits[0];input.max=e.limits[1];input.step='1';input.required=true;input.value=e.seconds;input.dataset.duration=e.id;input.setAttribute('aria-label',`${e.title}: длительность в секундах`);label.append(input,node('span','сек'));foot.append(label);}
 else foot.append(node('span',e.id==='chess'||e.id==='pong'?'1 на 1 · без таймера':'Мгновенно','event-meta'));
 const button=node('button','Запустить ↗','event-trigger');if(['chess','pong'].includes(e.id))button.dataset.pvp=e.id;
 button.onclick=()=>{const command={action:'event',event:e.id};if(e.limits){const input=card.querySelector('[data-duration]');if(!input.reportValidity())return;command.duration=Number(input.value);if(!Number.isInteger(command.duration))return toast('Введите целое число секунд.');}if(e.id==='music'){command.track=$('musicTrack').value;command.volume=Number($('musicVolume').value);}if(e.id==='upgrader'){if(!$('upgraderChanceNumber').reportValidity())return;command.chance=Number($('upgraderChanceNumber').value);}send(command);};
 foot.append(button);card.append(foot);$('events').append(card);
 const label=node('label'),box=node('input');box.type='checkbox';box.dataset.enabled=e.id;label.append(box,document.createTextNode(e.title));$('enabledEvents').append(label);
 }$('eventCount').textContent=`${events.length} событие`;}
function render(data){snapshot=data;const online=data.clients.filter(c=>c.online);$('onlineCount').textContent=online.length;
 for(const id of selected)if(!online.some(c=>c.id===id))selected.delete(id);
 const list=$('players');list.replaceChildren();for(const c of data.clients.filter(c=>!c.revoked)){
 const card=node('div',undefined,'player'+(selected.has(c.id)||$('allUsers').checked&&c.online?' selected':'')),top=node('label',undefined,'player-top'),check=node('input');check.type='checkbox';check.checked=$('allUsers').checked?c.online:selected.has(c.id);check.disabled=!c.online||$('allUsers').checked;
 check.addEventListener('change',()=>{check.checked?selected.add(c.id):selected.delete(c.id);card.classList.toggle('selected',check.checked);selection();});top.append(check,node('strong',c.name),node('span',c.online?'В сети':'Нет связи','badge'+(c.online?' live':'')));card.append(top);
 if(c.immunity){const seconds=c.immunity;card.append(node('div',`◇ Иммунитет · ${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`,'shield'));}
 if(c.match&&c.match.status!=='ended')card.append(node('div',(c.match.kind==='chess'?'♞ Шахматы':'Ⅱ Пинг-понг')+' · '+c.match.players.join(' / '),'match-label'));
 card.append(node('p',`${c.status.active||'Ожидание'}\n${c.status.timer||'—'} · ${c.status.running?'Таймер работает':'Пауза'}`),node('p',c.status.note||''));
 if(c.online&&(c.status.protocol||1)<data.protocol)card.append(node('p',`Нужен новый клиент версии ${data.protocol}.`,'version-warning'));
 const revoke=node('button','Отключить доступ','quiet revoke');revoke.onclick=async()=>{if(!confirm(`Отозвать доступ клиента «${c.name}»?`))return;try{await api('/api/admin/revoke',{client_id:c.id});await refresh();}catch(e){toast(e.message);}};card.append(revoke);list.append(card);
 }if(!list.children.length)list.append(node('p','Пока никто не подключён. Создайте код и передайте его игроку.','empty'));
 if(!initialized){eventControls(data.events);selection();config(data.defaults);initialized=true;}
 $('providerState').textContent=`Gemini: ${data.providers.gemini?'настроен':'ключ не задан'} · Groq: ${data.providers.groq?'настроен':'ключ не задан'}`;
 const log=$('log');log.replaceChildren();for(const row of data.commands){const payload=JSON.parse(row.payload),event=data.events.find(e=>e.id===payload.event),tr=node('tr');tr.append(node('td',new Date(row.created*1000).toLocaleTimeString('ru-RU')),node('td',row.name),node('td',(event?event.title:names[payload.action]||payload.action)+(payload.duration?' · '+payload.duration+' с':'')));const td=node('td',states[row.status]||row.status);td.title=row.detail||'';tr.append(td);log.append(tr);}selection();}
async function refresh(){if(refreshing)return;refreshing=true;try{render(await api('/api/admin/state'));$('connection').textContent='● Сервер доступен';$('connection').className='badge live';}catch(e){$('connection').textContent='Нет связи';$('connection').className='badge';}finally{refreshing=false;}}
$('allUsers').onchange=()=>snapshot&&render(snapshot);
document.querySelectorAll('[data-action]').forEach(b=>b.onclick=()=>send({action:b.dataset.action}));
$('invite').onclick=async()=>{try{const r=await api('/api/admin/invite',{});$('inviteCode').textContent=r.code;$('inviteBox').hidden=false;}catch(e){toast(e.message);}};
$('copyInvite').onclick=async()=>{try{await navigator.clipboard.writeText($('inviteCode').textContent);toast('Код скопирован.');}catch{toast('Скопируйте код вручную.');}};
$('volume').oninput=()=>$('volumeValue').textContent=$('volume').value+'%';
$('musicVolume').oninput=()=>$('musicVolumeValue').textContent=$('musicVolume').value+'%';
$('applyMusicVolume').onclick=()=>send({action:'music_volume',volume:Number($('musicVolume').value)});
$('websiteForm').onsubmit=event=>{
 event.preventDefault();const input=$('websiteUrl');input.value=input.value.trim();
 if(!input.reportValidity())return;
 try{const url=new URL(input.value);if(!['http:','https:'].includes(url.protocol)||url.username||url.password)throw Error();}
 catch{return toast('Введите ссылку http:// или https:// без логина и пароля.');}
 if(!chosen().length)return toast('Выберите игроков слева.');
 send({action:'open_url',url:input.value});
};
$('saveSettings').onclick=()=>{const durations={};for(const input of document.querySelectorAll('[data-duration]')){if(!input.reportValidity())return;durations[input.dataset.duration]=Number(input.value);}if(!$('upgraderChanceNumber').reportValidity())return;send({action:'settings',settings:{enabled:[...document.querySelectorAll('[data-enabled]:checked')].map(x=>x.dataset.enabled),volume:Number($('volume').value),music_volume:Number($('musicVolume').value),upgrader_chance:Number($('upgraderChanceNumber').value),tp_key:'T',shop_key:$('shopKey').value.toUpperCase(),shop_xy:$('shopXY').value.trim(),demo:$('demo').checked,ai_provider:$('aiProvider').value,durations,music_track:$('musicTrack').value}});};
$('loadSettings').onclick=()=>{if($('allUsers').checked||selected.size!==1)return toast('Выберите одного игрока.');const c=snapshot.clients.find(x=>selected.has(x.id));config(c.status.settings||snapshot.defaults);toast('Настройки и длительности игрока загружены.');};
$('logout').onclick=async()=>{try{await api('/logout',{});location.href='/login';}catch(e){toast(e.message);}};
refresh();setInterval(refresh,2000);
