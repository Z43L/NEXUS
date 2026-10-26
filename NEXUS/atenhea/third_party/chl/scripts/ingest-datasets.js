#!/usr/bin/env node
/**
 * ingest-datasets.js — Descarga e ingesta de datasets en CHL
 * 
 * Fuentes:
 *   - CVE database (NVD) — vulnerabilidades de ciberseguridad
 *   - ArXiv papers — abstracts de AI/ML
 *   - Stack Overflow — preguntas de programación
 *   - OWASP Top 10 — conceptos de seguridad web
 */

const fs = require("node:fs");
const path = require("node:path");
const https = require("node:https");
const { spawn } = require("node:child_process");

const ARTIFACTS_DIR = path.resolve(__dirname, "..", "artifacts");
const DATASETS_DIR = path.join(ARTIFACTS_DIR, "datasets");

// ─── Download helpers ─────────────────────────────────────

function downloadFile(url, destPath) {
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(destPath);
    https.get(url, { headers: { "User-Agent": "CHL-dataset-ingestor/1.0" } }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        file.close();
        fs.unlinkSync(destPath);
        return downloadFile(res.headers.location, destPath).then(resolve).catch(reject);
      }
      res.pipe(file);
      file.on("finish", () => { file.close(); resolve(); });
    }).on("error", (err) => { file.close(); reject(err); });
  });
}

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

// ─── Dataset builders ─────────────────────────────────────

/**
 * Ciberseguridad: CVE entries + OWASP concepts
 */
