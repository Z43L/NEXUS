# Spec de fusión NEXUS × Atenhea

**Red P2P de inferencia de IA con marketplace de piezas de modelo y economía NEX**

- Versión: 0.1 (borrador para decisión)
- Fecha: 2026-10-20
- Repos: `Z43L/NEXUS` (commit 452c68e) y `Z43L/4T3NH34` — Atenhea (commit d3e64f1)
- Autor del análisis: Wally, a petición de David Moreno
- Estado: **borrador de producto con implementación parcial**. Desde esta propuesta existe una ruta local H0/H1 con Router, worker, recibos y una vertical aislada de settlement EVM. No equivale a red multi-host, marketplace, testnet ni producto listo para producción; el estado verificable y sus límites están en `EXECUTIVE_BRIEF.md` y `PROJECT_DELIVERY.md`. Este documento conserva los objetivos y criterios de producto pendientes.

---

## 0. Resumen ejecutivo

NEXUS y Atenhea son dos mitades del mismo producto:

- **NEXUS** tiene el plano de control y la economía (red P2P libp2p, token ERC-20 `NEX` con `payForService`, staking, reputación, Proof-of-Knowledge, tokenomics) pero **ningún motor de inferencia propio**: su núcleo LLM llama a APIs externas vía LangChain.
- **Atenhea** es un **motor de inferencia local real y probado** (Gemma 4 E2B en Safetensors BF16, sin llama.cpp, API compatible OpenAI con streaming) pero solo escucha en `localhost`, sin red, sin identidad, sin pagos.

**Decisión central de la fusión:** Atenhea se convierte en el *worker* (nodo trabajador) de la red; NEXUS se convierte en el *plano de control* (descubrimiento, enrutado, medición, liquidación y gobernanza). La integración es API contra API, sin reescribir el motor.

**Segunda decisión central:** los pesos base (checkpoint Gemma, ~10 GB, licencia de Google) **nunca viajan por la red**. Cada nodo lo descarga de la fuente oficial y verifica sus hashes, exactamente como Atenhea ya hace. Lo que la red distribuye, versiona y comercia son los **`.nram`**: adaptadores LoRA y microexpertos de pocos MB, en un contenedor con manifiesto y `tensor_sha256` verificable.

**Tercera decisión central (la incómoda):** la inferencia de un modelo clase E2B vale hoy en el mercado centralizado ~0,05 $/M tokens de entrada y ~0,10 $/M de salida (Gemma 3 4B en OpenRouter). A esos precios, un nodo a pleno rendimiento ingresa céntimos al día (ver §8.4). Por tanto, **el negocio no es vender tokens baratos**: es (1) el marketplace de microexpertos con regalías por tarea especializada, (2) trabajos batch con prima de privacidad (el cómputo ocurre en máquinas de la red, la memoria del usuario nunca sale de su equipo) y (3) a largo plazo, sharding de modelos grandes, donde el precio por token es 10-30× mayor. La spec está ordenada para validar eso en ese orden.

---

## 1. Inventario verificado (estado real de cada pieza)

### 1.1 Atenhea (`4T3NH34`) — el motor

| Pieza | Estado | Evidencia |
|---|---|---|
| Motor nativo Gemma 4 E2B (BF16, Safetensors, PyTorch MPS/CPU) | ✅ Funciona | `native_runtime.py` (402 líneas), probado en macOS/Apple Silicon |
| Servidor HTTP API compatible OpenAI (`:11434`) + motor (`:11436`) | ✅ Funciona | `onram.py` (1.291 líneas): `/v1/chat/completions`, `/v1/responses`, `/v1/messages`, streaming SSE |
| Endpoints de conteo de tokens | ✅ Funciona | `/v1/chat/completions/input_tokens`, `/v1/messages/count_tokens` → **es el taxímetro de la red** |
| Contenedor `.nram` v2 | ✅ Funciona | `nram_container.py`: magic `NRAM\x00\x02`, manifiesto JSON + sección Safetensors, `tensor_sha256`, escritura atómica |
| Microexpertos (MLP residuales, enrutado por activaciones) | ✅ Funciona | `micro_extensions.py`: banco de expertos, `attach_extension`, crecimiento `grow()` |
| Microentrenamiento y evolución LoRA con validación y promoción | ✅ Funciona (acotado) | `micro_training.py`, `nram_evolve.py`; pausa la generación mientras entrena |
| Memoria episódica CHL + mapa de hechos (SQLite) | ✅ Funciona | `episodic_memory.py`, `world_memory.py`; puente a `CHL-episodic-agent-memory` |
| Caché de prefijo KV | ✅ Funciona | `prefix_cache.py`: 1 entrada, hasta 2.048 tokens / 32 MiB |
| Batería de tests | ✅ 26 ficheros `test_*.py` | cubren runtime, `.nram`, memoria, entrenamiento |
| **Concurrencia** | ⚠️ **1 generación en serie por nodo** | un motor residente, un hilo de inferencia compartido |
| **Plataformas** | ⚠️ Solo macOS/MPS validado; sin selección CUDA; Windows no soportado (POSIX/`fcntl`) | README §Requisitos |
| **Red** | ❌ Solo `127.0.0.1`, sin autenticación | hay que construir el modo worker (§5.2) |

