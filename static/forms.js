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
    fields = `${duplicate ? '<p class="full setting-note">A new transaction will be created. Check the amount and today’s date before saving.</p>' : ''}${accountField('Account', 'account_id', item?.account_id)}${selectField('Type', 'kind', ['expense','income'], item?.kind || 'expense')}${field('Amount', 'amount', 'number', moneyValue(item?.amount_cents), 'min="0.01" step="0.01"')}${field('Category', 'category', 'text', item?.category || '', `list="category-options" maxlength="40"`)}${field('Date', 'occurred_on', 'date', duplicate ? localDate() : item?.occurred_on || localDate(), `max="${localDate()}"`)}<label class="full">Note (optional)<input name="note" type="text" value="${escapeHtml(item?.note || '')}" maxlength="200" placeholder="What was it for?"></label>${categoryDatalist([...expenseCategories, ...incomeCategories])}`;
  } else if (type === 'account') {
    title = item ? 'Edit account' : 'Add account'; eyebrow = 'YOUR MONEY IN ONE PLACE';
    fields = `${field('Account name', 'name', 'text', item?.name || '', 'maxlength="40" placeholder="e.g. Main current or Holiday savings"')}<label>Account type<select name="kind"><option value="current" ${!item || item.kind === 'current' ? 'selected' : ''}>Current account</option><option value="savings" ${item?.kind === 'savings' ? 'selected' : ''}>Savings account</option><option value="card" ${item?.kind === 'card' ? 'selected' : ''}>Card account</option></select></label>${field('Opening balance', 'opening_balance', 'number', moneyValue(item?.opening_balance_cents) || '0.00', 'step="0.01" min="-100000000" max="100000000"')}<p class="full setting-note">Enter the balance before the first transaction you record here. For a card with an amount owed, enter a negative opening balance. Editing this amount recalculates the balance.</p>`;
  } else if (type === 'transfer') {
    title = item ? 'Edit transfer' : 'Transfer between accounts'; eyebrow = 'MOVE MONEY';
    const source = item?.source_account_id || state.data.accounts.find(account => account.kind === 'current')?.id || state.data.accounts[0].id;
    const target = item?.target_account_id || state.data.accounts.find(account => account.id !== source)?.id;
    fields = `${accountField('From account', 'source_account_id', source)}${accountField('To account', 'target_account_id', target)}${field('Amount moved', 'amount', 'number', moneyValue(item?.amount_cents), 'min="0.01" step="0.01"')}${field('Transfer date', 'occurred_on', 'date', item?.occurred_on || localDate(), `max="${localDate()}"`)}<label class="full">Note (optional)<input name="note" maxlength="200" value="${escapeHtml(item?.note || '')}" placeholder="e.g. Move to holiday savings"></label><p class="full setting-note">This reduces one account balance and increases the other by the same amount. It does not count as spending or income.</p>`;
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
function statementDialog(title, content) {
  $('#dialog-eyebrow').textContent = 'REVIEW BANK STATEMENT';
  $('#dialog-title').textContent = title;
  $('#dialog-body').innerHTML = content;
  if (!$('#form-dialog').open) $('#form-dialog').showModal();
  $('.dialog-content').scrollTop = 0;
  $('#dialog-close').focus();
}
function openStatementImport() {
  state.statement = null;
  statementDialog('Import a CSV statement', `<form id="statement-file-form" novalidate><p class="setting-note">Choose a CSV file from your bank. Your statement is reviewed here before any transaction is saved. Up to 500 rows and 1 MB per file.</p><label class="statement-file-label">CSV statement<input id="statement-file" type="file" accept=".csv,text/csv" required></label><p class="setting-note">The app can read UTF-8 and common Windows CSV exports. Review dates, signs and duplicates carefully; bank files vary.</p><div class="form-actions"><button type="button" class="btn btn-outline" id="dialog-cancel">Cancel</button></div></form>`);
}
async function readStatementFile(input) {
  const file = input.files?.[0];
  if (!file) return;
  if (file.size > 1_000_000) throw new Error('The CSV statement must be 1 MB or smaller.');
  const bytes = await file.arrayBuffer();
  let text;
  try { text = new TextDecoder('utf-8', { fatal: true }).decode(bytes); }
  catch { text = new TextDecoder('windows-1252').decode(bytes); }
  const inspected = await api('/api/statements/inspect', { method: 'POST', body: JSON.stringify({ text }) });
  state.statement = { text, filename: file.name, inspected, preview: null };
  renderStatementMapping();
}
function statementColumnSelect(key, label, mapping, headers) {
  const selected = mapping[key];
  return `<label>${label}<select name="${key}"><option value="">${key === 'date' ? 'Choose date column' : 'Not in this file'}</option>${headers.map((header, index) => `<option value="${index}" ${selected === index ? 'selected' : ''}>${escapeHtml(header)} (column ${index + 1})</option>`).join('')}</select></label>`;
}
function renderStatementMapping() {
  const { inspected, filename } = state.statement;
  const { headers, mapping, sample } = inspected;
  const selectors = [['date', 'Transaction date'], ['description', 'Description / payee'],
                     ['amount', 'Signed amount'], ['debit', 'Debit / money out'],
                     ['credit', 'Credit / money in'], ['category', 'Category (optional)']]
    .map(([key, label]) => statementColumnSelect(key, label, mapping, headers)).join('');
  statementDialog('Map statement columns', `<form id="statement-mapping-form" novalidate><p class="setting-note"><strong>${escapeHtml(filename)}</strong> · ${inspected.row_count} rows. Match the bank's headers below. Use either one signed amount column or separate debit and credit columns.</p><div class="statement-mapping-grid">${selectors}<label>Date order<select name="date_order"><option value="dmy">Day / month / year (UK)</option><option value="mdy">Month / day / year</option><option value="ymd">Year / month / day</option></select></label><label>Decimal separator<select name="decimal_mark"><option value="dot">Dot, e.g. 1,234.56</option><option value="comma">Comma, e.g. 1.234,56</option></select></label><label>Signed amount direction<select name="positive_expense"><option value="false">Negative = expense, positive = income</option><option value="true">Positive = expense, negative = income</option></select></label></div><div class="statement-sample"><strong>Sample from the file</strong><div class="table-wrap"><table class="data-table"><thead><tr>${headers.map(header => `<th>${escapeHtml(header)}</th>`).join('')}</tr></thead><tbody>${sample.map(row => `<tr>${row.map(cell => `<td>${escapeHtml(cell)}</td>`).join('')}</tr>`).join('')}</tbody></table></div></div><div class="form-actions"><button type="button" class="btn btn-outline" data-action="statement-back-file">Choose another file</button><button type="submit" class="btn btn-primary">Preview rows</button></div></form>`);
}
async function previewStatement(form) {
  const data = Object.fromEntries(new FormData(form));
  const mapping = {};
  for (const key of ['date', 'description', 'amount', 'debit', 'credit', 'category']) {
    if (data[key] !== '') mapping[key] = Number(data[key]);
  }
  const result = await api('/api/statements/preview', { method: 'POST', body: JSON.stringify({
    text: state.statement.text, mapping, date_order: data.date_order,
    decimal_mark: data.decimal_mark, positive_expense: data.positive_expense === 'true'
  }) });
  state.statement.preview = result;
  renderStatementReview();
}
function statementReviewRow(item) {
  const alreadyImported = item.duplicate === 'already imported from this file';
  const warning = item.error || (alreadyImported ? 'Already imported from this CSV — unavailable' : item.duplicate ? `${item.duplicate.charAt(0).toUpperCase()}${item.duplicate.slice(1)} — review before including` : 'Ready to import');
  const isDuplicate = Boolean(item.duplicate);
  const number = item.row_number;
  const fields = `<div class="statement-row-fields">
    <label>Date<input name="occurred_on" type="date" aria-label="Row ${number} date" value="${escapeHtml(item.occurred_on || '')}"></label>
    <label>Type<select name="kind" aria-label="Row ${number} type"><option value="expense" ${item.kind !== 'income' ? 'selected' : ''}>Expense</option><option value="income" ${item.kind === 'income' ? 'selected' : ''}>Income</option></select></label>
    <label>Amount<input name="amount" inputmode="decimal" aria-label="Row ${number} amount" value="${escapeHtml(item.amount || item.raw_amount || '')}"></label>
    <label>Category<input name="category" list="statement-categories" maxlength="40" aria-label="Row ${number} category" value="${escapeHtml(item.category || 'Other')}"></label>
    <label class="statement-note-label">Description<input name="note" maxlength="200" aria-label="Row ${number} description" value="${escapeHtml(item.note || '')}"></label>
  </div>`;
  return `<div class="statement-review-row ${item.error || isDuplicate ? 'statement-caution' : ''}" data-row="${number}"><div class="statement-row-top"><label><input type="checkbox" name="include" ${item.include ? 'checked' : ''} ${alreadyImported ? 'disabled' : ''}> Include row ${number}</label><span>${escapeHtml(warning)}</span></div>${fields}${isDuplicate && !alreadyImported ? `<label class="statement-override"><input type="checkbox" name="allow_duplicate"> I checked row ${number} and want a second transaction for this payment</label>` : ''}${item.error ? `<small class="statement-raw">Original date: ${escapeHtml(item.raw_date)} · amount: ${escapeHtml(item.raw_amount)}</small>` : ''}</div>`;
}
function renderStatementReview() {
  const { preview, filename } = state.statement;
  const cats = [...new Set([...state.data.categories, ...expenseCategories, ...incomeCategories])];
  statementDialog('Review statement rows', `<form id="statement-review-form" novalidate><p class="setting-note"><strong>${escapeHtml(filename)}</strong> · ${preview.row_count} rows. Check dates, expense/income signs and categories. Exact and probable duplicates are skipped by default; you can explicitly include a legitimate repeat.</p><div class="import-account-choice">${accountField('Import into account')}</div><div class="statement-review-toolbar"><div><button type="button" class="table-action" data-action="statement-select-clean">Select ready rows</button><button type="button" class="table-action" data-action="statement-clear">Clear selection</button></div><strong id="statement-selection-summary" aria-live="polite"></strong></div><datalist id="statement-categories">${cats.map(cat => `<option value="${escapeHtml(cat)}"></option>`).join('')}</datalist><div class="statement-review-list">${preview.rows.map(statementReviewRow).join('')}</div><p class="setting-note">Only checked rows are saved. A failed batch saves no transactions. After import, the file and import count appear in this profile's history.</p><div class="form-actions"><button type="button" class="btn btn-outline" data-action="statement-back-map">Back to columns</button><button type="submit" class="btn btn-primary" id="statement-save" disabled>Import selected</button></div></form>`);
  updateStatementSelection();
}
function updateStatementSelection() {
  const form = $('#statement-review-form'); if (!form) return;
  const selected = [...form.querySelectorAll('.statement-review-row input[name="include"]:checked')];
  $('#statement-selection-summary').textContent = `${selected.length} of ${state.statement.preview.row_count} selected`;
  const submit = $('#statement-save');
  submit.disabled = !selected.length;
  submit.textContent = selected.length ? `Import ${selected.length} transaction${selected.length === 1 ? '' : 's'}` : 'Import selected';
}
async function saveStatement(form) {
  const rows = [...form.querySelectorAll('.statement-review-row')].filter(row => row.querySelector('[name="include"]').checked).map(row => ({
    row_number: Number(row.dataset.row), occurred_on: row.querySelector('[name="occurred_on"]').value,
    kind: row.querySelector('[name="kind"]').value, amount: row.querySelector('[name="amount"]').value,
    category: row.querySelector('[name="category"]').value, note: row.querySelector('[name="note"]').value,
    allow_duplicate: Boolean(row.querySelector('[name="allow_duplicate"]')?.checked)
  }));
  if (!rows.length) throw new Error('Select at least one row to import.');
  const result = await api('/api/statements/save', { method: 'POST', body: JSON.stringify({
    text: state.statement.text, filename: state.statement.filename,
    profile_id: state.statement.preview.profile_id,
    account_id: form.querySelector('[name="account_id"]').value, rows
  }) });
  state.statement = null;
  $('#form-dialog').close();
  state.txOffset = 0;
  await loadData();
  toast(`${result.imported_count} transactions imported; ${result.skipped_count} rows skipped.`);
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
  $('#dialog-body').innerHTML = `<form id="bill-import-form"><p class="setting-note">Choose payments you have made in ${monthLabel(state.month)}. Each becomes an expense transaction at the bill's real amount and due date. Future and previously imported payments cannot be selected.</p><div class="import-account-choice">${accountField('Pay from account')}</div><div class="bill-import-toolbar"><strong>${monthLabel(state.month)}</strong><div><button type="button" class="table-action" data-action="select-ready-bills">Select all ready</button><button type="button" class="table-action" data-action="clear-import-bills">Clear</button></div></div>${rows ? `<div class="bill-import-list">${rows}</div>` : empty('▦', 'No scheduled bill payments this month', 'Monthly bills appear here; other frequencies need a first payment date.')} ${schedules ? `<div class="bill-schedule-list"><strong>Set a schedule to import these bills</strong>${schedules}</div>` : ''}<p class="setting-note">If a payment date differs from its due date, add or edit its transaction with the actual date.</p><div class="form-actions"><button type="button" class="btn btn-outline" id="dialog-cancel">Cancel</button><button type="submit" class="btn btn-primary" id="bill-import-submit" disabled>Import selected</button></div></form>`;
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
  const result = await api('/api/bills/import', { method: 'POST', body: JSON.stringify({
    month: state.month, items: selected,
    account_id: form.querySelector('[name="account_id"]').value
  }) });
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
  const route = { transaction: 'transactions', account: 'accounts', transfer: 'transfers', budget: 'budgets', goal: 'goals', bill: 'bills', commute: 'commutes', profile: 'profiles' }[type];
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
