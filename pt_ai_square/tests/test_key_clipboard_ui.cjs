// Exercise the maintained page with synthetic keys only; no browser, network, or real credentials.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '../static/local_access.js'), 'utf8');
const template = fs.readFileSync(path.join(__dirname, '../templates/local_access.html'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
const SUCCESS = 'KEY를 복사했습니다.';

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {resolve = yes; reject = no;});
  return {promise, resolve, reject};
}

async function fixture({secure = false, writeText, execCopy = true, missingExecCommand = false} = {}) {
  const elements = new Map(), writes = [], copies = [], requests = [];
  let serial = 0, currentKeyId = null, connectionKey = null;
  const tokens = [];
  const document = {
    activeElement: null,
    querySelector(selector) {
      assert.ok(elements.has(selector), `Unexpected page selector: ${selector}`);
      return elements.get(selector);
    },
    createElement: makeElement,
  };
  function makeElement(tag = 'div') {
    const listeners = new Map();
    return {
      tagName: tag.toUpperCase(), value: '', textContent: '', hidden: false, disabled: false,
      dataset: {}, children: [], selectionStart: 0, selectionEnd: 0,
      append(...children) {this.children.push(...children);},
      replaceChildren(...children) {this.children = children;},
      focus() {document.activeElement = this;},
      select() {this.selectionStart = 0; this.selectionEnd = this.value.length;},
      setSelectionRange(start, end) {this.selectionStart = start; this.selectionEnd = end;},
      addEventListener(name, callback) {listeners.set(name, callback);},
      dispatch(name, event = {}) {return this[`on${name}`]?.(event) ?? listeners.get(name)?.(event);},
    };
  }
  for (const match of template.matchAll(/<([a-z][\w-]*)\b[^>]*\bid="([^"]+)"[^>]*>/gi)) {
    const element = makeElement(match[1]);
    element.hidden = /\bhidden(?:\s|>)/.test(match[0]);
    element.disabled = /\bdisabled(?:\s|>)/.test(match[0]);
    elements.set(`#${match[2]}`, element);
  }
  const secret = elements.get('#secret'), copyButton = elements.get('#copy-token');
  if (!missingExecCommand) document.execCommand = command => {
    assert.equal(command, 'copy');
    assert.equal(document.activeElement, secret, 'Fallback must focus the visible KEY input');
    assert.equal(secret.selectionStart, 0);
    assert.equal(secret.selectionEnd, secret.value.length, 'Fallback must select the entire KEY');
    copies.push(secret.value.slice(secret.selectionStart, secret.selectionEnd));
    if (execCopy instanceof Error) throw execCopy;
    return execCopy;
  };
  const navigator = {};
  if (writeText) navigator.clipboard = {writeText(value) {writes.push(value); return writeText(value);}};
  const context = {
    document, navigator, isSecureContext: secure,
    localStorage: {setItem() {assert.fail('KEY must not be persisted');}},
    sessionStorage: {setItem() {assert.fail('KEY must not be persisted');}},
    async fetch(url, options) {
      requests.push({url, method: options.method || 'GET'});
      let data;
      if (url === 'api/local-tokens' && options.method === 'POST') {
        if (connectionKey) connectionKey.status = 'replaced';
        currentKeyId = `fake-key-id-${++serial}`;
        connectionKey = {id: currentKeyId, name: 'Synthetic key', scope: 'publish', status: 'active', expires: null, created: 1, uploads: 0, downloads: 0};
        tokens.push(connectionKey);
        data = {id: currentKeyId, token: `FAKE_KEY_FOR_CLIPBOARD_TEST_${serial}`};
      } else if (url === `api/local-tokens/${currentKeyId}` && options.method === 'DELETE') {
        connectionKey.status = 'revoked';
        data = {};
      } else {
        assert.equal(url, 'api/local-tokens');
        assert.equal(options.method, undefined);
        data = {csrf: 'fake-csrf', currentKeyId, connectionKey, tokens, employee: {name: 'Test', id: 'fake-employee'}, usage: {uploads: 0, downloads: 0}, history: []};
      }
      return {ok: true, json: async () => data};
    },
  };
  context.window = context;
  vm.runInNewContext(source, context, {filename: 'local_access.js'});
  await flush();
  return {
    secret, copyButton, writes, copies, requests, document,
    get status() {return elements.get('#status').textContent;},
    get issuedHidden() {return elements.get('#issued').hidden;},
    issue: () => elements.get('#token-form').dispatch('submit', {preventDefault() {}}),
    copy: () => copyButton.dispatch('click'),
    revoke: () => elements.get('#key-revoke').dispatch('click'),
    async externalReplace() {
      connectionKey.status = 'replaced';
      currentKeyId = 'fake-key-id-from-another-page';
      connectionKey = {...connectionKey, id: currentKeyId, status: 'active'};
      tokens.push(connectionKey);
      await elements.get('#refresh-usage').dispatch('click');
    },
  };
}

function assertManualCopy(h) {
  assert.notEqual(h.status, SUCCESS);
  assert.match(h.status, /Ctrl\s*\+\s*C/);
  assert.equal(h.document.activeElement, h.secret);
  assert.equal(h.secret.selectionStart, 0);
  assert.equal(h.secret.selectionEnd, h.secret.value.length);
  assert.ok(!h.status.includes(h.secret.value), 'Status must not contain the KEY');
  assert.equal(h.copyButton.disabled, false);
}

