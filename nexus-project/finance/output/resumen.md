# Resumen del modelo financiero NEXUS (36 meses)

Generado por `python3 finance/model.py`. **Todo son proyecciones con supuestos** (ver bloque `PARAM_TABLE` en `model.py`):
no existe hoy ningún ingreso, cliente de pago ni liquidación con dinero real (alpha cerrada, testnet, sin token). Moneda: USD.
Ingreso neto = lo que retiene la empresa (comisión de plataforma + tarifas de enclave/SLA/certificación/fine-tuning); el GMV es lo que paga el cliente.

## Financiación derivada del caso base

- Quema acumulada del caso base en la ventana de pre-seed (meses 1-18): **964,542 USD**.
- Pre-seed dimensionada = quema x 1.25, redondeada a 50 k: **1,250,000 USD** (mes 1).
- Seed (mes 19) para cubrir la fosa restante del caso base con el mismo colchón, redondeada a 100 k: **1,700,000 USD**.
- Esta misma financiación se aplica a los tres escenarios para ver quién se queda sin caja.

## Resultados por escenario

| Métrica | Conservador | Base | Optimista |
|---|---|---|---|
| Ingreso neto acumulado 36 m (USD) | 64,844 | 508,977 | 2,074,729 |
| GMV acumulado 36 m (USD) | 7,130 | 61,922 | 317,561 |
| Ingreso neto mes 36 (USD/mes) | 11,286 | 51,647 | 169,787 |
| GMV mes 36 (USD/mes) | 497 | 3,491 | 15,792 |
| Margen bruto mes 36 | -2% | 50% | 65% |
| EBITDA mes 36 (USD/mes) | -75,008 | -92,078 | -63,864 |
| Necesidad máxima de financiación acumulada (USD) | 1,599,273 | 2,326,578 | 2,106,383 |
| Ingreso neto mensual necesario mes 36 para EBITDA = 0 (USD) | 86,294 | 143,725 | 233,651 |
| Contratos enclave ADICIONALES equivalentes para equilibrio mes 36 | 24.7 | 20.2 | 10.5 |
| Caja mínima con la financiación derivada (USD) | 590,390 | 285,458 | 203,663 |
| Mes en que la caja es negativa | no (>36) | no (>36) | no (>36) |
| Punto de equilibrio mensual (EBITDA >= 0, 3 meses seguidos) | no (>36) | no (>36) | no (>36) |
| Caja al mes 36 (USD) | 1,350,727 | 623,422 | 843,617 |
| Cuentas dev mes 36 | 198 | 1,551 | 6,302 |
| Cuentas business mes 36 | 9.3 | 40.4 | 133.0 |
| Contratos enclave mes 36 (esperados) | 1.4 | 5.2 | 13.5 |
| Operadores mes 36 | 43 | 126 | 341 |
| Utilización de nodos mes 36 | 75% | 75% | 75% |
| Demanda atendida mes 36 | 69% | 21% | 7% |
| Beneficio mensual medio por operador mes 36 (USD) | -48.0 | -24.8 | -4.1 |

## Ingresos por línea (mes 36, USD/mes)

| Línea | Conservador | Base | Optimista |
|---|---|---|---|
| Comisión sobre inferencia | 74 | 503 | 2,132 |
| Comisión sobre regalías (trabajos con adaptador) | 1 | 21 | 237 |
| Enclaves/swarms privados | 10,448 | 45,766 | 138,693 |
| Soporte y SLA | 699 | 4,843 | 26,590 |
| Operadores certificados | 65 | 379 | 1,534 |
| Fine-tuning | 0 | 135 | 600 |

## Ingresos netos por trimestre (USD)

| Trimestre | Conservador | Base | Optimista |
|---|---|---|---|
| T1 | 0 | 0 | 0 |
| T2 | 0 | 0 | 0 |
| T3 | 0 | 0 | 490 |
| T4 | 0 | 243 | 3,853 |
| T5 | 20 | 975 | 24,419 |
| T6 | 110 | 3,134 | 95,996 |
| T7 | 516 | 17,929 | 161,924 |
| T8 | 967 | 46,608 | 227,125 |
| T9 | 1,348 | 72,566 | 292,447 |
| T10 | 10,509 | 97,854 | 358,149 |
| T11 | 20,747 | 122,655 | 422,707 |
| T12 | 30,627 | 147,013 | 487,618 |