function buildCybersecurityDataset() {
  ensureDir(DATASETS_DIR);
  const entries = [];

  // OWASP Top 10 2021
  const owasp = [
    { id: "owasp-a01", text: "Broken Access Control: las restricciones de acceso no se aplican correctamente, permitiendo a usuarios no autorizados acceder a datos o funciones privilegiadas", category: "cybersec" },
    { id: "owasp-a02", text: "Cryptographic Failures: fallos en la proteccion de datos sensibles como contraseñas, tokens de sesión o información financiera por cifrado débil o ausente", category: "cybersec" },
    { id: "owasp-a03", text: "Injection: datos no confiables se interpretan como comandos en el sistema, incluyendo SQL injection, command injection, LDAP injection o cross-site scripting", category: "cybersec" },
    { id: "owasp-a04", text: "Insecure Design: riesgos relacionados a fallos en el diseño de la aplicación que no pueden remediarse con una implementación perfecta", category: "cybersec" },
    { id: "owasp-a05", text: "Security Misconfiguration: configuraciones por defecto inseguras, mensajes de error con información sensible, cabeceras HTTP mal configuradas", category: "cybersec" },
    { id: "owasp-a06", text: "Vulnerable and Outdated Components: uso de bibliotecas o frameworks con vulnerabilidades conocidas sin actualizar o parchear", category: "cybersec" },
    { id: "owasp-a07", text: "Identification and Authentication Failures: debilidades en la gestión de sesiones, contraseñas débiles, falta de autenticación multifactor", category: "cybersec" },
    { id: "owasp-a08", text: "Software and Data Integrity Failures: pipelines CI/CD inseguros, actualizaciones sin firma digital, deserialización de datos no confiables", category: "cybersec" },
    { id: "owasp-a09", text: "Security Logging and Monitoring Failures: falta de registro de eventos de seguridad, monitorización insuficiente que permite brechas sin detectar", category: "cybersec" },
    { id: "owasp-a10", text: "Server-Side Request Forgery (SSRF): el servidor realiza peticiones a URLs controladas por el atacante, exponiendo recursos internos", category: "cybersec" },
  ];

  // Vulnerabilidades CVE conocidas
  const cves = [
    { id: "cve-log4shell", text: "Log4Shell CVE-2021-44228: vulnerabilidad critica en Apache Log4j que permite ejecución remota de código mediante mensajes de log manipulados con JNDI lookups", category: "cybersec" },
    { id: "cve-spring4shell", text: "Spring4Shell CVE-2022-22965: vulnerabilidad de ejecución remota de código en Spring Framework mediante manipulación de parámetros en peticiones HTTP", category: "cybersec" },
    { id: "cve-heartbleed", text: "Heartbleed CVE-2014-0160: vulnerabilidad en OpenSSL que permite leer memoria del servidor exponiendo claves privadas y datos sensibles", category: "cybersec" },
    { id: "cve-shellshock", text: "Shellshock CVE-2014-6271: vulnerabilidad en Bash que permite ejecución remota de comandos mediante variables de entorno manipuladas", category: "cybersec" },
    { id: "cve-spectre", text: "Spectre CVE-2017-5753: ataque de ejecución especulativa que permite filtrar datos entre procesos mediante la predicción de saltos del procesador", category: "cybersec" },
    { id: "cve-meltdown", text: "Meltdown CVE-2017-5754: vulnerabilidad hardware que permite a un proceso leer memoria del kernel rompiendo el aislamiento entre usuario y sistema", category: "cybersec" },
    { id: "cve-eternalblue", text: "EternalBlue CVE-2017-0144: exploit de SMBv1 usado por WannaCry que permite ejecución remota de código en sistemas Windows sin parchear", category: "cybersec" },
    { id: "cve-proxylogon", text: "ProxyLogon CVE-2021-26855: vulnerabilidad en Microsoft Exchange Server que permite bypass de autenticación y ejecución remota de código", category: "cybersec" },
    { id: "cve-zerologon", text: "Zerologon CVE-2020-1472: vulnerabilidad en Netlogon que permite tomar control de un controlador de dominio Active Directory con privilegios máximos", category: "cybersec" },
    { id: "cve-follina", text: "Follina CVE-2022-30190: vulnerabilidad en Microsoft Support Diagnostic Tool que permite ejecución remota de código mediante documentos Office maliciosos", category: "cybersec" },
    { id: "cve-solarwinds", text: "SolarWinds CVE-2020-10148: ataque a la cadena de suministro que comprometió actualizaciones del software Orion permitiendo acceso a miles de organizaciones", category: "cybersec" },
    { id: "cve-printnightmare", text: "PrintNightmare CVE-2021-34527: vulnerabilidad en el servicio de impresión de Windows que permite escalada de privilegios y ejecución remota de código", category: "cybersec" },
  ];

  // Conceptos de ciberseguridad
  const concepts = [
    { id: "sec-xss", text: "Cross-Site Scripting (XSS): inyección de JavaScript malicioso en páginas web que se ejecuta en el navegador de la víctima, permitiendo robo de cookies, sesiones o datos", category: "cybersec" },
    { id: "sec-sqli", text: "SQL Injection: inserción de consultas SQL maliciosas en formularios web que permiten leer, modificar o eliminar datos de la base de datos", category: "cybersec" },
    { id: "sec-csrf", text: "Cross-Site Request Forgery: ataque que fuerza al usuario a realizar acciones no deseadas en una aplicación web donde está autenticado", category: "cybersec" },
    { id: "sec-buffer-overflow", text: "Buffer Overflow: escritura de datos más allá de los límites de un buffer permitiendo sobrescribir la pila de ejecución y ejecutar código arbitrario", category: "cybersec" },
    { id: "sec-zero-day", text: "Zero-Day: vulnerabilidad desconocida para el fabricante del software que es explotada antes de que exista un parche disponible", category: "cybersec" },
    { id: "sec-ransomware", text: "Ransomware: malware que cifra los archivos de la víctima y exige un rescate económico para restaurar el acceso a los datos", category: "cybersec" },
    { id: "sec-phishing", text: "Phishing: técnica de ingeniería social que suplanta identidades legítimas para engañar a usuarios y obtener credenciales o información confidencial", category: "cybersec" },
    { id: "sec-apt", text: "Advanced Persistent Threat: grupo de atacantes sofisticados con recursos significativos que mantiene acceso prolongado a sistemas objetivo", category: "cybersec" },
    { id: "sec-zero-trust", text: "Zero Trust Architecture: modelo de seguridad donde ninguna entidad es confiable por defecto, cada acceso debe verificarse independientemente", category: "cybersec" },
    { id: "sec-pentest", text: "Penetration Testing: simulación controlada de un ataque real contra sistemas para identificar vulnerabilidades antes de que sean explotadas", category: "cybersec" },
  ];

  entries.push(...owasp, ...cves, ...concepts);
  return entries;
}

