import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readableQuote } from './judge-evidence';

test('prose stays prose and is not marked as transformed', () => {
  const read = readableQuote('Le statut livré ne prouve pas la réception.');
  assert.equal(read.text, 'Le statut livré ne prouve pas la réception.');
  assert.equal(read.transformed, false);
});

test('structured data becomes labelled facts without ids or hashes', () => {
  const quote = JSON.stringify({ '/data/context': [{ claim_id: 'RC-5003', currency: 'EUR', paid_amount: '49.90', document_id: 'abc', sha256: 'f00' }] });
  const read = readableQuote(quote);
  assert.equal(read.transformed, true);
  assert.deepEqual(read.fields, [
    { label: 'context · claim id', value: 'RC-5003' },
    { label: 'context · currency', value: 'EUR' },
    { label: 'context · paid amount', value: '49.90' },
  ]);
});

test('a JSON fragment around a document keeps only its words', () => {
  const quote = 'de livraison disponible.", "document_id":"967ae13a","filename":"confirmation-perte-lm5003.pdf","page":1,"sha256":"938be","content":"LUMA MAISON Document de démonstration Réclamation RC-5003';
  const read = readableQuote(quote);
  assert.equal(read.text, 'LUMA MAISON Document de démonstration Réclamation RC-5003');
  assert.equal(read.transformed, true);
});

test('empty citations are empty', () => {
  assert.deepEqual(readableQuote(''), { text: null, fields: [], transformed: false });
  assert.deepEqual(readableQuote(null), { text: null, fields: [], transformed: false });
});
