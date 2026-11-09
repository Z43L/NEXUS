# 04 · Modelo de amenazas

Versión 0.1 · 2026-10-27. **Este documento manda sobre el marketing**: la lista de afirmaciones permitidas y prohibidas (§7) es la fuente para landing y go-to-market. Etiquetas: **[SIM]** simulador; **[EXISTE]** código probado en el repo; **[FUTURO]** no implementado; **[NO RESUELTO]** línea de investigación.

## 1. Alcance y supuestos

- Producto: v0.1 alpha cerrada, testnet, sin token, sin dinero real. Gateway, coordinador, vault y libro **centralizados** (equipo).
- Modelo base con licencia que permite lo que hacemos (no verificado: `[POR VERIFICAR]` por modelo).
- No se cubre: seguridad del SO del operador, ataques físicos, canales laterales de GPU.

## 2. Activos

| ID | Activo | Dueño | Valor / impacto si se pierde |
|---|---|---|---|
| A1 | Pesos del modelo (completos) | Autor | Pérdida de ventaja y de regalías; copia libre |
| A2 | Slot en claro (1/S) | Autor | Fuga parcial; con S pequeño es significativa |
| A3 | `master_key` / claves por slot (KeyVault) | Equipo | Descifra todos los fragmentos almacenados |
| A4 | Prompts y respuestas del cliente | Cliente | Confidencialidad |
| A5 | Integridad de la salida | Cliente | Respuestas falsas facturadas |
| A6 | Integridad del libro y de los lotes | Todos | Pagos incorrectos |
| A7 | Claves Ed25519 (nodos, autor, coordinador, signer) | Cada parte | Suplantación, firma de recibos falsos |
| A8 | Disponibilidad del servicio | Cliente/operadores | Ingresos y reputación |
| A9 | Presupuesto de pago (depósito de escrow) | Pagador | Pérdida de fondos (v0.2) |

## 3. Adversarios

| ID | Adversario | Capacidades | Objetivo |
|---|---|---|---|
| X1 | **Operador curioso** | Un nodo honesto en forma; lee su memoria/disco | Obtener su slot, prompts que pasan por él |
| X2 | **Coalición de operadores** | Varios operadores colaboran, cada uno con su slot | Reunir todos los slots ⇒ reconstruir el modelo |
| X3 | **Sybil** | Muchas identidades baratas | Obtener todos los slots; acaparar pagos; sesgar la baliza |
| X4 | **Nodo que miente** | Devuelve cómputo falso/barato, infla tokens, copia recibos | Cobrar sin trabajar |
| X5 | **Consumidor que destila** | API legítima; muchas peticiones | Entrenar un modelo propio con las salidas |
| X6 | **Gateway/coordinador comprometido** | Control del plano de control | Ver todos los prompts, falsificar recibos/lotes, robar claves |
| X7 | **Cliente malicioso** | Peticiones abusivas, lectura cruzada | DoS, ver trabajos de otros, evadir cuota |
| X8 | **Autor malicioso** | Publica manifiesto/modelo trampa | Pesos con puerta trasera, licencia falsa, DoS de nodos |
| X9 | **Red** | Man-in-the-middle, replay | Interceptar activaciones/claves, reinyectar mensajes |

## 4. Ataques, mitigaciones, riesgo residual

### 4.1 Confidencialidad de pesos

| Ataque | Adversario | Mitigación presente | Mitigación futura | Riesgo residual |
|---|---|---|---|---|
| Leer el slot de la memoria del nodo | X1 | Un operador solo conoce 1/S **[SIM: `max_fraccion_por_operador = 1/S`]**; clave por slot | TEE con attestation (ADR-06) | **Alto para el slot propio**: está en claro. No es protección del 1/S |
| Un operador con varios nodos obtiene varios slots | X1 | Operador fijo en un slot (una identidad lógica) | Detección de huella por nodo **[NO RESUELTO]** | Depende de que "operador" = identidad real; Sybil lo rompe (X3) |
| **Coalición reúne todos los slots** | X2 | Ninguna en v0.1 (asignación aleatoria no basta) | Corte por capa T; TEE; coste de identidad | **Alto.** **[SIM]** S=16, ~300 nodos/slot, T=1: coalición del 2 % de operadores P≈0,44; 5 % P≈0,99. T=8: 10 % → 0,005; 30 % → 0,995 |
| Coalición en el diseño de 3 réplicas por etapa | X2 | Menos nodos por etapa | — | **[SIM]** escenario 1: 30 % de operadores, S=8: 0,03; S=16: 0,0005. **No es el diseño elegido**: no usar esta cifra para el sistema final |
| Más capacidad ⇒ más copias de cada trozo | X2 | — | Limitar réplicas por slot | **[SIM]** 5 réplicas por etapa, S=8: exposición 0,22 @30 %. Fiabilidad y secreto compiten |
| Robar fragmentos del almacenamiento | X1/X9 | Ciphertext + EC k-de-n; clave aparte | — | Bajo si la clave no se filtra; el atacante necesita k fragmentos **y** la clave |
| Robar la `master_key` del vault | X6 | Vault separado, claves por slot derivadas | HSM / vault distribuido (umbral) | **Alto en v0.1**: si el vault es del equipo, el equipo puede reconstruir el modelo (declarar) |
| Exfiltrar pesos tras salir de la red | X1/X2 | Ninguna técnica: los pesos descargados no se devuelven al retirar stake **[SIM escenario 7]** | — | **Irreductible** sin TEE: lo descargado queda copiado |

