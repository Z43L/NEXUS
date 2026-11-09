# 02 · Posicionamiento y mensajes

Fecha: 2026-10-27. Base: BRIEF.md (sección 3, reglas de honestidad), `research/swarm-sim/README.md`, `NEXUS/site/index.html` y `01-mercado-y-competencia.md`. Nombre: "NEXUS" es nombre de trabajo y tiene riesgo de marca alto (01, §7); los textos usan `{NOMBRE}` solo donde conviene que sea fácil de sustituir.

## 1. Estado real que condiciona todo mensaje

- Alpha cerrada, **testnet**, **sin token**, **sin liquidación con dinero real**.
- v0.1: gateway OpenAI-compatible (chat; sin streaming, tools ni multimodal en H0), agente de nodo, CLI de publicación (partir, cifrar, erasure coding, manifiesto firmado), coordinador con slots, recibos firmados y libro de contribuciones, demo multiproceso con un modelo pequeño.
- No demostrado: nodos en redes independientes (H1), liquidación en testnet pública, auditoría de seguridad independiente, rendimiento a escala.
- Un nodo de cómputo tiene **su slot en claro en memoria**; el nodo que ejecuta una etapa también **ve las entradas que le llegan** (en H0 el worker ve el prompt completo; en la partición por slots la primera etapa ve embeddings, según `swarm-sim`, "no evalúa privacidad de las entradas"). Por tanto **los prompts no son privados frente a los operadores**.

> Observación para el equipo de landing (fuera de mi carpeta, no la he tocado): el borrador `NEXUS/site/index.html` dice "Privacidad por diseño" y "Tus pesos y tu memoria se quedan en tu máquina". Esas frases son ciertas para el modelo local H0 pero pueden leerse como que el prompt del cliente es privado, lo que no es cierto. Recomiendo sustituir por "ningún operador tiene el modelo completo" y añadir "los operadores que ejecutan tu petición pueden ver su contenido".

## 2. Posicionamiento

**Declaración (para uso interno):**

> Para desarrolladores que quieren una API estándar sobre modelos abiertos, y para dueños de GPU que quieren cobrar por trabajo verificado, {NOMBRE} es una red experimental de inferencia en la que **ningún operador tiene el modelo completo**, cada trabajo deja un **recibo firmado verificable** y el pago es **proporcional al trabajo verificado**. A diferencia de los proveedores centralizados, ningún proveedor único ve ni posee el modelo; a diferencia de las redes con token, no hay token ni promesa de rentabilidad. Es una alpha: la prioridad es aprender, no escalar.

**Categoría:** "red experimental de inferencia con pesos repartidos" (no "plataforma descentralizada de IA", demasiado amplio y saturado, ver 01).

**Tres diferenciadores defendibles hoy** (cada uno con su límite):

| Diferenciador | Qué es verdad | Límite que hay que decir |
|---|---|---|
| Ningún operador tiene el modelo completo | Cada operador fija en un único slot (1/S del modelo); asignación estratificada con baliza aleatoria; pesos en reposo cifrados con erasure coding k-de-n | Una coalición suficientemente grande podría reconstruirlo (con ~300 nodos por slot: 2 % de operadores P≈0,44; 5 % P≈0,99, simulación); quien consulta puede destilarlo; un Sybil sin huella ni comisión reúne un modelo de 16 slots por ~770 $ (parámetros ilustrativos) |
| Recibos firmados por trabajo | Recibos Ed25519 ligados a trabajo y nodo; verificación en router (H0 probado en local) | Probado en local y Compose, no entre redes independientes |
| Pago por trabajo verificado | Reparto proporcional a `work_share`; escrow por lotes (testnet/local) | No hay dinero real ni token; precio de referencia en micro-USD |

**Lo que no somos:** no somos más baratos (sin datos), no somos más rápidos (S=8 ≈ 4–6 tok/s por stream en simulación), no somos "privados", no somos "descentralizados" sin matiz, no somos una inversión.

## 3. Propuesta de valor por audiencia

### 3.1 Desarrolladores (demanda)
- **Promesa:** "Cambia la URL base y obtén una respuesta con recibo firmado de una red donde ningún operador tiene el modelo completo."
- **Pruebas disponibles hoy:** endpoints `/v1/chat/completions` y `/v1/models`; SDKs Python y TypeScript; recibos verificables; evidencia en `docs/evidence/`.
- **Límites a decir:** sin streaming, sin tools, sin multimodal; latencia baja de tokens/s (útil para batch); alpha, sin SLA, sin precios definitivos; los operadores ven el contenido de la petición.
- **Para quién es ahora:** quien experimenta, investiga o tiene cargas por lotes tolerantes a latencia.

