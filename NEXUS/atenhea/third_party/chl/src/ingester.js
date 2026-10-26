/**
 * CHL Universal Ingester — Traga cualquier cosa y la mete en memoria.
 *
 * Formatos soportados:
 * - PDF (extrae texto con pdftotext o pdf-parse)
 * - Markdown (.md) — chunking por headers
 * - Código (.js, .ts, .py, .go, .rs, .java, .c, .cpp, .rb, etc.) — chunking por funciones/clases
 * - Texto plano (.txt, .log, .csv, .json, .yaml, .toml, .xml, .html)
 * - Office (.docx — extrae texto)
 *
 * Estrategia de chunking:
 * - Tamaño objetivo: ~1200 caracteres por chunk
 * - Overlap: ~200 caracteres entre chunks
 * - Respeta boundaries naturales (párrafos, funciones, secciones)
 * - Metadata por chunk: source file, position, type
 */

const fs = require("node:fs");
const path = require("node:path");
const { execSync } = require("node:child_process");

// ─── Constantes ───────────────────────────────────────────

const DEFAULT_CHUNK_CHARS = 1200;
const DEFAULT_OVERLAP_CHARS = 200;
const MIN_CHUNK_CHARS = 80;

const CODE_EXTENSIONS = new Set([
  ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs",
  ".py", ".pyi", ".pyx",
  ".go",
  ".rs",
  ".java", ".kt", ".kts",
  ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp",
  ".rb",
  ".swift",
  ".scala",
  ".php",
  ".pl", ".pm",
  ".lua",
  ".r", ".R",
  ".sql",
  ".sh", ".bash", ".zsh",
  ".tf", ".tfvars",
  ".yml", ".yaml",
  ".toml",
]);

const MARKDOWN_EXTENSIONS = new Set([
  ".md", ".mdx", ".markdown",
]);

const TEXT_EXTENSIONS = new Set([
  ".txt", ".log", ".csv", ".tsv", ".json", ".jsonl",
  ".xml", ".html", ".htm", ".svg",
  ".cfg", ".conf", ".ini", ".env",
  ".tex", ".bib",
  ".css", ".scss", ".less",
  ".graphql", ".gql",
  ".proto",
]);

const SUPPORTED_EXTENSIONS = new Set([
  ".pdf",
  ".docx",
  ...CODE_EXTENSIONS,
  ...MARKDOWN_EXTENSIONS,
  ...TEXT_EXTENSIONS,
]);

// ─── Detección de tipo ────────────────────────────────────

function detectFileType(filePath) {
  const ext = path.extname(filePath).toLowerCase();

  if (ext === ".pdf") return "pdf";
  if (ext === ".docx") return "docx";
  if (CODE_EXTENSIONS.has(ext)) return "code";
  if (MARKDOWN_EXTENSIONS.has(ext)) return "markdown";
  if (TEXT_EXTENSIONS.has(ext)) return "text";

  // Fallback: intentar leer como texto
  return "text";
}

function isSupportedFile(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (SUPPORTED_EXTENSIONS.has(ext)) return true;

  // Binarios comunes que ignoramos
  const skip = new Set([
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svgz",
    ".mp3", ".mp4", ".wav", ".ogg", ".mov", ".avi",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".wasm",
    ".ttf", ".otf", ".woff", ".woff2",
    ".o", ".obj", ".class", ".pyc", ".pyo",
    ".db", ".sqlite", ".sqlite3",
    ".node",
    ".pdf", // ya cubierto arriba
    ".docx", // ya cubierto arriba
  ]);
  if (skip.has(ext)) return false;

  // Si no lo conocemos, intentamos como texto
  return true;
}

// ─── Extractores por formato ──────────────────────────────

/**
 * Extrae texto de un PDF usando pdftotext (poppler) si está disponible.
 */
function extractPDFText(filePath) {
  try {
    const result = execSync(`pdftotext -layout "${filePath}" -`, {
      encoding: "utf8",
      maxBuffer: 50 * 1024 * 1024,
      timeout: 30000,
    });
    return result;
  } catch {
    // Fallback: intentar con pdf-parse de npm si está instalado
    try {
      const pdfParse = require("pdf-parse");
      const dataBuffer = fs.readFileSync(filePath);
      return pdfParse(dataBuffer).then(d => d.text).catch(() => null);
    } catch {
      return null;
    }
  }
}

/**
 * Extrae texto de un DOCX.
 */
function extractDocxText(filePath) {
  try {
    // Usar shell: unzip -p file.docx word/document.xml | sed 's/<[^>]*>//g'
    const result = execSync(
      `unzip -p "${filePath}" word/document.xml 2>/dev/null | sed 's/<[^>]*>//g' | sed 's/&amp;/&/g' | sed 's/&lt;/</g' | sed 's/&gt;/>/g' | sed 's/&quot;/"/g' | sed 's/&apos;/'"'"'/g'`,
      { encoding: "utf8", maxBuffer: 50 * 1024 * 1024, timeout: 15000 }
    );
    return result.trim() || null;
  } catch {
    return null;
  }
}

