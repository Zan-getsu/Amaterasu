// 1. Accordion toggle
document.querySelectorAll('.bs-accordion-trigger').forEach(trigger => {
  trigger.addEventListener('click', () => {
    const isOpen = trigger.classList.contains('open');
    // Close all others...
    trigger.classList.toggle('open', !isOpen);
    if(trigger.nextElementSibling) {
      trigger.nextElementSibling.style.display = isOpen ? 'none' : 'block';
    }
  });
});

// 2. Copy to clipboard (generic)
document.querySelectorAll('[data-copy]').forEach(btn => {
  btn.addEventListener('click', () => {
    const target = document.querySelector(btn.dataset.copy);
    if (!target) return;
    navigator.clipboard.writeText(target.textContent).then(() => {
      const original = btn.innerHTML;
      btn.innerHTML = '✓ Copied';
      setTimeout(() => (btn.innerHTML = original), 2000);
    });
  });
});

// 3. Toast system
function showToast(message, type = 'success', duration = 4000) {
  let container = document.getElementById('bs-toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'bs-toast-container';
    container.className = 'bs-toast-container';
    document.body.appendChild(container);
  }
  const toast = document.createElement('div');
  toast.className = `bs-toast bs-toast--${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), duration);
}

// 4. Mobile nav toggle
const mobileToggle = document.querySelector('.bs-navbar__mobile-toggle');
const navLinks = document.querySelector('.bs-navbar__links');
if (mobileToggle) {
  mobileToggle.addEventListener('click', () => {
    if (navLinks) {
      navLinks.classList.toggle('bs-navbar__links--open');
      mobileToggle.setAttribute('aria-expanded', navLinks.classList.contains('bs-navbar__links--open'));
    }
  });
}
