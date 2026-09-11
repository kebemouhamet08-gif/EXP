const form = document.querySelector('#login-form');
const message = document.querySelector('#form-message');

form?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = form.querySelector('button');
  button.disabled = true;
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
    window.location.assign(result.role === 'STUDENT' ? '/eleve' : '/professeur');
  } catch (error) {
    message.textContent = error.message;
    button.disabled = false;
  }
});