/**
 * Programación: conceptos de lenguajes, patrones, algoritmos
 */
function buildProgrammingDataset() {
  const entries = [];

  // Algoritmos y estructuras de datos
  const algorithms = [
    { id: "algo-quicksort", text: "QuickSort: algoritmo de ordenamiento divide y vencerás que elige un pivote, particiona el array y ordena recursivamente las dos mitades con complejidad O(n log n) promedio y O(n²) peor caso", category: "programming" },
    { id: "algo-mergesort", text: "MergeSort: algoritmo de ordenamiento estable que divide el array en mitades recursivamente, las ordena y luego fusiona las listas ordenadas con complejidad garantizada O(n log n)", category: "programming" },
    { id: "algo-binary-search", text: "Binary Search: búsqueda en array ordenado que descarta la mitad de elementos en cada iteración comparando con el elemento central, complejidad O(log n)", category: "programming" },
    { id: "algo-hash-table", text: "Hash Table: estructura de datos que mapea claves a valores mediante una función hash, ofreciendo inserción, búsqueda y eliminación en O(1) promedio con manejo de colisiones por encadenamiento o direccionamiento abierto", category: "programming" },
    { id: "algo-bfs", text: "Breadth-First Search: algoritmo de recorrido de grafos que explora nivel por nivel usando una cola, útil para encontrar caminos más cortos en grafos no ponderados con complejidad O(V+E)", category: "programming" },
    { id: "algo-dfs", text: "Depth-First Search: algoritmo de recorrido de grafos que explora en profundidad usando recursión o pila, útil para detección de ciclos, ordenamiento topológico y backtracking con complejidad O(V+E)", category: "programming" },
    { id: "algo-dijkstra", text: "Dijkstra: algoritmo de camino más corto desde un nodo fuente en grafos con pesos no negativos usando una cola de prioridad, complejidad O((V+E)log V) con heap binario", category: "programming" },
    { id: "algo-dp", text: "Dynamic Programming: técnica de optimización que resuelve problemas descomponiéndolos en subproblemas solapados y almacenando soluciones intermedias para evitar recalcular resultados ya conocidos", category: "programming" },
  ];

  // Patrones de diseño
  const patterns = [
    { id: "pattern-singleton", text: "Singleton: patrón creacional que garantiza una única instancia de una clase y proporciona un punto de acceso global a ella, útil para gestores de configuración o pools de conexiones", category: "programming" },
    { id: "pattern-factory", text: "Factory Method: patrón creacional que define una interfaz para crear objetos pero delega a las subclases la decisión de qué clase concreta instanciar, desacoplando el código cliente de las clases concretas", category: "programming" },
    { id: "pattern-observer", text: "Observer: patrón de comportamiento donde un objeto sujeto notifica automáticamente a sus observadores sobre cambios de estado, implementado en event listeners y reactive programming", category: "programming" },
    { id: "pattern-strategy", text: "Strategy: patrón de comportamiento que define una familia de algoritmos intercambiables encapsulando cada uno y permitiendo que varíen independientemente del cliente que los usa", category: "programming" },
    { id: "pattern-decorator", text: "Decorator: patrón estructural que añade responsabilidades adicionales a objetos de forma dinámica envolviéndolos, alternativa flexible a la herencia para extender funcionalidad", category: "programming" },
    { id: "pattern-dependency-injection", text: "Dependency Injection: las dependencias de un componente se inyectan desde fuera en lugar de crearse internamente, facilitando testing con mocks, desacoplamiento y configuración flexible de la aplicación", category: "programming" },
    { id: "pattern-repository", text: "Repository Pattern: abstrae la capa de persistencia detrás de una interfaz que simula una colección en memoria, permitiendo cambiar la tecnología de almacenamiento sin modificar la lógica de negocio", category: "programming" },
  ];

  // Lenguajes y conceptos
  const languages = [
    { id: "lang-python", text: "Python: lenguaje interpretado de alto nivel con tipado dinámico, sintaxis limpia y extenso ecosistema de bibliotecas para desarrollo web con Django, ciencia de datos con NumPy y Pandas, y machine learning con PyTorch", category: "programming" },
    { id: "lang-rust", text: "Rust: lenguaje compilado con seguridad de memoria sin garbage collector mediante ownership y borrowing, ideal para sistemas de alto rendimiento, drivers y WebAssembly con concurrencia segura", category: "programming" },
    { id: "lang-go", text: "Go: lenguaje compilado por Google con concurrencia basada en goroutines y channels, sintaxis minimalista, compilación rápida y garbage collector eficiente para microservicios y herramientas CLI", category: "programming" },
    { id: "lang-typescript", text: "TypeScript: superset de JavaScript con tipado estático opcional desarrollado por Microsoft, que añade interfaces, genéricos y enums para mejorar la mantenibilidad de aplicaciones web escalables", category: "programming" },
    { id: "concept-rest", text: "REST API: arquitectura de servicios web basada en recursos identificados por URLs, operaciones HTTP estándar GET POST PUT DELETE, sin estado en el servidor y respuestas típicamente en JSON", category: "programming" },
    { id: "concept-graphql", text: "GraphQL: lenguaje de consulta para APIs que permite al cliente especificar exactamente los datos que necesita, resolviendo el problema de over-fetching y under-fetching de REST", category: "programming" },
    { id: "concept-git", text: "Git: sistema de control de versiones distribuido que rastrea cambios en archivos mediante snapshots, permitiendo branching y merging eficiente con repositorios remotos como GitHub o GitLab", category: "programming" },
    { id: "concept-docker", text: "Docker: plataforma de contenedores que empaqueta aplicaciones con sus dependencias en unidades aisladas, garantizando consistencia entre desarrollo, testing y producción con imágenes inmutables", category: "programming" },
    { id: "concept-ci-cd", text: "CI/CD Pipeline: práctica de desarrollo donde los cambios de código se integran, prueban y despliegan automáticamente, detectando errores temprano mediante tests automatizados y despliegue continuo", category: "programming" },
  ];

  entries.push(...algorithms, ...patterns, ...languages);
  return entries;
}