Requisitos de un nodo Atenhea hoy: ~10 GB de disco para el checkpoint, 16 GB de RAM (con presión de memoria en prompts largos), Python 3.12, Node.js para CHL.

### 1.2 NEXUS — el plano de control y la economía

| Pieza | Estado | Evidencia |
|---|---|---|
| Token `NexusToken.sol` (ERC-20 «NEX», `payForService`, registro de proveedores) | 🟡 Esqueleto sólido | 38 líneas; sin pausas, sin control de mint, fees en bps sin tope |
| `Staking.sol` (`NexusStaking`) | 🟡 Esqueleto sólido | stake mínimo **1.000 NEX**, bloqueo **30 días**, slash **10 %** |
| Otros 11 contratos (Governance, RewardSystem, KnowledgeRegistry, ProofOfKnowledge…) | 🟡 Esqueletos | 1.134 líneas Solidity en total |
| Red P2P libp2p (`/nexus/message`, `/discovery`, `/sync`) | 🔴 **Roto** | `p2p_protocol.py` invoca 5 métodos que no existen: `_encode_message`, `_decode_message`, `_start_peer_discovery`, `_handle_discovery`, `_handle_sync` |
| Roles de nodo (INFERENCE / VALIDATION / STORAGE / HYBRID) y requisitos | 🟡 Diseño en código | `node_roles.py`: INFERENCE exige ≥16 GB RAM y ≥100 GB disco — **coincide con un nodo Atenhea** |
| Consenso Proof-of-Knowledge (votos firmados, timeouts) | 🟡 Esqueleto | `proof_of_knowledge.py` (153 líneas) |
| Sistema de recompensas por contribución | 🟡 Esqueleto a rediseñar | `reward_system.py`: tarifas fijas en tokens (computation=15, validation=10…) → inflacionario, se sustituye en §8 |
| Tokenomics (distribución inicial + emisión) | 🟡 Diseño en código a corregir | ver §8.2 y §8.3 |
| Sharding de memoria por embeddings (KMeans) | 🟡 Esqueleto | `shard_manager.py`: sirve para el registro distribuido de `.nram`, **no** para partir pesos de un LLM |
| Núcleo LLM | 🔴 No es inferencia | `dynamic_model.py`: cliente LangChain a APIs; el fine-tuning «no aplica» |
| `marketplace_contract.py`, `reputation.py`, `asset_types.py` (raíz) | 🔴 **0 bytes** | existen los nombres; hay que escribirlos |

**Conclusión del inventario:** de NEXUS se reutiliza el diseño, los contratos base y los roles; de Atenhea se reutiliza el motor tal cual. El trabajo nuevo es la unión: modo worker en red, enrutador, registro de `.nram`, medición firmada y liquidación.

---

## 2. Principios de diseño (innegociables)

