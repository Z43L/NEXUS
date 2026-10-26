#!/usr/bin/env node
/**
 * train-frontier.js — Entrenamiento CHL a escala 7B-equivalente
 *
 * Estrategia:
 *   - Corpus grande (50K documentos) con paráfrasis
 *   - CHL con LexiconTrainer + HyperAttention + HyperDecoder
 *   - Múltiples épocas de entrenamiento por feedback
 *   - Cada época: query → si falla, feedback negativo → ajuste de prototipos y atención
 *   - Métricas: recall@1, recall@3, MRR por época
 */

const fs = require("node:fs");
const path = require("node:path");
const { performance } = require("node:perf_hooks");
const readline = require("node:readline");
const {
  JSCHL: CHL,
  LexiconTrainer,
  HyperAttentionContext,
  HyperDecoder,
  tokenize,
  normalizeText,
} = require("../src");

// ─── Corpus builder (escalado) ────────────────────────────

const baseFacts = [
  { id: "cat-table", text: "el gato duerme sobre la mesa", paraphrases: ["el gato duerme en la mesa", "el felino descansa sobre la mesa"] },
  { id: "dog-park", text: "el perro corre por el parque", paraphrases: ["el perro corre en el parque", "el can corre por el parque"] },
  { id: "train-station", text: "el tren entra en la estacion", paraphrases: ["el tren llega a la estacion", "el tren se acerca a la estacion"] },
  { id: "rain-street", text: "la lluvia cae sobre la calle", paraphrases: ["la lluvia moja la calle", "la lluvia cae en la calle"] },
  { id: "memory-remembers", text: "la memoria guarda recuerdos utiles", paraphrases: ["la memoria conserva recuerdos utiles", "la memoria almacena recuerdos"] },
  { id: "drone-field", text: "el dron sobrevuela el campo", paraphrases: ["el dron vuela sobre el campo", "el dron cruza el campo"] },
  { id: "key-door", text: "la llave abre la puerta", paraphrases: ["la llave desbloquea la puerta", "la llave abre una puerta"] },
  { id: "river-city", text: "el rio atraviesa la ciudad", paraphrases: ["el rio cruza la ciudad", "el rio pasa por la ciudad"] },
  { id: "book-library", text: "el libro esta en la biblioteca", paraphrases: ["el libro queda en la biblioteca", "la biblioteca guarda el libro"] },
  { id: "bird-tree", text: "el pajaro se posa en el arbol", paraphrases: ["el pajaro descansa en el arbol", "el ave se posa en el arbol"] },
  { id: "coffee-kitchen", text: "el cafe humea en la cocina", paraphrases: ["el cafe esta caliente en la cocina", "el cafe humea dentro de la cocina"] },
  { id: "phone-battery", text: "el telefono carga la bateria", paraphrases: ["el telefono recarga la bateria", "la bateria del telefono se carga"] },
  { id: "lamp-room", text: "la lampara ilumina la habitacion", paraphrases: ["la lampara da luz a la habitacion", "la habitacion queda iluminada"] },
  { id: "car-road", text: "el coche circula por la carretera", paraphrases: ["el coche va por la carretera", "el automovil circula por la carretera"] },
  { id: "fish-river", text: "el pez nada en el rio", paraphrases: ["el pez se mueve en el rio", "el pez nada por el rio"] },
  { id: "student-class", text: "la estudiante toma apuntes en clase", paraphrases: ["la estudiante escribe apuntes en clase", "la alumna toma notas en clase"] },
  { id: "doctor-hospital", text: "el doctor atiende al paciente", paraphrases: ["el medico atiende al paciente", "el doctor cuida al paciente"] },
  { id: "chef-kitchen", text: "la chef prepara la cena", paraphrases: ["la cocinera prepara la cena", "la chef cocina la cena"] },
  { id: "window-open", text: "la ventana permanece abierta", paraphrases: ["la ventana sigue abierta", "la ventana esta abierta"] },
  { id: "forest-shadow", text: "la sombra cubre el bosque", paraphrases: ["la sombra cae sobre el bosque", "el bosque queda en sombra"] },
  { id: "music-speaker", text: "la musica suena en el altavoz", paraphrases: ["la musica sale del altavoz", "el altavoz reproduce musica"] },
  { id: "code-editor", text: "el codigo se escribe en el editor", paraphrases: ["el programador escribe codigo en el editor", "el editor contiene codigo"] },
  { id: "bridge-river", text: "el puente cruza el rio", paraphrases: ["el puente atraviesa el rio", "el puente esta sobre el rio"] },
  { id: "market-buy", text: "la persona compra pan en el mercado", paraphrases: ["la persona compra pan", "el mercado vende pan"] },
  { id: "garden-water", text: "la regadera riega el jardin", paraphrases: ["la regadera moja el jardin", "el jardin recibe agua"] },
  { id: "sun-warm", text: "el sol calienta la terraza", paraphrases: ["el sol calienta la superficie", "la terraza recibe calor del sol"] },
  { id: "mail-delivery", text: "el correo llega a la oficina", paraphrases: ["el correo entra en la oficina", "la oficina recibe correo"] },
  { id: "clock-time", text: "el reloj marca las tres", paraphrases: ["el reloj indica las tres", "las tres aparecen en el reloj"] },
  { id: "tablet-screen", text: "la pantalla muestra el mapa", paraphrases: ["la pantalla enseña el mapa", "el mapa aparece en la pantalla"] },
  { id: "library-quiet", text: "la biblioteca permanece en silencio", paraphrases: ["la biblioteca esta silenciosa", "el silencio reina en la biblioteca"] },
];

