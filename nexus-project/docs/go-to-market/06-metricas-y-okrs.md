# 06 · Métricas y OKRs

Fecha: 2026-10-27. No existen datos de partida: **toda meta es un supuesto** `[SUPUESTO]` y se recalibra tras las primeras 4 semanas de alpha. Las métricas de producto/red salen del libro de contribuciones y del router; no se reportan métricas de vanidad. Datos personales: mínimos y con consentimiento (RGPD).

## 1. Embudo por lado

### 1.1 Operadores
`Visita landing -> Lista de espera (operador) -> Formulario de aptitud -> Invitado -> Instalado -> Nodo conectado -> Activo (>=1 trabajo verificado en 7 días) -> Retenido (activo 4 de 6 semanas)`

### 1.2 Desarrolladores
`Visita landing/repo -> Lista de espera -> Invitado -> Clave creada -> Primera petición con éxito -> Uso semanal (>=1 petición en 7 días) -> Uso repetido (4 de 6 semanas)`

### 1.3 Autores de modelos
`Interés -> Aptitud (licencia) -> Modelo publicado (manifiesto firmado) -> Modelo servido en red -> Peticiones recibidas -> Regalía (testnet) acreditada`

## 2. Métricas por lado

### Operadores (oferta)
| Métrica | Definición | Fuente |
|---|---|---|
| Nodos conectados / activos | Heartbeat <60 s y >=1 trabajo en 7 días | Router |
| Operadores distintos y redes distintas | Organizaciones/ASN únicos (clave para H1 y para el límite de coalición) | Registro |
| Concentración | % del slot que ocupa el mayor operador (simulación: ~21 %) | Coordinador |
| Disponibilidad | Uptime medio por nodo | Router |
| Tiempo de unión a slot | p50/p95 (simulación: ~60 s / ~231 s con S=16) | Agente |
| Trabajos verificados por nodo y `work_share` | Reparto real | Libro |
| Retención de operadores | % activos a 4 y 8 semanas | Cohortes |
| Tiquets de soporte por nodo | Carga de soporte | COM |

### Desarrolladores (demanda)
| Métrica | Definición |
|---|---|
| Tiempo hasta la primera petición exitosa | Mediana desde la invitación |
| Peticiones/semana y tokens/semana | Reales, sin trabajo sintético |
| Tasa de éxito | Trabajos completados / enviados |
| Latencia p50/p95 y tokens/s por stream | Medidas reales (contrastar con simulación 4–6 tok/s) |
| Coste real por 1.000 tokens | Coste de red incluyendo verificación y gas |
| Retención | Activos a 4 y 8 semanas |
| Motivo de abandono | Encuesta de 1 pregunta |

### Autores
| Métrica | Definición |
|---|---|
| Modelos publicados y servidos | Contador |
| Peticiones por modelo | Contador |
| Regalías de testnet acreditadas | Libro |
| Incidencias de licencia | Contador (objetivo 0) |

### Red y confianza
| Métrica | Definición |
|---|---|
| Discrepancia de tokens | Router (H0: 0 % en pruebas locales) |
| Recibos válidos | % recibos con firma válida |
| Incidentes de seguridad | Contador y tiempo de resolución |
| Trabajos sintéticos vs reales | Se reportan por separado siempre |
| Respuesta a la comunidad | Tiempo medio de primera respuesta |

### Marketing
| Métrica | Notas |
|---|---|
| Visitas -> lista (conversión) | Por canal y por titular |
| Calidad de lista | % que responde al Email 1 |
| Estrellas/forks de GitHub y contribuciones externas | Indicador secundario |
| Menciones y tono | Cualitativo; vigilar especulación de token |
| Coste de adquisición | Solo si hay gasto de pago; en pre-lanzamiento ~0 |

## 3. OKRs

Todos los números son `[SUPUESTO]`. Los trimestres siguen el plan de 04 (T1 = nov-2026 a ene-2027; T2 = feb a abr-2027; T3 = may a jul-2027). Si el producto no cumple las puertas, los OKRs de fase siguiente no empiezan.

### T1 (pre-lanzamiento y arranque de alpha)
**O1. Construir una lista de espera cualificada y entender a los tres lados.**
- KR1: 400–1.000 inscritos con rol declarado.
- KR2: 30 entrevistas realizadas, con un informe de dolores publicado.
- KR3: titular ganador con >= 100 visitantes por variante.
**O2. Lanzar la alpha con operadores reales y distintos.**
- KR1: 8–16 operadores de >= 3 organizaciones conectados.
- KR2: >= 70 % de operadores con >= 1 trabajo verificado semanal durante 4 semanas.
- KR3: demo y evidencia H1 publicadas.
**O3. Mantener credibilidad.**
- KR1: 0 afirmaciones públicas fuera de la lista de 02 (revisión mensual).
- KR2: informe semanal de red publicado >= 6 semanas seguidas, con métricas negativas incluidas.
- KR3: decisión de nombre documentada.

