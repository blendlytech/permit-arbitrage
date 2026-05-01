/* Permit Arbitrage — Dashboard JS */
'use strict';

// ── State ──────────────────────────────────────────────────────────
let _prospects   = [];   // full list from API
let _edits       = {};   // { email -> { subject, body } } user edits
let _activeEmail = null; // currently selected prospect email
let _pollTimer   = null;

// ── DOM refs ───────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const fileSelect     = $('fileSelect');
const countyInput    = $('countyInput');
const templateSelect = $('templateSelect');
const senderInput    = $('senderInput');
const delayInput     = $('delayInput');
const loadBtn        = $('loadBtn');
const prospectList   = $('prospectList');
const editorTitle    = $('editorTitle');
const editorBody     = $('editorBody');
const sendBtn        = $('sendBtn');
const abortBtn       = $('abortBtn');
const statusDot      = $('statusDot');
const statusLabel    = $('statusLabel');
const progressBar    = $('progressBar');
const progressLabel  = $('progressLabel');
const confirmModal   = $('confirmModal');
const modalBody      = $('modalBody');
const confirmSendBtn = $('confirmSendBtn');
const cancelSendBtn  = $('cancelSendBtn');
const resetEmailBtn  = $('resetEmailBtn');
const selectAllBtn   = $('selectAllBtn');
const deselectAllBtn = $('deselectAllBtn');

// ── Stats helpers ──────────────────────────────────────────────────
function setStats({ total, selected, sent, failed, permits }) {
  $('statTotal').textContent    = total    ?? '—';
  $('statSelected').textContent = selected ?? '—';
  $('statSent').textContent     = sent     ?? '—';
  $('statFailed').textContent   = failed   ?? '—';
  $('statPermits').textContent  = permits  ?? '—';
}

// ── Load prospect files into dropdown ─────────────────────────────
async function loadFileList() {
  const res   = await fetch('/api/prospect-files');
  const files = await res.json();
  fileSelect.innerHTML = '';
  if (!files.length) {
    fileSelect.innerHTML = '<option>No prospect files found</option>';
    return;
  }
  files.forEach(f => {
    const opt = document.createElement('option');
    opt.value = f; opt.textContent = f.replace('Prospects_List_', '').replace('.csv', '').replace(/_/g,' ');
    fileSelect.appendChild(opt);
  });
}

// ── Load & render prospects ────────────────────────────────────────
async function loadProspects() {
  loadBtn.textContent = '⟳ Loading…';
  loadBtn.disabled    = true;
  _edits = {};
  _activeEmail = null;
  renderEditor(null);

  const params = new URLSearchParams({
    file:     fileSelect.value,
    county:   countyInput.value.trim(),
    template: templateSelect.value,
    sender:   senderInput.value.trim(),
  });

  try {
    const res  = await fetch(`/api/prospects?${params}`);
    const data = await res.json();
    if (data.error) { alert(data.error); return; }

    _prospects = data.prospects;
    setStats({ total: _prospects.length, selected: _prospects.filter(p=>!p.already_sent).length, sent: '—', failed: '—', permits: data.permit_count });
    renderProspectList();
    sendBtn.disabled = _prospects.filter(p=>!p.already_sent).length === 0;
  } finally {
    loadBtn.textContent = '⟳ Load Preview';
    loadBtn.disabled    = false;
  }
}

// ── Render left panel list ─────────────────────────────────────────
function renderProspectList() {
  prospectList.innerHTML = '';
  if (!_prospects.length) {
    prospectList.innerHTML = '<div class="empty-state">No valid prospects found.</div>';
    return;
  }

  _prospects.forEach(p => {
    const item    = document.createElement('div');
    const niche   = (p.niche || '').toLowerCase();
    const nicheClass = niche.includes('pool') ? 'niche-pool' : niche.includes('roof') ? 'niche-roofing' : 'niche-other';

    item.className = `prospect-item${p.already_sent ? ' sent-badge' : ''}`;
    item.dataset.email = p.email;
    if (p.email === _activeEmail) item.classList.add('active');

    item.innerHTML = `
      <div class="prospect-check">
        <input type="checkbox" data-email="${p.email}" ${p.already_sent ? 'disabled title="Already sent"' : 'checked'} />
      </div>
      <div class="prospect-info">
        <div class="prospect-name">${esc(p.business || p.email)}</div>
        <div class="prospect-meta">${esc(p.email)}</div>
      </div>
      <span class="niche-badge ${nicheClass}">${esc(p.niche || '?')}</span>
      ${p.already_sent ? '<span class="sent-tag">Sent</span>' : ''}
    `;

    item.addEventListener('click', e => {
      if (e.target.type === 'checkbox') return;
      selectProspect(p.email);
    });

    prospectList.appendChild(item);
  });

  updateSelectedCount();
}

