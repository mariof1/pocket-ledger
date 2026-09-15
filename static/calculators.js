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