## Unidad económica (por escenario)

| Concepto | Conservador | Base | Optimista |
|---|---|---|---|
| Precio de referencia mezclado (USD/M tok) | 0.1550 | 0.1550 | 0.1550 |
| Precio estándar NEXUS (USD/M tok) | 0.1395 | 0.1395 | 0.1395 |
| Ingreso (GMV) por petición de 900 tok (USD) | 0.000126 | 0.000126 | 0.000126 |
| Retención de plataforma por petición (USD) | 0.000019 | 0.000019 | 0.000019 |
| GMV mensual por cuenta dev (USD) | 1.27 | 3.17 | 7.92 |
| Ingreso neto mensual por cuenta dev (USD) | 0.190 | 0.475 | 1.187 |
| CAC dev (USD) | 250 | 120 | 80 |
| LTV dev, margen de contribución (USD) | 1.65 | 5.78 | 20.65 |
| Coste mensual de un enclave (USD) | 3,800 | 3,800 | 3,800 |
| Tarifa mensual de enclave coste+margen (USD) | 6,840 | 8,360 | 9,880 |

## Reparto del escrow: actual (75/10/5/5/5) frente a propuesto

| Reparto | Escenario | Ingreso neto acum. 36 m | EBITDA mes 36 | Necesidad de financiación | Beneficio por operador m36 |
|---|---|---|---|---|---|
| current | conservador | 64,131 | -75,058 | 1,599,970 | -47.5 |
| current | base | 502,425 | -92,517 | 2,332,799 | -23.4 |
| current | optimista | 2,038,973 | -65,843 | 2,141,638 | -1.8 |
| proposed | conservador | 64,844 | -75,008 | 1,599,273 | -48.0 |
| proposed | base | 508,977 | -92,078 | 2,326,578 | -24.8 |
| proposed | optimista | 2,074,729 | -63,864 | 2,106,383 | -4.1 |

## Sensibilidad (caso base)

### Precio y elasticidad (precio como fracción del precio de mercado)

| Elasticidad | Precio/mercado | Ingreso neto acum. | Ingreso neto m36 | Necesidad financiación | Beneficio operador m36 |
|---|---|---|---|---|---|
| -0.6 | 0.60 | 506,299 | 51,477 | 2,330,650 | -32.2 |
| -0.6 | 0.70 | 507,115 | 51,533 | 2,329,322 | -29.8 |
| -0.6 | 0.80 | 507,963 | 51,589 | 2,327,983 | -27.3 |
| -0.6 | 0.90 | 508,821 | 51,645 | 2,326,648 | -24.8 |
| -0.6 | 1.00 | 509,647 | 51,701 | 2,325,346 | -22.3 |
| -0.6 | 1.20 | 511,271 | 51,814 | 2,322,790 | -17.3 |
| -0.6 | 1.40 | 512,858 | 51,926 | 2,320,301 | -12.2 |
| -0.6 | 2.00 | 528,713 | 53,385 | 2,304,637 | 2.9 |
| -0.6 | 3.00 | 537,820 | 54,265 | 2,296,853 | 28.4 |
| -1.2 | 0.60 | 506,860 | 51,483 | 2,330,411 | -32.4 |
| -1.2 | 0.70 | 507,685 | 51,539 | 2,329,063 | -29.9 |
| -1.2 | 0.80 | 508,323 | 51,593 | 2,327,814 | -27.4 |
| -1.2 | 0.90 | 508,977 | 51,647 | 2,326,578 | -24.8 |
| -1.2 | 1.00 | 509,647 | 51,701 | 2,325,346 | -22.3 |
| -1.2 | 1.20 | 510,892 | 51,810 | 2,322,999 | -17.2 |
| -1.2 | 1.40 | 512,591 | 51,927 | 2,320,433 | -12.0 |
| -1.2 | 2.00 | 520,583 | 53,008 | 2,311,061 | 1.8 |
| -1.2 | 3.00 | 514,724 | 52,534 | 2,314,673 | 19.1 |
| -1.8 | 0.60 | 506,995 | 51,483 | 2,330,376 | -32.5 |
| -1.8 | 0.70 | 508,008 | 51,542 | 2,328,911 | -30.0 |
| -1.8 | 0.80 | 508,719 | 51,597 | 2,327,621 | -27.4 |
| -1.8 | 0.90 | 509,147 | 51,648 | 2,326,499 | -24.9 |
| -1.8 | 1.00 | 509,647 | 51,701 | 2,325,346 | -22.3 |
| -1.8 | 1.20 | 510,863 | 51,812 | 2,322,972 | -17.1 |
| -1.8 | 1.40 | 511,804 | 51,918 | 2,320,947 | -11.8 |
| -1.8 | 2.00 | 510,338 | 52,158 | 2,319,233 | 0.4 |
| -1.8 | 3.00 | 503,996 | 51,571 | 2,323,395 | 20.1 |

