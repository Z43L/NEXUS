# Hoja ejecutiva — NEXUS × Atenhea

**Fecha de análisis:** 25 de octubre de 2026
**Repositorio analizado:** `NEXUS/`, rama local `codex/nexus-e2e-functional`, commit `36805c5` (derivada de `main` en `ed1a9f5`)
**Alcance:** documentación, estructura, rutas de ejecución/configuración y código de integración H0; análisis complementario de backend, cadena/economía, interfaz y operaciones.

## Resumen para dirección

NEXUS × Atenhea pretende ser una red de inferencia distribuida: Atenhea ejecuta localmente el modelo Gemma E2B en cada nodo; NEXUS aporta coordinación, enrutado, medición, reputación, liquidación y, más adelante, marketplace de adaptadores `.nram`. La propuesta separa los pesos base y la memoria privada de cada nodo del trabajo remoto, que debe ejecutarse sin herramientas ni acceso a memoria local.

**Estado real:** H0 funciona en local: router HTTP con ledger SQLite, worker sidecar, recibos Ed25519, medición y clientes. La suite mock pasó 100/100 trabajos y la puerta real pasó 100/100 con Atenhea (`athenea-e2b:latest`) y salida limitada a 24 tokens; evidencia en `docs/evidence/h0-real-2026-10-25.json`. Esta revisión corrige límites de concurrencia del Router, validación de modelo, timeouts y errores de SDK, y añade una ruta Compose H0/H1. No se ha demostrado H1 entre máquinas ni liquidación testnet, H2 marketplace o H3/H4 públicos.

**Lectura ejecutiva:** el vertical de inferencia H0 y el settlement local simulado forman un camino E2E reproducible en las validaciones previas. Se implementó una configuración H1 con TLS, autenticación y enrolamiento, además de Compose aislado; la prueba de loopback existe, pero Compose no pudo construirse en este entorno y la conexión entre redes no está demostrada. NEXUS no acredita una red descentralizada, pagos/token en producción ni operación pública.

## Producto y arquitectura prevista

| Capa | Responsabilidad | Estado observado |
|---|---|---|
| Atenhea (motor) | Inferencia local Gemma E2B, API compatible OpenAI, adaptadores `.nram`, memoria episódica CHL privada, herramientas locales | Código integrado bajo `NEXUS/atenhea/`; el README describe la ruta principal como macOS/Apple Silicon, MPS/CPU y generación serial. Requiere modelo y dependencias locales. |
| NEXUS (plano de control) | API, descubrimiento/enrutado, medición, recibos, reputación, pagos/gobernanza | Gran cantidad de módulos Python, pero el H0 usa un router independiente pequeño. El protocolo P2P general se documenta roto/incompleto. |
| H0 | Router + worker + motor + ledger local y recibos | Código en `NEXUS/nexus/h0/`; suite E2E con mock. Ledger SQLite, HTTP loopback, JWT Ed25519 y firmas de requests de nodo. Se limita el número de chats síncronos y se reserva capacidad para tráfico del worker. |
| H1 | Segundo nodo y futura liquidación | Worker H1 validado contra el protocolo local; ensayo con dos workers y mock. Hay receta Compose con TLS, autenticación, enrolamiento y persistencia, pero no se ha construido/ejecutado en Docker en esta sesión. No se ha demostrado conectividad entre máquinas ni liquidación en testnet. |
| H2–H4 | `.nram` distribuido/verificado, nodos externos, beta pública | Especificación/diseño, no evidencia de producto desplegado. |

Flujo objetivo: cliente → gateway/router → worker Atenhea → respuesta y recibo firmado → verificación/ledger → futura liquidación agregada. En H0, el router y el worker hacen polling HTTP; no se usa todavía la red P2P declarada ni contratos para liquidar.

## Qué hay en el repositorio

