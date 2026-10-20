// JSON stdin/stdout boundary; CHL diagnostics go to stderr.
const path = require('node:path');
const fs = require('node:fs');
console.log = (...args) => console.error(...args);
(async () => {
  const request = JSON.parse(fs.readFileSync(0, 'utf8'));
  const { NativeCHL } = require(path.join(request.repo, 'src/native.js'));
  const memory = new NativeCHL({persistPath: request.memory});
  await memory.whenReady();
  let result;
  try {
    if (request.action === 'remember') {
      result = memory.remember(request.prompt, {
        prompt: request.prompt, completion: request.completion,
        verified: request.verified === true, model: request.model || null,
        area: request.area || 'general', source_sha256: request.source_sha256 || null,
      }, {memoryType: request.memory_type || 'episodic', source: 'onram', expiresAt: null});
      result = {ok: true};
    } else if (request.action === 'recall') {
      const recalled = memory.recall(request.query, {topK: request.top_k});
      result = {engine: memory.fallback ? 'javascript' : 'native', candidates:
        recalled.candidates.map(c => ({score: c.score,
          payload: c.payload ?? c.entry?.payload,
          metadata: c.metadata ?? c.entry?.metadata}))};
    } else if (request.action === 'export' || request.action === 'export_all') {
      result = memory.backup().journal.filter(e => e.type === 'remember' &&
        e.metadata?.source === 'onram' &&
        (request.action === 'export_all' || e.payload?.verified === true))
        .map(e => e.payload);
    } else throw new Error('Unknown action');
  } finally { await memory.close(); }
  process.stdout.write(JSON.stringify(result));
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