// Ruido: términos que suenan parecido pero no son
const hardNoise = [
  "el pato duerme sobre la mesa",
  "el gato corre por el parque", // ¡no es dog-park!
  "el tren sale de la estacion",
  "el sol seca la calle",
  "el disco guarda archivos",
  "el avion sobrevuela la ciudad",
  "el candado cierra la puerta",
  "el canal bordea la ciudad",
  "la revista esta en el quiosco",
  "la mariposa se posa en la flor",
  "el te hierve en la tetera",
  "la radio emite musica",
  "la vela da luz a la cueva",
  "la moto acelera en la pista",
  "el delfin salta en el mar",
  "el profesor explica la leccion",
  "la enfermera toma la temperatura",
  "el camarero sirve la mesa",
  "la puerta sigue cerrada",
  "la niebla envuelve el valle",
  "el microfono capta el sonido",
  "el mecanico revisa el motor",
  "el tunel cruza la montaña",
  "la turista compra recuerdos",
  "el aspersor moja el cesped",
  "la estufa calienta el salon",
  "el paquete sale de la oficina",
  "el cronometro marca cero",
  "el cartel anuncia el evento",
  "el museo guarda silencio",
];

function buildLargeCorpus(targetDocs = 50000) {
  const docs = [];
  const conceptPairs = [];
  const templates = []; // Para variar textos

  for (let i = 0; i < baseFacts.length && docs.length < targetDocs; i++) {
    const fact = baseFacts[i];
    docs.push({ id: fact.id, text: fact.text, type: "fact", category: "large-positive" });
    
    // Añadir paráfrasis como documentos adicionales (variantes)
    for (const para of fact.paraphrases) {
      const variantId = `${fact.id}-var-${docs.length}`;
      docs.push({ id: variantId, text: para, type: "fact", category: "large-positive" });
      conceptPairs.push({ source: para, target: fact.text });
    }
  }

  // Añadir ruido (distractores)
  for (let i = 0; i < hardNoise.length && docs.length < targetDocs; i++) {
    docs.push({ id: `noise-${i}`, text: hardNoise[i], type: "noise", category: "noise" });
  }

  // Generar más ruido si hace falta
  const extraNoise = [
    "el sistema procesa datos rapidamente",
    "la red conecta todos los nodos",
    "el algoritmo encuentra la ruta optima",
    "el sensor detecta movimiento",
    "la camara graba video en alta definicion",
    "el archivo se comprime sin perdida",
    "el proceso termina correctamente",
    "la señal viaja por el cable",
    "el chip calcula operaciones complejas",
    "la pantalla refleja la luz del sol",
    "el teclado responde al instante",
    "el raton se desplaza sobre la alfombrilla",
    "la impresora imprime el documento",
    "el escaner digitaliza la imagen",
    "el disco duro almacena terabytes",
    "la memoria RAM accede a los datos",
    "el procesador ejecuta instrucciones",
    "la fuente de alimentacion suministra energia",
    "el ventilador refrigera el sistema",
    "la placa base conecta componentes",
  ];

  let noiseIdx = 0;
  while (docs.length < targetDocs) {
    const noiseText = extraNoise[noiseIdx % extraNoise.length];
    const variant = noiseText + " " + (noiseIdx + 1);
    docs.push({ id: `auto-noise-${noiseIdx}`, text: variant, type: "noise", category: "noise" });
    noiseIdx++;
  }

  // Construir query samples base: cada fact + sus paráfrasis generan queries
  const querySamples = [];
  for (const fact of baseFacts) {
    querySamples.push({
      query: fact.text,
      expectedId: fact.id,
      category: "positive",
    });
    for (const para of fact.paraphrases) {
      querySamples.push({
        query: para,
        expectedId: fact.id,
        category: "paraphrase",
      });
    }
  }
  // Aumentar cobertura: generar variaciones sintácticas/lexicales por plantilla
  const queryAugmented = [];
  for (const fact of baseFacts) {
    const variants = [fact.text, ...fact.paraphrases];
    for (const v of variants) {
      queryAugmented.push({ query: v, expectedId: fact.id, category: "aug-original" });
      queryAugmented.push({ query: `dime si recuerdas: ${v}`, expectedId: fact.id, category: "aug-prefix" });
      queryAugmented.push({ query: `${v} por favor`, expectedId: fact.id, category: "aug-suffix" });
      queryAugmented.push({ query: `recuerdo que ${v}`, expectedId: fact.id, category: "aug-rewrite" });
      queryAugmented.push({ query: v.replace(/\ben\b/g, "dentro de"), expectedId: fact.id, category: "aug-prep" });
      queryAugmented.push({ query: v.replace(/\bsobre\b/g, "encima de"), expectedId: fact.id, category: "aug-prep" });
    }
  }
  const dedup = new Map();
  for (const s of [...querySamples, ...queryAugmented]) {
    const k = `${s.expectedId}::${normalizeText(s.query)}`;
    if (!dedup.has(k)) dedup.set(k, s);
  }

  return { docs: docs.slice(0, targetDocs), conceptPairs, querySamples: Array.from(dedup.values()) };
}

