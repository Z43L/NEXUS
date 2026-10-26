#!/usr/bin/env node
/**
 * bootstrap-lexicon.js — Genera un conceptMap rico para el LexiconTrainer
 * combinando sinónimos conocidos + pares descubiertos + colocaciones.
 */
const fs = require("node:fs");
const path = require("node:path");

// Sinónimos de verbos frecuentes en español
const VERB_SYNONYMS = [
  ["entrar", "ingresar", "acceder", "penetrar"],
  ["salir", "abandonar", "partir", "marcharse"],
  ["llegar", "arribar", "alcanzar", "presentarse"],
  ["correr", "trotar", "desplazarse", "moverse rápido"],
  ["caminar", "andar", "pasear", "recorrer"],
  ["dormir", "descansar", "reposar", "yacer"],
  ["comer", "ingerir", "alimentarse", "tragar"],
  ["beber", "tomar", "ingerir líquido"],
  ["mirar", "observar", "contemplar", "visualizar"],
  ["escuchar", "oir", "atender", "prestar atención"],
  ["hablar", "decir", "comunicar", "expresar"],
  ["escribir", "anotar", "redactar", "garabatear"],
  ["leer", "repasar", "estudiar", "examinar"],
  ["comprar", "adquirir", "obtener", "conseguir"],
  ["vender", "comerciar", "ofrecer", "traspasar"],
  ["guardar", "conservar", "almacenar", "preservar", "mantener", "retener"],
  ["abrir", "desbloquear", "destapar", "desplegar"],
  ["cerrar", "bloquear", "tapar", "sellar"],
  ["construir", "edificar", "levantar", "fabricar"],
  ["destruir", "romper", "dañar", "estropear"],
  ["enseñar", "mostrar", "explicar", "instruir"],
  ["aprender", "estudiar", "asimilar", "comprender"],
  ["volar", "sobrevolar", "planear", "surcar"],
  ["nadar", "flotar", "sumergirse"],
  ["caer", "descender", "precipitarse", "desplomarse"],
  ["subir", "ascender", "elevar", "trepar"],
  ["cruzar", "atravesar", "traspasar", "pasar"],
  ["iluminar", "alumbrar", "aclarar", "dar luz"],
  ["sonar", "resonar", "retumbar", "reproducirse"],
  ["cargar", "recargar", "llenar", "abastecer"],
  ["calentar", "templar", "caldear", "elevar temperatura"],
  ["enfriar", "refrescar", "helar", "congelar"],
  ["mojar", "humedecer", "empapar", "regar"],
  ["secar", "deshidratar", "evaporar"],
  ["cubrir", "tapar", "envolver", "proteger"],
  ["descubrir", "destapar", "revelar", "encontrar"],
  ["limpiar", "asear", "lavar", "purificar"],
  ["ensuciar", "manchar", "contaminar"],
  ["empezar", "comenzar", "iniciar", "arrancar"],
  ["terminar", "acabar", "finalizar", "concluir"],
];

// Sinónimos de sustantivos frecuentes
const NOUN_SYNONYMS = [
  ["coche", "automovil", "auto", "vehiculo"],
  ["perro", "can", "canino"],
  ["gato", "felino", "minino"],
  ["casa", "hogar", "vivienda", "domicilio", "residencia"],
  ["ciudad", "urbe", "poblacion", "localidad"],
  ["calle", "via", "avenida", "camino"],
  ["rio", "afluente", "caudal", "corriente"],
  ["montaña", "monte", "cerro", "colina"],
  ["arbol", "planta", "vegetal"],
  ["pajaro", "ave", "volatil"],
  ["medico", "doctor", "facultativo", "galeno"],
  ["profesor", "maestro", "docente", "educador"],
  ["estudiante", "alumno", "aprendiz", "educando"],
  ["comida", "alimento", "sustento", "vianda"],
  ["tren", "ferrocarril", "convoy", "locomotora"],
  ["avion", "aeronave", "aparato", "nave"],
  ["barco", "embarcacion", "navio", "buque"],
  ["libro", "ejemplar", "volumen", "texto"],
  ["puerta", "entrada", "acceso", "porton"],
  ["ventana", "apertura", "vano"],
  ["mesa", "tablero", "superficie"],
  ["silla", "asiento", "butaca"],
  ["cama", "lecho", "yacija"],
  ["telefono", "aparato", "dispositivo", "terminal"],
  ["pantalla", "monitor", "display", "visualizador"],
  ["ordenador", "computadora", "pc", "equipo"],
  ["dron", "UAV", "aeronave no tripulada", "multicoptero"],
  ["llave", "cerradura", "apertura"],
  ["memoria", "recuerdo", "reminiscencia"],
  ["musica", "melodia", "cancion", "sonido"],
  ["biblioteca", "libreria", "archivo"],
  ["oficina", "despacho", "lugar de trabajo"],
  ["parque", "jardin", "zona verde", "area recreativa"],
  ["estacion", "terminal", "parada", "apeadero"],
  ["campo", "terreno", "zona rural", "agro"],
  ["cocina", "estancia", "habitacion"],
  ["habitacion", "cuarto", "dormitorio", "estancia"],
  ["bosque", "arboleda", "selva", "floresta"],
  ["sombra", "penumbra", "oscuridad parcial"],
  ["sol", "astro", "estrella"],
  ["lluvia", "precipitacion", "agua", "pluvial"],
  ["nieve", "nevada", "precipitacion blanca"],
  ["viento", "corriente", "brisa", "aire"],
  ["fuego", "llama", "incendio", "combustion"],
];

