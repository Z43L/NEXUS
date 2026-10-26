# Hoja ejecutiva — NEXUS × Atenhea

**Fecha de análisis:** 26 de octubre de 2026
**Repositorio analizado:** `NEXUS/`, rama local `codex/nexus-e2e-functional` (derivada de `main` en `ed1a9f5`; revisión local actual)
**Alcance:** documentación, estructura, rutas de ejecución/configuración y código de integración H0; análisis complementario de backend, cadena/economía, interfaz y operaciones.

## Resumen para dirección

NEXUS × Atenhea pretende ser una red de inferencia distribuida: Atenhea ejecuta localmente el modelo Gemma E2B en cada nodo; NEXUS aporta coordinación, enrutado, medición, reputación, liquidación y, más adelante, marketplace de adaptadores `.nram`. La propuesta separa los pesos base y la memoria privada de cada nodo del trabajo remoto, que debe ejecutarse sin herramientas ni acceso a memoria local.

**Estado real:** H0 funciona en local: router HTTP con ledger SQLite, worker sidecar, recibos Ed25519, medición y clientes. La suite mock pasó 100/100 trabajos y la puerta real pasó 100/100 con Atenhea (`athenea-e2b:latest`) y salida limitada a 24 tokens; evidencia en `docs/evidence/h0-real-2026-10-25.json`. Esta revisión corrige límites de concurrencia del Router, validación de modelo, timeouts y errores de SDK, y añade una ruta Compose H0/H1. No se ha demostrado H1 entre máquinas ni liquidación testnet, H2 marketplace o H3/H4 públicos.

**Lectura ejecutiva:** el vertical de inferencia H0 y el settlement local simulado forman un camino E2E reproducible. El Compose H0 se construyó en ARM64 y ejecutó en Colima: UI same-origin → API autenticada → Router TLS privado → worker → mock autocontenido y también engine Atenhea real local (`athenea-e2b:latest`). Ambas rutas terminaron jobs; la ruta real verificó 401 sin credencial, chat API/UI, token ausente del HTML y `job_000006` en `done`. El catálogo y el gauge ya excluyen workers cuyo heartbeat expiró. Un worker del host también completó un trabajo real por TLS hacia Router Compose en Colima (`job_000008`), con el worker contenedor pausado; esto prueba separación host→VM local, no dos hosts físicos. Siguen pendientes H1 entre redes independientes, CI remoto, pagos/token en producción y operación pública.

## Producto y arquitectura prevista

| Capa | Responsabilidad | Estado observado |
|---|---|---|
| Atenhea (motor) | Inferencia local Gemma E2B, API compatible OpenAI, adaptadores `.nram`, memoria episódica CHL privada, herramientas locales | Código integrado bajo `NEXUS/atenhea/`; el README describe la ruta principal como macOS/Apple Silicon, MPS/CPU y generación serial. Requiere modelo y dependencias locales. |
| NEXUS (plano de control) | API, descubrimiento/enrutado, medición, recibos, reputación, pagos/gobernanza | Gran cantidad de módulos Python, pero el H0 usa un router independiente pequeño. El protocolo P2P general se documenta roto/incompleto. |
| H0 | Router + worker + motor + ledger local y recibos | Código en `NEXUS/nexus/h0/`; suite E2E con mock. Ledger SQLite, HTTP loopback, JWT Ed25519 y firmas de requests de nodo. Se limita el número de chats síncronos y se reserva capacidad para tráfico del worker. |
| H1 | Segundo nodo y futura liquidación | Worker H1 validado contra el protocolo local; ensayo con dos workers y mock. Hay receta Compose con TLS, autenticación, enrolamiento y persistencia, y el Compose se construyó y ejecutó localmente con Colima; no se ha demostrado conectividad entre máquinas ni liquidación en testnet. |
| H2–H4 | `.nram` distribuido/verificado, nodos externos, beta pública | Especificación/diseño, no evidencia de producto desplegado. |

