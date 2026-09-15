const $ = (selector) => document.querySelector(selector);
const localDate = () => { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`; };
const state = { bootstrap: null, data: null, transactions: null, txOffset: 0, txRequest: 0, page: 'dashboard', month: localDate().slice(0, 7), filter: '', kind: 'all', calc: 'mortgage', mortgageView: 'payments', mortgageInputs: {}, authMode: 'login' };
const pages = { dashboard: 'Overview', transactions: 'Transactions', budgets: 'Budgets', goals: 'Savings goals', bills: 'Regular bills', calculators: 'Calculators', settings: 'Profiles & settings' };
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
  } else { state.data = null; state.transactions = null; closeMenu(); }
}
async function loadData() {
  state.data = await api(`/api/data?month=${encodeURIComponent(state.month)}`);
  $('#sidebar-profile').textContent = state.data.profile.name;
  $('#profile-avatar').textContent = state.data.profile.name.charAt(0).toUpperCase();
  if (state.page === 'transactions') await loadTransactions(); else render();
}
async function loadTransactions() {
  const requestId = ++state.txRequest;
  const requestedFilter = state.filter, requestedKind = state.kind;
  let query = new URLSearchParams({ offset: String(state.txOffset), kind: state.kind, search: state.filter });
  let listing = await api(`/api/transactions?${query}`);
  if (requestId !== state.txRequest || state.page !== 'transactions' || requestedFilter !== state.filter || requestedKind !== state.kind) return;
  state.transactions = listing;
  if (state.txOffset > 0 && state.txOffset >= state.transactions.total) {
    state.txOffset = Math.max(0, Math.floor((state.transactions.total - 1) / 50) * 50);
    query = new URLSearchParams({ offset: String(state.txOffset), kind: state.kind, search: state.filter });
    listing = await api(`/api/transactions?${query}`);
    if (requestId !== state.txRequest || state.page !== 'transactions' || requestedFilter !== state.filter || requestedKind !== state.kind) return;
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
    [/^Budget/, 'limit'], [/^Saved/, 'saved'], [/^Target/, 'target'],
    [/^Amount/, 'amount'], [/^Date/, 'occurred_on'], [/^Month/, 'month'],
    [/^Note/, 'note'], [/^Category/, 'category'],
  ];
  let name = labels.find(([pattern]) => pattern.test(message))?.[1];
  if (name === 'category' && form.elements.namedItem('category')?.value === '__new__') name = 'new_category';
  const field = /^Choose an exported JSON file|^The export file/.test(message)
    ? form.querySelector('#account-import-file') : name && form.querySelector(`[name="${name}"]`);
  if (field) {
    const prior = field.getAttribute('aria-describedby') || '';
    field.dataset.errorPriorDescription = prior;
    field.setAttribute('aria-invalid', 'true');
    field.setAttribute('aria-describedby', `${prior ? `${prior} ` : ''}${summary.id}`);
  }
  summary.focus();
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
  const view = { dashboard: dashboard, transactions: transactionsPage, budgets: budgetsPage, goals: goalsPage, bills: billsPage, calculators: calculatorsPage, settings: settingsPage }[state.page];
  $('#page-content').innerHTML = view();
  if (state.page === 'calculators') updateCalculator();
}
function metric(label, value, foot, icon, tone = '') {
  return `<div class="metric-card"><div class="metric-top"><span>${label}</span><span class="metric-icon ${tone}">${icon}</span></div><div class="metric-value">${value}</div><div class="metric-foot">${foot}</div></div>`;
}
function transactionRows(items, compact = false) {
  return items.map(tx => `<tr><td><strong>${escapeHtml(tx.note || tx.category)}</strong><span class="sub">${escapeHtml(tx.kind === 'income' ? 'Income' : 'Expense')}</span></td><td><span class="category-pill">${escapeHtml(tx.category)}</span></td><td>${shortDate(tx.occurred_on)}</td><td class="amount ${tx.kind === 'income' ? 'positive' : ''}">${tx.kind === 'income' ? '+' : '−'}${fmt(tx.amount_cents)}</td>${compact ? '' : `<td class="action-cell"><button class="table-action" data-action="duplicate-transaction" data-id="${tx.id}">Duplicate</button><button class="table-action" data-action="edit-transaction" data-id="${tx.id}">Edit</button><button class="table-action delete" data-action="delete-transaction" data-id="${tx.id}">Delete</button></td>`}</tr>`).join('');
}
function mobileTransactionCards(items, compact = false) {
  return `<div class="mobile-record-list">${items.map(tx => `<article class="mobile-record"><div><strong>${escapeHtml(tx.note || tx.category)}</strong><span class="amount ${tx.kind === 'income' ? 'positive' : ''}">${tx.kind === 'income' ? '+' : '−'}${fmt(tx.amount_cents)}</span></div><small>${escapeHtml(tx.category)} · ${shortDate(tx.occurred_on)} · ${tx.kind === 'income' ? 'Income' : 'Expense'}</small>${compact ? '' : `<div class="mobile-record-actions"><button class="table-action" data-action="duplicate-transaction" data-id="${tx.id}">Duplicate</button><button class="table-action" data-action="edit-transaction" data-id="${tx.id}">Edit</button><button class="table-action delete" data-action="delete-transaction" data-id="${tx.id}">Delete</button></div>`}</article>`).join('')}</div>`;
}
function billStatusPanel() {
  const status = state.data.bill_status;
  const next = status.next_unrecorded.map(item => `<li><span><strong>${escapeHtml(item.name)}</strong><small>${shortDate(item.due_on)} · ${item.due_now ? 'Due or past due' : 'Upcoming'}</small></span><b>${fmt(item.amount_cents)}</b></li>`).join('');
  return `<section class="panel bill-status-panel">${panelHead('Scheduled bill payments', monthLabel(state.month), `<button class="mini-link" data-action="import-bills" ${state.data.bills.length ? '' : 'disabled'}>Review payments →</button>`)}<div class="bill-status-grid"><div><span>Scheduled this month</span><strong>${fmt(status.scheduled_cents)}</strong><small>${status.scheduled_count} occurrence${status.scheduled_count === 1 ? '' : 's'} from saved bills</small></div><div><span>Linked to transactions</span><strong>${fmt(status.recorded_schedule_cents)}</strong><small>${status.recorded_count} linked · transaction amounts ${fmt(status.recorded_cents)}</small></div><div class="bill-status-pending"><span>Not linked to transactions</span><strong>${fmt(status.unrecorded_cents)}</strong><small>${fmt(status.due_now_cents)} due or past due · ${fmt(status.upcoming_cents)} upcoming</small></div></div>${next ? `<ul class="bill-status-next" aria-label="Next unrecorded bill payments">${next}</ul>` : ''}${status.unscheduled_bills ? `<p class="bill-status-warning">${status.unscheduled_bills} non-monthly bill${status.unscheduled_bills === 1 ? '' : 's'} need${status.unscheduled_bills === 1 ? 's' : ''} a first payment date before the app can list due payments.</p>` : ''}<p class="bill-status-note">Linked and unlinked scheduled values add up to this month’s total. Linked transaction amounts may differ after edits. Manual payments remain unlinked; review them before importing. The schedule reflects current bill settings.</p></section>`;
}
function dashboard() {
  const income = state.data.monthly_totals.income;
  const expenses = state.data.monthly_totals.expense;
  const net = income - expenses;
  const rate = income ? Math.round(net / income * 100) : 0;
  const bills = state.data.monthly_bills_cents;
  const goalsMonthly = sum(state.data.goals, 'monthly_cents');
  const bars = state.data.chart;
  const max = Math.max(1, ...bars.flatMap(bar => [bar.income, bar.expense]));
  const chart = bars.some(bar => bar.income || bar.expense) ? `<div class="chart">${bars.map(bar => `<div class="chart-col"><div class="chart-bars"><span class="${bar.income ? '' : 'zero'}" title="Income ${fmt(bar.income)}" style="height:${bar.income ? Math.max(1, bar.income / max * 100) : 0}%"></span><span class="expense ${bar.expense ? '' : 'zero'}" title="Spending ${fmt(bar.expense)}" style="height:${bar.expense ? Math.max(1, bar.expense / max * 100) : 0}%"></span></div><small>${new Date(`${bar.key}-01T12:00:00`).toLocaleDateString('en-GB', { month: 'short' })}</small></div>`).join('')}</div><div class="legend"><span>Income</span><span>Spending</span></div>` : empty('▤', 'No chart history', 'Add income or spending to see the last six months.');
  const categories = state.data.spending.slice(0, 5);
  const breakdown = categories.length ? `<div class="breakdown-list">${categories.map(({category, amount_cents: amount}, i) => `<div class="breakdown-row"><div class="breakdown-top"><strong>${escapeHtml(category)}</strong><span>${fmt(amount)}</span></div><div class="track ${i === 1 ? 'gold' : ''}"><span style="width:${expenses ? amount / expenses * 100 : 0}%"></span></div></div>`).join('')}</div>` : empty('▥', 'No spending yet', 'Add an expense to see where your money goes.');
  const goals = state.data.goals.slice(0, 3);
  return heading('Your month at a glance', `Recorded activity and scheduled bill payments for ${monthLabel(state.month)}.`, `${monthPicker()}<button class="btn btn-secondary" data-action="add-transaction">＋ Add new</button>`)
    + `<div class="grid-4">${metric('Recorded income', fmt(income), 'Income transactions this month', '↙')}${metric('Recorded spending', fmt(expenses), 'Expense transactions this month', '↗', 'gold')}${metric('Recorded cash flow', fmt(net), 'Income less recorded spending, not an account balance', '⌁', net < 0 ? 'red' : '')}${metric('Savings rate', `${rate}%`, income ? 'Recorded cash flow ÷ income' : 'Add income to calculate', '◎')}</div>`
    + `<section class="monthly-plan"><div><small>Bills & commuting · monthly planning average</small><strong>${fmt(bills)}</strong></div><div><small>Savings goal contributions · monthly plan</small><strong>${fmt(goalsMonthly)}</strong></div><p>These are planning figures, not extra recorded spending. Bill averages spread recurring costs over the year; commuting uses this month’s workday estimate.</p></section>`
    + billStatusPanel()
    + `<div class="dashboard-grid"><section class="panel">${panelHead('Income & spending', 'The last six months')}${chart}</section><section class="panel">${panelHead('Spending breakdown', monthLabel(state.month))}${breakdown}</section></div>`
    + `<div class="dashboard-bottom"><section class="panel">${panelHead('Recent transactions', 'Latest activity this month', `<button class="mini-link" data-page="transactions">View all →</button>`)}${state.data.recent.length ? `<div class="table-wrap recent-table"><table class="data-table"><thead><tr><th>Transaction</th><th>Category</th><th>Date</th><th style="text-align:right">Amount</th></tr></thead><tbody>${transactionRows(state.data.recent, true)}</tbody></table></div>${mobileTransactionCards(state.data.recent, true)}` : empty('⇄', 'No transactions this month', 'Start with an income or expense.')}</section><section class="panel">${panelHead('Savings goals', 'Make progress on what matters', `<button class="mini-link" data-page="goals">View goals →</button>`)}${goals.length ? `<div class="goal-mini">${goals.map(goal => `<div class="goal-mini-item"><div><strong>${escapeHtml(goal.name)}</strong><span>${Math.min(100, Math.round(goal.saved_cents / goal.target_cents * 100))}%</span></div><div class="track"><span style="width:${Math.min(100, goal.saved_cents / goal.target_cents * 100)}%"></span></div><span>${fmt(goal.saved_cents)} of ${fmt(goal.target_cents)}</span></div>`).join('')}</div>` : empty('◎', 'No savings goals yet', 'Create a goal to track your progress.')}</section></div>`;
}
function transactionsPage() {
  const listing = state.transactions || { transactions: [], total: 0, offset: 0, limit: 50 };
  const rows = listing.transactions;
  const start = listing.total ? listing.offset + 1 : 0;
  const end = Math.min(listing.offset + rows.length, listing.total);
  return heading('Transactions', 'Every pound in and out, in one place.', `<button class="btn btn-primary" data-action="add-transaction">＋ Add transaction</button>`)
    + `<div class="toolbar"><input class="search-input" id="transaction-search" placeholder="Search transactions" value="${escapeHtml(state.filter)}" aria-label="Search transactions"><select id="kind-filter" aria-label="Filter transaction type"><option value="all" ${state.kind === 'all' ? 'selected' : ''}>All activity</option><option value="income" ${state.kind === 'income' ? 'selected' : ''}>Income</option><option value="expense" ${state.kind === 'expense' ? 'selected' : ''}>Expenses</option></select><span class="muted" style="font-size:11px">${listing.total} ${listing.total === 1 ? 'record' : 'records'}</span></div>`
    + `<section class="panel wide-panel">${rows.length ? `<div class="table-wrap desktop-record-table"><table class="data-table"><thead><tr><th>Transaction</th><th>Category</th><th>Date</th><th style="text-align:right">Amount</th><th></th></tr></thead><tbody>${transactionRows(rows)}</tbody></table></div>${mobileTransactionCards(rows)}` : empty('⇄', 'Nothing to show', 'Try a different search or add a transaction.')}${listing.total ? `<div class="pager"><span>Showing ${start}–${end} of ${listing.total}</span><div><button class="btn btn-outline" data-action="tx-prev" ${listing.offset === 0 ? 'disabled' : ''}>Previous</button><button class="btn btn-outline" data-action="tx-next" ${end >= listing.total ? 'disabled' : ''}>Next</button></div></div>` : ''}</section>`;
}
function budgetsPage() {
  const spent = state.data.monthly_totals.expense;
  const total = sum(state.data.budgets, 'limit_cents');
  const rows = state.data.budgets.map(budget => {
    const used = sum(state.data.spending.filter(item => item.category.toLowerCase() === budget.category.toLowerCase()));
    const percent = Math.round(used / budget.limit_cents * 100);
    return `<div class="budget-row"><div><strong>${escapeHtml(budget.category)}</strong><small>${fmt(used)} spent of ${fmt(budget.limit_cents)}</small><div class="track budget-bar ${percent > 100 ? 'red' : percent > 80 ? 'gold' : ''}"><span style="width:${Math.min(100, percent)}%"></span></div></div><div><strong class="${percent > 100 ? 'negative' : ''}">${percent}% used</strong><small>${percent > 100 ? `${fmt(used - budget.limit_cents)} over` : `${fmt(budget.limit_cents - used)} left`}</small></div><div class="action-cell"><button class="table-action delete" data-action="delete-budget" data-id="${budget.id}">Remove</button></div></div>`;
  });
  return heading('Monthly budgets', `Plan what you can spend in ${monthLabel(state.month)}.`, `${monthPicker()}<button class="btn btn-primary" data-action="add-budget">＋ Set budget</button>`)
    + `<div class="grid-4">${metric('Budgeted', fmt(total), 'Across all categories', '▤')}${metric('Spent', fmt(spent), 'All expenses this month', '↗', 'gold')}${metric('Budget remaining', fmt(total - spent), 'Budgeted less all spending', '⌁', spent > total ? 'red' : '')}${metric('Categories', state.data.budgets.length, 'With a monthly limit', '▥')}</div>`
    + `<section class="panel budget-plan"><div><span>Bills & commuting · ${monthLabel(state.month)} plan</span><strong>${fmt(state.data.monthly_bills_cents)}</strong></div><p>If a category budget already covers a bill or commute, don't add it twice. Paid transactions are included in Spent.</p><button class="mini-link" data-page="bills">View bills →</button></section>`
    + `<section class="panel" style="margin-top:17px">${panelHead('Category limits', 'Adding a category again updates its limit')}${rows.length ? `<div class="budget-list">${rows.join('')}</div>` : empty('▤', 'No budgets for this month', 'Set a category limit to get started.')}</section>`;
}
function goalsPage() {
  const goals = state.data.goals;
  const cards = goals.map(goal => {
    const percent = Math.min(100, Math.round(goal.saved_cents / goal.target_cents * 100));
    const remaining = Math.max(0, goal.target_cents - goal.saved_cents);
    const months = remaining && goal.monthly_cents ? Math.ceil(remaining / goal.monthly_cents) : null;
    const deadline = goalDeadlineMessage(goal, remaining);
    return `<article class="panel goal-card"><div class="goal-icon">◎</div><h2>${escapeHtml(goal.name)}</h2><p>${goal.target_date ? `Target date · ${shortDate(goal.target_date)}` : 'A goal worth saving for'}</p><div class="goal-numbers"><strong>${fmt(goal.saved_cents)}</strong><span>of ${fmt(goal.target_cents)}</span></div><div class="track"><span style="width:${percent}%"></span></div><div class="goal-details"><span>${percent}% complete</span><span>${fmt(remaining)} to go</span></div><div class="goal-details"><span>${goal.monthly_cents ? `${fmt(goal.monthly_cents)} / month` : 'No monthly plan'}</span><span>${months ? `~${months} months at this pace` : percent === 100 ? 'Complete!' : ''}</span></div>${deadline ? `<p class="goal-plan-warning">${escapeHtml(deadline)}</p>` : ''}<div class="card-actions"><button class="btn btn-secondary" data-action="edit-goal" data-id="${goal.id}">Update goal</button><button class="btn btn-outline" data-action="delete-goal" data-id="${goal.id}">Delete</button></div></article>`;
  });
  return heading('Savings goals', 'Turn good intentions into visible progress.', `<button class="btn btn-primary" data-action="add-goal">＋ New goal</button>`)
    + (cards.length ? `<div class="cards-3">${cards.join('')}</div>` : `<section class="panel">${empty('◎', 'Your first goal starts here', 'Add a target, current balance and monthly contribution.')}</section>`);
}
function billsPage() {
  const bills = state.data.bills;
  const commutes = state.data.commutes || [];
  const rows = bills.map(bill => {
    const frequency = billFrequencyLabel(bill.frequency);
    const due = bill.frequency === 'monthly' ? ` · Day ${bill.day_of_month}` : bill.first_due_on ? ` · From ${shortDate(bill.first_due_on)}` : '';
    return `<tr><td><strong>${escapeHtml(bill.name)}</strong></td><td><span class="category-pill">${escapeHtml(bill.category)}</span></td><td>${escapeHtml(frequency)}${due}</td><td class="amount">${fmt(bill.amount_cents)}</td><td class="amount">${fmt(bill.monthly_cents)}</td><td class="action-cell"><button class="table-action" data-action="edit-bill" data-id="${bill.id}">Edit</button><button class="table-action delete" data-action="delete-bill" data-id="${bill.id}">Delete</button></td></tr>`;
  });
  const cards = bills.map(bill => `<article class="mobile-record"><div><strong>${escapeHtml(bill.name)}</strong><span class="bill-record-money"><span class="amount">${fmt(bill.monthly_cents)}</span><small>monthly average</small></span></div><small>${escapeHtml(bill.category)} · ${fmt(bill.amount_cents)} each time · ${escapeHtml(billFrequencyLabel(bill.frequency))}${bill.frequency === 'monthly' ? ` · Day ${bill.day_of_month}` : bill.first_due_on ? ` · From ${shortDate(bill.first_due_on)}` : ''}</small><div class="mobile-record-actions"><button class="table-action" data-action="edit-bill" data-id="${bill.id}">Edit</button><button class="table-action delete" data-action="delete-bill" data-id="${bill.id}">Delete</button></div></article>`);
  const commuteCards = commutes.map(plan => `<article class="commute-card"><div><span class="category-pill">${plan.mode === 'car' ? 'Car' : 'Public transport'}</span><strong>${escapeHtml(plan.name)}</strong><small>${commuteDayText(plan)} · ${fmt(plan.daily_cents)} per day${commuteAdjustmentText(plan)}</small></div><div class="commute-card-amount"><strong>${fmt(plan.monthly_cents)}</strong><small>in ${monthLabel(state.month)}</small></div><div class="commute-card-actions"><button class="table-action" data-action="edit-commute" data-id="${plan.id}">Edit</button><button class="table-action delete" data-action="delete-commute" data-id="${plan.id}">Delete</button></div>${plan.holiday_status || plan.leave_status ? `<p class="freshness-warning">${escapeHtml([plan.holiday_status, plan.leave_status].filter(Boolean).join(' '))}</p>` : ''}</article>`).join('');
  return heading('Regular bills', `Plan bills and commuting for ${monthLabel(state.month)}.`, `${monthPicker()}<button class="btn btn-secondary" data-action="add-commute">＋ Commuting</button><button class="btn btn-primary" data-action="add-bill">＋ Add bill</button>`)
    + `<div class="bill-total"><span>Bills & commuting · monthly planning average</span><strong>${fmt(state.data.monthly_bills_cents)}</strong></div>`
    + billStatusPanel()
    + `<section class="panel commute-panel">${panelHead('Commuting', 'Car fuel or public transport, based on the workdays you choose', `<button class="mini-link" data-action="add-commute">Add commute →</button>`)}${commutes.length ? `<div class="commute-list">${commuteCards}</div>` : empty('↗', 'No commute planned yet', 'Add a car or public transport commute to estimate this month’s travel cost.')}</section>`
    + `<section class="panel wide-panel bills-panel"><div class="bill-import-bar"><div><strong>Bill payments</strong><small>Review what's due and record only bills you've paid.</small></div><button class="btn btn-secondary" data-action="import-bills" ${bills.length ? '' : 'disabled'}>Import into transactions</button></div>${bills.length ? `<div class="table-wrap desktop-record-table"><table class="data-table"><thead><tr><th>Bill</th><th>Category</th><th>Frequency</th><th style="text-align:right">Each time</th><th style="text-align:right">Monthly average</th><th></th></tr></thead><tbody>${rows.join('')}</tbody></table></div><div class="mobile-record-list">${cards.join('')}</div>` : empty('▦', 'No bills saved', 'Add rent, utilities, subscriptions or other regular costs.')}</section><p class="setting-note">Bill averages spread annual costs over 12 months and use 52 weeks per year. Commuting counts this month's selected weekdays and optional UK bank holidays. Annual leave entered as a yearly number is an approximate monthly share; exact dates give precise months. Import paid bills at their actual amount and due date; commuting estimates stay as plans. Payments recorded as transactions appear in actual spending.</p>`;
}
function commuteDayText(plan) {
  return plan.leave_mode === 'annual' ? `${plan.expected_days} estimated commuting days` : `${plan.workdays} commuting days`;
}
function commuteAdjustmentText(plan) {
  const notes = [];
  if (plan.leave_days) notes.push(`${plan.leave_days} exact day${plan.leave_days === 1 ? '' : 's'} off`);
  if (plan.annual_leave_estimate_days) notes.push(`about ${plan.annual_leave_estimate_days} days from annual leave`);
  if (plan.bank_holiday_days) notes.push(`${plan.bank_holiday_days} bank holiday${plan.bank_holiday_days === 1 ? '' : 's'} excluded`);
  return notes.map(note => ` · ${note}`).join('');
}
function calcField(label, name, value, suffix = '', min = '0') { return `<label>${label}<input type="number" data-calc="${name}" value="${value}" min="${min}" step="0.01" ${suffix ? `placeholder="${suffix}"` : ''}></label>`; }
function mortgageField(label, name, defaultValue) {
  return calcField(label, name, escapeHtml(state.mortgageInputs[name] ?? defaultValue));
}
function mortgageSelect(label, name, options, initial) {
  const selected = String(state.mortgageInputs[name] ?? initial);
  return `<label>${label}<select data-mortgage="${name}">${options.map(([value, text]) => `<option value="${value}" ${selected === String(value) ? 'selected' : ''}>${text}</option>`).join('')}</select></label>`;
}
function calculatorsPage() {
  const tabs = `<div class="calc-tabs"><button data-calc-tab="mortgage" class="${state.calc === 'mortgage' ? 'active' : ''}">Mortgage</button><button data-calc-tab="savings" class="${state.calc === 'savings' ? 'active' : ''}">Savings growth</button><button data-calc-tab="habit" class="${state.calc === 'habit' ? 'active' : ''}">Spending habit</button></div>`;
  let form, text;
  if (state.calc === 'mortgage') {
    const switcher = `<div class="mortgage-switch" role="group" aria-label="Mortgage calculator view"><button data-mortgage-view="payments" class="${state.mortgageView === 'payments' ? 'active' : ''}" aria-pressed="${state.mortgageView === 'payments'}">Monthly payments</button><button data-mortgage-view="affordability" class="${state.mortgageView === 'affordability' ? 'active' : ''}" aria-pressed="${state.mortgageView === 'affordability'}">Can I afford it?</button></div>`;
    const common = `<div class="form-grid">${mortgageField('Home price (£)', 'price', 300000)}${mortgageField('Deposit (£)', 'deposit', 30000)}${mortgageField('Interest rate (%)', 'rate', 4.5)}${mortgageField('Term (years)', 'years', 25)}</div>`;
    if (state.mortgageView === 'payments') {
      form = switcher + common;
      text = 'Estimate a repayment mortgage payment and the total interest over the full term.';
    } else {
      form = switcher + common + `<h3 class="calc-subhead">Your household</h3><div class="form-grid">${mortgageField('Gross annual income (£)', 'grossAnnual', 0)}${mortgageField('Monthly take-home pay (£)', 'netMonthly', 0)}${mortgageSelect('Applicants', 'applicants', [[1,'One applicant'],[2,'Two applicants']], 1)}${mortgageSelect('Buying situation', 'buyer', [['ftb','First-time buyer'],['mover','Moving home']], 'ftb')}${mortgageSelect('Property type', 'propertyType', [['unknown','Select for high-LTV screening'],['house','House'],['flat','Flat']], 'unknown')}${mortgageSelect('Employment', 'employment', [['employed','Employed'],['self','Self-employed']], 'employed')}${mortgageSelect('Initial fixed-rate deal', 'fixedYears', [[2,'2 years'],[5,'5 years'],[10,'10 years']], 5)}${mortgageSelect('HSBC Premier customer?', 'premier', [['no','No'],['yes','Yes']], 'no')}${mortgageSelect('Already have a Nationwide mortgage?', 'nationwideExisting', [['no','No'],['yes','Yes']], 'no')}${mortgageField('Dependants', 'dependants', 0)}</div><p class="setting-note">For joint first-time buyer schemes, this guide assumes both applicants are first-time buyers.</p><h3 class="calc-subhead">Monthly costs after moving</h3><div class="form-grid">${mortgageField('Loans & card repayments (£)', 'debtsMonthly', 0)}${mortgageField('Food, utilities & travel (£)', 'livingMonthly', 0)}${mortgageField('Childcare & support (£)', 'childcareMonthly', 0)}${mortgageField('Council tax, insurance & service charges (£)', 'homeMonthly', 0)}</div><p class="setting-note">Use costs you expect after moving. Leave out rent that this mortgage would replace. These entries are not saved.</p>`;
      text = 'Compare published UK borrowing caps with your own monthly budget. All amounts in this view are GBP.';
    }
  } else if (state.calc === 'savings') {
    form = `<div class="form-grid">${calcField('Starting balance', 'starting', 1000)}${calcField('Add each month', 'contribution', 200)}${calcField('Annual return (%)', 'return', 3)}${calcField('Years', 'savingsYears', 5, '', '1')}</div>`;
    text = 'See what regular saving could add up to. Returns are illustrative and may vary.';
  } else {
    form = `<div class="form-grid">${calcField('Cost each time', 'habitCost', 5)}${calcField('Times each week', 'habitTimes', 4)}${calcField('Reduce by (%)', 'habitReduce', 50)}${calcField('Years', 'habitYears', 3, '', '1')}</div>`;
    text = 'Find the yearly cost of a small repeat expense and what you could save by cutting back.';
  }
  return heading('Money calculators', 'Explore a few what-if scenarios for your plans.') + tabs + `<div class="calculator-layout"><section class="panel"><span class="eyebrow">PLAY WITH THE NUMBERS</span><h2 style="font-size:21px;letter-spacing:-.04em;margin:9px 0">${{mortgage:'Mortgage calculator',savings:'Savings growth',habit:'Spending habit'}[state.calc]}</h2><p class="setting-note">${text}</p>${form}</section><section class="panel"><span class="eyebrow">YOUR ESTIMATE</span><div id="calc-output"></div></section></div>`;
}
function num(name) { return Number(document.querySelector(`[data-calc="${name}"]`)?.value || 0); }
function mortgageInput(name, fallback = 0) {
  const field = document.querySelector(`[data-calc="${name}"], [data-mortgage="${name}"]`);
  return field ? field.value : (state.mortgageInputs[name] ?? fallback);
}
const mortgageFmt = amount => new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP', maximumFractionDigits: 0 }).format(amount || 0);
const mortgagePaymentFmt = amount => new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP', minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(amount || 0);
function affordabilityOutput(result) {
  if (result.error) return `<div class="alert">${escapeHtml(result.error)}</div>`;
  const budget = result.budget;
  const budgetLabel = !budget ? 'Add monthly take-home pay to check your budget.' :
    budget.current <= 0 ? 'Your entered budget is stretched at the current rate.' :
    budget.higherRate <= 0 ? 'Your entered budget is positive now, but not in the rate-rise scenario.' :
    'Your entered budget remains positive at both rates.';
  const capLabel = result.stale ? 'Published caps need a fresh source check before comparing.' :
    result.multiple == null ? 'Add gross annual income to compare lender caps.' :
    result.hasPublishedCap ? 'The loan is within at least one sampled published cap.' :
    'No sampled published cap covers this loan; check lenders directly.';
  const checks = result.lenders.map(item => `<div class="lender-row"><div><strong>${item.name}</strong><small>${escapeHtml(item.scheme || 'Case-specific check')}</small></div><div class="lender-figure">${item.multiple == null ? 'Review lender' : `${item.multiple.toFixed(2)}× · ${mortgageFmt(item.ceiling)}`}<small>${result.stale ? 'Recheck current criteria' : item.withinCap == null ? 'Not screened' : item.withinCap ? 'Within published cap' : 'Above published cap'}</small></div><a href="${item.source}" target="_blank" rel="noopener noreferrer" aria-label="View ${item.name} criteria">↗</a></div><p class="lender-reason">${escapeHtml(item.reason)}</p>`).join('');
  return `${result.stale ? `<div class="freshness-warning">These lender caps were last checked ${result.checked}. Open each lender's current criteria before relying on a cap comparison.</div>` : ''}<div class="calc-result"><small>MONTHLY REPAYMENT AT ${escapeHtml(mortgageInput('rate'))}%</small><strong>${mortgagePaymentFmt(result.monthly)}</strong><p>${mortgageFmt(result.loan)} loan · ${result.ltv.toFixed(1)}% loan-to-value${result.multiple == null ? '' : ` · ${result.multiple.toFixed(2)}× gross income`}</p></div><div class="afford-status"><strong>${escapeHtml(budgetLabel)}</strong><span>${escapeHtml(capLabel)}</span></div><div class="insight-list"><div class="insight"><span>Money left after mortgage & entered costs</span><strong class="${budget && budget.current < 0 ? 'negative' : ''}">${budget ? mortgagePaymentFmt(budget.current) : 'Add take-home pay'}</strong></div><div class="insight"><span>At a rate 2 points higher (${Number(mortgageInput('rate')) + 2}%)</span><strong class="${budget && budget.higherRate < 0 ? 'negative' : ''}">${budget ? mortgagePaymentFmt(budget.higherRate) : mortgagePaymentFmt(result.sensitivity) + ' payment'}</strong></div></div><h3 class="calc-subhead">Published lender cap checks</h3><div class="lender-list">${checks}</div><p class="setting-note">Criteria checked ${result.checked}. Income multiples are ceilings, not affordability decisions. Lenders also check credit history, income evidence, expenditure, dependants, property and their own interest-rate stress tests. The 2-point scenario is your planning check, not a lender's stress rate. Ask a lender for an Agreement or Decision in Principle for a personalised answer. <a href="${result.sources.natwest}" target="_blank" rel="noopener noreferrer">NatWest's calculator</a> asks for income, dependants and commitments; the <a href="${result.sources.fca}" target="_blank" rel="noopener noreferrer">FCA explains lender stress testing</a>.</p>`;
}
function updateCalculator() {
  if (state.page !== 'calculators') return;
  const output = $('#calc-output'); let result = '';
  if (state.calc === 'mortgage') {
    if (state.mortgageView === 'affordability') {
      const guide = window.MortgageGuide.screen({
        price: mortgageInput('price'), deposit: mortgageInput('deposit'), rate: mortgageInput('rate'), years: mortgageInput('years'),
        grossAnnual: mortgageInput('grossAnnual'), netMonthly: mortgageInput('netMonthly'), applicants: mortgageInput('applicants', 1),
        buyer: mortgageInput('buyer', 'ftb'), propertyType: mortgageInput('propertyType', 'unknown'), employment: mortgageInput('employment', 'employed'), fixedYears: mortgageInput('fixedYears', 5),
        premier: mortgageInput('premier', 'no') === 'yes', nationwideExisting: mortgageInput('nationwideExisting', 'no') === 'yes',
        dependants: mortgageInput('dependants'),
        debtsMonthly: mortgageInput('debtsMonthly'), livingMonthly: mortgageInput('livingMonthly'),
        childcareMonthly: mortgageInput('childcareMonthly'), homeMonthly: mortgageInput('homeMonthly'),
      });
      output.innerHTML = affordabilityOutput(guide);
      return;
    }
    const price = num('price'), deposit = num('deposit'), rate = num('rate'), years = num('years');
    if (![price, deposit, rate, years].every(Number.isFinite) || price <= 0 || deposit < 0 || deposit > price || rate < 0 || rate > 100 || years < 1 || years > 50) {
      output.innerHTML = `<div class="alert">Enter a home price, a deposit no larger than the price, an interest rate from 0 to 100%, and a term of 1 to 50 years.</div>`;
      return;
    }
    const principal = Math.max(0, price - deposit), n = Math.round(years * 12), r = rate / 1200;
    const payment = n > 0 ? (r > 0 ? principal * r / (1 - Math.pow(1 + r, -n)) : principal / n) : 0;
    const interest = n > 0 ? payment * n - principal : 0;
    if (![payment, interest].every(Number.isFinite)) { output.innerHTML = '<div class="alert">The amounts are too large to calculate.</div>'; return; }
    result = `<div class="calc-result"><small>ESTIMATED MONTHLY REPAYMENT</small><strong>${mortgagePaymentFmt(payment)}</strong><p>Based on ${mortgagePaymentFmt(principal)} borrowed over ${years} years.</p></div><div class="insight-list"><div class="insight"><span>Deposit</span><strong>${mortgagePaymentFmt(deposit)}</strong></div><div class="insight"><span>Total interest</span><strong>${mortgagePaymentFmt(interest)}</strong></div><div class="insight"><span>Total repaid</span><strong>${mortgagePaymentFmt(payment * n)}</strong></div></div><p class="setting-note">Excludes fees, insurance, taxes and rate changes. This is an estimate, not a mortgage offer.</p>`;
  } else if (state.calc === 'savings') {
    const starting = num('starting'), monthly = num('contribution'), annual = num('return'), n = Math.round(num('savingsYears') * 12), r = annual / 1200;
    if (![starting, monthly, annual, n].every(Number.isFinite) || starting < 0 || monthly < 0 || annual < 0 || annual > 100 || n < 12 || n > 1200) {
      output.innerHTML = `<div class="alert">Use non-negative savings amounts, a return from 0 to 100%, and a term of 1 to 100 years.</div>`;
      return;
    }
    const future = r ? starting * Math.pow(1 + r, n) + monthly * ((Math.pow(1 + r, n) - 1) / r) : starting + monthly * n;
    const contributed = starting + monthly * n;
    if (![future, contributed].every(Number.isFinite)) { output.innerHTML = '<div class="alert">The projected balance is too large to calculate.</div>'; return; }
    result = `<div class="calc-result"><small>PROJECTED BALANCE</small><strong>${fmt(Math.round(future * 100))}</strong><p>After ${num('savingsYears')} years of monthly deposits.</p></div><div class="insight-list"><div class="insight"><span>Your contributions</span><strong>${fmt(Math.round(contributed * 100))}</strong></div><div class="insight"><span>Illustrative growth</span><strong>${fmt(Math.round((future - contributed) * 100))}</strong></div></div><p class="setting-note">Uses monthly compounding. Taxes, fees and inflation are excluded.</p>`;
  } else {
    const annual = num('habitCost') * num('habitTimes') * 52, saved = annual * num('habitReduce') / 100, years = num('habitYears');
    if (![num('habitCost'), num('habitTimes'), num('habitReduce'), years].every(Number.isFinite) || num('habitCost') < 0 || num('habitTimes') < 0 || num('habitTimes') > 1000 || num('habitReduce') < 0 || num('habitReduce') > 100 || years < 1 || years > 100) {
      output.innerHTML = `<div class="alert">Use a non-negative cost, 0 to 1,000 times per week, a reduction from 0 to 100%, and a term of 1 to 100 years.</div>`;
      return;
    }
    if (![annual, saved, saved * years].every(Number.isFinite)) { output.innerHTML = '<div class="alert">The amounts are too large to calculate.</div>'; return; }
    result = `<div class="calc-result"><small>POTENTIAL SAVINGS EACH YEAR</small><strong>${fmt(Math.round(saved * 100))}</strong><p>By reducing this expense by ${num('habitReduce')}%.</p></div><div class="insight-list"><div class="insight"><span>Current yearly cost</span><strong>${fmt(Math.round(annual * 100))}</strong></div><div class="insight"><span>Saved over ${years} years</span><strong>${fmt(Math.round(saved * years * 100))}</strong></div></div>`;
  }
  output.innerHTML = result;
}
function settingsPage() {
  const profiles = state.bootstrap.profiles || [];
  const canImport = Boolean(state.bootstrap.import_ready);
  const transfer = `<section class="panel settings-panel">${panelHead('Move your account data', 'Export every profile and import it into another new account')}
    <p class="setting-note">The JSON file includes transactions, saved categories, budgets, savings goals, bills, commuting plans and links to imported bill payments. It excludes passwords, sign-in sessions and your account email. Keep the file private.</p>
    <button type="button" class="btn btn-secondary" data-action="export-data">Export all data</button>
    <form id="account-import-form" class="transfer-form" novalidate>
      <label>Import into this account<input id="account-import-file" type="file" accept=".json,application/json" required ${canImport ? '' : 'disabled'}></label>
      <button type="submit" class="btn btn-outline" ${canImport ? '' : 'disabled'}>Import data</button>
    </form>
    <p class="setting-note">${canImport ? 'This new account is ready for an import.' : 'Import requires a new account with one empty profile. Existing account data is never replaced.'} Files up to 50 MB are accepted.</p>
  </section>`;
  return heading('Profiles & settings', 'Give different plans their own space.', `<button class="btn btn-primary" data-action="add-profile">＋ New profile</button>`)
    + `<section class="panel settings-panel">${panelHead('Your profiles', 'Each profile has separate transactions, budgets, goals, bills and commutes')}<div class="profile-list">${profiles.map(profile => `<div class="profile-item"><span class="workspace-avatar">${escapeHtml(profile.name.charAt(0).toUpperCase())}</span><div><strong>${escapeHtml(profile.name)}</strong><small>${escapeHtml(profile.currency)} · ${profile.id === state.data.profile.id ? 'Active profile' : 'Separate workspace'}</small></div>${profile.id !== state.data.profile.id ? `<button class="btn btn-secondary" data-action="select-profile" data-id="${profile.id}">Switch</button>` : `<span class="category-pill">Current</span>`}${profiles.length > 1 ? `<button class="table-action delete" data-action="delete-profile" data-id="${profile.id}">Delete</button>` : ''}</div>`).join('')}</div></section><section class="panel settings-panel">${panelHead('Account password', 'Change your password and sign out other sessions')}<form id="password-form" class="password-form" novalidate><label>Current password<input name="current_password" type="password" autocomplete="current-password" required></label><label>New password<input name="new_password" type="password" autocomplete="new-password" minlength="12" maxlength="128" required></label><label>Confirm new password<input name="confirm_password" type="password" autocomplete="new-password" minlength="12" maxlength="128" required></label><button class="btn btn-primary" type="submit">Change password</button></form><p class="setting-note">Forgot your password? The server owner can run <code>python reset_password.py --email your@email.com</code> on this computer. The new password is entered privately in the console.</p></section>${transfer}<section class="panel settings-panel">${panelHead('Private local storage')}<p class="setting-note">Your account data is stored in <code>instance/ledger.sqlite3</code> on this server. Keep a backup of the <code>instance</code> directory if you move the app to another computer.</p><p class="setting-note">Current account: <strong>${escapeHtml(state.bootstrap.user.email)}</strong></p></section>`;
}
function goalDeadlineMessage(goal, remaining, today = localDate()) {
  if (!goal.target_date || !remaining) return '';
  const [year, month, day] = goal.target_date.split('-').map(Number);
  const [nowYear, nowMonth, nowDay] = today.split('-').map(Number);
  const contributionMonths = (year - nowYear) * 12 + month - nowMonth + (day >= nowDay ? 1 : 0);
  if (contributionMonths <= 0) return 'The target date has passed. Update the date or your goal.';
  const needed = Math.ceil(remaining / contributionMonths);
  if (goal.monthly_cents >= needed) return '';
  return `At this pace the target date may be missed. Plan about ${fmt(needed)} per month for the next ${contributionMonths} month${contributionMonths === 1 ? '' : 's'} to reach it. This assumes one contribution each month.`;
}

