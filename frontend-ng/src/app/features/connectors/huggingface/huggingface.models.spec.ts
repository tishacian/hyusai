import assert from 'node:assert/strict';
import { test } from 'node:test';
import { defaultSelection, filesForFormat, hasWeights, hubError, isTerminalJob } from './huggingface.models';

const files = ['config.json', 'model.safetensors', 'model.safetensors.index.json', 'q4.gguf', 'q8.gguf', 'weights.bin', 'custom.py', 'tokenizer.model', 'train.parquet'].map(path => ({ path, size_bytes: 1 }));

test('GGUF leaves weights unselected so two quantizations never import silently together', () => {
  const selection = defaultSelection(files, 'gguf');
  assert.deepEqual(selection, ['config.json', 'tokenizer.model']);
  assert.equal(hasWeights(selection, 'gguf'), false);
  assert.equal(hasWeights([...selection, 'q4.gguf'], 'gguf'), true);
  assert.equal(filesForFormat(files, 'gguf').some(f => /\.(bin|py|parquet)$/.test(f.path)), false);
});

test('dataset files require explicit selection and model indexes follow their format', () => {
  assert.deepEqual(defaultSelection(files, 'parquet'), []);
  assert.deepEqual(filesForFormat(files, 'parquet').map(f => f.path), ['train.parquet']);
  assert.deepEqual(defaultSelection(files, 'safetensors'), ['config.json', 'model.safetensors', 'model.safetensors.index.json', 'tokenizer.model']);
});

test('terminal failures stop polling and named API errors remain actionable', () => {
  assert.equal(isTerminalJob({ id: '1', status: 'failed' }), true);
  assert.equal(isTerminalJob({ id: '1', status: 'queued' }), false);
  assert.equal(hubError({ error: { detail: { code: 'HF_LICENSE_BLOCKED', message: 'unknown' } } }), 'HF_LICENSE_BLOCKED · unknown');
});
