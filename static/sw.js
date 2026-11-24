function cabinetUrl(target) {
  try {
    const url = new URL(target, self.location.origin);
    if (url.origin === self.location.origin && url.pathname === '/admin') return url.href;
  } catch {
    // При повреждённой ссылке открываем список записей.
  }
  return new URL('/admin', self.location.origin).href;
}

self.addEventListener('push', event => {
  if (!event.data) return;
  const payload = event.data.json();
  event.waitUntil(self.registration.showNotification('Кабинет мастера', {
    body: payload.body,
    tag: payload.tag,
    data: cabinetUrl(payload.url),
    icon: '/assets/icon-192.png'
  }));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const url = cabinetUrl(event.notification.data);
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({type: 'window', includeUncontrolled: true});
    const opened = windows.find(window => window.url === url);
    if (opened) return opened.focus();
    return self.clients.openWindow(url);
  })());
});