1. **Los pesos base no se redistribuyen.** Cada nodo descarga el checkpoint de la fuente oficial (Google/HF) y verifica hashes. La red mueve manifiestos, adaptadores y microexpertos — artefactos propios, pequeños y con licencia clara.
2. **La memoria del usuario nunca sale de su equipo.** La memoria episódica CHL y el mapa de hechos son locales por diseño. A la red solo viajan *trabajos* (prompts de clientes), nunca la memoria de un nodo.
3. **Sin herramientas en trabajos remotos.** Atenhea sirve agentes con tools en local; un trabajo de red se ejecuta siempre en modo texto, sin tools, sin acceso a ficheros del nodo.
4. **Emisión atada a ingresos.** Ningún nodo cobra por existir. Toda recompensa sale de un pago previo de un cliente (más un fondo de incentivos finito y con fecha de fin, §8.3).
5. **Medición firmada, liquidación agregada.** Cada trabajo genera un recibo firmado por el nodo (§7). La cadena se usa para liquidar lotes, no por petición (el gas mataría el margen).
6. **Testnet hasta el final.** NEX no se vende, no se promete y no cotiza durante las fases H0-H3. La decisión de mainnet es una puerta separada con revisión legal MiCA (§11).
7. **Honestidad de capacidad.** Un nodo = una generación concurrente. La red escala añadiendo nodos; cualquier material público debe decirlo así.

---

## 3. Arquitectura objetivo

```
                        ┌─────────────────────────────────────────────┐
   Cliente (apps,       │                NEXUS (control)              │
   agentes, la fábrica  │                                             │
   de novelas, juegos)  │  Gateway API ──► Router/Scheduler           │
        │               │      │              │  ▲                    │
        │  HTTPS        │      │              │  │ heartbeats,        │
        └──────────────►│      │              │  │ recibos firmados   │
                        │      ▼              ▼  │                    │
                        │  Registro de    Registro/Marketplace        │
                        │  nodos (stake   de .nram (manifiestos +     │
                        │  on-chain)      hashes, IPFS en H3)         │
                        │      │              │                       │
                        │  Medición y liquidación (ledger H0-H1,      │
                        │  escrow en Base Sepolia desde H1)           │
                        └──────┬──────────────┬──────────────┬────────┘
                               │ trabajo      │ trabajo      │ trabajo
                               ▼              ▼              ▼
                        ┌────────────┐ ┌────────────┐ ┌────────────┐
                        │ Nodo       │ │ Nodo       │ │ Nodo       │
                        │ Atenhea    │ │ Atenhea    │ │ Atenhea    │
                        │ (worker)   │ │ (worker)   │ │ (worker)   │
                        │            │ │            │ │            │ │
                        │ Gemma E2B  │ │ Gemma E2B  │ │ Gemma E2B  │
                        │ + .nram    │ │ + .nram    │ │ + .nram    │
                        │ CHL local  │ │ CHL local  │ │ CHL local  │
                        │ (privada)  │ │ (privada)  │ │ (privada)  │
                        └────────────┘ └────────────┘ └────────────┘
```

### 3.1 Componentes

**Gateway NEXUS** — reutiliza `nexus/api/core/api_server.py`. Expone hacia el cliente la misma API que Atenhea (`/v1/chat/completions`, `/v1/responses`, `/v1/messages`) para que cualquier cliente OpenAI-compatible funcione sin cambios, añadiendo cabeceras de red (`X-Nexus-Job-Id`).

**Router/Scheduler (nuevo)** — módulo `nexus/router/` en NEXUS. Mantiene la tabla de nodos vivos (rol, modelos y `.nram` disponibles, reputación, cola, región) a partir de `node_roles.py` y de los *heartbeats*. Política de enrutado H0-H1: nodo con reputación ≥ umbral, que tenga el `.nram` pedido, con la cola más corta. Sin optimización prematura.

**Worker Atenhea — modo `--worker` (nuevo)** — ver §5.2.

**Registro de nodos** — el stake vive en `NexusStaking` (testnet). El estado operativo (IP, puerto, capacidad, última vez visto) vive off-chain en el Router en H0-H2 y pasa a descubrimiento libp2p en H3 (§6).

**Registro/Marketplace de `.nram` (nuevo)** — implementa por fin `marketplace_contract.py` (lógica off-chain en H0-H2; registro on-chain de manifiestos en H2). Cada entrada: manifiesto del `.nram` + `tensor_sha256` + autor + precio por uso + estadísticas. El binario se distribuye por descarga directa firmada en H0-H2 y por IPFS en H3, siempre verificando el hash antes de cargarlo.

**Medición y liquidación** — ver §7 y §8.

---

## 4. Qué se hace con cada pieza existente

