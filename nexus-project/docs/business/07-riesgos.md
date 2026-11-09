# 07 · Registro de riesgos

Fecha: 2026-10-27. Probabilidad (P) e impacto (I): Baja / Media / Alta, **juicio del equipo de negocio** sin datos históricos. Las señales tempranas son medibles. Fuentes: `BRIEF.md`, `EXECUTIVE_BRIEF.md`, `research/swarm-sim`, `finance/output/resumen.md`.

## Técnicos
| ID | Riesgo | P | I | Mitigación | Señal temprana |
|---|---|---|---|---|---|
| T1 | El throughput por nodo es muy inferior a la cota del simulador (190 tok/s) y la economía del operador no cierra; hoy el motor Atenhea genera en serie y no hay medición multi-nodo | Alta | Alta | Medir ya H1 de dos y cuatro nodos; priorizar modelos y cuantización que reduzcan la red; considerar solo enclaves con nodos colocalizados | tok/s medido < 50 % de la cota (95 tok/s) en el primer ensayo multi-nodo |
| T2 | Latencia por salto de slots hace inviable el chat interactivo (S=8 ≈ 2,5-7 tok/s por stream) | Alta | Media | Posicionar la red para lote/agentes; elegir S por caso de uso; ofrecer tier de baja latencia colocalizado solo en enclave | p50 de TTFT y tok/s por stream en beta |
| T3 | Coaliciones y Sybil reconstruyen el modelo (2 % de operadores ⇒ P≈0,44 con ~300 nodos por slot; 16 slots por ≈ 770 USD ilustrativo) | Media | Alta | Comunicación honesta; coste de identidad (KYC de operadores certificados), comisión de registro, huella por nodo (investigación), TEE; no usar modelos con licencia que prohíba redistribución | Concentración por operador en un slot; registros con patrón común |
| T4 | Verificación insuficiente: recibos firmados no prueban cómputo correcto; el signer del gateway es de confianza y puede autorizar pagos erróneos | Media | Alta | Canarios, doble ejecución muestreada, revisión independiente del signer/contrato, árbitro con proceso definido | Tasa de discrepancias > 1 % o disputas abiertas |
| T5 | Errores de contrato o del puente de liquidación con dinero real | Media | Alta | Auditoría externa antes del primer pago, topes por lote, 7 días de ventana de disputa, bug bounty | Hallazgos críticos abiertos; divergencia redondeos USD/token |
| T6 | Cripto en Python puro sin auditar en rutas de producción | Media | Alta | Sustituir por librerías auditadas (`cryptography`) antes de beta con dinero | Código marcado `NOT AUDITED` en la ruta de pagos/claves |
| T7 | Credencial expuesta en el historial público (`8445b54`) y superficie de red inmadura | Alta | Media | Rotar la clave, limpiar historial, escaneo de secretos en CI, pentest antes de superficie pública | Alertas de uso de la clave; hallazgos del pentest |
| T8 | Fine-tuning distribuido no viable en el horizonte (≈ 59 etapas para 70B, compresión ≥ 10×) | Alta | Baja (en el modelo base) | No contar con ello hasta mes ≥ 27-33; tratarlo como I+D con subvención | Sin resultado de compresión de activaciones en prototipo |

## De mercado y negocio
| ID | Riesgo | P | I | Mitigación | Señal temprana |
|---|---|---|---|---|---|
| M1 | **Los operadores no cubren costes a precio de mercado** y la oferta no escala (el modelo: –24,8 USD/mes por operador medio en el caso base; solo se atiende 21 % de la demanda) | Alta | Alta | Priorizar hardware ya amortizado y de bajo consumo; tier verificado a 2-3× el mercado; crédito de arranque acotado; no vender rendimiento | Tasa de abandono de operadores > 5 %/mes; utilización > 70 % con cola |
| M2 | **La línea de enclaves no existe**: 89 % del ingreso base depende de ella y hoy hay 0 conversaciones | Media | Alta | 20-30 entrevistas antes de ampliar plantilla; pilotos de pago; ajustar plan al precio real | Menos de 3 pilotos de pago/carta de intención en el mes 15-18 |
| M3 | Competir por precio es inviable frente a H100 + batching y a marketplaces (RTX 4090 ≈ 0,34-0,40 USD/h en alquiler, `[POR VERIFICAR]`) | Alta | Alta | No competir por precio; diferenciar por recibos, regalías y enclaves | Clientes que se van por 10-20 % de precio |
| M4 | LTV/CAC de desarrolladores self-serve ≈ 0,05 (base): el marketing de pago no se recupera | Alta | Media | Adquisición orgánica y comunidad; foco business | CAC real > 20 USD por cuenta con ARPA < 1 USD/mes |
| M5 | Proveedores centralizados bajan precios o los modelos abiertos se commoditizan más (clase 8B a 0,02/0,04 USD/M en DeepInfra) | Alta | Media | Foco en capas de servicio; vigilar precio de referencia trimestralmente | Cambios de precio en las 3 páginas de referencia |
| M6 | Demanda de autores `.nram` pequeña: sin catálogo no hay regalías | Media | Media | Programa de autores iniciales; licencias claras | < 5 autores activos en 12 meses |
| M7 | Financiación: sin hitos creíbles la seed no cierra y la caja base baja a ≈ 285 k USD en el mes 18 | Media | Alta | Hitos de `04`; plantilla escalonada (con la mitad de plantilla la necesidad baja a 1,38 M); subvenciones | Caja < 6 meses de quema sin ronda en curso |
| M8 | Dependencia del mercado de la lista de espera (no existe cifra real) | Media | Media | No usar cifras de lista como tracción; medir conversión real | Conversión < 5 % |

