async function save(path,data={}){
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  if(!response.ok){const err=await response.json();throw Error(err.detail||'Не удалось сохранить')}
}
for(const form of document.querySelectorAll('.rule')){
  const fields=form.elements, kind=form.dataset.kind;
  function sync(){
    const off=fields.work?!fields.work.checked:!!fields.off?.checked;
    if(fields.opens){
      form.querySelector('.hours').hidden=off;
      fields.opens.disabled=fields.closes.disabled=off;
    }
    if(fields.work || fields.off)form.querySelector('.switch span').textContent=fields.work?(off?'Выходной':'Рабочий'):(off?'Весь день выходной':'Особые часы работы');
  }
  sync();
  form.oninput=()=>{sync();const button=form.querySelector('.commit');if(button)button.hidden=false};
  form.onsubmit=async e=>{
    e.preventDefault();
    const data={kind,day:fields.day.value,off:fields.work?!fields.work.checked:!!fields.off?.checked};
    if(fields.opens){data.opens=fields.opens.value;data.closes=fields.closes.value}
    if(fields.step){data.step=Number(fields.step.value);data.horizon=Number(fields.horizon.value)}
    const output=form.querySelector('output');
    try{await save('/admin/rules',data);
      if(kind==='week'||kind==='settings'){form.querySelector('.commit').hidden=true;output.textContent='Сохранено'}
      else location.assign('/admin?tab=schedule&day='+data.day);
    }catch(err){output.textContent=err.message}
  };
}
document.addEventListener('click',async e=>{
  const action=e.target.dataset.action;
  if(!action)return;
  const box=e.target.closest('[data-id]'),id=box.dataset.id;
  const message=box.querySelector('[role=status]');
  try{
    if(action==='options'){
      const response=await fetch('/admin/options/'+id);
      if(!response.ok)throw Error('Обновите страницу');
      const times=await response.json();
      const select=box.querySelector('select');select.replaceChildren(...times.map(t=>new Option(t.slice(0,10).split('-').reverse().join('.')+' · '+t.slice(11,16),t)));
      box.querySelector('.move').hidden=!times.length;
      if(!times.length)message.textContent='Свободных окон нет';
      return;
    }
    if(action==='cancel' && !confirm('Отменить визит и освободить время?'))return;
    const start=box.querySelector('select')?.value;
    if(action==='move' && !confirm('Перенести визит на выбранное время?'))return;
    await save('/admin/'+action+'/'+id,action==='move'?{starts:start}:{});
    location.assign(action==='unblock'?location.href:'/admin?visit='+id);
  }catch(error){message.textContent=error.message}
});
