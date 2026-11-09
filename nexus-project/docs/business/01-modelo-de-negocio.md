# 01 · Modelo de negocio

Fecha: 2026-10-27 · Estado del producto: **alpha cerrada, testnet, sin token, sin liquidación con dinero real**. Todo lo que sigue es un
diseño y una proyección con supuestos explícitos. No hay clientes, ingresos, rondas ni mercado medido. Las cifras vienen de
`finance/model.py` (ejecutable) y las referencias externas llevan URL y fecha en `02-precios.md`.

## 1. Hallazgo central (léelo primero)

El modelo financiero obliga a decir algo incómodo: **cobrar una comisión sobre tokens de modelos abiertos genéricos no sostiene una
empresa**. A precios de mercado (≈ 0,155 USD por millón de tokens mezclados para la clase 70B, DeepInfra, 2026-10-27) una petición de 900
tokens factura ≈ 0,000126 USD y la plataforma retiene ≈ 0,000019 USD (15 %). Un desarrollador típico del escenario base (20 M tokens/mes)
aporta ≈ 0,47 USD/mes de ingreso neto frente a un CAC supuesto de 120 USD. Y el operador que sirve esos tokens gana, en el escenario base,
**menos de lo que le cuesta la electricidad** salvo que use hardware ya amortizado y de bajo consumo (un Mac de Apple Silicon, por ejemplo).

Por tanto el negocio no es "un OpenRouter descentralizado más barato". Los ingresos que sí pagan un equipo salen de lo que un proveedor
centralizado no ofrece: **enclaves/swarms privados, SLA y soporte, certificación de operadores, regalías de autores con comisión de
plataforma** y, más tarde, fine-tuning. La inferencia comunitaria es el escaparate, el motor de oferta y la prueba técnica, no la caja.

## 2. Lienzo del modelo

| Bloque | Contenido (todo hipótesis salvo lo marcado como existente) |
|---|---|
| Segmentos | (a) desarrolladores y startups que quieren API compatible con OpenAI con recibos firmados; (b) equipos/empresas con requisitos de trazabilidad o de que ningún proveedor único vea el modelo completo; (c) autores de modelos/adaptadores `.nram` que quieren cobrar regalías; (d) dueños de GPU/Mac (aficionados, pequeños centros, universidades) como oferta; (e) organizaciones que quieren un swarm privado sobre sus propios nodos. |
| Propuesta de valor | API OpenAI-compatible (existe en H0, local); recibo firmado verificable por trabajo (existe); *ningún operador tiene el modelo completo* (diseño; una coalición lo bastante grande sí podría reconstruirlo y quien consulta puede destilarlo); reparto automático de regalías a autores (escrow en testnet). **No** prometemos "trustless", privacidad total ni "imposible de copiar". |
| Canales | Documentación y SDKs (Python/TS existen), comunidad de modelos abiertos, listas de espera, contenido técnico, partners de hardware/universidades `[POR VERIFICAR]`. Detalle en `docs/go-to-market/`. |
| Relación | Self-serve para devs; ventas asistidas para business/enclaves; programa de certificación para operadores. |
| Ingresos | Ver sección 3. |
| Recursos clave | Coordinador/gateway, protocolo de slots y recibos, escrow, equipo de ingeniería y seguridad, red de operadores. |
| Actividades | Operar el coordinador, verificar trabajos (canarios/doble ejecución), publicar y firmar modelos, liquidar por lotes, soporte. |
| Socios | Autores de modelos, operadores certificados, auditores de seguridad, proveedor de pagos/KYC. |
| Costes | Equipo, infraestructura del coordinador, verificación, auditorías, legal, marketing, incentivos de arranque a operadores. Ver `finance/output/resumen.md`. |

## 3. Fuentes de ingresos

El modelo usa **ingreso neto = lo que retiene la empresa**. El GMV (lo que paga el cliente) incluye lo que se reenvía a nodos, autores y
verificación y no es ingreso de la empresa.

