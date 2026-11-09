# 03 · Plan de ingresos

Fecha: 2026-10-27. Fuente de todos los números de este documento: `python3 finance/model.py` (salida en `finance/output/`, resumen en `finance/output/resumen.md`;
22 tests `unittest` pasan). **Son proyecciones con supuestos, no previsiones ni compromisos.** Hoy: cero ingresos, cero clientes de pago,
alpha cerrada en testnet, sin token. Moneda: USD.

## 1. Resultado en una frase

Con el plan de costes diseñado (equipo de 4 a 13 personas en el caso base), **ninguno de los tres escenarios alcanza el punto de equilibrio en 36 meses**: el
ingreso neto del mes 36 es de 11 k / 52 k / 170 k USD/mes frente a una necesidad de 86 k / 144 k / 234 k USD/mes para EBITDA cero. El caso optimista queda más cerca (le faltan ≈ 10 contratos de enclave adicionales
equivalentes). Esto es un resultado del modelo y de sus supuestos, no una predicción de lo que ocurrirá.

## 2. Escenarios (resultados reales del script)

| Métrica | Conservador | Base | Optimista |
|---|---|---|---|
| Primer mes con ingresos (pagos reales) | 13 | 10 | 8 |
| Ingreso neto acumulado 36 m (USD) | 64.844 | 508.977 | 2.074.729 |
| GMV acumulado 36 m (USD) | 7.130 | 61.922 | 317.561 |
| Ingreso neto mes 36 (USD/mes) | 11.286 | 51.647 | 169.787 |
| GMV mes 36 (USD/mes) | 497 | 3.491 | 15.792 |
| Margen bruto mes 36 | –2 % | 50 % | 65 % |
| EBITDA mes 36 (USD/mes) | –75.008 | –92.078 | –63.864 |
| Ingreso neto necesario mes 36 para EBITDA = 0 | 86.294 | 143.725 | 233.651 |
| Necesidad máxima de financiación acumulada (USD) | 1.599.273 | 2.326.578 | 2.106.383 |
| Caja mínima con la financiación derivada (1,25 M + 1,70 M) | 590.390 | 285.458 | 203.663 |
| Caja al mes 36 | 1.350.727 | 623.422 | 843.617 |
| Cuentas dev / business / enclaves (mes 36) | 198 / 9 / 1,4 | 1.551 / 40 / 5,2 | 6.302 / 133 / 13,5 |
| Operadores mes 36 | 43 | 126 | 341 |
| Demanda atendida mes 36 | 69 % | 21 % | 7 % |
| Beneficio por operador mes 36 (USD/mes, media mezclada) | –48,0 | –24,8 | –4,1 |
| Equilibrio mensual (EBITDA ≥ 0 tres meses) | no (>36) | no (>36) | no (>36) |

Notas de lectura:
- La **financiación 1,25 M + 1,70 M** se deriva del caso base (ver `04`), y se aplica igual a los tres para ver quién se queda sin caja: ninguno la agota; la caja base cae a 285 k en el mes 18 (justo antes de la seed).
- "Demanda atendida" baja en los escenarios con más demanda: la oferta está limitada por la rentabilidad de los operadores (ver sección 5). El 7 % del optimista significa que **el 93 % de la demanda supuesta no se sirve**: señal de que el supuesto de demanda dev del optimista (6.302 cuentas) no es coherente con la oferta a ese precio.
- El caso optimista tiene un EBITDA mes 36 mejor pero necesita más capital que el base porque contrata más rápido desde el mes 19.
- Estacionalidad, impuestos, IVA, capital circulante, FX y cuotas de pago no financiadas se omiten (ver límites).

### Ingreso neto por trimestre (USD) y hitos
| Trimestre | Conservador | Base | Optimista | Hito de ingresos (caso base) |
|---|---|---|---|---|
| T1 (m1-3) | 0 | 0 | 0 | Alpha cerrada; sin pagos |
| T2 (m4-6) | 0 | 0 | 0 | Opiniones legales, auditoría del escrow contratada |
| T3 (m7-9) | 0 | 0 | 490 | Beta cerrada, sin dinero real (en el base) |
| T4 (m10-12) | 0 | 243 | 3.853 | **Primeros pagos reales**: lista de espera convertida; menos de 250 USD de ingreso neto |
| T5 (m13-15) | 20 | 975 | 24.419 | |
| T6 (m16-18) | 110 | 3.134 | 95.996 | GA y primeras cuentas business |
| T7 (m19-21) | 516 | 17.929 | 161.924 | Seed cerrada; certificación de operadores |
| T8 (m22-24) | 967 | 46.608 | 227.125 | **Primer contrato de enclave** (mes 20 en el base) |
| T9 (m25-27) | 1.348 | 72.566 | 292.447 | |
| T10 (m28-30) | 10.509 | 97.854 | 358.149 | |
| T11 (m31-33) | 20.747 | 122.655 | 422.707 | Fine-tuning (hipótesis, mes 33) |
| T12 (m34-36) | 30.627 | 147.013 | 487.618 | ≈ 5 contratos de enclave en el base |