test('the one-time KEY is readonly selectable text with autofill disabled', () => {
  const input = template.match(/<input\b[^>]*\bid="secret"[^>]*>/)?.[0];
  assert.ok(input, 'The issued KEY input must exist');
  assert.match(input, /\btype="text"/);
  assert.match(input, /\breadonly(?:\s|>)/);
  assert.match(input, /\bautocomplete="off"/);
});

test('HTTP without Clipboard API copies the complete issued KEY during the click', async () => {
  const h = await fixture();
  await h.issue();
  const pending = h.copy();
  assert.deepEqual(h.copies, [h.secret.value], 'HTTP fallback must run synchronously inside the user gesture');
  await pending;
  assert.equal(h.status, SUCCESS);
  assert.equal(h.copyButton.disabled, false);
  assert.deepEqual(h.writes, []);
});

test('an insecure origin uses synchronous fallback even if a Clipboard API object exists', async () => {
  const h = await fixture({writeText: () => assert.fail('HTTP must use the synchronous copy path')});
  await h.issue();
  await h.copy();
  assert.deepEqual(h.writes, []);
  assert.deepEqual(h.copies, [h.secret.value]);
  assert.equal(h.status, SUCCESS);
});

test('secure Clipboard API success reports success only after the write completes', async () => {
  const pending = deferred();
  const h = await fixture({secure: true, writeText: () => pending.promise});
  await h.issue();
  const result = h.copy();
  assert.deepEqual(h.writes, [h.secret.value]);
  assert.equal(h.copyButton.disabled, true);
  assert.notEqual(h.status, SUCCESS);
  pending.resolve();
  await result;
  assert.equal(h.status, SUCCESS);
  assert.equal(h.copyButton.disabled, false);
  assert.deepEqual(h.copies, []);
});

test('secure context without Clipboard API still uses the copy fallback', async () => {
  const h = await fixture({secure: true});
  await h.issue();
  await h.copy();
  assert.deepEqual(h.copies, [h.secret.value]);
  assert.equal(h.status, SUCCESS);
});

test('Clipboard API permission rejection tries fallback and reports its success', async () => {
  const h = await fixture({secure: true, writeText: async () => {throw Error('private clipboard permission detail');}});
  await h.issue();
  await h.copy();
  assert.deepEqual(h.writes, [h.secret.value]);
  assert.deepEqual(h.copies, [h.secret.value]);
  assert.equal(h.status, SUCCESS);
  assert.equal(h.copyButton.disabled, false);
});

for (const [label, execCopy, missingExecCommand] of [
  ['returns false', false, false],
  ['throws', Error('private browser detail'), false],
  ['is unavailable', undefined, true],
]) {
  test(`when fallback ${label}, manual Ctrl+C remains possible without false success`, async () => {
    const h = await fixture({execCopy, missingExecCommand});
    await h.issue();
    await h.copy();
    assertManualCopy(h);
    assert.doesNotMatch(h.status, /private browser detail/);
  });
}

test('both copy methods failing leaves the complete KEY selected and hides exception details', async () => {
  const h = await fixture({secure: true, writeText: async () => {throw Error('private clipboard detail');}, execCopy: false});
  await h.issue();
  await h.copy();
  assertManualCopy(h);
  assert.doesNotMatch(h.status, /private clipboard detail/);
});

test('no issued KEY does not write an empty value or claim copy success', async () => {
  const h = await fixture({secure: true, writeText: async () => {}});
  const previousStatus = h.status;
  await h.copy();
  assert.equal(h.status, previousStatus);
  assert.deepEqual(h.writes, []);
  assert.deepEqual(h.copies, []);
  assert.equal(h.copyButton.disabled, false);
});

for (const action of ['revoke', 'externalReplace', 'issue']) {
  for (const settlement of ['resolve', 'reject']) {
    test(`pending clipboard ${settlement} cannot overwrite ${action} state or copy a replacement KEY`, async () => {
      const pending = deferred();
      const h = await fixture({secure: true, writeText: () => pending.promise});
      await h.issue();
      const originalKey = h.secret.value;
      const result = h.copy();
      await h[action]();
      const latestStatus = h.status;
      if (action === 'issue') {
        assert.notEqual(h.secret.value, originalKey);
        assert.equal(h.issuedHidden, false);
      } else {
        assert.equal(h.secret.value, '');
        assert.equal(h.issuedHidden, true);
      }
      pending[settlement](settlement === 'reject' ? Error('private delayed clipboard detail') : undefined);
      await result;
      if(action==='externalReplace')assert.equal(h.status, 'KEY가 변경되었습니다. 최신 KEY를 확인해 주세요.');
      else assert.equal(h.status, latestStatus);
      assert.notEqual(h.status, SUCCESS);
      assert.deepEqual(h.writes, [originalKey]);
      assert.deepEqual(h.copies, [], 'An obsolete operation must not fall back and copy a new or revoked KEY');
      assert.equal(h.copyButton.disabled, false);
    });
  }
}