### 4.2 Sybil y economía de ataque

| Ataque | Mitigación presente | Futura | Riesgo residual |
|---|---|---|---|
| Crear identidades para cubrir los S slots | Asignación estratificada tras baliza: el atacante no elige slot **[SIM]**: 54 identidades (p99 115) vs 16 si elige | Comisión de registro no reembolsable; huella por nodo; prueba de hardware | **[SIM, parámetros ilustrativos]** reunir un modelo de 16 slots ≈ 770 $ y ~4 meses; **el stake solo no protege** (se recupera el capital y se conservan los pesos). Comisión 500 $ ⇒ ~27 500 $. S=16, T=8 ⇒ ~695 identidades |
| Manipular la baliza o ver el orden de asignación | Baliza publicada tras cerrar registro (por el coordinador) | Baliza verificable (p. ej. compromiso-revelación de múltiples partes, o beacon público) | **Alto en v0.1**: el coordinador la controla |
| Hardware falso (prueba de capacidad débil) | Mediciones de velocidad reales por heartbeat | Pruebas de capacidad adversariales | **[SIM, supuesto frágil]** si la prueba es barata de pasar el coste real baja |
| Huella por nodo para detectar copias | — | Códigos resistentes a colusión (Tardos) y marcas robustas a cuantización/fine-tuning | **[NO RESUELTO]** línea de investigación; el atacante promedia copias y borra marcas |

### 4.3 Integridad del cómputo (nodo que miente)

| Ataque | Mitigación presente | Futura | Riesgo residual |
|---|---|---|---|
| Inflar tokens | v0.1 objetivo: el gateway cuenta tokens con su propio tokenizer y rechaza discrepancias > 1 %. **Ojo:** en H0 esa comprobación (`NEXUS/nexus/h0/router.py` l.959) compara el recibo con `engine_prompt_tokens/engine_completion_tokens` **declarados por el propio worker en el recibo**, no con una medida independiente del gateway (la spec §7.1 lo describía así, el código no lo hace). Es consistencia interna, no verificación | Conteo independiente en gateway (tokenizer del modelo) y en el último slot | **Medio** hasta implementar el conteo independiente |
| Devolver basura/cómputo parcial | Encadenado `out_hash/in_hash` entre etapas (detecta manipulación en tránsito, **no** corrección) | Canarios 1–2 %; doble ejecución muestreada 2 % con tolerancia numérica; reputación; slashing | **Medio-alto en v0.1**: sin verificación activa; un nodo puede mentir sin ser detectado. No existe prueba de que ejecutó el modelo (no zkML) |
| Falsificar recibo | Ed25519 + clave fijada (fingerprint) por nodo **[EXISTE]** | — | Bajo; **un recibo firmado prueba "este nodo declara esto", no "esto se calculó"** |
| Replay de recibo/lote | `claimedJobs` global en escrow; hojas V2 ligadas a chain/escrow/token; nonce en peticiones **[EXISTE]** | Anti-replay en capa de red | Bajo |
| No determinismo fp entre GPUs rompe doble ejecución | — | Tolerancia en activaciones; comparación por argmax en T=0 | **[POR VERIFICAR]** (experimento E-Determinismo) |
| Nodo que se queda con la clave y se va | — | TEE; rotación de clave por época (costosa: reencripta) | Alto; ver ADR-06 |

### 4.4 Consumidor que destila

| Ataque | Mitigación | Riesgo residual |
|---|---|---|
| Recolectar muchas (prompt, salida) y entrenar un modelo propio | Cuotas por cliente, rate limits, ToS (licencias del modelo base) | **Irreductible.** Cualquier API que sirva el modelo permite destilación. Particionar pesos **no** protege contra esto. Debe decirse |

