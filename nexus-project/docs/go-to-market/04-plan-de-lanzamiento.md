# 04 · Plan de lanzamiento

Fecha: 2026-10-27. **Todos los objetivos numéricos son supuestos** (etiquetados `[SUPUESTO]`): no hay datos de partida. Se revisan al final de cada fase con las métricas de 06. El plan está condicionado a que el producto cumpla las puertas técnicas de cada fase; si no, se retrasa el marketing, no se adelanta el producto en el discurso.

Roles usados (pueden ser una sola persona al principio): **CEO/Founder**, **CTO/Eng** (ingeniería), **GTM** (responsable de go-to-market, este rol), **COM** (comunidad y soporte), **DEVREL** (documentación y relaciones con desarrolladores), **LEGAL** (asesoría externa), **FIN** (negocio/finanzas).

Semana 1 = semana del **lunes 2026-11-02** `[SUPUESTO]` (ajustar a la decisión real de arranque).

## 1. Principios

1. **Honestidad primero (BRIEF §3).** Cada pieza pública pasa la lista de verificación de 02 antes de publicarse.
2. **Alpha cerrada de verdad:** invitaciones, cohortes pequeñas, testnet; no abrir registro público hasta cumplir las puertas.
3. **Operadores antes que demanda**, con matices (ver §4): sin nodos reales distintos no hay demostración del reparto.
4. **Aprender sobre vender:** el objetivo de la alpha es validar (a) que el reparto por slots funciona entre operadores reales, (b) coste real por 1.000 tokens, (c) disposición a usar y a operar.
5. **Sin token, sin subsidio.** No se compra crecimiento con promesas; la tracción vendrá por interés técnico.
6. **Nombre provisional** (01, §7). Decisión de marca antes de la beta pública.

## 2. Fases

### Fase 0 · Pre-lanzamiento (90 días) — lista de espera
**Objetivo:** construir una lista de espera cualificada, validar mensajes y reclutar la primera cohorte de operadores, sin vender ni prometer.

| Elemento | Detalle |
|---|---|
| Duración | 90 días (semanas 1–13) |
| Activos | Landing con lista de espera (formulario con tres roles: operador, desarrollador, autor), página de estado honesta, post técnico de arquitectura (05), repositorio público con README de captación, simulador y evidencia |
| Puerta de salida a alpha | (1) Demo multiproceso con modelo pequeño real repartido por etapas funcionando y grabada; (2) agente de nodo instalable con un comando en Linux/macOS; (3) política de uso, aviso de testnet y términos revisados por LEGAL; (4) decisión de nombre/marca o aceptación explícita del riesgo; (5) rotada la credencial expuesta en `8445b54` (BRIEF §3.7) |
| Objetivos `[SUPUESTO]` | 400–1.000 correos en lista (50–60 % desarrolladores, 30–40 % operadores, ≤10 % autores); ≥ 30 entrevistas de descubrimiento (10 operadores, 15 desarrolladores, 5 autores); 3 versiones de titular probadas con ≥ 100 visitantes cada una; ≥ 25 operadores candidatos con formulario de aptitud completo; ≥ 150 estrellas en GitHub (indicador secundario, no objetivo vanidoso) |

### Fase 1 · Alpha cerrada (≈ 8–12 semanas, comienza ~semana 7)
**Objetivo:** demostrar con operadores reales distintos que el reparto por slots funciona, medir coste y fiabilidad, y cerrar el primer bucle de feedback.

- **Cohorte 1 (operadores):** 8–16 operadores invitados `[SUPUESTO]`, de al menos 3 organizaciones/redes distintas (puerta técnica H1: redes independientes). Nodos solo en testnet.
- **Cohorte 1 (desarrolladores):** 15–30 invitados `[SUPUESTO]` con cargas batch, créditos de prueba.
- **Autores:** 2–3 pilotos (publicación y manifiesto).
- **Medimos:** tasa de trabajos completados, discrepancia de tokens, tokens/s por stream, coste real por 1.000 tokens, tiempo de unión de nodo a slot, incidencias de seguridad, NPS cualitativo.
- **Puerta de salida a beta pública:** (1) H1 entre ≥ 3 redes independientes demostrado con evidencia publicada; (2) liquidación de lotes en testnet pública con transacciones verificables; (3) revisión de seguridad al menos interna, y plan de auditoría independiente contratada o calendarizada; (4) tasa de trabajos completados ≥ 95 % durante 2 semanas `[SUPUESTO]`; (5) medición real de coste y velocidad publicada; (6) nombre decidido; (7) 0 incidentes de seguridad abiertos de severidad alta.

