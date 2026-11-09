# 05 · Contenido y activos

Fecha: 2026-10-27. Todos los borradores usan marcadores `{...}` que hay que completar con datos reales **antes** de publicar (nombre, URLs, mediciones). Cualquier `[MEDIR]` es un dato que aún no existe y no debe inventarse. Antes de publicar cada pieza: pasarla por la lista "decimos / no decimos" de 02. Ninguna pieza contiene testimonios, usuarios, logos ni socios, y ninguna debe añadirlos.

Marcadores comunes: `{NOMBRE}` (nombre de trabajo NEXUS, ver riesgo de marca en 01 §7), `{URL}` (landing), `{REPO}` (repositorio público), `{DEMO}` (vídeo), `{FECHA}`.

---

## A. Calendario editorial de 12 semanas

Coherente con el cronograma de 04 §7. Cadencia: 1 pieza larga + 2–3 breves por semana.

| Sem | Pieza larga | Breves (X / Reddit / Discord) | CTA | Responsable |
|---|---|---|---|---|
| 1 | Página "Estado" y "Límites conocidos" (texto) | X: presentación del proyecto y del estado (alpha, testnet, sin token) | Lista de espera | GTM |
| 2 | Post "Por qué un modelo partido en slots" (borrador, ver D) | X: 1 gráfico del simulador con etiqueta "simulación" | Lista de espera | CTO + GTM |
| 3 | Notas de 8 entrevistas (resumen, sin nombres) | Discord: apertura y reglas | Unirse a Discord | COM |
| 4 | **Post de arquitectura de slots y límites (D)** + Email 1 | **Hilo X (C)** | Leer, comentar, lista | GTM, CTO |
| 5 | "Lo que hemos aprendido de operadores de GPU" (hallazgos) | Reddit: pregunta de investigación en comunidades de hardware | Cuestionario | COM |
| 6 | **Demo de 3 minutos (G)** + README de captación (H) | X: clip de 30 s | Repo, lista | DEVREL |
| 7 | "Cómo se calcula el pago por trabajo (sin token, en testnet)" | X: diagrama del `work_share` | Formulario de operador | CTO |
| 8 | "Decisión de nombre" o "Por qué seguimos con {NOMBRE} de momento" | Discord AMA | Feedback | CEO |
| 9 | "Seguridad: lo que no protegemos" (coaliciones, Sybil, destilación) | X: 1 hilo corto | Revisores de seguridad | CTO |
| 10 | "Comienza la alpha cerrada: cohorte 1" (sin cifras no medidas) + Email 4 | X, Discord | Invitaciones | COM |
| 11 | **Informe semanal 1 de red** (números reales, también malos) | X: datos y errores | Seguimiento | CTO, GTM |
| 12 | **Show HN (B)** si se cumple la puerta; si no, informe y retraso + Email 5 | Hilo X, Reddit | Probar la demo | GTM |

Cadencia posterior: informe quincenal de red; post técnico mensual; AMA mensual.

---

## B. Borrador "Show HN"

**Condición de publicación:** demo reproducible por terceros y repositorio con instrucciones que funcionen. Estar disponible varias horas para responder.

**Título (≤ 80 caracteres):**

> Show HN: {NOMBRE} – an OpenAI-compatible API on a model split across operators

Alternativa:

> Show HN: Experimental network where no operator holds the whole model (alpha)

**Texto:**

