import { api, ApiError } from './api.js';
import { clear, initTheme, notice, toggleTheme } from './ui.js';

initTheme();

const form = document.getElementById('login-form');
const submit = document.getElementById('submit');
const errorSlot = document.getElementById('error-slot');

document.getElementById('theme-toggle').addEventListener('click', toggleTheme);

api.me()
  .then(({ user }) => {
    sessionStorage.setItem('user', JSON.stringify(user));
    window.location.href = 'app.html';
  })
  .catch(() => {  });

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  clear(errorSlot);
  submit.disabled = true;
  submit.textContent = 'Signing in…';

  try {
    const { user } = await api.login(
      document.getElementById('email').value.trim(),
      document.getElementById('password').value,
    );
    sessionStorage.setItem('user', JSON.stringify(user));
    window.location.href = 'app.html';
  } catch (error) {
    const message = error instanceof ApiError ? error.message : 'Something went wrong.';
    errorSlot.append(notice(message, 'err'));
    submit.disabled = false;
    submit.textContent = 'Sign in';
  }
});