### T2 (alpha ampliada y preparación de beta)
**O1. Demostrar valor para desarrolladores batch.**
- KR1: 15–30 desarrolladores invitados; >= 40 % con uso semanal.
- KR2: coste real por 1.000 tokens y latencia medidos y publicados.
- KR3: >= 3 casos de uso repetidos documentados (anónimos y con permiso).
**O2. Robustez.**
- KR1: tasa de éxito de trabajos >= 95 % durante 2 semanas.
- KR2: liquidación de lotes en testnet pública con transacciones verificables.
- KR3: auditoría independiente contratada o calendarizada.
**O3. Autores.**
- KR1: 2–5 modelos publicados por >= 2 autores; 0 incidencias de licencia.

### T3 (beta pública)
**O1. Crecer con calidad.**
- KR1: 100–300 nodos registrados; >= 30 % activos semanales.
- KR2: 300–1.000 desarrolladores registrados; >= 20 % con uso semanal.
**O2. Comunidad sana.**
- KR1: tiempo de primera respuesta < 24 h; 0 hilos de especulación de token sin moderar > 12 h.
**O3. Preparar GA.**
- KR1: auditoría completada con hallazgos críticos cerrados.
- KR2: precios publicados basados en coste real; decisión legal sobre liquidación real documentada.

## 4. Cuadro de mando (semanal)

Una página, publicada internamente cada lunes; versión pública resumida en el informe de red.

| Bloque | Indicadores | Verde / Ámbar / Rojo `[SUPUESTO]` |
|---|---|---|
| Lista | Altas/semana; % rol; conversión | V: crece; A: plano 2 sem; R: cae 3 sem |
| Oferta | Nodos activos; operadores distintos; concentración máx. | V: >= objetivo; R: un operador > 30 % de un slot |
| Demanda | Peticiones reales/semana; usuarios activos; éxito | V: éxito >= 95 %; R: < 85 % |
| Rendimiento | tok/s p50; latencia p95; coste/1k tokens | Contrastar con simulación; R: > 5× peor que lo simulado |
| Confianza | Recibos válidos; discrepancia; incidentes | R: cualquier incidente de severidad alta |
| Comunidad | Respuesta; sentimiento; hilos de token | R: especulación persistente |
| Marca | Estado de anterioridades; menciones de confusión con otros "Nexus" | R: carta de cese o reclamación |

## 5. Señales de pivotar o seguir

**Seguir (todas a la vez durante 8 semanas de alpha):**
- Operadores activos sin pago real: >= 60 % se mantienen.
- >= 3 desarrolladores repiten uso semanal sin que se les empuje.
- Tasa de éxito de trabajos >= 95 % y recibos válidos 100 %.
- Rendimiento dentro de un factor de 3 de lo simulado y coste real medido de forma comprensible.
- Sin incidentes graves de seguridad.

**Ajustar (una o dos señales fallan):**
- Si falta demanda pero hay oferta: reorientar a investigación/laboratorio y a cargas sintéticas con universidades.
- Si falta oferta: ampliar a universidades y a hosting pequeño; revisar requisitos de VRAM/slot.
- Si el rendimiento es mucho peor que el simulado: reducir S o centrarse en lotes; revisar corte por capa.

**Pivotar (varias señales fallan o una crítica):**
- Nadie, tras 12 semanas y 30 entrevistas, identifica un caso de uso batch donde el diseño aporte algo sobre alternativas centralizadas baratas (01 §4: 0,10–1,25 $/M tokens).
- Los operadores solo participan por especulación de token: señal de que el interés no es por el producto. Rechazar; no cambiar el discurso.
- El coste real por 1.000 tokens (incluyendo verificación y gas) supera con holgura al de proveedores centralizados y no hay otra propuesta de valor sostenible.
- Evidencia de que las coaliciones pequeñas reconstruyen modelos con coste bajo y las palancas (huella, comisión, identidad) no funcionan: replantear como producto de investigación o de modelos de bajo secreto.
- Reclamación de marca no resuelta: renombrar (01 §7).

**Posibles pivotes (a evaluar, no decididos):** (a) herramienta de inferencia verificable para equipos con varios proveedores; (b) red académica de investigación; (c) producto para autores sobre un solo operador con cifrado en reposo; (d) simulador y publicación abierta como contribución de investigación.

## 6. Cadencia de revisión

- Semanal: cuadro de mando (GTM + CTO + COM).
- Fin de fase: revisión de puertas y KPIs con CEO; decisiones por escrito.
- Mensual: auditoría de mensajes contra 02.