// Pares de verbos con preposición (P1)
const VERB_PREP_PAIRS = [
  ["entrar", "en"],
  ["llegar", "a"],
  ["salir", "de"],
  ["ir", "a"],
  ["venir", "de"],
  ["correr", "por"],
  ["pasar", "por"],
  ["cruzar", "por"],
  ["volar", "sobre"],
  ["sobrevolar", ""],  // no lleva preposición
  ["caer", "sobre"],
  ["dormir", "sobre"],
  ["posar", "sobre"],
  ["poner", "en"],
  ["meter", "en"],
  ["sacar", "de"],
  ["subir", "a"],
  ["bajar", "de"],
  ["nadar", "en"],
  ["flotar", "en"],
  ["hablar", "de"],
  ["pensar", "en"],
  ["soñar", "con"],
  ["contar", "con"],
  ["depender", "de"],
  ["consistir", "en"],
  ["confiar", "en"],
  ["creer", "en"],
  ["interesarse", "por"],
  ["preocuparse", "por"],
  ["acordarse", "de"],
  ["olvidarse", "de"],
  ["quejarse", "de"],
  ["alegrarse", "de"],
  ["enamorarse", "de"],
  ["mirar", "a"],
  ["llamar", "a"],
  ["esperar", "a"],
  ["ayudar", "a"],
  ["ensenar", "a"],
  ["aprender", "a"],
  ["empezar", "a"],
  ["terminar", "de"],
  ["acabar", "de"],
  ["tratar", "de"],
  ["dejar", "de"],
  ["seguir", ""], // sin preposición fija
  ["estar", "en"],
  ["quedar", "en"],
  ["permanecer", "en"],
];

// ─── Generar conceptMap completo ──────────────────────────

function buildFullConceptMap() {
  const map = new Map();
  
  // Añadir sinónimos de verbos: cada variante → primera forma (canónica)
  for (const group of VERB_SYNONYMS) {
    const canonical = group[0];
    for (const variant of group) {
      if (variant !== canonical) {
        map.set(variant, canonical);
      }
    }
  }
  
  // Añadir sinónimos de sustantivos
  for (const group of NOUN_SYNONYMS) {
    const canonical = group[0];
    for (const variant of group) {
      if (variant !== canonical) {
        map.set(variant, canonical);
      }
    }
  }
  
  return map;
}

function buildCollocationMap() {
  const map = new Map(); // "verbo" → preposición esperada
  for (const [verb, prep] of VERB_PREP_PAIRS) {
    map.set(verb, prep);
  }
  return map;
}

// ─── Main ─────────────────────────────────────────────────

const conceptMap = buildFullConceptMap();
const collocationMap = buildCollocationMap();

const outDir = path.resolve(__dirname, "..", "artifacts");
fs.mkdirSync(outDir, { recursive: true });

// Guardar conceptMap como TSV
const tsvLines = [];
for (const [variant, canonical] of conceptMap) {
  tsvLines.push(`${variant}\t${canonical}`);
}
fs.writeFileSync(path.join(outDir, "chl-concepts-bootstrap.tsv"), tsvLines.join("\n"));

// Guardar collocationMap como JSON
fs.writeFileSync(
  path.join(outDir, "chl-collocations.json"),
  JSON.stringify({ collocations: [...collocationMap.entries()].map(([v,p]) => [v,p]) }, null, 2)
);

console.log(`✅ Bootstrap lexicon generado:`);
console.log(`   ${conceptMap.size} pares de concepto`);
console.log(`   ${collocationMap.size} pares verbo-preposición`);
console.log(`   Guardado en artifacts/chl-concepts-bootstrap.tsv`);
console.log(`   Guardado en artifacts/chl-collocations.json`);

// Mostrar algunos ejemplos
console.log("\nEjemplos de pares de concepto:");
let shown = 0;
for (const [variant, canonical] of conceptMap) {
  if (shown >= 10) break;
  console.log(`  ${variant.padEnd(16)} → ${canonical}`);
  shown++;
}

console.log("\nEjemplos de colocaciones:");
let shown2 = 0;
for (const [verb, prep] of collocationMap) {
  if (shown2 >= 10) break;
  console.log(`  ${verb.padEnd(14)} + ${prep || '(sin prep)'}`);
  shown2++;
}

module.exports = { buildFullConceptMap, buildCollocationMap };