function generateDynamicQuerySamples(docs = [], options = {}) {
  const evalRatio = Number(options.evalRatio ?? 0.002);
  const explicitEvalQueries = Number(options.evalQueries ?? 0) || 0;
  const maxQueries = explicitEvalQueries > 0
    ? explicitEvalQueries
    : Math.max(400, Math.min(20000, Math.floor(docs.length * evalRatio)));

  const queries = [];
  const stride = Math.max(1, Math.floor(docs.length / Math.max(1, Math.floor(maxQueries / 4))));
  for (let i = 0; i < docs.length && queries.length < maxQueries; i += stride) {
    const doc = docs[i];
    const text = normalizeText(doc?.text ?? "");
    if (!text || text.length < 24) continue;
    queries.push({ query: text, expectedId: doc.id, category: "dyn-original" });
    if (queries.length >= maxQueries) break;
    queries.push({ query: `recuerdo que ${text}`, expectedId: doc.id, category: "dyn-prefix" });
    if (queries.length >= maxQueries) break;
    queries.push({ query: `${text} por favor`, expectedId: doc.id, category: "dyn-suffix" });
    if (queries.length >= maxQueries) break;
    queries.push({ query: text.replace(/\ben\b/g, "dentro de").replace(/\bsobre\b/g, "encima de"), expectedId: doc.id, category: "dyn-prep" });
  }

  const dedup = new Map();
  for (const q of queries) {
    const k = `${q.expectedId}::${normalizeText(q.query)}`;
    if (!dedup.has(k)) dedup.set(k, q);
  }
  return Array.from(dedup.values()).slice(0, maxQueries);
}

function generateHardQuerySamples(docs = [], options = {}) {
  const evalRatio = Number(options.evalRatio ?? 0.002);
  const explicitEvalQueries = Number(options.evalQueries ?? 0) || 0;
  const maxQueries = explicitEvalQueries > 0
    ? explicitEvalQueries
    : Math.max(500, Math.min(30000, Math.floor(docs.length * evalRatio * 2.2)));
  const stop = new Set(["el", "la", "los", "las", "de", "del", "en", "a", "y", "que", "por", "con"]);
  const pickKeywords = (text) => tokenize(normalizeText(text)).filter((t) => t.length > 4 && !stop.has(t)).slice(0, 4);
  const out = [];
  const stride = Math.max(1, Math.floor(docs.length / Math.max(1, Math.floor(maxQueries / 6))));

  for (let i = 0; i < docs.length && out.length < maxQueries; i += stride) {
    const doc = docs[i];
    const text = normalizeText(doc?.text ?? "");
    if (!text || text.length < 40) continue;
    const kws = pickKeywords(text);
    const kwLine = kws.join(" ");
    const indirect = kws.length > 0 ? `que documento menciona ${kwLine}` : `a que se refiere ${text.slice(0, 80)}`;
    const noisy = `no estoy seguro pero creo que ${text}`;
    const contradiction = `esto contradice lo anterior: no ${text}`;
    const paraphrase = text
      .replace(/\bes\b/g, "resulta")
      .replace(/\best[aá]\b/g, "permanece")
      .replace(/\btiene\b/g, "mantiene")
      .replace(/\ben\b/g, "dentro de")
      .replace(/\bsobre\b/g, "encima de");
    const compressed = kws.length > 1 ? `resumen factual de ${kwLine}` : `explica brevemente ${text.slice(0, 70)}`;

    out.push({ query: indirect, expectedId: doc.id, category: "hard-indirect" });
    out.push({ query: noisy, expectedId: doc.id, category: "hard-noisy" });
    out.push({ query: contradiction, expectedId: doc.id, category: "hard-contradiction" });
    out.push({ query: paraphrase, expectedId: doc.id, category: "hard-paraphrase" });
    out.push({ query: compressed, expectedId: doc.id, category: "hard-summary" });
    if (kws.length > 0) out.push({ query: `busca evidencia sobre ${kwLine}`, expectedId: doc.id, category: "hard-evidence" });
  }

  const dedup = new Map();
  for (const q of out) {
    const k = `${q.expectedId}::${normalizeText(q.query)}`;
    if (!dedup.has(k)) dedup.set(k, q);
  }
  return Array.from(dedup.values()).slice(0, maxQueries);
}

