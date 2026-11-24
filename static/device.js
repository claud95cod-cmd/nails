const devices = document.getElementById('devices');
const workerReady = 'serviceWorker' in navigator
  ? navigator.serviceWorker.register('/sw.js', {scope: '/'}).then(() => navigator.serviceWorker.ready)
  : null;

if (!devices) {
  workerReady?.catch(() => {});
} else {
  const statusLine = document.getElementById('status');
  const activeMark = document.getElementById('active');
  const enable = document.getElementById('enable');
  const test = document.getElementById('test');
  const disable = document.getElementById('disable');
  const ios = /iPhone|iPad|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const standalone = navigator.standalone || matchMedia('(display-mode: standalone)').matches;
  const permissionHelp = ios
    ? 'Откройте «Настройки → Уведомления», найдите кабинет мастера и разрешите уведомления.'
    : 'В Chrome откройте настройки сайта и разрешите уведомления. Затем вернитесь в кабинет.';
  let registration;
  let active = false;
  let busy = false;

  async function send(action, subscription) {
    const response = await fetch('/admin/device/' + action, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(subscription)
    });
    if (response.status === 401) throw Error('Сеанс истёк. Откройте кабинет и войдите заново.');
    const data = await response.json();
    if (!response.ok) {
      if (action === 'test' && response.status === 409) active = false;
      throw Error(data.detail || 'Запрос не выполнен.');
    }
    return data;
  }

  function render() {
    activeMark.hidden = !active;
    enable.hidden = active;
    test.hidden = disable.hidden = !active;
    enable.disabled = !registration || busy || Notification.permission === 'denied';
    test.disabled = disable.disabled = busy;
  }

  async function refresh() {
    const sub = await registration.pushManager.getSubscription();
    active = !!sub && Notification.permission === 'granted' && sameKey(sub, applicationKey()) &&
      (await send('status', sub)).enabled;
    render();
    statusLine.textContent = Notification.permission === 'denied' ? permissionHelp : '';
  }

  function applicationKey() {
    const key = devices.dataset.key.replace(/-/g, '+').replace(/_/g, '/');
    return Uint8Array.from(atob(key), character => character.charCodeAt(0));
  }

  function sameKey(subscription, key) {
    const saved = subscription.options?.applicationServerKey;
    if (!saved) return true;
    const bytes = new Uint8Array(saved);
    return bytes.length === key.length && key.every((byte, index) => bytes[index] === byte);
  }

  async function action(kind) {
    if (!registration || busy) return;
    busy = true;
    render();
    try {
      if (kind === 'enable' && await Notification.requestPermission() !== 'granted') {
        throw Error(permissionHelp);
      }
      let sub = await registration.pushManager.getSubscription();
      if (kind === 'enable') {
        const key = applicationKey();
        if (sub && !sameKey(sub, key)) {
          await send('disable', sub);
          await sub.unsubscribe();
          sub = null;
        }
        sub ??= await registration.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: key});
      }
      if (!sub) {
        active = false;
        throw Error('Подписка исчезла. Включите уведомления заново.');
      }
      await send(kind, sub);
      if (kind === 'disable') await sub.unsubscribe();
      active = kind !== 'disable';
      statusLine.textContent = kind === 'test'
        ? 'Проверка поставлена в очередь. Проверьте, появится ли уведомление на телефоне.'
        : '';
    } catch (error) {
      statusLine.textContent = error.message;
    } finally {
      busy = false;
      render();
    }
  }

  async function init() {
    if (ios && !standalone) {
      workerReady?.catch(() => {});
      statusLine.textContent = 'В Safari нажмите «Поделиться» → «На экран Домой», затем откройте кабинет с иконки. Требуется iOS 16.4 или новее.';
      return;
    }
    if (!workerReady || !('PushManager' in window && 'Notification' in window)) {
      workerReady?.catch(() => {});
      statusLine.textContent = ios
        ? 'Для уведомлений обновите iPhone до iOS 16.4 или новее.'
        : 'Откройте кабинет по HTTPS в Chrome с поддержкой Web Push.';
      return;
    }
    registration = await workerReady;
    render();
    await refresh();
  }

  enable.onclick = () => action('enable');
  test.onclick = () => action('test');
  disable.onclick = () => action('disable');
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && registration && !busy) {
      refresh().catch(error => {statusLine.textContent = error.message;});
    }
  });
  init().catch(error => {
    statusLine.textContent = error.message || 'Не удалось подготовить уведомления. Обновите страницу.';
  });
}
