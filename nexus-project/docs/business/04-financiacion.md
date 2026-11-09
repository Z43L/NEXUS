# 04 · Financiación

Fecha: 2026-10-27. **No hay ronda abierta, ni inversores, ni compromisos.** Los importes de esta página salen del presupuesto del modelo
(`finance/model.py`, caso base) y son orden de magnitud para planificar, no una oferta. Las valoraciones del cap table son **hipótesis aritméticas**,
no estimaciones de mercado. No es asesoría de inversión ni legal.

## 1. Ronda pre-seed

### Cómo se dimensiona (reproducible)
1. El script simula el caso base mes a mes y toma la **quema acumulada máxima en los meses 1-18**: **964.542 USD** (gasto total ≈ 968.900 USD menos 4.352 USD de ingreso neto).
2. Se multiplica por un colchón de **1,25** (`buffer`, supuesto) y se redondea a 50 k: **1.250.000 USD** (≈ 1,14 M€ a 1,10 USD/€ `[POR VERIFICAR]` FX).
3. Cubre hasta el mes 18-19 en el caso base con una caja mínima de ≈ 285 k USD justo antes de la seed. En el conservador (menos gasto) sobra caja; en el optimista (contrata más tras el mes 19) la caja mínima cae a ≈ 204 k USD en el mes 18-19.

### Uso de fondos (meses 1-18, caso base; USD)
| Concepto | USD | % del gasto |
|---|---|---|
| Equipo (4 FTE hasta el mes 9, 7 desde el 10, a 6.000 USD/mes cargado, `[SUPUESTO]`) | 594.000 | 61,3 % |
| Auditorías: contrato/puente de escrow antes del primer pago real (60 k, `[POR VERIFICAR]` cotización), pen test (20 k), revisión independiente del protocolo de slots/vault (40 k) | 120.000 | 12,4 % |
| Legal: constitución, marca, opinión de pagos/KYC y token, ToS/AUP/DPA + iguala | 74.500 | 7,7 % |
| Marketing y comunidad | 69.000 | 7,1 % |
| G&A (contabilidad, seguros, herramientas) | 61.650 | 6,4 % |
| Infraestructura del coordinador/gateway (alpha 800 USD/mes, beta 2.500 USD/mes) y costes de pago | 45.809 | 4,7 % |
| Crédito de arranque a operadores y KYC | 3.934 | 0,4 % |
| **Total gasto** | **≈ 968.900** | 100 % |
| Ingreso neto estimado | –4.352 | |
| **Quema** | **964.542** | |
| Colchón (25 %) | 285.458 | |

**Lo que NO financia esta ronda:** token, listado en exchanges, marketing masivo, hardware propio de nodos ni liquidación con dinero real a gran escala.

### Hitos que desbloquean la siguiente ronda (propuestos, no existentes)
La seed del modelo (1,7 M USD, ver abajo) se plantea en el mes 19. Para llegar con un caso creíble el equipo debería poder mostrar, con evidencia verificable:
1. **H1 entre redes independientes** funcionando (hoy solo host→VM local, `EXECUTIVE_BRIEF.md`) y una medida de **throughput real por nodo** en configuración de slots (hoy no hay).
2. Escrow **auditado por un tercero** y primer lote de pagos reales pequeño, con KYC cerrado; sin hallazgos críticos abiertos.
3. **≥ 30-50 operadores externos** (no del equipo) que sirven trabajo verificado durante ≥ 3 meses, con tasa de fallo y de discrepancia publicadas.
4. **Demanda de pago medida**: cuentas dev y business con consumo recurrente y una cohorte con retención; cifras reales, no la lista de espera.
5. **≥ 3 conversaciones de enclave con piloto de pago o carta de intención** (el modelo depende de esta línea; hoy es una hipótesis sin cliente).
6. Licencias del catálogo verificadas por abogado (ver `05`) y nombre/marca despejados (riesgo señalado en el brief).
Los umbrales numéricos son propuestas del equipo de negocio y deben validarse con inversores reales.

