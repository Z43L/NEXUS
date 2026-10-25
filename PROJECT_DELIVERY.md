# Plan de entrega — NEXUS × Atenhea

Objetivo: convertir el monorepo en un producto end-to-end reproducible, seguro y mantenible. La entrega se divide en verticales con puertas explícitas; no se considerará completo por tener módulos o manifiestos presentes.

## Estado de ejecución

### M0 — Gateway local H0 ✅

- [x] Persistir y devolver el texto de salida producido por el worker.
- [x] Exponer `POST /v1/chat/completions` para inferencia local no streaming.
- [x] Validar el modelo anunciado por el nodo al despachar.
- [x] Resolver el modelo pedido por cada trabajo, rechazar modelos no disponibles y comparar el modelo firmado del receipt con el solicitado (incluyendo alias `:latest`).
- [x] Rechazar recibos con identidad, hash, precio, reparto o discrepancia incorrectos.
- [x] Vincular `receipt.nram_used` a los autores NRAM persistidos en el trabajo y rechazar firmas válidas con autorías alteradas.
- [x] Proteger aceptación/rechazo de resultado con token de despacho y exigir que el nodo esté registrado.
- [x] Probar respuesta directa del gateway y formato básico OpenAI.
- [x] Limitar tamaño de cuerpo, mensajes y tokens; validar temperatura y capar la cola activa.
- [x] Limitar los chats síncronos y reservar handlers para polling/resultados de workers; responder 503/Retry-After al exceder capacidad.
- [x] Reintentar fallos de Atenhea clasificados como transitorios (red, timeout, HTTP 429/5xx), con máximo de tres despachos; errores permanentes siguen terminales.
- [x] Ejecutar `test_h0.py`: 100/100 trabajos, 100 recibos válidos, discrepancia 0%, tools y autoría NRAM no solicitada rechazadas, firma/replay rechazados, SDK Python, UI proxy, recuperación/failover y dialecto alterno de conteo validados.

**Límite:** el E2E simulado es repetible; además, la puerta H0 real se ejecutó con 100 trabajos y salida limitada a 24 tokens por trabajo. H0 sigue siendo loopback y no un servicio remoto seguro. La corrida real no es un benchmark de salida completa.

### M1 — Seguridad y operación del plano local 🔄

- [x] Quitar credenciales API del YAML activo y exigir variables de entorno en el API general.
- [x] Reemplazar HMAC por JWT Ed25519 consistente con el worker H1, con expiración, audiencia y vínculo a nodo/trabajo.
- [x] Verificar que el ID de nodo corresponde a su clave pública persistente.
- [x] Firmar registro, polling, heartbeat y entrega; rechazar firmas repetidas o caducadas.
- [x] Agregar límites de threads, cola, tamaño, timeout y leases con reintentos/fallo terminal.
- [x] Exponer health/readiness y métricas Prometheus del router; documentar recuperación por lease.
- [x] Documentar procedimiento de backup/restauración de SQLite y custodia separada de claves.
- [x] Crear guía segura de configuración y verificación de credenciales en `NEXUS/nexus/h0/README_H0.md`.
- [x] Añadir fachada FastAPI con auth opcional, credencial upstream separada, rate limit de instancia única y error envelopes preservados.
- [x] Añadir lock de dependencias, regresiones de API/SDK, timeout de transporte > deadline H0 y metadatos instalables del SDK Python.
- [x] Añadir CI para pruebas H0, ambos SDKs, validación/build Compose y E2E en contenedores.
- [ ] Confirmar instalación/build del SDK Python en CI o un entorno con acceso a PyPI; las pruebas pasan, pero `setuptools` no está disponible localmente y DNS a PyPI está bloqueado.
- [ ] Ejecutar CI remoto con el estado actual de los cambios.

### M2 — Worker H1 de dos nodos

- [x] Mantener `nexus-h1-node` dentro del repositorio y eliminar incompatibilidades de autenticación worker/router para la ruta local.
- [x] Implementar modo Router remoto con TLS 1.2+, bind loopback/RFC1918, bearer token, enrolamiento de nodos por token, verificación de CA/SAN en worker y claves/token en ficheros 0600.
- [x] Probar dos workers locales, reparto de trabajos y verificación de recibos con motor simulado; la desconexión/reconexión remota sigue pendiente.
- [x] Ejecutar puerta H0 con Atenhea real y archivar evidencia agregada en `docs/evidence/h0-real-2026-10-25.json`.
- [x] Probar el flujo remoto sobre loopback con TLS temporal: token de cliente, alta válida, rechazo de token/CA incorrectos y restricciones de bind/permisos.
- [x] Añadir retención configurable (30 días por defecto) y purga idempotente de prompt/salida, conservando recibos y metadatos.
- [x] Añadir Compose separado para Router H0 + worker H1, TLS/auth/enrolamiento, tokens locales aleatorios, persistencia y healthchecks; Atenhea se configura como engine externo explícito.
- [x] Corregir la CA ausente del healthcheck Router y hacer que el bootstrap tolere un directorio `data/` preexistente.
- [ ] Ejecutar `docker compose config`, build y runtime de esa ruta en host con Docker/Compose. En este entorno faltan Docker/Podman; solo se validaron YAML, scripts y Python.

