# 06 · Pitch y memo de inversión

Fecha: 2026-10-27. Estado real: **alpha cerrada, testnet, sin token, sin liquidación con dinero real, sin clientes de pago, sin ronda abierta.**
Todo lo cuantitativo de proyección sale de `finance/model.py`; todo lo "real" sale del repo (`EXECUTIVE_BRIEF.md`, `README.md`). Lo que falta se dice como falta.

## Parte A. Esquema del pitch deck (12 diapositivas)

Regla: ninguna diapositiva puede mostrar clientes, logos, testimonios, usuarios, ingresos, rondas ni *benchmarks* que no existan.

| # | Título | Mensaje | Evidencia real disponible | Qué falta |
|---|---|---|---|---|
| 1 | NEXUS | Red de inferencia de IA en la que ningún operador tiene el modelo completo y cada nodo cobra por trabajo verificado | Nombre y repo; estado "alpha cerrada, testnet" visible | Nombre y dominio no despejados (`nexus.example` es marcador; riesgo de marca) |
| 2 | Problema | Los modelos abiertos se sirven desde pocos proveedores que ven los pesos y los prompts; los autores no tienen una vía para cobrar regalías sin entregar los pesos a un único operador | Argumento; precios de referencia con URL (DeepInfra, OpenRouter) | Entrevistas con desarrolladores y autores: ninguna realizada |
| 3 | Solución | API compatible con OpenAI + recibos firmados + modelo partido en slots (fijo por operador) + pago proporcional al trabajo verificado | H0: gateway `POST /v1/chat/completions`, worker, recibos Ed25519, ledger SQLite; SDK Python/TS | H1 entre redes independientes no demostrado |
| 4 | Cómo funciona | S slots (rangos de capas), asignación estratificada, erasure coding k-de-n con manifiesto Merkle, clave por slot. **Un nodo de cómputo sí tiene su slot en claro en memoria**; una coalición suficiente puede reconstruir el modelo; quien consulta puede destilarlo | `research/swarm-sim`: coalición 2 % ⇒ P≈0,44, 5 % ⇒ P≈0,99 con ~300 nodos por slot; Sybil de 16 slots ≈ 770 USD (ilustrativo) | Prototipo multiproceso integrado con pesos reales; corte por capa/TEE no implementados |
| 5 | Estado y evidencia | Funciona en local y se puede reproducir | Suite H0 mock: 100/100 jobs y recibos; puerta real con Atenhea: 100/100 (salida limitada a 24 tokens); E2E Compose multiusuario; escrow Foundry 21/21 y Python 31/31; E2E Anvil con 2 claims (`docs/evidence/*.json`) | CI remoto sin ejecutar; revisión de seguridad independiente pendiente; sin hash de pesos; sin Base Sepolia |
| 6 | Mercado | Hay un mercado de inferencia de modelos abiertos con precios conocidos y una dispersión de 5-6× entre proveedores | Precios con URL y fecha (`02-precios.md`): 70B a 0,10/0,32 USD/M (DeepInfra) frente a 0,88 USD/M (Together, `[POR VERIFICAR]`) | **Tamaño de mercado: no lo afirmamos.** Hace falta fuente fiable (URL y fecha) antes de ponerlo |
| 7 | Modelo de negocio | La comisión sobre inferencia no sostiene la empresa; los ingresos son enclaves privados, SLA, certificación de operadores y regalías con comisión | Mecánica de reparto en `InferenceEscrow.sol`; propuesta 15 % plataforma / 5 % verificación / 10 % autor / resto nodo | Ningún precio validado con clientes; enclave = coste + margen, sin cotización |
| 8 | Economía unitaria | Honestidad por delante: a precio de mercado, una petición de 900 tokens deja ≈ 0,000019 USD de comisión; un operador con Mac/PC existente cubre electricidad pero gana unos pocos USD/mes; un rig dedicado no cubre coste | `finance/output/unit_economics.csv`, `operator_economics.csv` | Medir tok/s reales por nodo (hoy el motor es serial; la cota de 190 tok/s es del simulador) |
| 9 | Plan de ingresos | 3 escenarios a 36 meses: ingreso neto mes 36 de 11 k / 52 k / 170 k USD/mes; sin equilibrio en 36 meses en ninguno; la línea decisiva es enclaves | `finance/output/resumen.md` (22 tests pasan) | Validación de supuestos con datos; el modelo es una proyección |
| 10 | Go-to-market | Comunidad de modelos abiertos y desarrolladores primero; operadores certificados y enclaves después; lista de espera → alpha → beta | `docs/go-to-market/` (otro equipo), SDKs, landing en borrador | Lista de espera real y su tamaño (`[POR VERIFICAR]`); canal de ventas de enclaves |
| 11 | Competencia | Proveedores centralizados (OpenRouter, DeepInfra, Together), marketplaces de GPU (Vast.ai, Akash, Nosana) y redes con token (Bittensor) | Páginas oficiales consultadas (comisiones y precios) | Análisis comparativo profundo y de Petals/otros `[POR VERIFICAR]`; diferenciación probada con cliente |
| 12 | Equipo, ronda y hitos | Pre-seed ≈ 1,25 M USD (≈ 1,14 M€) para 18 meses; hitos: H1 multi-red, escrow auditado, ≥ 30-50 operadores externos, demanda de pago medida, ≥ 3 pilotos de enclave | Presupuesto derivado del modelo (`04-financiacion.md`) | Equipo (nombres, trayectoria) `[POR VERIFICAR]`; interés real de inversores: ninguno consultado |

