const find = (selector, root = document) => root.querySelector(selector);
const all = (selector, root = document) => [...root.querySelectorAll(selector)];
const toast = find('#ce-toast');
let toastTimer;
function notify(message, error = false) {
  clearTimeout(toastTimer);
  toast.textContent = message;
  toast.classList.toggle('error', error);
  toast.hidden = false;
  toastTimer = setTimeout(() => {toast.hidden = true;}, error ? 6500 : 3000);
}

async function send(path, payload) {
  const binary = payload instanceof File;
  let response;
  try {
    response = await fetch('/admin/content/' + path, {method:'POST',
      headers:{'Content-Type': binary ? 'application/octet-stream' : 'application/json'},
      body:binary ? payload : JSON.stringify(payload)});
  } catch {
    throw Error('Нет связи с сервером. Повторите попытку.');
  }
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : 'Не удалось сохранить. Проверьте данные и повторите попытку.');
  return result;
}

async function checkPhoto(file) {
  if (file.size > 8 * 1024 * 1024) throw Error('Файл «' + file.name + '» слишком большой. Максимум — 8 МБ.');
  const bytes = new Uint8Array(await file.slice(0,12).arrayBuffer());
  const signature = String.fromCharCode(...bytes);
  const formats = {'image/jpeg':bytes[0]===255 && bytes[1]===216 && bytes[2]===255,
    'image/png':signature.startsWith(String.fromCharCode(137,80,78,71,13,10,26,10)), 'image/webp':signature.startsWith('RIFF') && signature.slice(8)==='WEBP'};
  if (!formats[file.type]) throw Error('Поддерживаются только JPEG, PNG и WebP.');
}
const photoUrl = key => '/admin/content/media/' + key + '/thumb';

const profile = find('#ce-profile');
if (profile) {
  const fileInput = find('#avatar-file');
  const avatar = find('.ce-avatar img');
  const remove = find('#remove-avatar');
  let selected, preview;
  const show = src => {
    avatar.hidden = remove.hidden = !src;
    if (src) avatar.src = src;
    else avatar.removeAttribute('src');
  };
  find('#pick-avatar').onclick = () => fileInput.click();
  profile.elements.name.oninput = () => { find('.ce-avatar span').textContent = profile.elements.name.value.trim().slice(0,1); };
  fileInput.onchange = async () => {
    const file = fileInput.files[0];
    fileInput.value = '';
    if (!file) return;
    const submit = find('button:not([type])',profile);
    submit.disabled = remove.disabled = find('#pick-avatar').disabled = true;
    try {
      await checkPhoto(file);
      selected = file;
      if (preview) URL.revokeObjectURL(preview);
      preview = URL.createObjectURL(file);
      show(preview);
    } catch (error) {notify(error.message,true);}
    finally {submit.disabled = remove.disabled = find('#pick-avatar').disabled = false;}
  };
  profile.addEventListener('invalid', event => {
    const label = event.target.closest('label')?.textContent.trim();
    notify(label ? 'Проверьте поле «' + label + '»' : 'Проверьте поля профиля',true);
  },true);
  remove.onclick = () => {
    selected = null;
    if (preview) URL.revokeObjectURL(preview);
    preview = null;
    profile.elements.avatar.value = '';
    show('');
  };
  profile.onsubmit = async event => {
    event.preventDefault();
    profile.inert = true;
    try {
      const values = Object.fromEntries(new FormData(profile));
      if (selected) values.avatar = (await send('photo',selected)).image;
      await send('edit-profile',values);
      profile.elements.avatar.value = values.avatar;
      selected = null;
      show(values.avatar ? photoUrl(values.avatar) : '');
      if (preview) URL.revokeObjectURL(preview);
      preview = null;
      notify('Изменения сохранены');
    } catch (error) {notify(error.message,true);}
    finally {profile.inert = false;}
  };
}