| Pieza existente | Destino en la fusión |
|---|---|
| Atenhea `onram.py` / `native_runtime.py` | Worker sin cambios en el motor; se añade modo worker (§5.2) |
| Atenhea endpoints `*_tokens` | Fuente de medición de entrada; la salida se cuenta del stream SSE y se contrasta |
| `.nram` + `nram_container.py` | Unidad de comercio de la red; su `tensor_sha256` es la identidad del activo |
| Microexpertos + microentrenamiento | Producto del marketplace: un nodo entrena, publica, cobra regalías por uso |
| Memoria CHL de Atenhea | **No se fusiona.** Queda local (principio 2). NEXUS no sincroniza memoria de usuarios |
| NEXUS `knowledge/` + `shard_manager.py` | Se reconvierte en índice distribuido de manifiestos `.nram` (sharding por embedding = búsqueda semántica de expertos) |
| NEXUS `sync/` (graph/knowledge sync) | Se descarta para memoria; se reutiliza el patrón para sincronizar el índice de `.nram` en H3 |
| NEXUS `llm/dynamic_model.py` | Se sustituye por el Router: el «cliente LLM» de NEXUS pasa a ser la propia red |
| NEXUS `reasoning/` (agente) | Cliente interno nº 1 de la red (dogfooding, §10) |
| Contratos `NexusToken` / `NexusStaking` | Base de liquidación y de fianza de nodo, con las correcciones de §9.3 |
| `reputation.py` / `marketplace_contract.py` (0 bytes) | Se escriben de cero según §7 y §8 |

---

## 5. El nodo trabajador (Atenhea en red)

### 5.1 Requisitos de nodo v1

- Mac Apple Silicon, 16 GB RAM mínimo (32 GB recomendado), ~15 GB libres (checkpoint + `.nram` + cachés).
- Atenhea instalada y verificada en local (`atenhea --version`, test de inferencia local OK).
- Fianza en testnet: stake de 1.000 NEX (parámetro heredado de `NexusStaking`) bloqueado 30 días.
- Conectividad: el nodo hace *polling* saliente al Router en H0-H2 (sin abrir puertos en casa del operador; NAT-friendly). Conexión directa/relay libp2p en H3.

### 5.2 Cambios en Atenhea (modo `--worker`)

1. **Arranque separado**: `atenhea worker --nexus <url-router> --node-key <fichero>` junto al servidor actual, sin tocar la ruta local `127.0.0.1:11434` de uso personal.
2. **Autenticación**: cada trabajo llega con un JWT de corta duración firmado por el Router (job id, expiración, `.nram` permitido, `max_tokens`). El worker rechaza cualquier petición sin JWT válido o dirigida a sus endpoints locales de agente.
3. **Tools desactivadas**: en modo worker se ignora el campo `tools` y se responde error si el trabajo lo exige. Sin excepciones.
4. **Aislamiento**: el trabajo remoto no lee ni escribe memoria CHL, no accede al mapa de hechos, no reutiliza la caché de prefijo de sesiones locales (instancia de caché separada).
5. **Cola y límites**: cola FIFO con máximo configurable (defecto 8 trabajos), `max_tokens` por trabajo (defecto 4.096), timeout por trabajo (defecto 300 s). Si la cola está llena, el nodo rechaza y el Router reasigna.
6. **Recibo firmado**: al terminar, el worker emite el recibo de §7 firmado con su clave de nodo (Ed25519) y lo envía al Router junto al resultado.
7. **Heartbeat**: cada 30 s — estado, trabajos en cola, `.nram` instalados (hash), versión. Tres heartbeats perdidos = nodo fuera de rotación.

### 5.3 Segundo tipo de worker (futuro, fuera del MVP)

Worker Linux/CUDA con llama.cpp/vLLM tras la misma interfaz de trabajo/recibo, para nodos sin Mac y para modelos grandes en una fase posterior a esta spec. No se diseña ahora; la interfaz de §6 es el contrato que deberá cumplir.

---

## 6. Protocolo de red

### 6.1 MVP (H0-H2): HTTPS + polling, sin libp2p

Justificación: `p2p_protocol.py` está roto y libp2p en Python es la pieza más frágil del repo. El MVP valida economía y medición, que es lo que decide si el proyecto vive; el transporte se sustituye después sin cambiar trabajos ni recibos.

Mensajes (JSON, firmados donde se indica):

