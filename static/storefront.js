const el = id => document.getElementById(id);
let pressedControl;
function releaseControl() {
  pressedControl?.removeAttribute('data-touch-pressed');
  pressedControl = null;
}
document.addEventListener('pointerdown', event => {
  if (!event.isPrimary || event.pointerType !== 'touch') return;
  releaseControl();
  pressedControl = event.target.closest('button:enabled, a[href], label:has(input[type="checkbox"])');
  pressedControl?.setAttribute('data-touch-pressed', '');
}, {passive:true});
for (const type of ['pointerup','pointercancel']) {
  document.addEventListener(type, event => { if (event.isPrimary) releaseControl(); }, {passive:true});
}
window.addEventListener('blur', releaseControl);
for (const photo of document.querySelectorAll('.content img')) {
  if (photo.complete) continue;
  photo.classList.add('photo-loading');
  const reveal = () => photo.classList.remove('photo-loading');
  photo.addEventListener('load', reveal, {once:true});
  photo.addEventListener('error', reveal, {once:true});
}
const dialog = el('booking');
const form = el('form');
const sections = [...dialog.querySelectorAll('[data-step]')];
const services = [...dialog.querySelectorAll('[data-service]')];
const extras = [...dialog.querySelectorAll('[data-for-service]')];
const next = el('booking-next');
const submit = el('submit');
const note = el('notice');
const retry = el('retry-slots');
const titles = {service: 'Выберите услугу', time: 'Выберите окошко', contacts: 'Ваши контакты'};
let order, step, opener, service, quote, days, day, month, start, attempt;
let loading = false, sending = false, generation = 0;
let today = document.querySelector('[data-today]').dataset.today;

const endFormat = new Intl.DateTimeFormat('sv-SE', {
  timeZone: dialog.dataset.timezone, year:'numeric', month:'2-digit', day:'2-digit',
  hour:'2-digit', minute:'2-digit', hourCycle:'h23',
});
const dateLabel = (date, options) => new Date(date + 'T12:00:00').toLocaleDateString('ru-RU', options);
const shortDate = date => date === today ? 'сегодня' : dateLabel(date, {day:'numeric', month:'long'});
const selectedAddons = () => extras.filter(label => !label.hidden && label.firstElementChild.checked)
  .map(label => Number(label.firstElementChild.value));
const hasTime = () => !!start && !!days?.[start.slice(0, 10)]?.includes(start);
const total = () => quote ? [quote.minutes + ' мин', quote.price + ' ₽'].join(' · ') : '';

function status(message = '', canRetry = false) {
  note.hidden = !message;
  note.textContent = message;
  retry.hidden = !canRetry;
}

function updateActions() {
  const contacts = step === 'contacts';
  next.hidden = contacts;
  submit.hidden = !contacts;
  next.disabled = loading || (step === 'service' && (!quote || (order[0] === 'time' && !hasTime())))
    || (step === 'time' && !hasTime());
  submit.disabled = sending || loading || !quote || !hasTime() || !el('consent').checked;
  el('booking-back').disabled = sending;
  el('booking-close').disabled = sending;
  el('quote').hidden = contacts || !quote;
  el('quote').textContent = total();
  if (contacts && start && quote) {
    const end = new Date(Date.parse(start) + quote.minutes * 60000);
    const parts = Object.fromEntries(endFormat.formatToParts(end).map(({type, value}) => [type, value]));
    const endDay = [parts.year, parts.month, parts.day].join('-');
    const endTime = (endDay === day ? '' : shortDate(endDay) + ', ') + parts.hour + ':' + parts.minute;
    el('summary').textContent = [
      quote.title, shortDate(day) + ', ' + start.slice(11, 16) + ' — ' + endTime,
      total(), dialog.dataset.address,
    ].filter(Boolean).join('\n');
  }
}

function makeButton(text, click) {
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = text;
  button.addEventListener('click', click);
  return button;
}