Flujo objetivo: cliente → gateway/router → worker Atenhea → respuesta y recibo firmado → verificación/ledger → futura liquidación agregada. En H0, el router y el worker hacen polling HTTP; no se usa todavía la red P2P declarada ni contratos para liquidar.

## Qué hay en el repositorio

- **Backend Python:** API FastAPI cognitiva, inicialización de componentes, agentes de razonamiento, herramientas, LLM vía conectores, memoria vectorial/distribuida, grafo de conocimiento, seguridad, privacidad, red, consenso, sincronización y gobierno.
- **Atenhea:** runtime nativo, servidor/API, manejo de `.nram`, microexpertos y entrenamiento/evolución, memoria CHL y utilidades. Su documentación limita la inferencia práctica a una generación a la vez por motor y especifica que no es entrada multimodal en la ruta nativa.
- **Blockchain:** 14 contratos Solidity, una implementación Rust/Substrate bajo `nexus-blockchain/` y utilidades Python relacionadas. La presencia de varias implementaciones no demuestra que compartan despliegue o estado.
- **Interfaz/SDK:** dos archivos de interfaz (React y Streamlit) y SDKs mínimos JS/Python.
- **Operación:** Docker Compose, Dockerfile, Terraform para AWS/Kubernetes, manifiestos Kubernetes/Helm, scripts de despliegue y configuración de Prometheus/Grafana.
- **Pruebas:** suites para memoria, seguridad, consenso, P2P, LLM, carga e integración; H0 añade su propio test E2E contra mock. En este trabajo se ejecutaron las puertas H0, integración UI/API y Docker Compose; el resto de suites heredadas no se ejecutó de forma exhaustiva.

El código fuera de Atenhea se ve como una colección de subsistemas y prototipos de madurez desigual. La spec de fusión identifica expresamente piezas vacías o esqueletos, entre ellas `marketplace_contract.py`, `reputation.py`, `asset_types.py`, ciertos contratos, recompensas fijas y P2P con métodos faltantes. Esto debe tomarse como inventario de diseño hasta validar módulo por módulo.

### Backend general: flujo no operativo de extremo a extremo

La API FastAPI se convirtió en una fachada al gateway H0 y dejó de inicializar el stack heredado de AGE/Weaviate/ReAct. Expone `/v1/chat/completions` y `/v1/models` y adapta `/cognitive/query` y `/cognitive/infer`. Se instaló FastAPI/Uvicorn con un lock pip compatible y hashes; la prueba funcional real conectó la fachada al Router, worker y mock y verificó readiness, descubrimiento de modelos, chat y `/cognitive/infer`. El launcher limita la escucha y el upstream a loopback; la fachada sigue dependiendo de un Router H0 activo. Las capacidades heredadas de memoria/grafo siguen fuera de la ruta funcional: agentes llaman métodos de memoria inexistentes, la consulta del grafo es un stub y hay APIs Weaviate incompatibles.

Los SDKs Python y TypeScript y la consola web comparten el contrato `/v1/chat/completions`. En modo local, la UI llama al Router loopback; en Compose, el servicio web actúa como BFF same-origin y guarda el token API en el servidor, llamando FastAPI por la red privada. Se añadió `GET /jobs/{job_id}` autenticado a la fachada. El dashboard Flask roto se reemplazó por un launcher de compatibilidad hacia la UI/BFF canónica. La carga de conocimiento y streaming siguen fuera del contrato H0.

La fachada FastAPI falla cerrado si no tiene credencial, admite bearer/API key, registry por cliente con hash/scopes/cuotas y token upstream separado. El upstream HTTP solo se acepta para loopback; HTTPS valida CA y los redirects se rechazan para no reenviar credenciales a otra autoridad. El worker exige API key de servicio fuera de loopback; Atenhea exige clave y TLS 1.2+ en listeners no-loopback. Las claves de servicio se leen de archivos privados, y redirects/proxies ambientales no reenvían credenciales. Health/readiness no filtran la URL interna. La API añade cuentas scrypt, sesiones opacas en Valkey, cookies HttpOnly y cuotas distribuidas atómicas; el rate limiter falla cerrado ante indisponibilidad del almacén. Los SDK validan el deadline H0, amplían el timeout HTTP diez segundos y conservan `job_id`/mensaje de errores FastAPI.