- **Backend Python:** API FastAPI cognitiva, inicialización de componentes, agentes de razonamiento, herramientas, LLM vía conectores, memoria vectorial/distribuida, grafo de conocimiento, seguridad, privacidad, red, consenso, sincronización y gobierno.
- **Atenhea:** runtime nativo, servidor/API, manejo de `.nram`, microexpertos y entrenamiento/evolución, memoria CHL y utilidades. Su documentación limita la inferencia práctica a una generación a la vez por motor y especifica que no es entrada multimodal en la ruta nativa.
- **Blockchain:** 14 contratos Solidity, una implementación Rust/Substrate bajo `nexus-blockchain/` y utilidades Python relacionadas. La presencia de varias implementaciones no demuestra que compartan despliegue o estado.
- **Interfaz/SDK:** dos archivos de interfaz (React y Streamlit) y SDKs mínimos JS/Python.
- **Operación:** Docker Compose, Dockerfile, Terraform para AWS/Kubernetes, manifiestos Kubernetes/Helm, scripts de despliegue y configuración de Prometheus/Grafana.
- **Pruebas:** suites para memoria, seguridad, consenso, P2P, LLM, carga e integración; H0 añade su propio test E2E contra mock. En el trabajo posterior se ejecutó la puerta H0; no se ejecutaron las otras suites.

El código fuera de Atenhea se ve como una colección de subsistemas y prototipos de madurez desigual. La spec de fusión identifica expresamente piezas vacías o esqueletos, entre ellas `marketplace_contract.py`, `reputation.py`, `asset_types.py`, ciertos contratos, recompensas fijas y P2P con métodos faltantes. Esto debe tomarse como inventario de diseño hasta validar módulo por módulo.

### Backend general: flujo no operativo de extremo a extremo

La API FastAPI se convirtió en una fachada al gateway H0 y dejó de inicializar el stack heredado de AGE/Weaviate/ReAct. Expone `/v1/chat/completions` y `/v1/models` y adapta `/cognitive/query` y `/cognitive/infer`. Se instaló FastAPI/Uvicorn con un lock pip compatible y hashes; la prueba funcional real conectó la fachada al Router, worker y mock y verificó readiness, descubrimiento de modelos, chat y `/cognitive/infer`. El launcher limita la escucha y el upstream a loopback; la fachada sigue dependiendo de un Router H0 activo. Las capacidades heredadas de memoria/grafo siguen fuera de la ruta funcional: agentes llaman métodos de memoria inexistentes, la consulta del grafo es un stub y hay APIs Weaviate incompatibles.

Los SDKs Python y TypeScript y una nueva consola web local comparten el contrato `/v1/chat/completions`. El SDK TypeScript compiló y la suite E2E ejercita el SDK Python y el proxy UI. El dashboard Flask heredado, la carga de conocimiento y streaming siguen fuera del contrato H0.

La fachada FastAPI tiene auth opcional por bearer/API key, token separado para el upstream y rate limiting de proceso único. Los SDK ahora validan el deadline H0, amplían el timeout HTTP diez segundos y conservan `job_id`/mensaje de errores FastAPI. Python incluye metadatos de paquete; sus pruebas pasan, aunque la instalación real no se pudo completar por DNS en esta sesión. Esta auth protege la fachada; no cambia que el Router H0 local no autentica clientes.

## H0: funcionamiento observado

1. `router.py` mantiene nodos, trabajos, recibos y estados en SQLite; entrega trabajos por polling y calcula discrepancias de medición.
2. `worker_agent.py` pregunta por el modelo del motor Atenhea (`:11436`), calibra el andamiaje de tokens, se registra y solicita trabajos.
3. El worker rechaza trabajos con `tools`, envía la inferencia al endpoint de chat, calcula precio de referencia en micro-USD y firma el recibo con Ed25519.
4. El router verifica firma y JWT de despacho Ed25519, persiste el recibo y expone estado/resumen.
5. `test_h0.py` levanta motor simulado, router y worker; verifica SDK Python, proxy UI, firmas/replay, leases, failover, métricas y dos workers.