### Fase 2 · Beta pública (≈ 3 meses)
**Objetivo:** abrir el registro público para desarrolladores y operadores con límites, sin dinero real salvo decisión explícita posterior (cumplimiento).

- Registro público con cuotas y límites de uso por cuenta (el sistema ya soporta cuotas y cuentas con scrypt, según el estado).
- Catálogo con 2–4 modelos con licencia visible `[SUPUESTO]`.
- Programa de autores abierto con revisión previa.
- **Objetivos `[SUPUESTO]`:** 100–300 nodos registrados con ≥ 30 % activos semanalmente; 300–1.000 desarrolladores registrados con ≥ 20 % haciendo ≥ 1 petición semanal; ≥ 5 modelos publicados por ≥ 3 autores.
- **Dinero real:** solo si hay revisión legal, auditoría de contratos y decisión del CEO. En caso contrario, la beta permanece en testnet.
- **Puerta de salida a GA:** ver §2.4.

### Fase 3 · GA (disponibilidad general)
Condiciones mínimas (no fechadas): auditoría independiente de seguridad completada y hallazgos críticos cerrados; liquidación en producción con revisión legal (token solo si pasa revisión como opción, sin lanzarlo por defecto); SLA definido; precios publicados con coste real; soporte con horarios; programa para empresas con alcance claro; documentación completa. Hasta entonces, no se usa la expresión "GA".

## 3. Canales por fase

| Canal | Fase 0 | Alpha | Beta | Notas / riesgos |
|---|---|---|---|---|
| **Comunidades de GPU/hardware** (r/LocalLLaMA, foros de hardware, Discords de llama.cpp/Ollama, servidores de homelab) | Preguntas de investigación (¿qué os frenaría?), sin spam; posts explicativos | Reclutar cohorte de operadores | Programa abierto | Respetar normas de cada comunidad; autopromoción limitada; avisar siempre "alpha, testnet, sin pagos reales" |
| **Hacker News** | Post técnico de arquitectura (no "Show HN" aún) | **Show HN** cuando haya demo reproducible | Update de beta | Titular sin superlativos; estar disponible 8–12 h para responder (05) |
| **Reddit** (r/selfhosted, r/LocalLLaMA, r/MachineLearning) | Posts técnicos | Hilos de resultados medidos | Anuncios de beta | Cada subreddit tiene sus reglas; no cross-post masivo |
| **X** | Hilo de arquitectura y límites; construir en público | Resultados semanales | Anuncios | Evitar lenguaje cripto; no seguir ciclos de especulación |
| **GitHub** | Repo, simulador, evidencia, issues `good first issue` | README de captación, releases | Contribuciones | Licencia del repo `[POR VERIFICAR]`; nunca subir secretos |
| **Discord** (propio) | Abrir servidor con reglas (07) | Canales por cohortes | Soporte | Moderación estricta contra especulación de token |
| **Podcasts** | Preparar kit de prensa; proponerse a 3–5 podcasts técnicos de IA abierta/sistemas `[POR VERIFICAR lista concreta]` | 1–2 apariciones | 2–4 | Contar límites; no usar cifras sin etiqueta |
| **Conferencias y meetups** | Charla propuesta a 2–3 eventos de sistemas/IA abierta (FOSDEM, USENIX/OSDI, NeurIPS workshops, eventos locales de IA) `[POR VERIFICAR fechas y CFP]` | Demo en meetups locales | Charlas | Priorizar eventos técnicos sobre cripto |
| **Universidades** | Contacto con 3–5 grupos de sistemas distribuidos/IA; ofrecer simulador y datos | Pilotos de nodos y colaboración | Cursos/proyectos | Valor: investigación y legitimidad; sin exclusividad |
| **Newsletter/blog propio** | Serie de 5 emails y blog técnico | Informes quincenales | Mensual | Cadencia fija |
| **Prensa técnica** | Preparar nota; no enviar | Enviar tras demo y resultados H1 | Comunicado de beta | Ver §6 |

