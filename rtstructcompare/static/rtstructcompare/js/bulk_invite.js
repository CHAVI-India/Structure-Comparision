/**
 * Bulk User Invite - Client-side Logic
 */

// ── Row management ─────────────────────────────────────────────────────────
function rowNumber(n) {
  return `<span class="row-number">${n}</span>`;
}

function makeRow(n, first='', last='', username='', email='') {
  const div = document.createElement('div');
  div.className = 'recipient-row';
  div.innerHTML = `
    ${rowNumber(n)}
    <input type="text"  name="first_name[]" placeholder="First Name" value="${first}" autocomplete="off">
    <input type="text"  name="last_name[]"  placeholder="Last Name"  value="${last}" autocomplete="off">
    <input type="text"  name="username[]"   placeholder="Username"   value="${username}" autocomplete="off">
    <input type="email" name="email[]"      placeholder="Email"      value="${email}" autocomplete="off">
    <button class="delete-row-btn" type="button" title="Remove row">🗑</button>
  `;
  div.querySelector('.delete-row-btn').addEventListener('click', () => {
    div.remove();
    renumberRows();
    updatePreview();
  });
  return div;
}

function renumberRows() {
  document.querySelectorAll('#recipient-rows .recipient-row').forEach((row, i) => {
    const numSpan = row.querySelector('.row-number');
    if (numSpan) numSpan.textContent = i + 1;
  });
}

function addRows(n) {
  const container = document.getElementById('recipient-rows');
  if (!container) return;
  const currentCount = container.querySelectorAll('.recipient-row').length;
  for (let i = 0; i < n; i++) {
    container.appendChild(makeRow(currentCount + i + 1));
  }
  renumberRows();
}

// ── Live Preview ────────────────────────────────────────────────────────────
const DEFAULT_PREVIEW = {
  name: 'Santam',
  username: '*******',
  password: '*******'
};

function updatePreview() {
  const subjectInput = document.getElementById('id-subject');
  const bodyInput = document.getElementById('id-body');
  const previewBox = document.getElementById('preview-box');
  
  if (!subjectInput || !bodyInput || !previewBox) return;

  const subject = subjectInput.value;
  const body    = bodyInput.value;

  // Get first real recipient first_name for preview
  const firstInput = document.querySelector('#recipient-rows input[name="first_name[]"]');
  const userFirst = firstInput ? firstInput.value : '';
  const firstName = userFirst || DEFAULT_PREVIEW.name;

  const userHandleInput = document.querySelector('#recipient-rows input[name="username[]"]');
  const previewUser = (userHandleInput && userHandleInput.value) || DEFAULT_PREVIEW.username;

  let rendered = `Subject: ${subject}\n\n`;
  rendered += `Dear Dr. ${firstName},\n\n`;
  rendered += body
    .replace(/\{name\}/g,     `Dr. ${firstName}`)
    .replace(/\{username\}/g, previewUser)
    .replace(/\{password\}/g, DEFAULT_PREVIEW.password);

  previewBox.textContent = rendered;
}