**Límite M2:** la corrida real usó el modelo que el motor activo anunció como `athenea-e2b:latest`: 100/100 terminados, 100 recibos válidos, discrepancia 0%, tools rechazadas, 186,5 s y 13,29 tokens/s con el límite de 24 tokens de salida. El ensayo de dos workers sigue siendo simulado/local. No hay archivos de pesos `.gguf`/`.safetensors` en el checkout; no se verificó hash/versión exacta de pesos.

**Límite operativo actual:** la regresión con cuatro handlers demuestra que chats concurrentes no bloquean polling/entrega; no es un benchmark ni prueba de carga. Compose tiene configuración estática comprobada, no ejecución real. El modo H1 entre dos hosts y la rotación/renovación de certificados siguen pendientes.

La suite E2E mock se repitió con éxito: **ALL H0 TESTS PASS**, incluyendo los 100 jobs, SDK Python, UI proxy, replay, failover, rechazo de autor NRAM no solicitado y dos workers. También se ejecutó el launcher completo `run_h0_local.sh` en modo `mock` con puertos y data-dir aislados: `/v1/models` anunció `athenea-e2b`, una petición HTTP atravesó UI → Router → worker → mock y devolvió 200; Ctrl-C cerró los cuatro procesos. La prueba generó un ledger y claves locales en `/private/tmp/nexus-h0-launcher-e2e-20261025`, que permanecen ahí.

Tras implementar TLS/auth/enrolamiento y retención, se ejecutaron ambas puertas con permisos de bind loopback: **ALL H0 TESTS PASS** y **ALL SECURE REMOTE TESTS PASS**. La prueba segura creó certificados temporales, confirmó TLS/hostname, rechazó CA y credenciales inválidas, validó alta de nodo y purga/migración de contenido. Es una prueba de integración local: no acredita conectividad entre dos redes ni operación remota.

Con el motor Atenhea ya activo, se repitió `run_h0_local.sh` en modo `real`: el launcher reutilizó el engine en vez de iniciar un duplicado; una consulta desde la consola completó por Router/worker y devolvió HTTP 200 (`athenea-e2b:latest`, 109 tokens de entrada, 2 de salida, 1,36 s). Al parar, Router/worker/UI cerraron y Atenhea siguió respondiendo. Evidencia agregada en `docs/evidence/h0-real-2026-10-25.json`.

### M3 — Cliente e interfaces

- [x] Elegir `/v1/chat/completions` y `/v1/models` como contrato local canónico y alinear SDK Python/JS y chat React con él.
- [x] Compilar SDK TypeScript con `npm run build` (TypeScript strict, salida exit 0).
- [x] Verificar UI loopback por HTTP → `/v1/models` y `/v1/chat/completions` dentro de la suite E2E.
- [x] Convertir la API FastAPI heredada en fachada HTTP hacia H0, manteniendo `/cognitive/query` y `/cognitive/infer` como compatibilidad.
- [x] Añadir `NEXUS/nexus/api/run_h0_api.sh` y dependencias mínimas con versiones directas fijadas; listener y upstream quedan limitados a loopback.
- [x] Generar lock transitivo pip-compatible con hashes (`requirements-h0.lock`) e instalarlo con `--require-hashes`.
- [x] Arrancar FastAPI/Uvicorn reales y probar `/ready`, `/v1/models`, `/v1/chat/completions` y `/cognitive/infer` sobre la ruta API → Router → worker → mock.
- [x] Ejecutar los launchers `run_h0_local.sh` + `run_h0_api.sh` juntos; comprobar UI/API loopback y chat atravesando el worker.
- [ ] Alinear/arreglar dashboard Flask; no es aún una app empaquetada ni auth client.
- [ ] Implementar claves de cliente, cuotas, errores/documentación OpenAPI y política de streaming.
- [ ] Mantener el backend cognitivo heredado fuera de la ruta crítica hasta que pase pruebas funcionales.