function renderCalendar() {
  const dates = Object.keys(days);
  const months = [...new Set(dates.map(date => date.slice(0, 7)))];
  const index = months.indexOf(month);
  el('month').textContent = month ? dateLabel(month + '-01', {month:'long', year:'numeric'}) : '';
  for (const [id, delta] of [['prev', -1], ['next', 1]]) {
    const control = el(id);
    control.disabled = !months[index + delta];
    control.onclick = () => {
      month = months[index + delta];
      day = dates.find(date => date.startsWith(month) && days[date].length) || dates.find(date => date.startsWith(month));
      renderCalendar();
    };
  }

  const grid = el('dates');
  grid.replaceChildren();
  if (month) {
    const first = new Date(month + '-01T12:00:00');
    const count = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
    for (let number = 1; number <= count; number++) {
      const date = month + '-' + String(number).padStart(2, '0');
      const control = makeButton(number, () => {
        day = date;
        grid.querySelector('[aria-pressed="true"]')?.setAttribute('aria-pressed', 'false');
        control.setAttribute('aria-pressed', 'true');
        renderTimes();
      });
      if (number === 1) control.style.gridColumnStart = (first.getDay() + 6) % 7 + 1;
      control.disabled = !(date in days);
      control.setAttribute('aria-label', dateLabel(date, {day:'numeric', month:'long'}));
      control.setAttribute('aria-pressed', date === day);
      control.classList.toggle('has-windows', !!days[date]?.length);
      grid.append(control);
    }
  }
  renderTimes();
}

function renderTimes() {
  const options = days[day] || [];
  el('when').textContent = day ? shortDate(day) + ' · начало визита' : 'Начало визита';
  const list = el('slots');
  list.replaceChildren();
  for (const time of options) {
    const control = makeButton(time.slice(11, 16), () => {
      start = time;
      list.querySelector('[aria-pressed="true"]')?.setAttribute('aria-pressed', 'false');
      control.setAttribute('aria-pressed', 'true');
      updateActions();
    });
    control.setAttribute('aria-pressed', time === start);
    list.append(control);
  }

  const availableDays = Object.keys(days).filter(date => days[date].length);
  const nearest = availableDays.find(date => date >= day) || availableDays[0];
  el('nearest').hidden = !!options.length || !nearest;
  el('nearest').onclick = () => {
    day = nearest;
    month = day.slice(0, 7);
    renderCalendar();
    el('slots').firstElementChild?.focus();
  };
  if (!options.length) status(nearest ? 'На этот день свободных окон нет.' : 'Свободных окон пока нет. Свяжитесь с мастером.');
  else status();
  updateActions();
  if (start?.slice(0, 10) !== day) next.disabled = true;
}

async function refresh() {
  const id = ++generation;
  loading = true;
  quote = null;
  days = {};
  if (step === 'time') {
    el('dates').replaceChildren();
    el('slots').replaceChildren();
    el('month').textContent = '';
    el('when').textContent = 'Начало визита';
    el('prev').disabled = el('next').disabled = true;
    el('nearest').hidden = true;
  }
  status('Загружаем свободные окошки…');
  updateActions();
  try {
    const params = new URLSearchParams({service});
    selectedAddons().forEach(addon => params.append('addons', addon));
    const response = await fetch(service ? '/slots?' + params : '/windows');
    const data = await response.json();
    if (id !== generation) return;
    if (!response.ok) throw Error(data.detail);
    days = Object.fromEntries(Object.entries(data.days).map(([date, options]) =>
      [date, service ? options.filter(option => !option.status).map(option => option.start) : options]));
    today = data.today || today;
    if (service) quote = data;
    loading = false;
    if (step === 'time') {
      if (hasTime()) day = start.slice(0, 10);
      if (!(day in days)) day = data.times[0]?.slice(0, 10) || Object.keys(days)[0];
      month = day?.slice(0, 7);
      renderCalendar();
    } else if (step === 'service' && order[0] === 'time' && !hasTime()) {
      status('Услуга с выбранными дополнениями не помещается в это окошко. Выберите другую услугу или вернитесь к календарю.');
    } else {
      status();
      updateActions();
    }
    if (step === 'service') updateActions();
  } catch (error) {
    if (id !== generation) return;
    loading = false;
    status(error instanceof TypeError ? 'Не удалось загрузить окошки. Проверьте интернет.' : 'Услуга или дополнение изменились. Обновите страницу.', error instanceof TypeError);
    updateActions();
  }
}