// ── Initialization ──────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  const recipientRows = document.getElementById('recipient-rows');
  const inviteForm = document.getElementById('invite-form');
  const testForm = document.getElementById('test-form');
  const btnAddRows = document.getElementById('btn-add-rows');
  const btnClearEmpty = document.getElementById('btn-clear-empty');
  const idSubjectInput = document.getElementById('id-subject');
  const idBodyInput = document.getElementById('id-body');

  // Add initial rows if empty
  if (recipientRows && recipientRows.querySelectorAll('.recipient-row').length === 0) {
    addRows(5);
  }

  // Row Controls
  if (btnAddRows) {
    btnAddRows.addEventListener('click', () => {
      const n = parseInt(document.getElementById('add-count').value, 10) || 5;
      addRows(n);
    });
  }

  if (btnClearEmpty) {
    btnClearEmpty.addEventListener('click', () => {
      document.querySelectorAll('#recipient-rows .recipient-row').forEach(row => {
        const inputs = row.querySelectorAll('input');
        if (!inputs[0].value.trim() && !inputs[1].value.trim()) {
          row.remove();
        }
      });
      renumberRows();
      updatePreview();
    });
  }

  // Static row deletion (for server-rendered rows)
  document.querySelectorAll('#recipient-rows .delete-row-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      btn.closest('.recipient-row').remove();
      renumberRows();
      updatePreview();
    });
  });

  // Listeners for Preview
  if (recipientRows) recipientRows.addEventListener('input', updatePreview);
  if (idSubjectInput) idSubjectInput.addEventListener('input', updatePreview);
  if (idBodyInput) idBodyInput.addEventListener('input', updatePreview);

  // Initial Preview
  updatePreview();

  // ── Form Submission ──
  if (inviteForm) {
    inviteForm.addEventListener('submit', function(e) {
      const rows = document.querySelectorAll('#recipient-rows .recipient-row');
      let hasValid = false;
      rows.forEach(row => {
        const inputs = row.querySelectorAll('input');
        if (inputs[0].value.trim() && inputs[1].value.trim()) hasValid = true;
      });

      if (!hasValid) {
        e.preventDefault();
        alert('Please enter at least one recipient name and email address.');
        return;
      }

      const btn  = document.getElementById('btn-submit');
      const icon = document.getElementById('btn-icon');
      const text = document.getElementById('btn-text');
      if (btn) btn.disabled = true;
      if (icon) icon.innerHTML = '<span class="spinner"></span>';
      if (text) text.textContent = 'Sending…';
    });
  }

  // ── Auto-hide alerts ────────────────────────────────────────────────────────
  const alerts = document.querySelectorAll('.status-auto-hide');
  alerts.forEach(alert => {
    setTimeout(() => {
      alert.style.opacity = '0';
      setTimeout(() => alert.remove(), 800);
    }, 8000);
  });

  // ── Test SMTP Connection ────────────────────────────────────────────────────
  if (testForm) {
    testForm.addEventListener('submit', async function(e) {
      e.preventDefault();
      const btn    = document.getElementById('btn-test');
      const icon   = document.getElementById('test-icon');
      const result = document.getElementById('test-result');

      if (!btn || !icon || !result) return;

      btn.disabled = true;
      icon.innerHTML = '<span class="spinner" style="width:14px;height:14px;border-width:2px;"></span>';
      result.style.display = 'none';
      result.style.opacity = '1';

      try {
        const resp = await fetch(this.action, {
          method: 'POST',
          headers: { 'X-CSRFToken': this.querySelector('[name=csrfmiddlewaretoken]').value },
        });
        const data = await resp.json();
        
        result.style.display = 'block';
        result.style.transition = 'opacity 0.8s ease-out';

        if (data.success) {
          result.className = 'test-result ok';
          result.innerHTML = `✅ <strong>Connection OK!</strong> — ${data.message} &nbsp;|&nbsp; Provider: <code>${data.provider}</code> &nbsp;|&nbsp; Host: <code>${data.host}</code>`;
        } else {
          result.className = 'test-result err';
          let html = `❌ <strong>${data.error}</strong>`;
          if (data.detail) html += `<br><small style="opacity:0.85;">Detail: ${data.detail}</small>`;
          if (data.fix)    html += `<br><small style="opacity:0.85;">💡 Fix: ${data.fix}</small>`;
          result.innerHTML = html;
        }

        setTimeout(() => {
          result.style.opacity = '0';
          setTimeout(() => { result.style.display = 'none'; }, 800);
        }, 10000);

      } catch(err) {
        result.style.display = 'block';
        result.className = 'test-result err';
        result.innerHTML = `❌ Network error: ${err.message}`;
      }
      
      btn.disabled = false;
      icon.textContent = '🔌';
    });
  }
});