const modal = find('#service-dialog');
if (modal) {
  const form = find('#service-form');
  const catalog = JSON.parse(find('#catalog-data').textContent);
  const list = find('#addons');
  const problem = find('.ce-error',modal);
  let editing, removed;
  function appendAddon(value = {price:0, minutes:0, visible:true}) {
    const row = find('#addon-row').content.firstElementChild.cloneNode(true);
    row.dataset.key = value.id || '';
    row.dataset.visible = value.visible;
    find('[name=extra_title]',row).value = value.title || '';
    find('[name=extra_price]',row).value = value.price;
    find('[name=extra_minutes]',row).value = value.minutes;
    find('[data-remove]',row).onclick = () => {
      if (value.id) removed.push(value.id);
      row.remove();
      find('#add-addon').disabled = false;
    };
    list.append(row);
    find('#add-addon').disabled = list.children.length >= 20;
  }
  function open(item) {
    editing = item;
    removed = [];
    form.reset();
    problem.textContent = '';
    find('#service-heading').textContent = item ? 'Редактировать услугу' : 'Добавить услугу';
    for (const name of ['title','price','minutes']) form.elements[name].value = item?.[name] ?? '';
    list.replaceChildren();
    find('#add-addon').disabled = false;
    if (item) catalog.addons.filter(value => value.service_id === item.id).forEach(appendAddon);
    modal.showModal();
    form.elements.title.focus();
  }
  find('#add-service').onclick = () => open(null);
  find('#add-addon').onclick = () => appendAddon();
  for (const button of all('[data-close]',modal)) button.onclick = () => modal.close();
  modal.onclick = event => {
    if (event.target !== modal || form.inert) return;
    const bounds = modal.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) modal.close();
  };
  modal.oncancel = event => {if (form.inert) event.preventDefault();};
  form.onsubmit = async event => {
    event.preventDefault();
    form.inert = true;
    try {
      const addons = all('.addon-row',list).map(row => ({
        id:Number(row.dataset.key) || null, visible:row.dataset.visible === 'true',
        title:find('[name=extra_title]',row).value, price:+find('[name=extra_price]',row).value,
        minutes:+find('[name=extra_minutes]',row).value
      }));
      await send('edit-service',{id:editing?.id || null, title:form.elements.title.value,
        price:+form.elements.price.value, minutes:+form.elements.minutes.value, addons, removed});
      location.reload();
    } catch (error) {problem.textContent = error.message; form.inert = false;}
  };
  for (const row of all('.service-row')) {
    const item = catalog.items.find(value => value.id === Number(row.dataset.id));
    const endpoint = 'service/' + item.id + '/action';
    const toggle = find('.visibility',row);
    toggle.onchange = async () => {
      toggle.disabled = true;
      try {await send(endpoint,{action:'visibility', visible:toggle.checked}); notify('Сохранено');}
      catch (error) {toggle.checked = !toggle.checked; notify(error.message,true);}
      finally {toggle.disabled = false;}
    };
    for (const button of all('[data-op]',row)) button.onclick = async () => {
      const action = button.dataset.op;
      if (action === 'edit') return open(item);
      if (action === 'delete' && !confirm('Удалить услугу «' + item.title + '» вместе с дополнениями?')) return;
      const section = find('#services-list');
      section.inert = true;
      try {await send(endpoint,{action}); location.reload();}
      catch (error) {section.inert = false; notify(error.message,true);}
    };
  }
}

const grid = find('.work-grid');
if (grid) {
  function wire(card) {
    const input = find('input',card);
    let saved = input.value;
    input.onkeydown = event => {if (event.key === 'Enter') input.blur();};
    input.onblur = async () => {
      if (input.value === saved) return;
      input.readOnly = true;
      try {await send('work/' + card.dataset.id + '/caption',{caption:input.value}); saved = input.value; notify('Сохранено');}
      catch (error) {input.value = saved; notify(error.message,true);}
      finally {input.readOnly = false;}
    };
    find('[data-delete]',card).onclick = async () => {
      if (!confirm('Удалить фото из портфолио?')) return;
      card.inert = true;
      try {await send('work/' + card.dataset.id + '/delete',{}); card.remove(); notify('Фото удалено');}
      catch (error) {card.inert = false; notify(error.message,true);}
    };
  }
  all('.work',grid).forEach(wire);
  const picker = find('#work-files'), tile = find('#add-photo');
  tile.onclick = () => picker.click();
  picker.onchange = async () => {
    const files = [...picker.files];
    picker.value = '';
    tile.disabled = true;
    tile.setAttribute('aria-busy','true');
    const hint = find('small',tile), original = hint.textContent;
    const errors = [];
    for (const [index,file] of files.entries()) {
      hint.textContent = 'Загрузка ' + (index+1) + ' из ' + files.length + '…';
      try {
        await checkPhoto(file);
        const photo = await send('photo',file);
        const work = await send('work',{image:photo.image});
        const card = find('#work-card').content.firstElementChild.cloneNode(true);
        card.dataset.id = work.id;
        find('img',card).src = photoUrl(photo.image);
        grid.append(card);
        wire(card);
      } catch (error) {errors.push(error.message); notify(error.message,true);}
    }
    tile.disabled = false;
    tile.removeAttribute('aria-busy');
    hint.textContent = original;
    if (errors.length) notify([...new Set(errors)].join(' '),true);
    else if (files.length) notify('Фото добавлены');
  };
}