/**
 * Inteligencia Artificial: ML, DL, NLP, conceptos fundamentales
 */
function buildAIDataset() {
  const entries = [];

  const fundamentals = [
    { id: "ai-machine-learning", text: "Machine Learning: subcampo de IA donde los sistemas aprenden patrones desde datos sin programación explícita, mediante entrenamiento supervisado, no supervisado o por refuerzo para hacer predicciones o tomar decisiones", category: "ai" },
    { id: "ai-deep-learning", text: "Deep Learning: subcampo de ML que usa redes neuronales profundas con múltiples capas ocultas para aprender representaciones jerárquicas de datos, impulsado por GPUs y grandes volúmenes de datos etiquetados", category: "ai" },
    { id: "ai-supervised", text: "Supervised Learning: paradigma de ML donde el modelo aprende de ejemplos etiquetados con entrada y salida deseada, minimizando una función de pérdida que mide el error entre predicción y valor real", category: "ai" },
    { id: "ai-unsupervised", text: "Unsupervised Learning: paradigma de ML donde el modelo descubre patrones en datos sin etiquetar mediante clustering como K-means, reducción de dimensionalidad como PCA o modelos generativos como autoencoders", category: "ai" },
    { id: "ai-reinforcement", text: "Reinforcement Learning: paradigma donde un agente aprende a tomar decisiones interactuando con un entorno, recibiendo recompensas o penalizaciones y optimizando una política para maximizar la recompensa acumulada", category: "ai" },
    { id: "ai-overfitting", text: "Overfitting: el modelo aprende patrones espurios del conjunto de entrenamiento y no generaliza bien a datos nuevos, memorizando ruido en lugar de capturar la señal subyacente de los datos", category: "ai" },
    { id: "ai-regularization", text: "Regularization: técnicas como L1 Lasso, L2 Ridge o Dropout que penalizan la complejidad del modelo durante el entrenamiento para prevenir overfitting y mejorar la capacidad de generalización", category: "ai" },
    { id: "ai-gradient-descent", text: "Gradient Descent: algoritmo de optimización que ajusta iterativamente los parámetros del modelo en dirección opuesta al gradiente de la función de pérdida, convergiendo hacia un mínimo local con learning rate como hiperparámetro", category: "ai" },
  ];

  const neural = [
    { id: "ai-cnn", text: "Convolutional Neural Network: arquitectura especializada en datos con estructura de grilla como imágenes, usando filtros convolucionales que detectan patrones locales mediante pesos compartidos y pooling para reducción dimensional", category: "ai" },
    { id: "ai-rnn", text: "Recurrent Neural Network: arquitectura para datos secuenciales con conexiones recurrentes que mantienen estado oculto entre pasos temporales. LSTM y GRU resuelven el problema del gradiente evanescente", category: "ai" },
    { id: "ai-transformer", text: "Transformer: arquitectura basada exclusivamente en mecanismos de atención que procesa secuencias completas en paralelo, eliminando la recurrencia. Es la base de modelos como GPT BERT Claude Gemini Llama", category: "ai" },
    { id: "ai-attention", text: "Attention Mechanism: permite al modelo enfocarse en partes relevantes de la entrada asignando pesos de importancia a diferentes posiciones. Self-attention relaciona cada token con todos los demás en la secuencia", category: "ai" },
    { id: "ai-embedding", text: "Word Embedding: representación vectorial densa de palabras en un espacio semántico continuo donde palabras similares están cercanas. Word2Vec GloVe y FastText capturan relaciones semánticas mediante vectores de 100-1000 dimensiones", category: "ai" },
    { id: "ai-transfer", text: "Transfer Learning: técnica donde un modelo pre-entrenado en una tarea masiva se adapta a una tarea específica con pocos datos, aprovechando representaciones aprendidas. Fundamental en NLP con fine-tuning de LLMs", category: "ai" },
    { id: "ai-rag", text: "Retrieval Augmented Generation: arquitectura que combina un LLM generativo con un sistema de recuperación de documentos, permitiendo al modelo acceder a conocimiento externo actualizado sin necesidad de fine-tuning", category: "ai" },
    { id: "ai-agent", text: "AI Agent: sistema autónomo que percibe su entorno mediante sensores o APIs, razona sobre el contexto usando un modelo de lenguaje, planifica acciones y utiliza herramientas para alcanzar objetivos definidos por el usuario", category: "ai" },
  ];

  const nlp = [
    { id: "ai-tokenization", text: "Tokenization: proceso de dividir texto en unidades mínimas tokens que pueden ser palabras, subpalabras mediante BPE o SentencePiece, o caracteres. El vocabulario del tokenizer define la granularidad del modelo", category: "ai" },
    { id: "ai-llm", text: "Large Language Model: modelo con miles de millones de parámetros entrenado en corpus masivos de texto mediante predicción del siguiente token, que emerge capacidades de razonamiento instrucción y generación de código", category: "ai" },
    { id: "ai-fine-tuning", text: "Fine-tuning: proceso de entrenamiento adicional de un modelo pre-entrenado en datos específicos de dominio para especializarlo. Técnicas como LoRA y QLoRA permiten fine-tuning eficiente con pocos recursos", category: "ai" },
    { id: "ai-prompt", text: "Prompt Engineering: práctica de diseñar instrucciones textuales óptimas para guiar el comportamiento de un LLM sin modificar sus pesos, usando técnicas como few-shot chain-of-thought o role prompting", category: "ai" },
    { id: "ai-hallucination", text: "Hallucination: fenómeno donde un LLM genera información plausible pero factualmente incorrecta, inventando datos fuentes o referencias. La verificación externa y RAG ayudan a mitigar este problema", category: "ai" },
  ];

  entries.push(...fundamentals, ...neural, ...nlp);
  return entries;
}