> Hi HN,
>
> We're building {NOMBRE}, an experimental inference network. It exposes an OpenAI-compatible chat API (`/v1/chat/completions`, `/v1/models`) on top of independent nodes. The model is split into S slots (layer ranges), each operator is pinned to a single slot, so no operator holds more than 1/S of the weights. Weights at rest are encrypted and erasure-coded (k-of-n) with a signed Merkle manifest; every job produces a signed receipt (Ed25519) tied to the node and the job. Work inside a slot is routed in proportion to node speed, and payouts follow verified work.
>
> Honest status: closed alpha, testnet only, no token, no real-money settlement. We have run {N_REAL} jobs end-to-end locally (mock and a real small model), see evidence in {REPO}/docs/evidence. We have not yet demonstrated nodes across independent networks at scale `{ACTUALIZAR según estado real}`.
>
> What it is not:
> - Not "trustless" or private: a compute node holds its slot in clear in memory, and the operators that run your request can see its content. Don't send sensitive data.
> - Not copy-proof: a large-enough coalition of operators could reconstruct the model, and anyone who can query it can distill it. In our simulation (`research/swarm-sim`, not measurements), with ~300 nodes per slot, a coalition of 2% of operators reconstructs the model with P≈0.44 and 5% with P≈0.99. Stake alone doesn't prevent Sybil attacks in our model.
> - Not fast: simulated decode with S=8 is ~2.5–7 tok/s per stream. We think it's for batch workloads today, not interactive chat.
> - Not cheaper (yet): we have no measured cost per 1k tokens, so we make no price claims.
>
> Why build it: we wanted to see if "pay for verified work, no token" and "nobody holds the whole model" can coexist, and where it breaks. The simulator, the design decisions and the failure modes are in the repo.
>
> What we'd like from you: try the demo `{DEMO}`, break the assumptions (especially around coalitions/Sybil and the receipt format), and tell us which workloads would be useful under these constraints. If you have a spare GPU and want to join the closed alpha as a node operator, the waitlist is at {URL}; payments are testnet-only.
>
> Name note: "NEXUS" is a working name and we know it collides with existing products; we will rename before the public beta if needed.

**Respuestas preparadas (tono: factual):**
- *"This is just Petals with a payment layer."* → "Petals pioneered splitting a model across volunteers (paper: arxiv.org/abs/2312.08361). Differences we aim for: signed per-job receipts, pay-per-verified-work, and encrypted at-rest chunks with erasure coding. We don't claim to be better; see the limits above."
- *"Why not a token?"* → "We have none in v0.1. If a token is ever considered, it'd be a future option subject to securities-law review; nothing is promised."
- *"What stops a Sybil?"* → "Not stake alone: in our simulation the stake only costs the capital during withdrawal and the attacker keeps the downloaded chunk. Levers we study: per-node fingerprinting with detection, non-refundable registration fee, long withdrawal. Fingerprinting is research, not a solved technique."
- *"Latency?"* → Cifras del simulador con etiqueta; "we will publish measurements when we have them".
- *"Licences?"* → "Each catalog model ships with its licence; we respect base-model licences (e.g. Gemma, Llama)."

---

## C. Hilo para X

> 1/ Estamos construyendo {NOMBRE}: una red experimental de inferencia donde **ningún operador tiene el modelo completo**. Alpha cerrada, testnet, sin token. Hilo con lo que funciona y lo que no.
>
> 2/ Qué es: una API compatible con el formato de chat de OpenAI sobre nodos independientes. El modelo se parte en S "slots" (rangos de capas). Cada operador queda fijo en un solo slot: nadie reúne más de 1/S.
>
> 3/ Los pesos en reposo van cifrados y con erasure coding (p. ej. 10-de-16, 1,6× de sobrecarga) y un manifiesto firmado. Los nodos de almacenamiento solo ven ciphertext.
>
> 4/ Cada trabajo deja un recibo firmado (Ed25519) ligado al nodo y al trabajo. Sirve para auditar qué nodo hizo qué. No demuestra que la respuesta sea buena.
>
> 5/ El pago es proporcional al trabajo verificado. Hoy: testnet, sin dinero real y sin token. No prometemos ingresos a nadie.
>
> 6/ Límites, sin maquillaje: un nodo de cómputo tiene su slot en claro en memoria; los operadores que ejecutan tu petición pueden verla; no envíes datos sensibles.
>
> 7/ Una coalición lo bastante grande puede reconstruir el modelo. En nuestro simulador (simulación, no medida), con ~300 nodos por slot: 2 % de operadores ≈ 0,44 de probabilidad; 5 % ≈ 0,99. Y quien consulta puede destilarlo.
>
> 8/ Velocidad: en simulación con S=8, ~4–6 tok/s por stream. Sirve para batch, no para chat interactivo. Medidas reales: pendientes.
>
> 9/ Lo que hemos probado: {N} trabajos completos en local (mock y modelo pequeño real) con recibos válidos. Evidencia en {REPO}. Lo que no: nodos en redes independientes a escala.
>
> 10/ Buscamos: operadores con GPU para la alpha (testnet), desarrolladores con cargas por lotes, y críticos de seguridad. Lista de espera: {URL}. Repo y simulador: {REPO}.

