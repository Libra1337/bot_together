(() => {
  'use strict';

  // Legacy forms use sibling labels. Associate only an unambiguous next control.
  let fieldSequence = 0;
  document.querySelectorAll('label:not([for])').forEach((label) => {
    if (label.querySelector('input, select, textarea, button')) return;
    const next = label.nextElementSibling;
    const control = next && (next.matches('input, select, textarea')
      ? next : (next.querySelectorAll('input, select, textarea').length === 1
        ? next.querySelector('input, select, textarea') : null));
    if (!control || control.type === 'hidden') return;
    if (!control.id) {
      do { fieldSequence += 1; control.id = `dashboard-field-${fieldSequence}`; }
      while (document.querySelectorAll(`#${control.id}`).length > 1);
    }
    label.htmlFor = control.id;
  });

  const toggle = document.querySelector('.mc-nav-toggle');
  const navigation = document.getElementById('dashboard-navigation');
  if (toggle && navigation) {
    const setOpen = (open) => {
      toggle.setAttribute('aria-expanded', String(open));
      navigation.classList.toggle('is-open', open);
      const marker = toggle.querySelector('span');
      if (marker) marker.textContent = open ? '−' : '＋';
    };
    toggle.addEventListener('click', () => setOpen(toggle.getAttribute('aria-expanded') !== 'true'));
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && toggle.getAttribute('aria-expanded') === 'true') {
        setOpen(false);
        toggle.focus();
      }
    });
    navigation.addEventListener('click', (event) => {
      if (event.target.closest('a')) setOpen(false);
    });
    window.matchMedia('(min-width: 900px)').addEventListener('change', (event) => {
      if (event.matches) setOpen(false);
    });
  }

  let pendingConfirmation = null;
  const dialog = document.createElement('dialog');
  dialog.className = 'confirm-dialog';
  dialog.setAttribute('aria-labelledby', 'confirmation-title');
  dialog.setAttribute('aria-describedby', 'confirmation-description');
  dialog.innerHTML = '<h2 id="confirmation-title">确认此操作</h2><p id="confirmation-description"></p><div class="actions"><button type="button" class="ghost" data-dialog-cancel autofocus>取消</button><button type="button" class="danger" data-dialog-confirm>确认操作</button></div>';
  document.body.appendChild(dialog);
  const cancelButton = dialog.querySelector('[data-dialog-cancel]');
  const confirmButton = dialog.querySelector('[data-dialog-confirm]');
  cancelButton.addEventListener('click', () => dialog.close('cancel'));
  confirmButton.addEventListener('click', () => dialog.close('confirm'));
  dialog.addEventListener('cancel', () => { dialog.returnValue = 'cancel'; });
  dialog.addEventListener('close', () => {
    const pending = pendingConfirmation;
    pendingConfirmation = null;
    if (!pending) return;
    if (dialog.returnValue === 'confirm' && pending.form.isConnected) {
      pending.form.dataset.confirmed = 'true';
      if (pending.submitter && pending.submitter.isConnected) pending.form.requestSubmit(pending.submitter);
      else pending.form.requestSubmit();
      delete pending.form.dataset.confirmed;
    } else if (pending.submitter && pending.submitter.isConnected) {
      pending.submitter.focus();
    }
  });

  document.addEventListener('submit', (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || event.defaultPrevented) return;
    const submitter = event.submitter;
    const confirmation = (submitter && submitter.dataset.confirm) || form.dataset.confirm;
    if (confirmation && form.dataset.confirmed !== 'true') {
      event.preventDefault();
      if (pendingConfirmation) return;
      pendingConfirmation = { form, submitter };
      dialog.querySelector('#confirmation-description').textContent = confirmation;
      dialog.returnValue = 'cancel';
      dialog.showModal();
      cancelButton.focus();
      return;
    }
    delete form.dataset.confirmed;
    if (!form.classList.contains('ai-form')) return;
    if (form.getAttribute('aria-busy') === 'true') {
      event.preventDefault();
      return;
    }
    form.setAttribute('aria-busy', 'true');
    // Keep the submitter enabled: its name/value and formaction must be submitted.
    if (submitter && submitter.tagName === 'BUTTON') {
      submitter.dataset.originalLabel = submitter.textContent;
      submitter.textContent = /保存/.test(submitter.textContent) ? '正在保存…' : '正在处理…';
      submitter.setAttribute('aria-disabled', 'true');
    }
    const state = document.createElement('p');
    state.className = 'field-note';
    state.dataset.submissionStatus = 'true';
    state.setAttribute('role', 'status');
    state.textContent = '请求正在处理中，请稍候。';
    form.appendChild(state);
  });

  window.addEventListener('pageshow', () => {
    document.querySelectorAll('.ai-form[aria-busy="true"]').forEach((form) => {
      form.removeAttribute('aria-busy');
      form.querySelectorAll('[data-original-label]').forEach((button) => {
        button.textContent = button.dataset.originalLabel;
        button.removeAttribute('aria-disabled');
        delete button.dataset.originalLabel;
      });
      form.querySelectorAll('[data-submission-status]').forEach((status) => status.remove());
    });
  });
})();