function showStep(name) {
  step = name;
  sections.forEach(section => section.hidden = section.dataset.step !== name);
  el('booking-progress').textContent = 'Шаг ' + (order.indexOf(name) + 1) + ' из 3';
  el('booking-title').textContent = titles[name];
  el('booking-back').hidden = order[0] === name;
  el('time-context').hidden = order[0] !== 'time' || !start;
  if (start) el('time-context').textContent = shortDate(start.slice(0, 10)) + ', ' + start.slice(11, 16);
  dialog.querySelector('.booking-body').scrollTop = 0;
  status();
  updateActions();
  el('booking-title').focus();
}

function chooseService(id) {
  const changed = service !== id;
  service = id;
  if (changed) {
    if (order[0] === 'service') {
      start = undefined;
      day = undefined;
    }
    services.forEach(button => button.setAttribute('aria-pressed', Number(button.dataset.service) === id));
    extras.forEach(label => {
      label.hidden = Number(label.dataset.forService) !== id;
      label.firstElementChild.checked = false;
    });
    el('extras').hidden = extras.every(label => label.hidden);
  }
  refresh();
}

function openBooking(trigger, first, preferred, preset, fromPortfolio = false) {
  if (dialog.open) return;
  generation++;
  el('consent').checked = false;
  loading = false;
  opener = trigger;
  order = [first, first === 'service' ? 'time' : 'service', 'contacts'];
  start = preferred;
  day = preferred?.slice(0, 10);
  service = quote = undefined;
  days = {};
  services.forEach(button => button.setAttribute('aria-pressed', 'false'));
  el('extras').hidden = true;
  dialog.showModal();
  showStep(fromPortfolio ? 'time' : (preferred ? 'service' : first));
  if (preset) chooseService(preset);
  if (first === 'time' && !preferred) refresh();
}

