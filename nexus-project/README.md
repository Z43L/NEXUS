# nexus-project

Carpeta de trabajo de la startup **NEXUS**: una red descentralizada de IA donde ningún operador posee el modelo completo y el
cómputo se paga en proporción al trabajo verificado. Estado: **alpha cerrada, testnet, sin token, sin liquidación con dinero real.**

Empieza por [`BRIEF.md`](BRIEF.md): producto, decisiones técnicas (salen de [`../research/swarm-sim`](../research/swarm-sim/README.md)),
reglas de honestidad y propiedad de carpetas.

| Carpeta | Contenido | Responsable |
|---|---|---|
| [`docs/product/`](docs/product/) | Análisis del repo, PRD, arquitectura, modelo de amenazas, hoja de ruta, decisiones | Arquitecto de producto |
| [`code/nexus_storage/`](code/nexus_storage/) | Partir, cifrar, erasure coding y manifiesto firmado de modelos | Ingeniería de almacenamiento |
| [`code/nexus_runtime/`, `nexus_api/`, `nexus_cli/`, `deploy/`](code/) | Coordinador, nodos, inferencia por etapas, recibos, gateway OpenAI-compatible, CLI | Ingeniería de runtime |
| [`docs/go-to-market/`](docs/go-to-market/) | Mercado, posicionamiento, plan de lanzamiento, contenido, métricas, comunidad | Go-to-market |
| [`site/`](site/) | Landing oficial (ES/EN), páginas legales en borrador | Diseño web |
| [`docs/business/`](docs/business/), [`finance/`](finance/) | Modelo de negocio, precios, plan de ingresos, financiación, legal, riesgos, modelo financiero | Negocio y finanzas |

## Reglas que no se negocian

- Nada de métricas, clientes, testimonios ni precios inventados: lo que falta va como `[POR VERIFICAR]` o como supuesto etiquetado.
- Todo texto público respeta la lista permitido/prohibido de `docs/product/04-modelo-de-amenazas.md`.
- Cripto escrita a mano en este repo es **NOT AUDITED**: se sustituye por librerías auditadas antes de cualquier uso con dinero real.
- Hay una credencial antigua expuesta en el historial (`8445b54`): debe rotarse en el proveedor.

## Estado a 2026-10-27 (verificado al integrar)

| Pieza | Verificación real |
|---|---|
| `code/nexus_storage` | 21 tests OK (1 omitido sin `cryptography`) |
| `code/nexus_runtime`, `nexus_api`, `nexus_cli` | 20 tests OK (41 con storage); demo de 1 coordinador + 6 nodos con un nodo muerto a mitad: salida idéntica a la de referencia, 168 recibos y 6 reclamaciones verificadas |
| `finance/model.py` | 22 tests OK; ningún escenario llega a equilibrio en 36 meses |
| `site/` | 154 enlaces internos sin rotos según el agente; no vuelta a abrir tras el último cambio de texto |
| `docs/` | Producto, go-to-market y negocio escritos; cifras de mercado con `[POR VERIFICAR]` pendientes |

**Límites:** modelo de demo con pesos aleatorios; HTTP sin TLS con claves de slot por ese canal; cripto de respaldo sin auditar;
`docker-compose.yml` ya validado (2026-11-09, `code/deploy/docker_smoke.sh`: chat, recibos, lote, 401 sin token en `/stage`); sin TLS ni multi-host; adaptador `AtenheaEngine` de un solo nodo (no distribuido, probado con servidor simulado); sin pagos reales.

**Decisiones abiertas para el equipo:** nombre/marca (riesgo alto, ver `docs/go-to-market/01`), licencia del código (propuesta Apache-2.0),
reparto de ingresos (propuesta del agente de negocio: plataforma 15 %, verificación 5 %, autor 10 % solo con adaptador, sin quema),
quién opera el coordinador en la alpha, y revisión legal de textos y de un crédito de arranque a operadores.