---

## D. Post de blog técnico: la arquitectura de slots y sus límites

**Título:** "Partir un modelo en slots: qué protege y qué no"

**Cuerpo (borrador):**

> **Resumen.** Describimos cómo {NOMBRE} reparte un modelo entre operadores independientes y qué garantiza y qué no. Todo lo de abajo que lleve "simulación" sale de un simulador analítico + Monte Carlo (`research/swarm-sim`), no de mediciones de hardware real.
>
> **1. El problema.** Quien sirve un modelo ve sus pesos. Si queremos que ningún operador los tenga todos, hay que repartirlos.
>
> **2. Slots.** Partimos las capas en S rangos (slots). Cada operador queda fijo en un único slot, por muchos nodos que tenga. Resultado: ningún operador reúne más de 1/S del modelo. Con S=16 y un modelo de 70B en int4, un slot pesa ~2,2 GB.
>
> **3. Asignación estratificada.** Si el atacante pudiera elegir slot, bastaría con 16 identidades para un modelo de 16 slots. Ordenamos por capacidad, permutamos slots por bloques con una baliza aleatoria publicada tras cerrar el registro, y el atacante no elige. Eficiencia ~0,96 frente a 1,00 (determinista) y 0,83 (aleatorio puro). El atacante necesita ~54 identidades de media (p99: 115) por el efecto "coupon collector".
>
> **4. Reparto de trabajo.** Dentro de un slot, el trabajo se enruta proporcional a la velocidad de cada nodo. El pago es proporcional al trabajo verificado (`work_share`).
>
> **5. Pesos en reposo.** Trozos cifrados + erasure coding k-de-n con manifiesto Merkle anclado on-chain (testnet). Un nodo de almacenamiento solo ve ciphertext; la clave se libera a un nodo asignado. Unir un nodo a un slot de 2,2 GB tarda ~60 s (p95 ~231 s); la salida del operador mayor tarda ~27 min en restaurarse (simulación).
>
> **6. Lo que no protege.**
> - *Coaliciones.* Con ~300 nodos por slot, 2 % de operadores reúne el modelo con P=0,44; 5 % con P=0,99. Más nodos de cómputo = más copias de cada trozo = más fácil reunirlas.
> - *Sybil.* Con parámetros ilustrativos (stake 2000 $, retirada 21 días, comisión 5 $), reunir un modelo de 16 slots cuesta ~770 $ y ~4 meses. El stake solo no protege: el atacante se queda el trozo y recupera el capital.
> - *Nodo de cómputo.* Tiene su slot en claro en memoria; es inevitable sin TEE/MPC.
> - *Entradas.* La primera etapa ve embeddings; el simulador no evalúa privacidad de entradas.
> - *Destilación.* Quien puede consultar el modelo puede imitarlo.
>
> **7. Palancas y su coste.** Cortar cada capa en T trozos reduce la exposición (T=8 y coalición del 10 %: P=0,007) pero cuesta un all-reduce por capa: ~0,6 s/token si el RTT del pod es 0,5 ms, ~2,3 s con 2 ms, ~22 s con 20 ms. Solo viable con lotes grandes y nodos casi colocalizados. TEE con attestation y huella por nodo son líneas abiertas, no resueltas.
>
> **8. Velocidad.** S=8 ≈ 4–6 tok/s por stream; S=16 ≈ 2,8 tok/s (simulación). Es un diseño para cargas por lotes. Throughput agregado bajo escala, cota superior: ~0,95 M tok/s con 5.000 nodos y S=8 (cota teórica, no medida).
>
> **9. Entrenamiento.** Entrenar 70B en GPUs de 24 GB exige ~59 etapas y compresión de activaciones ≥10×; DiLoCo exige réplica completa. No lo ofrecemos; es investigación.
>
> **10. Qué hemos probado y qué no.** {listar evidencia real: jobs completados, recibos, etc.}. No hemos probado redes independientes a escala ni liquidación en testnet pública `{ACTUALIZAR}`.
>
> **11. Cómo ayudar.** Rompe los supuestos: coaliciones, Sybil, formato de recibos. Repositorio: {REPO}.