### 4.5 Plano de control comprometido

| Ataque | Mitigación presente | Futura | Residual |
|---|---|---|---|
| Gateway ve todos los prompts | Retención 30 días con `secure_delete` (H0) | Cifrado del prompt hacia TEE; no hay solución sin TEE/MPC | **Alto.** Declarar: "el gateway ve el texto" |
| Coordinador falsifica recibos/`work_share` | Recibos de etapa firmados por nodo; libro append-only | Coordinadores múltiples/firma umbral; transparencia (Merkle log) | Alto en v0.1 |
| Signer del escrow autoriza pagos falsos | Límite = depósito; policy hash; fingerprints pinneados **[EXISTE]**; ventana de disputa 7 días **[EXISTE]** | Disputas con bond/slash de nodo; auditoría; multisig | **Alto**: el README del escrow lo reconoce; el árbitro es el `owner` |
| Credencial expuesta en historial (`8445b54`) | Eliminada del árbol actual | **Rotación en el proveedor (acción humana)** | Mientras no se rote, comprometida |

### 4.6 Red, clientes y autores

| Ataque | Mitigación presente | Residual |
|---|---|---|
| MITM / interceptar activaciones | TLS + CA fijada en nodo H1 (probado local) **[EXISTE]**; v0.1 loopback/LAN | Activaciones **no** van cifradas extremo a extremo entre nodos más allá de TLS: el coordinador las ve |
| Acceso cruzado entre clientes | `job_access_allowed`, 404 a otros clientes **[EXISTE]** | Bajo |
| DoS / cuotas | 503 + `Retry-After`, límites de cola, cuotas por cliente **[EXISTE]** | Medio |
| Manifiesto/modelo trampa | Firma del autor + `verify()`; licencia obligatoria | Medio: la firma identifica, no certifica contenido benigno. Requiere revisión/lista de autores aprobados en alpha |
| Fuga en logs | Sin prompts en logs; retención acotada | A verificar por auditoría |

## 5. Postura de confianza (resumen honesto)

| Quién | Ve | Puede |
|---|---|---|
| Nodo de cómputo (X1) | Su slot en claro; activaciones de su etapa; si es slot 0: embeddings de los prompts; si es último: logits | Copiar su slot; mentir sin ser detectado (v0.1) |
| Nodo de almacenamiento | Fragmentos cifrados | Negar servicio |
| Coalición suficiente | Todos los slots | Reconstruir el modelo |
| Gateway/coordinador/vault (equipo) | Prompts, respuestas, claves | Todo (en v0.1 es el modelo de confianza) |
| Consumidor | Salidas | Destilar |
| Autor | Su modelo completo | — |

## 6. Prioridades de mitigación

| Prioridad | Acción | Cuándo |
|---|---|---|
| P0 | Rotar credencial `8445b54`; escaneo de secretos en CI | Ya |
| P0 | Etiquetar en todo el producto: "gateway ve el texto", "slot en claro en el nodo" | v0.1 |
| P1 | Verificación activa (canarios + doble ejecución) | v0.2 |
| P1 | Identidad con coste + baliza verificable | v0.2–1.0 |
| P2 | Corte por capa T / TEE | v1.0 (según E-TEE, E-CorteT) |
| P2 | Revisión de seguridad independiente del escrow antes de testnet pública | v0.2 |

## 7. Afirmaciones para marketing (CRÍTICO para landing y GTM)

### 7.1 Permitidas (con el matiz indicado)