Notas de uso: (a) la diapositiva 9 debe mostrar "no se alcanza equilibrio en 36 meses" tal cual; (b) usar la palabra "descentralizado" solo con el matiz de la diapositiva 4; (c) la diapositiva 8 va antes que la 9 para que la proyección se lea con el contexto.

## Parte B. Memo de inversión (≈ 2 páginas)

**Para**: posibles inversores pre-seed. **Estado**: borrador interno, no es oferta de valores.

### 1. Tesis
NEXUS es una red de inferencia donde el modelo se parte en *slots* y cada operador queda fijado a uno, de modo que **ningún operador reúne más de 1/S del modelo** y se paga por trabajo verificado con recibos firmados. Apuesta: habrá clientes dispuestos a pagar por trazabilidad verificable, enclaves privados y regalías de autores sobre modelos abiertos, y operadores dispuestos a servir con hardware ya amortizado. Es una apuesta técnica y de mercado sin validar.

### 2. Estado del producto (verificado en el repositorio, 2026-10-26/27)
Alpha cerrada en testnet. Funciona en local: gateway OpenAI-compatible, worker, recibos Ed25519, ledger SQLite; 100/100 trabajos con motor simulado y 100/100 con Atenhea real (con salida limitada a 24 tokens); E2E Compose con dos cuentas; contrato de escrow de liquidación con 21/21 pruebas Foundry y E2E local con Anvil. **No** hay: H1 entre redes independientes, medición de throughput en multi-nodo, revisión de seguridad independiente, liquidación con dinero real, token, clientes ni ingresos. El simulador (`research/swarm-sim`) da órdenes de magnitud, no medidas.

### 3. Qué es y qué no es la protección del modelo
Un nodo de cómputo tiene su slot en claro en memoria. Una coalición suficiente puede reconstruir el modelo (con ≈ 300 nodos por slot, una coalición del 2 % ⇒ P≈0,44; 5 % ⇒ P≈0,99 en el simulador); un Sybil de 16 slots cuesta ≈ 770 USD con parámetros ilustrativos; quien consulta puede destilar el modelo. No vendemos "trustless", ni privacidad total.

### 4. Mercado y precios
No presentamos tamaño de mercado: no tenemos una fuente fiable aún. Los precios de referencia son públicos: Llama 3.3 70B a 0,10/0,32 USD por millón de tokens (DeepInfra, 2026-10-27) y Gemma 3 27B a 0,08/0,16; el mismo 70B aparece a 0,88/0,88 en otro proveedor (`[POR VERIFICAR]`). A esos precios, una red de GPU de consumo no gana por precio; la oferta de valor es otra.

### 5. Modelo de negocio y finanzas (proyección)
Cinco líneas: comisión de inferencia, comisión sobre regalías, enclaves, SLA, certificación (fine-tuning futuro). El reparto propuesto es 15 % plataforma, 5 % verificación, 10 % autor (solo con adaptador), resto nodo, sin quema. El modelo de 36 meses (22 tests) da:

| | Conservador | Base | Optimista |
|---|---|---|---|
| Ingreso neto mes 36 (USD/mes) | 11.286 | 51.647 | 169.787 |
| Ingreso neto acumulado (USD) | 64.844 | 508.977 | 2.074.729 |
| EBITDA mes 36 (USD/mes) | –75.008 | –92.078 | –63.864 |
| Necesidad acumulada de financiación (USD) | 1.599.273 | 2.326.578 | 2.106.383 |
| Equilibrio en 36 meses | no | no | no |

El ≈ 89 % del ingreso base del mes 36 es de enclaves: una línea con cero clientes hoy. La inferencia comunitaria aporta ≈ 1 %.

### 6. Ronda
Pre-seed ≈ 1,25 M USD (quema base 964.542 USD en 18 meses × 1,25): 61 % equipo, 12 % auditorías, 8 % legal, 7 % marketing, 6 % G&A, 5 % infraestructura. Seed posterior ≈ 1,7 M USD en el mes 19 si se cumplen los hitos (H1 multi-red, escrow auditado, operadores externos, demanda medida, pilotos de enclave). Alternativas no dilutivas (NLnet, EIC, CDTI/ENISA, ESP, Nosana) en `04-financiacion.md`. Cap table orientativo: con las hipótesis allí descritas, los fundadores quedarían ≈ 62 % tras la seed; es aritmética, no valoración.

### 7. Riesgos principales (ver `07-riesgos.md`)
1. **Economía del operador**: a precio de mercado el operador gana poco o pierde; sin oferta no hay red.
2. **Demanda de enclaves sin validar**: la línea decisiva carece de cliente y de precio.
3. **Seguridad de la secrecía**: coaliciones y Sybil; la huella por nodo es investigación abierta.
4. **Licencias**: Gemma ≤ 3 y Llama imponen condiciones a la distribución de pesos; hay que confirmar qué Gemma usa Atenhea.
5. **Pagos y regulación**: KYC/AML, estructura de marketplace, riesgo de que cualquier token sea valor.
6. **Equipo y ejecución**: alcance enorme para un equipo pequeño `[POR VERIFICAR]` composición del equipo.
7. **Marca NEXUS** no despejada y credencial expuesta en el historial público.

### 8. Qué haríamos con el dinero y qué mediríamos
Medir throughput real, cerrar H1 multi-red, auditar el escrow, abrir el primer pago real pequeño, recoger 20-30 entrevistas de enclave y decidir con datos si seguir, cambiar de línea (p. ej. foco en enclaves/regalías) o parar. La plantilla crece solo con hitos.