// ── Select a prospect in the list ─────────────────────────────────
function selectProspect(email) {
  // Save current edit before switching
  if (_activeEmail) saveCurrentEdit();

  _activeEmail = email;

  // Update active state
  document.querySelectorAll('.prospect-item').forEach(el => {
    el.classList.toggle('active', el.dataset.email === email);
  });

  const p = _prospects.find(x => x.email === email);
  renderEditor(p);
}

// ── Render email editor ────────────────────────────────────────────
function renderEditor(p) {
  if (!p) {
    editorTitle.textContent = 'Email Editor';
    editorBody.innerHTML = '<div class="empty-state">Select a prospect to preview or edit their email.</div>';
    resetEmailBtn.disabled = true;
    return;
  }

  editorTitle.textContent = p.business || p.email;
  resetEmailBtn.disabled = false;

  const edit    = _edits[p.email] || {};
  const subject = edit.subject ?? p.subject;
  const body    = edit.body    ?? p.body;

  editorBody.innerHTML = `
    <div class="editor-fields">
      <div class="editor-row">
        <label>To</label>
        <span class="meta-val">${esc(p.email)}</span>
      </div>
      <div class="editor-row">
        <label>Business</label>
        <span class="meta-val">${esc(p.business)} — ${esc(p.niche)}${p.phone ? ' — '+esc(p.phone) : ''}</span>
      </div>
      <div class="editor-row">
        <label>Subject</label>
        <input id="edSubject" type="text" value="${esc(subject)}" placeholder="Email subject line..." />
      </div>
      <div class="editor-body-row">
        <label>Body</label>
        <textarea id="edBody" class="editor-textarea" spellcheck="true">${esc(body)}</textarea>
      </div>
    </div>
  `;

  // Live-save on input
  $('edSubject').addEventListener('input', saveCurrentEdit);
  $('edBody').addEventListener('input', saveCurrentEdit);
}

// ── Save current editor content to _edits ─────────────────────────
function saveCurrentEdit() {
  if (!_activeEmail) return;
  const subjectEl = $('edSubject');
  const bodyEl    = $('edBody');
  if (!subjectEl || !bodyEl) return;
  _edits[_activeEmail] = { subject: subjectEl.value, body: bodyEl.value };
}

// ── Reset current email to template default ────────────────────────
resetEmailBtn.addEventListener('click', () => {
  if (!_activeEmail) return;
  delete _edits[_activeEmail];
  const p = _prospects.find(x => x.email === _activeEmail);
  renderEditor(p);
});

// ── Select / Deselect all checkboxes ──────────────────────────────
selectAllBtn.addEventListener('click', () => {
  document.querySelectorAll('.prospect-list input[type=checkbox]:not(:disabled)').forEach(cb => cb.checked = true);
  updateSelectedCount();
});
deselectAllBtn.addEventListener('click', () => {
  document.querySelectorAll('.prospect-list input[type=checkbox]:not(:disabled)').forEach(cb => cb.checked = false);
  updateSelectedCount();
});
prospectList.addEventListener('change', updateSelectedCount);

function updateSelectedCount() {
  const selected = document.querySelectorAll('.prospect-list input[type=checkbox]:checked:not(:disabled)').length;
  $('statSelected').textContent = selected;
  sendBtn.disabled = selected === 0;
}