### 3.2 Operadores de GPU (oferta)
- **Promesa:** "Aporta tu GPU a una red experimental y recibe pago por trabajo verificado; hoy en testnet, sin dinero real."
- **Pruebas disponibles hoy:** agente de nodo, recibos, libro de contribuciones, slots con asignación equilibrada por capacidad.
- **Límites a decir:** sin ingresos garantizados ni estimaciones; no hay liquidación con dinero real; el nodo tiene su slot en claro en memoria; recursos y requisitos de VRAM por slot (con S=4 el slot de 70B int4 ~11 GB deja fuera ~25 % de nodos en simulación).
- **Prohibido:** cualquier cifra de ganancias, "ROI", "ingresos pasivos".

### 3.3 Autores de modelos
- **Promesa:** "Publica un modelo con manifiesto firmado, pesos cifrados y regalías configurables, sin entregar los pesos en claro a un único operador."
- **Pruebas disponibles hoy:** CLI de publicación; `royalty_bps` y firma en el manifiesto; regalías a autores `.nram` en el lote de liquidación (testnet).
- **Límites a decir:** no impide la destilación ni la reconstrucción por coalición; las regalías son de testnet; la licencia del modelo base manda (Gemma, Llama); no hay demanda demostrada de este lado todavía.

### 3.4 Empresas
- **Promesa (futura, no vender ahora):** "Auditar qué nodo hizo qué trabajo con recibos firmados, y no depender de un solo proveedor."
- **Hoy:** no es un producto empresarial: sin auditoría independiente, sin SLA, sin cumplimiento (SOC 2 etc.). Mensaje permitido: "estamos buscando 3–5 equipos para pilotos de laboratorio, sin datos sensibles."

## 4. Pilares de mensaje

1. **Reparto, no magia.** El modelo se parte en slots; nadie tiene todo; decimos cómo y cuánto resiste (con cifras del simulador marcadas como tales).
2. **Prueba, no confianza ciega.** Recibos firmados, evidencia publicada, código abierto en lo que se pueda `[POR VERIFICAR licencia del repo]`.
3. **Pago por trabajo.** Sin token, sin rentabilidad prometida; el reparto es proporcional a trabajo verificado.
4. **Honestidad como ventaja.** Página de estado pública, límites explícitos, riesgos publicados. En un mercado con subvenciones y promesas (01, H5), esto diferencia.
5. **Estándar abierto.** API compatible con OpenAI; modelos abiertos con su licencia visible.

## 5. Tono

Técnico, sereno, con humor seco opcional; español neutro de España/LatAm (inglés en piezas internacionales). Frases cortas, verbos concretos. Siempre que se dé una cifra: de dónde sale (simulación, medida, supuesto). Sin signos de exclamación en superficies de producto, sin "revolucionario", "el futuro de", "democratizar", "unstoppable". Nunca atacar a competidores por nombre en público; compararse solo con hechos fuente-citados.

## 6. Cinco titulares candidatos

Todos compatibles con el estado real. Prueba A/B en la lista de espera (04).

1. **"Una API de IA donde ningún operador tiene el modelo completo."** Directo; es la fórmula del brief; riesgo: puede sonar a absoluto, por eso el subtítulo lleva el límite (coalición, destilación).
2. **"Inferencia con recibo: cada respuesta, firmada y verificable."** Enfatiza prueba; riesgo: si se interpreta como "respuesta correcta garantizada"; aclarar que el recibo prueba qué nodo hizo el trabajo, no la calidad del modelo.
3. **"Cambia la URL base. Reparte el modelo entre operadores independientes."** Orientado a devs; honesto en alpha.
4. **"Tu GPU, pagada por trabajo verificado (en testnet, por ahora)."** Orientado a operadores; el paréntesis es obligatorio.
5. **"Publica un modelo sin entregárselo entero a nadie."** Autores; riesgo: "sin entregárselo entero a nadie" requiere el matiz de que una coalición podría reunirlo; el subtítulo lo dice.

Subtítulo estándar sugerido para cualquiera: "Alpha cerrada en testnet, sin token. Una coalición lo bastante grande de operadores podría reconstruir el modelo; quien consulta puede destilarlo."

## 7. Afirmaciones permitidas y prohibidas (alineadas con la sección 3 del brief)

