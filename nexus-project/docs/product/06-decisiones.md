# 06 · Registro de decisiones (ADR)

Formato: contexto, decisión, alternativas, consecuencias. Estado: **Aceptada** (viene del brief o de evidencia), **Propuesta** (requiere confirmación del fundador). Fecha: 2026-10-27.

| ADR | Título | Estado |
|---|---|---|
| 01 | Un operador, un slot | Aceptada (brief) |
| 02 | Erasure coding k-de-n para pesos en reposo | Aceptada (brief) |
| 03 | Sin token en v0.1/v0.2 | Aceptada (brief) + propuesta de reparto |
| 04 | EVM (Base) frente a Substrate para liquidación | Propuesta (consistente con spec §13) |
| 05 | Pipeline por slots frente a tensor parallel; corte T opcional | Aceptada |
| 06 | TEE como mejora futura, no en MVP | Aceptada |
| 07 | Licencia del código y de los modelos | **Propuesta — abierta** |
| 08 | Asignación estratificada con baliza tras cierre de registro | Aceptada |
| 09 | Plano de control centralizado en v0.1; P2P aparcado | Propuesta |
| 10 | Verificación económico-estadística, no criptográfica | Propuesta |
| 11 | Atenhea fuera del camino crítico de v0.1 | Propuesta |

---

## ADR-01 · Un operador, un slot

- **Contexto.** El objetivo es que ningún operador reúna el modelo. Un operador con muchos nodos podría cubrir varios slots. `swarmsim.py::assign_slots` fija a cada operador a un slot; el máximo por operador es 1/S (`max_fraccion_por_operador`, escenario 5).
- **Decisión.** Cada operador (identidad lógica) queda fijado a **un único slot por época**, por muchos nodos que tenga; el trabajo dentro del slot se reparte ∝ velocidad.
- **Alternativas.** (a) Libre elección de slot por el nodo (determinista por capacidad): un atacante necesita 16 identidades en vez de ~54 **[SIM]**. (b) Réplicas completas por nodo (H0 actual): contradice el producto. (c) Slot por nodo, no por operador: un operador grande acumularía slots.
- **Consecuencias.** + Cota dura 1/S por operador. − Solo vale si "operador" es una identidad real: **el Sybil la rompe** (ADR-08, `04` §4.2). − Operadores grandes ocupan ~21 % de su slot **[SIM]** y su salida degrada ese slot (recuperación ~27 min p50). Un tope por operador (15 % del slot) cambia poco con la distribución simulada.

## ADR-02 · Erasure coding k-de-n

- **Contexto.** Los pesos en reposo deben sobrevivir al churn y no revelarse a nodos de almacenamiento. **[SIM]** escenario 3: 10-de-16 (1,6×) pierde 0,0005 por época frente a 0,0103 de 3 réplicas (3×).
- **Decisión.** Cada slot se cifra y se trocea con EC (por defecto 10-de-16) con manifiesto Merkle firmado; los nodos de almacenamiento solo ven ciphertext. Parámetros configurables (`ec_k`, `ec_n` en el manifiesto) para la demo.
- **Alternativas.** Réplicas simples (más caras, más sencillas); IPFS (sin garantías de disponibilidad, dependencia externa); almacenamiento solo en nodos de cómputo.
- **Consecuencias.** + Menor sobrecarga y mayor durabilidad. − Complejidad de reparación (**[SIM]** 5,6 GB/día por modelo a 1 % de pérdida diaria; crece con el nº de modelos). − Implementación Reed-Solomon propia en stdlib: rendimiento y corrección a probar (E4). − Cifrado no impide que el nodo asignado vea el slot en claro tras `grant`.

## ADR-03 · Sin token en v0.1 (ni v0.2)

- **Contexto.** El brief fija "sin token en v0.1". La spec heredada (`docs/spec-fusion-nexus-atenea.md` §8) diseña NEX v2 con emisión atada a ingresos y advierte de MiCA; el código heredado (`nexus/tokenomics`, `nexus/economics`) está derogado por la propia spec. El escrow existente acepta **cualquier ERC-20 estándar** (`InferenceEscrow.sol`), por lo que no necesita token propio.
- **Decisión.** v0.1: libro de contribuciones en unidades internas (micro-USD de referencia, como `nexus_common.price_micro_usd`) sin transferencia de valor. v0.2: liquidación **en testnet pública con un ERC-20 de prueba** (sin valor). Cualquier token propio o stablecoin real es una decisión posterior con dictamen legal.
- **Alternativas.** (a) Token nativo (NEX): riesgo de calificación como valor (MiCA/CNMV, ver spec §8.2 y §15), expectativas de rendimiento, regla honesta 4 y 5. (b) Pagos fiat/stablecoin directos con liquidación off-chain. (c) Crédito interno canjeable.
- **Consecuencias.** + Evita riesgo regulatorio y reduce superficie. + Mensaje de marketing limpio. − Sin token, el reparto "5 % quema" carece de sentido: **propuesta** reasignar a verificación + tesoro (revisar 75/10/5/5/5 de `nexus_common.split_payment`; el contrato lo fija en constantes: cambiarlo implica nuevo despliegue). − Los operadores no tienen instrumento de stake: el stake solo no protegía en cualquier caso **[SIM]**; la identidad se resuelve con comisión no reembolsable y huella (futuro).

