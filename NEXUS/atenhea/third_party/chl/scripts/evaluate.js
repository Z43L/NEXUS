const fs = require("node:fs");
const path = require("node:path");
const { performance } = require("node:perf_hooks");
const { CHL: JSCHL, CHL, tokenize } = require("../src");
const {
  learnConceptPairsFromExamples,
  learnPhrasePairsFromExamples,
  serializeConceptMap,
} = require("../src/concepts");

const baseFacts = [
  {
    id: "cat-table",
    text: "el gato duerme sobre la mesa",
    paraphrases: ["el gato duerme en la mesa", "el felino descansa sobre la mesa"],
  },
  {
    id: "dog-park",
    text: "el perro corre por el parque",
    paraphrases: ["el perro corre en el parque", "el can corre por el parque"],
  },
  {
    id: "train-station",
    text: "el tren entra en la estacion",
    paraphrases: ["el tren llega a la estacion", "el tren se acerca a la estacion"],
  },
  {
    id: "rain-street",
    text: "la lluvia cae sobre la calle",
    paraphrases: ["la lluvia moja la calle", "la lluvia cae en la calle"],
  },
  {
    id: "memory-remembers",
    text: "la memoria guarda recuerdos utiles",
    paraphrases: ["la memoria conserva recuerdos utiles", "la memoria almacena recuerdos"],
  },
  {
    id: "drone-field",
    text: "el dron sobrevuela el campo",
    paraphrases: ["el dron vuela sobre el campo", "el dron cruza el campo"],
  },
  {
    id: "key-door",
    text: "la llave abre la puerta",
    paraphrases: ["la llave desbloquea la puerta", "la llave abre una puerta"],
  },
  {
    id: "river-city",
    text: "el rio atraviesa la ciudad",
    paraphrases: ["el rio cruza la ciudad", "el rio pasa por la ciudad"],
  },
  {
    id: "book-library",
    text: "el libro esta en la biblioteca",
    paraphrases: ["el libro queda en la biblioteca", "la biblioteca guarda el libro"],
  },
  {
    id: "bird-tree",
    text: "el pajaro se posa en el arbol",
    paraphrases: ["el pajaro descansa en el arbol", "el ave se posa en el arbol"],
  },
  {
    id: "coffee-kitchen",
    text: "el cafe humea en la cocina",
    paraphrases: ["el cafe esta caliente en la cocina", "el cafe humea dentro de la cocina"],
  },
  {
    id: "phone-battery",
    text: "el telefono carga la bateria",
    paraphrases: ["el telefono recarga la bateria", "la bateria del telefono se carga"],
  },
  {
    id: "lamp-room",
    text: "la lampara ilumina la habitacion",
    paraphrases: ["la lampara da luz a la habitacion", "la habitacion queda iluminada"],
  },
  {
    id: "car-road",
    text: "el coche circula por la carretera",
    paraphrases: ["el coche va por la carretera", "el automovil circula por la carretera"],
  },
  {
    id: "fish-river",
    text: "el pez nada en el rio",
    paraphrases: ["el pez se mueve en el rio", "el pez nada por el rio"],
  },
  {
    id: "student-class",
    text: "la estudiante toma apuntes en clase",
    paraphrases: ["la estudiante escribe apuntes en clase", "la alumna toma notas en clase"],
  },
  {
    id: "doctor-hospital",
    text: "el doctor atiende al paciente",
    paraphrases: ["el medico atiende al paciente", "el doctor cuida al paciente"],
  },
  {
    id: "chef-kitchen",
    text: "la chef prepara la cena",
    paraphrases: ["la cocinera prepara la cena", "la chef cocina la cena"],
  },
  {
    id: "window-open",
    text: "la ventana permanece abierta",
    paraphrases: ["la ventana sigue abierta", "la ventana esta abierta"],
  },
  {
    id: "forest-shadow",
    text: "la sombra cubre el bosque",
    paraphrases: ["la sombra cae sobre el bosque", "el bosque queda en sombra"],
  },
  {
    id: "music-speaker",
    text: "la musica suena en el altavoz",
    paraphrases: ["la musica sale del altavoz", "el altavoz reproduce musica"],
  },
  {
    id: "code-editor",
    text: "el codigo se escribe en el editor",
    paraphrases: ["el programador escribe codigo en el editor", "el editor contiene codigo"],
  },
  {
    id: "bridge-river",
    text: "el puente cruza el rio",
    paraphrases: ["el puente atraviesa el rio", "el puente esta sobre el rio"],
  },
  {
    id: "market-buy",
    text: "la persona compra pan en el mercado",
    paraphrases: ["la persona compra pan", "el mercado vende pan"],
  },
  {
    id: "garden-water",
    text: "la regadera riega el jardin",
    paraphrases: ["la regadera moja el jardin", "el jardin recibe agua"],
  },
  {
    id: "sun-warm",
    text: "el sol calienta la terraza",
    paraphrases: ["el sol calienta la superficie", "la terraza recibe calor del sol"],
  },
  {
    id: "mail-delivery",
    text: "el correo llega a la oficina",
    paraphrases: ["el correo entra en la oficina", "la oficina recibe correo"],
  },
  {
    id: "clock-time",
    text: "el reloj marca las tres",
    paraphrases: ["el reloj indica las tres", "las tres aparecen en el reloj"],
  },
  {
    id: "tablet-screen",
    text: "la pantalla muestra el mapa",
    paraphrases: ["la pantalla enseña el mapa", "el mapa aparece en la pantalla"],
  },
  {
    id: "library-quiet",
    text: "la biblioteca permanece en silencio",
    paraphrases: ["la biblioteca esta silenciosa", "el silencio domina la biblioteca"],
  },
];