### Permitidas (con su condición)
- "API compatible con OpenAI para chat (`/v1/chat/completions`, `/v1/models`); sin streaming ni tools en v0.1."
- "Ningún operador tiene el modelo completo; cada uno ejecuta un único slot." (acompañar con el límite de coalición o enlazar a él)
- "Una coalición lo bastante grande podría reconstruirlo; quien consulta puede destilarlo."
- "Recibos firmados con Ed25519 ligados al trabajo y al nodo; verificados por el router."
- "Pesos en reposo cifrados con erasure coding k-de-n; los nodos de almacenamiento solo ven ciphertext."
- "Un nodo de cómputo tiene su slot en claro en memoria."
- "Estado: alpha cerrada, testnet, sin token, sin liquidación con dinero real."
- "Pago por trabajo verificado, proporcional a lo aportado."
- Cifras del simulador, siempre con "simulación, orden de magnitud, no medida".
- Evidencia publicada en `docs/evidence/` (100/100 jobs mock y real con salida limitada a 24 tokens; no es un benchmark).
- Comparaciones de precio de competidores **con fuente y fecha**.

### Prohibidas (no usar ni en redes ni en notas internas públicas)
- "Trustless", "imposible de copiar", "pesos nunca descargables", "privacidad total", "privado", "seguro" sin matiz, "descentralizado" sin matiz, "censura-resistente", "sin confianza".
- Cualquier promesa de **ganancias, APY, ROI, "ingresos pasivos", "gana X al mes"** a operadores.
- "Más barato que OpenAI/Together/etc." o cualquier benchmark propio de precio o latencia hasta que existan datos reales medidos.
- Clientes, logos, testimonios, usuarios, "miles de nodos", rondas de inversión, partners, ingresos: ninguno existe.
- "Token", "airdrop", "puntos que se convertirán en token", "preventa", "staking" como producto. (El token solo puede discutirse como opción futura con riesgo regulatorio de valores explícito, y no en superficie de marketing.)
- "Listo para producción", "enterprise-grade", "auditado" (no hay auditoría independiente).
- "Entrena modelos" o "fine-tuning descentralizado": el entrenamiento es investigación (entrenar 70B en GPUs de 24 GB exige ~59 etapas y compresión de activaciones ≥10×).
- Afirmar que recibos prueban "correctitud" de la respuesta.
- Usar el nombre de modelos o marcas de terceros como si fueran socios.

## 8. Tabla "Decimos / No decimos"

| Decimos | No decimos | Por qué |
|---|---|---|
| "Ningún operador tiene el modelo completo." | "Tu modelo es imposible de copiar." | Una coalición grande puede reconstruirlo; el consultante puede destilarlo |
| "Los nodos de almacenamiento solo ven ciphertext; la clave se libera al nodo asignado." | "Los pesos nunca son descargables." | El nodo de cómputo tiene su slot en claro |
| "Los operadores que ejecutan tu petición pueden ver su contenido." | "Tus prompts son privados." | Sin TEE/MPC no hay privacidad de entradas |
| "Pago por trabajo verificado (en testnet)." | "Gana X al mes con tu GPU." | Brief 3.4; no hay dinero real |
| "Sin token en v0.1." | "Pronto, token." / "Puntos = futuro token." | Brief 3.5; riesgo regulatorio |
| "Recibo firmado: prueba qué nodo hizo el trabajo y con qué entrada/salida." | "Respuesta garantizada correcta." | El recibo no valida calidad |
| "Con S=8, simulamos 4–6 tok/s por stream: pensado para batch." | "Rápido como los proveedores centralizados." | Es peor para chat interactivo |
| "Red experimental, alpha cerrada." | "Listo para producción." | Estado real |
| "Compatible con el formato de chat de OpenAI." | "Drop-in replacement de OpenAI." | Sin streaming, tools, multimodal |
| "Un Sybil sin huella ni comisión podría reunir un modelo de 16 slots por ~770 $ (parámetros ilustrativos); el stake solo no protege." | "El stake nos protege." | Es la conclusión del simulador |
| "Hemos probado 100/100 jobs en local (mock y real, salida de 24 tokens)." | "Probado a escala." | Evidencia limitada a H0/Compose local |
| "Código y evidencia públicos." | "Auditado por terceros." | No hay auditoría independiente |
| "Compatible con las licencias de cada modelo (se muestran en el catálogo)." | "Cualquier modelo abierto, sin condiciones." | Gemma/Llama imponen condiciones |

## 9. Guía rápida de comparación con competidores en público

- Permitido: "Petals fue pionero en repartir bloques de un LLM entre voluntarios (paper 2023); {NOMBRE} añade pago por trabajo y recibos." (fuente: https://arxiv.org/pdf/2312.08361)
- Permitido: "Chutes es una subred de Bittensor con pago por uso y TEE" (fuente: https://chutes.ai/pricing, fecha).
- No permitido: citar la estimación de subsidios (01, H5) como hecho; es de un analista.
- Nunca: "somos mejores que X". Siempre: "esto es lo que hace distinto".