## Legales y regulatorios
| ID | Riesgo | P | I | Mitigación | Señal temprana |
|---|---|---|---|---|---|
| L1 | Servicio de pagos/dinero electrónico no autorizado al custodiar y repartir fondos | Media | Alta | Proveedor autorizado de *split payments*; opinión legal (mes 4); no custodiar | Opinión legal desfavorable o requerimiento |
| L2 | Un token (o "crédito"/"quema") se considera valor (Howey / MiCA) | Media | Alta | Sin token en 36 meses; revisar `BURN_BPS`; lenguaje sin rendimiento | Cualquier plan de venta de token |
| L3 | Licencias de modelos: Gemma ≤ 3 trata el servicio alojado como distribución y puede restringir remotamente; Llama exige "Built with Llama", nombre con prefijo e indemnización; distribución de fragmentos a operadores | Alta | Alta | Catálogo por defecto con Apache 2.0 (Gemma 4); contrato de operador con trasladado de condiciones; catálogo versionado y retirable | Cambio de términos del licenciante; reclamación |
| L4 | RGPD: prompts con datos personales vistos por operadores terceros, transferencias fuera del EEE, ilusión de anonimato | Alta | Alta | DPA, subencargados, retención 30 d por defecto/cero retención, DPIA, no prometer privacidad total | Solicitud de un cliente empresa que exige DPA |
| L5 | AML/KYC de operadores y obligaciones fiscales de plataforma (DAC7, IVA) | Media | Media | KYC en el cobro, informes; integrar proveedor | Primer pago a un operador no residente |
| L6 | Contenido ilícito generado y responsabilidad (DSA, AI Act) | Media | Media | AUP, retirada, logs mínimos, seguro | Primera denuncia |
| L7 | Marca NEXUS ya registrada por terceros | Media | Media | Búsqueda de anterioridades (mes 2); alternativa de nombre | Oposición o carta de cese |
| L8 | Reclamación de PI por un adaptador de autor | Baja | Media | Garantías del autor, takedown, retención de fondos | Primera reclamación |

## De equipo y ejecución
| ID | Riesgo | P | I | Mitigación | Señal temprana |
|---|---|---|---|---|---|
| E1 | Alcance excesivo para un equipo pequeño (red, criptografía, pagos, legal, ventas) | Alta | Alta | Secuenciar por hitos; reducir a una vertical (enclaves o regalías) si M2 falla | Retrasos > 2 meses en hitos H1 |
| E2 | Dependencia de pocas personas clave `[POR VERIFICAR]` composición real | Media | Alta | Vesting, documentación, reparto de conocimiento | Baja de una persona clave |
| E3 | Contratar antes de validar demanda: el optimista hunde caja con 18 FTE | Media | Alta | Contratar por hitos; plan lean (×0,5 de plantilla) | Quema > plan durante 3 meses |
| E4 | Ruido de comunicación: promesas de "descentralización" o rendimiento que incumplen las reglas de honestidad | Media | Alta | Revisión de textos públicos; checklist del brief | Página web con "trustless" o cifras de ganancia |
| E5 | Documentación y repositorio con mensajes contradictorios (evidencia de H1 frente a la realidad local) | Media | Media | Fuente única de estado (`EXECUTIVE_BRIEF.md`) | Inversor encuentra contradicción |

## Prioridades (para las próximas 4-8 semanas)
1. Medir throughput real multi-nodo (T1, M1).
2. 20-30 entrevistas de enclave y de desarrolladores (M2, M4).
3. Opinión legal de pagos/licencias y confirmar qué Gemma usa Atenhea (L1, L3).
4. Rotar la credencial expuesta (T7).
5. Búsqueda de anterioridad de marca (L7).