/**
 * Lee un archivo como texto plano.
 */
function readTextFile(filePath) {
  try {
    return fs.readFileSync(filePath, "utf8");
  } catch {
    return null;
  }
}

// ─── Chunking ─────────────────────────────────────────────

/**
 * Chunk genérico: divide por párrafos respetando tamaño.
 */
function chunkByParagraphs(text, maxChars = DEFAULT_CHUNK_CHARS, overlapChars = DEFAULT_OVERLAP_CHARS) {
  const paragraphs = text.split(/\n\s*\n/).filter(p => p.trim());
  const chunks = [];
  let current = "";
  let currentChars = 0;

  for (const para of paragraphs) {
    const paraChars = para.length;

    if (currentChars + paraChars > maxChars && currentChars >= MIN_CHUNK_CHARS) {
      chunks.push(current.trim());
      // Overlap: mantener las últimas líneas del chunk anterior
      const lines = current.split("\n");
      let overlap = "";
      let overlapChars = 0;
      for (let i = lines.length - 1; i >= 0 && overlapChars < overlapChars; i--) {
        overlap = lines[i] + "\n" + overlap;
        overlapChars += lines[i].length;
      }
      current = overlap + para;
      currentChars = overlapChars + paraChars;
    } else {
      current += (current ? "\n\n" : "") + para;
      currentChars = current.length;
    }
  }

  if (current.trim()) {
    chunks.push(current.trim());
  }

  return chunks.filter(c => c.length >= MIN_CHUNK_CHARS);
}

/**
 * Chunk de Markdown: divide por headers (##, ###).
 */