async function loadCorpusFromJsonl(filePath, targetDocs = 50000, options = {}) {
  if (!filePath || !fs.existsSync(filePath)) {
    throw new Error(`Corpus JSONL no encontrado: ${filePath}`);
  }
  const minDocChars = Number(options.minDocChars ?? 40);
  const docs = [];
  const stream = fs.createReadStream(filePath, { encoding: "utf8" });
  const rl = readline.createInterface({ input: stream, crlfDelay: Infinity });
  let i = 0;
  for await (const line of rl) {
    if (!line || !line.trim()) continue;
    let obj = null;
    try {
      obj = JSON.parse(line);
    } catch {
      continue;
    }
    const text = String(obj.text ?? obj.content ?? obj.body ?? obj.document ?? "").trim();
    if (!text || text.length < minDocChars) continue;
    const id = String(obj.id ?? `real-${i}`);
    docs.push({
      id,
      text,
      type: "fact",
      category: "real-corpus",
    });
    i += 1;
    if (docs.length >= targetDocs) break;
  }
  rl.close();
  stream.destroy();

  const querySamples = options.hardEval
    ? generateHardQuerySamples(docs, options)
    : generateDynamicQuerySamples(docs, options);
  return { docs, conceptPairs: [], querySamples };
}

// ─── Métricas ─────────────────────────────────────────────

function p95(arr) {
  const sorted = [...arr].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length * 0.95)] ?? 0;
}

function median(arr) {
  const sorted = [...arr].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)] ?? 0;
}

function candidateId(candidate) {
  const payload = candidate?.entry?.payload ?? candidate?.payload ?? {};
  return payload?.fact ?? payload?.id ?? candidate?.entry?.id ?? "";
}

function evaluate(chl, samples, options = {}) {
  const latencies = [];
  let recallAt1 = 0, recallAt3 = 0, mrr = 0;
  let failures = [];
  const failureByType = { lexical: 0, syntax: 0, concept_miss: 0 };
  const docTextById = options.docTextById ?? new Map();
  const maxEval = Math.max(1, Number(options.maxEval ?? samples.length));
  const progressEvery = Math.max(50, Number(options.progressEvery ?? 200));
  const evalSamples = samples.length > maxEval ? samples.slice(0, maxEval) : samples;
  const t0 = performance.now();

  for (let idx = 0; idx < evalSamples.length; idx++) {
    const sample = evalSamples[idx];
    const start = performance.now();
    const result = chl.recall(sample.query, {
      topK: 5,
      fastEval: Boolean(options.fastEval),
      disableSecondPass: Boolean(options.disableSecondPass),
      secondPassThreshold: options.secondPassThreshold,
    });
    const elapsed = (performance.now() - start) * 1000;
    latencies.push(elapsed);

    const ranked = result.candidates.map(candidateId);
    const rank = ranked.indexOf(sample.expectedId);

    if (ranked[0] === sample.expectedId) recallAt1++;
    if (ranked.slice(0, 3).includes(sample.expectedId)) recallAt3++;
    if (rank !== -1) mrr += 1 / (rank + 1);
    else {
      const expectedText = String(docTextById.get(sample.expectedId) ?? baseFacts.find((f) => f.id === sample.expectedId)?.text ?? "").toLowerCase();
      const qTokens = new Set(tokenize(normalizeText(sample.query)));
      const eTokens = new Set(tokenize(normalizeText(expectedText)));
      let overlap = 0;
      for (const t of qTokens) if (eTokens.has(t)) overlap++;
      const jaccard = qTokens.size + eTokens.size > 0 ? overlap / (new Set([...qTokens, ...eTokens]).size || 1) : 0;
      let type = "concept_miss";
      if (ranked.slice(0, 3).length > 0 && jaccard >= 0.55) type = "syntax";
      else if (jaccard >= 0.25) type = "lexical";
      failureByType[type] += 1;
      failures.push({ query: sample.query, expectedId: sample.expectedId, got: ranked.slice(0, 3), type });
    }

    if ((idx + 1) % progressEvery === 0) {
      const elapsedS = ((performance.now() - t0) / 1000).toFixed(1);
      process.stdout.write(`\r   eval ${idx + 1}/${evalSamples.length} (${elapsedS}s)`);
    }
  }
  if (evalSamples.length >= progressEvery) process.stdout.write("\n");

  const n = evalSamples.length;
  return {
    recallAt1: recallAt1 / n,
    recallAt3: recallAt3 / n,
    mrr: mrr / n,
    p95Us: p95(latencies),
    medianUs: median(latencies),
    failures: failures.slice(0, 10),
    failureCount: failures.length,
    failureByType,
  };
}

// ─── Entrenamiento ────────────────────────────────────────