**Nota editorial:** acompañar con 2 gráficos del simulador rotulados "simulación"; enlazar al README del simulador.

---

## E. Secuencia de 5 emails para la lista de espera

Remitente: persona real del equipo (nombre por completar). Cada email incluye pie: "Estás en la lista de espera de {NOMBRE} (alpha cerrada, testnet, sin token). Puedes darte de baja aquí: {BAJA}." Cumplir RGPD: consentimiento explícito en el formulario y enlace de baja.

**Email 1 — Bienvenida (día 0)**
Asunto: Estás en la lista. Esto es lo que hay (y lo que no)
> Hola {NOMBRE_PERSONA},
> Gracias por apuntarte. En una frase: {NOMBRE} es una red experimental de inferencia donde ningún operador tiene el modelo completo.
> Estado real: alpha cerrada, testnet, sin token y sin pagos reales. No tenemos usuarios que citar ni cifras de rendimiento medidas; te lo contaremos cuando las tengamos.
> Para ayudarnos a priorizar, responde a este correo con: (1) qué rol te interesa (operador, desarrollador, autor de modelos), (2) qué harías con ello. Leemos todas las respuestas.
> {FIRMA}

**Email 2 — Cómo funciona (día 5)**
Asunto: Un modelo partido en slots: qué protege y qué no
> Hemos publicado el post técnico sobre la arquitectura de slots y sus límites: {URL_POST}. Resumen: cada operador tiene como máximo 1/S del modelo; una coalición suficientemente grande podría reconstruirlo; y quien consulta puede destilarlo. Si algo no te cuadra, respóndenos.

**Email 3 — Demo (día 12)**
Asunto: Demo de 3 minutos y repositorio
> Ya hay demo reproducible: {DEMO}. Se ejecuta con {COMANDO}. Es un modelo pequeño repartido por etapas en varios procesos locales; no es una medida de rendimiento. Repositorio: {REPO}. Si algo falla, abre un issue; nos interesa más el fallo que el aplauso.

**Email 4 — Alpha (día 24, solo según rol)**
Asunto (operadores): ¿Quieres probar un nodo en la alpha cerrada?
> Abrimos plazas limitadas para operadores de la cohorte 1. Requisitos: {REQUISITOS}. Los pagos son de testnet, sin dinero real y sin garantía de ingresos futuros. El nodo tiene su slot en claro en memoria. Si te encaja, completa el formulario: {FORMULARIO}.

Asunto (desarrolladores): Alpha para cargas por lotes: ¿te interesa?
> Buscamos 15–30 desarrolladores con cargas batch tolerantes a latencia. Hay créditos de testnet. Sin streaming ni tools; los operadores pueden ver tus peticiones: no envíes datos sensibles. Formulario: {FORMULARIO}.

**Email 5 — Informe y siguiente paso (día 40)**
Asunto: Qué hemos medido (y qué ha fallado)
> Informe de las últimas semanas: {datos reales: nodos conectados, trabajos, tasa de fallos}. Lo que funcionó, lo que no, lo que viene. Si no tienes plaza todavía, seguirás en la lista; avisaremos antes de abrir la beta pública. Responde si quieres que cambiemos algo en el enfoque.

---

## F. Nota de prensa (borrador, no enviar antes de la puerta de alpha)

**PARA PUBLICACIÓN INMEDIATA — {CIUDAD}, {FECHA}**

**{NOMBRE} abre una alpha cerrada para probar una red de inferencia en la que ningún operador tiene el modelo completo**

{NOMBRE} anuncia el inicio de una alpha cerrada de una red experimental de inferencia de modelos abiertos. La red expone una API compatible con el formato de chat de OpenAI y reparte el modelo entre operadores independientes: cada operador ejecuta un único tramo ("slot") y recibe pago proporcional al trabajo verificado. Cada trabajo genera un recibo firmado verificable.

