let pressedControl;
function releaseControl() {
  pressedControl?.removeAttribute('data-touch-pressed');
  pressedControl = null;
}
document.addEventListener('pointerdown', event => {
  if (!event.isPrimary || event.pointerType !== 'touch') return;
  releaseControl();
  pressedControl = event.target.closest('button:enabled, a[href], summary, label:has(input:is([type="checkbox"],[type="radio"])), .toggle:enabled');
  pressedControl?.setAttribute('data-touch-pressed', '');
}, {passive:true});
for (const type of ['pointerup','pointercancel']) {
  document.addEventListener(type, event => { if (event.isPrimary) releaseControl(); }, {passive:true});
}
window.addEventListener('blur', releaseControl);
