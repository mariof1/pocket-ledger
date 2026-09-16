const $ = (selector) => document.querySelector(selector);
const localDate = () => { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`; };
const state = { bootstrap: null, data: null, transactions: null, statementHistory: [], statement: null, txOffset: 0, txRequest: 0, page: 'dashboard', month: localDate().slice(0, 7), filter: '', kind: 'all', accountFilter: '', calc: 'mortgage', mortgageView: 'payments', mortgageInputs: {}, authMode: 'login' };
const pages = { dashboard: 'Overview', transactions: 'Transactions', accounts: 'Accounts', budgets: 'Budgets', goals: 'Savings goals', bills: 'Regular bills', calculators: 'Calculators', settings: 'Profiles & settings' };
const expenseCategories = ['Housing','Groceries','Transport','Utilities','Eating out','Shopping','Entertainment','Health','Travel','Education','Other'];
const incomeCategories = ['Salary','Freelance','Investment','Gift','Other'];
const billFrequencies = [
  ['daily', 'Daily', 365, 12], ['weekly', 'Weekly', 52, 12],
  ['biweekly', 'Every 2 weeks', 26, 12], ['fourweekly', 'Every 4 weeks', 13, 12],
  ['monthly', 'Monthly', 1, 1], ['quarterly', 'Every 3 months', 1, 3],
  ['yearly', 'Yearly', 1, 12],
];
const billFrequencyLabel = frequency => billFrequencies.find(([value]) => value === frequency)?.[1] || 'Monthly';
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const currency = () => state.data?.profile?.currency || 'GBP';
const fmt = cents => new Intl.NumberFormat('en-GB', { style: 'currency', currency: currency(), maximumFractionDigits: 2 }).format((Number(cents) || 0) / 100);
const shortDate = value => new Date(`${value}T12:00:00`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
const monthLabel = value => new Date(`${value}-01T12:00:00`).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
const sum = (items, field = 'amount_cents') => items.reduce((total, item) => total + Number(item[field] || 0), 0);
const el = (html) => { const template = document.createElement('template'); template.innerHTML = html; return template.content; };

async function api(path, options = {}) {
  const response = await fetch(path, { credentials: 'same-origin', ...options, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': state.bootstrap?.csrf || '', ...(options.headers || {}) } });
  const body = await response.json().catch(() => ({}));
  if (response.status === 401 && path !== '/api/bootstrap') {
    state.data = null; state.transactions = null;
    await boot();
  }
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
  return body;
}
async function boot() {
  state.bootstrap = await api('/api/bootstrap');
  const signedIn = Boolean(state.bootstrap.user);
  $('#auth').classList.toggle('hidden', signedIn);
  $('#app').classList.toggle('hidden', !signedIn);
  if (signedIn) {
    $('#user-email').textContent = state.bootstrap.user.email;
    $('#user-avatar').textContent = state.bootstrap.user.email.charAt(0).toUpperCase();
    $('#today-label').textContent = new Date().toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
    await loadData();
    syncMenu();
  } else {
    state.data = null; state.transactions = null; closeMenu();
    const directory = Boolean(state.bootstrap.auth?.ldap);
    const registration = state.bootstrap.auth?.registration !== false;
    if (!registration && state.authMode === 'register') { state.authMode = 'login'; switchAuth(true); }
    $('#auth-identifier-label').textContent = directory ? 'Email or AD username' : 'Email address';
    $('#auth-identifier').type = state.authMode === 'register' || !directory ? 'email' : 'text';
    $('#auth-identifier').placeholder = directory && state.authMode === 'login' ? 'you@example.com or username' : 'you@example.com';
    $('#auth-switch').classList.toggle('hidden', !registration);
    $('#auth-footnote').textContent = directory
      ? 'Active Directory verifies directory passwords. Financial data stays in this server database.'
      : "Your data stays in this server's private database.";
  }
}
async function loadData() {
  state.data = await api(`/api/data?month=${encodeURIComponent(state.month)}`);
  if (state.accountFilter && !state.data.accounts.some(item => String(item.id) === state.accountFilter)) { state.accountFilter = ''; state.txOffset = 0; }
  $('#sidebar-profile').textContent = state.data.profile.name;
  $('#profile-avatar').textContent = state.data.profile.name.charAt(0).toUpperCase();
  if (state.page === 'transactions') await loadTransactions(); else render();
}
async function loadTransactions() {
  const requestId = ++state.txRequest;
  const requestedFilter = state.filter, requestedKind = state.kind, requestedAccount = state.accountFilter;
  let query = new URLSearchParams({ offset: String(state.txOffset), kind: state.kind, search: state.filter, account_id: state.accountFilter });
  let listing = await api(`/api/transactions?${query}`);
  if (requestId !== state.txRequest || state.page !== 'transactions' || requestedFilter !== state.filter || requestedKind !== state.kind || requestedAccount !== state.accountFilter) return;
  state.transactions = listing;
  state.statementHistory = (await api('/api/statements/history')).batches;
  if (state.txOffset > 0 && state.txOffset >= state.transactions.total) {
    state.txOffset = Math.max(0, Math.floor((state.transactions.total - 1) / 50) * 50);
    query = new URLSearchParams({ offset: String(state.txOffset), kind: state.kind, search: state.filter, account_id: state.accountFilter });
    listing = await api(`/api/transactions?${query}`);
    if (requestId !== state.txRequest || state.page !== 'transactions' || requestedFilter !== state.filter || requestedKind !== state.kind || requestedAccount !== state.accountFilter) return;
    state.transactions = listing;
  }
  const searching = document.activeElement?.id === 'transaction-search';
  const cursor = searching ? document.activeElement.selectionStart : 0;
  render();
  if (searching && state.page === 'transactions') {
    const input = $('#transaction-search'); input.focus(); input.setSelectionRange(cursor, cursor);
  }
}
function toast(message) {
  const node = $('#toast'); node.textContent = message; node.classList.remove('hidden');
  clearTimeout(toast.timer); toast.timer = setTimeout(() => node.classList.add('hidden'), 3400);
}
function showError(error) { toast(error.message || String(error)); }
function clearFormError(form) {
  const summary = form.querySelector('.form-error');
  if (summary) summary.classList.add('hidden');
  form.querySelectorAll('.statement-row-error').forEach(row => row.classList.remove('statement-row-error'));
  form.querySelectorAll('[aria-invalid="true"]').forEach(field => {
    field.removeAttribute('aria-invalid');
    if ('errorPriorDescription' in field.dataset) {
      if (field.dataset.errorPriorDescription) field.setAttribute('aria-describedby', field.dataset.errorPriorDescription);
      else field.removeAttribute('aria-describedby');
      delete field.dataset.errorPriorDescription;
    }
  });
}
function showFormError(form, error) {
  if (!form) return showError(error);
  const message = error.message || String(error);
  const rowNumber = /^Row (\d+)(?::|\b)/.exec(message)?.[1];
  const detail = message.replace(/^Row \d+:\s*/, '');
  let summary = form.querySelector('.form-error');
  if (!summary) {
    summary = document.createElement('div');
    summary.id = `form-error-${form.id}`;
    summary.className = 'form-error';
    summary.setAttribute('role', 'alert');
    summary.tabIndex = -1;
    form.prepend(summary);
  }
  clearFormError(form);
  summary.textContent = message;
  summary.classList.remove('hidden');
  const labels = [
    [/^New passwords do not match/, 'confirm_password'], [/^Current password/, 'current_password'],
    [/^New password/, 'new_password'], [/^Bill day/, 'day_of_month'],
    [/^First payment date/, 'first_due_on'], [/^Target date/, 'target_date'],
    [/^Monthly contribution/, 'monthly'], [/^Daily round-trip/, 'distance'],
    [/^UK miles per gallon/, 'mpg'], [/^Fuel price/, 'fuel_price'],
    [/^Daily return fare/, 'fare'], [/^Annual leave days/, 'annual_leave_days'],
    [/^Dates off|^Excluded dates/, 'excluded_dates'],
    [/^Bill name|^Goal name|^Commute name|^Profile name/, 'name'],
    [/^Account name|^An account with that name/, 'name'], [/^Opening balance/, 'opening_balance'],
    [/^Transfer date/, 'occurred_on'], [/^Transfer amount/, 'amount'],
    [/^Budget/, 'limit'], [/^Saved/, 'saved'], [/^Target/, 'target'],
    [/^Amount/, 'amount'], [/^Date/, 'occurred_on'], [/^Month/, 'month'],
    [/^Note/, 'note'], [/^Category/, 'category'],
  ];
  let name = labels.find(([pattern]) => pattern.test(detail))?.[1];
  if (name === 'category' && form.elements.namedItem('category')?.value === '__new__') name = 'new_category';
  const row = rowNumber ? form.querySelector(`[data-row="${rowNumber}"]`) : null;
  if (row) row.classList.add('statement-row-error');
  const field = /^Choose an exported JSON file|^The export file/.test(detail)
    ? form.querySelector('#account-import-file') : name && (row || form).querySelector(`[name="${name}"]`);
  if (field) {
    const prior = field.getAttribute('aria-describedby') || '';
    field.dataset.errorPriorDescription = prior;
    field.setAttribute('aria-invalid', 'true');
    field.setAttribute('aria-describedby', `${prior ? `${prior} ` : ''}${summary.id}`);
  }
  summary.focus();
  if (row) row.scrollIntoView({ block: 'nearest' });
}
function closeMenu(returnFocus = false) {
  $('#sidebar').classList.remove('open');
  $('#menu-scrim').classList.add('hidden');
  $('#menu-toggle').setAttribute('aria-expanded', 'false');
  $('#menu-toggle').setAttribute('aria-label', 'Open menu');
  document.body.classList.remove('menu-open');
  $('#sidebar').inert = window.matchMedia('(max-width: 850px)').matches;
  if (returnFocus) $('#menu-toggle').focus();
}
function toggleMenu() {
  if ($('#sidebar').classList.contains('open')) return closeMenu(true);
  $('#sidebar').inert = false;
  $('#sidebar').classList.add('open');
  $('#menu-scrim').classList.remove('hidden');
  $('#menu-toggle').setAttribute('aria-expanded', 'true');
  $('#menu-toggle').setAttribute('aria-label', 'Close menu');
  document.body.classList.add('menu-open');
  $('#sidebar .workspace-picker').focus();
}
function syncMenu() {
  if (!window.matchMedia('(max-width: 850px)').matches) closeMenu();
  else $('#sidebar').inert = !$('#sidebar').classList.contains('open');
}
window.addEventListener('resize', syncMenu);
document.addEventListener('keydown', event => { if (event.key === 'Escape' && $('#sidebar').classList.contains('open')) closeMenu(true); });
async function navigate(page) {
  state.page = page;
  closeMenu();
  document.querySelectorAll('[data-page]').forEach(button => button.classList.toggle('active', button.dataset.page === page));
  $('#breadcrumb-page').textContent = pages[page];
  if (page === 'transactions') await loadTransactions(); else render();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
function heading(title, subtitle, actions = '') {
  return `<div class="page-heading"><div><span class="eyebrow">${escapeHtml(state.data.profile.name)} · ${escapeHtml(currency())}</span><h1>${title}</h1><p>${subtitle}</p></div><div class="heading-actions">${actions}</div></div>`;
}
function monthPicker() { return `<input type="month" class="month-input" id="month-picker" value="${state.month}" aria-label="Select month">`; }
function panelHead(title, subtitle = '', link = '') { return `<div class="panel-heading"><div><h2>${title}</h2>${subtitle ? `<p>${subtitle}</p>` : ''}</div>${link}</div>`; }
function empty(icon, title, detail = '') { return `<div class="empty"><div class="empty-icon">${icon}</div><strong>${title}</strong>${detail ? `<p>${detail}</p>` : ''}</div>`; }
function render() {
  if (!state.data) return;
  const view = { dashboard: dashboard, transactions: transactionsPage, accounts: accountsPage, budgets: budgetsPage, goals: goalsPage, bills: billsPage, calculators: calculatorsPage, settings: settingsPage }[state.page];
  $('#page-content').innerHTML = view();
  if (state.page === 'calculators') updateCalculator();
}
