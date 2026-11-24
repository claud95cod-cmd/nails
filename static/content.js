
const profile = document.querySelector('[data-editor="profile"]');
const preview = document.getElementById('preview');
const pictures = new Map();
const texts = ['name', 'specialty', 'tagline', 'description', 'phone', 'address', 'directions', 'timezone',
  'accent', 'background', 'fonts', 'avatar', 'cover'];
const data = (form, names) => Object.fromEntries(names.map(name => [name, form.get(name)]));
const assetUrl = (key, size = 'thumb') => '/admin/content/media/' + key + '/' + size;

async function submit(url, payload, binary = false) {
  const response = await fetch('/admin/content/' + url, {
    method: 'POST',
    headers: {'Content-Type': binary ? 'application/octet-stream' : 'application/json'},
    body: binary ? payload : JSON.stringify(payload)
  });
  const result = await response.json();
  if (!response.ok) throw Error(result.detail || 'Запрос не выполнен');
  return result;
}

function foreground(color) {
  const channels = [1, 3, 5].map(index => Number.parseInt(color.slice(index, index + 2), 16) / 255);
  const linear = channels.map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
  const light = linear[0] * .2126 + linear[1] * .7152 + linear[2] * .0722;
  return light > .179 ? '#000000' : '#ffffff';
}

function updatePhoto(img, key, size) {
  img.hidden = !key;
  if (key) {
    const url = assetUrl(key, size);
    if (img.getAttribute('src') !== url) img.src = url;
  } else {
    img.removeAttribute('src');
  }
}

function updatePreview() {
  const fields = profile.elements;
  for (const element of preview.querySelectorAll('[data-preview]')) {
    element.textContent = fields[element.dataset.preview].value;
    element.hidden = !element.textContent;
  }
  preview.querySelector('.button').hidden = !document.querySelector('[data-editor="service"][data-published="true"]');
  preview.dataset.fonts = fields.fonts.value;
  preview.style.setProperty('--profile-bg', fields.background.value);
  preview.style.setProperty('--profile-ink', foreground(fields.background.value));
  preview.style.setProperty('--profile-accent', fields.accent.value);
  preview.style.setProperty('--profile-on-accent', foreground(fields.accent.value));
  const cover = preview.querySelector('.profile-cover');
  cover.style.objectPosition = fields.cover_x.value + '% ' + fields.cover_y.value + '%';
  updatePhoto(cover, fields.cover.value, 'full');
  updatePhoto(preview.querySelector('.profile-avatar'), fields.avatar.value);
}

function wirePicture(field) {
  const key = field.querySelector('input[type="hidden"]');
  const file = field.querySelector('input[type="file"]');
  const output = field.querySelector('output');
  const remove = field.querySelector('.remove-photo');
  function change(value) {
    key.value = value;
    updatePhoto(field.querySelector('img'), value);
    if (remove) remove.hidden = !value;
    if (field.closest('form') === profile) updatePreview();
  }
  if (remove) remove.onclick = () => {change(''); output.textContent = '';};
  file.onchange = () => {
    const photo = file.files[0];
    if (!photo) return;
    file.disabled = true;
    if (remove) remove.disabled = true;
    output.textContent = 'Загружается «' + photo.name + '»…';
    const pending = submit('photo', photo, true).then(result => {
      change(result.image);
      output.textContent = 'Фото готово. Сохраните изменения.';
    }).catch(error => {
      output.textContent = photo.name + ' · ' + error.message;
      throw error;
    }).finally(() => {
      pictures.delete(field);
      file.value = '';
      file.disabled = false;
      if (remove) remove.disabled = false;
    });
    pictures.set(field, pending);
    pending.catch(() => {});
  };
}

function profilePayload(form) {
  const values = new FormData(form);
  return {
    ...data(values, texts),
    cover_x: Number(values.get('cover_x')), cover_y: Number(values.get('cover_y')),
    links: [...form.querySelectorAll('.link-row')].map(row => ({
      title: row.querySelector('[name=link_title]').value,
      url: row.querySelector('[name=link_url]').value
    }))
  };
}