## 2. Ronda seed (orientativa)

- Necesidad del caso base tras la pre-seed: la fosa acumulada máxima es 2.326.578 USD; con 1,25 M ya financiados y el mismo colchón, la **seed = 1.700.000 USD** (mes 19, redondeado a 100 k).
- Sirve para pasar de 7 a 13 FTE, la certificación de operadores, el primer enclave y la expansión comercial.
- **Aun así no llega al equilibrio**: el EBITDA del mes 36 es –92.078 USD/mes en el caso base, y la caja al mes 36 es 623.422 USD (≈ 7 meses de quema). Haría falta una serie A, financiación no dilutiva, o un plan de plantilla menor (con la mitad de plantilla la necesidad baja a 1,38 M USD acumulados).
- Los inversores de seed probablemente pedirán una tracción que hoy no existe; si el hito 5 no se cumple, la seed se retrasa y el modelo debe reducirse.

## 3. Alternativas no dilutivas (programas reales, a verificar antes de aplicar)

| Programa | Qué es | Importe / calendario | Encaje con NEXUS | Fuente |
|---|---|---|---|---|
| **NLnet** (NGI Zero y otros fondos) | Subvención para código abierto técnico, licencias abiertas | 5.000-50.000 € la primera vez; **próxima fecha límite: 3-nov-2026, 12:00 CET**; exige licencia abierta, "dimensión europea" si el fondo es de la UE; **no admite propuestas redactadas por IA** | Bueno para componentes abiertos (almacenamiento cifrado/erasure coding, recibos firmados, CLI). Requiere decidir licencias del código `[POR VERIFICAR]` | https://nlnet.nl/propose/ (consultado 2026-10-27) |
| **EIC Accelerator** | Subvención + equity de la UE para deep tech | Hasta 2,5 M€ de subvención y 1-10 M€ de equity (EIC Fund hasta 25 %); cortes 2026 incl. 4-nov-2026; paso 1 abierto siempre; empresa UE | **Prematuro** (exige TRL 6-8; NEXUS está en alpha local). Candidato tras H1 multi-red y primer cliente de pago | https://opportunitiesforyouth.org/2025/11/26/apply-now-eic-accelerator-2026-grants-up-to-e2-5m-and-equity-up-to-e10m-for-deep-tech-startups (secundaria); oficial: https://eic.ec.europa.eu `[POR VERIFICAR]` |
| **CDTI Neotec** (España) | Subvención no reembolsable para empresas de base tecnológica jóvenes | Según guías, hasta 250.000 €; empresa de 6-36 meses; convocatoria 2026 publicada el 8-abr-2026; próxima `[POR VERIFICAR]` | Posible si la sociedad es española y se constituye con antelación | https://www.cdti.es (oficial, no consultada); resumen secundario en https://tecnociminnova.com `[POR VERIFICAR]` |
| **ENISA** (España) | Préstamo participativo, no dilutivo | Fuentes discrepan: 25.000-75.000 € (Jóvenes Emprendedores) o hasta 300.000 €/1,5 M€ según línea; `[POR VERIFICAR]` | Complementa la ronda; exige sociedad española y cuentas | https://www.enisa.es (oficial, no consultada); https://ecosistemastartup.com/prestamo-enisa-2026-hasta-15me-sin-ceder-equity/ (secundaria) |
| **Ethereum Foundation – Ecosystem Support Program** | Subvenciones a software libre que refuerza Ethereum | Agregadores: 5.000-50.000 USD, sin plazo fijo; asignación Q1-2026 ≈ 9,86 M USD | Encaje parcial: NEXUS liquida con contratos EVM (Base), pero ESP prioriza infraestructura de Ethereum (criptografía, seguridad, ZK) | https://esp.ethereum.foundation/ |
| **Nosana Grants** | Subvenciones de un marketplace de GPU descentralizado | 5.000-50.000 USD + acceso a su red GPU (nota de prensa de pago, dic-2025) | Compite parcialmente; puede exigir uso de su red `[POR VERIFICAR]` | https://cointelegraph.com/press-releases/nosana-launches-grants-program-to-support-the-creators-of-the-next-wave-of-decentralized-ai |
| **Filecoin Foundation** | Financiación de proyectos que usan/mejoran Filecoin | `[POR VERIFICAR]` | Encaje solo si el almacenamiento de fragmentos pudiera usar su red | https://fil.org/blog/2025-annual-report |
| **Mozilla Ventures / Builders** | Inversión (equity) y aceleradora para IA abierta y de confianza | Reservas de Mozilla ≈ 1.400 M USD con ≈ 20 % del gasto previsto a IA de confianza; condiciones `[POR VERIFICAR]` | Es dilutivo (equity), no una subvención | https://www.eweek.com/news/mozilla-1-4b-ai-rebel-alliance/ |
| **Sovereign Tech Fund (Alemania)** | Financia infraestructura digital abierta | Un resumen secundario cita mínimo 150.000 €; `[POR VERIFICAR]` | No encaja en alpha; es para infraestructura madura de uso amplio | https://www.sovereign.tech (la subpágina de programa devolvió 404 el 2026-10-27) |