### Utilización objetivo de los nodos

| Util. objetivo | Util. m36 | Operadores m36 | Demanda atendida m36 | Ingreso neto acum. | Incentivos a operadores acum. | Beneficio operador m36 | Necesidad financiación |
|---|---|---|---|---|---|---|---|
| 0.15 | 75% | 130 | 22% | 510,392 | 6,229 | -24.8 | 2,325,564 |
| 0.25 | 75% | 129 | 21% | 510,179 | 6,273 | -24.8 | 2,325,733 |
| 0.35 | 75% | 128 | 21% | 509,558 | 6,361 | -24.8 | 2,326,197 |
| 0.45 | 75% | 126 | 21% | 508,977 | 6,384 | -24.8 | 2,326,578 |
| 0.55 | 75% | 125 | 21% | 508,549 | 6,384 | -24.8 | 2,326,845 |
| 0.65 | 75% | 125 | 21% | 508,205 | 6,384 | -24.8 | 2,327,062 |
| 0.75 | 75% | 124 | 21% | 508,003 | 6,384 | -24.8 | 2,327,190 |

### Coste de adquisición

| Multiplicador CAC | CAC (USD) | Cuentas dev m36 | Ingreso neto acum. | Necesidad financiación | LTV/CAC |
|---|---|---|---|---|---|
| 0.50 | 60 | 2,786 | 509,631 | 2,326,397 | 0.10 |
| 0.75 | 90 | 1,962 | 509,223 | 2,326,522 | 0.06 |
| 1.00 | 120 | 1,551 | 508,977 | 2,326,578 | 0.05 |
| 1.50 | 180 | 1,139 | 508,719 | 2,326,596 | 0.03 |
| 2.00 | 240 | 933 | 508,560 | 2,326,593 | 0.02 |
| 3.00 | 360 | 727 | 508,428 | 2,326,545 | 0.02 |

### Rendimiento por nodo (fracción de la cota del simulador, 190 tok/s; >1 es hipotético)

| Fracción de la cota | tok/s efectivos | Beneficio operador m36 | Operadores m36 | Demanda atendida m36 | GMV m36 | Ingreso neto m36 | Necesidad financiación |
|---|---|---|---|---|---|---|---|
| 0.25 | 47.5 | -35.8 | 129 | 11% | 1,787 | 51,400 | 2,331,735 |
| 0.50 | 95.0 | -24.8 | 126 | 21% | 3,491 | 51,647 | 2,326,578 |
| 0.75 | 142.5 | -13.8 | 124 | 31% | 5,154 | 51,890 | 2,321,737 |
| 1.00 | 190.0 | -2.8 | 124 | 41% | 6,838 | 52,141 | 2,316,840 |
| 2.00 | 380.0 | 31.0 | 183 | 100% | 16,606 | 53,784 | 2,306,312 |
| 4.00 | 760.0 | 94.5 | 99 | 100% | 16,606 | 53,531 | 2,308,109 |