// ── Build the batch to send (merging edits) ────────────────────────
function buildBatch() {
  saveCurrentEdit();
  const checked = new Set([...document.querySelectorAll('.prospect-list input[type=checkbox]:checked:not(:disabled)')].map(cb => cb.dataset.email));
  return _prospects
    .filter(p => checked.has(p.email) && !p.already_sent)
    .map(p => ({
      email:    p.email,
      business: p.business,
      niche:    p.niche,
      subject:  (_edits[p.email]?.subject ?? p.subject),
      body:     (_edits[p.email]?.body    ?? p.body),
    }));
}

// ── Send button → show confirm modal ─────────────────────────────
sendBtn.addEventListener('click', () => {
  const batch = buildBatch();
  if (!batch.length) { alert('No prospects selected.'); return; }
  modalBody.textContent = `You are about to send ${batch.length} cold email${batch.length > 1 ? 's' : ''} to real contractors. This action cannot be undone.`;
  confirmModal.classList.add('open');
});

cancelSendBtn.addEventListener('click', () => confirmModal.classList.remove('open'));
confirmModal.addEventListener('click', e => { if (e.target === confirmModal) confirmModal.classList.remove('open'); });

// ── Confirmed: fire send ───────────────────────────────────────────
confirmSendBtn.addEventListener('click', async () => {
  confirmModal.classList.remove('open');
  const batch = buildBatch();
  if (!batch.length) return;

  const delay = parseInt(delayInput.value) || 45;
  const res   = await fetch('/api/send', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ batch, delay }),
  });
  const data = await res.json();
  if (data.error) { alert('Send error: ' + data.error); return; }

  sendBtn.disabled  = true;
  abortBtn.disabled = false;
  startPolling();
});

// ── Abort ─────────────────────────────────────────────────────────
abortBtn.addEventListener('click', async () => {
  await fetch('/api/abort', { method: 'POST' });
});

// ── Poll send status ───────────────────────────────────────────────
function startPolling() {
  if (_pollTimer) clearInterval(_pollTimer);
  _pollTimer = setInterval(pollStatus, 1500);
}

async function pollStatus() {
  const res  = await fetch('/api/send-status');
  const data = await res.json();

  const { status, total, sent, failed, progress } = data;

  // Update status indicator
  statusDot.className   = `status-dot ${status}`;
  statusLabel.textContent = status.charAt(0).toUpperCase() + status.slice(1);

  // Update stats
  setStats({ total: _prospects.length, selected: $('statSelected').textContent, sent, failed, permits: $('statPermits').textContent });

  // Progress bar
  const pct = total > 0 ? Math.round(((sent + failed) / total) * 100) : 0;
  progressBar.style.width = pct + '%';
  progressLabel.textContent = total > 0 ? `${sent + failed} of ${total} processed (${pct}%)` : 'Ready';

  // Mark sent items in the prospect list
  (progress || []).forEach(entry => {
    const item = document.querySelector(`.prospect-item[data-email="${CSS.escape(entry.email)}"]`);
    if (item && entry.status === 'sent') {
      item.classList.add('sent-badge');
      const cb = item.querySelector('input[type=checkbox]');
      if (cb) { cb.checked = false; cb.disabled = true; }
      if (!item.querySelector('.sent-tag')) {
        const tag = document.createElement('span');
        tag.className = 'sent-tag'; tag.textContent = 'Sent';
        item.appendChild(tag);
      }
    }
  });

  if (status === 'done' || status === 'aborted') {
    clearInterval(_pollTimer);
    abortBtn.disabled = true;
    sendBtn.disabled  = false;
    progressLabel.textContent = status === 'done'
      ? `Campaign complete — ${sent} sent, ${failed} failed.`
      : `Aborted — ${sent} sent before stop.`;
  }
}

// ── Escape HTML ────────────────────────────────────────────────────
function esc(str) {
  return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Init ───────────────────────────────────────────────────────────
(async () => {
  await loadFileList();
  await loadProspects();
  loadBtn.addEventListener('click', loadProspects);
  // Template/county/sender changes auto-reload preview
  [templateSelect, countyInput, senderInput].forEach(el => {
    el.addEventListener('change', loadProspects);
  });
})();