## 4. Arranque en frío del mercado de dos (tres) lados

**Problema:** los desarrolladores necesitan nodos fiables; los nodos necesitan trabajo. Sin token no hay subsidio.

**Decisión:** **operadores primero, pero con carga sintética de la propia red.**

1. **Oferta primero (Fases 0–1).** Un grupo pequeño de operadores comprometidos con el *aprendizaje* (no con ingresos) permite demostrar el reparto por slots. La tentación es reclutar cientos de nodos: no. Con S=8 y ~3–5 operadores por slot, ya hay red demostrable (40 operadores en total `[SUPUESTO]`). Con ~300 nodos por slot la simulación indica que la exposición a coaliciones crece, así que no conviene crecer sin las salvaguardas (huella, comisión de registro, identidad).
2. **Demanda sintética honesta.** NEXUS ejecuta **trabajos propios** (evaluaciones, benchmarks, el simulador) y los marca como tales para que operadores vean actividad. Se etiqueta "trabajo sintético del equipo" en el libro de contribuciones; nunca se presenta como demanda de clientes.
3. **Demanda temprana por invitación.** 15–30 desarrolladores con cargas batch tolerantes a latencia; se les da créditos de testnet y atención directa. Se priorizan casos que generan trabajo repetible (evaluaciones periódicas).
4. **Autores al final.** Dos o tres pilotos que ayuden a probar el flujo de publicación; no son palanca de crecimiento hasta que exista demanda.
5. **Sin pagos reales que subsidien.** La motivación del operador en alpha es: aprender, acceso temprano, visibilidad en la comunidad, posibilidad de reconocimiento (sin promesas de pago futuro). Se comunica de forma explícita para evitar expectativas de token.
6. **Bucle de confianza:** publicar semanalmente métricas reales de la red (nodos, trabajos, fallos), incluso cuando son malas.
7. **Si el lado demanda no aparece:** no inflar; recortar a la narrativa de investigación/laboratorio (ver señales de pivote en 06).

## 5. Alianzas (candidatas; ninguna existe hoy)

Todas son **ideas a explorar**; no mencionar como socios mientras no haya acuerdo escrito.

| Tipo | Candidatos | Qué buscar | Riesgo |
|---|---|---|---|
| Universidades / laboratorios | Grupos de sistemas distribuidos y privacidad `[POR VERIFICAR nombres]` | Nodos, validación, co-autoría de medidas | Plazos académicos |
| Comunidades de modelos abiertos | Hugging Face, Ollama, llama.cpp, vLLM (integración técnica, no endorso) | Compatibilidad, canales de distribución | No presentar como socio sin acuerdo |
| Agregadores | OpenRouter como posible canal de distribución tras la beta | Exposición a desarrolladores | Requiere fiabilidad real; ver 01 H3 |
| Hosting pequeño / neoclouds | Operadores con capacidad ociosa | Nodos de calidad | Expectativas de ingresos |
| Autores de modelos abiertos | Equipos con fine-tunes | Contenido del catálogo | Licencias |
| Auditoría de seguridad | Firmas independientes `[POR VERIFICAR]` | Puerta GA | Coste |

## 6. Relaciones públicas

- **Narrativa:** "Una alpha honesta: un experimento con límites publicados." Evitar "la alternativa a OpenAI".
- **Kit de prensa:** nota (05), ficha técnica, página de estado, evidencia, fotos del equipo, glosario. Sin cifras de usuarios.
- **Portavoces:** CEO y CTO; preparar respuestas a "¿por qué otro DePIN?" y "¿hay token?" (siempre: "no hay token en v0.1").
- **Calendario:** no enviar a prensa hasta cumplir puerta de salida de alpha (demo + H1 + resultados). Antes: solo medios técnicos especializados y blogs de investigación, bajo petición.
- **Gestión de crisis:** plan para tres escenarios: (1) un incidente de seguridad, (2) crítica por marca/nombre, (3) especulación de token. Plantillas en 07.
- **Embargos y exclusivas:** solo con medios técnicos, sin comprometer contenido.
- **Medios:** lista de contactos `[POR VERIFICAR]`; no inventar contactos.

## 7. Cronograma semana a semana (semanas 1–12)

