(() => {
  const sidebar = document.querySelector('[data-sidebar]');
  const backdrop = document.querySelector('[data-sidebar-backdrop]');
  const menuToggle = document.querySelector('[data-menu-toggle]');

  const setMenuState = (open) => {
    sidebar?.classList.toggle('is-open', open);
    backdrop?.classList.toggle('is-visible', open);
    menuToggle?.setAttribute('aria-expanded', String(open));
  };

  menuToggle?.addEventListener('click', () => {
    setMenuState(!sidebar?.classList.contains('is-open'));
  });
  backdrop?.addEventListener('click', () => setMenuState(false));
  sidebar?.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => setMenuState(false)));

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
        await navigator.clipboard.writeText(value);
        const original = button.textContent;
        button.textContent = 'Copié';
        window.setTimeout(() => { button.textContent = original; }, 1400);
      } catch {
        button.textContent = value;
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
    const timer = exam.querySelector('[data-countdown]');
    const timerCard = exam.querySelector('[data-timer-card]');
    const status = exam.querySelector('[data-timer-status]');
    let remaining = Number(exam.dataset.remaining || 0);

    const tick = () => {
      const safeRemaining = Math.max(0, remaining);
      const hours = String(Math.floor(safeRemaining / 3600)).padStart(2, '0');
      const minutes = String(Math.floor((safeRemaining % 3600) / 60)).padStart(2, '0');
      const seconds = String(safeRemaining % 60).padStart(2, '0');
      if (timer) timer.textContent = `${hours}:${minutes}:${seconds}`;
      timerCard?.classList.toggle('is-warning', safeRemaining <= 600 && safeRemaining > 300);
      timerCard?.classList.toggle('is-danger', safeRemaining <= 300);
      if (status) status.textContent = safeRemaining ? 'L’épreuve est en cours' : 'Le temps est écoulé';
      if (remaining > 0) {
        remaining -= 1;
        window.setTimeout(tick, 1000);
      }
    };
    tick();
  }
})();