### Contratos enclave nuevos por trimestre (caso base)

| Nuevos/trimestre | Enclaves m36 | Ingreso neto m36 | EBITDA m36 | Necesidad financiación | Equilibrio (mes) |
|---|---|---|---|---|---|
| 0.0 | 0.0 | 5,880 | -117,951 | 2,581,187 | no (>36) |
| 0.5 | 2.6 | 28,764 | -105,014 | 2,453,883 | no (>36) |
| 1.0 | 5.2 | 51,647 | -92,078 | 2,326,578 | no (>36) |
| 2.0 | 10.5 | 97,413 | -66,206 | 2,071,969 | no (>36) |
| 3.0 | 15.7 | 143,180 | -40,333 | 1,817,360 | no (>36) |
| 4.0 | 20.9 | 188,946 | -14,460 | 1,562,751 | no (>36) |
| 6.0 | 31.4 | 280,479 | 37,285 | 1,311,469 | 27 |

### Tamaño del equipo (caso base)

| Multiplicador de plantilla | FTE mes 36 | Ingreso neto necesario m36 | Ingreso neto m36 | EBITDA m36 | Necesidad financiación | Equilibrio (mes) |
|---|---|---|---|---|---|---|
| 0.50 | 6.5 | 102,450 | 51,647 | -50,803 | 1,383,603 | no (>36) |
| 0.75 | 9.8 | 123,087 | 51,647 | -71,441 | 1,855,091 | no (>36) |
| 1.00 | 13.0 | 143,725 | 51,647 | -92,078 | 2,326,578 | no (>36) |
| 1.25 | 16.2 | 164,362 | 51,647 | -112,716 | 2,798,066 | no (>36) |

## Economía del operador (caso base, precio estándar, comisión propuesta)

Parámetros de hardware y potencia en `OPERATOR_PROFILES`; electricidad 0.27 EUR/kWh x 1.10 USD/EUR. `node_tps` NO está medido.