- `NodeAdvert` (nodo → Router, en el registro y cada heartbeat): `node_id` (hash de la clave pública), roles, modelos, lista de `.nram` (hash + versión), capacidad, región aproximada, versión de worker.
- `JobOffer` (Router → nodo, vía polling): trabajo completo (§6.2) + JWT.
- `JobResult` (nodo → Router): `job_id`, salida (o referencia si es batch grande), `usage`, tiempo, recibo firmado.
- `NramPublish` (autor → Registro): manifiesto `.nram`, `tensor_sha256`, precio por uso, licencia de uso elegida por el autor, evaluación de referencia (dataset y métrica declarados).

### 6.2 Trabajo (Job)

```json
{
  "job_id": "job_01K...",
  "kind": "inference",
  "model": "gemma-4-e2b-it",
  "nram": ["sha256:ab12…"],
  "messages": [{"role": "user", "content": "…"}],
  "params": {"temperature": 0.7, "max_tokens": 1024, "stream": true},
  "tools": null,
  "privacy_tier": "standard",
  "max_price_nem": "1250000000000000000",
  "expires_at": "2026-10-20T19:30:00Z"
}
```

### 6.3 Fase H3: libp2p de verdad

Completar en `p2p_protocol.py` los métodos ausentes (`_encode_message`/`_decode_message` con JSON + firma, `_start_peer_discovery` con mDNS/Kademlia, `_handle_discovery`, `_handle_sync`), manteniendo los protocolos ya declarados (`/nexus/message/1.0.0`, `/nexus/discovery/1.0.0`, `/nexus/sync/1.0.0`). El Router pasa a ser un nodo más (el primero, con rol de bootstrap). Los formatos de §6.1-6.2 no cambian: solo cambia el transporte.

---

## 7. Medición, recibos y verificación

### 7.1 Recibo de trabajo

```json
{
  "job_id": "job_01K...",
  "node_id": "node_7f3…",
  "input_tokens": 812,
  "output_tokens": 1024,
  "nram_used": ["sha256:ab12…"],
  "started_at": "…", "finished_at": "…",
  "output_sha256": "…",
  "price_nem": "…",
  "signature": "ed25519:…"
}
```

- `input_tokens` se obtiene del endpoint de conteo de Atenhea antes de generar; `output_tokens` se cuenta sobre los tokens emitidos en el stream. Discrepancia >1 % entre lo que declara el nodo y lo que observa el Gateway (que reenvía el stream al cliente) = recibo rechazado.
- El Gateway es quien entrega la salida al cliente: el nodo no puede inflar tokens sin que se vea.

### 7.2 Verificación de honestidad (sin zkML)

1. **Trabajos canario** (1-2 % del tráfico): prompts con salida conocida o verificable (clasificación, extracción, preguntas cerradas) inyectados por el Router sin marcar. Fallar canarios degrada reputación; fallar 3 en 24 h = expulsión temporal.
2. **Doble ejecución por muestreo** (2 % de trabajos normales, con `temperature=0`): un segundo nodo repite el trabajo; se comparan los primeros 64 tokens y el hash de salida. Divergencia = disputa.
3. **Disputas**: se resuelven con el consenso Proof-of-Knowledge ya diseñado en NEXUS (votos firmados de nodos validadores). El perdedor sufre slash del 10 % de su fianza (parámetro heredado de `NexusStaking`) y la parte contraria se compensa desde ahí.
4. **Reputación**: se escribe por fin `reputation.py` (0-1, decae con el tiempo, sube con trabajos verificados, baja con disputas perdidas y canarios fallados). El Router no asigna trabajos con precio alto a reputación < 0,8.

Limitación declarada: con muestreo generativo no determinista no hay prueba absoluta de que un nodo ejecutó el modelo «de verdad» en el 100 % de los trabajos. El sistema es económico-estadístico: mentir sale caro en esperanza matemática. Es el mismo compromiso que acepta Petals en su diseño.

---

## 8. Economía NEX v2

### 8.1 Reparto de cada pago (sustituye a las tarifas fijas de `reward_system.py`)

De cada pago de un cliente por un trabajo:

| Destino | % | Nota |
|---|---|---|
| Nodo que ejecutó | 75 % | su ingreso principal |
| Autor del `.nram` usado | 10 % | regalía; si no se usó `.nram`, suma al nodo (85 %) |
| Pool de verificación | 5 % | paga canarios, dobles ejecuciones y validadores de disputas |
| Quema | 5 % | deflación atada a uso real |
| Tesoro del protocolo | 5 % | desarrollo; con multisig y contabilidad pública |

### 8.2 Distribución inicial: heredada y corregida

