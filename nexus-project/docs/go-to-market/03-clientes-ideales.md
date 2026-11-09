# 03 · Clientes ideales y personas

Fecha: 2026-10-27. Todo lo de este documento son **hipótesis de trabajo** (no hay entrevistas ni datos de usuarios todavía). Se validan con la lista de espera y las entrevistas de las semanas 1–6 (04). Prohibido citar personas como si fueran clientes reales.

## 1. Mercado de tres lados: cuál pesa más hoy

| Lado | Rol | Prioridad en alpha | Motivo |
|---|---|---|---|
| **Oferta: operadores de GPU** | Aportan slots y cobran por trabajo verificado | **Primero** (cantidad pequeña y de calidad) | Sin nodos distintos no hay red ni prueba del reparto. Cada slot necesita varios operadores |
| **Demanda: desarrolladores** | Consumen la API | Segundo, a pequeña escala y con cargas de prueba | Tolerantes a latencia, dispuestos a probar algo rotas |
| **Autores de modelos** | Publican y cobran regalías | Tercero, 2–5 autores piloto | Sin demanda ni oferta estable no hay a quién vender; el valor es ilustrativo |
| Empresas | Pilotos de laboratorio | Después (GA+) | Sin auditoría ni SLA |

## 2. ICP: operadores de GPU

**ICP primario (alpha):** persona o equipo técnico con **1–8 GPU de consumo/estación (≥12–24 GB VRAM)** o un Mac con memoria unificada abundante, que ya ejecuta modelos locales, **tiene curiosidad por la red y tolera que los pagos sean de testnet**.

Segmentos, de más a menos prioritario:
1. **Aficionados de IA local / homelab** (r/LocalLLaMA, foros de hardware, Discords de llama.cpp/Ollama). Motivación: aprender, contribuir, quizá ganar algo en el futuro. No aceptar su participación como compromiso de ingresos.
2. **Universidades y laboratorios** con GPUs infrautilizadas fuera de horario. Motivación: investigación (sistemas distribuidos, privacidad), publicaciones, acceso a datos de red.
3. **Pequeños centros de datos / hosting** con capacidad ociosa. Motivación económica; hay que ser especialmente cuidadosos: no prometer demanda ni ingresos.
4. **Operadores cripto (miners reconvertidos)**: ruido alto, riesgo de expectativas de token. Aceptar caso a caso; filtrar quien venga por "airdrop".

**Persona O1 — "Marta, la del homelab"** (ficticia, hipótesis)
- Perfil: ingeniera de datos, 2×RTX 4090 en casa, sirve modelos con llama.cpp para uso propio.
- Dolores: la GPU está ociosa por la noche; le interesa la IA descentralizada pero desconfía de proyectos con token.
- Disparadores: instalación sencilla (un contenedor), página de estado honesta, posibilidad de ver recibos de su nodo, comunidad técnica cercana.
- Objeciones: "¿qué veréis de mi máquina?", "¿cuánto gano?", "¿me exponéis a abuso?", "¿consume mucho?".
- Respuestas: ver §5.

**Persona O2 — "Prof. Iván, laboratorio de sistemas"** (ficticia)
- Perfil: cuenta con 8 GPU de un clúster compartido con ventanas libres; interés investigador.
- Disparadores: poder escribir un paper/medida; datos abiertos, simulador y código para reproducir.
- Objeciones: seguridad de red del campus, licencias, responsabilidad sobre el contenido servido.
- Respuestas: aislamiento en contenedor, nodo bajo su control (se activa/desactiva), política de contenido y registro de trabajos; acuerdo piloto por escrito.

**Criterios de calificación (rápido):** VRAM suficiente para al menos un slot del modelo de la alpha; conexión de subida estable; experiencia con Docker; acepta el aviso de testnet por escrito; no espera ingresos.

## 3. ICP: desarrolladores (demanda)

**ICP primario (alpha):** desarrollador/a o equipo pequeño con **cargas de inferencia por lotes** (resumen, clasificación, extracción, evaluación) con modelos abiertos, que **ya usa el SDK de OpenAI**, valora no depender de un único proveedor y tolera latencia de decenas de segundos.

Segmentos:
1. **Investigadores y hackers de IA abierta** que quieren probar una red nueva y dar feedback.
2. **Equipos de producto con pipelines offline** (etiquetado, evaluaciones, ETL de texto) donde la latencia importa poco.
3. **Mantenedores de herramientas open source** que quieren ofrecer "backend descentralizado" opcional.
4. **Empresas con aversión a un solo proveedor** (más tarde; ver §5).

**Persona D1 — "Leo, indie hacker"** (ficticia)
- Perfil: construye una herramienta que resume documentos por lotes; usa OpenRouter hoy.
- Dolores: dependencia de proveedores, cambios de precio y de modelo (01, H8 muestra volatilidad de precios en GPU).
- Disparadores: cambiar `base_url`, ver recibos, créditos de prueba, catálogo con licencias claras.
- Objeciones: "¿es estable?", "¿cuánto tarda?", "¿puede salirme caro/barato?", "¿veréis mis prompts?".

**Persona D2 — "Elena, ML engineer en una startup"** (ficticia)
- Perfil: evaluaciones periódicas de modelos abiertos; presupuesto limitado.
- Disparadores: ejecución batch, informes de coste por 1.000 tokens, API estándar.
- Objeciones: calidad/determinismo, reproducibilidad, soporte, falta de SLA.