document.querySelectorAll('[data-booking-entry]').forEach(trigger => trigger.addEventListener('click', event => {
  event.preventDefault();
  openBooking(trigger, trigger.dataset.bookingEntry, trigger.dataset.start);
}));
const rows = [...document.querySelectorAll('[data-price-service]')];
const addons = JSON.parse(el('service-extras').textContent);
let primary;
const picked = new Set();
const dock = document.querySelector('.dock');
const dockSelection = document.createElement('div');
const dockCount = document.createElement('small');
const dockTotal = document.createElement('strong');
const dockContinue = makeButton('Продолжить', continueSelection);
const nearestControls = dock ? [...dock.children] : [];
dockSelection.append(dockCount, dockTotal);
dockSelection.hidden = dockContinue.hidden = true;
dock?.append(dockSelection, dockContinue);
const sameItem = (row, addon) => row.dataset.title === addon.title && Number(row.dataset.minutes) === addon.minutes && Number(row.dataset.price) === addon.price;
function renderSelection() {
  const options = addons.filter(a => a.service_id === Number(primary?.dataset.priceService));
  for (const row of rows) {
    const addon = options.find(a => sameItem(row,a));
    row.setAttribute('aria-pressed', row === primary || !!addon && picked.has(addon.id));
  }
  const list = el('price-addons');
  list.replaceChildren();
  for (const addon of options.filter(a => !rows.some(row => sameItem(row,a)))) {
    const label = document.createElement('label');
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = picked.has(addon.id);
    input.onchange = () => toggleAddon(addon);
    label.append(input, addon.title + ' · ' + addon.price + ' ₽ · ' + addon.minutes + ' мин');
    list.append(label);
  }
  const selected = options.filter(a => picked.has(a.id));
  const price = selected.reduce((n,a) => n+a.price,Number(primary?.dataset.price || 0));
  const minutes = selected.reduce((n,a) => n+a.minutes,Number(primary?.dataset.minutes || 0));
  el('price-total').textContent = primary ? 'Итого: ' + price.toLocaleString('ru-RU') + ' ₽ · ' + minutes + ' мин' : 'Выберите услугу';
  el('continue-selection').disabled = !primary;
  for (const control of nearestControls) control.hidden = !!primary;
  dockSelection.hidden = dockContinue.hidden = !primary;
  if (primary) {
    dockCount.textContent = 'Выбрано услуг: ' + (1 + selected.length);
    dockTotal.textContent = price.toLocaleString('ru-RU') + ' ₽ · ' + minutes + ' мин';
  }
}
function toggleAddon(addon) {
  if (picked.has(addon.id)) picked.delete(addon.id);
  else picked.add(addon.id);
  renderSelection();
}
for (const row of rows) row.onclick = () => {
  const addon = addons.find(a => a.service_id === Number(primary?.dataset.priceService) && sameItem(row,a));
  if (addon && row !== primary) return toggleAddon(addon);
  const previous = primary;
  const selected = addons.filter(a => picked.has(a.id));
  primary = row === primary ? null : row;
  picked.clear();
  for (const a of addons.filter(a => a.service_id === Number(primary?.dataset.priceService))) {
    if ((previous && sameItem(previous,a)) || selected.some(x => x.title===a.title && x.price===a.price && x.minutes===a.minutes)) picked.add(a.id);
  }
  renderSelection();
};
function continueSelection(event) {
  openBooking(event.currentTarget,'service',undefined,Number(primary.dataset.priceService),true);
  for (const label of extras) label.firstElementChild.checked = !label.hidden && picked.has(Number(label.firstElementChild.value));
  if (picked.size) refresh();
}
el('continue-selection').onclick = continueSelection;
el('consent').onchange = updateActions;
document.addEventListener('book-portfolio', event => openBooking(event.target, 'service', undefined, event.detail, true));
services.forEach(button => button.addEventListener('click', () => chooseService(Number(button.dataset.service))));
el('extras').addEventListener('change', refresh);
retry.addEventListener('click', refresh);
el('booking-close').addEventListener('click', () => dialog.close());
dialog.addEventListener('cancel', event => { if (sending) event.preventDefault(); });
dialog.addEventListener('close', () => {
  if (dialog.open) return;
  generation++;
  loading = false;
  opener?.focus({preventScroll:true});
});
el('booking-back').addEventListener('click', () => {
  const previous = order[order.indexOf(step) - 1];
  if (previous === 'time' && order[0] === 'time') quote = undefined;
  showStep(previous);
  if (previous === 'time') refresh();
  if (previous === 'service' && service) refresh();
});
next.addEventListener('click', () => {
  showStep(order[order.indexOf(step) + 1]);
  if (step === 'time') refresh();
});

form.addEventListener('submit', async event => {
  event.preventDefault();
  if (submit.disabled || step !== 'contacts') return;
  const name = el('name');
  const phone = el('phone');
  if (!name.value.trim()) {
    name.setCustomValidity('Введите имя');
    name.reportValidity();
    return;
  }
  if (!/^\+?\d{10,15}$/.test(phone.value.replace(/[ ()-]/g, ''))) {
    phone.setCustomValidity('Введите от 10 до 15 цифр');
    phone.reportValidity();
    return;
  }
  const fields = {
    name: name.value.trim(), phone: phone.value, starts: start, service,
    price: quote.price, minutes: quote.minutes, addons: selectedAddons(), social: el('social').value.trim(), comment:el('comment').value.trim(),
    consent_version:el('consent').checked ? el('consent').value : null,
  };
  const fingerprint = JSON.stringify(fields);
  if (attempt?.fingerprint !== fingerprint) attempt = {fingerprint, id: crypto.randomUUID()};
  sending = true;
  updateActions();
  status();
  try {
    const response = await fetch('/book', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({...fields, request_id:attempt.id}),
    });
    const data = await response.json();
    if (response.ok) {
      location.assign(data.url);
      return;
    }
    if (response.status === 409) {
      attempt = undefined;
      await refresh();
      if (quote && !hasTime()) {
        showStep('time');
        await refresh();
      }
    } else if (response.status === 404) {
      showStep('service');
      await refresh();
    }
    status(data.detail);
  } catch {
    status('Ответ не получен. После подключения нажмите «Записаться» ещё раз.');
  } finally {
    sending = false;
    updateActions();
  }
});

for (const id of ['name', 'phone']) el(id).addEventListener('input', () => el(id).setCustomValidity(''));