## H0: funcionamiento observado

1. `router.py` mantiene nodos, trabajos, recibos y estados en SQLite; entrega trabajos por polling y calcula discrepancias de medición.
2. `worker_agent.py` pregunta por el modelo del motor Atenhea (`:11436`), calibra el andamiaje de tokens, se registra y solicita trabajos.
3. El worker rechaza trabajos con `tools`, envía la inferencia al endpoint de chat, calcula precio de referencia en micro-USD y firma el recibo con Ed25519.
4. El router verifica firma y JWT de despacho Ed25519, persiste el recibo y expone estado/resumen.
5. `test_h0.py` levanta motor simulado, router y worker; verifica SDK Python, proxy UI, firmas/replay, leases, failover, métricas y dos workers.

El proceso separa el motor (`:11436`) del proxy local de agentes (`:11434`); el worker marca las solicitudes NEXUS como `nexus_worker`, y Atenhea evita tanto recuperación como captura en su memoria CHL/World y en su buffer automático de aprendizaje para ese tráfico multiusuario. Una regresión cubre que el marcador no llegue al backend y que no se consulte/actualice memoria. La memoria por cuenta todavía no está implementada; la personalización episódica queda desactivada en trabajos NEXUS hasta particionar por principal autenticado.

## Madurez y confianza de afirmaciones

| Afirmación | Evidencia disponible | Confianza |
|---|---|---|
| Atenhea tiene una ruta local de inferencia utilizable | README técnico, runtime y pruebas dedicadas presentes | Media-alta para el entorno indicado; el análisis no ejecutó el entorno ni verificó el modelo. |
| H0 completa trabajos y verifica recibos con mock | Suite E2E: 100/100 jobs, recibos, discrepancia 0%; SDK, UI proxy, replay, failover y dos workers | Alta en integración local. |
| H0 ejecuta el lote con motor Atenhea real | Puerta real: 100/100 jobs, 100 recibos válidos, discrepancia 0%, tools rechazadas; 24 tokens máximos/job | Alta para el flujo probado; no es benchmark completo ni confirma hash de pesos. |
| H1 remoto es seguro y operable entre redes | TLS/auth/enrolamiento probado en loopback; un worker del host atendió un job real vía Router Compose/Colima; rotación certificada y healthchecks reales | Alta para host→VM local; operación entre hosts/redes independientes aún no demostrada. |
| P2P, tokenómica y marketplace operan integrados | Diseño y módulos existentes, con numerosos esqueletos/incompletos documentados | No demostrado. |
| Existe una ruta local integrada de liquidación EVM | Escrow V2 compila con Solc 0.8.24; Foundry pasó 21/21 pruebas y las pruebas Python 31/31. El E2E Anvil ejecuta Router, worker y motor mock, fija fingerprints públicos de nodos, verifica dos recibos, prueba guards de chainId/decimales y liquida dos claims. El publicador exige un commitment independiente sobre chainId, escrow, token, batchId, root y rootSum; el E2E rechazó un root sustituido | Alta para la integración local simulada. No representa liquidación con ledger de producción, token real ni testnet. |
| El Router conserva capacidad de worker con chats concurrentes | Regresión con `--max-threads 4`: tres chats esperan; chat adicional recibe 503/Retry-After y un worker hace polling y envía resultado; suite H0 pasa tras los cambios de modelo | Alta para el escenario local cubierto; no es benchmark de carga. |
| Compose H0/H1 define la entrada de producto | UI same-origin → FastAPI autenticada → Router TLS privado → worker; UI/API se publican solo en loopback, Router/worker permanecen privados; bridge automático y TLS por DNS `router`; acciones CI fijadas por SHA | Build ARM64 y runtime local con mock y Atenhea real pasan; falta resultado del workflow remoto y H1 entre redes. Evidencia: `docs/evidence/h0-compose-2026-10-26.json`. |
| Sistema listo para clientes/producción | No hay evidencia de despliegue integrado, operación, hardening o métricas operativas | No. |

