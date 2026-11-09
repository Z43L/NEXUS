# 01 · Mercado y competencia

Fecha: 2026-10-27. Todas las fuentes se consultaron el **2026-10-27** salvo que se indique otra fecha. Regla del brief: lo que no pude verificar en una fuente primaria lleva `[POR VERIFICAR]`. Las páginas de precios cambian a diario: tratar cualquier cifra de este documento como una foto, no como dato estable.

## 1. Panorama en una página

El mercado donde NEXUS quiere entrar tiene tres capas que conviene no mezclar:

1. **Inferencia centralizada de modelos abiertos** (Together, Fireworks, Groq, OpenRouter como agregador). Es la referencia de precio, latencia y fiabilidad. Compite en precio por token con márgenes pequeños; el diferencial es velocidad, catálogo y SLA.
2. **Alquiler de GPU descentralizado o agregado** (Akash, io.net, Hyperbolic, Render, Prime Intellect compute). Venden horas de GPU, no inferencia verificada ni modelos particionados.
3. **Redes descentralizadas de IA con token** (Bittensor/Chutes, Gensyn, Pluralis, Nous/Psyche). Compiten por la narrativa "IA abierta y colectiva", pero casi todas dependen de un token y/o de una incentivación que NEXUS no tiene ni quiere tener en v0.1.

NEXUS (alpha cerrada, testnet, sin token) es, hoy, un **prototipo en la intersección de 1 y 3**: API compatible con OpenAI (capa 1) sobre nodos independientes con reparto por contribución y recibos firmados (capa 3), sin token. No tiene tracción medible ni precios públicos; cualquier comparación de precio con los competidores es hipotética hasta medir coste real por 1.000 tokens (EXECUTIVE_BRIEF, "Métricas de decisión").

## 2. Hechos de mercado verificados (con fuente)

