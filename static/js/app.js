(() => {
  const sidebar = document.querySelector('[data-sidebar]');
  const backdrop = document.querySelector('[data-sidebar-backdrop]');
  const menuToggle = document.querySelector('[data-menu-toggle]');
  const toast = document.querySelector('[data-toast]');

  const standaloneQuery = window.matchMedia('(display-mode: standalone)');
  const isStandalone = () => standaloneQuery.matches || window.navigator.standalone === true;
  document.documentElement.classList.toggle('is-standalone', isStandalone());

  if (navigator.windowControlsOverlay) {
    const updateWindowControlsOverlay = () => {
      document.documentElement.classList.toggle(
        'has-window-controls-overlay', navigator.windowControlsOverlay.visible,
      );
    };
    updateWindowControlsOverlay();
    navigator.windowControlsOverlay.addEventListener('geometrychange', updateWindowControlsOverlay);
  }

  let deferredInstallPrompt = null;
  const installSection = document.querySelector('[data-install-section]');
  const installButton = document.querySelector('[data-install-app]');
  const iosInstallHint = document.querySelector('[data-ios-install-hint]');
  const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent)
    || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

  const updateInstallUi = () => {
    const installed = isStandalone();
    document.documentElement.classList.toggle('is-standalone', installed);
    if (installSection) installSection.hidden = installed || (!deferredInstallPrompt && !isIos);
    if (installButton) installButton.hidden = installed || !deferredInstallPrompt;
    if (iosInstallHint) iosInstallHint.hidden = installed || !isIos || Boolean(deferredInstallPrompt);
  };

  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    deferredInstallPrompt = event;
    updateInstallUi();
  });
  window.addEventListener('appinstalled', () => {
    deferredInstallPrompt = null;
    updateInstallUi();
  });
  standaloneQuery.addEventListener?.('change', updateInstallUi);
  installButton?.addEventListener('click', async () => {
    if (!deferredInstallPrompt) return;
    deferredInstallPrompt.prompt();
    await deferredInstallPrompt.userChoice;
    deferredInstallPrompt = null;
    updateInstallUi();
  });
  updateInstallUi();

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/static/sw.js', { scope: '/' }).catch(() => {
        // ClasseXP remains fully usable when service workers are unavailable.
      });
    });
  }

  let toastTimeout;
  const showToast = (message) => {
    if (!toast) return;
    window.clearTimeout(toastTimeout);
    toast.textContent = message;
    toast.classList.add('is-visible');
    toastTimeout = window.setTimeout(() => toast.classList.remove('is-visible'), 1600);
  };

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
        showToast('Code copié');
      } catch {
        showToast(`Code : ${value}`);
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
    const initialRemaining = Math.max(0, Number(exam.dataset.remaining || 0));
    const deadline = Date.now() + (initialRemaining * 1000);
    const submitButton = exam.querySelector('[data-submit-button]');

    const tick = () => {
      const safeRemaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
      const hours = String(Math.floor(safeRemaining / 3600)).padStart(2, '0');
      const minutes = String(Math.floor((safeRemaining % 3600) / 60)).padStart(2, '0');
      const seconds = String(safeRemaining % 60).padStart(2, '0');
      if (timer) timer.textContent = `${hours}:${minutes}:${seconds}`;
      timerCard?.classList.toggle('is-warning', safeRemaining <= 600 && safeRemaining > 300);
      timerCard?.classList.toggle('is-danger', safeRemaining <= 300);
      if (status) status.textContent = safeRemaining ? 'L’épreuve est en cours' : 'Le temps est écoulé';
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