El proceso separa el motor (`:11436`) del proxy local de agentes (`:11434`), evitando pasar por el camino que maneja tools/memoria CHL. Sin embargo, la afirmación de aislamiento requiere revisión en el runtime real; el H0 solamente verifica el rechazo de `tools` en el worker.

## Madurez y confianza de afirmaciones

| Afirmación | Evidencia disponible | Confianza |
|---|---|---|
| Atenhea tiene una ruta local de inferencia utilizable | README técnico, runtime y pruebas dedicadas presentes | Media-alta para el entorno indicado; el análisis no ejecutó el entorno ni verificó el modelo. |
| H0 completa trabajos y verifica recibos con mock | Suite E2E: 100/100 jobs, recibos, discrepancia 0%; SDK, UI proxy, replay, failover y dos workers | Alta en integración local. |
| H0 ejecuta el lote con motor Atenhea real | Puerta real: 100/100 jobs, 100 recibos válidos, discrepancia 0%, tools rechazadas; 24 tokens máximos/job | Alta para el flujo probado; no es benchmark completo ni confirma hash de pesos. |
| H1 remoto es seguro y operable entre redes | Modo TLS/auth/enrolamiento probado sobre loopback con certificados temporales | Seguridad de configuración comprobada localmente; conectividad, renovación de certificados y operación entre redes no demostradas. |
| P2P, tokenómica y marketplace operan integrados | Diseño y módulos existentes, con numerosos esqueletos/incompletos documentados | No demostrado. |
| Existe una ruta local integrada de liquidación EVM | Escrow V2 compila con Solc 0.8.24; 19/19 pruebas Foundry y 25/25 pruebas Python pasan. El E2E Anvil ejecuta Router, worker y motor mock, verifica dos recibos del ledger SQLite, despliega primero token/escrow, genera una raíz ligada a chainId y direcciones reales y liquida dos reclamaciones | Alta para la integración local simulada. No representa liquidación con ledger de producción, token real ni testnet. |
| El Router conserva capacidad de worker con chats concurrentes | Regresión con `--max-threads 4`: tres chats esperan; chat adicional recibe 503/Retry-After y un worker hace polling y envía resultado; suite H0 pasa tras los cambios de modelo | Alta para el escenario local cubierto; no es benchmark de carga. |
| Compose H0/H1 es desplegable | Se corrigió la CA ausente en healthcheck y el bootstrap con `data/` existente; CI ahora configura, construye y arranca Compose para un chat Router → worker → mock, pero no se ha ejecutado | Parcial; falta resultado de CI y runtime Docker real. |
| Sistema listo para clientes/producción | No hay evidencia de despliegue integrado, operación, hardening o métricas operativas | No. |

## Riesgos principales

