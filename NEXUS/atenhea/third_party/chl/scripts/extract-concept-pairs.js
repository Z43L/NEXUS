#!/usr/bin/env node
/**
 * extract-concept-pairs.js — Extracción agresiva de pares de concepto
 * 
 * A diferencia del learnConceptPairsFromExamples original (que solo compara
 * tokens en la misma posición), este script:
 * 1. Toma todas las combinaciones de (paráfrasis, original) 
 * 2. Encuentra TODOS los pares de tokens diferentes, sin importar posición
 * 3. Filtra por frecuencia mínima
 * 4. Detecta colocaciones (verbo+preposición) para el PhraseAliasIndex
 */

const fs = require("node:fs");
const path = require("node:path");
const { normalizeText, tokenize } = require("../src/utils");

// ─── Datos de entrenamiento ──────────────────────────────

const facts = [
  { id: 'cat-table', text: 'el gato duerme sobre la mesa',
    paraphrases: ['el gato duerme en la mesa', 'el felino descansa sobre la mesa', 'el minino duerme encima de la mesa'] },
  { id: 'dog-park', text: 'el perro corre por el parque',
    paraphrases: ['el perro corre en el parque', 'el can corre por el parque', 'el perro atraviesa el parque corriendo'] },
  { id: 'train-station', text: 'el tren entra en la estacion',
    paraphrases: ['el tren llega a la estacion', 'el tren se acerca a la estacion', 'el ferrocarril entra en la estacion'] },
  { id: 'rain-street', text: 'la lluvia cae sobre la calle',
    paraphrases: ['la lluvia moja la calle', 'la lluvia cae en la calle', 'la precipitacion cae sobre la calle'] },
  { id: 'memory-remembers', text: 'la memoria guarda recuerdos utiles',
    paraphrases: ['la memoria conserva recuerdos utiles', 'la memoria almacena recuerdos', 'el sistema guarda datos en memoria'] },
  { id: 'drone-field', text: 'el dron sobrevuela el campo',
    paraphrases: ['el dron vuela sobre el campo', 'el dron cruza el campo', 'el UAV sobrevuela el terreno'] },
  { id: 'key-door', text: 'la llave abre la puerta',
    paraphrases: ['la llave desbloquea la puerta', 'la llave abre una puerta', 'la llave permite abrir la entrada'] },
  { id: 'river-city', text: 'el rio atraviesa la ciudad',
    paraphrases: ['el rio cruza la ciudad', 'el rio pasa por la ciudad', 'el afluente atraviesa la urbe'] },
  { id: 'book-library', text: 'el libro esta en la biblioteca',
    paraphrases: ['el libro queda en la biblioteca', 'la biblioteca guarda el libro', 'el ejemplar permanece en la biblioteca'] },
  { id: 'bird-tree', text: 'el pajaro se posa en el arbol',
    paraphrases: ['el pajaro descansa en el arbol', 'el ave se posa en el arbol', 'el pajaro se apoya en la rama'] },
  { id: 'coffee-kitchen', text: 'el cafe humea en la cocina',
    paraphrases: ['el cafe esta caliente en la cocina', 'el cafe desprende vapor en la cocina'] },
  { id: 'phone-battery', text: 'el telefono carga la bateria',
    paraphrases: ['el telefono recarga la bateria', 'la bateria del telefono se carga'] },
  { id: 'lamp-room', text: 'la lampara ilumina la habitacion',
    paraphrases: ['la lampara da luz a la habitacion', 'la habitacion queda iluminada'] },
  { id: 'car-road', text: 'el coche circula por la carretera',
    paraphrases: ['el coche va por la carretera', 'el automovil circula por la carretera'] },
  { id: 'fish-river', text: 'el pez nada en el rio',
    paraphrases: ['el pez se mueve en el rio', 'el pez nada por el rio'] },
  { id: 'student-class', text: 'la estudiante toma apuntes en clase',
    paraphrases: ['la estudiante escribe apuntes en clase', 'la alumna toma notas en clase'] },
  { id: 'doctor-hospital', text: 'el doctor atiende al paciente',
    paraphrases: ['el medico atiende al paciente', 'el doctor cuida al paciente'] },
  { id: 'chef-kitchen', text: 'la chef prepara la cena',
    paraphrases: ['la cocinera prepara la cena', 'la chef cocina la cena'] },
  { id: 'window-open', text: 'la ventana permanece abierta',
    paraphrases: ['la ventana sigue abierta', 'la ventana esta abierta'] },
  { id: 'forest-shadow', text: 'la sombra cubre el bosque',
    paraphrases: ['la sombra cae sobre el bosque', 'el bosque queda en sombra'] },
  { id: 'music-speaker', text: 'la musica suena en el altavoz',
    paraphrases: ['la musica sale del altavoz', 'el altavoz reproduce musica'] },
  { id: 'code-editor', text: 'el codigo se escribe en el editor',
    paraphrases: ['el programador escribe codigo en el editor', 'el editor contiene codigo'] },
  { id: 'bridge-river', text: 'el puente cruza el rio',
    paraphrases: ['el puente atraviesa el rio', 'el puente esta sobre el rio'] },
  { id: 'market-buy', text: 'la persona compra pan en el mercado',
    paraphrases: ['la persona compra pan', 'el mercado vende pan'] },
  { id: 'garden-water', text: 'la regadera riega el jardin',
    paraphrases: ['la regadera moja el jardin', 'el jardin recibe agua'] },
  { id: 'sun-warm', text: 'el sol calienta la terraza',
    paraphrases: ['el sol calienta la superficie', 'la terraza recibe calor del sol'] },
  { id: 'mail-delivery', text: 'el correo llega a la oficina',
    paraphrases: ['el correo entra en la oficina', 'la oficina recibe correo'] },
  { id: 'clock-time', text: 'el reloj marca las tres',
    paraphrases: ['el reloj indica las tres', 'las tres aparecen en el reloj'] },
  { id: 'tablet-screen', text: 'la pantalla muestra el mapa',
    paraphrases: ['la pantalla enseña el mapa', 'el mapa aparece en la pantalla'] },
  { id: 'library-quiet', text: 'la biblioteca permanece en silencio',
    paraphrases: ['la biblioteca esta silenciosa', 'el silencio reina en la biblioteca'] },
];

