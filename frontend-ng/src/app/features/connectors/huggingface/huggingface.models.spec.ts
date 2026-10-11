import assert from 'node:assert/strict';
import { test } from 'node:test';
import { defaultSelection, filesForFormat, hasWeights, hubError, hubErrorCode, isTerminalJob, jobError } from './huggingface.models';
import { RESOURCES_FR, RESOURCES_EN } from '@app/core/i18n/resources.dict';

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

test('TabICL license refusals explain bundle repair in FR/EN across API, jobs and artifacts', () => {
  for (const dictionary of [RESOURCES_FR, RESOURCES_EN]) {
    const translate = (key: string) => (dictionary as Record<string, string>)[key] ?? key;
    for (const code of ['HF_TABICL_LICENSE_REQUIRED', 'HF_TABICL_LICENSE_INVALID']) {
      const sentence = hubErrorCode(code, translate);
      assert.match(sentence, /license\.json/);
      assert.match(sentence, /bundle/);
      assert.doesNotMatch(sentence, /connectors\.hf\./);
      assert.equal(hubError({ error: { detail: { code, message: 'Backend English message' } } }, translate), sentence);
      assert.equal(jobError({ id: '1', status: 'failed', error: { code, message: 'Backend English message' } }, translate), sentence);
      assert.equal(jobError({ id: '1', status: 'failed', error: 'Backend English message', result: { error_code: code } }, translate), sentence);
    }
    assert.equal(hubError({ error: { detail: { code: 'HF_OTHER', message: 'Unknown cause' } } }, translate), 'HF_OTHER · Unknown cause');
    assert.equal(jobError({ id: '1', status: 'failed', error: 'Unknown cause', result: { error_code: 'HF_OTHER' } }, translate), 'Unknown cause');
  }
});
