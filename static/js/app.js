(() => {
  const sidebar = document.querySelector('[data-sidebar]');
  const backdrop = document.querySelector('[data-sidebar-backdrop]');
  const menuToggle = document.querySelector('[data-menu-toggle]');
  const toastContainer = document.querySelector('[data-toast-container]');
  const toastIcons = { success: '✓', error: '✕', warning: '!', info: 'i' };

  const dismissToast = (toast) => {
    if (!toast || toast.classList.contains('is-leaving')) return;
    window.clearTimeout(toast._dismissTimeout);
    toast.classList.add('is-leaving');
    toast.classList.remove('is-visible');
    window.setTimeout(() => toast.remove(), 220);
  };

  const armToast = (toast) => {
    const category = toast.dataset.category || 'info';
    const delay = category === 'warning' ? 6000 : 4500;
    const schedule = () => {
      window.clearTimeout(toast._dismissTimeout);
      toast._dismissTimeout = window.setTimeout(() => dismissToast(toast), delay);
    };
    toast.querySelector('[data-toast-close]')?.addEventListener('click', () => dismissToast(toast));
    toast.addEventListener('mouseenter', () => window.clearTimeout(toast._dismissTimeout));
    toast.addEventListener('mouseleave', schedule);
    toast.addEventListener('focusin', () => window.clearTimeout(toast._dismissTimeout));
    toast.addEventListener('focusout', schedule);
    window.requestAnimationFrame(() => toast.classList.add('is-visible'));
    schedule();
  };

  const showToast = (message, category = 'info') => {
    if (!toastContainer) return;
    const safeCategory = Object.prototype.hasOwnProperty.call(toastIcons, category) ? category : 'info';
    const toast = document.createElement('div');
    toast.className = `toast toast--${safeCategory}`;
    toast.dataset.toast = '';
    toast.dataset.category = safeCategory;
    toast.setAttribute('role', safeCategory === 'error' ? 'alert' : 'status');
    const icon = document.createElement('span');
    icon.className = 'toast-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = toastIcons[safeCategory];
    const copy = document.createElement('p');
    copy.textContent = message;
    const close = document.createElement('button');
    close.className = 'toast-close';
    close.type = 'button';
    close.dataset.toastClose = '';
    close.setAttribute('aria-label', 'Fermer la notification');
    close.textContent = '×';
    toast.append(icon, copy, close);
    toastContainer.appendChild(toast);
    armToast(toast);
  };

  document.querySelectorAll('[data-toast]').forEach(armToast);
  window.ClasseXPToast = showToast;

  const setMenuState = (open) => {
    sidebar?.classList.toggle('is-open', open);
    backdrop?.classList.toggle('is-visible', open);
    menuToggle?.setAttribute('aria-expanded', String(open));
    menuToggle?.setAttribute('aria-label', open ? 'Fermer la navigation' : 'Ouvrir la navigation');
    document.body.classList.toggle('menu-open', open);
  };

  menuToggle?.addEventListener('click', () => {
    setMenuState(!sidebar?.classList.contains('is-open'));
  });
  backdrop?.addEventListener('click', () => setMenuState(false));
  sidebar?.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => setMenuState(false)));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') setMenuState(false);
  });

  document.querySelectorAll('[data-password-toggle]').forEach((toggle) => {
    toggle.addEventListener('click', () => {
      const input = toggle.closest('.password-field')?.querySelector('input');
      if (!input) return;
      const visible = input.type === 'text';
      input.type = visible ? 'password' : 'text';
      toggle.setAttribute('aria-pressed', String(!visible));
      toggle.setAttribute('aria-label', visible ? 'Afficher le mot de passe' : 'Masquer le mot de passe');
    });
  });

  document.querySelectorAll('[data-copy]').forEach((button) => {
    button.addEventListener('click', async () => {
      const value = button.dataset.copy || '';
      try {
        if (navigator.clipboard?.writeText) {
          await navigator.clipboard.writeText(value);
        } else {
          const helper = document.createElement('textarea');
          helper.value = value;
          helper.setAttribute('readonly', '');
          helper.style.position = 'fixed';
          helper.style.opacity = '0';
          document.body.appendChild(helper);
          helper.select();
          document.execCommand('copy');
          helper.remove();
        }
        showToast('Code copié', 'success');
      } catch {
        showToast(`Code : ${value}`, 'info');
      }
    });
  });

  document.querySelectorAll('[data-dropzone]').forEach((zone) => {
    const input = zone.querySelector('[data-file-input]');
    const filename = zone.querySelector('[data-file-name]');
    if (!input) return;

    const updateFile = (file) => {
      if (!file) return;
      filename && (filename.textContent = file.name);
      zone.classList.remove('is-dragging');
    };

    input.addEventListener('change', () => updateFile(input.files?.[0]));
    ['dragenter', 'dragover'].forEach((eventName) => zone.addEventListener(eventName, (event) => {
      event.preventDefault();
      zone.classList.add('is-dragging');
    }));
    ['dragleave', 'drop'].forEach((eventName) => zone.addEventListener(eventName, (event) => {
      event.preventDefault();
      if (eventName === 'drop') {
        const file = event.dataTransfer?.files?.[0];
        if (file) {
          try { input.files = event.dataTransfer.files; } catch { /* Browser may protect the file list. */ }
          updateFile(file);
        }
      } else {
        zone.classList.remove('is-dragging');
      }
    }));
  });

  const assignmentForm = document.querySelector('[data-assignment-form]');
  if (assignmentForm) {
    const title = assignmentForm.querySelector('[data-summary-title]');
    const classSelect = assignmentForm.querySelector('[data-summary-class]');
    const date = assignmentForm.querySelector('[data-summary-date]');
    const duration = assignmentForm.querySelector('[data-summary-duration]');
    const output = {
      title: document.querySelector('[data-summary-output]'),
      className: document.querySelector('[data-summary-class-output]'),
      date: document.querySelector('[data-summary-date-output]'),
      duration: document.querySelector('[data-summary-duration-output]'),
    };

    const updateSummary = () => {
      if (output.title) output.title.textContent = title?.value.trim() || 'Titre du devoir';
      if (output.className) output.className.textContent = classSelect?.selectedOptions[0]?.textContent || 'Classe sélectionnée';
      if (output.date) {
        output.date.textContent = date?.value ? new Date(date.value).toLocaleString('fr-FR', { dateStyle: 'medium', timeStyle: 'short' }) : 'Date à définir';
      }
      if (output.duration) output.duration.textContent = duration?.selectedOptions[0]?.textContent || 'Durée à définir';
    };

    [title, classSelect, date, duration].forEach((field) => field?.addEventListener('input', updateSummary));
    [classSelect, duration].forEach((field) => field?.addEventListener('change', updateSummary));
    updateSummary();
  }

  const exam = document.querySelector('[data-exam]');
  if (exam) {
    const completed = exam.dataset.completed === 'true';
    const timer = exam.querySelector('[data-countdown]');
    const timerCard = exam.querySelector('[data-timer-card]');
    const status = exam.querySelector('[data-timer-status]');
    const initialRemaining = Math.max(0, Number(exam.dataset.remaining || 0));
    const deadline = Date.now() + (initialRemaining * 1000);
    const submitButton = exam.querySelector('[data-submit-button]');
    let deadlineWarningShown = false;

    const tick = () => {
      const safeRemaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
      const hours = String(Math.floor(safeRemaining / 3600)).padStart(2, '0');
      const minutes = String(Math.floor((safeRemaining % 3600) / 60)).padStart(2, '0');
      const seconds = String(safeRemaining % 60).padStart(2, '0');
      if (timer) timer.textContent = `${hours}:${minutes}:${seconds}`;
      if (!completed) {
        timerCard?.classList.toggle('is-warning', safeRemaining <= 600 && safeRemaining > 300);
        timerCard?.classList.toggle('is-danger', safeRemaining <= 300);
        if (status) status.textContent = safeRemaining ? 'L’épreuve est en cours' : 'Le temps est écoulé';
        if (!deadlineWarningShown && safeRemaining > 0 && safeRemaining <= 300) {
          showToast('Il vous reste moins de 5 minutes pour envoyer votre copie.', 'warning');
          deadlineWarningShown = true;
        }
      }
      if (submitButton) submitButton.disabled = safeRemaining === 0;
      if (safeRemaining > 0) {
        window.setTimeout(tick, 1000);
      }
    };
    tick();
  }

  document.querySelectorAll('[data-current-date]').forEach((element) => {
    const now = new Date();
    element.dateTime = now.toISOString().slice(0, 10);
    element.textContent = now.toLocaleDateString('fr-FR', {
      weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
    });
  });
})();
