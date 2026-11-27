const el = id => document.getElementById(id);
const install = el('install-dialog');
install.querySelector('.close').onclick = () => install.close();
  let installPrompt;
  const installButton = el('install');
  installButton.hidden = matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    installPrompt = event;
  });
  addEventListener('appinstalled', () => {
    installPrompt = undefined;
    installButton.hidden = true;
  });
  installButton.onclick = async () => {
    if (installPrompt) {
      const event = installPrompt;
      installPrompt = undefined;
      await event.prompt();
      return;
    }
    const message = el('install-message');
    if (location.protocol === 'file:') {
      message.textContent = 'Откройте сайт в браузере.';
    } else if (/iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)) {
      message.textContent = 'В Safari откройте «Поделиться» → «На экран Домой» → «Добавить».';
    } else {
      message.textContent = 'В меню браузера выберите «Установить приложение» или «Добавить на главный экран», если этот пункт доступен.';
    }
    install.showModal();
  };
