const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../ui/store.js'), 'utf8');

function setup() {
  const opened = [];
  const el = (tag, cls = '', text = '') => {
    const n = {tag, cls, text: String(text), children: [], dataset: {}, attributes: {},
      append(...nodes) { nodes.forEach(child => { child.parent = this; this.children.push(child); }); },
      prepend(child) { child.parent = this; this.children.unshift(child); },
      setAttribute(k, v) { this.attributes[k] = v; }, getAttribute(k) { return this.attributes[k]; },
      addEventListener(k, fn) { this[k] = fn; },
      replaceWith(child) { const i = this.parent.children.indexOf(this); child.parent = this.parent; this.parent.children[i] = child; },
      remove() { this.parent.children.splice(this.parent.children.indexOf(this), 1); },
      querySelector(selector) { return find(this, selector.slice(1)); },
      set textContent(value) { this.text = String(value); }, get textContent() { return this.text; }};
    n.classList = {add(cls) { n.cls += ' ' + cls; }};
    return n;
  };
  const cards = [];
  const c = {el, document: {createElementNS: (_, tag) => el(tag)}, detail: id => opened.push(id),
    button: (text, cls, action) => { const n = el('button', cls, text); n.click = action; return n; },
    symbol: () => el('span', 'tool-symbol'), window: {getSelection: () => null},
    $: () => ({querySelectorAll: () => cards})};
  vm.createContext(c);
  vm.runInContext(source.slice(source.indexOf('  function typeBadge('), source.indexOf('  function recordName(')), c);
  vm.runInContext(source.slice(source.indexOf('  function section('), source.indexOf('  function closeDetail(')), c);
  return {c, opened, cards};
}
function find(node, cls) { return node.cls.split(' ').includes(cls) ? node : node.children.map(child => find(child, cls)).find(Boolean); }
function text(node) { return [node.text, ...node.children.map(text)].join(' '); }
const item = () => ({id: 12, name: '회의록 정리', type: 'Skill', org: '기술팀', category: '공통 업무', access: 'approved',
  recommendationBadge: {active: true, status: 'active', reason: '회의 내용을 할 일과 결정 사항으로 정리합니다.', reviewedVersion: 2}});

test('recommendation is the first compact metadata tag and opens the existing detail dialog', () => {
  const {c, opened} = setup(), value = item(), card = c.toolCard(value), tags = find(card, 'tags');
  assert.deepEqual(tags.children.slice(0, 3).map(n => n.text), ['추천', 'Skill', '기술팀']);
  const badge = tags.children[0];
  assert.equal(badge.tag, 'button'); assert.equal(badge.attributes['aria-label'], '추천 이유 보기');
  assert.equal(badge.attributes['aria-controls'], 'detail-dialog'); assert.equal(badge.attributes['aria-haspopup'], 'dialog');
  assert.equal(badge.children[0].attributes['aria-hidden'], 'true'); badge.click(); assert.deepEqual(opened, [12]);
  assert.doesNotMatch(text(card), /관리자|인증/);
});

test('legacy and inactive responses keep ordinary metadata without a recommendation', () => {
  const {c} = setup();
  for (const badge of [undefined, null, {active: false, status: 'none'}, {active: false, status: 'needs_review'}, {active: 'true'}]) {
    const tags = c.cardTags({...item(), recommendationBadge: badge});
    assert.equal(find(tags, 'recommendation-badge'), undefined); assert.equal(tags.children[0].text, 'Skill');
  }
  const staticBadge = c.recommendationBadge(item(), false);
  assert.equal(staticBadge.tag, 'span'); assert.equal(staticBadge.attributes['aria-haspopup'], undefined);
});

test('recommendation evidence is plain text and is withheld for restricted or inactive tools', () => {
  const {c} = setup(), value = item();
  value.recommendationBadge.reason = '<img src=x onerror=alert(1)> 사용자 제공 이유';
  const section = c.recommendationDetails(value);
  assert.equal(section.children[1].text, value.recommendationBadge.reason);
  assert.equal(section.children[1].innerHTML, undefined); assert.match(text(section), /확인한 버전 v2/);
  for (const access of ['pending', 'required', 'denied', undefined, null]) assert.equal(c.recommendationDetails({...value, access}), null);
  assert.equal(c.recommendationDetails({...value, recommendationBadge: {active: false, reason: 'old private reason', reviewedVersion: 1}}), null);
  assert.equal(c.recommendationDetails({...value, recommendationBadge: {active: true}}), null);
  for (const reviewedVersion of [undefined, -1, '2']) {
    const visible = c.recommendationDetails({...value, recommendationBadge: {...value.recommendationBadge, reviewedVersion}});
    assert.doesNotMatch(text(visible), /확인한 버전/);
  }
});

test('a refreshed detail removes a superseded recommendation from the visible card', () => {
  const {c, cards} = setup(), value = item(), card = c.toolCard(value); card.dataset.toolId = String(value.id); cards.push(card);
  assert.ok(find(card, 'recommendation-badge'));
  c.updateCard({...value, recommendationBadge: {active: false, status: 'needs_review'}});
  assert.equal(find(card, 'recommendation-badge'), undefined); assert.equal(find(card, 'tags').children[0].text, 'Skill');
});