function buildConceptMap(facts) {
  // Combinar: pares atestiguados (precisos) + bootstrap (cobertura)
  const attested = new Map();
  for (const fact of facts) {
    for (const para of fact.paraphrases) {
      const srcWords = para.toLowerCase().split(/[^a-z0-9]+/g).filter(Boolean);
      const tgtWords = fact.text.toLowerCase().split(/[^a-z0-9]+/g).filter(Boolean);
      const minLen = Math.min(srcWords.length, tgtWords.length);
      for (let i = 0; i < minLen; i++) {
        if (srcWords[i] !== tgtWords[i] && srcWords[i].length > 2 && tgtWords[i].length > 2) {
          attested.set(srcWords[i], tgtWords[i]);
        }
      }
    }
  }
  
  // Bootstrap lexicon como respaldo (solo para retrieval, no canonicalization)
  const { buildFullConceptMap, buildCollocationMap: bcm } = require("../scripts/bootstrap-lexicon");
  const bootstrap = buildFullConceptMap();
  
  // El mapa para canonicalización SOLO usa pares atestiguados
  const canonMap = new Map(attested);
  
  // El mapa completo (attested + bootstrap) para retrieval
  const fullMap = new Map(bootstrap);
  for (const [k, v] of attested) {
    fullMap.set(k, v);  // attested overwrites bootstrap
  }
  
  return { canonMap, fullMap, attestedSize: attested.size, bootstrapSize: bootstrap.size };
}