El proyecto se encuentra en fase experimental: funciona en testnet, sin token y sin liquidación con dinero real. {Citar solo resultados medidos: p. ej. "El equipo ha completado {N} trabajos en pruebas locales; la evidencia es pública."}

"{CITA del portavoz: debe ser real, aprobada por la persona citada y sin superlativos; p. ej. 'Queremos averiguar con operadores reales dónde se rompe este diseño y publicarlo.'}" — {Nombre, cargo}.

**Límites declarados.** Un nodo de cómputo mantiene su slot en claro en memoria; los operadores que ejecutan una petición pueden ver su contenido; una coalición suficientemente grande podría reconstruir el modelo; y quien consulta puede destilarlo. En simulaciones del equipo (no mediciones), la velocidad de generación por stream con 8 slots se sitúa en torno a 4–6 tokens por segundo, por lo que la red se orienta a cargas por lotes.

**Participar.** Operadores de GPU, desarrolladores y autores de modelos pueden apuntarse a la lista de espera en {URL}. Los pagos de la alpha son de testnet y no suponen garantía de ingresos futuros.

**Sobre {NOMBRE}.** {Descripción del equipo, real.} Nombre de trabajo sujeto a revisión de marca.

**Contacto de prensa:** {NOMBRE_CONTACTO}, {EMAIL}. (Rellenar; no usar direcciones de marcador.)

---

## G. Guion de demo de 3 minutos

**Requisitos:** demo multiproceso del repositorio con un modelo pequeño real repartido por etapas. Grabar en una sola toma con terminal legible (fuente grande). No editar tiempos de ejecución. Subtítulos en español e inglés.

| Tiempo | Pantalla | Voz en off |
|---|---|---|
| 0:00–0:15 | Título con estado en pantalla: "Alpha · testnet · sin token" | "Esto es {NOMBRE}, un experimento: una red de inferencia donde ningún operador tiene el modelo completo. Te enseño qué hace hoy y qué no." |
| 0:15–0:45 | Diagrama simple: modelo → S slots → un operador por slot | "El modelo se parte en slots. Cada operador ejecuta uno solo, así que nadie reúne más de 1/S del modelo." |
| 0:45–1:20 | Terminal: arrancar coordinador y N procesos de nodo (cada uno anuncia su slot) | "Aquí hay {N} procesos locales, cada uno con su slot. El coordinador los asigna con una baliza aleatoria." |
| 1:20–2:00 | Terminal: llamada con el SDK de OpenAI cambiando la `base_url`; respuesta de un modelo pequeño real | "Usamos el SDK de OpenAI, solo cambia la URL base. La respuesta llega repartida por etapas. Es un modelo pequeño y no es una medida de rendimiento." |
| 2:00–2:30 | Mostrar el recibo firmado y verificarlo con un comando; mostrar el libro de contribuciones con `work_share` | "Cada trabajo deja un recibo firmado ligado al nodo. Y el pago es proporcional al trabajo verificado; en testnet, sin dinero real." |
| 2:30–3:00 | Pantalla de límites: coalición, destilación, slot en claro, entradas visibles; QR/URL del repo y la lista | "Lo que no hace: no es privado frente a los operadores, no es a prueba de copia, y no es rápido para chat. Si quieres romperlo, está todo en el repositorio." |

**Comprobaciones antes de grabar:** que todo lo mostrado sea reproducible con el comando indicado; que ningún dato sensible, clave o token aparezca en pantalla; que no se muestren cifras no medidas.

---

## H. README de GitHub orientado a captación (borrador)

