for (const form of document.querySelectorAll('.schedule-editor')) {
  const {day, kind} = form.dataset;
  const rows = [...form.querySelectorAll('.week-row')];
  const saveButton = form.querySelector('.schedule-save');
  const feedback = form.querySelector('output');
  const breaks = form.querySelector('#break-list');
  const initialBreaks = breaks ? [...breaks.children].map(row => row.dataset.key) : [];
  let source = rows[0];
  let saving = false;

  function hours(row) {
    return {opens: row.querySelector('[name=opens]').value, closes: row.querySelector('[name=closes]').value};
  }

  function values() {
    if (kind === 'settings') {
      return [{kind, day, step: +form.elements.step.value, horizon: +form.elements.horizon.value,
        lead_hours: +form.elements.lead_hours.value}];
    }
    if (kind === 'week') {
      return rows.map(row => ({kind, day: row.dataset.day, off: !row.querySelector('.toggle').checked,
        ...hours(row)}));
    }
    const mode = form.elements.mode.value;
    return [mode === 'inherit' ? {kind:'inherit', day} :
      {kind:'date', day, off:mode === 'off', ...(mode === 'custom' ? hours(form.querySelector('.custom-hours')) : {})}];
  }

  const initial = values().map(value => JSON.stringify(value));
  function changes() {
    const edits = values().filter((value,i) => JSON.stringify(value) !== initial[i]);
    const remaining = breaks ? [...breaks.children] : [];
    for (const row of remaining.filter(row => !row.dataset.key)) edits.push({kind:'break', day, ...hours(row)});
    return {day, edits, remove_breaks: initialBreaks.filter(key => !remaining.some(row => row.dataset.key === key))};
  }

  function sync() {
    for (const row of rows) {
      for (const input of row.querySelectorAll('[type=time]')) input.disabled = !row.querySelector('.toggle').checked;
    }
    if (kind === 'day') {
      const custom = form.querySelector('.custom-hours');
      custom.hidden = form.elements.mode.value !== 'custom';
      for (const input of custom.querySelectorAll('input')) input.disabled = custom.hidden;
      form.querySelector('#inherited').hidden = form.elements.mode.value !== 'inherit';
    }
    const pending = changes();
    saveButton.hidden = !pending.edits.length && !pending.remove_breaks.length;
  }

  form.addEventListener('input', event => {
    const row = event.target.closest('.week-row');
    if (row) {
      source = row;
      form.querySelector('#copy-source').textContent = 'По образцу: ' + row.querySelector('strong').textContent;
    }
    feedback.textContent = '';
    sync();
  });
  if (kind === 'week') form.querySelector('#copy-week').onclick = () => {
    for (const row of rows) {
      row.querySelector('.toggle').checked = source.querySelector('.toggle').checked;
      for (const name of ['opens','closes']) row.querySelector('[name='+name+']').value = source.querySelector('[name='+name+']').value;
    }
    sync();
  };
  if (breaks) {
    form.querySelector('#add-break').onclick = () => {
      const block = form.querySelector('#new-break').content.cloneNode(true);
      block.querySelector('[name=opens]').value = '13:00';
      block.querySelector('[name=closes]').value = '14:00';
      breaks.append(block);
      breaks.lastElementChild.querySelector('input').focus();
      sync();
    };
    breaks.onclick = event => {
      if (event.target.closest('[data-remove]')) {
        event.target.closest('.break-edit').remove();
        sync();
      }
    };
  }
  form.onsubmit = async event => {
    event.preventDefault();
    if (saving || saveButton.hidden) return;
    const payload = changes();
    saving = true;
    form.inert = true;
    try {
      await save('/admin/schedule-changes', payload);
      sessionStorage.setItem('saved-schedule',location.href);
      location.reload();
    } catch (error) {
      feedback.textContent = error.message;
      saving = false;
      form.inert = false;
    }
  };
  if (sessionStorage.getItem('saved-schedule') === location.href) {
    sessionStorage.removeItem('saved-schedule');
    feedback.textContent = 'Сохранено';
  }
  sync();
}