function learnConceptPairsFromCorpus(docs = [], minCount = 3) {
  const stop = new Set(["el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "en", "a", "y", "o", "que", "se", "por", "para", "con", "sobre"]);
  const pairCounts = new Map();
  const docsById = new Map(docs.map((d) => [d.id, d]));
  const contextSig = (tokens, i) => `${tokens[i - 1] ?? "_"}|${tokens[i + 1] ?? "_"}`;

  for (const doc of docs) {
    if (!doc?.text || !doc?.id) continue;
    if (doc.id.includes("-var-")) {
      const baseId = doc.id.split("-var-")[0];
      const base = docsById.get(baseId);
      if (!base?.text) continue;

      const src = tokenize(normalizeText(doc.text)).filter((t) => t.length > 2 && !stop.has(t));
      const tgt = tokenize(normalizeText(base.text)).filter((t) => t.length > 2 && !stop.has(t));
      const srcSet = new Set(src);
      const tgtSet = new Set(tgt);

      const onlySrc = src.filter((t) => !tgtSet.has(t));
      const onlyTgt = tgt.filter((t) => !srcSet.has(t));

      for (let i = 0; i < onlySrc.length; i++) {
        const from = onlySrc[i];
        const fromCtx = contextSig(src, src.indexOf(from));
        for (let j = 0; j < onlyTgt.length; j++) {
          const to = onlyTgt[j];
          const toCtx = contextSig(tgt, tgt.indexOf(to));
          if (from === to) continue;
          // Alineamiento por contexto local: subir señal cuando el entorno coincide
          const key = `${from}\t${to}`;
          const bump = fromCtx === toCtx ? 2 : 1;
          pairCounts.set(key, (pairCounts.get(key) ?? 0) + bump);
        }
      }
    }
  }

  const learned = new Map();
  for (const [key, count] of pairCounts.entries()) {
    if (count < minCount) continue;
    const [from, to] = key.split("\t");
    learned.set(from, to);
  }
  return learned;
}

function buildCollocationMap() {
  const { buildCollocationMap: bcm } = require("../scripts/bootstrap-lexicon");
  return bcm();
}

function learnCollocationsFromCorpus(docs = [], conceptMap = new Map(), minCount = 2) {
  const PREPOSITIONS = new Set(["a", "en", "de", "por", "sobre", "con", "para", "sin", "entre", "tras"]);
  const counts = new Map();

  for (const doc of docs) {
    const tokens = tokenize(normalizeText(doc?.text ?? ""));
    for (let i = 0; i < tokens.length - 1; i++) {
      const word = tokens[i];
      const next = tokens[i + 1];
      if (!PREPOSITIONS.has(next)) continue;
      const key = `${word}\t${next}`;
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
  }

  const learned = new Map();
  for (const [key, count] of counts.entries()) {
    if (count < minCount) continue;
    const [verbLike, prep] = key.split("\t");
    learned.set(verbLike, prep);
    const canonical = conceptMap.get(verbLike);
    if (canonical && !learned.has(canonical)) {
      learned.set(canonical, prep);
    }
  }
  return learned;
}

async function train(epochs = 10, targetDocs = 5000, options = {}) {
  console.log(`\n🚀 CHL Frontier Training — ${targetDocs} documentos, ${epochs} épocas\n`);
  
  // 1. Construir corpus
  console.log("📦 Construyendo corpus...");
  const corpus = options.corpusJsonl
    ? await loadCorpusFromJsonl(options.corpusJsonl, targetDocs, options)
    : buildLargeCorpus(targetDocs);
  console.log(`   ${corpus.docs.length} documentos, ${corpus.querySamples.length} queries`);
  if (options.corpusJsonl) {
    console.log(`   corpus real: ${options.corpusJsonl}`);
  }
  const docTextById = new Map(corpus.docs.map((d) => [d.id, d.text]));
  
  // 2. Construir mapa de conceptos
  const { canonMap, fullMap } = buildConceptMap(baseFacts);
  const corpusPairs = learnConceptPairsFromCorpus(corpus.docs, 1);
  for (const [from, to] of corpusPairs) {
    fullMap.set(from, to);
    if (!canonMap.has(from)) canonMap.set(from, to);
  }
  const totalPairs = fullMap.size;
  const attestedPairs = canonMap.size;
  console.log(`   ${attestedPairs} pares atestiguados + ${totalPairs - attestedPairs} bootstrap = ${totalPairs} totales`);
  
  // 3. Inicializar trainer + attention
  const collocationMap = buildCollocationMap();
  const learnedCollocations = learnCollocationsFromCorpus(corpus.docs, fullMap, 2);
  for (const [verb, prep] of learnedCollocations) {
    collocationMap.set(verb, prep);
  }
  console.log(`   + ${corpusPairs.size} concept-pairs de corpus, ${learnedCollocations.size} colocaciones aprendidas`);
  // Usar fullMap para retrieval (resolveConcept, conceptIndex)
  // La canonicalización en memory.js usa canonMap (más conservador)
  const trainer = new LexiconTrainer({ conceptMap: fullMap, collocationMap, seed: 42 });
  // Guardar canonMap para canonicalización
  trainer._canonMap = canonMap;
  const attention = new HyperAttentionContext({ seed: 42 });
  const decoder = new HyperDecoder({ lexiconTrainer: trainer, seed: 42 });
  
  // Pre-entrenar el decoder con los textos del corpus
  const allTexts = [...new Set(corpus.docs.map(d => d.text).filter(Boolean))];
  decoder.trainOnExamples(allTexts.slice(0, 200));
  
  console.log(`   Trainer: ${trainer.snapshot().prototypeCount} prototipos`);
  
  // 4. Insertar corpus en CHL
  console.log("📥 Insertando documentos...");
  const chl = new CHL({
    profile: "large",
    seed: 42,
    maxEntries: options.maxEntries ?? undefined,
    lexiconTrainer: trainer,
    attention: attention,
  });
  console.log(`   maxEntries efectivo: ${chl.memory.maxEntries}`);
  
  let insertStart = performance.now();
  const batchSize = options.batchSize ?? 10000;
  for (let i = 0; i < corpus.docs.length; i += batchSize) {
    const chunk = corpus.docs.slice(i, i + batchSize).map((doc) => ({
      input: doc.text,
      payload: { fact: doc.id, category: doc.category },
      metadata: { quality: doc.category === "noise" ? 2 : 8 },
    }));
    chl.rememberBatch(chunk);
  }
  console.log(`   ${corpus.docs.length} docs en ${((performance.now() - insertStart) / 1000).toFixed(1)}s`);
  
  // 5. Evaluación inicial (época 0)
  console.log("\n📊 Época 0 (sin entrenar):");
  const baseline = evaluate(chl, corpus.querySamples, {
    docTextById,
    maxEval: options.evalQueries ?? corpus.querySamples.length,
    progressEvery: options.evalProgressEvery ?? 200,
    fastEval: options.fastEval,
    disableSecondPass: options.disableSecondPass,
    secondPassThreshold: options.secondPassThreshold,
  });
  printMetrics(baseline);
  
  // 6. Ciclo de entrenamiento
  const history = [{ epoch: 0, ...baseline }];
  const allSamples = corpus.querySamples;
  const { prototypeVectorFromText: pvft } = require("../src/hypervector");
  
  // Directorio de salida para checkpoints
  const outDir = path.resolve(__dirname, "..", "artifacts");
  fs.mkdirSync(outDir, { recursive: true });
  const patience = 3;
  let noImprove = 0;
  let best = {
    epoch: 0,
    recallAt1: baseline.recallAt1,
    mrr: baseline.mrr,
    score: baseline.recallAt1 + baseline.mrr,
  };
  let bestCheckpointPath = path.join(outDir, "concepts-prototypes-best.json");
  trainer.prototypesPath = bestCheckpointPath;
  trainer.save();

  for (let epoch = 1; epoch <= epochs; epoch++) {
    console.log(`\n🔄 Época ${epoch}/${epochs} — Entrenando...`);
    let corrections = 0;
    let compositions = 0;

    // Currículum: entrenar SOLO en fallos + hard negatives (bajo margen)
    const failedSamples = [];
    const hardNegatives = [];
    for (const sample of allSamples) {
      const result = chl.recall(sample.query, { topK: 5 });
      const ranked = result.candidates.map(candidateId);
      const topId = ranked[0];
      if (topId !== sample.expectedId) {
        failedSamples.push(sample);
      } else if ((result.confidence ?? 0) < 0.45) {
        hardNegatives.push(sample);
      }
    }
    const hardBudget = Math.min(hardNegatives.length, Math.max(20, Math.floor(failedSamples.length * 0.8)));
    const trainingPool = [...failedSamples, ...hardNegatives.slice(0, hardBudget)];
    const shuffled = trainingPool.sort(() => Math.random() - 0.5);
    const progressTotal = shuffled.length || 1;

    // Decaimiento por época para feedback y atención (evita sobreajuste)
    const decay = Math.max(0.35, 1 - ((epoch - 1) / Math.max(1, epochs)) * 0.65);
    const attnWeights = {
      hash: 0.03 * decay,
      concept: 0.02 * decay,
      prototype: 0.03 * decay,
      intent: 0.01 * decay,
    };
    const rejectedBudget = decay < 0.65 ? 1 : 2;

    for (let i = 0; i < shuffled.length; i++) {
      const sample = shuffled[i];
      const result = chl.recall(sample.query, { topK: 5 });
      const ranked = result.candidates.map(candidateId);
      const topId = ranked[0];

      if (topId !== sample.expectedId) {
        // Fallo → feedback negativo: reforzar concepto correcto, penalizar incorrecto
        const expectedConcept = trainer.resolveConcept(sample.query);
        const wrongConcept = trainer.resolveConcept(
          result.candidates[0]?.entry?.text ?? ""
        );
        
        const rejectedIds = [];
        if (wrongConcept && wrongConcept !== expectedConcept) {
          rejectedIds.push(wrongConcept);
        }
        if (ranked.length > 1 && ranked[1] !== sample.expectedId) {
          const secondConcept = trainer.resolveConcept(
            result.candidates[1]?.entry?.text ?? ""
          );
          if (secondConcept && secondConcept !== expectedConcept) {
            rejectedIds.push(secondConcept);
          }
        }
        if (rejectedIds.length > rejectedBudget) {
          rejectedIds.length = rejectedBudget;
        }
        
        if (expectedConcept) {
          trainer.applyOnlineFeedback(sample.query, expectedConcept, rejectedIds);
          corrections++;
        }
        
        // Actualizar atención
        const qv = pvft(sample.query, 256, 42);
        attention.updateKeys(qv, attnWeights);
      }
      
      if (i > 0 && i % 2000 === 0) {
        process.stdout.write(`\r   ${i}/${progressTotal} queries (${corrections} correcciones)...`);
      }
    }
    
    console.log(`\r   ${shuffled.length}/${progressTotal} queries (${corrections} correcciones, ${compositions} composiciones)`);
    // El trainer se actualiza por referencia, no necesita rebuild
    
    // Evaluar composición
    console.log("   Evaluando HyperDecoder...");
    let composeOk = 0;
    let composeTotal = 0;
    for (const sample of allSamples.slice(0, 30)) {
      const result = chl.recall(sample.query, { topK: 3 });
      if (result.candidates.length > 0) {
        const composed = decoder.compose(sample.query, result.candidates);
        if (composed.composed && composed.text.length > 3) {
          // Verificar que la respuesta contiene al menos una palabra clave del expected
          const expectedEntry = corpus.docs.find(d => d.id === sample.expectedId);
          if (expectedEntry) {
            const keywords = expectedEntry.text.toLowerCase().split(/\s+/).filter(w => w.length > 3);
            const hasKeyword = keywords.some(kw => composed.text.toLowerCase().includes(kw));
            if (hasKeyword) composeOk++;
          }
        }
        composeTotal++;
      }
    }
    const composeRate = composeTotal > 0 ? (composeOk / composeTotal * 100).toFixed(1) : '0';
    
    // Evaluar recall
    const metrics = evaluate(chl, corpus.querySamples, {
      docTextById,
      maxEval: options.evalQueries ?? corpus.querySamples.length,
      progressEvery: options.evalProgressEvery ?? 200,
      fastEval: options.fastEval,
      disableSecondPass: options.disableSecondPass,
      secondPassThreshold: options.secondPassThreshold,
    });
    printMetrics(metrics);
    console.log(`   HyperDecoder: ${composeOk}/${composeTotal} respuestas correctas (${composeRate}%)`);
    history.push({ epoch, ...metrics, corrections, compositions, composeOk, composeTotal });
    
    // Guardar checkpoint
    const ckptPath = path.join(outDir, `concepts-prototypes-epoch${epoch}.json`);
    trainer.prototypesPath = ckptPath;
    trainer.save();

    // Early stopping sobre score combinado recall@1 + MRR
    const score = metrics.recallAt1 + metrics.mrr;
    if (score > best.score + 1e-6) {
      best = { epoch, recallAt1: metrics.recallAt1, mrr: metrics.mrr, score };
      bestCheckpointPath = path.join(outDir, "concepts-prototypes-best.json");
      fs.copyFileSync(ckptPath, bestCheckpointPath);
      noImprove = 0;
      console.log(`   ✅ Nuevo mejor en época ${epoch} (score ${(score).toFixed(4)})`);
    } else {
      noImprove += 1;
      console.log(`   ⏸️ Sin mejora (${noImprove}/${patience})`);
      if (noImprove >= patience) {
        console.log(`   🛑 Early stopping en época ${epoch} (patience=${patience})`);
        break;
      }
    }
  }
  
  // 7. Guardar estado
  trainer.prototypesPath = path.join(outDir, "concepts-prototypes.json");
  trainer.save();
  
  const report = {
    mode: "frontier-training",
    targetDocs,
    epochs,
    baseline: history[0],
    final: history[history.length - 1],
    best,
    bestCheckpointPath,
    history: history.map(h => ({
      epoch: h.epoch,
      recallAt1: h.recallAt1,
      recallAt3: h.recallAt3,
      mrr: h.mrr,
      failureCount: h.failureCount,
      failureByType: h.failureByType,
      p95Us: h.p95Us,
    })),
    trainer: trainer.snapshot(),
    attention: attention.snapshot(),
    decoder: decoder.snapshot(),
  };
  
  const reportPath = path.join(outDir, "chl-frontier-training.json");
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
  
  console.log(`\n✅ Entrenamiento completo. Reporte: ${reportPath}`);
  console.log(`   Trainer: ${trainer.snapshot().prototypeCount} prototipos, ${trainer.snapshot().feedbackCount} feedbacks`);
  console.log(`   Attention: ${attention.snapshot().updateCount} actualizaciones`);
  console.log(`   Decoder: ${decoder.snapshot().compositions} composiciones`);
  
  return report;
}

function printMetrics(m) {
  console.log(`   recall@1: ${(m.recallAt1 * 100).toFixed(2)}%  recall@3: ${(m.recallAt3 * 100).toFixed(2)}%  MRR: ${m.mrr.toFixed(4)}  fallos: ${m.failureCount}  p95: ${m.p95Us.toFixed(1)}µs`);
  if (m.failureByType) {
    console.log(`   fallos tipo → lexical:${m.failureByType.lexical} syntax:${m.failureByType.syntax} concept_miss:${m.failureByType.concept_miss}`);
  }
}

// ─── Main ─────────────────────────────────────────────────

if (require.main === module) {
  const args = process.argv.slice(2);
  const epochs = parseInt(args.find(a => a.startsWith("--epochs="))?.split("=")[1] || "10");
  const docs = parseInt(args.find(a => a.startsWith("--docs="))?.split("=")[1] || "5000");
  const maxEntriesArg = args.find(a => a.startsWith("--maxEntries="))?.split("=")[1];
  const batchSizeArg = args.find(a => a.startsWith("--batchSize="))?.split("=")[1];
  const corpusJsonl = args.find(a => a.startsWith("--corpusJsonl="))?.split("=")[1];
  const evalQueriesArg = args.find(a => a.startsWith("--evalQueries="))?.split("=")[1];
  const evalProgressEveryArg = args.find(a => a.startsWith("--evalProgressEvery="))?.split("=")[1];
  const secondPassThresholdArg = args.find(a => a.startsWith("--secondPassThreshold="))?.split("=")[1];
  const evalRatioArg = args.find(a => a.startsWith("--evalRatio="))?.split("=")[1];
  const minDocCharsArg = args.find(a => a.startsWith("--minDocChars="))?.split("=")[1];
  const maxEntries = maxEntriesArg ? parseInt(maxEntriesArg, 10) : undefined;
  const batchSize = batchSizeArg ? parseInt(batchSizeArg, 10) : undefined;
  const evalQueries = evalQueriesArg ? parseInt(evalQueriesArg, 10) : undefined;
  const evalProgressEvery = evalProgressEveryArg ? parseInt(evalProgressEveryArg, 10) : undefined;
  const secondPassThreshold = secondPassThresholdArg ? Number(secondPassThresholdArg) : undefined;
  const fastEval = args.includes("--fastEval");
  const hardEval = args.includes("--hardEval");
  const disableSecondPass = args.includes("--disableSecondPass");
  const evalRatio = evalRatioArg ? Number(evalRatioArg) : undefined;
  const minDocChars = minDocCharsArg ? parseInt(minDocCharsArg, 10) : undefined;
  
  train(epochs, docs, {
    maxEntries,
    batchSize,
    corpusJsonl,
    evalQueries,
    evalProgressEvery,
    fastEval,
    hardEval,
    disableSecondPass,
    secondPassThreshold,
    evalRatio,
    minDocChars,
  }).catch(err => {
    console.error("❌ Error:", err.message);
    process.exit(1);
  });
}

module.exports = { train, buildLargeCorpus, evaluate, buildConceptMap };
