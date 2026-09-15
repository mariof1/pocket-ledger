function itemMessage(type, id) { return `${type.charAt(0).toUpperCase() + type.slice(1)} ${id ? 'updated' : 'saved'}.`; }
async function deleteItem(type, id) {
  const labels = { transaction: 'transaction', account: 'account', transfer: 'transfer', budget: 'budget', goal: 'savings goal', bill: 'regular bill', commute: 'commuting plan', profile: 'profile and all its records' };
  if (!confirm(`Delete this ${labels[type]}?`)) return;
  await api(`/api/${{transaction:'transactions',account:'accounts',transfer:'transfers',budget:'budgets',goal:'goals',bill:'bills',commute:'commutes',profile:'profiles'}[type]}/${id}`, { method: 'DELETE' });
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
    if (button.id === 'dialog-close' || button.id === 'dialog-cancel') { state.statement = null; return $('#form-dialog').close(); }
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
    if (action === 'import-statement') return openStatementImport();
    if (action === 'statement-back-file') return openStatementImport();
    if (action === 'statement-back-map') return renderStatementMapping();
    if (action === 'statement-select-clean') { $('#statement-review-form').querySelectorAll('.statement-review-row').forEach(row => { const item = state.statement.preview.rows.find(item => item.row_number === Number(row.dataset.row)); row.querySelector('[name="include"]').checked = !item.error && !item.duplicate; }); return updateStatementSelection(); }
    if (action === 'statement-clear') { $('#statement-review-form').querySelectorAll('[name="include"]').forEach(input => { input.checked = false; }); return updateStatementSelection(); }
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
    if (action.startsWith('edit-')) { const type = action.slice(5); const list = { transaction: state.transactions?.transactions || [], account: state.data.accounts, transfer: state.data.transfers, goal: state.data.goals, bill: state.data.bills, commute: state.data.commutes || [] }[type]; return modal(type, list.find(item => item.id === id)); }
    if (action.startsWith('delete-')) return await deleteItem(action.slice(7), id);
  } catch (error) { showError(error); }
});
document.addEventListener('submit', async event => {
  if (event.target.id === 'statement-file-form') {
    event.preventDefault();
  } else if (event.target.id === 'statement-mapping-form') {
    event.preventDefault();
    clearFormError(event.target);
    const submit = event.target.querySelector('[type="submit"]'); submit.disabled = true;
    try { await previewStatement(event.target); } catch (error) { showFormError(event.target, error); } finally { submit.disabled = false; }
  } else if (event.target.id === 'statement-review-form') {
    event.preventDefault();
    clearFormError(event.target);
    const submit = $('#statement-save'); submit.disabled = true;
    try { await saveStatement(event.target); } catch (error) { showFormError(event.target, error); } finally { submit.disabled = false; }
  } else if (event.target.id === 'auth-form') {
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
  if (event.target.id === 'statement-file') {
    try { await readStatementFile(event.target); }
    catch (error) { showFormError($('#statement-file-form'), error); }
  }
  if (event.target.name === 'include' && event.target.closest('#statement-review-form')) updateStatementSelection();
  if (event.target.name === 'bill-occurrence') updateBillImportSelection();
  if (event.target.id === 'month-picker') { state.month = event.target.value; try { await loadData(); } catch (error) { showError(error); } }
  if (event.target.id === 'kind-filter') { state.kind = event.target.value; state.txOffset = 0; try { await loadTransactions(); } catch (error) { showError(error); } }
  if (event.target.id === 'account-filter') { state.accountFilter = event.target.value; state.txOffset = 0; try { await loadTransactions(); } catch (error) { showError(error); } }
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
$('#form-dialog').addEventListener('close', () => { state.statement = null; });
boot().catch(showError);
