const { test } = require('node:test');
const assert = require('node:assert/strict');
const axios = require('axios');

let lastCall;
let lastConfig;
let nextError;
axios.create = (config) => {
  lastConfig = config;
  return {
    defaults: { timeout: config.timeout },
    post: async (...args) => {
      lastCall = args;
      if (nextError) {
        const error = nextError;
        nextError = undefined;
        throw error;
      }
      return { data: { choices: [] } };
    },
  };
};

const { NexusAPIError, NexusClient } = require('../dist/index.js');

test('defaults to the FastAPI facade and sends the configured client token', async () => {
  const client = new NexusClient({ apiKey: 'client-token' });
  await client.chat('hello');
  assert.equal(lastConfig.baseURL, 'http://127.0.0.1:8000');
  assert.equal(lastConfig.headers['X-API-Key'], 'client-token');
  assert.equal(lastConfig.maxRedirects, 0);
  assert.equal(lastConfig.proxy, false);
});

test('rejects remote plaintext API endpoints', () => {
  assert.throws(() => new NexusClient({
    apiKey: 'client-token', baseURL: 'http://api.example.test',
  }), TypeError);
  assert.throws(() => new NexusClient({
    baseURL: 'https://user:password@api.example.test',
  }), TypeError);
  assert.throws(() => new NexusClient({
    baseURL: 'https://api.example.test/v1',
  }), TypeError);
  assert.doesNotThrow(() => new NexusClient({ baseURL: 'https://api.example.test' }));
});

test('per-request HTTP deadline exceeds Router job deadline', async () => {
  const client = new NexusClient({ timeout: 30_000 });
  await client.chat('slow job', { timeoutSeconds: 1800 });
  assert.equal(lastCall[1].timeout_s, 1800);
  assert.equal(lastCall[2].timeout, 1_810_000);
});

test('constructor timeout can extend the per-request HTTP deadline', async () => {
  const client = new NexusClient({ timeout: 2_000_000 });
  await client.chat('slow job', { timeoutSeconds: 1800 });
  assert.equal(lastCall[2].timeout, 2_000_000);
});

test('FastAPI wrapped Router errors preserve useful message and job ID', async () => {
  const client = new NexusClient();
  nextError = {
    response: {
      status: 504,
      data: { detail: { error: {
        type: 'job_timeout', job_id: 'job_123', message: 'still pending',
      } } },
    },
  };
  await assert.rejects(client.chat('slow job'), (error) => {
    assert.ok(error instanceof NexusAPIError);
    assert.equal(error.statusCode, 504);
    assert.equal(error.message, 'still pending');
    assert.equal(error.payload.detail.error.job_id, 'job_123');
    return true;
  });
});

test('rejects Router deadlines outside supported range', async () => {
  const client = new NexusClient();
  await assert.rejects(client.chat('bad timeout', { timeoutSeconds: 1801 }), RangeError);
});
