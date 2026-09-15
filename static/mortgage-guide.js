/* UK mortgage planning checks. Published caps are ceilings, not lender decisions. */
(function (root, factory) {
  const guide = factory();
  if (typeof module === 'object' && module.exports) module.exports = guide;
  if (root) root.MortgageGuide = guide;
})(typeof window !== 'undefined' ? window : null, function () {
  const sources = {
    nationwide: 'https://www.nationwide-intermediary.co.uk/lending-criteria/affordability',
    helpingHand: 'https://www.nationwide-intermediary.co.uk/products/helping-hand',
    helpingHandIncome: 'https://www.nationwide-intermediary.co.uk/news/helping-hand-updates',
    hsbc: 'https://www.hsbc.co.uk/mortgages/how-much-can-i-borrow/',
    santander: 'https://www.santanderforintermediaries.co.uk/lending-criteria/residential-lending-criteria',
    santanderHighLtv: 'https://www.santanderforintermediaries.co.uk/products/high-ltv-mortgages',
    natwest: 'https://www.natwest.com/mortgages/mortgage-calculators/how-much-can-i-borrow.html',
    fca: 'https://www.fca.org.uk/firms/interest-rate-stress-test-rule',
  };

  function payment(principal, rate, years) {
    if (principal <= 0) return 0;
    const count = Math.round(years * 12);
    if (count <= 0) return NaN;
    const monthlyRate = rate / 1200;
    return monthlyRate === 0 ? principal / count : principal * monthlyRate / (1 - Math.pow(1 + monthlyRate, -count));
  }

  function lender(name, multiple, loan, income, reason, source, scheme = '') {
    return {
      name, multiple, ceiling: multiple == null ? null : income * multiple,
      withinCap: multiple == null ? null : loan <= income * multiple + 0.01,
      reason, source, scheme,
    };
  }

  function screen(input, asOf = new Date()) {
    const price = Number(input.price), deposit = Number(input.deposit), rate = Number(input.rate);
    const years = Number(input.years), income = Number(input.grossAnnual);
    const net = Number(input.netMonthly), debts = Number(input.debtsMonthly);
    const living = Number(input.livingMonthly), childcare = Number(input.childcareMonthly);
    const home = Number(input.homeMonthly), dependants = Number(input.dependants);
    const applicants = Number(input.applicants), fixedYears = Number(input.fixedYears);
    const buyer = input.buyer, employment = input.employment;
    const propertyType = input.propertyType || 'unknown';
    const premier = Boolean(input.premier), nationwideExisting = Boolean(input.nationwideExisting);
    const amounts = [price, deposit, rate, years, income, net, debts, living, childcare, home, dependants];
    if (amounts.some(value => !Number.isFinite(value)) || price <= 0 || price > 100_000_000 ||
        deposit < 0 || deposit >= price || rate < 0 || rate > 30 || years < 1 || years > 40 ||
        income < 0 || income > 100_000_000 || net < 0 || net > 10_000_000 ||
        [debts, living, childcare, home].some(value => value < 0 || value > 10_000_000) ||
        dependants < 0 || dependants > 20 ||
        !Number.isInteger(dependants) ||
        ![1, 2].includes(applicants) || ![2, 5, 10].includes(fixedYears) ||
        !['ftb', 'mover'].includes(buyer) || !['employed', 'self'].includes(employment) ||
        !['unknown', 'house', 'flat'].includes(propertyType)) {
      return { error: 'Check the home price, deposit, rate, term and household figures. The deposit must be less than the price.' };
    }
    const loan = price - deposit, ltv = loan / price * 100;
    const monthly = payment(loan, rate, years);
    const sensitivity = payment(loan, rate + 2, years);
    const outgoings = debts + living + childcare + home;
    const budget = net > 0 ? { current: net - outgoings - monthly, higherRate: net - outgoings - sensitivity } : null;
    const lenders = [];

    if (income > 0 && ltv <= 95) {
      const helpingEligible = buyer === 'ftb' && employment === 'employed' && fixedYears >= 5 &&
        income >= (applicants === 1 ? 30000 : 50000) && ltv <= (fixedYears === 10 ? 90 : 95);
      const moverHighIncome = buyer === 'mover' && income >= 75000;
      const moverExisting = buyer === 'mover' && nationwideExisting;
      const enhanced = helpingEligible || moverHighIncome || moverExisting;
      const scheme = helpingEligible ? 'Helping Hand' : moverExisting ? 'Existing customer' : moverHighIncome ? 'High-income mover' : 'Standard';
      const reason = helpingEligible ? 'Helping Hand: qualifying first-time buyer, 5 or 10-year fixed rate.' :
        moverExisting ? 'Existing Nationwide mover: published higher cap, subject to individual criteria.' :
        moverHighIncome ? 'New home mover with at least £75,000 eligible income: published higher cap.' :
        'Standard published cap. Other Nationwide schemes may still apply.';
      lenders.push(lender('Nationwide', enhanced ? 6 : 4.49, loan, income,
        reason, helpingEligible ? sources.helpingHand : sources.nationwide, scheme));
    } else {
      lenders.push(lender('Nationwide', null, loan, income,
        ltv > 95 ? 'Above the 95% LTV used for this screen.' : 'Add gross annual income to compare.',
        sources.nationwide));
    }

    if (income > 0 && ltv <= 90 && premier) {
      lenders.push(lender('HSBC', 6.5, loan, income,
        'Premier customers may be able to borrow up to 6.5× income.', sources.hsbc, 'Premier'));
    } else if (income > 0 && ltv <= 90 && buyer === 'ftb' &&
               income >= (applicants === 1 ? 35000 : 55000)) {
      lenders.push(lender('HSBC', 5.5, loan, income,
        'First-time buyer enhanced cap with qualifying income and up to 90% LTV.', sources.hsbc, 'First-time buyer'));
    } else {
      lenders.push(lender('HSBC', null, loan, income,
        'Enhanced first-time buyer/Premier cap does not fit these inputs; standard HSBC lending needs its own calculator.',
        sources.hsbc));
    }

    const santanderHighLtvNeedsReview = ltv > 90 &&
      (employment === 'self' || propertyType === 'unknown' ||
       price > (propertyType === 'flat' ? 400000 : 600000) ||
       loan > (propertyType === 'flat' ? 380000 : 570000));
    if (income > 0 && ltv <= 95 && !santanderHighLtvNeedsReview) {
      const multiple = income < 45000 ? 4.45 : (ltv > 90 ? 4.45 : income < 100000 ? 5 : 5.5);
      lenders.push(lender('Santander', multiple, loan, income,
        'Published capital-and-interest LTI band for this income and LTV.', sources.santander, 'Residential'));
    } else {
      lenders.push(lender('Santander', null, loan, income,
        ltv > 95 ? 'Standard screen stops at 95% LTV; a separate first-time buyer scheme may apply.' :
          santanderHighLtvNeedsReview ? 'Over 90% LTV, property type, value or self-employment needs a direct product check.' :
          'Add gross annual income to compare.',
        santanderHighLtvNeedsReview || ltv > 95 ? sources.santanderHighLtv : sources.santander));
    }

    const checkedAt = new Date('2026-09-15T00:00:00Z');
    const stale = asOf.getTime() - checkedAt.getTime() > 45 * 24 * 60 * 60 * 1000;
    return {
      loan, ltv, multiple: income > 0 ? loan / income : null,
      monthly, sensitivity, outgoings, budget, lenders,
      hasPublishedCap: !stale && lenders.some(item => item.withinCap === true),
      checked: '15 September 2026', stale, sources,
    };
  }
  return { payment, screen, sources };
});