**Criterios:** usa API OpenAI-compatible, carga no interactiva, acepta alpha, no envía datos sensibles ni regulados.

## 4. ICP: autores de modelos

**ICP primario (alpha):** autor/a con un **modelo ajustado o adaptador pequeño con licencia que permite redistribución** (fine-tunes, `.nram`), que quiere ser **pagado por uso** y no distribuir los pesos en claro a ningún operador.

Segmentos:
1. **Creadores de fine-tunes especializados** (dominio, idioma, estilo) en Hugging Face.
2. **Estudios/equipos pequeños** con un modelo propio que quieren monetizar sin montar infraestructura.
3. **Investigadores** que quieren probar el flujo "publicar → cifrar → manifiesto firmado".

**Persona A1 — "Sofía, creadora de un fine-tune en español jurídico"** (ficticia)
- Disparadores: regalías por inferencia (`royalty_bps`), manifiesto firmado, cifrado en reposo.
- Objeciones: "¿pueden copiar mi modelo?", "¿cómo me pagan?", "¿qué licencia aplica sobre el base?", "¿cuánto demanda hay?"
- Respuestas: honestidad: el cifrado y el slot reducen pero no eliminan el riesgo de copia; las regalías son de testnet hoy; no hay demanda demostrada; respetar licencia del modelo base.

**Criterios:** licencia compatible; modelo base con redistribución permitida; acepta que publicar en la red no garantiza uso ni ingresos.

## 5. Empresas (referencia, no objetivo de alpha)

Disparadores futuros: no depender de un único proveedor; necesidad de **auditar qué nodo ejecutó qué**; requisitos de datos. Realidad: sin SLA, sin auditoría independiente y con operadores que ven las peticiones; **no es apto para datos sensibles**. Mensaje hoy: pilotos de laboratorio con datos no sensibles, 3–5 equipos como máximo, tras la beta.

## 6. Objeciones y respuestas (compatibles con el estado real)

### Operadores
| Objeción | Respuesta honesta |
|---|---|
| ¿Cuánto voy a ganar? | No lo sabemos y no lo prometemos. En la alpha los pagos son de testnet (sin dinero real). Medimos "trabajo verificado"; el precio y la demanda están por demostrar. |
| ¿Qué ve {NOMBRE} de mi máquina? | El agente de nodo comunica heartbeats, capacidad declarada y recibos. Publicaremos qué datos recoge y cómo desactivarlo `[POR VERIFICAR con eng-runtime]`. |
| ¿Puedo ver el modelo entero? | No: tu nodo tiene su slot (1/S) en claro en memoria. Eso es inevitable sin TEE/MPC. Una coalición grande sí podría reunirlo; por eso hay límites de identidad y registros. |
| ¿Qué pasa si sirvo contenido ilegal o abusivo? | Los operadores son responsables de lo que ejecutan igual que en otros servicios de cómputo; política de uso aceptable y registro de trabajos `[POR VERIFICAR con asesoría legal]`. |
| ¿Es seguro abrir puertos? | El worker H1 usa TLS y autenticación; el enrutado funciona por polling. Aún falta ensayo H1 entre redes independientes y auditoría. Empieza en una red aislada. |
| ¿Hay token? | No hay token en v0.1. Cualquier cosa futura se discutirá públicamente con sus riesgos regulatorios. |

### Desarrolladores
| Objeción | Respuesta honesta |
|---|---|
| ¿Es drop-in de OpenAI? | Para chat: sí en formato (`/v1/chat/completions`, `/v1/models`); sin streaming, tools ni multimodal. |
| ¿Latencia y velocidad? | Orden de magnitud simulado: S=8 ≈ 4–6 tok/s por stream; útil para batch; no para chat interactivo. Mediremos con la beta. |
| ¿Es más barato? | No lo sabemos aún. Publicaremos el coste real por 1.000 tokens cuando lo midamos. |
| ¿Mis prompts son privados? | No: los operadores que ejecutan tu petición pueden verla. No envíes datos sensibles. |
| ¿Es fiable? | Es una alpha; sin SLA. Los nodos pueden caer; el router reenruta y reintenta hasta tres veces (H0). |
| ¿Qué demuestra el recibo? | Qué nodo ejecutó qué trabajo (firma Ed25519), con hash de salida y medición de tokens. No demuestra que la respuesta sea buena. |

### Autores
| Objeción | Respuesta honesta |
|---|---|
| ¿Pueden robar mi modelo? | Ningún operador tiene el modelo completo y los trozos en reposo están cifrados, pero una coalición suficientemente grande podría reconstruirlo y quien consulta puede destilarlo. Si necesitas secreto fuerte, esta red todavía no es para ti. |
| ¿Cómo me pagan? | Regalía (`royalty_bps`) incluida en el lote de liquidación; hoy en testnet. |
| ¿Quién usará mi modelo? | No hay demanda demostrada; empezamos con pilotos. |

### Empresas
| Objeción | Respuesta honesta |
|---|---|
| ¿Cumplimiento (SOC 2, GDPR)? | No hay certificaciones. Piloto solo con datos no sensibles; contacto para necesidades específicas. |
| ¿Quién responde si falla? | Alpha sin SLA. |
