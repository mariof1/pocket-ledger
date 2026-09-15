const test = require('node:test');
const assert = require('node:assert/strict');
const guide = require('./static/mortgage-guide.js');

const base = {
  price: 300000, deposit: 30000, rate: 4.5, years: 25,
  grossAnnual: 60000, netMonthly: 3600, debtsMonthly: 200,
  livingMonthly: 700, childcareMonthly: 0, homeMonthly: 300,
  dependants: 0, applicants: 1, fixedYears: 5,
  buyer: 'ftb', employment: 'employed', premier: false,
};

test('payment and monthly budget respond to rate increases', () => {
  assert.equal(guide.payment(120000, 0, 10), 1000);
  const result = guide.screen(base);
  assert.ok(result.monthly > 1500 && result.monthly < 1501);
  assert.ok(result.sensitivity > result.monthly);
  assert.ok(result.budget.higherRate < result.budget.current);
  const tight = guide.screen({ ...base, netMonthly: 2600 });
  assert.ok(tight.budget.current < 0);
});

test('Nationwide Helping Hand checks fixed term, income and employment', () => {
  const eligible = guide.screen({ ...base, price: 200000, deposit: 10000, grossAnnual: 35000 });
  assert.equal(eligible.lenders[0].multiple, 6);
  assert.equal(eligible.lenders[0].withinCap, true);
  assert.equal(guide.screen({ ...base, employment: 'self' }).lenders[0].multiple, 4.49);
  assert.equal(guide.screen({ ...base, fixedYears: 2 }).lenders[0].multiple, 4.49);
  assert.equal(guide.screen({ ...base, price: 200000, deposit: 10000, fixedYears: 10 }).lenders[0].multiple, 4.49);
  assert.equal(guide.screen({ ...base, buyer: 'mover', grossAnnual: 80000 }).lenders[0].multiple, 6);
  assert.equal(guide.screen({ ...base, buyer: 'mover', grossAnnual: 45000, nationwideExisting: true }).lenders[0].multiple, 6);
});

test('HSBC enhanced caps and Santander income/LTV bands are conditional', () => {
  assert.equal(guide.screen(base).lenders[1].multiple, 5.5);
  assert.equal(guide.screen({ ...base, grossAnnual: 34000 }).lenders[1].multiple, null);
  assert.equal(guide.screen({ ...base, premier: true }).lenders[1].multiple, 6.5);
  assert.equal(guide.screen(base).lenders[2].multiple, 5);
  assert.equal(guide.screen({ ...base, deposit: 15000, propertyType: 'house' }).lenders[2].multiple, 4.45);
  assert.equal(guide.screen({ ...base, grossAnnual: 120000 }).lenders[2].multiple, 5.5);
  assert.equal(guide.screen({ ...base, deposit: 15000, employment: 'self' }).lenders[2].multiple, null);
  assert.equal(guide.screen({ ...base, price: 500000, deposit: 30000 }).lenders[2].multiple, null);
  assert.equal(guide.screen({ ...base, price: 500000, deposit: 30000, propertyType: 'house' }).lenders[2].multiple, 4.45);
  assert.equal(guide.screen({ ...base, price: 500000, deposit: 30000, propertyType: 'flat' }).lenders[2].multiple, null);
});

test('invalid inputs and loans above sampled LTV are not treated as eligible', () => {
  assert.ok(guide.screen({ ...base, deposit: 310000 }).error);
  assert.ok(guide.screen({ ...base, years: 45 }).error);
  assert.ok(guide.screen({ ...base, grossAnnual: 1e308 }).error);
  assert.ok(guide.screen({ ...base, price: 1e308 }).error);
  const result = guide.screen({ ...base, deposit: 3000 });
  assert.equal(result.lenders.every(item => item.multiple === null), true);
  assert.equal(result.hasPublishedCap, false);
});

test('published cap comparison stops claiming a match after the review window', () => {
  const result = guide.screen(base, new Date('2026-11-15T00:00:00Z'));
  assert.equal(result.stale, true);
  assert.equal(result.hasPublishedCap, false);
  assert.equal(result.lenders.some(item => item.withinCap), true);
});

test('Santander criteria link points to the current lender page', () => {
  assert.equal(guide.sources.santander,
    'https://www.santanderforintermediaries.co.uk/lending-criteria/residential-lending-criteria');
});
