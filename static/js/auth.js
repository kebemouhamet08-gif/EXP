const form = document.querySelector('#login-form');
const message = document.querySelector('#form-message');

form?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = form.querySelector('button');
  if (!navigator.onLine) {
    window.ClasseXPFeedback?.showToast('Connexion Internet requise pour vous connecter.', 'error', 0);
    return;
  }

  const originalHtml = button.innerHTML;
  button.style.minWidth = `${Math.ceil(button.getBoundingClientRect().width)}px`;
  button.disabled = true;
  button.classList.add('is-loading');
  button.setAttribute('aria-disabled', 'true');
  const spinner = document.createElement('span');
  spinner.className = 'spinner';
  spinner.setAttribute('aria-hidden', 'true');
  const loadingLabel = document.createElement('span');
  loadingLabel.textContent = button.dataset.loadingText || 'Connexion…';
  button.replaceChildren(spinner, loadingLabel);
  message.textContent = 'Connexion…';

  try {
    const csrfResponse = await fetch('/api/auth/csrf');
    const { csrf_token: csrfToken } = await csrfResponse.json();
    const response = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({
        email: form.user_mail.value,
        password: form.user_passwd.value,
      }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.message || 'Connexion impossible.');
    try {
      sessionStorage.setItem('classexp-feedback', JSON.stringify({
        type: 'success', message: 'Connexion réussie.',
      }));
    } catch {
      // Navigation still succeeds when storage is unavailable.
    }
    window.location.assign(result.role === 'STUDENT' ? '/eleve' : '/professeur');
  } catch (error) {
    message.textContent = error.message;
    message.setAttribute('role', 'alert');
    window.ClasseXPFeedback?.showToast(error.message, 'error');
    button.innerHTML = originalHtml;
    button.style.minWidth = '';
    button.classList.remove('is-loading');
    button.removeAttribute('aria-disabled');
    button.disabled = false;
  }
});