function chunkMarkdown(text, maxChars = DEFAULT_CHUNK_CHARS, overlapChars = DEFAULT_OVERLAP_CHARS) {
  // Dividir por headers nivel 2+
  const sections = text.split(/(?=^#{1,4}\s)/m).filter(s => s.trim());
  if (sections.length <= 1) return chunkByParagraphs(text, maxChars, overlapChars);

  const chunks = [];
  let current = "";
  let currentChars = 0;

  for (const section of sections) {
    const secChars = section.length;
    if (currentChars + secChars > maxChars && currentChars >= MIN_CHUNK_CHARS) {
      chunks.push(current.trim());
      current = section;
      currentChars = secChars;
    } else {
      current += (current ? "\n" : "") + section;
      currentChars += secChars;
    }
  }

  if (current.trim()) chunks.push(current.trim());
  return chunks.filter(c => c.length >= MIN_CHUNK_CHARS);
}

/**
 * Chunk de código: divide por bloques (funciones, clases, etc.).
 */
function chunkCode(text, maxChars = DEFAULT_CHUNK_CHARS, overlapChars = DEFAULT_OVERLAP_CHARS) {
  const lines = text.split("\n");

  // Detectar boundaries: líneas que empiezan function, class, def, export, pub, fn, etc.
  const boundaryPatterns = [
    /^(export\s+)?(async\s+)?function\s/,
    /^(export\s+)?(abstract\s+)?class\s/,
    /^(export\s+)?interface\s/,
    /^(export\s+)?type\s/,
    /^def\s/,
    /^class\s/,
    /^func\s/,
    /^pub\s+fn\s/,
    /^pub\s+struct\s/,
    /^public\s+(static\s+)?(class|void|int|String|boolean)\s/,
    /^#+/,
    /^\/\*\*/,  // JSDoc/docstring blocks
  ];

  const boundaries = [0];
  for (let i = 1; i < lines.length; i++) {
    const trimmed = lines[i].trim();
    if (boundaryPatterns.some(p => p.test(trimmed))) {
      boundaries.push(i);
    }
  }

  if (boundaries.length <= 2) return chunkByParagraphs(text, maxChars, overlapChars);

  const chunks = [];
  let current = "";
  let currentChars = 0;

  for (let b = 0; b < boundaries.length; b++) {
    const start = boundaries[b];
    const end = b + 1 < boundaries.length ? boundaries[b + 1] : lines.length;
    const block = lines.slice(start, end).join("\n");
    const blockChars = block.length;

    if (currentChars + blockChars > maxChars && currentChars >= MIN_CHUNK_CHARS) {
      chunks.push(current.trim());
      current = block;
      currentChars = blockChars;
    } else {
      current += (current ? "\n" : "") + block;
      currentChars += blockChars;
    }
  }

  if (current.trim()) chunks.push(current.trim());
  return chunks.filter(c => c.length >= MIN_CHUNK_CHARS);
}

/**
 * Chunk inteligente: elige la estrategia según el tipo.
 */
function chunkContent(text, fileType) {
  switch (fileType) {
    case "markdown":
      return chunkMarkdown(text);
    case "code":
      return chunkCode(text);
    case "pdf":
    case "docx":
    case "text":
    default:
      return chunkByParagraphs(text);
  }
}

// ─── API principal ────────────────────────────────────────

/**
 * Procesa un archivo y devuelve los chunks listos para ingestar.
 *
 * @param {string} filePath — ruta absoluta al archivo
 * @param {Object} opts
 * @param {number} opts.maxChars — tamaño máximo de chunk
 * @param {number} opts.overlapChars — solapamiento entre chunks
 * @returns {Array<{text: string, metadata: Object}>}
 */
function processFile(filePath, opts = {}) {
  const absPath = path.resolve(filePath);
  if (!fs.existsSync(absPath)) return [];

  const fileType = detectFileType(absPath);
  const fileName = path.basename(absPath);
  const ext = path.extname(absPath).toLowerCase();
  const maxChars = opts.maxChars || DEFAULT_CHUNK_CHARS;
  const overlapChars = opts.overlapChars || DEFAULT_OVERLAP_CHARS;

  let rawText = null;

  switch (fileType) {
    case "pdf":
      rawText = extractPDFText(absPath);
      break;
    case "docx":
      rawText = extractDocxText(absPath);
      break;
    default:
      rawText = readTextFile(absPath);
  }

  if (!rawText || !rawText.trim()) return [];

  const chunks = chunkContent(rawText, fileType);
  if (chunks.length === 0 && rawText.trim().length >= MIN_CHUNK_CHARS) {
    chunks.push(rawText.trim().slice(0, maxChars * 2));
  }

  return chunks.map((text, i) => ({
    text: text.slice(0, maxChars * 3), // safety cap
    metadata: {
      source: absPath,
      fileName,
      extension: ext,
      fileType,
      chunkIndex: i,
      totalChunks: chunks.length,
      ingestedAt: new Date().toISOString(),
    },
  }));
}

/**
 * Escanea un directorio recursivamente y devuelve todas las rutas de archivos soportados.
 *
 * @param {string} dirPath
 * @param {Object} opts
 * @param {number} opts.maxFiles — límite de archivos
 * @param {number} opts.maxFileBytes — tamaño máximo por archivo
 * @param {Array<string>} opts.ignoreDirs — directorios a ignorar
 * @returns {Array<string>}
 */
function scanDirectory(dirPath, opts = {}) {
  const absPath = path.resolve(dirPath);
  if (!fs.existsSync(absPath) || !fs.statSync(absPath).isDirectory()) return [];

  const maxFiles = opts.maxFiles || 5000;
  const maxFileBytes = opts.maxFileBytes || 3 * 1024 * 1024; // 3MB default
  const ignoreDirs = new Set([
    ...(opts.ignoreDirs || []),
    "node_modules",
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    "target",
    ".next",
    ".cache",
    "coverage",
    ".DS_Store",
  ]);

  const files = [];

  function walk(dir) {
    if (files.length >= maxFiles) return;
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }

    for (const entry of entries) {
      if (files.length >= maxFiles) return;
      const fullPath = path.join(dir, entry.name);

      if (entry.isDirectory()) {
        if (ignoreDirs.has(entry.name)) continue;
        if (entry.name.startsWith(".") && !opts.includeHidden) continue;
        walk(fullPath);
      } else if (entry.isFile()) {
        if (!isSupportedFile(fullPath)) continue;
        try {
          const stat = fs.statSync(fullPath);
          if (stat.size > maxFileBytes) continue;
          if (stat.size === 0) continue;
          files.push(fullPath);
        } catch {
          continue;
        }
      }
    }
  }

  walk(absPath);
  return files.slice(0, maxFiles);
}

/**
 * Estadísticas de un directorio sin procesarlo.
 */
function scanDirectoryStats(dirPath, opts = {}) {
  const files = scanDirectory(dirPath, opts);
  const byType = {};
  let totalBytes = 0;

  for (const f of files) {
    const ext = path.extname(f).toLowerCase() || "(sin extensión)";
    byType[ext] = (byType[ext] || 0) + 1;
    try {
      totalBytes += fs.statSync(f).size;
    } catch { /* ignore */ }
  }

  return {
    totalFiles: files.length,
    totalBytes,
    totalMB: (totalBytes / (1024 * 1024)).toFixed(1),
    byType,
  };
}

module.exports = {
  processFile,
  scanDirectory,
  scanDirectoryStats,
  detectFileType,
  isSupportedFile,
  chunkContent,
  chunkByParagraphs,
  chunkMarkdown,
  chunkCode,
  extractPDFText,
  extractDocxText,
  SUPPORTED_EXTENSIONS,
};
