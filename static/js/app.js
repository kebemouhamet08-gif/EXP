(() => {
  const sidebar = document.querySelector('[data-sidebar]');
  const backdrop = document.querySelector('[data-sidebar-backdrop]');
  const menuToggle = document.querySelector('[data-menu-toggle]');
  const toastRegion = document.querySelector('[data-toast-region]');

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

  const toastSymbols = { success: '✓', error: '×', warning: '!', info: 'i' };
  const removeToast = (toast) => {
    if (!toast || toast.classList.contains('is-leaving')) return;
    toast.classList.add('is-leaving');
    window.setTimeout(() => toast.remove(), 200);
  };

  const scheduleToastRemoval = (toast, duration = 4600) => {
    if (!duration) return;
    let timeout = window.setTimeout(() => removeToast(toast), duration);
    toast.addEventListener('mouseenter', () => window.clearTimeout(timeout));
    toast.addEventListener('mouseleave', () => {
      timeout = window.setTimeout(() => removeToast(toast), 1200);
    });
  };

  const showToast = (message, type = 'info', duration = 4600) => {
    if (!toastRegion) return null;
    const kind = Object.hasOwn(toastSymbols, type) ? type : 'info';
    const toast = document.createElement('article');
    toast.className = `toast toast--${kind} is-visible`;
    toast.dataset.toast = '';
    toast.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    toast.setAttribute('aria-live', kind === 'error' ? 'assertive' : 'polite');
    toast.setAttribute('aria-atomic', 'true');

    const icon = document.createElement('span');
    icon.className = 'toast-icon';
    icon.setAttribute('aria-hidden', 'true');
    const symbol = document.createElement('span');
    symbol.textContent = toastSymbols[kind];
    icon.appendChild(symbol);

    const copy = document.createElement('p');
    copy.textContent = message;
    const close = document.createElement('button');
    close.className = 'toast-close';
    close.type = 'button';
    close.dataset.toastClose = '';
    close.setAttribute('aria-label', 'Fermer la notification');
    close.textContent = '×';
    toast.append(icon, copy, close);
    toastRegion.appendChild(toast);
    scheduleToastRemoval(toast, duration);
    return toast;
  };

  toastRegion?.addEventListener('click', (event) => {
    const close = event.target.closest('[data-toast-close]');
    if (close) removeToast(close.closest('[data-toast]'));
  });
  toastRegion?.querySelectorAll('[data-auto-dismiss]').forEach((toast) => scheduleToastRemoval(toast));
  window.ClasseXPFeedback = Object.freeze({ showToast });

  try {
    const pendingFeedback = JSON.parse(sessionStorage.getItem('classexp-feedback'));
    if (pendingFeedback?.message) showToast(pendingFeedback.message, pendingFeedback.type);
    sessionStorage.removeItem('classexp-feedback');
  } catch {
    // Storage can be unavailable in hardened privacy modes.
  }

  window.addEventListener('offline', () => showToast('Hors connexion.', 'warning', 0));
  window.addEventListener('online', () => showToast('Connexion rétablie.', 'info'));
  if (!navigator.onLine) showToast('Hors connexion.', 'warning', 0);

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

  const validationMessage = (input) => {
    if (input.validity.valueMissing) return 'Ce champ est obligatoire.';
    if (input.validity.typeMismatch && input.type === 'email') return 'Adresse e-mail invalide.';
    if (input.validity.tooShort) return `${input.minLength} caractères minimum.`;
    if (input.validity.rangeUnderflow || input.validity.rangeOverflow) {
      return `La valeur doit être comprise entre ${input.min} et ${input.max}.`;
    }
    if (input.validity.badInput || input.validity.patternMismatch) return 'Vérifiez la valeur saisie.';
    return '';
  };

  const renderFieldValidation = (input, force = false) => {
    const field = input.closest('.form-field');
    if (!field || input.type === 'hidden') return;
    const hasValue = input.type === 'file' ? Boolean(input.files?.length) : Boolean(input.value.trim());
    const showError = !input.validity.valid && (force || input.dataset.validationTouched === 'true');
    field.classList.toggle('has-error', showError);
    field.classList.toggle('has-success', input.validity.valid && hasValue);
    input.setAttribute('aria-invalid', String(showError));

    let message = field.querySelector('.form-validation-message');
    if (showError) {
      if (!message) {
        message = document.createElement('p');
        message.className = 'form-validation-message';
        message.setAttribute('aria-live', 'polite');
        field.appendChild(message);
      }
      message.textContent = validationMessage(input);
    } else {
      message?.remove();
    }
  };

  document.querySelectorAll('input, select, textarea').forEach((input) => {
    if (input.type === 'hidden' || input.type === 'radio' || input.type === 'checkbox') return;
    input.addEventListener('blur', () => {
      input.dataset.validationTouched = 'true';
      renderFieldValidation(input, true);
    });
    input.addEventListener('input', () => {
      if (input.dataset.validationTouched === 'true') renderFieldValidation(input);
    });
    input.addEventListener('change', () => {
      if (input.dataset.validationTouched === 'true') renderFieldValidation(input);
    });
  });

  document.querySelectorAll('form').forEach((form) => {
    form.addEventListener('invalid', (event) => {
      const input = event.target;
      input.dataset.validationTouched = 'true';
      renderFieldValidation(input, true);
      if (!form.dataset.invalidNotified) {
        form.dataset.invalidNotified = 'true';
        showToast('Vérifiez les champs signalés.', 'error');
        window.setTimeout(() => delete form.dataset.invalidNotified, 100);
      }
    }, true);
  });

  const passwordWithRules = document.querySelector('[data-password-rules]');
  const passwordCriteria = document.querySelector('[data-password-criteria]');
  const passwordLengthRule = passwordCriteria?.querySelector('[data-minlength-rule]');
  const updatePasswordCriteria = () => {
    if (!passwordWithRules || !passwordCriteria || !passwordLengthRule) return;
    const started = passwordWithRules.value.length > 0;
    const met = passwordWithRules.value.length >= 8;
    passwordCriteria.hidden = !started;
    passwordLengthRule.classList.toggle('is-met', met);
    const indicator = passwordLengthRule.querySelector('span');
    if (indicator) indicator.textContent = met ? '✓' : '○';
  };
  passwordWithRules?.addEventListener('input', updatePasswordCriteria);
  updatePasswordCriteria();

  const setLoadingState = (control, loadingText) => {
    if (!control || control.classList.contains('is-loading')) return false;
    control.dataset.originalHtml = control.innerHTML;
    control.style.minWidth = `${Math.ceil(control.getBoundingClientRect().width)}px`;
    control.classList.add('is-loading');
    control.setAttribute('aria-disabled', 'true');
    if ('disabled' in control) control.disabled = true;
    const spinner = document.createElement('span');
    spinner.className = 'spinner';
    spinner.setAttribute('aria-hidden', 'true');
    const label = document.createElement('span');
    label.textContent = loadingText || 'Envoi en cours…';
    control.replaceChildren(spinner, label);
    return true;
  };

  const restoreLoadingControls = () => {
    document.querySelectorAll('.is-loading[data-original-html]').forEach((control) => {
      control.innerHTML = control.dataset.originalHtml;
      delete control.dataset.originalHtml;
      control.style.minWidth = '';
      control.classList.remove('is-loading');
      control.removeAttribute('aria-disabled');
      if ('disabled' in control) control.disabled = false;
    });
    document.querySelectorAll('[data-dropzone].is-uploading').forEach((zone) => {
      zone.classList.remove('is-uploading');
      const file = zone.querySelector('[data-file-input]')?.files?.[0];
      const filename = zone.querySelector('[data-file-name]');
      if (file && filename) filename.textContent = `${file.name} · Prêt à envoyer`;
    });
  };

  document.querySelectorAll('form[data-action-feedback]').forEach((form) => {
    form.addEventListener('submit', (event) => {
      if (event.defaultPrevented || !form.checkValidity()) return;
      if (!navigator.onLine) {
        event.preventDefault();
        const message = form.matches('[data-upload-form]')
          ? 'Connexion Internet requise pour envoyer votre fichier.'
          : 'Connexion Internet requise pour effectuer cette action.';
        showToast(message, 'error', 0);
        return;
      }

      const submitter = event.submitter || form.querySelector('[type="submit"]');
      if (submitter?.classList.contains('is-loading')) {
        event.preventDefault();
        return;
      }
      setLoadingState(submitter, submitter?.dataset.loadingText);
      if (form.matches('[data-upload-form]')) {
        form.querySelectorAll('[data-file-name]').forEach((filename) => {
          const zone = filename.closest('[data-dropzone]');
          const input = zone?.querySelector('[data-file-input]');
          const file = input?.files?.[0];
          if (file) {
            zone.classList.add('is-uploading');
            filename.textContent = `${file.name} · Envoi…`;
          }
        });
      }
    });
  });

  document.querySelectorAll('[data-oauth-provider]').forEach((link) => {
    link.addEventListener('click', (event) => {
      if (!navigator.onLine) {
        event.preventDefault();
        showToast(`Connexion Internet requise pour ouvrir ${link.dataset.oauthProvider}.`, 'error', 0);
        return;
      }
      setLoadingState(link, link.dataset.loadingText);
    });
  });

  window.addEventListener('pageshow', restoreLoadingControls);

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
        showToast('Code copié.', 'success');
      } catch {
        showToast(`Copie impossible. Code : ${value}`, 'error');
      }
    });
  });

  document.querySelectorAll('[data-dropzone]').forEach((zone) => {
    const input = zone.querySelector('[data-file-input]');
    const filename = zone.querySelector('[data-file-name]');
    if (!input) return;

    const updateFile = (file) => {
      if (!file) return;
      filename && (filename.textContent = `${file.name} · Prêt à envoyer`);
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
    let fiveMinuteWarningShown = false;

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
      if (safeRemaining <= 300 && safeRemaining > 0 && !fiveMinuteWarningShown) {
        fiveMinuteWarningShown = true;
        showToast('Il vous reste 5 minutes.', 'warning');
      }
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

  document.querySelectorAll('form[data-confirm]').forEach((form) => {
    form.addEventListener('submit', (event) => {
      if (form.dataset.confirmed === '1') return;
      event.preventDefault();
      const dialog = document.createElement('dialog');
      dialog.className = 'confirm-dialog';
      const message = document.createElement('p');
      message.textContent = form.dataset.confirm || 'Confirmer cette action ?';
      const cancel = document.createElement('button'); cancel.type = 'button'; cancel.textContent = 'Annuler';
      const confirm = document.createElement('button'); confirm.type = 'button'; confirm.textContent = 'Confirmer'; confirm.className = 'button button-danger';
      dialog.append(message, cancel, confirm); document.body.append(dialog);
      cancel.addEventListener('click', () => { dialog.close(); dialog.remove(); });
      confirm.addEventListener('click', () => { form.dataset.confirmed = '1'; dialog.close(); dialog.remove(); form.requestSubmit(); });
      dialog.showModal(); cancel.focus();
    });
  });
})();