## ADR-04 · EVM (Base) frente a Substrate

- **Contexto.** Hay un escrow EVM probado en local (`settlement-evm`, Foundry + Anvil) y un runtime Substrate sin manifiestos (`NEXUS/nexus-blockchain`, `PROJECT_DELIVERY.md` M4). La spec §13 recomienda Base.
- **Decisión.** Liquidación en **EVM (Base Sepolia primero)** reutilizando `InferenceEscrow.sol` y `batch_builder.py`; **descartar Substrate** y los contratos heredados.
- **Alternativas.** Substrate propio (control total, coste de mantenimiento enorme); Solana (reescritura); liquidación off-chain en v0.1.
- **Consecuencias.** + Reutiliza lo más sólido del repo. − Signer de gateway de confianza y árbitro `owner`: la descentralización de la liquidación es parcial; mejora requerida (bond de nodos, multisig, verificación de recibos en cadena es cara). − Revisión independiente obligatoria antes de testnet pública. Hay que actualizar sus docs (C4, C5 de doc 01). − Dependencia de Foundry/Anvil no disponibles en este entorno.

## ADR-05 · Pipeline por slots (no tensor parallel); corte por capa T como opción

- **Contexto.** Hay dos formas de repartir un modelo: por capas (pipeline) o cortando cada capa (tensor parallel). **[SIM]** pipeline S=8: ~4–6 tok/s por stream, ≈0,95 M tok/s agregado en lote 32 (cota superior). Tensor parallel T=8 cuesta ~0,6 s/token a 0,5 ms de RTT, 2,3 s a 2 ms, 22 s a 20 ms: solo viable con pods co-localizados y lotes grandes. DiLoCo exige réplica completa (≲1B en 24 GB).
- **Decisión.** v0.1–v0.2: **pipeline por slots (T=1)**. El manifiesto soporta `n_slices` (=T) para activar corte por capa más adelante en modo batch.
- **Alternativas.** Tensor parallel desde el inicio (latencia inaceptable por WAN); réplica completa (H0: sin partición); MoE con expertos por nodo (no evaluado).
- **Consecuencias.** + Menos comunicación por token (un salto por slot). − **Peor exposición ante coaliciones** (2 %→0,44; 5 %→0,99 a S=16, T=1 **[SIM]**). − Latencia crece con S. − Entrenamiento: solo pipeline híbrido (≈59 etapas para 70B/24 GB) y condicionado a compresión ≥10× no validada en convergencia.

## ADR-06 · TEE como mejora futura, no MVP

- **Contexto.** Sin TEE/MPC el nodo tiene su slot en claro (brief §2). GPUs con computación confidencial y attestation podrían impedirlo, pero el hardware de aficionados no lo soporta de forma general. El `KeyVault.grant(..., attestation=None)` ya prevé el parámetro.
- **Decisión.** No usar TEE en v0.1/v0.2. Reservar la interfaz de attestation en `KeyVault` y el formato de manifiesto. Evaluar en T5 (**E7**) con operadores reales de TEE.
- **Alternativas.** MPC/HE (órdenes de magnitud más lento, no viable); solo confianza económica.
- **Consecuencias.** + MVP simple. − Se debe declarar siempre que el slot está en claro (lista NO-3, NO-4). − Si la attestation se exige, se excluye a la mayoría de aficionados (reduce oferta). − TEE añade confianza en el fabricante.

## ADR-07 · Licencia del código y de los modelos (abierta)