const negationSeeds = [
  { id: "cat-table", query: "el gato no duerme sobre la mesa" },
  { id: "dog-park", query: "el perro no corre por el parque" },
  { id: "train-station", query: "el tren no entra en la estacion" },
  { id: "rain-street", query: "la lluvia no cae sobre la calle" },
  { id: "key-door", query: "la llave no abre la puerta" },
  { id: "river-city", query: "el rio no atraviesa la ciudad" },
  { id: "book-library", query: "el libro no esta en la biblioteca" },
  { id: "bird-tree", query: "el pajaro no se posa en el arbol" },
  { id: "coffee-kitchen", query: "el cafe no humea en la cocina" },
  { id: "phone-battery", query: "el telefono no carga la bateria" },
  { id: "lamp-room", query: "la lampara no ilumina la habitacion" },
  { id: "car-road", query: "el coche no circula por la carretera" },
  { id: "fish-river", query: "el pez no nada en el rio" },
  { id: "doctor-hospital", query: "el doctor no atiende al paciente" },
  { id: "chef-kitchen", query: "la chef no prepara la cena" },
];

const hardNoise = [
  "el gato duerme sobre la silla",
  "el perro corre por la calle",
  "el tren entra en el tunel",
  "la lluvia cae sobre el techo",
  "la memoria conserva datos utiles",
  "el dron sobrevuela la ciudad",
  "la llave abre el cajon",
  "el rio atraviesa la montana",
  "el libro esta en la mesa",
  "el pajaro se posa en la rama",
  "el cafe humea en el vaso",
  "el telefono carga el reloj",
  "la lampara ilumina el pasillo",
  "el coche circula por la avenida",
  "el pez nada en la pecera",
  "la estudiante toma apuntes en casa",
  "el doctor atiende la llamada",
  "la chef prepara el desayuno",
  "la ventana permanece cerrada",
  "la sombra cubre la pared",
  "la musica suena en los auriculares",
  "el codigo se escribe en la libreta",
  "el puente cruza el canal",
  "la persona compra pan en la tienda",
  "la regadera riega las flores",
  "el sol calienta el asfalto",
  "el correo llega al buzon",
  "el reloj marca las cuatro",
  "la pantalla muestra un video",
  "la biblioteca permanece vacia",
];