// ─── Main ─────────────────────────────────────────────────

async function main() {
  ensureDir(ARTIFACTS_DIR);
  ensureDir(DATASETS_DIR);

  console.log("📦 Generando datasets...");

  const cybersec = buildCybersecurityDataset();
  const programming = buildProgrammingDataset();
  const ai = buildAIDataset();
  
  const allEntries = [...cybersec, ...programming, ...ai];
  
  console.log(`   Ciberseguridad: ${cybersec.length} entradas`);
  console.log(`   Programación:   ${programming.length} entradas`);
  console.log(`   IA:             ${ai.length} entradas`);
  console.log(`   Total:          ${allEntries.length} entradas`);

  // Guardar como JSONL para CHL
  const jsonlPath = path.join(DATASETS_DIR, "tech-knowledge.jsonl");
  const lines = allEntries.map(e => JSON.stringify({
    id: e.id,
    text: e.text,
    metadata: { category: e.category, quality: 8 }
  }));
  fs.writeFileSync(jsonlPath, lines.join("\n"));
  console.log(`\n💾 Guardado en ${jsonlPath}`);

  // Guardar también como TSV para el lexicon (extraer pares concepto->categoría)
  const tsvPath = path.join(DATASETS_DIR, "tech-concepts.tsv");
  const tsvLines = [];
  for (const e of allEntries) {
    // Extraer primeras palabras significativas como conceptos
    const words = e.text.split(/[:\-,.(]/)[0].trim().toLowerCase().split(/\s+/);
    if (words.length >= 2) {
      tsvLines.push(`${words.slice(0,2).join(" ")}\t${e.category}`);
    }
  }
  fs.writeFileSync(tsvPath, [...new Set(tsvLines)].join("\n"));
  console.log(`💾 Conceptos guardados en ${tsvPath}`);

  // Ahora ingerir en CHL vía MCP
  console.log("\n📥 Ingeriendo en CHL via MCP...");
  
  // Clear module cache to ensure fresh frontier setup
for (const key of Object.keys(require.cache)) {
  if (key.includes('/src/mcp') || key.includes('/src/memory') || key.includes('/src/chl')) {
    delete require.cache[key];
  }
}
const { createMcpContext, callTool } = require("../src/mcp");
  const ctx = createMcpContext({ 
    frontier: true,
    profile: "large",
    memory: { maxEntries: 50000 }
  });

  let ingested = 0;
  let errors = 0;
  
  for (const entry of allEntries) {
    try {
      await callTool(ctx, "chl_remember", {
        input: entry.text,
        payload: { id: entry.id, category: entry.category },
        metadata: { quality: 8, category: entry.category }
      });
      ingested++;
      if (ingested % 25 === 0) {
        process.stdout.write(`\r   ${ingested}/${allEntries.length} entradas...`);
      }
    } catch (err) {
      errors++;
    }
  }
  
  console.log(`\r   ✅ ${ingested}/${allEntries.length} entradas ingeridas (${errors} errores)`);

  // Verificar recall
  console.log("\n🔍 Verificando recall...");
  const tests = [
    { query: "que es un transformer en IA?", expected: "ai-transformer" },
    { query: "vulnerabilidad Log4j", expected: "cve-log4shell" },
    { query: "algoritmo quicksort complejidad", expected: "algo-quicksort" },
    { query: "patron de diseño singleton", expected: "pattern-singleton" },
    { query: "que es phishing", expected: "sec-phishing" },
  ];

  let ok = 0;
  for (const test of tests) {
    const r = await callTool(ctx, "chl_recall", { query: test.query, topK: 3 });
    const data = JSON.parse(r.content[0].text);
    const top = data.candidates?.[0]?.payload?.id;
    const symbol = top === test.expected ? "✅" : "❌";
    console.log(`   ${symbol} ${test.query.padEnd(35)} → ${top || '?'}`);
    if (top === test.expected) ok++;
  }
  console.log(`\n   Recall: ${ok}/${tests.length} queries correctas`);

  // Guardar estado
  console.log("\n💾 Guardando estado del trainer...");
  const r = await callTool(ctx, "chl_frontier_status", {});
  console.log("   Estado:", JSON.parse(r.content[0].text).trainer);
  
  console.log("\n✅ Datasets ingeridos y verificados en CHL Frontier");
}

main().catch(err => {
  console.error("❌", err.message);
  process.exit(1);
});