- **Contexto.** No hay fichero `LICENSE` en la raíz del repo ni en `NEXUS/` (verificado con `ls`). El código de terceros (`NEXUS/atenhea/third_party/chl`) trae licencia propia, **[POR VERIFICAR]**. Los modelos base (Gemma, Llama…) tienen licencias con restricciones de uso y redistribución. El simulador y el escrow se pretenden "abiertos" (OK-8 en doc 04).
- **Decisión (propuesta, requiere confirmación del fundador y consejo legal).** Código del cliente, CLI, nodo y SDK bajo **Apache-2.0** (patentes explícitas, favorece adopción de operadores). Servicios de plano de control: mismo código, sin cláusulas copyleft de red en v0.1. Cada modelo publicado conserva su licencia, la declara en el manifiesto (`license`) y `publish` falla si falta; solo se admiten modelos cuya licencia permita fragmentarlos y servirlos.
- **Alternativas.** MIT (más simple, sin patentes); AGPL-3.0 (protege de nube que cierra el servicio, frena adopción corporativa); BSL/fuente disponible (menos confianza de la comunidad).
- **Consecuencias.** + Claridad para contribuidores y operadores. − Decisión irreversible tras recibir contribuciones externas (CLA/DCO). − Verificación de compatibilidad de licencias de dependencias (cryptography, etc.) antes de publicar. **[POR VERIFICAR]**.

## ADR-08 · Asignación estratificada con baliza tras cierre de registro

- **Contexto.** **[SIM]** escenario 7a: asignación determinista por capacidad declarada → atacante elige slot, 16 identidades bastan; aleatoria pura → eficiencia 0,83; estratificada (ordenar por capacidad, permutar slots por bloques con baliza) → eficiencia 0,956 y ~54 identidades (p99 115).
- **Decisión.** Asignación estratificada; la baliza se publica **después** de cerrar la ventana de registro de la época. En v0.1 la genera el coordinador (centralizado).
- **Alternativas.** Determinista (eficiente, manipulable); aleatoria (menos eficiente); asignación libre con subasta.
- **Consecuencias.** + Mejor equilibrio capacidad/secreto. − La baliza debe ser inmanipulable: en v0.1 **no lo es** (coordinador de confianza); beacon verificable en v1.0. − Reasignaciones por época implican redescargar slots (~60 s p50 con 2,2 GB **[SIM]**).

## ADR-09 · Plano de control centralizado en v0.1; libp2p aparcado

- **Contexto.** `NEXUS/nexus/network/p2p_protocol.py` es hoy un stand-in TCP loopback con Ed25519, "NO es libp2p", sin anti-replay (docstring). `FUSION.md` (spec §6.1) ya recomendaba HTTPS+polling para el MVP.
- **Decisión.** Gateway, coordinador, vault y libro son un servicio del equipo con protocolo HTTPS firmado; el P2P queda fuera hasta v1.0. Comunicarlo como tal.
- **Alternativas.** Coordinación P2P/DHT desde el inicio; coordinador federado de varios operadores.
- **Consecuencias.** + Foco en la propuesta diferencial (partición/reparto). − Punto único de fallo y de confianza (X6 en doc 04): impide decir "descentralizado" sin matiz (NO-5). − Migración posterior de transporte: los formatos de manifiesto y recibo no deben cambiar.

## ADR-10 · Verificación económico-estadística, no criptográfica

- **Contexto.** No hay zkML práctico para modelos grandes; el muestreo no determinista complica la comparación (spec §7.2: "no hay prueba absoluta"). H0 solo comprueba consistencia interna del recibo.
- **Decisión.** v0.1: recibos firmados + encadenado de hashes + conteo independiente en gateway. v0.2: canarios (1–2 %) + doble ejecución muestreada (2 %) con tolerancia numérica + reputación + disputa. El recibo se describe siempre como medición, no como prueba de cálculo.
- **Alternativas.** zkML/proof of inference (inmaduro y caro); TEE attestation (ADR-06); redundancia completa (2× coste).
- **Consecuencias.** + Viable. − Un nodo puede mentir con probabilidad de ser pillado < 1; la esperanza de castigo debe superar la ganancia (parámetros por calibrar en E5/E6). − No determinismo entre GPUs (E3) puede dar falsos positivos (kill: ≥5 %).

## ADR-11 · Atenhea fuera del camino crítico de v0.1

- **Contexto.** Atenhea (`NEXUS/atenhea/`) carga el checkpoint HF completo en un proceso, MPS/macOS, una generación a la vez; no tiene ejecución por rangos de capa (comprobado en `native_runtime.py`: sin API de etapas). La propuesta de valor del producto nuevo es que **nadie** tenga el modelo completo.
- **Decisión.** El runtime de etapas se escribe sobre un modelo pequeño con capas accesibles (stdlib/numpy opcional). Atenhea queda como backend opcional de "nodo réplica completa" para pruebas comparativas y como fuente de ideas (`.nram`, medición). No se promociona como parte del producto.
- **Alternativas.** Forzar Atenhea a ejecutar rangos de capa (invasivo, Mac-only); usar un runtime externo (llama.cpp/vLLM) en v0.2+.
- **Consecuencias.** + Ruta crítica corta. − Se pierde la reutilización de ~1,4 k líneas de motor. − La demo no usa Gemma. − Debe actualizarse el relato público (C1 de doc 01) para no vender "Atenhea" como núcleo.