| # | Línea | Quién paga | Mecánica | Estado de la evidencia |
|---|---|---|---|---|
| 1 | Comisión sobre inferencia | Cliente de la API | % del precio por token retenido por la plataforma (propuesta 15 %; escrow actual 5 %) | Mecánica en escrow de testnet; sin clientes. |
| 2 | Regalías a autores + comisión de plataforma | Cliente que usa un adaptador `.nram` | El autor recibe 10 % (escrow actual) de los trabajos con su adaptador; la plataforma mantiene su % sobre el total | `InferenceEscrow.sol` lo implementa; sin autores reales. |
| 3 | Enclaves / swarms privados | Empresa | Cuota mensual fija (coordinación, instancia dedicada, soporte, cumplimiento) + alta; el cómputo corre en nodos del cliente o certificados, no en el pool público | Hipótesis; precio por coste + margen (ver `02`), sin cotizaciones reales. |
| 4 | Soporte y SLA | Cuentas business | Plan mensual; SLA solo cuando existan métricas medidas de disponibilidad | Hipótesis; no se ofrece SLA en alpha. |
| 5 | Programa de operadores certificados | Operador | Cuota anual pequeña (≈ coste de KYC y revisión de atestación); da acceso a trabajos de enclave | Hipótesis; apenas margen, sirve para habilitar la línea 3. |
| 6 | Fine-tuning (futuro) | Cliente / autor | Marketplace con % de plataforma | **Problema de investigación abierto** (swarm-sim: ~59 etapas para 70B, compresión ≥10×). No contar con ello antes del mes 27-33. |

### Qué NO se monetiza
- **No hay token en v0.1** ni venta de token. Si se plantea en el futuro es una opción con riesgo regulatorio (ver `05`).
- No se vende "privacidad total", "descentralización" sin matiz ni garantía de rendimiento a operadores.
- No se cobra al operador por unirse (más allá de la cuota de certificación voluntaria) ni se le promete ingreso: se le **paga por trabajo
  verificado**. El "crédito de arranque" del modelo (30-50 % del hueco de coste de los nodos mínimos hasta el mes 20-24) es un gasto de la
  empresa, no una promesa de rendimiento, y requiere revisión legal.
- No se venden datos de prompts. No se entrena con prompts de clientes.
- No se cobra comisión sobre el cómputo local de un usuario sobre sus propios modelos.

### Por qué cada lado paga o cobra
- **Cliente**: paga por una API estándar con recibos verificables y, en los niveles de pago, por redundancia, prioridad y soporte. El precio
  del tier comunitario no puede ser mucho menor que el mercado (ver abajo), así que la razón para pagar no es el precio.
- **Autor**: cobra regalías sin entregar los pesos en claro a un único operador; paga su parte como comisión de plataforma.
- **Operador**: cobra por trabajo verificado; a cambio aporta capacidad y acepta recibos firmados y canarios. Honestamente: a precios de
  mercado solo compensa si el hardware ya existe y consume poco, o si el precio por token es mayor (tier verificado).
- **Empresa enclave**: paga por no depender de un único proveedor que vea los pesos y por trazabilidad; es la línea con margen.
- **NEXUS**: cobra por coordinar, verificar, liquidar, certificar y dar soporte.

## 4. ¿Encaja el reparto 75/10/5/5/5 del escrow?

`InferenceEscrow.sol`: nodo 75 %, autor 10 %, verificación 5 %, quema 5 %, tesorería 5 %; si no hay autor, el 10 % pasa al nodo (nodo 85 %).
Resto de la división entera, a tesorería.