| # | Hecho | Fuente |
|---|---|---|
| H1 | Together AI publica en su página de precios, entre otros, Llama 3 8B Instruct Lite a 0,14 $/M tokens (entrada y salida), DeepSeek V4.1 Flash a 0,30 $ entrada / 1,20 $ salida, Qwen3.5 9B a 0,17/0,25 $, y GPU clúster H100 on-demand 3,99 $/GPU-h (preemptible 1,99 $). Llama 3.3 70B **no** aparece en su tabla serverless visible. | https://www.together.ai/pricing (2026-10-27) |
| H2 | Fireworks cobra serverless por tramo de tamaño: <4B 0,10 $/M; 4B–16B 0,20 $; >16B 0,90 $; GPT OSS 120B 0,15 $ entrada / 0,60 $ salida; batch al 50 %. GPU on-demand H100 8,00 $/h. | https://docs.fireworks.ai/serverless/pricing y https://fireworks.ai/pricing (2026-10-27) |
| H3 | OpenRouter no marca el precio de inferencia ("sin recargo"); cobra una comisión al comprar créditos: 5,5 % (Standard) / 8 % (Business); BYOK gratis hasta 25.000 $/mes de inferencia a precio de lista y 5 % por encima. | https://openrouter.ai/pricing y https://openrouter.ai/docs/faq (2026-10-27) |
| H4 | Chutes (subred de Bittensor) es solo pago por uso, sin plan gratuito; ejemplos: gemma-4-31B-turbo 0,12 $ entrada / 0,37 $ salida por M; Qwen3.8-27B 0,039 / 1,25 $; DeepSeek-V3.2 1,00 / 1,00 $; GPU privada RTX Pro 6000 1,80 $/h. Muchos modelos sufijo `-TEE` (entornos de ejecución confiables). Acepta Stripe y TAO. | https://chutes.ai/pricing (2026-10-27) |
| H5 | Un análisis bajista (Pine Analytics) estima que Chutes recibe ~52 M$/año en emisiones TAO frente a 1,3–2,4 M$ de ingresos reales de clientes. Es una estimación de un analista, no un dato verificado. | https://pineanalytics.substack.com/p/the-bear-case-for-bittensor-tao (resultado de búsqueda, 2026-10-27) `[POR VERIFICAR]` |
| H6 | Bittensor se describe a sí mismo como "una red abierta donde subredes independientes producen commodities digitales y la cadena paga a los contribuyentes en TAO". | https://bittensor.com/ (2026-10-27) |
| H7 | Petals (BigScience, MIT) reparte bloques de un modelo entre voluntarios; README lista Llama 3.1 hasta 405B, Mixtral 8x22B, Falcon y BLOOM; 10,7 k estrellas, 522 commits, sin releases listadas; sin aviso de archivado. Su actividad reciente no pude confirmarla. | https://github.com/bigscience-workshop/petals (2026-10-27). Paper: https://arxiv.org/pdf/2312.08361 |
| H8 | Hyperbolic ofrece GPU on-demand/reservadas, API de inferencia compatible con OpenAI facturada por token y "private cloud"; se declara "250.000+ builders" (cifra de la empresa, no verificada) y una Serie A1 de 30 M$ (titular de blog). Precios H100: un agregador de terceros indica 3,19 $/h a 21/08/2026 tras subir desde 1,50 $ en junio. | https://www.hyperbolic.ai/ (2026-10-27); https://computeprices.com/providers/hyperbolic/gpus/h100 (vía búsqueda) `[POR VERIFICAR]` el precio actual en su web |
| H9 | Prime Intellect: GPUs on-demand de 1 a 256, mercado spot, Prime Inference Gateway y modelos alojados con una API compatible con OpenAI; tarifas de H100 desde 2,43 $/h (spot 0,94 $/h) según su página. Respaldo declarado: Founders Fund, NVIDIA, Intel y otros (sin importes). | https://www.primeintellect.ai/ (2026-10-27) |
| H10 | io.net declara en sus propias guías >320.000 GPU en 130+ países y H100 SXM entre 2,10 y 3,50 $/h; sus páginas son marketing propio y se contradicen entre sí (1,49–4 $/h). | https://io.net/p/h100-gpu-cloud-where-to-rent-complete-pricing-guide-for-2026 (2026-10-27) `[POR VERIFICAR]` |
| H11 | Akash: precios dinámicos por subasta; guías de terceros citan H100 en 1,20–1,80 $/h frente a 4,50–5,50 $ en AWS, y una comisión de red del ~4 % (pago en AKT) a ~20 % (stablecoins). | https://www.dextools.io/news/what-is-akash-network-depin-cloud-compute-akt-guide-2026 y https://www.fierceelectronics.com/ai/akash-airbnb-gpus-owners-idle-chips-can-rent-out-compute-cheap (2026-10-27) `[POR VERIFICAR]`; su tabla oficial https://akash.network/pricing/gpus/ no mostró valores |
| H12 | Render Network: renderizado GPU descentralizado bajo demanda (Octane, Redshift, Blender) más acceso a herramientas de imagen generativa de terceros; token RENDER; no describe "inferencia" como producto. | https://rendernetwork.com/ (2026-10-27) |
| H13 | Gensyn: publicaciones recientes sobre Delphi (mercados de información, lanzado 22-abr-2026), REE (reproducibilidad, 17-mar-2026), AXL (comunicación P2P, 15-abr-2026) y un modelo "auditable" open-1b (15-sep-2026). La página no aclara estado de mainnet ni token. | https://www.gensyn.ai/ (2026-10-27) |
| H14 | Pluralis Research ("Protocol Learning"): entrenamiento descentralizado con modelos de propiedad colectiva; su informe cita Pluralis-8B (8,6 B parámetros, 500 B tokens, 330 nodos). Respaldo: Union Square Ventures (sin importe). | https://pluralis.ai/ (2026-10-27) |
| H15 | Nous Research hoy se presenta con Hermes Agent y suscripciones (anuncio del 27-oct-2026); la página no menciona Psyche ni una red de inferencia descentralizada. | https://nousresearch.com/ (2026-10-27) |
| H16 | Groq: la página de precios no mostró cifras por token y se describe como "neocloud para inferencia rápida". | https://groq.com/pricing (2026-10-27) `[POR VERIFICAR]` precios |

## 3. Matriz de competidores

Leyenda de "Tipo": **C** centralizada, **D** descentralizada, **A** agregador, **G** alquiler de GPU. "¿Token?": si el modelo de negocio depende de un token nativo.