Cada semana cierra con revisión de 30 min y actualización del cuadro de mando (06). "Entregable" = definición de hecho.

| Sem | Fechas `[SUPUESTO]` | Foco | Tareas (rol) | Entregable |
|---|---|---|---|---|
| 1 | 2-nov | Fundamentos | Revisar 01–03 con el equipo (GTM, CEO). Abrir formulario de lista de espera con 3 roles (DEVREL). Encargar búsqueda de anterioridades de marca (CEO/LEGAL). Verificar rotación de credencial de `8445b54` (CTO) | Decisión de alcance; encargo de marca; formulario operativo |
| 2 | 9-nov | Landing y estado | Ajustar landing al tono 02 (landing/DEVREL); página de estado pública; primer post técnico en borrador (CTO+GTM) | Landing con lista de espera y estado |
| 3 | 16-nov | Descubrimiento | 8 entrevistas (3 operadores, 4 devs, 1 autor) (GTM, COM); abrir Discord con reglas (COM) | Notas de entrevistas; Discord abierto |
| 4 | 23-nov | Contenido 1 | Publicar post de arquitectura de slots (05) en blog + hilo X (GTM, CTO). Email 1 de la secuencia | Post publicado; primeras señales |
| 5 | 30-nov | Comunidad de GPU | Hilos de pregunta en 2–3 comunidades (COM); 8 entrevistas más; test A/B de titulares (GTM) | Hallazgos de dolores; ganador provisional de titular |
| 6 | 7-dic | Producto visible | Grabar demo de 3 min (05) con producto real (CTO, DEVREL); README de captación (DEVREL) | Demo y README publicados |
| 7 | 14-dic | Preparar alpha | Criterios y formulario de aptitud de operadores (COM); términos y aviso de testnet con LEGAL; guion de onboarding (COM, CTO) | Documentos de alpha listos |
| 8 | 21-dic | Decisión de nombre | Informe de anterioridades (LEGAL); decisión de nombre o riesgo aceptado (CEO). Email 2–3 | Decisión documentada |
| 9 | 28-dic | Pausa festiva reducida | Solo respuesta a lista y soporte; preparar Show HN y nota de prensa (GTM) | Borradores finales revisados contra 02 |
| 10 | 4-ene | **Invitaciones cohorte 1 de operadores** | Seleccionar 8–16 operadores (COM, CTO); onboarding en grupos de 4; soporte en Discord | Primeros nodos conectados |
| 11 | 11-ene | **Invitaciones cohorte 1 de devs** | 15–30 invitaciones con créditos de testnet (DEVREL); recopilar feedback; primer informe semanal de red (CTO, GTM) | Informe semanal público |
| 12 | 18-ene | Show HN / revisión | **Solo si** puerta de alpha cumplida (demo reproducible y nodos de ≥ 3 redes): Show HN, hilo X (GTM, CTO). Retrospectiva de 12 semanas, KPIs vs supuestos, decisión seguir/pivotar (CEO, GTM) | Show HN publicado o aplazado con motivo; informe de las 12 semanas |

Si una puerta no se cumple, **se desplaza el hito**, no se rebaja el criterio.

## 8. Presupuesto de atención (sin cifras de dinero)

No se estiman cifras monetarias aquí (eso corresponde a `docs/business/` y `finance/`). La carga semanal de GTM `[SUPUESTO]`: 40 % contenido, 25 % comunidad, 20 % entrevistas y análisis, 15 % relaciones y alianzas.

## 9. Riesgos del plan y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Que la demo no esté lista en semana 6 | Retrasar Show HN; seguir con contenido técnico y entrevistas |
| Atracción de público especulativo (token) | Mensajes de 02; moderación (07); filtrar en el formulario |
| Pocos operadores cualificados | Ampliar a universidades y comunidades específicas; no relajar criterios de seguridad |
| Incidente de seguridad durante alpha | Alcance reducido, red aislada, plan de comunicación (07), derecho de pausa |
| Nombre/marca bloquea lanzamiento | Plan B de nombres (01, §7); sin gasto de marca antes de decisión |
| Expectativas de pagos reales | Aviso de testnet en cada comunicación |
| Fatiga del equipo | Cadencia fija; no más de un hito público a la vez |