La que trae el código de NEXUS (`initial_distribution.py`): ecosistema 25 %, equipo 15 % (cliff 1 año, vesting 3 años mensual), venta pública 10 %, liquidez 5 %, recompensas comunidad 20 %, incentivos de red 25 %.

Correcciones de esta spec:

- **Venta pública 10 % → eliminada** (una oferta pública en España exige libro blanco MiCA notificado a la CNMV; y contradice el principio «0 € de inversión» para la comunidad inicial). Ese 10 % pasa a incentivos de red (35 %).
- Equipo 15 %: se mantiene vesting, pero el cliff pasa a empezar en el lanzamiento de mainnet, no antes.
- El fondo de ecosistema (25 %, cliff 180 días, vesting 5 años trimestral) se mantiene.

### 8.3 Emisión: de inflacionaria a atada a ingresos

El código heredado emite 5 % anual base ajustable hasta 15 % según utilización/demanda (`emission_schedule.py`). Eso replica el error de Bittensor (emisiones muy por encima de los ingresos reales).

Regla v2: la emisión de incentivos en un periodo **nunca supera el 100 % de los ingresos por pagos del periodo anterior** (matching 1:1 como máximo) y decrece un 25 % cada año hasta 0 en el año 5. El suelo del 1 % y el techo del 15 % del diseño original quedan derogados. `max_supply` fijo y público desde el despliegue del contrato.

### 8.4 Economía unitaria honesta (la prueba de realidad)

Referencia de mercado (2026-10-20): Gemma 3 4B servido en OpenRouter cuesta 0,05 $/M tokens de entrada y 0,10 $/M de salida.

- Un nodo Atenhea generando de forma sostenida a un ritmo supuesto de 20 tok/s, 24 h al día, produce ~1,73 M tokens de salida/día → **~0,17 $/día brutos** al precio de referencia, ~0,13 $/día para el nodo con el reparto de §8.1. **Conclusión: vender inferencia E2B por token no paga ni la electricidad de forma atractiva.**
- Por tanto el precio de la red **no** se fija por token commodity. Se fija **por tarea** en los productos donde hay valor:
  - *Tareas con experto* (`.nram` especializado: resumir con un estilo, extraer datos de un formato, clasificar un dominio): precio por trabajo cerrado (p. ej. 0,01-0,05 $ equivalentes), del que la regalía del autor es el negocio escalable — un buen experto usado por 100 nodos paga a su autor sin cómputo propio.
  - *Batch con prima de privacidad/localidad*: clientes que no quieren enviar sus documentos a una nube de EE. UU. pagan sobreprecio declarado.
  - *Dogfooding interno* (§10): la fábrica de novelas y los juegos pagan a la red a precio interno; es demanda real desde el día 1 y el primer benchmark honesto de coste.
- La inferencia por token queda como modo «grano fino» para agentes, con precio de referencia = paridad con OpenRouter, asumiendo margen ~0: sirve para atraer uso y datos de fiabilidad, no como fuente de beneficio inicial.

### 8.5 Fianza y reputación (parámetros v1)

- Fianza de nodo: 1.000 NEX en testnet (heredado). En mainnet se redenominará para que equivalga a ~50-100 $ al precio de lanzamiento: la fianza debe doler si te expulsan, pero no excluir a un usuario con un Mac.
- Bloqueo al salir: 30 días (heredado), para que un nodo no pueda hacer daño y huir con la fianza.
- Slash: 10 % por disputa perdida (heredado), 100 % y expulsión si se detecta suplantación de identidad de nodo.

---

## 9. Seguridad y privacidad

### 9.1 Amenazas y mitigaciones

| Amenaza | Mitigación |
|---|---|
| Nodo devuelve texto inventado sin ejecutar el modelo | Canarios + doble ejecución + reputación + slash (§7.2) |
| Nodo infla el conteo de tokens | El Gateway observa el stream; contraste con endpoints de conteo (§7.1) |
| Cliente ataca el equipo del nodo (prompt que pide tools/ficheros) | Modo worker sin tools, sin memoria, sin acceso a rutas locales (§5.2) |
| El nodo lee los prompts del cliente | **No hay mitigación criptográfica en v1**: el nodo ve el prompt en claro. Se declara. `privacy_tier: trusted` enruta solo a nodos propios/de confianza; la mitigación real (inferencia partida por capas) es trabajo posterior a esta spec |
| Sybil (muchos nodos falsos de un mismo operador) | Fianza por nodo + reputación que tarda en construirse + límites por clave/ASN en el Router |
| `.nram` malicioso (tensores que degradan el modelo o payload en el manifiesto) | Verificación de hash, carga con Safetensors (sin `pickle`), evaluación canario del experto antes de listar en el marketplace, firma del autor y reputación de autor separada |
| Robo de fianza/fondos por bug de contrato | Contratos mínimos, auditoría externa antes de mainnet (puerta H4), fondos de clientes en escrow con reembolso por timeout |

