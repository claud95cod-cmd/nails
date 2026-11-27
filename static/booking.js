const el = id => document.getElementById(id);
const form=el('form'), note=el('notice');
let days={}, selected='', month='', start='', price, minutes, title, attempt, generation=0, service;
const choices=[...document.querySelectorAll('[data-service]')];
const extras=[...document.querySelectorAll('[data-for-service]')];
const addons=()=>extras.filter(label=>!label.hidden && label.firstElementChild.checked)
  .map(label=>Number(label.firstElementChild.value));
const manual=el('booking').dataset.manual==='true';
const format=(day,options)=>new Date(day+'T12:00:00').toLocaleDateString('ru-RU',options);
function button(text,handler){
  const b=document.createElement('button'); b.type='button'; b.textContent=text; b.onclick=handler; return b;
}
function render(){
  const months=[...new Set(Object.keys(days).map(d=>d.slice(0,7)))];
  const index=months.indexOf(month);
  el('month').textContent=format(month+'-01',{month:'long',year:'numeric'});
  for(const [id,delta] of [['prev',-1],['next',1]]){
    el(id).disabled=!months[index+delta];
    el(id).onclick=()=>{month=months[index+delta];render()};
  }
  const grid=el('dates'); grid.replaceChildren();
  const first=new Date(month+'-01T12:00:00');
  const count=new Date(first.getFullYear(),first.getMonth()+1,0).getDate();
  for(let n=1;n<=count;n++){
    const d=month+'-'+String(n).padStart(2,'0');
    const b=button(n,()=>{selected=d;start='';render()});
    if(n===1)b.style.gridColumnStart=(first.getDay()+6)%7+1;
    b.disabled=!(d in days);
    b.setAttribute('aria-label',format(d,{day:'numeric',month:'long'}));
    b.setAttribute('aria-pressed',d===selected);
    b.classList.toggle('has-windows',!!days[d]?.some(o=>!o.status));
    grid.append(b);
  }
  const options=days[selected]||[];
  if(!options.some(o=>!o.status && o.start===start))start=options.find(o=>!o.status)?.start||'';
  el('when').textContent=format(selected,{day:'numeric',month:'long'})+' · начало визита';
  const slots=el('slots');slots.replaceChildren();
  for(const o of options){
    const b=button(o.start.slice(11,16),()=>{start=o.start;render()});
    b.disabled=!!o.status;b.setAttribute('aria-pressed',o.start===start);
    if(o.status){const label=document.createElement('small');label.textContent=o.status;b.append(label)}
    slots.append(b);
  }
  const nearest=Object.keys(days).find(d=>d>=selected && days[d].some(o=>!o.status)) ||
    Object.keys(days).find(d=>days[d].some(o=>!o.status));
  el('nearest').hidden=!!start || !nearest;
  el('nearest').onclick=()=>{selected=nearest;month=nearest.slice(0,7);render()};
  el('submit').disabled=!start;
  if(!start){el('summary').textContent=nearest?'На этот день свободных окон нет.':'Свободных окон нет.';return}
  const end=new Date(Date.parse(start.slice(0,16)+'Z')+minutes*60000).toISOString().slice(11,16);
  el('summary').textContent=[title,format(selected,{day:'numeric',month:'long'}),start.slice(11,16)+'–'+end,price+' ₽'].join(' · ');
}
async function refresh(){
  const id=++generation;
  el('booking').hidden=false;el('submit').disabled=true;
  try{
    const params=new URLSearchParams({service});
    addons().forEach(id=>params.append('addons',id));
    const r=await fetch((manual ? '/admin/slots?' : '/slots?')+params);
    const data=await r.json();
    if(id!==generation)return;
    if(!r.ok)throw Error(data.detail);
    days=data.days;price=data.price;minutes=data.minutes;title=data.title;
    if(!(selected in days))selected=(data.times[0]||Object.keys(days)[0]).slice(0,10);
    month=selected.slice(0,7);render();
  }catch(error){if(id===generation){days={};start='';el('dates').replaceChildren();el('slots').replaceChildren();el('month').textContent='';el('summary').textContent='';el('nearest').hidden=true;el('submit').disabled=true;note.textContent=error instanceof TypeError ? 'Нет связи. Повторите выбор услуги.' : 'Услуга или дополнение изменились. Обновите страницу.'}}
}
for(const choice of choices){
  choice.onclick=async()=>{
    const next=Number(choice.dataset.service);
    if(service!==next){
      service=next;
      selected=el('booking').dataset.day || '';start='';
      choices.forEach(item=>item.setAttribute('aria-pressed',item===choice));
      for(const label of extras){
        label.hidden=Number(label.dataset.forService)!==service;
        label.firstElementChild.checked=false;
      }
      el('extras').hidden=extras.every(label=>label.hidden);
    }
    note.textContent='';
    await refresh();
    el('booking').scrollIntoView();
  };
}
el('extras').onchange=()=>{note.textContent='';refresh()};
form.onsubmit=async e=>{
  e.preventDefault();
  if(!/^\+?\d{10,15}$/.test(el('phone').value.replace(/[ ()-]/g,''))){
    el('phone').setCustomValidity('Введите от 10 до 15 цифр');el('phone').reportValidity();return;
  }
  const fields={name:el('name').value.trim(),phone:el('phone').value,starts:start,price,minutes,service,addons:addons(),social:el('social').value.trim()};
  const fingerprint=JSON.stringify(fields);
  if(!attempt || attempt.fingerprint!==fingerprint) attempt={fingerprint,id:crypto.randomUUID()};
  const button=el('submit');
  const controls=[...choices,...extras.map(label=>label.firstElementChild)];
  controls.forEach(control=>control.disabled=true);
  button.disabled=true;
  try{
    const r=await fetch(manual?'/admin/book':'/book',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({...fields,request_id:attempt.id})});
    const data=await r.json();
    if(r.ok){location.assign(manual?'/admin?day='+selected:data.url);return}
    note.textContent=data.detail;
    if([404,409,422].includes(r.status)){if(r.status!==422)attempt=null;await refresh()}
  }catch{note.textContent='Ответ не получен. После подключения нажмите «Сохранить визит» ещё раз.'}
  finally{controls.forEach(control=>control.disabled=false);button.disabled=!start}
};
el('phone').oninput=()=>el('phone').setCustomValidity('');
