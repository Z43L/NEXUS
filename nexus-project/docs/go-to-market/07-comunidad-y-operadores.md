# 07 · Comunidad y operadores

Fecha: 2026-10-27. Programas y reglas para la alpha cerrada. Requisitos técnicos concretos (versiones, puertos, VRAM) son `[POR VERIFICAR con eng-runtime y product-architect]`; este documento define el marco, no las especificaciones. Revisión legal pendiente (LEGAL) para términos, política de uso y tratamiento de datos.

## 1. Programa de operadores alpha

### 1.1 Qué es y qué no es
Un programa de **pruebas** con cohortes pequeñas. Los operadores ayudan a validar el reparto por slots, el enrutado y los recibos. **Los pagos son de testnet**: no hay dinero real, no hay token y no hay garantía de ingresos futuros. No se publica ninguna estimación de ganancias, ni oralmente ni por escrito.

### 1.2 Criterios de selección
Selección por puntuación simple y revisión humana. No se vende ni se garantiza plaza.

| Criterio | Qué se busca | Peso |
|---|---|---|
| Aptitud técnica | Experiencia con Docker/Linux o macOS; capaz de seguir una guía y reportar errores | Eliminatorio |
| Hardware | VRAM/memoria suficiente para el slot de la cohorte; conexión de subida estable `[POR VERIFICAR requisitos]` | Eliminatorio |
| Diversidad de red | Redes/organizaciones/regiones distintas (necesario para demostrar H1 y limitar concentración) | Alto |
| Expectativas | Acepta por escrito: testnet, sin pagos, sin garantías | Eliminatorio |
| Motivación | Aprender, investigar, contribuir; no especulación de token | Alto |
| Compromiso | Disponible para responder en Discord y reportar semanalmente | Medio |
| Seguridad | Máquina dedicada o aislada; actualizaciones al día | Alto |
| Concentración | Máximo de nodos por operador en la cohorte `[SUPUESTO: 4]` para evitar sesgo en slots | Eliminatorio |

**Señales de rechazo:** preguntas centradas en "cuánto token/airdrop", intención de múltiples identidades, negativa a aceptar el aviso de testnet, infraestructura sin aislamiento.

### 1.3 Onboarding (primeros 7 días)
1. **Día 0:** correo de bienvenida con aviso de testnet y términos; acuerdo aceptado por escrito.
2. **Día 1:** guía de instalación en un comando (contenedor o paquete verificable con SHA-256; el sitio ya publica sumas de verificación). Prueba en una red aislada primero.
3. **Día 2:** verificación de capacidad; asignación al slot según la baliza tras cerrar el registro de la cohorte (el operador no elige slot).
4. **Día 3:** primer trabajo sintético etiquetado como tal; comprobar recibo propio.
5. **Día 5:** sesión de preguntas (30 min, grupos de 4–6).
6. **Día 7:** cuestionario breve: tiempo hasta funcionar, problemas, comprensión de límites.

Documentos a entregar: guía de instalación, guía de seguridad (qué datos llegan a tu nodo, cómo aislarlo, cómo apagarlo), política de uso aceptable, descripción de qué recoge el agente de nodo `[POR VERIFICAR]`, glosario (slot, recibo, `work_share`, testnet).

### 1.4 Soporte
- Canal de Discord por cohorte; horarios publicados (p. ej. laborables 10–18 h CET `[SUPUESTO]`); sin soporte 24/7.
- Objetivo de primera respuesta < 24 h `[SUPUESTO]`.
- Incidencias de seguridad: correo dedicado `{SECURITY_CONTACT}`; nunca por canales públicos; no se piden claves ni secretos a los operadores.
- Registro de incidencias y retrospectiva quincenal.
- Derecho de pausa: el equipo puede detener la cohorte ante incidentes.

### 1.5 Comunicación honesta sobre pagos en testnet
Reglas obligatorias para toda comunicación a operadores:
1. Cada documento y cada correo incluye la frase: "**Los pagos de la alpha son de testnet: no tienen valor monetario y no garantizan ingresos futuros.**"
2. No usar "ganarás", "recompensas", "rendimiento", "APY", "ROI", "ingresos pasivos". Sí: "contabilizamos trabajo verificado".
3. No insinuar token, airdrop ni conversión futura de puntos. Si preguntan: "No hay token en v0.1. Cualquier decisión futura será pública, sujeta a revisión legal por riesgos de valores y sin promesas previas".
4. Mostrar el libro de contribuciones al operador (su `work_share`) para que vea cómo se cuenta el trabajo.
5. Cuando haya liquidación real (no antes de la beta y con revisión legal/auditoría), anunciar con antelación, con términos propios; no retroactividad implícita.
6. Explicar los límites de seguridad: el nodo tiene su slot en claro; los operadores ven las peticiones que procesan.
7. Reportar públicamente la actividad real de la red (incluida la sintética) para evitar falsas expectativas.

### 1.6 Responsabilidades del operador
- Mantener el nodo actualizado; no modificar el agente para falsear recibos.
- No intentar extraer pesos del slot más allá de lo previsto ni colaborar con otros operadores para reunir slots (se prohíbe en los términos; detección es investigación abierta).
- No ejecutar contenido en nombre de terceros sin respetar la política de uso.
- Reportar vulnerabilidades de forma privada.

### 1.7 Salida del programa
El operador puede salir cuando quiera, avisando; el equipo puede expulsar por incumplimiento. Se explica el efecto en el slot (la salida del operador mayor tardaría ~27 min en restaurarse, simulación) para que entienda el impacto.