### 9.2 Privacidad

- CHL y el mapa de hechos **nunca** salen del dispositivo (principio 2) y los trabajos remotos no los tocan (§5.2.4).
- El Router registra metadatos de trabajos (ids, conteos, hashes), no el contenido, salvo que el cliente lo consienta para depuración. Retención por defecto: 30 días.
- Región: el `NodeAdvert` declara región aproximada; el cliente puede exigir `region: EU` en el trabajo.

### 9.3 Correcciones mínimas a los contratos heredados

- `NexusToken`: añadir tope de fee en `registerServiceProvider`, evento y límite en `payForService`, `Pausable`, y prohibir que el fee deje el neto en ≤0.
- `NexusStaking`: permitir fianzas diferenciadas por rol (usa `node_roles.py`), y que el slash solo lo pueda ejecutar el módulo de disputas, no el owner.
- Nuevo `InferenceEscrow`: depósito del cliente, liberación contra recibo válido (§7.1), reembolso automático si el trabajo expira sin resultado.
- Nuevo `NramRegistry`: ancla on-chain de `tensor_sha256` → autor → precio. El binario vive fuera de la cadena.

---

## 10. Demanda inicial (dogfooding)

La red nace con clientes propios, en este orden:

1. **Fábrica de novelas**: resúmenes, fichas de personajes, control de continuidad y borradores batch — trabajo asíncrono, tolerante a latencia, medible en coste por libro. Es el benchmark de la puerta H1.
2. **Serie TikTok «Martes de lluvia»**: guiones y variantes batch.
3. **Fábrica de juegos Android**: textos, descripciones y localizaciones batch.
4. **Agente de razonamiento de NEXUS** (`nexus/reasoning/`): pasa a consumir la red en vez de APIs externas.

Ningún cliente externo se promete hasta superar la puerta H2.

---

## 11. Hoja de ruta por hitos, con puertas

### H0 — Integración en un solo equipo (sin red, sin cadena)
Router mínimo + Atenhea en el Mac de David. Ledger local (SQLite). Recibos firmados.
**Puerta:** 100 trabajos batch reales de la fábrica de novelas completados; el conteo del ledger coincide con los endpoints de Atenhea en ≥99 %; coste interno por 1M de tokens calculado y anotado.
**Kill:** si el coste/tiempo por trabajo resulta >2× el de la vía actual (APIs) sin ventaja compensatoria, se para y se replantea el posicionamiento antes de seguir.

### H1 — Dos nodos + liquidación testnet
Segundo nodo (VM con worker CPU para pruebas funcionales, lento pero válido; o segundo Mac). Escrow en Base Sepolia, fianzas testnet, canarios y doble ejecución activos.
**Puerta:** liquidación de 7 días de trabajos sin intervención manual; una disputa provocada a propósito se resuelve con slash correcto.
**Kill:** tasa de falsos positivos de verificación >5 % (castigaríamos a nodos honestos: inaceptable).

### H2 — Marketplace de `.nram`
Publicar, descargar con verificación de hash, usar y cobrar regalía, todo en testnet. Primer experto «de autor» entrenado con el microentrenamiento de Atenhea y usado por otro nodo.
**Puerta:** un `.nram` creado en el nodo A produce salidas verificadas en el nodo B y su autor recibe la regalía del §8.1 en el ledger/escrow.
**Kill:** si ningún experto supera al modelo base en su tarea de referencia (evaluación ciega con el set de validación de Atenhea), el marketplace no tiene producto: se pausa H3 y se trabaja en calidad de expertos.

### H3 — Red abierta en testnet
Libp2p completado (§6.3), registro sin permiso (con fianza), objetivo 5-10 nodos externos, índice de `.nram` sincronizado.
**Puerta:** 7 días con ≥5 nodos ajenos, ≥95 % de trabajos completados sin reintento, y ningún incidente de seguridad del tipo §9.1.