**Límite M3:** el SDK TypeScript compiló. La API FastAPI/Uvicorn se instaló en un entorno temporal y pasó smoke funcional conectado al Router/worker/mock; la prueba cubrió readiness, modelos, chat y compatibilidad cognitiva. La instalación del lock con hashes se verificó con `uv pip install --require-hashes`; el launcher de la API sigue siendo local y requiere un Router H0 activo alcanzable mediante `NEXUS_H0_ROUTER_URL`. El Compose heredado no incluye Router/worker H0. El lock fija hashes de todas las dependencias para instalación reproducible.

### M4 — Contratos/economía y despliegue

- [x] Elegir Base EVM conforme a la especificación; aislar el nuevo vertical de los contratos heredados duplicados.
- [x] Compilar y probar el escrow aislado con Solidity 0.8.24; revisar los invariantes básicos de reparto, depósito y retiro en pruebas locales.
- [x] Conectar de forma offline los receipts H0 verificados con el batch builder, exigiendo mapping EVM y política de precio explícitos.
- [x] Integrar Router/worker/mock → recibos H0 verificados → batch → deploy/fund/publish/`claimMany` en Anvil local y comprobar balances/conservación.
- [ ] Implementar liquidación de lotes en testnet con pruebas verificables; el ledger local no se cuenta como pago.
- [ ] Reconstruir CI, imagen, Compose y chart Kubernetes desde manifiestos reproducibles.

**Inspección técnica M4 (25-10-2026):** `docs/spec-fusion-nexus-atenea.md` §§9 y 11 recomiendan Base EVM y especifican Base Sepolia para H1; §13 recomienda Base frente a alternativas. Se toma esa decisión como base del trabajo. Para evitar que los contratos heredados duplicados se confundan con una implementación viva, se creó el subproyecto aislado `NEXUS/settlement-evm/` sin modificarlos.

El subproyecto incluye `InferenceEscrow.sol`, proyecto Foundry fijado a Solidity 0.8.24 y pruebas de conservación/reparto, regalía vacante, redondeo, `claimMany`, pruebas Merkle-sum inválidas, replay entre batches, autorización del firmante, límites de depósito/deadline, cancelación, tokens con fee, decimales, overflow y devoluciones. El contrato utiliza hojas V2 con dominio, chainId, dirección de escrow, token y datos de trabajo; las pruebas rechazan pruebas válidas al cambiar la cadena, escrow o token. El constructor comprueba los decimales del token. Resultado actual: **Solc 0.8.24 compila y Foundry pasa 19/19 pruebas**. Se añadió la dependencia H0 `cryptography==50.0.2` al workflow y se fijó Foundry v1.8.6. Foundry ejecutado en este entorno, pero GitHub Actions aún no se ha lanzado.

El nuevo camino usa un firmante de gateway confiable que publica una raíz Merkle-sum de recibos ya verificados fuera de cadena. El contrato no verifica las firmas Ed25519 de workers de la especificación; el firmante asume esa responsabilidad y puede designar beneficiarios falsos dentro del depósito. La base SQLite local, incluyendo la tabla de claves públicas registradas y `verified=1`, forma parte de la frontera privilegiada: el bridge vuelve a verificar firmas pero no puede demostrar que un administrador no haya sustituido conjuntamente la clave, el recibo y la firma. La protección de replay de `jobId` es global dentro de una instancia escrow, y las hojas V2 quedan ligadas a la cadena, instancia y token. El bridge exige esos tres campos y el E2E los toma de los contratos recién desplegados en Anvil antes de producir la raíz. La política USD/token sigue siendo explícita y responsabilidad operativa. El contrato divide el total convertido en unidades mínimas del token; los `shares` H0 firmados se expresan en micro-USD y pueden diferir de los pagos EVM a una granularidad inferior a un micro-USD. El máximo de claim window es parámetro de despliegue que aún debe fijarse. El “burn” se transfiere a `0x...dEaD`, no reduce supply ERC-20. Estos límites están documentados junto al contrato y requieren integración/auditoría antes de Base Sepolia.

Foundry también imprime avisos estáticos durante `forge script`: detección conservadora de reentrada alrededor de llamadas ERC-20, igualdad de balances para rechazar tokens no estándar, llamadas/tipos de revert dentro del bucle de claims, comparaciones de deadline con `block.timestamp` y división previa a multiplicación. Las rutas con transferencias tienen `nonReentrant` y efectos antes de interacciones; los balances exactos, el deadline y la aritmética por componentes son intencionales. Estos avisos no equivalen a una auditoría y deben revisarse de nuevo con el token y el diseño de producción elegidos.

Los contratos heredados no forman un conjunto EVM canónico seleccionable sin más trabajo:

- `NEXUS/contracts/NexusToken.sol` y `NEXUS/contracts/phase3_deployment.sol` declaran ambos `NexusToken`; `Staking.sol` y `StakingSystem.sol` declaran ambos `NexusStaking`; `Governance.sol` y `GovernanceSystem.sol` declaran ambos `NexusGovernance`.
- `NEXUS/test/ContractSecurity.t.sol` importa `../src/NexusToken.sol` y `../src/StakingSystem.sol`, rutas que no existen desde `NEXUS/test/`; espera `new NexusToken(uint256)` y `StakingSystem`, mientras los contratos candidatos visibles ofrecen constructores/nombres diferentes. La prueba no constituye evidencia de compilación ni seguridad.
- Aun si se aísla un contrato, hay bloqueos de compilación visibles: `Staking.sol` contiene `else:`; `Governance.sol` llama `_executeProposalLogic` sin definición; `VoteDelegation.sol` usa `IERC20` y `nexusToken` sin declararlos. Varias dependencias de OpenZeppelin no están vendorizadas.
- En la ruta Substrate, `NEXUS/nexus-blockchain` solo contiene los archivos fuente runtime/node/pallet listados, sin manifests; el runtime referencia `Runtime` y tipos/configuración no definidos y el pallet tiene traits/helpers sin implementar.

Se añadió `NEXUS/settlement-evm/batch_builder.py`, herramienta Python stdlib para construir ABI estático V2 de nueve palabras (288 bytes), hashes Ethereum Keccak-256, árboles Merkle-sum y pruebas. Rechaza contexto ausente/malformado, destinatarios iguales al escrow, IDs duplicados, importes malformados, overflow uint256 y sumas superiores al depósito. Los vectores contrastan Keccak y el layout Solidity. Se ejecutaron 28 pruebas Python (builder, CLI, bridge, contexto de liquidación, precisión sub-microUSD y namespacing de IDs Router-native): **28/28 pasan**.

Se añadió `receipt_to_batch.py`, puente offline/read-only desde SQLite H0. Selecciona solo recibos con `verified=1` y vuelve a verificar firma Ed25519, identidad del nodo, estado del trabajo, NRAM solicitado frente al recibido, pricing, shares y discrepancia. Los IDs H0 `job_000001` se derivan a bytes32 estable con Ethereum Keccak-256 del recibo canónico firmado; el JSON incluye `sourceReceipts` para trazabilidad. Esto evita asumir que IDs secuenciales H0 ya sean bytes32 y reduce colisiones de IDs entre routers. Requiere que el operador provea mapping explícito `node_id`→wallet, identificador NRAM→autor, depósito, relación racional USD/token y contexto chainId/escrow/token; conversiones con redondeo se rechazan. El E2E `e2e_local.py` inicia Router, worker y motor mock como procesos separados, crea dos trabajos H0 y espera recibos verificados en SQLite. Despliega token y escrow de prueba primero, lee sus direcciones del registro Foundry, construye después la raíz ligada a chainId/escrow/token, fondea, publica y ejecuta `claimMany` en Anvil loopback. La pasada verificó balances exactos de nodo/autor, verificación, sink de quema, tesorería y escrow restante cero. Los artefactos Foundry se guardan en el directorio temporal de la corrida. La GitHub Action está configurada para Python, Foundry y el E2E local, pero el estado remoto de Actions no se ha verificado ni ejecutado.

**Acción siguiente:** ejecutar la GitHub Action; probar Compose con Docker; preparar snapshot real de ledger y policy con mappings revisados; completar revisión independiente antes de cualquier testnet. Definir disputas, direcciones receptoras y máximo claim window. No se ha desplegado ni probado ninguna transacción en Base o Base Sepolia.

### M5 — Lanzamiento controlado

- [ ] Revisar seguridad, claves y privacidad; comprobar aislamiento de prompts/resultados/memoria.
- [ ] Medir disponibilidad, latencia, capacidad, costes y márgenes antes de ampliar nodos.
- [ ] Completar revisión legal/económica antes de cualquier mainnet, token público o beta abierta.

## Decisiones vigentes

- La ruta prioritaria es Atenhea worker + router/gateway NEXUS; los módulos heredados no se consideran integrados hasta demostrarlo.
- H0 permanece local. No abrir puertos ni desplegar públicamente la implementación actual.
- No guardar credenciales en Git. Variables esperadas por el backend general: `OPENROUTER_API_KEY`, `OPENAI_API_KEY` y, si el almacenamiento lo requiere, `MEMORY_API_KEY`.
- La clave OpenRouter literal detectada en commit público `8445b54` se considera comprometida hasta su rotación en el proveedor y la coordinación de la limpieza del historial. El checkout actual usa variable de entorno; no se ha efectuado rotación externa.
- No declarar liquidación NEX, blockchain funcional ni despliegue productivo mientras M4 no pase sus puertas.