```markdown
# {NOMBRE}

Una red experimental de inferencia en la que **ningún operador tiene el modelo completo**.

> **Estado: alpha cerrada · testnet · sin token · sin pagos con dinero real.**
> No es privada frente a los operadores, no es a prueba de copia y no es adecuada para chat interactivo. Lee [Límites](#límites).

## Qué hace hoy
- API compatible con el formato de chat de OpenAI (`/v1/chat/completions`, `/v1/models`). Sin streaming, tools ni multimodal.
- El modelo se parte en S slots; cada operador ejecuta un único slot.
- Pesos en reposo cifrados con erasure coding (k-de-n) y manifiesto firmado.
- Recibos firmados (Ed25519) por trabajo; libro de contribuciones y lotes de liquidación (testnet).
- Demo multiproceso con un modelo pequeño real repartido por etapas.

## Pruébalo
{comandos reales y verificados; copiar de la demo}

## Qué hemos probado (y qué no)
- Probado: {lista basada en `docs/evidence/`}.
- No probado: nodos en redes independientes a escala; liquidación en testnet pública; auditoría independiente.

## Límites
- Un nodo de cómputo tiene su slot en claro en memoria.
- Los operadores que ejecutan tu petición pueden ver su contenido.
- Una coalición lo bastante grande podría reconstruir el modelo; quien consulta puede destilarlo (cifras en simulación: [`research/swarm-sim`](research/swarm-sim/README.md)).
- Velocidad simulada con S=8: ~4–6 tok/s por stream. Orientada a lotes.
- Sin garantías de ingresos para operadores. Sin token.

## Participar
- Lista de espera: {URL}
- Operadores: [guía de la alpha](docs/operadores.md)
- Autores de modelos: [guía de publicación](docs/autores.md)
- Seguridad: informa de vulnerabilidades en {SECURITY_CONTACT}. No incluyas secretos en issues.

## Licencia
{POR VERIFICAR: licencia del repositorio}. Cada modelo del catálogo lleva su propia licencia (p. ej. Gemma, Llama) y debe respetarse.
```

---

## I. FAQ de objeciones (versión pública)

**¿Es privado?** No frente a los operadores: quienes ejecutan tu petición pueden ver su contenido. No envíes datos sensibles. Los pesos y los trozos en reposo están cifrados, pero un nodo de cómputo tiene su slot en claro en memoria.

**¿Pueden copiar el modelo?** Ningún operador tiene el modelo completo. Una coalición suficientemente grande podría reconstruirlo y quien lo consulta puede destilarlo.

**¿Es descentralizado?** Está diseñado para repartir pesos y trabajo entre operadores independientes; en la alpha el coordinador y el catálogo los opera el equipo, por tanto no es descentralizado en su totalidad `{CONFIRMAR con product-architect}`.

**¿Hay token?** No. No hay token en v0.1 y no prometemos ninguno. Si alguna vez se plantea, será una opción futura, pública y sujeta a revisión legal por riesgos de valores.

**¿Cuánto gano si aporto mi GPU?** No lo sabemos y no lo prometemos. En la alpha los pagos son de testnet. Pago por trabajo verificado no equivale a ingresos garantizados.

**¿Es más barato que otros proveedores?** No tenemos datos medidos. Publicaremos coste real por 1.000 tokens cuando lo midamos.

**¿Es rápido?** No para chat interactivo. En simulación con S=8, ~4–6 tok/s por stream. Medidas reales: pendientes.

**¿Es compatible con OpenAI?** Para chat, en formato. Sin streaming, tools ni multimodal en v0.1.

**¿Qué prueba el recibo?** Que un nodo concreto ejecutó un trabajo concreto (firma Ed25519, hash de salida, medición de tokens). No prueba que la respuesta sea correcta.

**¿Puedo publicar mi modelo?** Sí, en la alpha con revisión y si la licencia lo permite. Las regalías son de testnet. No hay garantía de uso.

**¿Qué licencias aplican?** Las de cada modelo; se muestran en el catálogo. Respetamos las de los modelos base (Gemma, Llama).

**¿Está auditado?** No hay auditoría independiente todavía.

**¿Quién está detrás?** {Equipo real}. {Sin inventar credenciales ni inversores.}

**¿Por qué "NEXUS"?** Es un nombre de trabajo; existen otros productos con el mismo nombre y podemos cambiarlo antes de la beta pública.

**¿Dónde veo el estado real?** {URL}/estado y `docs/evidence/` en el repositorio.