## 2. Reglas de comunidad y moderación

### 2.1 Reglas (resumen para Discord/GitHub)
1. **Respeto.** Sin acoso, discriminación ni ataques personales.
2. **Sin especulación financiera.** No hablamos de precio de tokens ni de inversión; NEXUS no tiene token. Hilos de ese tipo se eliminan.
3. **Sin promesas de ingresos** de ningún miembro hacia otros.
4. **Sin spam ni autopromoción** de otros proyectos o productos.
5. **Sin datos sensibles.** Nunca pegues claves, tokens, credenciales ni datos personales. Si lo haces, lo retiramos y te pedimos rotarlos.
6. **Seguridad responsable.** Vulnerabilidades por canal privado; divulgación coordinada.
7. **Honestidad.** Cita fuentes y marca las estimaciones.
8. **Idiomas:** español e inglés.
9. **Licencias.** Respeta las licencias de modelos y de código.
10. **Contenido ilegal o dañino** se elimina y puede reportarse.

### 2.2 Escalado de moderación
| Nivel | Conducta | Acción |
|---|---|---|
| 1 | Off-topic, spam leve | Aviso y borrado |
| 2 | Especulación de token insistente, promesas de ingresos | Borrado, aviso privado, silencio temporal |
| 3 | Acoso, difusión de datos sensibles, suplantación | Expulsión temporal; registro |
| 4 | Ataques deliberados, intentos de fraude, doxxing | Expulsión permanente; informe a autoridades si procede |

Equipo de moderación: COM + 2 voluntarios de confianza tras 8 semanas `[SUPUESTO]`. Registro de decisiones. Apelación por correo.

### 2.3 Protocolos
- **Rumores de token o estafas con el nombre del proyecto:** fijar un mensaje oficial ("NEXUS no tiene token. Cualquier ofrecimiento es fraude."); avisar en el canal y en X.
- **Suplantación de cuentas:** lista de canales oficiales publicada en la landing.
- **Incidente de seguridad:** plantilla pública: qué ocurrió, qué datos afectan, qué hacer, cuándo habrá novedades. Sin culpar a operadores.
- **Crisis de marca (reclamación por "Nexus"):** consultar LEGAL; no responder públicamente sin revisión.

### 2.4 Gobernanza de comunidad
En alpha, decisiones del equipo con registro público de cambios; propuestas por GitHub Discussions. Sin votaciones con valor económico ni gobernanza por token.

## 3. Programa de autores de modelos

### 3.1 Objetivo
Probar el flujo "partir -> cifrar -> erasure coding -> manifiesto firmado" con 2–5 autores y recoger feedback sobre regalías, licencias y demanda. No es un canal de crecimiento en la alpha.

### 3.2 Criterios de admisión
| Criterio | Detalle |
|---|---|
| Licencia | El modelo base y los datos permiten redistribución y uso comercial/inferencia por terceros; se revisa caso a caso (Gemma, Llama y otras imponen condiciones) |
| Autoría | El autor firma el manifiesto con su clave (`author_pubkey`); verificación de identidad básica |
| Calidad y seguridad | Modelo documentado (tarjeta de modelo, uso previsto, limitaciones, fuentes de datos); sin contenido ilegal ni malware (pesos serializados no confiables) |
| Expectativas | Acepta: testnet, sin garantía de uso ni de ingresos, riesgo de destilación y coalición |
| Tamaño | Compatible con la cohorte de slots disponibles `[POR VERIFICAR]` |

### 3.3 Proceso
1. Solicitud con tarjeta de modelo y licencia.
2. Revisión (CTO + LEGAL) en <= 10 días laborables `[SUPUESTO]`.
3. Publicación con el CLI en un entorno de pruebas; revisión del manifiesto (firma, Merkle, `royalty_bps`, licencia).
4. Inclusión en catálogo de la alpha con la licencia visible.
5. Informe mensual al autor: peticiones servidas y regalías de testnet acreditadas.

### 3.4 Comunicación sobre regalías
- `royalty_bps` define la parte del pago que se acredita al autor; en alpha es testnet.
- No prometer demanda ni ingresos; no usar "gana regalías" sin "en testnet".
- Advertir: los operadores de cómputo tienen su slot en claro; una coalición grande podría reconstruir el modelo; los consultantes pueden destilarlo. Si el secreto fuerte del modelo es imprescindible, desaconsejar la publicación.
- Derecho de retirada: el autor puede retirar el modelo del catálogo; los trozos ya distribuidos se marcan como revocados y se rota la clave `[POR VERIFICAR con eng-storage el comportamiento de revocación]`.

### 3.5 Obligaciones y reconocimiento
Mantener la licencia y la documentación al día; responder a incidencias; reconocimiento en el catálogo y en el blog (con permiso). Sin pagos por captación y sin "embajadores" remunerados en alpha.

## 4. Kit de moderadores y respuestas tipo

- *"¿Cuándo token?"* -> "NEXUS no tiene token en v0.1 y no prometemos ninguno. Si algún día se plantea, será público y sujeto a revisión legal. No hablamos de precios ni de inversión aquí."
- *"¿Cuánto se gana con un nodo?"* -> "No lo sabemos y no lo prometemos. Los pagos de la alpha son de testnet."
- *"¿Es privado?"* -> "No frente a los operadores que ejecutan la petición. No envíes datos sensibles."
- *"¿Es seguro?"* -> "Es una alpha; sin auditoría independiente aún. Publicamos los límites en {URL}/estado."