### H4 — Decisión de mainnet (puerta separada, no automática)
Requisitos previos **todos**: auditoría de contratos, revisión legal MiCA para la emisión y la publicidad en España, libro blanco si procede, y una métrica de ingresos de testnet/dogfooding que sostenga el §8.4 con números propios. Sin esto, el proyecto se queda en testnet pública como producto de investigación — que también es un resultado presentable en un portfolio.

---

## 12. Trabajo concreto por repositorio

### En Atenhea (`4T3NH34`)
- `onram_cli.py` / lanzador: subcomando `worker` (§5.2.1) y gestión de clave de nodo.
- Nuevo `worker_mode.py`: validación JWT, cola, límites, aislamiento de memoria/caché, emisión de recibos firmados, heartbeat.
- Tests nuevos siguiendo el patrón existente (`test_worker_mode.py`, `test_job_receipt.py`): sin tools, sin CHL, recibo válido, rechazo sin JWT.

### En NEXUS
- Nuevo `nexus/router/` (scheduler, tabla de nodos, política de enrutado).
- `nexus/api/`: el Gateway expone la API compatible y reenvía el stream observando la medición.
- Escribir `reputation.py` (§7.2.4) y la lógica de marketplace que dará nombre a `marketplace_contract.py`.
- Sustituir `nexus/llm/dynamic_model.py` por un cliente que habla con el Router.
- Completar `p2p_protocol.py` solo en H3 (§6.3), no antes.
- Contratos: correcciones de §9.3 + `InferenceEscrow` + `NramRegistry`, con tests en `test/` siguiendo `ContractSecurity.t.sol`.

### Infraestructura (coste 0 €)
Mac de David = nodo 1 y banco de pruebas. La VM actual = Router/Gateway y ledger. Base Sepolia = cadena de pruebas (faucets gratuitos). Oracle Cloud Always Free (cuando esté la instancia) = nodo público de referencia en H3.

---

## 13. Decisiones abiertas para David (con recomendación)

1. **Cadena de liquidación** — Recomendación: **Base (EVM)**, porque los contratos de NEXUS ya son Solidity/EVM y el coste por liquidación agregada es bajo. Alternativa Solana obligaría a reescribir contratos.
2. **Precio de lanzamiento de tareas con experto** — Recomendación: fijar 3 tareas de referencia con precio cerrado (resumen largo, extracción estructurada, clasificación de dominio) y calibrar tras H0 con el coste real medido, no antes.
3. **¿Nodos de terceros en H1 o solo en H3?** — Recomendación: solo en H3. Antes, la superficie de ataque crece sin aportar validación nueva.
4. **Nombre público** — «NEXUS» es genérico y está muy usado; reservar la decisión para H3 con una comprobación de marcas. El token `NEX` puede colisionar con otros activos: comprobar antes de H4.
5. **Segundo modelo** — Recomendación: no añadir modelos hasta H2 superada. Un modelo, un experto estrella, una demo impecable > un catálogo.

---

## 14. No-objetivos (explícito)

- No competir en chat en tiempo real con APIs centralizadas (la latencia y el precio por token lo impiden, §8.4).
- No entrenar modelos base en la red (solo adaptadores y microexpertos).
- No redistribuir checkpoints de terceros.
- No prometer rentabilidad del token a nadie, en ninguna fase. NEX es un medio de pago y fianza dentro de la red; cualquier comunicación pública debe decir exactamente eso.
- No sincronizar memoria personal entre nodos, nunca.

---

## 15. Fuentes y referencias internas

- Auditorías propias de ambos repos (2026-10-20): conteos, ficheros y defectos citados en §1 salen de la lectura directa del código en los commits indicados.
- Precio de referencia de inferencia: Gemma 3 4B en OpenRouter, 0,05 $/M entrada y 0,10 $/M salida (consultado 2026-10-20).
- Diseño de referencia para inferencia P2P por capas y verificación económica con depósito y hashes: paper de Petals (Borzunov et al.). Nuestro MVP evita el sharding por capas; queda como opción posterior para modelos grandes.
- Marco legal de referencia: Reglamento MiCA (UE) 2023/1114 y comunicaciones de la CNMV sobre emisiones de criptoactivos en España (libro blanco y notificación previa). No es asesoramiento legal: H4 exige revisión profesional.
