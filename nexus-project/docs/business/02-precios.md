# 02 · Precios y economía del operador

Fecha: 2026-10-27. **No hay precios publicados ni clientes.** Este documento fija un *método* y ejemplos con supuestos; no una lista de precios.
Todos los datos externos se consultaron el 2026-10-27 salvo indicación; los marcados `[POR VERIFICAR]` provienen de agregadores o
resultados de búsqueda y deben confirmarse en la página oficial antes de usarlos.

## 1. Referencias externas

### Inferencia de modelos abiertos (USD por millón de tokens, entrada/salida)
| Modelo | Precio | Fuente |
|---|---|---|
| Llama-3.3-70B-Instruct-Turbo | 0,10 / 0,32 | DeepInfra, https://deepinfra.com/pricing |
| gemma-3-27b-it | 0,08 / 0,16 | DeepInfra (misma página); OpenRouter coincide en https://openrouter.ai/compare/google/gemma-3-27b-it (resultado de búsqueda; los rastreadores de terceros discrepan, `[POR VERIFICAR]`) |
| gemma-3-12b-it | 0,05 / 0,15 | DeepInfra |
| gemma-3-4b-it | 0,05 / 0,10 | DeepInfra |
| Meta-Llama-3.1-8B-Instruct-Turbo | 0,02 / 0,04 | DeepInfra |
| Llama 3 8B Instruct Lite | 0,14 / 0,14 | Together AI, https://www.together.ai/pricing |
| Llama 3.3 70B Turbo | 0,88 / 0,88 | Together AI según agregador (https://www.getmaxim.ai/bifrost/llm-cost-calculator/provider/together_ai/model/llama-3.3-70b-instruct-turbo.md); no aparece en la tabla serverless oficial consultada. `[POR VERIFICAR]` |

Lectura: el mismo modelo de 70B cuesta entre ≈ 0,155 USD/M (mezcla 3:1 en DeepInfra) y ≈ 0,88 USD/M (Together, si se confirma). El precio es
un mercado con dispersión de 5-6×; hay espacio para un tier de "verificado" pero **no** para un tier comunitario 5× más caro que el barato.
El modelo usa 0,155 USD/M (DeepInfra, 70B) como referencia por coherencia con el techo de throughput del simulador.

### Plataformas (comisiones)
- OpenRouter: 5,5 % (Standard) y 8 % (Business) sobre la compra de créditos, nunca por petición; precio de token = el del proveedor. https://openrouter.ai/pricing
- Akash: comisión por arrendamiento fijada por gobernanza, reducida a 1 % (uAKT) y 2 % (axlUSDC) en una propuesta; https://akash.network/roadmap/aep-22/ y https://polkachu.com/gov_proposals/4350. `[POR VERIFICAR]` valor vigente.
- Tiendas de apps: 15 % (pequeños) / 30 % (general), Apple, 2020: https://www.macrumors.com/2020/11/18/apple-drops-app-store-fees/. `[POR VERIFICAR]` vigencia 2026.
- Bittensor: la documentación consultada solo describe tasas de transacción de cadena, no una comisión de marketplace: https://docs.learnbittensor.org/fees.

### Alquiler de GPU (lo que gana un dueño de GPU si la alquila en vez de servir tokens)
- RTX 4090 en Vast.ai: mediana ≈ 0,40 USD/h según la propia web (resultado de búsqueda); la página directa no mostraba ofertas el 2026-10-27; la 4090D mediana ≈ 0,20 USD/h https://vast.ai/pricing/gpu/RTX-4090D. Rastreadores: 0,15-0,52 USD/h (https://computeprices.com/providers/vast/gpus/rtx4090). RunPod Community ≈ 0,34 USD/h. `[POR VERIFICAR]` todos; es una dispersión de snapshots.
- Referencia práctica: **0,35 USD/h ≈ 255 USD/mes** para una 4090 alquilada. Es el coste de oportunidad real del operador con GPU dedicada.

### Electricidad y hardware
- España, media doméstica 1.º semestre 2026: 27,39 c€/kWh (cálculo de Selectra a partir de Eurostat, https://selectra.es/energia/noticias/kwh-luz-2026-consumo-bajo-precio-caro; `[POR VERIFICAR]` no es cifra oficial de Eurostat). Media UE 2.º semestre 2025: 28,96 c€/kWh (Eurostat vía https://www.brusselstimes.com/2114367/stark-gaps-in-eu-household-energy-costs-as-taxes-take-bigger-slice).
- GPU de consumo: RTX 4090 descatalogada, usada ≈ 2.200 USD (eBay vendido) y RTX 5090 con PVP 1.999 USD pero precio de calle 4.300-5.000 USD en 2026 (https://tech-insider.org/rtx-5090-vs-rtx-4090-2026/; fuente de blog, `[POR VERIFICAR]`). TDP 450 W (4090) y 575 W (5090).

## 2. Estructura de precios (por capa de servicio)

| Capa | Para quién | Cómo se cobra | Precio | Estado |
|---|---|---|---|---|
| **Comunitaria** (best-effort) | Desarrolladores, pruebas | Por token, créditos prepago; entrada y salida separadas | Cerca del mercado (supuesto: 10 % por debajo del 70B de referencia) | beta |
| **Verificada** | Producción ligera | Por token con multiplicador (supuesto 2-2,5×) | Recibos firmados, re-ejecución por canarios, prioridad | beta tardía / GA |
| **Business** | Equipos | Por token con descuento por volumen (supuesto 0-10 %) + plan de soporte/SLA mensual | Plan mensual de soporte (supuesto 250-400 USD/mes) | GA (el SLA solo con métricas medidas) |
| **Enclave / swarm privado** | Empresas | Cuota mensual fija + alta; cómputo en nodos del cliente o certificados | Coste directo + margen (sección 3) | GA tardía; sin cotizaciones reales |
| **Regalías de autor** | Autores | Porcentaje del precio por token en los trabajos con su adaptador (`royalty_bps`) | El autor lo fija con tope de plataforma | desde beta |
| **Fine-tuning** | Autores/empresas | Por job / por M tokens de entrenamiento | Referencia centralizada: Llama 3.3 70B SFT ≈ 2,03 USD/M tokens de entrenamiento (Together, mínimo 4 USD, https://www.together.ai/pricing) | futuro |

### De lista de espera a beta (sin dinero real hasta que haya revisión legal y auditoría)
1. **Lista de espera**: sin precios ni pagos. Solo registro de interés. (No existe lista ni cifra de registros todavía: `[POR VERIFICAR]`.)
2. **Alpha cerrada (testnet)**: gratuita, cuota limitada, créditos sin valor monetario, recibos de prueba. Operadores sin pago real. Sin SLA.
3. **Beta de pago**: precio público por token en créditos prepago en euros/USD (no en token); operadores pagados por trabajo verificado con KYC cuando
   corresponda; tope de gasto por cuenta; sin SLA. Requiere auditoría del escrow y cierre de `05`.
4. **GA**: SLA solo para planes business/enclave con métricas medidas, política de precios estable con preaviso de cambios.

## 3. Método para fijar precio

Para cada modelo `m` del catálogo y cada capa:

1. **Suelo (coste del operador)**: `P_suelo = C_op / (Tok_op × cuota_nodo)`, con `C_op` el coste mensual del operador al nivel de utilización objetivo,
   `Tok_op` los millones de tokens que sirve en el mes y `cuota_nodo` la fracción del precio que le llega (80 % sin adaptador en la propuesta).
2. **Margen de operador**: `P_oper = P_suelo × (1 + margen_op)`; el margen da un incentivo mínimo para quedarse (supuesto 20 %).
3. **Techo (alternativas)**: `P_techo = P_ref × (1 - descuento)` donde `P_ref` es el precio mezclado 3:1 de la clase de modelo en 2-3 proveedores y el
   descuento (supuesto 10 %) paga el riesgo de ser nuevo. Para el tier verificado, el techo sube por el valor de recibos/redundancia (supuesto 2-2,5×, a validar con entrevistas).
4. **Decisión**: si `P_oper ≤ P_techo`, el precio es `P_techo`; el sobrante se reparte con la plataforma. **Si `P_oper > P_techo`, no hay negocio comunitario con ese perfil de operador** en ese modelo; o se baja
   el coste (más tok/s por nodo, hardware ya amortizado) o se vende solo como tier con valor diferencial.
5. **Revisión trimestral** con elasticidad medida; el modelo supone –1,2 (`[SUPUESTO]`), y la sensibilidad (–0,6 a –1,8) cambia el ingreso neto del caso base menos de 1 % porque la inferencia comunitaria es una parte pequeña (ver `03`).

Para enclaves: `Cuota = (infra dedicada + soporte + cumplimiento) × (1 + margen)`. Con los supuestos del modelo (1.200 + 2.000 + 600 = 3.800 USD/mes de coste directo;
margen 80/120/160 % según escenario) la cuota sale 6.840 / 8.360 / 9.880 USD/mes. **Es un suelo por coste, no un precio de mercado**: sin cotizaciones ni entrevistas no sabemos si una empresa lo pagaría `[POR VERIFICAR]`.

## 4. Economía del operador

### Fórmulas
Con `u` = utilización del tiempo del nodo (0-1), `h` = 730 h/mes:
- Electricidad: `E = [P_carga × u + P_reposo × (1 - u)] × h / 1000 × p_kWh` (hardware dedicado). Si el hardware ya existe y solo cuenta el consumo añadido: `E = (P_carga - P_reposo) × u × h / 1000 × p_kWh`.
- Amortización: `A = precio_hw × (1 - reventa) / vida_meses`.
- Conectividad: `K` (mensual).
- Coste mensual: `C_op = E + A + K`.
- Tokens servidos: `Tok_op = tps_efectivo × disponibilidad × 2,63·10^6 s × u / 10^6` (millones).
- Precio de equilibrio para el cliente: `P_eq = C_op / (Tok_op × cuota_nodo)`.

### Supuestos usados (todos en `OPERATOR_PROFILES` y `PARAM_TABLE`)
- Electricidad 0,27 €/kWh × 1,10 USD/€ ≈ 0,297 USD/kWh (`[POR VERIFICAR]` FX).
- Rig dedicado: 2.800 USD (4090 usada ≈ 2.200 + 600 de resto del equipo), vida 36 meses, reventa 30 %, 350 W de carga media (de 450 W de TDP) y 40 W de reposo, 15 USD/mes de conectividad. Potencias medias son supuestos.
- PC ya existente: 0 USD de amortización, 300 W de carga y 40 W de reposo (solo el consumo añadido cuenta).
- Mac Apple Silicon ya existente: 45 W de carga y 8 W de reposo (supuesto no medido).
- Throughput por nodo: **cota del simulador 190 tok/s** (0,95 M tok/s / 5.000 nodos, 70B int4, S=8, lote 32; `research/swarm-sim/README.md`). No es una medida; el
  modelo usa 25 % / 50 % / 75 % de esa cota (47,5 / 95 / 142,5 tok/s) y 85 % de disponibilidad.

### Ejemplos (precio estándar 0,1395 USD/M; nodo 80 % del precio; u = 0,5; salida de `finance/output/operator_economics.csv`)
| tok/s efectivos | Perfil | Coste USD/mes | Ingreso USD/mes | Beneficio | Precio de equilibrio USD/M |
|---|---|---|---|---|---|
| 50 | rig dedicado | 111,7 | 6,2 | –105,5 | 2,50 |
| 50 | PC existente | 28,2 | 6,2 | –22,0 | 0,63 |
| 50 | Mac existente | 4,0 | 6,2 | +2,2 | 0,09 |
| 100 | rig dedicado | 111,7 | 12,5 | –99,3 | 1,25 |
| 100 | PC existente | 28,2 | 12,5 | –15,7 | 0,32 |
| 100 | Mac existente | 4,0 | 12,5 | +8,4 | 0,045 |
| 190 (cota) | rig dedicado | 111,7 | 23,7 | –88,1 | 0,66 |
| 190 (cota) | PC existente | 28,2 | 23,7 | –4,5 | 0,17 |
| 190 (cota) | Mac existente | 4,0 | 23,7 | +19,7 | 0,024 |
| 1.000 (hipotético, no es NEXUS) | rig dedicado | 111,7 | 124,6 | +12,9 | 0,125 |

### Qué tiene que cobrar un nodo (conclusiones)
1. **A precio de mercado, un rig dedicado nunca cubre coste** con el throughput que el simulador permite (cota superior). Necesita ≈ 0,66-2,5 USD/M frente a un estándar de 0,14 USD/M: 5-18× más.
   Alquilar la misma GPU en un marketplace (≈ 255 USD/mes) rinde 10-20× más que servir tokens.
2. Un **Mac o PC ya existente** puede cubrir su coste marginal (electricidad) a 0,02-0,09 USD/M en el mejor caso; los ingresos son de unos pocos USD al mes, nada
   que justifique "ganar X al mes". Hay que decirlo así en la web: *pago por trabajo verificado*, sin cifras de ganancia.
3. **La palanca es el throughput por nodo y el precio del tier verificado**, no el porcentaje de reparto. En el modelo (caso base) el beneficio medio por operador pasa de –24,8 USD/mes (50 % de la cota, precio ×0,9) a +1,8 USD/mes con precio ×2,0, y a +31 USD/mes si el rendimiento efectivo es ×2 la cota del simulador (hipotético).
4. **La utilización objetivo casi no ayuda** (sensibilidad: 15-75 % no cambia el ingreso del caso base de forma material) porque en todos los casos la oferta está limitada por la rentabilidad del operador (techo de utilización alcanzado, solo se atiende el 21 % de la demanda del caso base).
5. El **crédito de arranque** (empresa cubre 30-50 % del hueco de coste en los nodos mínimos hasta el mes 20-24) cuesta ≈ 6.400 USD acumulados en el caso base: barato, pero no crea un mercado sostenible.

### Qué debe medirse antes de publicar precios a operadores `[POR VERIFICAR]`
- tok/s agregado real de un nodo en la configuración de slots (hoy el motor Atenhea genera en serie y no hay medición multi-nodo);
- vatios medios en carga de GPUs y Macs reales (no TDP);
- tasa efectiva de canarios/doble ejecución (coste real de la verificación);
- precio que aceptan clientes para el tier verificado (entrevistas).
