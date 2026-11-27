async function save(path,data={}){
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  if(!response.ok){const err=await response.json();throw Error(err.detail||'Не удалось сохранить')}
}
const dialog = document.querySelector('#move-dialog');
const dateField = dialog?.querySelector('#move-day');
const slots = dialog?.querySelector('#move-times');
const submit = dialog?.querySelector('#move-submit');
const statusLine = dialog?.querySelector('[role=status]');
let activeVisit;
let availableTimes = [];

for (const input of document.querySelectorAll('.date-trigger input')) {
  input.addEventListener('click', () => {
    try { input.showPicker?.(); } catch { input.focus(); }
  });
}
function displayMoveDate() {
  document.querySelector('#move-day-text').textContent = dateField.value.split('-').reverse().join('.') || 'Выбрать дату';
}
function showDayTimes() {
  displayMoveDate();
  slots.replaceChildren();
  submit.disabled = true;
  const times = availableTimes.filter(time => time.slice(0, 10) === dateField.value);
  statusLine.textContent = times.length ? '' : 'На эту дату свободного времени нет.';
  for (const time of times) {
    const label = document.createElement('label');
    label.className = 'chip';
    const choice = document.createElement('input');
    choice.type = 'radio';
    choice.name = 'move-time';
    choice.value = time;
    label.append(choice, time.slice(11, 16));
    slots.append(label);
  }
}

async function openMove(box) {
  const request = {};
  activeVisit = request;
  request.id = box.dataset.id;
  availableTimes = [];
  dateField.value = dateField.defaultValue;
  displayMoveDate();
  dateField.disabled = true;
  slots.replaceChildren();
  submit.disabled = true;
  statusLine.textContent = 'Загружаем свободное время…';
  dialog.showModal();
  try {
    const response = await fetch('/admin/options/' + request.id);
    if (!response.ok) throw Error('Не удалось загрузить время. Откройте окно ещё раз.');
    const times = await response.json();
    if (request !== activeVisit) return;
    availableTimes = times.filter(time => Date.parse(time) !== Date.parse(box.dataset.start));
    dateField.disabled = false;
    showDayTimes();
  } catch (error) {
    if (request === activeVisit) statusLine.textContent = error.message;
  }
}

if (dialog) {
  dialog.onclose = () => { activeVisit = null; };
  dateField.onchange = showDayTimes;
  slots.onchange = () => { submit.disabled = false; };
  submit.onclick = async () => {
    const choice = slots.querySelector('input:checked');
    if (!choice) return;
    const visit = activeVisit;
    submit.disabled = true;
    try {
      await save('/admin/move/' + visit.id, {starts: choice.value});
      location.assign('/admin?visit=' + visit.id);
    } catch (error) {
      if (activeVisit === visit) {
        statusLine.textContent = error.message;
        submit.disabled = false;
      }
    }
  };
}

document.addEventListener('click', async event => {
  const action = event.target.dataset.action;
  if (!action) return;
  const box = event.target.closest('[data-id]');
  if (action === 'options') return openMove(box);
  if (action === 'cancel' && !confirm('Отменить визит и освободить время?')) return;
  try {
    await save('/admin/' + action + '/' + box.dataset.id);
    location.assign(action === 'unblock' ? location.href : '/admin?visit=' + box.dataset.id);
  } catch (error) {
    box.querySelector('[role=status]').textContent = error.message;
  }
});