function field(label, name, type, value = '', extra = '') { return `<label>${label}<input name="${name}" type="${type}" value="${escapeHtml(value)}" ${extra} required></label>`; }
function selectField(label, name, values, selected) { return `<label>${label}<select name="${name}">${values.map(value => `<option value="${escapeHtml(value)}" ${selected === value ? 'selected' : ''}>${escapeHtml(value)}</option>`).join('')}</select></label>`; }
function billCategoryField(selected = '') {
  const saved = [...(state.data.categories || [])];
  const savedLower = new Set(saved.map(name => name.toLowerCase()));
  const suggested = expenseCategories.filter(name => !savedLower.has(name.toLowerCase()));
  if (selected && !savedLower.has(selected.toLowerCase()) && !suggested.some(name => name.toLowerCase() === selected.toLowerCase())) saved.unshift(selected);
  const options = (names) => names.map(name => `<option value="${escapeHtml(name)}" ${selected.toLowerCase() === name.toLowerCase() ? 'selected' : ''}>${escapeHtml(name)}</option>`).join('');
  return `<label>Category<select name="category" id="dialog-category-select" required><option value="" disabled ${selected ? '' : 'selected'}>Choose a category</option>${saved.length ? `<optgroup label="Your saved categories">${options(saved)}</optgroup>` : ''}<optgroup label="Suggested categories">${options(suggested)}</optgroup><option value="__new__">＋ Add a new category…</option></select></label><label class="full hidden" id="new-category-row">New category name<input name="new_category" type="text" maxlength="40" placeholder="e.g. Childcare"></label>`;
}
function billFrequencyField(selected = 'monthly') {
  return `<label>How often?<select name="frequency" id="bill-frequency">${billFrequencies.map(([value, label]) => `<option value="${value}" ${value === selected ? 'selected' : ''}>${label}</option>`).join('')}</select></label>`;
}
function updateBillForm() {
  if ($('#dialog-form')?.dataset.type !== 'bill') return;
  const frequency = $('#bill-frequency').value;
  const dayRow = $('#bill-day-row');
  const firstDueRow = $('#bill-first-due-row');
  dayRow.classList.toggle('hidden', frequency !== 'monthly');
  dayRow.querySelector('input').required = frequency === 'monthly';
  dayRow.querySelector('input').disabled = frequency !== 'monthly';
  firstDueRow.classList.toggle('hidden', frequency === 'monthly');
  firstDueRow.querySelector('input').disabled = frequency === 'monthly';
  const amount = Number($('#bill-amount').value);
  if (!Number.isFinite(amount) || amount <= 0 || amount > 100_000_000) {
    $('#bill-preview').textContent = 'Enter an amount to see its monthly average.';
    return;
  }
  const cents = Math.round(amount * 100);
  const [, , numerator, denominator] = billFrequencies.find(([value]) => value === frequency);
  const monthlyCents = Math.floor((cents * numerator + Math.floor(denominator / 2)) / denominator);
  $('#bill-preview').innerHTML = `<span>Monthly average</span><strong>${fmt(monthlyCents)}</strong>`;
}
function moneyValue(cents) { return cents == null ? '' : (cents / 100).toFixed(2); }
function categoryDatalist(suggested) {
  const choices = [...(state.data.categories || []), ...suggested];
  const seen = new Set();
  return `<datalist id="category-options">${choices.filter(name => {
    const key = name.toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).map(name => `<option value="${escapeHtml(name)}"></option>`).join('')}</datalist>`;
}
function commuteFields(item) {
  const days = new Set(String(item?.weekdays || '0,1,2,3,4').split(','));
  const leaveMode = item?.leave_mode || 'annual';
  const weekdayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  return `<label class="full">Commute name<input name="name" type="text" value="${escapeHtml(item?.name || 'Work commute')}" maxlength="60" required></label>
    <label class="full">How do you travel?<select name="mode" id="commute-mode"><option value="car" ${item?.mode !== 'public' ? 'selected' : ''}>Car</option><option value="public" ${item?.mode === 'public' ? 'selected' : ''}>Public transport</option></select></label>
    <div class="full commute-mode-fields" id="commute-car-fields"><label>Daily round-trip distance (miles)<input name="distance" type="number" min="0.01" max="500" step="0.01" value="${item?.distance_hundredths ? item.distance_hundredths / 100 : ''}" placeholder="e.g. 28"></label><label>Fuel economy (UK mpg)<input name="mpg" type="number" min="0.01" max="200" step="0.01" value="${item?.mpg_hundredths ? item.mpg_hundredths / 100 : ''}" placeholder="e.g. 42"></label><label>Fuel price per litre (${escapeHtml(currency())})<input name="fuel_price" type="number" min="0.01" step="0.01" value="${moneyValue(item?.fuel_price_cents)}" placeholder="e.g. 1.45"></label></div>
    <div class="full commute-mode-fields hidden" id="commute-public-fields"><label>Daily return fare (${escapeHtml(currency())})<input name="fare" type="number" min="0.01" step="0.01" value="${moneyValue(item?.fare_cents)}" placeholder="e.g. 8.50"></label></div>
    <fieldset class="full workday-fieldset"><legend>Which days do you commute?</legend><div class="workday-options">${weekdayNames.map((day, i) => `<label><input type="checkbox" name="weekdays" value="${i}" ${days.has(String(i)) ? 'checked' : ''}><span>${day}</span></label>`).join('')}</div></fieldset>
    <label class="full">UK bank holidays<select name="bank_holiday_region"><option value="none" ${!item || item.bank_holiday_region === 'none' ? 'selected' : ''}>Include them as workdays</option><option value="england-and-wales" ${item?.bank_holiday_region === 'england-and-wales' ? 'selected' : ''}>Exclude England & Wales holidays</option><option value="scotland" ${item?.bank_holiday_region === 'scotland' ? 'selected' : ''}>Exclude Scotland holidays</option><option value="northern-ireland" ${item?.bank_holiday_region === 'northern-ireland' ? 'selected' : ''}>Exclude Northern Ireland holidays</option></select><small>Choose an exclusion only if those days are normally off work.</small></label>
    <label class="full">How should days off be counted?<select name="leave_mode" id="commute-leave-mode"><option value="annual" ${leaveMode === 'annual' ? 'selected' : ''}>Annual leave allowance — monthly estimate</option><option value="dates" ${leaveMode === 'dates' ? 'selected' : ''}>Exact dates — precise month</option></select></label>
    <div class="full commute-leave-fields" id="commute-annual-leave-fields"><label>Annual leave days per year<input name="annual_leave_days" type="number" min="0" max="365" step="1" value="${item?.annual_leave_days ?? ''}" placeholder="e.g. 25"><small>Count days you would otherwise commute. These are spread across the year after any selected bank holidays.</small></label></div>
    <div class="full commute-leave-fields hidden" id="commute-exact-leave-fields"><label>Exact dates off<textarea name="excluded_dates" rows="3" placeholder="2026-10-12&#10;2026-12-21..2026-12-24">${escapeHtml(item?.excluded_dates || '')}</textarea><small>One date or inclusive range per line. Use YYYY-MM-DD..YYYY-MM-DD for a range.</small></label></div>
    <div class="full commute-preview"><button type="button" class="btn btn-outline" id="commute-preview-button">Preview ${monthLabel(state.month)}</button><div id="commute-preview-result" role="status">Preview to see days and cost for the selected month.</div></div>`;
}
function updateCommuteForm() {
  if ($('#dialog-form')?.dataset.type !== 'commute') return;
  const car = $('#commute-mode').value === 'car';
  for (const [id, active] of [['#commute-car-fields', car], ['#commute-public-fields', !car]]) {
    const block = $(id); block.classList.toggle('hidden', !active);
    block.querySelectorAll('input').forEach(input => { input.disabled = !active; input.required = active; });
  }
  const annual = $('#commute-leave-mode').value === 'annual';
  const annualBlock = $('#commute-annual-leave-fields');
  const exactBlock = $('#commute-exact-leave-fields');
  annualBlock.classList.toggle('hidden', !annual);
  exactBlock.classList.toggle('hidden', annual);
  annualBlock.querySelector('input').disabled = !annual;
  annualBlock.querySelector('input').required = annual;
  exactBlock.querySelector('textarea').disabled = annual;
  $('#commute-preview-result').textContent = 'Preview to see days and cost for the selected month.';
}
async function previewCommute() {
  const form = $('#dialog-form');
  const data = Object.fromEntries(new FormData(form));
  data.weekdays = new FormData(form).getAll('weekdays');
  data.month = state.month;
  const result = await api('/api/commutes/preview', { method: 'POST', body: JSON.stringify(data) });
  $('#commute-preview-result').innerHTML = `<strong>${fmt(result.monthly_cents)}</strong> · ${data.leave_mode === 'annual' ? `${result.expected_days} estimated commuting days` : `${result.workdays} commuting days`} · ${fmt(result.daily_cents)} per day${commuteAdjustmentText(result)}${result.holiday_status || result.leave_status ? `<p>${escapeHtml([result.holiday_status, result.leave_status].filter(Boolean).join(' '))}</p>` : ''}`;
}
function modal(type, item = null, duplicate = false) {
  let title, eyebrow = 'MAKE A CHANGE', fields;
  if (type === 'transaction') {
    title = duplicate ? 'Duplicate transaction' : item ? 'Edit transaction' : 'Add transaction';
    fields = `${duplicate ? '<p class="full setting-note">A new transaction will be created. Check the amount and today’s date before saving.</p>' : ''}${selectField('Type', 'kind', ['expense','income'], item?.kind || 'expense')}${field('Amount', 'amount', 'number', moneyValue(item?.amount_cents), 'min="0.01" step="0.01"')}${field('Category', 'category', 'text', item?.category || '', `list="category-options" maxlength="40"`)}${field('Date', 'occurred_on', 'date', duplicate ? localDate() : item?.occurred_on || localDate(), `max="${localDate()}"`)}<label class="full">Note (optional)<input name="note" type="text" value="${escapeHtml(item?.note || '')}" maxlength="200" placeholder="What was it for?"></label>${categoryDatalist([...expenseCategories, ...incomeCategories])}`;
  } else if (type === 'budget') {
    title = 'Set a monthly budget';
    fields = `${field('Month', 'month', 'month', state.month)}${field('Category', 'category', 'text', '', 'list="category-options" maxlength="40"')}${field('Monthly limit', 'limit', 'number', '', 'min="0.01" step="0.01"')}${categoryDatalist(expenseCategories)}`;
  } else if (type === 'goal') {
    title = item ? 'Update savings goal' : 'New savings goal';
    fields = `<div class="full">${field('Goal name', 'name', 'text', item?.name || '', 'maxlength="60"')}</div>${field('Target amount', 'target', 'number', moneyValue(item?.target_cents), 'min="0.01" step="0.01"')}${field('Saved so far', 'saved', 'number', moneyValue(item?.saved_cents) || '0', 'min="0" step="0.01"')}${field('Monthly contribution', 'monthly', 'number', moneyValue(item?.monthly_cents) || '0', 'min="0" step="0.01"')}<label>Target date (optional)<input name="target_date" type="date" value="${escapeHtml(item?.target_date || '')}"></label>`;
  } else if (type === 'bill') {
    title = item ? 'Edit regular bill' : 'Add regular bill';
    fields = `${field('Bill name', 'name', 'text', item?.name || '', 'maxlength="60"')}${billCategoryField(item?.category || '')}${billFrequencyField(item?.frequency || 'monthly')}<label>Amount each time<input id="bill-amount" name="amount" type="number" value="${moneyValue(item?.amount_cents)}" min="0.01" step="0.01" required></label><div id="bill-day-row" class="bill-day-row">${field('Day of month', 'day_of_month', 'number', item?.day_of_month || 1, 'min="1" max="31" step="1"')}</div><div id="bill-first-due-row" class="full bill-first-due-row hidden"><label>First payment date (optional)<input name="first_due_on" type="date" value="${escapeHtml(item?.first_due_on || '')}"></label><small>Set this to import weekly, quarterly or yearly payments at their real dates.</small></div><div id="bill-preview" class="bill-preview full" role="status"></div>`;
  } else if (type === 'commute') {
    title = item ? 'Edit commuting plan' : 'Add commuting plan';
    fields = commuteFields(item);
  } else {
    title = 'Create a profile'; eyebrow = 'A FRESH WORKSPACE';
    fields = `${field('Profile name', 'name', 'text', '', 'maxlength="40" placeholder="e.g. Household or Holiday"')}${selectField('Currency', 'currency', ['GBP','EUR','USD'], 'GBP')}`;
  }
  $('#dialog-eyebrow').textContent = eyebrow; $('#dialog-title').textContent = title;
  $('#dialog-body').innerHTML = `<form id="dialog-form" novalidate data-type="${type}" data-id="${duplicate ? '' : item?.id || ''}"><div class="form-grid">${fields}</div><div class="form-actions"><button type="button" class="btn btn-outline" id="dialog-cancel">Cancel</button><button type="submit" class="btn btn-primary">${duplicate ? 'Save duplicate' : item ? 'Save changes' : 'Save'}</button></div></form>`;
  $('#form-dialog').showModal();
  $('.dialog-content').scrollTop = 0;
  $('#dialog-close').focus();
  if (type === 'bill') updateBillForm();
  if (type === 'commute') updateCommuteForm();
}
async function openBillImport() {
  const preview = await api(`/api/bills/import-preview?month=${encodeURIComponent(state.month)}`);
  state.billImportPreview = preview;
  const rows = preview.items.map((item, index) => {
    const unavailable = item.already_imported || item.future;
    const note = item.already_imported ? 'Already imported' : item.future ? 'Not due yet' : item.possible_duplicate ? 'Similar expense recorded — review' : 'Ready to record';
    return `<label class="bill-import-row ${unavailable ? 'unavailable' : ''}"><input type="checkbox" name="bill-occurrence" data-index="${index}" ${unavailable ? 'disabled' : ''}><span><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(billFrequencyLabel(item.frequency))} · ${shortDate(item.due_on)} · ${escapeHtml(item.category)}</small><em class="${item.possible_duplicate ? 'duplicate-note' : ''}">${escapeHtml(note)}</em></span><b>${fmt(item.amount_cents)}</b></label>`;
  }).join('');
  const schedules = preview.needs_schedule.map(bill => `<div class="bill-schedule-item"><span>${escapeHtml(bill.name)} · ${escapeHtml(billFrequencyLabel(bill.frequency))}</span><button type="button" class="table-action" data-action="schedule-bill" data-id="${bill.id}">Set first payment date</button></div>`).join('');
  $('#dialog-eyebrow').textContent = 'REVIEW PAID BILLS';
  $('#dialog-title').textContent = 'Import bill payments';
  $('#dialog-body').innerHTML = `<form id="bill-import-form"><p class="setting-note">Choose payments you have made in ${monthLabel(state.month)}. Each becomes an expense transaction at the bill's real amount and due date. Future and previously imported payments cannot be selected.</p><div class="bill-import-toolbar"><strong>${monthLabel(state.month)}</strong><div><button type="button" class="table-action" data-action="select-ready-bills">Select all ready</button><button type="button" class="table-action" data-action="clear-import-bills">Clear</button></div></div>${rows ? `<div class="bill-import-list">${rows}</div>` : empty('▦', 'No scheduled bill payments this month', 'Monthly bills appear here; other frequencies need a first payment date.')} ${schedules ? `<div class="bill-schedule-list"><strong>Set a schedule to import these bills</strong>${schedules}</div>` : ''}<p class="setting-note">If a payment date differs from its due date, add or edit its transaction with the actual date.</p><div class="form-actions"><button type="button" class="btn btn-outline" id="dialog-cancel">Cancel</button><button type="submit" class="btn btn-primary" id="bill-import-submit" disabled>Import selected</button></div></form>`;
  $('#form-dialog').showModal();
  $('.dialog-content').scrollTop = 0;
  $('#dialog-close').focus();
}
function updateBillImportSelection() {
  const form = $('#bill-import-form'); if (!form) return;
  const checked = [...form.querySelectorAll('input[name="bill-occurrence"]:checked')];
  const amount = checked.reduce((total, input) => total + state.billImportPreview.items[Number(input.dataset.index)].amount_cents, 0);
  const submit = $('#bill-import-submit');
  submit.disabled = !checked.length;
  submit.textContent = checked.length ? `Import ${checked.length} payment${checked.length === 1 ? '' : 's'} · ${fmt(amount)}` : 'Import selected';
}
async function saveBillImport(form) {
  const selected = [...form.querySelectorAll('input[name="bill-occurrence"]:checked')].map(input => {
    const item = state.billImportPreview.items[Number(input.dataset.index)];
    return { bill_id: item.bill_id, due_on: item.due_on };
  });
  if (!selected.length) return showFormError(form, new Error('Select at least one paid bill.'));
  const result = await api('/api/bills/import', { method: 'POST', body: JSON.stringify({ month: state.month, items: selected }) });
  $('#form-dialog').close();
  await loadData();
  if (result.imported_count) await navigate('transactions');
  toast(`${result.imported_count} bill payment${result.imported_count === 1 ? '' : 's'} recorded${result.skipped_count ? `; ${result.skipped_count} already imported` : ''}.`);
}
async function saveForm(form) {
  const data = Object.fromEntries(new FormData(form));
  const type = form.dataset.type, id = form.dataset.id;
  if (type === 'commute') data.weekdays = new FormData(form).getAll('weekdays');
  if (type === 'bill' && data.category === '__new__') data.category = String(data.new_category || '').trim();
  delete data.new_category;
  const route = { transaction: 'transactions', budget: 'budgets', goal: 'goals', bill: 'bills', commute: 'commutes', profile: 'profiles' }[type];
  await api(`/api/${route}${id ? `/${id}` : ''}`, { method: id ? 'PUT' : 'POST', body: JSON.stringify(data) });
  $('#form-dialog').close();
  if (type === 'profile') await boot(); else await loadData();
  toast(itemMessage(type, id));
}
async function downloadAccount() {
  const response = await fetch('/api/account/export', { credentials: 'same-origin' });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || 'Export failed.');
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `pocket-ledger-${localDate()}.json`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast('Account export downloaded.');
}
async function uploadAccount(form) {
  const file = $('#account-import-file').files[0];
  if (!file) throw new Error('Choose an exported JSON file.');
  if (file.size > 50 * 1024 * 1024) throw new Error('The export file must be 50 MB or smaller.');
  const content = await file.text();
  const result = await api('/api/account/import', { method: 'POST', body: content });
  form.reset();
  await boot();
  toast(`Imported ${result.profiles} profile${result.profiles === 1 ? '' : 's'} and ${result.counts.transactions} transactions.`);
}
function itemMessage(type, id) { return `${type.charAt(0).toUpperCase() + type.slice(1)} ${id ? 'updated' : 'saved'}.`; }
async function deleteItem(type, id) {
  const labels = { transaction: 'transaction', budget: 'budget', goal: 'savings goal', bill: 'regular bill', commute: 'commuting plan', profile: 'profile and all its records' };
  if (!confirm(`Delete this ${labels[type]}?`)) return;
  await api(`/api/${{transaction:'transactions',budget:'budgets',goal:'goals',bill:'bills',commute:'commutes',profile:'profiles'}[type]}/${id}`, { method: 'DELETE' });
  if (type === 'profile') await boot(); else await loadData();
  toast('Deleted.');
}
function switchAuth() {
  state.authMode = state.authMode === 'login' ? 'register' : 'login';
  const register = state.authMode === 'register';
  $('#auth-title').textContent = register ? 'Create your account' : 'Welcome back';
  $('#auth-subtitle').textContent = register ? 'Start making sense of your money.' : 'Sign in to pick up where you left off.';
  $('#auth-submit').firstChild.textContent = register ? 'Create account ' : 'Sign in ';
  $('#auth-switch-label').textContent = register ? 'Already have an account?' : 'New here?';
  $('#auth-toggle').textContent = register ? 'Sign in' : 'Create an account';
  $('#password-hint').classList.toggle('hidden', !register);
  $('#auth-password').autocomplete = register ? 'new-password' : 'current-password';
  $('#auth-password').minLength = register ? 12 : 1;
  $('#auth-error').classList.add('hidden');
}
document.addEventListener('click', async event => {
  const button = event.target.closest('button'); if (!button) return;
  try {
    if (button.dataset.page) return await navigate(button.dataset.page);
    if (button.dataset.calcTab) { state.calc = button.dataset.calcTab; return render(); }
    if (button.dataset.mortgageView) { state.mortgageView = button.dataset.mortgageView; return render(); }
    if (button.id === 'auth-toggle') return switchAuth();
    if (button.id === 'menu-toggle') return toggleMenu();
    if (button.id === 'menu-scrim') return closeMenu(true);
    if (button.id === 'dialog-close' || button.id === 'dialog-cancel') return $('#form-dialog').close();
    if (button.id === 'commute-preview-button') {
      try { return await previewCommute(); }
      catch (error) { return showFormError($('#dialog-form'), error); }
    }
    if (button.id === 'quick-add') return modal('transaction');
    if (button.id === 'profile-shortcut') return await navigate('settings');
    if (button.id === 'logout') { await api('/api/logout', { method: 'POST' }); state.data = null; return boot(); }
    const action = button.dataset.action, id = Number(button.dataset.id);
    if (!action) return;
    if (action === 'select-profile') { await api(`/api/profiles/${id}/select`, { method: 'POST' }); await boot(); await navigate('dashboard'); return toast('Profile switched.'); }
    if (action === 'export-data') return await downloadAccount();
    if (action === 'import-bills') return await openBillImport();
    if (action === 'select-ready-bills') { $('#bill-import-form').querySelectorAll('input[name="bill-occurrence"]').forEach(input => { const item = state.billImportPreview.items[Number(input.dataset.index)]; input.checked = !input.disabled && !item.possible_duplicate; }); return updateBillImportSelection(); }
    if (action === 'clear-import-bills') { $('#bill-import-form').querySelectorAll('input[name="bill-occurrence"]').forEach(input => { input.checked = false; }); return updateBillImportSelection(); }
    if (action === 'schedule-bill') { $('#form-dialog').close(); return modal('bill', state.data.bills.find(bill => bill.id === id)); }
    if (action === 'tx-prev' || action === 'tx-next') { state.txOffset = Math.max(0, state.txOffset + (action === 'tx-next' ? 50 : -50)); return await loadTransactions(); }
    if (action === 'duplicate-transaction') {
      const item = state.transactions?.transactions.find(tx => tx.id === id);
      if (!item) throw new Error('Transaction is no longer on this page. Refresh and try again.');
      return modal('transaction', item, true);
    }
    if (action.startsWith('add-')) return modal(action.slice(4));
    if (action.startsWith('edit-')) { const type = action.slice(5); const list = { transaction: state.transactions?.transactions || [], goal: state.data.goals, bill: state.data.bills, commute: state.data.commutes || [] }[type]; return modal(type, list.find(item => item.id === id)); }
    if (action.startsWith('delete-')) return await deleteItem(action.slice(7), id);
  } catch (error) { showError(error); }
});
document.addEventListener('submit', async event => {
  if (event.target.id === 'auth-form') {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.target));
    try { await api(`/api/${state.authMode}`, { method: 'POST', body: JSON.stringify(data) }); await boot(); }
    catch (error) { $('#auth-error').textContent = error.message; $('#auth-error').classList.remove('hidden'); }
  } else if (event.target.id === 'dialog-form') {
    event.preventDefault();
    clearFormError(event.target);
    const submit = event.target.querySelector('[type="submit"]'); submit.disabled = true;
    try { await saveForm(event.target); } catch (error) { showFormError(event.target, error); } finally { submit.disabled = false; }
  } else if (event.target.id === 'bill-import-form') {
    event.preventDefault();
    const submit = $('#bill-import-submit'); submit.disabled = true;
    try { await saveBillImport(event.target); } catch (error) { showFormError(event.target, error); } finally { submit.disabled = false; }
  } else if (event.target.id === 'account-import-form') {
    event.preventDefault();
    clearFormError(event.target);
    const submit = event.target.querySelector('[type="submit"]'); submit.disabled = true;
    try { await uploadAccount(event.target); } catch (error) { showFormError(event.target, error); } finally { submit.disabled = false; }
  } else if (event.target.id === 'password-form') {
    event.preventDefault();
    clearFormError(event.target);
    const data = Object.fromEntries(new FormData(event.target));
    if (data.new_password !== data.confirm_password) return showFormError(event.target, new Error('New passwords do not match.'));
    const submit = event.target.querySelector('[type="submit"]'); submit.disabled = true;
    try {
      await api('/api/password', { method: 'POST', body: JSON.stringify({ current_password: data.current_password, new_password: data.new_password }) });
      await boot(); toast('Password changed. Other sessions were signed out.');
    } catch (error) { showFormError(event.target, error); } finally { submit.disabled = false; }
  }
});
document.addEventListener('change', async event => {
  if (event.target.name === 'bill-occurrence') updateBillImportSelection();
  if (event.target.id === 'month-picker') { state.month = event.target.value; try { await loadData(); } catch (error) { showError(error); } }
  if (event.target.id === 'kind-filter') { state.kind = event.target.value; state.txOffset = 0; try { await loadTransactions(); } catch (error) { showError(error); } }
  if (event.target.id === 'bill-frequency') updateBillForm();
  if (event.target.id === 'commute-mode') updateCommuteForm();
  if (event.target.id === 'commute-leave-mode') updateCommuteForm();
  if (event.target.id === 'dialog-category-select') {
    const adding = event.target.value === '__new__';
    $('#new-category-row').classList.toggle('hidden', !adding);
    const input = $('#new-category-row input'); input.required = adding;
    if (adding) input.focus(); else input.value = '';
  }
  if (event.target.dataset.mortgage) { state.mortgageInputs[event.target.dataset.mortgage] = event.target.value; updateCalculator(); }
});
document.addEventListener('input', event => {
  if (event.target.id === 'bill-amount') updateBillForm();
  if (event.target.id === 'transaction-search') {
    state.filter = event.target.value; state.txOffset = 0;
    clearTimeout(state.searchTimer);
    state.searchTimer = setTimeout(() => loadTransactions().catch(showError), 250);
  }
  if (event.target.dataset.calc) {
    if (state.calc === 'mortgage') state.mortgageInputs[event.target.dataset.calc] = event.target.value;
    updateCalculator();
  }
});
boot().catch(showError);