### Ingresos por línea, mes 36 (USD/mes)
| Línea | Conservador | Base | Optimista |
|---|---|---|---|
| Comisión sobre inferencia | 74 | 503 | 2.132 |
| Comisión sobre regalías (adaptadores) | 1 | 21 | 237 |
| Enclaves (cuota + altas) | 10.448 | 45.766 | 138.693 |
| Soporte y SLA | 699 | 4.843 | 26.590 |
| Operadores certificados | 65 | 379 | 1.534 |
| Fine-tuning | 0 | 135 | 600 |

**Lectura honesta**: ≈ 89 % del ingreso base del mes 36 son enclaves (99 % con SLA y certificación; la inferencia es el 1 %), con 5 contratos esperados `[SUPUESTO]` para los que no hay ninguna conversación comercial documentada. Si esa
línea no existe, el modelo no tiene negocio en 36 meses (sensibilidad "0 contratos/trimestre": ingreso neto m36 = 5.880 USD/mes, necesidad de financiación 2,58 M).

## 3. Unidad económica

Caso base, precio estándar 0,1395 USD/M tokens (10 % bajo la referencia 70B de 0,155 USD/M, DeepInfra 2026-10-27), reparto propuesto (plataforma 15 %).

### Por petición (900 tokens: 600 entrada + 300 salida, supuesto)
| Concepto | USD |
|---|---|
| Lo que paga el cliente (GMV) | 0,000126 |
| Retención de plataforma (15 %) | 0,000019 |
| Pago al nodo (80 % sin adaptador) | 0,000101 |
| Verificación (5 %) | 0,000006 |
| Coste variable de infraestructura (0,004 USD/M tok, supuesto) | 0,0000036 |
| Coste de pago (3 % del GMV, `[POR VERIFICAR]`) | 0,0000038 |

Contribución de la plataforma por petición ≈ 0,0000116 USD: son 86.000 peticiones para generar 1 USD de contribución. Una nómina de 6.000 USD/mes exigiría ≈ 520 millones de peticiones al mes
(≈ 470 mil millones de tokens al mes) solo con la comisión de inferencia; es el motivo de que el plan no dependa de ella.

### Por operador (caso base, `02-precios.md`)
Coste medio mezclado ≈ 28 USD/mes (rig dedicado 20 %, PC existente 45 %, Mac 35 %). Ingreso medio mezclado negativo en el escenario base (–24,8 USD/mes en el mes 36). Para que el operador medio cubra costes a u = 0,5:
- precio de equilibrio ≈ **0,43 USD/M** con el 50 % de la cota del simulador (3,1× el estándar de 0,1395);
- ≈ 0,21 USD/M con el 100 % de la cota (1,5×);
- con el doble de la cota (hipotético) basta u ≈ 0,30.
Sin esa condición la oferta no crece sola y hace falta crédito de arranque (en el modelo: 6.384 USD acumulados en el base, cubre solo los nodos mínimos).

### Por cliente
| Segmento | Ingreso neto/mes | CAC | LTV | Comentario |
|---|---|---|---|---|
| Dev self-serve (base) | 0,47 | 120 USD (supuesto) | 5,78 (contribución/churn 5 %) | **LTV/CAC = 0,05; recuperación 415 meses.** En conservador 0,01; optimista 0,26 (20,65 / 80). Un dev self-serve no se paga con paid marketing. |
| Business (base) | ≈ 28 de comisión (si se sirve toda la demanda; con 21 % atendido, ≈ 6) + 120 de SLA (40 % de adjunto × 300) ≈ 126-148 | no modelado: comercial en nómina | ≈ 150 / 2 % = 7.400 (sin descontar) | El CAC real depende de ventas que el modelo carga en la plantilla, no en marketing `[POR VERIFICAR]` |
| Enclave (base) | 8.360 de cuota − 3.800 de coste directo = 4.560 de contribución + alta 6.000 | no modelado | 4.560 / 1 % de churn = 456 k (sin descontar, vida implícita de 100 meses: **optimista**) | Margen bruto 55 % por supuesto de markup; no es un precio de mercado `[POR VERIFICAR]` |

Sensibilidad al CAC (`finance/output/sensitivity_cac.csv`): reducir el CAC a la mitad multiplica por 1,8 las cuentas dev del mes 36 (2.786 frente a 1.551) pero el ingreso neto acumulado sube solo 0,13 % (509.631 frente a 508.977 USD); con CAC ×3 baja a 508.428. **Con este precio unitario, el CAC es irrelevante porque ningún CAC pagado por cuenta se recupera.** El primer canal debe ser orgánico y de comunidad, y la métrica clave pasa
a ser contratos de enclave y cuentas business, no cuentas dev.

## 4. Utilización necesaria para ser sostenible