| Competidor | Tipo | Qué vende | Precio / modelo de negocio (fuente §2) | Fortalezas | Debilidades frente a NEXUS | ¿Token? |
|---|---|---|---|---|---|---|
| **Together AI** | C | API serverless de modelos abiertos, fine-tuning, GPU clúster/dedicada | Por token y por GPU-h (H1) | Catálogo grande y actualizado, precios claros, fine-tuning | Operador único ve pesos y prompts; sin recibos verificables por el cliente; no paga a terceros | No |
| **Fireworks** | C | Serverless por tramo de tamaño, batch -50 %, GPU on-demand | H2 | Latencia, tramos simples, batch barato | Igual que Together; GPU más cara (8 $/h H100) | No |
| **Groq** | C | Inferencia rápida (hardware propio) | `[POR VERIFICAR]` | Velocidad | Catálogo limitado a lo que su hardware soporta; centralizado | No |
| **OpenRouter** | A | Una API para muchos proveedores | Sin margen en inferencia; 5,5 %/8 % al comprar créditos (H3) | Mejor "capa de enrutado" del mercado; enlaza proveedores nuevos | No ejecuta cómputo propio; depende de proveedores | No |
| **Chutes / Bittensor SN64** | D | Inferencia serverless barata y GPU privada con TEE | Pago por uso (H4); subsidiada por emisiones según un analista (H5) | Precios muy bajos, uso alto declarado, integración vía OpenRouter | Dependiente del token TAO; calidad/fiabilidad heterogénea `[POR VERIFICAR]`; el nodo ve el modelo completo (confía en TEE) | Sí (TAO) |
| **Petals** | D | Inferencia/fine-tuning colaborativo de modelos grandes por voluntarios | Gratis, sin pago a nodos (H7) | Idea pionera, open source MIT, 10,7 k estrellas | Sin incentivos económicos ni recibos; latencia/estabilidad de enjambre voluntario; mantenimiento reciente `[POR VERIFICAR]` | No |
| **Gensyn** | D | Entrenamiento/verificación descentralizados; mercados de información | H13 | Investigación en verificabilidad (REE) | Foco en entrenamiento y mercados de predicción, no en API de inferencia para devs | `[POR VERIFICAR]` |
| **Prime Intellect** | G+D | GPUs, spot, gateway de inferencia, entrenamiento RL | H9 | Producto amplio y comunidad de investigación (INTELLECT) | Plataforma de cómputo/entrenamiento; no particiona modelos ni reparte por contribución | No evidente |
| **Akash** | G+D | Mercado de cómputo en subasta | H11 | Precios bajos, años en producción, comunidad | Alquila máquinas; no hay API de inferencia verificada | Sí (AKT) |
| **io.net** | G+D | Clústeres GPU agregados | H10 | Escala declarada | Cifras de marketing contradictorias; sin inferencia verificable | Sí (IO) |
| **Hyperbolic** | G+A | GPU marketplace + API compatible con OpenAI | H8 | Producto de dev maduro, GPU + inferencia en un sitio | Precios de GPU volátiles (H8); centralizado en la capa de API | `[POR VERIFICAR]` |
| **Render** | G+D | Renderizado y algo de IA generativa | H12 | Marca, red establecida | Foco en render | Sí (RENDER) |
| **Pluralis** | D | Entrenamiento colectivo, propiedad de modelos compartida | H14 | Investigación (NeurIPS/ICML), modelo propio de 8,6 B | Orientado a entrenamiento; sin API de producto visible | `[POR VERIFICAR]` |
| **Nous Research** | C/Lab | Modelos Hermes, agente, suscripciones | H15 | Marca fuerte en comunidad de modelos abiertos | Hoy no es una red descentralizada | `[POR VERIFICAR]` |

## 4. Referencia de precios para comparar (solo orden de magnitud)

Con los números anteriores, los modelos abiertos pequeños/medianos se sirven hoy entre **~0,10 y ~1,25 $/M tokens** en proveedores centralizados y subredes baratas (H1, H2, H4). Cualquier promesa de NEXUS de "precio por debajo" debe basarse en datos propios de coste real (energía, amortización, disponibilidad, verificación, gas) que **aún no existen**. En la alpha, el mensaje no puede ser precio; puede ser **verificabilidad, reparto transparente y no concentrar el modelo en un operador**.