const largeTemplates = {
  subjects: [
    "gato",
    "perro",
    "tren",
    "lluvia",
    "memoria",
    "dron",
    "llave",
    "rio",
    "libro",
    "pajaro",
    "cafe",
    "telefono",
    "lampara",
    "coche",
    "pez",
    "estudiante",
    "doctor",
    "chef",
    "ventana",
    "sombra",
    "musica",
    "codigo",
    "puente",
    "persona",
    "regadera",
    "sol",
    "correo",
    "reloj",
    "pantalla",
    "biblioteca",
    "robot",
    "sensor",
    "nave",
    "archivo",
    "servidor",
    "modelo",
    "agente",
    "motor",
    "camara",
    "mapa",
    "alarma",
    "consulta",
    "indice",
    "vector",
    "nodo",
    "bateria",
    "cuaderno",
    "mesa",
    "silla",
    "teclado",
    "ventilador",
  ],
  verbs: [
    "duerme sobre",
    "corre por",
    "entra en",
    "cae sobre",
    "guarda en",
    "vuela sobre",
    "abre",
    "atraviesa",
    "esta en",
    "se posa en",
    "humea en",
    "carga",
    "ilumina",
    "circula por",
    "nada en",
    "toma apuntes en",
    "atiende a",
    "prepara",
    "permanece en",
    "cubre",
    "suena en",
    "escribe en",
    "cruza",
    "compra en",
    "riega",
    "calienta",
    "llega a",
    "marca",
    "muestra",
    "observa",
    "analiza",
    "sincroniza con",
    "almacena",
    "procesa",
    "encuentra",
    "rastrea",
    "protege",
    "activa",
    "desactiva",
    "recibe",
    "prioriza",
    "aprende de",
  ],
  objects: [
    "la mesa",
    "el parque",
    "la estacion",
    "la calle",
    "recuerdos utiles",
    "el campo",
    "la puerta",
    "la ciudad",
    "la biblioteca",
    "el arbol",
    "la cocina",
    "la bateria",
    "la habitacion",
    "la carretera",
    "el rio",
    "la clase",
    "el paciente",
    "la cena",
    "la ventana",
    "el bosque",
    "el altavoz",
    "el editor",
    "el rio",
    "el mercado",
    "el jardin",
    "la terraza",
    "la oficina",
    "las tres",
    "el mapa",
    "el silencio",
    "el servidor",
    "el sensor",
    "la red",
    "el archivo",
    "el modelo",
    "la consulta",
    "el indice",
    "el vector",
    "el nodo",
    "la energia",
    "el cuaderno",
    "la mesa",
    "la silla",
    "el teclado",
    "el ventilador",
  ],
  modifiers: [
    "con cuidado",
    "cada noche",
    "en silencio",
    "con rapidez",
    "sin ruido",
    "de forma estable",
    "con precision",
    "en la nube",
    "en local",
    "a tiempo",
    "bajo demanda",
    "con memoria",
    "para siempre",
    "por defecto",
    "durante el dia",
    "durante la noche",
  ],
};

const largeParaphraseVerbs = [
  ["duerme sobre", "descansa sobre"],
  ["corre por", "se mueve por"],
  ["entra en", "llega a"],
  ["cae sobre", "desciende sobre"],
  ["guarda en", "conserva en"],
  ["vuela sobre", "sobrevuela"],
  ["abre", "desbloquea"],
  ["atraviesa", "cruza"],
  ["esta en", "permanece en"],
  ["se posa en", "descansa en"],
  ["humea en", "desprende humo en"],
  ["carga", "recarga"],
  ["ilumina", "da luz a"],
  ["circula por", "va por"],
  ["nada en", "se mueve en"],
  ["toma apuntes en", "escribe apuntes en"],
  ["atiende a", "cuida a"],
  ["prepara", "cocina"],
  ["permanece en", "sigue en"],
  ["cubre", "tapiza"],
  ["suena en", "resuena en"],
  ["escribe en", "anota en"],
  ["cruza", "atraviesa"],
  ["compra en", "adquiere en"],
  ["riega", "moja"],
  ["calienta", "templa"],
  ["llega a", "arriba a"],
  ["marca", "indica"],
  ["muestra", "enseña"],
  ["observa", "vigila"],
  ["analiza", "examina"],
  ["sincroniza con", "coordina con"],
  ["almacena", "guarda"],
  ["procesa", "maneja"],
  ["encuentra", "localiza"],
  ["rastrea", "sigue"],
  ["protege", "resguarda"],
  ["activa", "enciende"],
  ["desactiva", "apaga"],
  ["recibe", "obtiene"],
  ["prioriza", "favorece"],
  ["aprende de", "absorbe de"],
];