function servicePayload(form) {
  const values = new FormData(form);
  return {
    ...data(values, ['title', 'category', 'instructions']), id: Number(form.dataset.id) || null,
    price: Number(values.get('price')), minutes: Number(values.get('minutes')), position: Number(values.get('position')),
    visible: values.has('visible'),
    addons: [...form.querySelectorAll('.addon-row')].map(row => ({
      id: Number(row.querySelector('[name=addon_id]').value) || null,
      title: row.querySelector('[name=addon_title]').value,
      price: Number(row.querySelector('[name=addon_price]').value),
      minutes: Number(row.querySelector('[name=addon_minutes]').value),
      visible: row.querySelector('[name=addon_visible]').checked
    }))
  };
}

function workPayload(form) {
  const values = new FormData(form);
  return {
    ...data(values, ['image', 'caption']), position: Number(values.get('position')),
    service_id: Number(values.get('service_id')) || null, visible: values.has('visible')
  };
}

function wireEditor(form) {
  const type = form.dataset.editor;
  const fields = [...form.querySelectorAll('[data-picture]')];
  fields.forEach(wirePicture);
  form.onsubmit = async event => {
    event.preventDefault();
    const button = event.submitter || form.querySelector('button:last-of-type');
    const output = form.querySelector(':scope > output');
    button.disabled = true;
    output.textContent = 'Сохраняю…';
    try {
      await Promise.all(fields.map(field => pictures.get(field)));
      if (type === 'service') {
        const saved = await submit(type, servicePayload(form));
        const anchor = '#service-' + saved.id;
        history.replaceState(null, '', anchor);
        location.reload();
        return;
      }
      const payload = type === 'profile' ? profilePayload(form) : workPayload(form);
      await submit(type === 'work' ? 'work/' + form.dataset.id : type, payload);
      if (type === 'work') form.parentElement.firstElementChild.textContent =
        (payload.caption || 'Фото ' + form.dataset.id) + (payload.visible ? '' : ' · скрыто');
      output.textContent = 'Сохранено';
    } catch (error) {
      output.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  };
}

document.querySelectorAll('[data-editor]').forEach(wireEditor);
profile.addEventListener('input', updatePreview);
updatePreview();
const linked = document.getElementById('link-list');
document.getElementById('add-link').onclick = () => {
  if (linked.children.length >= 8) return;
  linked.append(document.getElementById('link-template').content.cloneNode(true));
  linked.lastElementChild.querySelector('input').focus();
};

document.addEventListener('click', event => {
  if (event.target.matches('[data-remove-link]')) event.target.closest('.link-row').remove();
  if (event.target.matches('[data-remove-addon]')) event.target.closest('.addon-row').remove();
  if (event.target.matches('[data-add-addon]')) {
    const list = event.target.previousElementSibling;
    if (list.children.length >= 20) return;
    list.append(document.getElementById('addon-template').content.cloneNode(true));
    list.lastElementChild.querySelector('[name=addon_title]').focus();
  }
});

const batch = document.getElementById('batch');
batch.onsubmit = async event => {
  event.preventDefault();
  const input = batch.querySelector('input');
  const button = batch.querySelector('button');
  const results = document.getElementById('batch-results');
  const files = [...input.files];
  input.disabled = button.disabled = true;
  results.replaceChildren();
  try {
    for (const file of files) {
      const result = document.createElement('li');
      results.append(result);
      result.textContent = file.name + ' · загружается…';
      try {
        const photo = await submit('photo', file, true);
        const saved = await submit('work', {image: photo.image});
        const list = document.getElementById('work-list');
        list.append(document.getElementById('work-template').content.cloneNode(true));
        const editor = list.lastElementChild.querySelector('form');
        editor.dataset.id = saved.id;
        editor.parentElement.firstElementChild.textContent = 'Фото ' + saved.id;
        editor.elements.image.value = photo.image;
        updatePhoto(editor.querySelector('img'), photo.image);
        wireEditor(editor);
        result.textContent = file.name + ' · загружено';
      } catch (error) {
        result.textContent = file.name + ' · ' + error.message;
      }
    }
  } finally {
    input.value = '';
    input.disabled = button.disabled = false;
  }
};

const serviceAnchor = /^#service-(\d+)$/.exec(location.hash);
if (serviceAnchor) {
  const serviceDetails = document.getElementById(serviceAnchor[0].slice(1));
  if (serviceDetails) {
    serviceDetails.open = true;
    serviceDetails.querySelector('output').textContent = 'Сохранено';
  }
}