// ─── Extracción de pares de concepto ─────────────────────

function extractAllConceptPairs(facts) {
  const pairCounts = new Map();   // "source→target" → count
  const collocationCounts = new Map(); // "(word1,word2)" → count

  for (const fact of facts) {
    const targetTokens = tokenize(normalizeText(fact.text));
    
    for (const paraphrase of fact.paraphrases) {
      const sourceTokens = tokenize(normalizeText(paraphrase));
      
      // Encontrar tokens que están en source pero no en target (y viceversa)
      const targetSet = new Set(targetTokens);
      const sourceSet = new Set(sourceTokens);
      
      const onlyInSource = sourceTokens.filter(t => !targetSet.has(t) && t.length >= 3);
      const onlyInTarget = targetTokens.filter(t => !sourceSet.has(t) && t.length >= 3);
      
      // Emparejar cada token único de la fuente con cada token único del target
      for (const src of onlyInSource) {
        for (const tgt of onlyInTarget) {
          if (src === tgt) continue;
          const key = `${src}\t${tgt}`;
          pairCounts.set(key, (pairCounts.get(key) ?? 0) + 1);
        }
      }
      
      // Detectar colocaciones (bigramas de palabras adyacentes)
      for (let i = 0; i < sourceTokens.length - 1; i++) {
        const bigram = `${sourceTokens[i]}\t${sourceTokens[i+1]}`;
        collocationCounts.set(bigram, (collocationCounts.get(bigram) ?? 0) + 1);
      }
      for (let i = 0; i < targetTokens.length - 1; i++) {
        const bigram = `${targetTokens[i]}\t${targetTokens[i+1]}`;
        collocationCounts.set(bigram, (collocationCounts.get(bigram) ?? 0) + 1);
      }
    }
  }

  // Filtrar pares con frecuencia >= 2
  const conceptPairs = [];
  const rawPairs = [];
  for (const [key, count] of pairCounts) {
    if (count >= 2) {
      const [src, tgt] = key.split('\t');
      conceptPairs.push({ from: src, to: tgt, count });
    }
    rawPairs.push({ from: key.split('\t')[0], to: key.split('\t')[1], count });
  }

  // Filtrar colocaciones frecuentes
  const collocations = [];
  for (const [key, count] of collocationCounts) {
    if (count >= 3) {
      const [w1, w2] = key.split('\t');
      collocations.push({ words: [w1, w2], count });
    }
  }

  return { conceptPairs, collocations, rawPairs, stats: {
    totalPairs: pairCounts.size,
    filteredPairs: conceptPairs.length,
    collocations: collocations.length,
  }};
}

// ─── Main ─────────────────────────────────────────────────

const result = extractAllConceptPairs(facts);

console.log('=== Pares de concepto extraídos ===');
console.log(`Total pares crudos: ${result.stats.totalPairs}`);
console.log(`Pares filtrados (freq>=2): ${result.stats.filteredPairs}`);
console.log(`Colocaciones frecuentes: ${result.stats.collocations}`);
console.log();

console.log('--- Pares de concepto ---');
for (const pair of result.conceptPairs.slice(0, 30)) {
  console.log(`  ${pair.from.padEnd(15)} → ${pair.to.padEnd(15)} (${pair.count})`);
}
if (result.conceptPairs.length > 30) {
  console.log(`  ... y ${result.conceptPairs.length - 30} más`);
}

console.log();
console.log('--- Colocaciones ---');
for (const col of result.collocations.slice(0, 15)) {
  console.log(`  [${col.words[0]} ${col.words[1]}]`.padEnd(25) + ` (${col.count})`);
}

// Guardar a archivo
const outDir = path.resolve(__dirname, '..', 'artifacts');
fs.mkdirSync(outDir, { recursive: true });

// Guardar pares como TSV
const tsvContent = result.conceptPairs.map(p => `${p.from}\t${p.to}`).join('\n');
fs.writeFileSync(path.join(outDir, 'chl-concepts-expanded.tsv'), tsvContent);

// Guardar colocaciones como JSON
fs.writeFileSync(
  path.join(outDir, 'chl-collocations.json'),
  JSON.stringify({ collocations: result.collocations }, null, 2)
);

console.log(`\n✅ Guardado en artifacts/chl-concepts-expanded.tsv y artifacts/chl-collocations.json`);

module.exports = { extractAllConceptPairs };
