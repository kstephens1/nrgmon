const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const html = fs.readFileSync(process.env.KIOSK_HTML || 'kiosk/index.html', 'utf8');
const script = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)][0][1];

function run(config = {}, hostname = '192.168.6.238') {
  const elements = Object.fromEntries(['page', 'energy', 'flow', 'history'].map(id => [id, {
    hidden: id === 'energy', src: '', style: {}, parentElement: { getBoundingClientRect: () => ({ width: 1280, height: 540 }) }, removeAttribute(name) { if (name === 'src') this.src = ''; },
  }]));
  let next;
  vm.runInNewContext(script, {
    URL, document: { getElementById: id => elements[id] },
    window: { NRGMonKioskConfig: config, location: { hostname }, setInterval(callback) { next = callback; }, addEventListener() {}, clearTimeout() {}, setTimeout() {} },
  });
  return { elements, next };
}

test('default kiosk fills both solo panels and refreshes without a dashboard toolbar', () => {
  const { elements, next } = run();
  assert.equal(elements.page.hidden, true);
  assert.equal(elements.energy.hidden, false);
  for (const [id, panelId] of [['flow', '10'], ['history', '4']]) {
    const u = new URL(elements[id].src);
    assert.equal(u.pathname, '/d-solo/solar-generation/solar-generation');
    assert.equal(u.searchParams.get('panelId'), panelId);
    assert.equal(u.searchParams.get('from'), 'now-12h');
    assert.equal(u.searchParams.get('to'), 'now');
    assert.equal(u.searchParams.get('refresh'), '1m');
  }
  assert.equal(next, undefined);
});

test('configured time range survives while other pages rotate and inactive frames stop loading', () => {
  const { elements, next } = run({ grafanaPort: 3100, pages: [
    'http://{{HOST}}:3100/d/solar-generation/custom-slug?orgId=2&from=now-6h&to=now&refresh=30s&viewPanel=panel-10',
    'https://example.net/status?kiosk',
  ] });
  const u = new URL(elements.history.src);
  assert.equal(u.port, '3100');
  assert.equal(u.searchParams.get('orgId'), '2');
  assert.equal(u.searchParams.get('from'), 'now-6h');
  assert.equal(u.searchParams.get('refresh'), '30s');
  assert.equal(u.searchParams.has('viewPanel'), false);
  next();
  assert.equal(elements.energy.hidden, true);
  assert.equal(elements.page.hidden, false);
  assert.equal(elements.page.src, 'https://example.net/status?kiosk');
  assert.equal(elements.flow.src, '');
  assert.equal(elements.history.src, '');
  next();
  assert.equal(elements.energy.hidden, false);
  assert.equal(elements.page.src, '');
});

test('other Grafana hosts, ports and dashboards retain their requested page', () => {
  for (const page of [
    'http://other-host:3000/d/solar-generation/solar',
    'http://192.168.6.238:3100/d/solar-generation/solar',
    'http://192.168.6.238:3000/d/another-dashboard/solar',
  ]) {
    const { elements } = run({ pages: [page] });
    assert.equal(elements.page.src, page);
    assert.equal(elements.energy.hidden, true);
  }
});