- **Del operador**: a precios de mercado, un rig dedicado no cubre coste a ninguna utilización con la cota del simulador (a 190 tok/s y u = 0,7 pierde ≈ 99 USD/mes). El Mac cubre su coste marginal a cualquier utilización razonable pero gana ≈ 20 USD/mes como máximo a la cota. La utilización objetivo 15-75 % apenas mueve los resultados del caso base (`sensitivity_utilization.csv`: ingreso neto acumulado entre 508.003 y 510.392 USD para objetivos de 0,75 a 0,15) porque el techo de utilización (75 %) y la rentabilidad del operador son los límites reales.
- **De la red**: los 40 nodos mínimos de GA (S = 8 × 5), al 50 % de la cota (95 tok/s) y 85 % de disponibilidad, con u = 0,45 sirven ≈ 3.800 M tokens/mes y generan ≈ 530 USD/mes de GMV (≈ 0,7 USD/h), de los que la plataforma retiene ≈ 80 USD/mes. **No cubre ni el coste de su infraestructura de coordinación (6.000 USD/mes en GA).** La economía de la red necesita precio por token mayor (tier verificado/enclave) o rendimiento por nodo ≥ 2× la cota del simulador.
- **De la empresa**: el equilibrio depende de contratos de enclave, no de utilización. Cada contrato adicional aporta 4.560 USD/mes de contribución en el caso base; con 143.725 USD/mes de ingreso necesario en el mes 36 hacen falta ≈ 20 contratos adicionales a los 5,2 esperados (25 en total) o una plantilla menor (con la mitad de plantilla, 6,5 FTE, el ingreso necesario baja a 102 k USD/mes).

## 5. Sensibilidades relevantes (caso base)
| Palanca | Rango | Efecto |
|---|---|---|
| Precio (elasticidad –1,2) | ×0,6 – ×3,0 del mercado | El ingreso neto del mes 36 se mueve entre 51.483 y 53.008 USD/mes: **el precio no es la palanca de la empresa** a estos volúmenes; sí lo es del operador (beneficio por operador de –32 a +19 USD/mes). |
| Elasticidad | –0,6 / –1,2 / –1,8 | < 1 % en ingreso neto. |
| Rendimiento por nodo | 25 % – 400 % de la cota | Con ≥ 200 % de la cota el operador mezclado pasa a beneficio positivo (+31 USD/mes) y la demanda se atiende al 100 %; el ingreso neto del mes 36 sube solo de 51.400 a 53.784 USD/mes (ver `sensitivity_throughput.csv`). |
| Contratos de enclave por trimestre | 0 – 6 | Ingreso neto m36 de 5.880 a 280.479 USD/mes; la necesidad de financiación baja de 2,58 M a 1,31 M; con 6 contratos nuevos por trimestre (31 en el mes 36, cota muy exigente) aparece equilibrio en el mes 27. **Es la única palanca grande.** |
| Plantilla | ×0,5 – ×1,25 | Necesidad de financiación de 1,38 M (×0,5) a 2,80 M (×1,25). |
| Reparto del escrow actual frente al propuesto | 75/10/5/5/5 vs 70-80/10/5/15/0 | +1,3 % en ingreso neto acumulado base (502 k → 509 k). Irrelevante para la caja; relevante para sostenibilidad del protocolo. |

## 6. Qué tiene que ser cierto para que funcione
1. **Hay empresas dispuestas a pagar ≈ 8-10 k USD/mes por un swarm privado** con nodos propios o certificados, y se pueden cerrar ≈ 1 contrato por trimestre desde el mes 20 (base). Nada de esto está validado `[POR VERIFICAR]`: el siguiente paso es 20-30 entrevistas de descubrimiento antes de contratar más allá de la ingeniería mínima.
2. **El throughput real por nodo ≥ 50 % de la cota del simulador** (95 tok/s en un nodo de slot de un modelo 70B) con latencia aceptable; hoy está sin medir y el motor Atenhea genera en serie.
3. **Los operadores aceptan cobrar poco por trabajo verificado** (Macs y PCs ya existentes) o existe un tier verificado que cliente pague 2-3× el mercado.
4. **Auditoría del escrow + opinión legal sobre pagos** completadas antes del primer pago real (mes 10 en el base); sin ellas el calendario se retrasa y el gasto de legal y auditorías (≈ 297 k USD en 36 meses del caso base: 137,5 k legal + 160 k auditorías) se adelanta.
5. **No se promete rendimiento a operadores** ni se vende un token en el horizonte; si el negocio dependiera de ello sería otro negocio con otro riesgo regulatorio.
6. **El coste de equipo se mantiene** en ≈ 6.000 USD/mes por FTE y la plantilla crece solo con hitos (si no, la caja no llega).

## 7. Límites del modelo
- Sin impuestos (sociedades, IVA/OSS), capital circulante, ni capex. FX fijo (1,10 USD/€).
- Demanda dev y business **sin evidencia**; el optimista supone una demanda que la oferta no puede servir.
- El CAC de cuentas business y enclave no está modelado: va en la plantilla.
- Las sensibilidades alteran una variable cada vez; no hay correlaciones.
- El crédito de arranque a operadores se modela como gasto de la empresa y debe aprobarse legalmente (`05`).