### Análisis
1. **Tesorería 5 % es insuficiente.** Con 5 % y 5 % de "quema" que en realidad no puede quemarse si se liquida en stablecoin (envía fondos reales a
   `0x…dEaD`, es una pérdida neta de caja y solo tiene lógica en un token propio con oferta), la empresa retiene como máximo 5 % del GMV. El
   procesamiento de pago supuesto (3 %, `[POR VERIFICAR]`) se come 60 % de eso. Referencias de mercado: OpenRouter cobra 5,5 %/8 % al comprar
   créditos (https://openrouter.ai/pricing, 2026-10-27) y Akash ha bajado su comisión al 1-2 % por arrendamiento (gobernanza, `[POR VERIFICAR]` valor vigente; https://akash.network/roadmap/aep-22/),
   pero ninguno exige además verificación redundante, enclaves ni soporte de autores; las tiendas de apps cobran 15-30 % (https://www.macrumors.com/2020/11/18/apple-drops-app-store-fees/, 2020, `[POR VERIFICAR]` vigencia).
2. **La quema (5 %) no tiene sentido sin token** y sí tiene un coste: es dinero del cliente que no llega a nadie. Sin token debe ser 0 %.
3. **Verificación 5 % es razonable como punto de partida**, pero es una hipótesis: el coste real depende de la tasa de canarios y doble ejecución
   (que aún no se ha medido). Debe ser un parámetro de gobernanza, no una constante.
4. **Autor 10 % solo en trabajos con adaptador.** Si no hay autor, no debe repartirse a nadie arbitrariamente; lo coherente es dejarlo en el nodo (como hoy).
5. **Nodo 75-85 %** es compatible con mercados comparables, pero el problema del operador no es el porcentaje, es el precio absoluto por token
   (ver `02`): un 10 % más de reparto no arregla un ingreso de unos pocos USD/mes por nodo.

### Propuesta razonada (a validar; no es definitiva)
| Concepto | Escrow actual | Propuesta | Razón |
|---|---|---|---|
| Plataforma/tesorería | 5 % | **15 %** | Cubre pago (≈ 3 %), infraestructura variable y soporte; debajo del 15-30 % de tiendas de apps; por encima de OpenRouter (que no hace verificación ni royalties). Margen de ajuste: 10-20 %. |
| Verificación | 5 % | 5 % (parámetro) | Mantener, medir el coste real y fijarlo por gobernanza. |
| Quema | 5 % | **0 %** | Sin token no hay quema; con stablecoin sería pérdida. Reintroducir solo si existe un token y tras revisión legal. |
| Autor | 10 % (solo con adaptador) | 10 % (solo con adaptador) | Sin cambio; es una variable del autor (royalty_bps del manifiesto), con tope. |
| Nodo | 75 % (85 % sin autor) | resto: **70 %** con adaptador, **80 %** sin adaptador | El nodo recibe el remanente. |

Resultado en el modelo (`finance/output/split_comparison.csv`, ingreso neto acumulado a 36 meses, USD): conservador 64.131 → 64.844; base 502.425 →
508.977; optimista 2.038.973 → 2.074.729. **El cambio de reparto casi no mueve el negocio** porque, a estos volúmenes, la inferencia comunitaria apenas
factura; el 99 % del ingreso neto base del mes 36 (51.647 USD) viene de enclaves (45.766), SLA y certificación; inferencia y regalías suman 524 USD. Por eso el ajuste del reparto debe justificarse por
sostenibilidad del protocolo y claridad frente a operadores y autores, no por la caja de los primeros 36 meses.

### Cambios al contrato que implica (no se hacen aquí; carpeta fuera de mi propiedad)
- Constantes `BURN_BPS` y `TREASURY_BPS` pasan a parámetros fijados por el desplegador y limitados por tope; `BURN_BPS=0` sin token.
- Sin token propio se liquida en stablecoin/euros: implica el análisis de pagos de `05-legal-y-cumplimiento.md`.
- El árbitro (owner) y la ventana de disputa de 7 días ya existen; el modelo no cuantifica el coste de una disputa (hipótesis pendiente).

## 5. Riesgos del modelo de negocio (resumen; detalle en `07-riesgos.md`)
- Operadores no cubren costes a precio de mercado → la oferta no escala (el modelo lo muestra: la utilización llega al techo de 75 % y se atiende solo
  el 21 % de la demanda del caso base en el mes 36).
- La proposición de "más barato" es débil frente a proveedores con H100 y batching; hay que competir en trazabilidad, regalías y enclaves.
- Las licencias de modelos base condicionan el catálogo (ver `05`).