Reglas de honestidad para cualquier solicitud: describir el estado alpha, no usar cifras de usuarios inexistentes, no prometer descentralización "sin matiz".
Una subvención con requisito de licencia abierta condiciona el modelo de negocio (si el código es MIT/Apache, las empresas pueden alojar su propia red y la defensa es operar el coordinador, la verificación y los enclaves certificados).

## 4. Cap table orientativo (ilustración; sin fundadores, valoraciones ni inversores reales)

Hipótesis de cálculo (todas `[SUPUESTO]`): pool de opciones del 10 % creado antes de la pre-seed; pre-seed de 1,25 M USD a una valoración **pre-money hipotética de 5 M USD** (dilución 20,0 %);
seed de 1,7 M USD a una valoración pre-money hipotética de 10 M USD (dilución 14,5 %). Dilución por pre-money (del script): pre-seed 29,4 % / 20,0 % / 13,5 % a 3 / 5 / 8 M USD; seed 22,1 % / 14,5 % / 9,6 % a 6 / 10 / 16 M USD.

| Titular | Tras constitución | Tras pre-seed | Tras seed |
|---|---|---|---|
| Fundadores (número y reparto `[POR VERIFICAR]`) | 90,0 % | 72,0 % | 61,6 % |
| Pool de opciones (ESOP) | 10,0 % | 8,0 % | 6,8 % |
| Inversores pre-seed | – | 20,0 % | 17,1 % |
| Inversores seed | – | – | 14,5 % |
| Total | 100 % | 100 % | 100 % |

Notas: no incluye ampliación de ESOP en la seed (habitual), notas convertibles ni SAFE, ni subvenciones (no diluyen) ni préstamos participativos. Una valoración de pre-seed por encima de 5 M USD con un producto en alpha
sin ingresos sería excepcional; hay que **esperar** que el mercado ponga una valoración distinta. Las cifras son aritmética, no una recomendación.

## 5. Recomendación de secuencia (hipótesis)
1. Ahora: solicitar NLnet (plazo 3-nov) solo si el código se puede publicar con licencia abierta y hay tiempo de redactarlo a mano; preparar el hito de H1 multi-red.
2. Meses 1-6: constitución, opiniones legales, entrevistas de enclave, medir throughput real. Pre-seed de ≈ 1,1-1,25 M cerrada con estos datos.
3. Meses 6-15: subvenciones españolas (Neotec, ENISA) si la sociedad es española; EIC Step 1 una vez haya H1 multi-red y primer cliente de pago.
4. Mes 18-19: seed solo si se cumplen los hitos de la sección 1; si no, reducir plantilla (el modelo con 50 % de plantilla necesita 1,38 M USD en total).