Hecho propio relevante: el simulador (`research/swarm-sim`) indica que con S=8 el decode es ~4–6 tok/s por stream (orden de magnitud, no medida). Eso es claramente peor que servicios centralizados para chat interactivo. NEXUS no gana por latencia; la alpha debe orientarse a **batch y cargas tolerantes a latencia**.

## 5. Huecos de mercado (donde NEXUS tiene espacio honesto)

1. **Ningún operador tiene el modelo completo + API estándar.** Los centralizados ven todo; Chutes confía en TEE; Petals no tiene API de producto ni pagos. La combinación "API OpenAI + reparto por slots + pago por trabajo verificado" no la he encontrado en ningún competidor, pero es una afirmación de ausencia: `[POR VERIFICAR]` con una revisión más amplia antes de usarla en público.
2. **Recibos firmados por trabajo.** Los competidores facturan por tokens, pero ninguno ofrece (en lo que he visto) un recibo verificable por el cliente ligado a nodo y trabajo. `[POR VERIFICAR]`.
3. **Pago proporcional a trabajo verificado sin token.** Frente a Bittensor, Akash, io.net y Render, que dependen de un token. Es un hueco pero también una debilidad: sin token no hay subsidio de arranque (ver 04, arranque en frío).
4. **Autores de modelos con regalías.** El brief incluye al autor (`.nram`, `royalty_bps` en el manifiesto). No encontré un competidor que ofrezca regalías por inferencia con cifrado de pesos; `[POR VERIFICAR]`. Es el hueco más especulativo: no hay demanda demostrada.
5. **Operadores pequeños y universidades** sin acceso a mercados con escala mínima (por ejemplo, clústeres con mínimos de GPU).

## 6. Riesgos de posicionamiento

| Riesgo | Por qué importa | Mitigación |
|---|---|---|
| **"Descentralizado" sin matiz** | Prohibido por el brief; además el nodo ve su slot en claro y una coalición grande puede reconstruir el modelo | Usar la fórmula del brief ("ningún operador tiene el modelo completo; una coalición lo bastante grande sí podría reconstruirlo; quien consulta puede destilarlo") |
| **Parecer "otro DePIN con token"** | El mercado está saturado y la confianza es baja (subvenciones, H5) | Decir explícitamente "sin token en v0.1" y no hablar de rendimiento |
| **Competir en precio** | Los centralizados bajan precios a 0,10–1,25 $/M (H1, H2, H4) | No competir en precio en alpha; competir en verificabilidad y no-concentración |
| **Competir en latencia** | S=8 ≈ 4–6 tok/s (simulador) | Orientar a batch/asíncrono |
| **Confusión con Petals** | Petals es la referencia mental de "BitTorrent para LLM" | Diferenciarse: pagos por trabajo, recibos, cifrado en reposo y reparto por slots; reconocer que Petals fue pionero |
| **Madurez real de H1** | Nodos entre redes independientes aún no demostrados (EXECUTIVE_BRIEF) | No reclutar para "producción"; alpha cerrada y testnet |
| **Conflicto de nombre** | Ver §7 | Plan B de nombres |
| **Modelo base y licencias** | Gemma, Llama imponen condiciones | Cada modelo del catálogo lleva su licencia; revisar términos de uso comercial `[POR VERIFICAR]` |

## 7. Conflicto de nombre y marca "NEXUS" (riesgo explícito, no resuelto)

**No es un análisis jurídico.** Solo he podido consultar páginas web y resultados de búsqueda; no he consultado USPTO, EUIPO ni OEPM/WIPO directamente. Antes de invertir en dominio, logos o PR hace falta una **búsqueda de anterioridades profesional en clases 9, 35, 42 (software, SaaS, servicios de cómputo)** en US, UE y ES.

Hallazgos:

| Titular / uso | Qué es | Gravedad | Fuente |
|---|---|---|---|
| **Nexus Labs (nexus.inc; antes nexus.xyz redirige aquí)** | Se presenta hoy como **gateway de IA corporativo** con 100+ modelos, API, controles de presupuesto y "Auto Router"; Nexus gestionado a precio de lista +5 %. Compite en el mismo espacio semántico (gateway/API de modelos). Antes se asociaba a un zkVM y a una red de cómputo verificable con una Serie A de 25 M$ (jul-2024, según prensa cripto) | **ALTA**: mismo sector, mismo tipo de producto, misma palabra | https://nexus.inc/ (2026-10-27); https://news.bit2me.com/en/nexus-presenta-red-abierta-de-proveedores-zkvm y https://docs.nexus.xyz (resultados de búsqueda). `[POR VERIFICAR]` que nexus.xyz y nexus.inc sean la misma empresa (la redirección 307 sugiere que sí) |
| **Sonatype (Nexus Repository, Nexus IQ)** | Marca SONATYPE NEXUS (clase software de desarrollo, solicitud presentada 22-dic-2010) y Nexus Repository Pro+ anunciado en oct-2026 con foco en artefactos de IA. Muy conocida entre desarrolladores | **ALTA** para audiencia de desarrolladores: búsqueda "nexus" en foros dev devuelve su producto | https://help.sonatype.com/en/copyright.html y https://finance.yahoo.com/technology/ai/articles/sonatype-unveils-nexus-repository-pro-100000742.html (2026-10-27) |
| **NEXUSAI (solicitud USPTO)** | Solicitud "NEXUSAI" para software de IA/ML en ciberseguridad, presentada en nov-2020, suspendida en el último estado visto | MEDIA | https://trademarks.justia.com/903/33/nexusai-90333499.html (2026-10-27) `[POR VERIFICAR]` estado actual y titular |
| **Nexus Mods, Nexus Mutual, y otros "Nexus"** | Marcas conocidas en juegos y seguros cripto | BAJA-MEDIA (otros sectores, pero ruido SEO). No pude abrir Nexus Mods (403) ni verificar su cobertura | `[POR VERIFICAR]` |
| **Dominio** | El brief usa `https://nexus.example` como marcador; `nexus.com`, `nexus.ai`, `nexus.xyz` y similares no están disponibles de forma realista `[POR VERIFICAR]` | ALTA | — |
| **Nombre actual del repo** | "NEXUS × Atenhea": Atenhea no he comprobado conflictos | `[POR VERIFICAR]` | — |

**Conclusión:** el riesgo es **alto en SEO y de confusión** (Sonatype y Nexus Labs dominan los resultados) y **posiblemente alto en marca registrada** en clases de software/SaaS. No se debe dar por resuelto. Recomendación: usar NEXUS como **nombre de trabajo** durante la alpha cerrada (sin gastar en identidad visual definitiva), encargar la búsqueda de anterioridades y decidir antes de la beta pública (semana 8 del plan, ver 04).

**Nombres en reserva** (ninguno verificado: son ideas para pasar por búsqueda de marca y dominio; comprobar también significado en español/inglés):

| Candidato | Idea | Nota |
|---|---|---|
| **Slotnet** | Alude a la arquitectura de slots | Descriptivo, probable de ser débil como marca; comprobar |
| **Cairn** | Montón de piedras colocadas por muchos; ningún viajero lo construye entero | Corto, evocador; probablemente usado en otros sectores |
| **Mesa / Teselado (Tesela)** | Cada nodo aporta una pieza | "Mesa" muy usado; "Tesela" más singular |
| **Quorum-like: "Coro"** | Muchas voces, una respuesta | Corto, pronunciable en ES/EN |
| **Atenhea** (ya existe como motor) | Reutilizar el nombre del motor para la marca | Menos tráfico; conflicto desconocido `[POR VERIFICAR]` |

Criterio de elección sugerido: pronunciable en español e inglés, dominio `.com`/`.ai`/`.dev` disponible, sin marca registrada en clases 9/35/42, sin colisión con términos cripto.

## 8. Qué falta investigar (pendientes)

- Precios actuales de Groq y el catálogo real de OpenRouter para Llama/Gemma en las mismas fechas.
- Estado de mantenimiento de Petals (últimos commits, salud del enjambre).
- Datos de uso reales de Chutes y de ingresos de Akash/io.net desde fuentes primarias (on-chain o informes).
- Términos de licencia de los modelos del catálogo de NEXUS (Gemma, Llama) para uso comercial en una red de terceros.
- Búsqueda formal de marca (§7).
