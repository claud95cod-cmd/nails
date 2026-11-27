const gallery = document.getElementById('work-dialog');
const full = document.getElementById('work-large');
const caption = document.getElementById('work-caption');
const book = document.getElementById('work-book');
let opener;

for (const trigger of document.querySelectorAll('.work-open')) {
  trigger.onclick = () => {
    opener = trigger;
    full.src = trigger.dataset.image;
    full.alt = trigger.dataset.caption;
    caption.textContent = trigger.dataset.caption;
    caption.hidden = !trigger.dataset.caption;
    book.hidden = !trigger.dataset.bookService;
    gallery.showModal();
  };
}

document.getElementById('work-close').onclick = () => gallery.close();
gallery.addEventListener('close', () => {
  full.removeAttribute('src');
  opener.focus({preventScroll: true});
});
book.onclick = () => {
  const service = opener.dataset.bookService;
  gallery.close();
  opener.dispatchEvent(new CustomEvent('book-portfolio', {bubbles: true, detail: Number(service)}));
};