| tok/s por nodo | Util. | Perfil | M tok/mes | Coste USD/mes | Ingreso USD/mes | Beneficio | Precio de equilibrio USD/M tok (vs estándar 0.1395) |
|---|---|---|---|---|---|---|---|
| 20 | 0.3 | dedicated | 13.4 | 98.3 | 1.5 | -96.8 | 9.1710 |
| 20 | 0.3 | sunk | 13.4 | 16.9 | 1.5 | -15.4 | 1.5781 |
| 20 | 0.3 | mac | 13.4 | 2.4 | 1.5 | -0.9 | 0.2246 |
| 20 | 0.5 | dedicated | 22.3 | 111.7 | 2.5 | -109.2 | 6.2552 |
| 20 | 0.5 | sunk | 22.3 | 28.2 | 2.5 | -25.7 | 1.5781 |
| 20 | 0.5 | mac | 22.3 | 4.0 | 2.5 | -1.5 | 0.2246 |
| 20 | 0.7 | dedicated | 31.3 | 125.2 | 3.5 | -121.7 | 5.0056 |
| 20 | 0.7 | sunk | 31.3 | 39.5 | 3.5 | -36.0 | 1.5781 |
| 20 | 0.7 | mac | 31.3 | 5.6 | 3.5 | -2.1 | 0.2246 |
| 50 | 0.3 | dedicated | 33.5 | 98.3 | 3.7 | -94.5 | 3.6684 |
| 50 | 0.3 | sunk | 33.5 | 16.9 | 3.7 | -13.2 | 0.6312 |
| 50 | 0.3 | mac | 33.5 | 2.4 | 3.7 | 1.3 | 0.0898 |
| 50 | 0.5 | dedicated | 55.8 | 111.7 | 6.2 | -105.5 | 2.5021 |
| 50 | 0.5 | sunk | 55.8 | 28.2 | 6.2 | -22.0 | 0.6312 |
| 50 | 0.5 | mac | 55.8 | 4.0 | 6.2 | 2.2 | 0.0898 |
| 50 | 0.7 | dedicated | 78.1 | 125.2 | 8.7 | -116.4 | 2.0022 |
| 50 | 0.7 | sunk | 78.1 | 39.5 | 8.7 | -30.7 | 0.6312 |
| 50 | 0.7 | mac | 78.1 | 5.6 | 8.7 | 3.1 | 0.0898 |
| 100 | 0.3 | dedicated | 67.0 | 98.3 | 7.5 | -90.8 | 1.8342 |
| 100 | 0.3 | sunk | 67.0 | 16.9 | 7.5 | -9.4 | 0.3156 |
| 100 | 0.3 | mac | 67.0 | 2.4 | 7.5 | 5.1 | 0.0449 |
| 100 | 0.5 | dedicated | 111.6 | 111.7 | 12.5 | -99.3 | 1.2510 |
| 100 | 0.5 | sunk | 111.6 | 28.2 | 12.5 | -15.7 | 0.3156 |
| 100 | 0.5 | mac | 111.6 | 4.0 | 12.5 | 8.4 | 0.0449 |
| 100 | 0.7 | dedicated | 156.3 | 125.2 | 17.4 | -107.7 | 1.0011 |
| 100 | 0.7 | sunk | 156.3 | 39.5 | 17.4 | -22.0 | 0.3156 |
| 100 | 0.7 | mac | 156.3 | 5.6 | 17.4 | 11.8 | 0.0449 |
| 190 | 0.3 | dedicated | 127.3 | 98.3 | 14.2 | -84.1 | 0.9654 |
| 190 | 0.3 | sunk | 127.3 | 16.9 | 14.2 | -2.7 | 0.1661 |
| 190 | 0.3 | mac | 127.3 | 2.4 | 14.2 | 11.8 | 0.0236 |
| 190 | 0.5 | dedicated | 212.1 | 111.7 | 23.7 | -88.1 | 0.6584 |
| 190 | 0.5 | sunk | 212.1 | 28.2 | 23.7 | -4.5 | 0.1661 |
| 190 | 0.5 | mac | 212.1 | 4.0 | 23.7 | 19.7 | 0.0236 |
| 190 | 0.7 | dedicated | 296.9 | 125.2 | 33.1 | -92.0 | 0.5269 |
| 190 | 0.7 | sunk | 296.9 | 39.5 | 33.1 | -6.3 | 0.1661 |
| 190 | 0.7 | mac | 296.9 | 5.6 | 33.1 | 27.5 | 0.0236 |
| 1,000 | 0.3 | dedicated | 669.8 | 98.3 | 74.7 | -23.5 | 0.1834 |
| 1,000 | 0.3 | sunk | 669.8 | 16.9 | 74.7 | 57.8 | 0.0316 |
| 1,000 | 0.3 | mac | 669.8 | 2.4 | 74.7 | 72.3 | 0.0045 |
| 1,000 | 0.5 | dedicated | 1,116.3 | 111.7 | 124.6 | 12.9 | 0.1251 |
| 1,000 | 0.5 | sunk | 1,116.3 | 28.2 | 124.6 | 96.4 | 0.0316 |
| 1,000 | 0.5 | mac | 1,116.3 | 4.0 | 124.6 | 120.6 | 0.0045 |
| 1,000 | 0.7 | dedicated | 1,562.8 | 125.2 | 174.4 | 49.2 | 0.1001 |
| 1,000 | 0.7 | sunk | 1,562.8 | 39.5 | 174.4 | 134.9 | 0.0316 |
| 1,000 | 0.7 | mac | 1,562.8 | 5.6 | 174.4 | 168.8 | 0.0045 |

Dilución orientativa de una ronda con el importe derivado (aritmética pura, valoración PRE-money hipotética):

| Pre-money hipotético (USD) | Pre-seed 1,250,000 | Seed 1,700,000 |
|---|---|---|
| 3,000,000 | 29.4% | 22.1% |
| 5,000,000 | 20.0% | 14.5% |
| 8,000,000 | 13.5% | 9.6% |

(La columna seed asume un pre-money del doble que el de la pre-seed; es un ejemplo, no una valoración.)

