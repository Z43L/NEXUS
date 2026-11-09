# Índice · docs/product

Propietario: product-architect · Fecha: 2026-10-27 · Brief: `nexus-project/BRIEF.md`

| Documento | Contenido | Úsalo para |
|---|---|---|
| [01-analisis-repositorio.md](01-analisis-repositorio.md) | Auditoría del repo: real / parcial / esqueleto, 14 contradicciones, tabla reutilizar-reescribir-descartar | Saber qué se puede reutilizar y qué documentos sobreafirman |
| [02-PRD.md](02-PRD.md) | Visión, 3 usuarios, alcance v0.1/v0.2/v1.0, RF/RNF, métricas con umbrales como supuestos, fuera de alcance | Definir qué se construye y qué no |
| [03-arquitectura.md](03-arquitectura.md) | Componentes, 4 flujos (Mermaid), manifiesto y recibos, mapa de ficheros `code/`, decisiones de escala, evolución a entrenamiento | Guía para eng-storage y eng-runtime |
| [04-modelo-de-amenazas.md](04-modelo-de-amenazas.md) | Activos, adversarios, ataques y mitigaciones, riesgo residual; **§7 afirmaciones permitidas (13) y prohibidas (18)** | Landing y GTM: fuente obligatoria de copy |
| [05-roadmap.md](05-roadmap.md) | 6 trimestres con criterios de salida, equipo, dependencias, 14 riesgos con experimento, puertas G1–G5 | Planificación y priorización |
| [06-decisiones.md](06-decisiones.md) | 11 ADR (slots, EC, token, EVM, pipeline, TEE, licencia, asignación, plano de control, verificación, Atenhea) | Trazabilidad de decisiones |

## Lectura rápida por rol

- **eng-storage**: 03 §3.1, §4.1, §5; 06 ADR-02; contrato en el brief §6.
- **eng-runtime**: 03 §3.2–3.4, §4.2–4.4, §5; 01 §6 (qué copiar de `h0/`); 06 ADR-05, 09, 11.
- **landing / gtm**: 04 §7 (obligatorio), 02 §4, 01 §5 (contradicciones a no heredar: C1, C13).
- **business**: 02 §8, 05 (R10 coste real), 06 ADR-03.

## Convención de etiquetas

`[SIM]` cifra del simulador (`research/swarm-sim`, re-ejecutado el 2026-10-27, 26 tests OK) · `[EXISTE]` código probado en el repo · `[NUEVO]` por construir · `[PROPUESTA]` formato a validar · `[SUPUESTO]` umbral sin evidencia · `[POR VERIFICAR]` falta dato · `[NO RESUELTO]` línea de investigación.