## Riesgos principales

1. **Superficie expuesta y autenticación:** FastAPI falla cerrado sin credencial; los registries técnicos y humanos guardan hashes y scopes. Las cuentas usan scrypt, cookies HttpOnly, sesiones opacas en Valkey con TTL e invalidación al cambiar contraseña, scopes o cuota. Cuotas por usuario e intentos de login se aplican con Lua atómico y fallan cerrados si Redis no está disponible. Los jobs guardan el `client_id` propietario en SQLite; el Router devuelve 404 a otros clientes aunque tengan `jobs:read`, y `admin` puede consultar globalmente. El E2E Compose multiusuario ya verificó login/logout, chat terminado y aislamiento entre cuentas. Compose publica UI/API solo en loopback, mantiene Router/worker privados y usa TLS/CA + secreto de servicio entre API y Router. El BFF conserva su clave con permisos mínimos y no la entrega al navegador. API, BFF, SDKs y worker evitan proxies ambientales; H1 pasa 16/16, incluida compatibilidad PKI estricta, allowlist del mock y regresiones bajo proxy hostil. El bootstrap exige sacar la clave CA de la carpeta runtime; la rotación exige archivo 0600 fuera del proyecto y revierte fallos manejables, pero un apagado abrupto entre movimientos aún requiere restaurar la pareja desde respaldo. Falta CI remoto y operación H1 entre redes independientes.
2. **Medición y economía no validadas:** H0 calcula un precio de referencia en micro-USD; no representa cobro en NEX ni liquidación on-chain. La calibración de andamiaje documentada es específica del motor y debe comprobarse en ejecución real y ante cambios de versión/modelo.
3. **Madurez heterogénea:** los módulos generales pueden parecer una plataforma completa, pero el flujo H0 no parece apoyarse en la mayor parte de la API, P2P, contratos, gobernanza ni base vectorial.
4. **Credencial expuesta confirmada:** `NEXUS/config/reasoning_agent.yaml` contiene una clave literal de aspecto real en el commit público [`8445b54`](https://github.com/Z43L/NEXUS/commit/8445b54a34fc741b787bf2e5490e85a0d46c5769). El árbol local actual usa `OPENROUTER_API_KEY` desde entorno, pero no rota la clave ni limpia la historia pública. Revocarla/rotarla urgentemente con el proveedor y coordinar limpieza de historia; hasta entonces, tratarla como comprometida.
5. **Despliegue y dependencias:** el Compose heredado usa runtime y dependencias generales de madurez desigual; Weaviate conserva acceso anónimo local. La ruta Compose H0/H1 usa imagen mínima con digest multi-plataforma fijado, lock completo con hashes SHA-256 para `cryptography`, `cffi` y `pycparser`, y materiales TLS/tokens locales; la API usa su propio lock transitivo con hashes. El build y runtime ARM64 del flujo UI/API → Router TLS → worker pasan localmente con mock; una corrida real previa usó Atenhea local. Hay chart Helm interno H0 con Services `ClusterIP`, PVC, Secrets externos y probes; lint, render y parseo pasan, pero no hay clúster para comprobar admisión/provisionamiento/runtime. El workflow ahora lint/renderiza ese chart, pero no se ejecutó remotamente. Se retiraron workflows anidados inactivos que asumían rutas inexistentes y proponían publicar/desplegar. Persisten referencias heredadas de Terraform/CI a recursos que no aparecen.

**Acceso y abuso:** la API y el BFF mantienen tokens fuera del navegador; sesiones opacas se almacenan compartidas en Valkey y los trabajos quedan asociados al usuario. El login limita por origen de red y por cuenta, para evitar que un proxy/BFF compartido convierta el límite en bloqueo cruzado entre usuarios. Los rechazos repetidos para cuentas desconocidas comparten un bucket reservado a identidades no provisionadas.
6. **Observabilidad no conectada:** el Compose heredado anuncia el puerto 9090 para métricas, pero la API no publica un exporter integrado; la config de Prometheus tiene rutas/labels de métricas discordantes y el health check consulta servicios/puertos que no corresponden a Compose/Kubernetes. El Compose H0 actual no publica 9090.
7. **Datos y privacidad:** H0 borra prompts y respuestas tras 30 días por defecto (configurable), con `secure_delete`, y conserva recibos/metadatos. Las regresiones verifican borrado del archivo activo y backups creados por el helper (purge + compactación + retención por edad); faltan snapshots externos, logs y memoria/caché de Atenhea.
8. **Blockchain/economía:** el escrow aislado compila y pasa pruebas locales; el E2E Anvil consume recibos firmados y comprueba `claimMany` con IDs nativos `job_000001`. El bridge deriva un `bytes32` estable desde el recibo canónico firmado y conserva el ID/router de origen en `sourceReceipts`. Las hojas V2 incluyen dominio, chainId, dirección del escrow, token y datos del trabajo; las pruebas rechazan replay al cambiar cualquiera de los tres parámetros de contexto. El E2E usa `DeploySettlementEscrow.s.sol` y `PublishSettlementBatch.s.sol`; separa deployer, payer y signer, comprueba configuración on-chain y rechaza chainId/decimales, signer, policy hash y contexto incorrectos antes de transmitir fondos. La raíz se limita al depósito de policy y revisa destinatarios, deadline, token y lote sin uso. El owner es inmutable, por lo que la dirección debe revisarse con cuidado antes de cada deploy. El bridge exige fingerprints SHA-256 de claves de nodo fijados en la policy, evitando que una sustitución aislada de la clave en SQLite autorice recibos. La policy y la base deben mantenerse bajo control independiente; el signer del gateway sigue siendo de confianza y capaz de autorizar pagos incorrectos bajo el depósito. La política USD/token también sigue siendo responsabilidad del operador. H0 firma `shares` enteros en micro-USD, mientras el escrow divide el total convertido en unidades mínimas del token; por tanto el reparto puede diferir a una precisión menor de un micro-USD. No se ha ejecutado deploy público ni testnet. Contratos Solidity heredados duplicados/incompatibles y runtime Rust/Substrate no son una plataforma funcional. No presentar PoK, staking, gobernanza, tokenómica ni marketplace como operativos.
9. **Concurrencia y fiabilidad:** el Router limita chats síncronos y reserva headroom del pool total para handlers del worker; devuelve 503/Retry-After al saturarse. H0/H1 resuelven el modelo solicitado entre los anunciados y el Router valida el modelo del recibo. El worker pide retry solo ante fallo de red, timeout, HTTP 429 o 5xx; el Router reencola hasta tres despachos sin fabricar un recibo. Los fallos permanentes quedan terminales; todavía no hay backoff y falta validar comportamiento con fallos reales de motor.
10. **Consistencia documental:** la spec de fusión, README, hoja ejecutiva y plan de entrega deben mantenerse alineados con el alcance local real y sus límites. Esta revisión actualiza la advertencia histórica de la spec; no implica que se haya cerrado el diseño de producto.
11. **Mantenimiento del repositorio:** los archivos H1 están versionados en la rama local. Los commits no están publicados en el repositorio compartido y la CI remota no se ha ejecutado. `.DS_Store` queda ignorado.
12. **Capacidad:** un motor Atenhea procesa generaciones en serie; el rendimiento y la economía dependen de añadir nodos, disponibilidad, carga de modelo y memoria local. La capacidad multi-nodo todavía no está acreditada.

## Recomendaciones por orden

### Próximas 1–2 semanas

- Repetir la puerta H0 real con pesos de producción y sin capar la salida; capturar versión/hash del modelo y comparar rendimiento. La evidencia limitada actual está en `docs/evidence/h0-real-2026-10-25.json`.
- Ejecutar un ensayo H1 con dos nodos en redes separadas, recuperación tras desconexión y límites medidos; la rotación del certificado ya se aplicó en Compose local, pero el ensayo multi-red sigue pendiente.
- Revocar/rotar la clave antigua con el proveedor y revisar historial Git/logs; el archivo activo ya usa una variable de entorno.
- Acordar cuál es el servicio de router H1 y demostrar dos nodos en una red de prueba controlada, con jobs y recibos reproducibles; no presentar Base/testnet como liquidación hasta que haya transacciones verificables.

### Siguiente fase

- Consolidar una única ruta de producto: H0/H1 como ruta principal o la API general heredada; marcar explícitamente módulos experimentales, obsoletos o no integrados.
- Publicar la rama revisada cuando la publicación esté autorizada y ejecutar GitHub Actions; el E2E local Router→worker→bridge→Anvil ya pasa con motor mock. Después repetir con snapshot controlado de ledger y mappings revisados; completar revisión independiente antes de testnet.
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
- Stack heredado, fuera de la ruta H0 validada: `NEXUS/docker-compose.yml`, `NEXUS/Dockerfile`.
- Ruta H0 actual: `NEXUS/compose.h0.yml`, `NEXUS/nexus-h1-node/bootstrap-compose-h0.sh` y Dockerfiles Router/worker, API y UI.
- Guía H1 local: `NEXUS/nexus-h1-node/README_MAC_NODE.md`

## Límites de este análisis

El análisis inicial fue estático y documental. Las validaciones actuales ejecutaron H0 mock, la puerta de 100 jobs, UI/API/SDK, TLS/auth/retención, FastAPI y settlement local. Los SDKs Python y TypeScript usan FastAPI por defecto; ambos exigen HTTPS fuera de loopback, evitan proxies ambientales y rechazan redirects. La API falla cerrado sin credencial, limita su upstream a loopback HTTP o HTTPS verificado, nunca reenvía el token cliente, y aplica límites de cuerpo/concurrencia. FastAPI/API-auth pasó 37/37; BFF 5/5; privacidad CHL/World y listener Atenhea 8/8; ownership Router 4/4, H1 18/18, SDK Python 8/8 y TypeScript 6/6. El E2E Compose multiusuario más reciente pasó: API 401 sin credencial, login de dos cuentas, cookie HttpOnly, modelos/chat, job completado, consulta cruzada 404 y cierre de sesión con acceso revocado; el token API no aparece en el HTML. `test_h0.py` pasó 100/100 trabajos y recibos con dos workers. Los trabajos NEXUS omiten la memoria compartida CHL/World hasta crear particiones por cuenta. El listener remoto exige API key y TLS; el worker carga la clave desde un archivo privado. La rotación real en Compose fue seguida por inferencia Atenhea local. El settlement Anvil procesó dos claims (`rootSum=20000`); Foundry v1.8.6 pasó 21/21 pruebas y Python builder/bridge 31/31. Compose se construyó y ejecutó en ARM64 con Colima contra mock y Atenhea local. Helm lint/render pasa; readiness usa un Host permitido y el chart exige Redis TLS verificado. No hay despliegue Kubernetes. El workflow GitHub no se ejecutó remotamente; tampoco se probó H1 entre redes independientes ni hubo transacciones públicas.

## Actualización de implementación — 26 de octubre de 2026

Después del análisis se trabajó en la vertical H0. Esta actualización reemplaza las observaciones anteriores sobre entrega de salida y token de despacho:

- El router ahora persiste y devuelve la salida del worker y ofrece `POST /v1/chat/completions` en modo texto/no streaming.
- El despacho usa JWT Ed25519 de 30 minutos ligados al nodo y al trabajo. Las requests de nodo también se firman y protegen contra replay.
- El router valida campos del trabajo y recibo, hash de salida, precio/reparto y discrepancia ≤1%; limita cuerpos, mensajes, longitud de entrada y la cola activa. Vincula `receipt.nram_used` con los autores NRAM persistidos en el trabajo y rechaza firmas válidas con autoría alterada.
- Se retiró la clave literal de `NEXUS/config/reasoning_agent.yaml`; el backend heredado ahora exige `OPENROUTER_API_KEY` de entorno. La clave anterior fue confirmada en el commit público `8445b54`; requiere revocación/rotación en el proveedor y coordinación para limpiar el historial Git.
- `test_h0.py` se ejecutó con el runtime Python del entorno y el mock: 100/100 trabajos, 100/100 recibos, discrepancia máxima 0%, rechazo de tools, firma manipulada rechazada, endpoint de chat y recuperación de resultado correctos, más fallback del contador alterno. Resultado: **ALL H0 TESTS PASS**.

La puerta real fue positiva con salida limitada a 24 tokens por trabajo; no es el benchmark de salida normal. No se encontraron pesos `.gguf`/`.safetensors` en el checkout ni se registró un hash de modelo. H0 local sigue limitado a `127.0.0.1`; los cambios recientes añaden modo remoto seguro, sujeto a ensayo entre redes. La inspección M4 encontró contratos heredados sin ruta compilable y plataformas duplicadas; se eligió Base EVM para el vertical aislado. El estado actual y las puertas pendientes se siguen en [PROJECT_DELIVERY.md](PROJECT_DELIVERY.md).

### Validación final local

Se amplió y volvió a ejecutar `NEXUS/nexus/h0/test_h0.py`: **ALL H0 TESTS PASS**. Además de la puerta de 100 trabajos y las verificaciones criptográficas, se validaron el SDK Python, el proxy same-origin de la consola web, la recuperación por lease y failover, y el reparto de 12 trabajos entre dos procesos H1. El SDK TypeScript compiló con `npm ci` + `npm run build`; se retiraron `node_modules/` y `dist/`, conservando `package-lock.json`.

La consola H0 se sirve solo en loopback; el fixture BFF usa archivos privados 0700/0600, hashes de credenciales y una clave técnica limitada. UI → API → Router TLS → worker enrolado y firmado → mock cubre readiness, modelos, chat, estado/receipt, origen extranjero 403, API sin credencial 401, body excesivo 413 y token ausente del HTML. H0 pasó 100/100 trabajos con dos workers; FastAPI/API-auth 37/37, BFF 5/5, memoria y listener Atenhea 8/8, ownership Router 4/4, H1 18/18, SDK Python 8/8 y TypeScript 6/6. Compose multiusuario completó un trabajo y probó acceso cruzado 404, logout y rechazo posterior 401; detalle en [`docs/evidence/auth-multiuser-compose-2026-10-26.json`](docs/evidence/auth-multiuser-compose-2026-10-26.json). Retención, rotación y backup también pasaron; settlement Python 31/31, Foundry 21/21 y E2E Anvil dos claims (`rootSum=20000`). Router/worker, API, UI y mock se construyen en ARM64 Colima; una ejecución previa usó Atenhea real local y otra un worker de host vía TLS, sin acreditar dos hosts físicos. Helm lint/render pasa; readiness usa un Host de la allowlist y el chart fuerza TLS de Redis. GitHub Actions se configuró pero no se ejecutó remoto. La evidencia base está en `docs/evidence/h0-compose-2026-10-26.json` y `docs/evidence/settlement-anvil-2026-10-26.json`. Pendientes: CI remoto, H1 entre redes, memorias CHL por usuario, revisión independiente de signer/contrato, economía/capacidad, hash de pesos, rotación externa de la credencial OpenRouter expuesta históricamente y testnet. No hay transacciones públicas ni pesos de producción en este checkout.