1. **Superficie expuesta y autenticación:** el Router local escucha en `127.0.0.1`; el modo remoto restringe bind a loopback/RFC1918, exige TLS 1.2+, token de cliente y enrolamiento, y firma requests de nodo. Hay auth/rate limit en la fachada FastAPI. Faltan ensayo entre redes, construcción/ejecución Compose, renovación de certificados y revisión de proxy/firewall. La consola web sigue en loopback.
2. **Medición y economía no validadas:** H0 calcula un precio de referencia en micro-USD; no representa cobro en NEX ni liquidación on-chain. La calibración de andamiaje documentada es específica del motor y debe comprobarse en ejecución real y ante cambios de versión/modelo.
3. **Madurez heterogénea:** los módulos generales pueden parecer una plataforma completa, pero el flujo H0 no parece apoyarse en la mayor parte de la API, P2P, contratos, gobernanza ni base vectorial.
4. **Credencial expuesta confirmada:** `NEXUS/config/reasoning_agent.yaml` contiene una clave literal de aspecto real en el commit público [`8445b54`](https://github.com/Z43L/NEXUS/commit/8445b54a34fc741b787bf2e5490e85a0d46c5769). El árbol local actual usa `OPENROUTER_API_KEY` desde entorno, pero no rota la clave ni limpia la historia pública. Revocarla/rotarla urgentemente con el proveedor y coordinar limpieza de historia; hasta entonces, tratarla como comprometida.
5. **Despliegue y dependencias:** el Compose heredado usa runtime y dependencias generales de madurez desigual; Weaviate conserva acceso anónimo local. La ruta Compose H0/H1 usa imagen mínima y materiales TLS/tokens locales. Se corrigió la CA requerida por el healthcheck y el bootstrap tolera datos ya existentes. El workflow de CI ahora intenta configuración, build y chat E2E en contenedores; falta ejecutarlo en Actions. Faltan templates Helm y hay referencias heredadas de Terraform/CI a recursos que no aparecen.
6. **Observabilidad no conectada:** Compose anuncia el puerto 9090 para métricas, pero la API no publica un exporter integrado; la config de Prometheus tiene rutas/labels de métricas discordantes y el health check consulta servicios/puertos que no corresponden a Compose/Kubernetes.
7. **Datos y privacidad:** H0 borra prompts y respuestas tras 30 días por defecto (configurable), con `secure_delete` y conserva recibos/metadatos. La purga/migración idempotente se probó; faltan una revisión de copias de seguridad/WAL, pruebas de borrado verificable y auditoría de aislamiento de memoria/logs en Atenhea.
8. **Blockchain/economía:** el escrow aislado compila y pasa pruebas locales; el E2E Anvil consume recibos firmados y comprueba `claimMany` con IDs nativos `job_000001`. El bridge deriva un `bytes32` estable desde el recibo canónico firmado y conserva el ID/router de origen en `sourceReceipts`. Las hojas V2 incluyen dominio, chainId, dirección del escrow, token y datos del trabajo; las pruebas rechazan replay al cambiar cualquiera de los tres parámetros de contexto. El E2E despliega contratos antes de generar el lote y lee las direcciones del registro Foundry. La política USD/token sigue siendo responsabilidad del operador, y el firmante de gateway debe validar identidad, veracidad y elegibilidad de cada recibo antes de publicar una raíz. Contratos Solidity heredados duplicados/incompatibles y runtime Rust/Substrate no son una plataforma funcional. No presentar PoK, staking, gobernanza, tokenómica ni marketplace como operativos.
9. **Concurrencia y fiabilidad:** el Router limita chats síncronos y reserva headroom del pool total para handlers del worker; devuelve 503/Retry-After al saturarse. H0/H1 resuelven el modelo solicitado entre los anunciados y el Router valida el modelo del recibo. El worker pide retry solo ante fallo de red, timeout, HTTP 429 o 5xx; el Router reencola hasta tres despachos sin fabricar un recibo. Los fallos permanentes quedan terminales; todavía no hay backoff y falta validar comportamiento con fallos reales de motor.
10. **Credencial histórica:** una clave de proveedor con aspecto real aparece en el commit público `8445b54`. El YAML actual usa `OPENROUTER_API_KEY` de entorno, pero el valor histórico debe revocarse/rotarse y el historial limpiarse coordinadamente. Esta revisión no puede ejecutar la revocación ni reescritura remota.
9. **Consistencia documental:** README, hoja ejecutiva y plan de entrega ya describen H0 y los límites actuales. La spec de fusión conserva lenguaje histórico («sin código nuevo») pese al H0/H1 implementados; conviene actualizarla como fuente de producto.
10. **Mantenimiento del repositorio:** los archivos del worker H1 están incluidos en los cambios de este checkout, pero todavía deben incorporarse al commit/revisión del proyecto para que estén en clones compartidos. `.DS_Store` queda ignorado.
11. **Capacidad:** un motor Atenhea procesa generaciones en serie; el rendimiento y la economía dependen de añadir nodos, disponibilidad, carga de modelo y memoria local. La capacidad multi-nodo todavía no está acreditada.

## Recomendaciones por orden

### Próximas 1–2 semanas

- Repetir la puerta H0 real con pesos de producción y sin capar la salida; capturar versión/hash del modelo y comparar rendimiento. La evidencia limitada actual está en `docs/evidence/h0-real-2026-10-25.json`.
- Ejecutar un ensayo con dos nodos en redes separadas, rotación de certificados, recuperación tras desconexión y límites medidos; el test de TLS actual usa loopback.
- Revocar/rotar la clave antigua con el proveedor y revisar historial Git/logs; el archivo activo ya usa una variable de entorno.
- Acordar cuál es el servicio de router H1 y demostrar dos nodos en una red de prueba controlada, con jobs y recibos reproducibles; no presentar Base/testnet como liquidación hasta que haya transacciones verificables.
- Incorporar el worker H1 al control de versiones para que sea reproducible desde un clone limpio.

### Siguiente fase

- Consolidar una única ruta de producto: H0/H1 como ruta principal o la API general heredada; marcar explícitamente módulos experimentales, obsoletos o no integrados.
- Ejecutar la GitHub Action; el E2E local de Router→worker→bridge→Anvil ya pasa con motor mock. Después repetir con snapshot controlado de ledger y mappings revisados; completar revisión independiente antes de testnet.
- Definir un contrato de job/receipt versionado y con pruebas de compatibilidad, claves rotables, idempotencia y reglas claras de discrepancia/canarios.
- Reproducir builds: versiones fijadas, imagen base soportada, CI para lint/build/seguridad y pruebas automatizadas. Separar configuración de ejemplo y secretos.
- Validar demanda y márgenes con medición de coste real de cómputo, disponibilidad, verificaciones y gas. Mantener testnet y sin venta/promesa de token hasta revisión legal y económica como dispone la spec.

## Métricas de decisión

- H0 real: 100/100 terminados, 100% de firmas válidas, discrepancia ≤1%, herramientas remotas rechazadas, cero acceso remoto a memoria local.
- H1: al menos dos nodos independientes conectados; jobs completados y recibos verificables; reconexión/reintento y límites medidos; sin exposición de secretos ni tráfico en claro.
- Operación: disponibilidad, latencia p50/p95, tokens/s, tasa de fallo, utilización, coste por 1.000 tokens y coste de verificación.
- Economía: margen neto por job y sostenibilidad del pool de verificación bajo doble ejecución/canarios.

## Archivos clave

- Visión y estado de fusión: `FUSION.md`
- Especificación de arquitectura/hitos: `docs/spec-fusion-nexus-atenea.md`
- Integración H0 y puerta: `NEXUS/nexus/h0/README_H0.md`, `NEXUS/nexus/h0/test_h0.py`
- Router y recibos: `NEXUS/nexus/h0/router.py`, `NEXUS/nexus/h0/nexus_common.py`
- Worker de Atenea: `NEXUS/nexus/h0/worker_agent.py`
- Runtime Atenhea y restricciones: `NEXUS/atenhea/README.md`
- API general: `NEXUS/nexus/api/core/api_server.py`
- Despliegue local: `NEXUS/docker-compose.yml`, `NEXUS/Dockerfile`
- Guía H1 local no rastreada en el commit analizado: `NEXUS/nexus-h1-node/README_MAC_NODE.md`

## Límites de este análisis

El análisis inicial fue estático y documental. Las actualizaciones posteriores ejecutaron la suite H0 mock, la puerta de 100 jobs con motor local, build del SDK TypeScript, smoke de UI, test HTTPS/auth/retención y prueba funcional FastAPI. El escrow V2 compila y pasa 19 pruebas Foundry; el builder y bridge pasan 25 pruebas Python. El E2E integrado inició Router, worker y motor mock, generó recibos `job_000001`/`job_000002` verificados por el Router, desplegó token de prueba y escrow solo en Anvil loopback (chainId 31337), vinculó la raíz a las direcciones desplegadas y completó `claimMany` con saldos exactos; no hubo transacciones en una red pública ni uso de fondos reales. Esta hoja no es una auditoría formal de seguridad ni de contratos.

## Actualización de implementación — 25 de octubre de 2026

Después del análisis se trabajó en la vertical H0. Esta actualización reemplaza las observaciones anteriores sobre entrega de salida y token de despacho:

- El router ahora persiste y devuelve la salida del worker y ofrece `POST /v1/chat/completions` en modo texto/no streaming.
- El despacho usa JWT Ed25519 de 30 minutos ligados al nodo y al trabajo. Las requests de nodo también se firman y protegen contra replay.
- El router valida campos del trabajo y recibo, hash de salida, precio/reparto y discrepancia ≤1%; limita cuerpos, mensajes, longitud de entrada y la cola activa. Vincula `receipt.nram_used` con los autores NRAM persistidos en el trabajo y rechaza firmas válidas con autoría alterada.
- Se retiró la clave literal de `NEXUS/config/reasoning_agent.yaml`; el backend heredado ahora exige `OPENROUTER_API_KEY` de entorno. La clave anterior fue confirmada en el commit público `8445b54`; requiere revocación/rotación en el proveedor y coordinación para limpiar el historial Git.
- `test_h0.py` se ejecutó con el runtime Python del entorno y el mock: 100/100 trabajos, 100/100 recibos, discrepancia máxima 0%, rechazo de tools, firma manipulada rechazada, endpoint de chat y recuperación de resultado correctos, más fallback del contador alterno. Resultado: **ALL H0 TESTS PASS**.

La puerta real fue positiva con salida limitada a 24 tokens por trabajo; no es el benchmark de salida normal. No se encontraron pesos `.gguf`/`.safetensors` en el checkout ni se registró un hash de modelo. H0 local sigue limitado a `127.0.0.1`; los cambios recientes añaden modo remoto seguro, sujeto a ensayo entre redes. La inspección M4 encontró contratos heredados sin ruta compilable y plataformas duplicadas; se eligió Base EVM para el vertical aislado. El estado actual y las puertas pendientes se siguen en [PROJECT_DELIVERY.md](PROJECT_DELIVERY.md).

### Validación final local

Se amplió y volvió a ejecutar `NEXUS/nexus/h0/test_h0.py`: **ALL H0 TESTS PASS**. Además de la puerta de 100 trabajos y las verificaciones criptográficas, se validaron el SDK Python, el proxy same-origin de la consola web, la recuperación por lease y failover, y el reparto de 12 trabajos entre dos procesos H1. El SDK TypeScript compiló con `npm ci` + `npm run build`; se retiraron `node_modules/` y `dist/`, conservando `package-lock.json`.

La consola H0 se sirve solo en loopback y `run_h0_local.sh` levanta Atenhea, Router, worker y UI; se verificó con motor real y mock. FastAPI/Uvicorn se instalaron en runtime temporal con lock hash-verificado y se probó contra Router/worker/mock. En esta revisión pasan la API (6/6), SDK Python (5/5), pruebas Python del builder/bridge (25/25), suite H0 (100/100 trabajos), regresión de concurrencia y TLS/auth/enrolamiento/retención en loopback; el SDK TypeScript pasó build y 4/4 pruebas. El Compose corrigió su montaje CA/healthcheck y bootstrap; el workflow ahora ejecuta configuración, build y chat E2E en contenedores, pero no se ha ejecutado. El escrow V2 pasó 19 pruebas Foundry y el recorrido Router → worker firmado → ledger verificado → bridge → escrow ligado a chain/escrow/token → `claimMany` pasó en Anvil loopback con saldos exactos y escrow vacío. Restan ejecutar CI remoto, probar Compose en Docker, conectar nodos entre redes, revisar seguridad/firmante, validar testnet y rotar la credencial histórica. No se encontraron pesos en este checkout ni transacciones verificadas en testnet.