| # | Afirmación | Condición / apoyo |
|---|---|---|
| OK-1 | "Ningún operador individual tiene el modelo completo." | Añadir: "una coalición suficientemente grande podría reconstruirlo". Apoyo: **[SIM]** `max_fraccion_por_operador = 1/S` |
| OK-2 | "El modelo se reparte en S partes; cada operador sirve una." | Describir como alpha/testnet |
| OK-3 | "API compatible con OpenAI (chat completions, no streaming en alpha)." | `NEXUS/nexus/h0/router.py` |
| OK-4 | "Cada trabajo produce un recibo firmado (Ed25519) verificable." | Aclarar que prueba **medición y autoría del recibo**, no que el cálculo fuese correcto |
| OK-5 | "Pago por trabajo verificado." | Sin cifras de ingresos; en testnet |
| OK-6 | "Alpha cerrada, testnet, sin token, sin dinero real." | Obligatorio visible |
| OK-7 | "Los pesos en reposo se guardan cifrados y fragmentados (erasure coding)." | Solo cuando `nexus_storage` esté probado; cripto marcada "no auditada" |
| OK-8 | "El diseño se apoya en un simulador abierto; las cifras son órdenes de magnitud, no medidas." | Citar `research/swarm-sim` |
| OK-9 | "Más lento que una API centralizada: pensado para batch/asíncrono." | **[SIM]** 1,6–7 tok/s por stream |
| OK-10 | "Sustituir un nodo caído es reenrutar; recuperar capacidad tras una salida grande tarda decenas de minutos en simulación." | **[SIM]** ~27 min p50 en el escenario modelado |
| OK-11 | "El operador ve en claro la parte del modelo que sirve, y el gateway ve el texto de las peticiones." | Debe estar visible en la landing |
| OK-12 | "Prototipo local completó 100/100 trabajos de prueba con recibos válidos contra un motor real (salida ≤ 24 tokens)." | `docs/evidence/h0-real-2026-10-25.json`; no es benchmark |
| OK-13 | "Respetamos la licencia de cada modelo; cada modelo del catálogo muestra la suya." | Cuando exista catálogo |

### 7.2 Prohibidas

| # | Afirmación prohibida | Por qué |
|---|---|---|
| NO-1 | "Trustless", "sin confianza", "sin terceros" | El plano de control es centralizado; el gateway ve prompts; el signer del escrow es de confianza |
| NO-2 | "Imposible de copiar/robar/reconstruir el modelo" | Coaliciones (**[SIM]** 2 %→0,44; 5 %→0,99), copia por slot en claro, destilación |
| NO-3 | "Los pesos nunca se pueden descargar" | El nodo descarga y descifra su slot; no hay forma de impedir su copia |
| NO-4 | "Privacidad total", "tus datos nunca salen", "tus prompts son privados" | Gateway, slot 0 (embeddings) y último slot (logits) ven información; no hay TEE/MPC |
| NO-5 | "Descentralizado" sin matiz | Gateway, coordinador, vault y libro son del equipo en v0.1 |
| NO-6 | "Más barato que OpenAI/Together/etc." o cualquier comparación de precio | `[POR VERIFICAR]`; sin medición de coste ni de mercado |
| NO-7 | "Rápido", "baja latencia", "tiempo real" | **[SIM]** 1,6–7 tok/s por stream |
| NO-8 | "Gana X al mes", "ingresos pasivos", "rentabilidad", "ROI" para operadores | Brief regla 4; la spec calcula céntimos/día para E2B |
| NO-9 | Mencionar token, "NEX", staking con rendimiento, airdrop, preventa | No hay token; riesgos regulatorios (valores) |
| NO-10 | "Seguro", "auditado", "verificado criptográficamente" sobre la red completa | Sin auditoría; cripto en Python puro marcada NOT AUDITED; escrow sin revisión independiente |
| NO-11 | "Verificación de que el modelo se ejecutó correctamente" / "prueba de inferencia" | No hay zkML ni verificación activa en v0.1; el recibo prueba medición |
| NO-12 | "Resistente a Sybil", "protegido contra colusión" | **[SIM]** el stake solo no protege; huella **[NO RESUELTO]** |
| NO-13 | "Miles de nodos", "red global", "clientes", logos, testimonios, benchmarks de usuarios | No existen (5000 nodos son del simulador) |
| NO-14 | "Entrenamiento distribuido", "fine-tuning descentralizado" como capacidad | Solo línea de investigación; **[SIM]** supuestos ideales |
| NO-15 | "Compatible con OpenAI" sin acotar | Solo `/v1/chat/completions` y `/v1/models`, sin streaming ni tools |
| NO-16 | "Liquidación on-chain en producción", "pagos en cripto" | Solo escrow local con token mock (Anvil); sin testnet pública |
| NO-17 | "Resistente a censura" | No evaluado |
| NO-18 | Usar el nombre/logos de modelos (Gemma, Llama…) como aval | Licencias y marcas |

### 7.3 Texto modelo (alpha)

> NEXUS es una alpha cerrada en testnet, sin token y sin dinero real. El modelo se reparte en partes entre operadores independientes: ningún operador tiene el modelo completo, aunque una coalición lo bastante grande podría reconstruirlo y quien consulta puede destilarlo. El operador ve en claro la parte que sirve, y el gateway ve el texto de las peticiones. Cada trabajo genera un recibo firmado que mide el consumo; no demuestra por sí solo que el cálculo sea correcto. Es más lento que una API centralizada.