function p95(values) {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const idx = Math.min(sorted.length - 1, Math.ceil(sorted.length * 0.95) - 1);
  return sorted[idx];
}

function median(values) {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
}

function normalize(text) {
  return String(text)
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function tokens(text) {
  return tokenize(normalize(text));
}

function candidateId(candidate) {
  return (
    candidate?.payload?.payload?.fact ??
    candidate?.payload?.fact ??
    candidate?.entry?.payload?.fact ??
    candidate?.entry?.payload?.payload?.fact ??
    candidate?.entry?.payload?.id ??
    candidate?.entry?.payload ??
    candidate?.payload?.id ??
    null
  );
}

function negate(text) {
  const parts = tokens(text);
  if (parts.length < 3) return `no ${normalize(text)}`;
  return `${parts[0]} ${parts[1]} no ${parts.slice(2).join(" ")}`;
}

function paraphraseFromText(text) {
  const replacements = [
    ["duerme", "descansa"],
    ["corre", "se mueve"],
    ["entra", "llega"],
    ["cae", "desciende"],
    ["guarda", "conserva"],
    ["sobrevuela", "vuela sobre"],
    ["abre", "desbloquea"],
    ["atraviesa", "cruza"],
    ["esta", "permanece"],
    ["posa", "se apoya"],
    ["humea", "desprende humo"],
    ["carga", "recarga"],
    ["ilumina", "da luz a"],
    ["circula", "va"],
    ["nada", "se desplaza"],
    ["toma", "anota"],
    ["atiende", "ayuda"],
    ["prepara", "cocina"],
    ["permanece", "sigue"],
    ["cubre", "tapiza"],
    ["suena", "resuena"],
    ["escribe", "anota"],
    ["compra", "adquiere"],
    ["riega", "moja"],
    ["calienta", "templa"],
    ["llega", "arriba"],
    ["marca", "indica"],
    ["muestra", "enseña"],
  ];

  let variant = normalize(text);
  for (const [from, to] of replacements) {
    if (variant.includes(` ${from} `) || variant.startsWith(`${from} `) || variant.endsWith(` ${from}`)) {
      variant = variant.replace(new RegExp(`\\b${from}\\b`, "g"), to);
      break;
    }
  }
  return variant;
}

function buildCorpus() {
  const docs = [];
  const querySamples = [];
  const conceptPairs = [];

  for (const fact of baseFacts) {
    const factDoc = {
      id: fact.id,
      text: fact.text,
      type: "fact",
      category: "positive",
    };
    docs.push(factDoc);

    const positiveQueries = new Set([fact.text, ...fact.paraphrases.map((query) => normalize(query)), paraphraseFromText(fact.text)]);
    for (const query of positiveQueries) {
      querySamples.push({ query, expectedId: fact.id, category: "positive" });
      if (query !== fact.text) {
        conceptPairs.push([fact.text, query]);
      }
    }

    const negQuery = negate(fact.text);
    docs.push({
      id: `${fact.id}-neg`,
      text: negQuery,
      type: "fact",
      category: "negation",
    });
    querySamples.push({ query: negQuery, expectedId: `${fact.id}-neg`, category: "negation" });
    querySamples.push({ query: `no ${normalize(fact.text)}`, expectedId: `${fact.id}-neg`, category: "negation" });
  }

  for (const [index, text] of hardNoise.entries()) {
    docs.push({
      id: `noise-${index}`,
      text: normalize(text),
      type: "noise",
      category: "hard-noise",
    });
  }

  return { docs, querySamples, conceptPairs };
}

function buildLargeCorpus(targetDocs = 10000) {
  const docs = [];
  const querySamples = [];
  const conceptPairs = [];
  const seen = new Set();
  const subjects = largeTemplates.subjects;
  const verbs = largeTemplates.verbs;
  const objects = largeTemplates.objects;
  const modifiers = largeTemplates.modifiers;
  let i = 0;

  for (const subject of subjects) {
    for (const verb of verbs) {
      for (const object of objects) {
        for (const modifier of modifiers) {
          const text = normalize(`el ${subject} ${verb} ${object} ${modifier}`);
          if (seen.has(text)) continue;
          seen.add(text);
          const id = `large-${String(i).padStart(5, "0")}`;
          docs.push({
            id,
            text,
            type: "fact",
            category: "large-positive",
          });

          const verbPair = largeParaphraseVerbs.find(([base]) => base === verb);
          const paraphrase = verbPair ? normalize(`el ${subject} ${verbPair[1]} ${object} ${modifier}`) : paraphraseFromText(text);
          querySamples.push({ query: text, expectedId: id, category: "large-positive" });
          querySamples.push({ query: paraphrase, expectedId: id, category: "large-paraphrase" });
          if (paraphrase !== text) {
            conceptPairs.push([text, paraphrase]);
          }
          if (i % 4 === 0) {
            querySamples.push({ query: negate(text), expectedId: `${id}-neg`, category: "large-negation" });
          }

          docs.push({
            id: `${id}-neg`,
            text: negate(text),
            type: "fact",
            category: "large-negation",
          });

          i += 1;
          if (docs.length >= targetDocs) {
            return { docs, querySamples, conceptPairs };
          }
        }
      }
    }
  }

  while (docs.length < targetDocs) {
    const subject = subjects[docs.length % subjects.length];
    const verb = verbs[(docs.length * 7) % verbs.length];
    const object = objects[(docs.length * 13) % objects.length];
    const modifier = modifiers[(docs.length * 5) % modifiers.length];
    const text = normalize(`el ${subject} ${verb} ${object} ${modifier}`);
    if (seen.has(text)) continue;
    seen.add(text);
    const id = `large-${String(i).padStart(5, "0")}`;
    docs.push({ id, text, type: "fact", category: "large-positive" });
    querySamples.push({ query: text, expectedId: id, category: "large-positive" });
    if (docs.length >= targetDocs) break;
    docs.push({ id: `${id}-neg`, text: negate(text), type: "fact", category: "large-negation" });
    querySamples.push({ query: negate(text), expectedId: `${id}-neg`, category: "large-negation" });
    i += 1;
  }

  return { docs, querySamples, conceptPairs };
}

function makeIndex(corpus) {
  const docTokens = corpus.docs.map((doc) => new Set(tokens(doc.text)));
  const df = new Map();
  const termToDocs = new Map();

  for (let i = 0; i < corpus.docs.length; i += 1) {
    for (const term of docTokens[i]) {
      df.set(term, (df.get(term) ?? 0) + 1);
      if (!termToDocs.has(term)) termToDocs.set(term, new Set());
      termToDocs.get(term).add(i);
    }
  }

  const idf = new Map();
  for (const [term, count] of df.entries()) {
    idf.set(term, Math.log((corpus.docs.length + 1) / (count + 1)) + 1);
  }

  const docLengths = docTokens.map((set) => set.size);
  const avgDocLen = docLengths.reduce((sum, len) => sum + len, 0) / docLengths.length;

  return { ...corpus, docTokens, df, idf, termToDocs, docLengths, avgDocLen };
}

function exactRanker(index, query) {
  const queryText = normalize(query);
  return index.docs
    .map((doc) => ({ doc, score: doc.text === queryText ? 1 : 0 }))
    .filter((item) => item.score > 0)
    .sort((a, b) => b.score - a.score);
}

function jaccardRanker(index, query) {
  const q = new Set(tokens(query));
  return index.docs
    .map((doc, i) => {
      const dt = index.docTokens[i];
      const inter = [...q].filter((term) => dt.has(term)).length;
      const union = new Set([...q, ...dt]).size || 1;
      return { doc, score: inter / union };
    })
    .sort((a, b) => b.score - a.score);
}

function bm25Ranker(index, query) {
  const qTokens = tokens(query);
  const k1 = 1.2;
  const b = 0.75;
  return index.docs
    .map((doc, i) => {
      const dt = index.docTokens[i];
      let score = 0;
      for (const term of qTokens) {
        if (!dt.has(term)) continue;
        const tf = 1;
        const idf = index.idf.get(term) ?? 0;
        score += idf * ((tf * (k1 + 1)) / (tf + k1 * (1 - b + (b * index.docLengths[i]) / index.avgDocLen)));
      }
      return { doc, score };
    })
    .sort((a, b) => b.score - a.score);
}

function evaluateRanker(name, ranker, index, samples, topK = 3) {
  const latenciesUs = [];
  let recallAt1 = 0;
  let recallAt3 = 0;
  let meanRank = 0;
  let mrr = 0;
  const categoryStats = new Map();

  for (const sample of samples) {
    const start = performance.now();
    const ranked = ranker(index, sample.query);
    const elapsedUs = (performance.now() - start) * 1000;
    latenciesUs.push(elapsedUs);

    const top = ranked.slice(0, topK).map((item) => item.doc.id);
    const rank = ranked.findIndex((item) => item.doc.id === sample.expectedId);
    const category = categoryStats.get(sample.category) ?? { queryCount: 0, recallAt1: 0, recallAt3: 0 };
    category.queryCount += 1;
    if (top[0] === sample.expectedId) category.recallAt1 += 1;
    if (top.includes(sample.expectedId)) category.recallAt3 += 1;
    categoryStats.set(sample.category, category);

    if (top[0] === sample.expectedId) recallAt1 += 1;
    if (top.includes(sample.expectedId)) recallAt3 += 1;
    if (rank !== -1) {
      meanRank += rank + 1;
      mrr += 1 / (rank + 1);
    }
  }

  return {
    name,
    queryCount: samples.length,
    recallAt1: recallAt1 / samples.length,
    recallAt3: recallAt3 / samples.length,
    meanRank: meanRank / samples.length,
    mrr: mrr / samples.length,
    p95LatencyUs: p95(latenciesUs),
    medianLatencyUs: median(latenciesUs),
    categoryStats: Object.fromEntries(
      [...categoryStats.entries()].map(([category, stats]) => [
        category,
        {
          queryCount: stats.queryCount,
          recallAt1: stats.recallAt1 / stats.queryCount,
          recallAt3: stats.recallAt3 / stats.queryCount,
        },
      ])
    ),
  };
}

function evaluateChl(engine, samples) {
  const latenciesUs = [];
  let recallAt1 = 0;
  let recallAt3 = 0;
  let meanRank = 0;
  let mrr = 0;
  const categoryStats = new Map();

  for (const sample of samples) {
    const start = performance.now();
    const result = engine.recall(sample.query, { topK: 3 });
    const elapsedUs = (performance.now() - start) * 1000;
    latenciesUs.push(elapsedUs);
    const ranked = result.candidates.map(candidateId);
    const rank = ranked.indexOf(sample.expectedId);
    const category = categoryStats.get(sample.category) ?? { queryCount: 0, recallAt1: 0, recallAt3: 0 };
    category.queryCount += 1;
    if (ranked[0] === sample.expectedId) category.recallAt1 += 1;
    if (ranked.includes(sample.expectedId)) category.recallAt3 += 1;
    categoryStats.set(sample.category, category);

    if (ranked[0] === sample.expectedId) recallAt1 += 1;
    if (ranked.includes(sample.expectedId)) recallAt3 += 1;
    if (rank !== -1) {
      meanRank += rank + 1;
      mrr += 1 / (rank + 1);
    }
  }

  return {
    queryCount: samples.length,
    recallAt1: recallAt1 / samples.length,
    recallAt3: recallAt3 / samples.length,
    meanRank: meanRank / samples.length,
    mrr: mrr / samples.length,
    p95LatencyUs: p95(latenciesUs),
    medianLatencyUs: median(latenciesUs),
    categoryStats: Object.fromEntries(
      [...categoryStats.entries()].map(([category, stats]) => [
        category,
        {
          queryCount: stats.queryCount,
          recallAt1: stats.recallAt1 / stats.queryCount,
          recallAt3: stats.recallAt3 / stats.queryCount,
        },
      ])
    ),
  };
}

function attachCorpus(engine, corpus) {
  for (const doc of corpus.docs) {
    if (doc.type === "fact") {
      engine.remember(doc.text, { fact: doc.id, category: doc.category }, { quality: doc.category === "negation" ? 7 : 8 });
    } else {
      engine.remember(doc.text, { fact: doc.id, category: doc.category }, { quality: 2 });
    }
  }
}

function prepareLearnedConceptLexicon(corpus, name) {
  const learnedMap = learnConceptPairsFromExamples(corpus.conceptPairs);
  const learnedPhraseMap = learnPhrasePairsFromExamples(corpus.conceptPairs);
  const outDir = path.resolve(__dirname, "..", "artifacts");
  fs.mkdirSync(outDir, { recursive: true });
  const outFile = path.join(outDir, name);
  const phraseFile = outFile.replace(/\.tsv$/i, "-phrases.tsv");
  fs.writeFileSync(outFile, serializeConceptMap(learnedMap));
  fs.writeFileSync(phraseFile, serializeConceptMap(learnedPhraseMap));
  process.env.CHL_CONCEPTS_PATH = outFile;
  process.env.CHL_PHRASES_PATH = phraseFile;
  return {
    path: outFile,
    size: learnedMap.size,
    phrasePath: phraseFile,
    phraseSize: learnedPhraseMap.size,
  };
}

function runScaledBenchmark({ mode, targetDocs, sampleSize, outFileName, conceptFileName }) {
  const corpus = makeIndex(buildLargeCorpus(targetDocs));
  const concepts = prepareLearnedConceptLexicon(corpus, conceptFileName);
  const samples = corpus.querySamples.slice(0, sampleSize);
  const nativeChl = new CHL({
    profile: "large",
    seed: 42,
  });
  const jsChl = new JSCHL({
    profile: "large",
    seed: 42,
  });

  const nativeLoadStart = performance.now();
  attachCorpus(nativeChl, corpus);
  const nativeLoadMs = performance.now() - nativeLoadStart;

  const jsLoadStart = performance.now();
  attachCorpus(jsChl, corpus);
  const jsLoadMs = performance.now() - jsLoadStart;

  const report = {
    mode,
    dataset: {
      docs: corpus.docs.length,
      queries: samples.length,
      positiveDocs: corpus.docs.filter((doc) => doc.category === "large-positive").length,
      negationDocs: corpus.docs.filter((doc) => doc.category === "large-negation").length,
      learnedConcepts: concepts.size,
      learnedPhrases: concepts.phraseSize,
      queryCategories: Object.fromEntries(
        [...new Set(samples.map((sample) => sample.category))].map((category) => [
          category,
          samples.filter((sample) => sample.category === category).length,
        ])
      ),
    },
    systems: [
      { name: "chl-native", loadMs: nativeLoadMs, profile: nativeChl.snapshot().profile ?? "large", ...summarizeChl("chl-native", nativeChl, samples) },
      { name: "chl-js", loadMs: jsLoadMs, profile: jsChl.profile?.() ?? "large", ...summarizeChl("chl-js", jsChl, samples) },
    ],
  };

  const outDir = path.resolve(__dirname, "..", "artifacts");
  fs.mkdirSync(outDir, { recursive: true });
  const outFile = path.join(outDir, outFileName);
  fs.writeFileSync(outFile, JSON.stringify(report, null, 2));

  console.log(JSON.stringify(report, null, 2));
  console.log("");
  console.table(
    report.systems.map((system) => ({
      system: system.name,
      docs: report.dataset.docs,
      queries: report.dataset.queries,
      profile: system.profile ?? "",
      loadMs: system.loadMs.toFixed(2),
      recallAt1: system.recallAt1.toFixed(3),
      recallAt3: system.recallAt3.toFixed(3),
      mrr: system.mrr.toFixed(3),
      medianLatencyUs: system.medianLatencyUs.toFixed(2),
      p95LatencyUs: system.p95LatencyUs.toFixed(2),
      collisionBuckets: system.bucketStats?.collisionBuckets ?? "",
      maxBucketSize: system.bucketStats?.maxBucketSize ?? "",
    }))
  );
}

function runLargeBenchmark() {
  runScaledBenchmark({
    mode: "large",
    targetDocs: 12000,
    sampleSize: 6000,
    outFileName: "chl-benchmark-large.json",
    conceptFileName: "chl-concepts.tsv",
  });
}

function runHugeBenchmark() {
  runScaledBenchmark({
    mode: "huge",
    targetDocs: 50000,
    sampleSize: 20000,
    outFileName: "chl-benchmark-huge.json",
    conceptFileName: "chl-concepts-huge.tsv",
  });
}

function summarizeChl(name, engine, samples) {
  const metrics = evaluateChl(engine, samples);
  const bucketStats = engine.bucketStats?.() ?? null;
  const snapshot = engine.snapshot?.() ?? null;
  return {
    name,
    ...metrics,
    bucketStats,
    snapshot,
  };
}

function runBenchmark() {
  const corpus = makeIndex(buildCorpus());
  const concepts = prepareLearnedConceptLexicon(corpus, "chl-concepts-small.tsv");
  const samples = corpus.querySamples;

  const nativeChl = new CHL({
    bitCount: 128,
    bandBits: 32,
    hyperDim: 256,
    maxEntries: 4096,
    maxCandidates: 64,
    seed: 42,
  });
  const jsChl = new JSCHL({
    bitCount: 128,
    bandBits: 32,
    hyperDim: 256,
    maxEntries: 4096,
    maxCandidates: 64,
    seed: 42,
  });

  attachCorpus(nativeChl, corpus);
  attachCorpus(jsChl, corpus);

  const report = {
    dataset: {
      facts: baseFacts.length,
      negatedFacts: baseFacts.length,
      distractors: hardNoise.length,
      queries: samples.length,
      learnedConcepts: concepts.size,
      learnedPhrases: concepts.phraseSize,
      categories: {
        positive: samples.filter((sample) => sample.category === "positive").length,
        negation: samples.filter((sample) => sample.category === "negation").length,
      },
    },
    systems: [
      summarizeChl("chl-native", nativeChl, samples),
      summarizeChl("chl-js", jsChl, samples),
      evaluateRanker("exact-match", exactRanker, corpus, samples),
      evaluateRanker("jaccard", jaccardRanker, corpus, samples),
      evaluateRanker("bm25-lite", bm25Ranker, corpus, samples),
    ],
  };

  const outDir = path.resolve(__dirname, "..", "artifacts");
  fs.mkdirSync(outDir, { recursive: true });
  const outFile = path.join(outDir, "chl-benchmark.json");
  fs.writeFileSync(outFile, JSON.stringify(report, null, 2));

  console.log(JSON.stringify(report, null, 2));
  console.log("");
  console.table(
    report.systems.map((system) => ({
      system: system.name,
      recallAt1: system.recallAt1.toFixed(3),
      recallAt3: system.recallAt3.toFixed(3),
      mrr: system.mrr.toFixed(3),
      medianLatencyUs: system.medianLatencyUs.toFixed(2),
      p95LatencyUs: system.p95LatencyUs.toFixed(2),
      collisionBuckets: system.bucketStats?.collisionBuckets ?? "",
      maxBucketSize: system.bucketStats?.maxBucketSize ?? "",
    }))
  );
}

if (require.main === module) {
  const mode = process.env.CHL_BENCH_MODE ?? (process.argv.includes("--huge") ? "huge" : process.argv.includes("--large") ? "large" : "small");
  if (mode === "huge") {
    runHugeBenchmark();
  } else if (mode === "large") {
    runLargeBenchmark();
  } else {
    runBenchmark();
  }
}

module.exports = {
  bm25Ranker,
  buildCorpus,
  evaluateChl,
  evaluateRanker,
  exactRanker,
  jaccardRanker,
  makeIndex,
  runLargeBenchmark,
  runBenchmark,
};
