# 05 · Legal y cumplimiento

> **AVISO: este documento NO es asesoría legal.** Es un mapa de riesgos elaborado por el equipo de negocio a partir de fuentes públicas
> consultadas el 2026-10-27 (muchas secundarias). Puede estar incompleto o equivocado. Cada punto marcado `[DECISIÓN ABOGADO]` requiere
> opinión escrita de un abogado cualificado en la jurisdicción pertinente antes de actuar. Hasta entonces, NEXUS es alpha en testnet, sin dinero real y sin token.

## 1. Estructura societaria (opciones, sin decidir)

| Opción | A favor | En contra |
|---|---|---|
| Sociedad limitada española (SL/SLU) | Cercana al equipo; acceso a CDTI/ENISA (ver `04`); IVA y facturación locales | Menos familiar para inversores anglosajones; conversión posterior si se levanta en EE. UU. |
| C-corp de Delaware con filial española | Estándar para rondas de VC; opciones sobre acciones sencillas | Coste legal y fiscal; doble presencia; subvenciones europeas pueden exigir entidad UE |
| Fundación / asociación (para el protocolo abierto) + empresa operadora | Separa el estándar abierto del negocio; útil si hay gobernanza comunitaria o token | Complejidad prematura; un token y una fundación aumentan el riesgo regulatorio |

Recomendación de trabajo (hipótesis): **una sola sociedad operadora (SL o equivalente), código bajo licencia abierta compatible con las subvenciones elegidas, y sin fundación ni token en 36 meses** salvo que cambie el análisis. `[DECISIÓN ABOGADO]`: forma, país, pacto de socios (vesting, cesión de IP de los fundadores a la sociedad, no competencia), régimen de empresa emergente (Ley 28/2022 de fomento del ecosistema de las empresas emergentes `[POR VERIFICAR]` vigencia y requisitos).
El repositorio ya contiene una credencial expuesta en el historial (`8445b54`): debe rotarse; un inversor la encontrará en la debida diligencia.

## 2. Licencias de modelos base

Resumen de lo que dicen las licencias respecto de **ofrecer inferencia como servicio** y de **distribuir pesos fragmentados a terceros** (los operadores). Esto es lectura de las páginas oficiales, no interpretación jurídica.

| Modelo | Licencia | Uso comercial | Servicio alojado | Distribuir pesos (incl. fragmentos) | Fuente |
|---|---|---|---|---|---|
| **Gemma (≤ Gemma 3 / 3n)** | Gemma Terms of Use + Prohibited Use Policy (Google) | Permitido con condiciones | **Ofrecerlo por API cuenta como Distribución** ("Hosted Services") y aplican las mismas condiciones | Hay que trasladar las restricciones de uso (incluida la política de usos prohibidos) a los receptores **en un acuerdo ejecutable**, entregarles copia del acuerdo y avisar de las modificaciones. Los *Model Derivatives* incluyen modelos entrenados para imitarlo (destilación, datos sintéticos de Gemma); los *outputs* no son derivados. Google puede restringir, "remotamente o de otro modo", usos que crea infractores y terminar la licencia (hay que borrar copias) | https://ai.google.dev/gemma/terms (2026-10-27) |
| **Gemma 4** | **Apache 2.0** (cambio anunciado el 2-abr-2026) | Permitido sin la política de uso de Google | Sin condiciones especiales aparte de Apache 2.0 | Redistribución con aviso de licencia y de cambios | https://www.theregister.com/2026/04/02/googles_gemma_4_open_weights/ , https://www.implicator.ai/google-releases-gemma-4-under-apache-2-0-dropping-its-custom-ai-license/ (secundarias; confirmar en la ficha oficial del checkpoint) |
| **Llama 3.3** (y familia 3.x) | Llama Community License + Acceptable Use Policy (Meta) | Permitido; con más de 700 M de usuarios activos mensuales de la empresa o afiliadas hay que pedir licencia a Meta | Permitido | Hay que incluir copia de la licencia, mostrar **"Built with Llama"**, conservar el aviso, cumplir la AUP; **un modelo entrenado/afinado con materiales o salidas de Llama y distribuido debe llevar "Llama" al principio del nombre**; el licenciatario indemniza a Meta ante reclamaciones por su uso/distribución; si se demanda a Meta por PI, la licencia termina | https://dev.meta.ai/llama/llama3_3/license (2026-10-27) |
| Otros (Qwen, Mistral, etc.) | Varía por checkpoint (Apache 2.0 en muchos, licencias propias en otros) | `[POR VERIFICAR]` | `[POR VERIFICAR]` | `[POR VERIFICAR]` | Comprobar la ficha oficial de cada checkpoint antes de añadirlo al catálogo |

**Consecuencias para NEXUS**
1. **Catálogo condicionado por licencia**: cada modelo del catálogo lleva su licencia y versión; el manifiesto (`license` en `ModelManifest`) debe guardarla y la CLI de publicación rechazar modelos sin licencia declarada.
2. **Los operadores son receptores de distribución**. En Gemma ≤ 3 y Llama hay que entregarles el texto de la licencia y que acepten condiciones; los fragmentos cifrados de reposo y el slot en claro en memoria son ambos "materiales". `[DECISIÓN ABOGADO]`: si un fragmento cifrado/erasure-coded sin clave cuenta como distribución de los materiales (cautela: sí) y cómo se hace ejecutable el traslado de restricciones (contrato de operador).
3. **Gemma ≤ 3: Google puede restringir remotamente usos.** Hay que poder retirar un modelo del catálogo y revocar claves (el `KeyVault.revoke` existe). La opción de menor riesgo hoy es preferir modelos Apache 2.0 (Gemma 4) para el catálogo por defecto.
4. **Qué Gemma usa Atenhea hoy**: el repositorio habla de `athenea-e2b` y "Gemma E2B"; no se pudo verificar si es Gemma 3n E2B (ToU de Gemma) o Gemma 4 E2B (Apache 2.0) `[POR VERIFICAR]`. El régimen legal cambia según el caso.
5. **Nombre del producto**: si se publica un modelo afinado a partir de Llama, su nombre debe empezar por "Llama" (restricción de la licencia, también para adaptadores distribuidos como modelo).
6. **Destilación**: quien consulta puede destilar el modelo desde las salidas; en Gemma ≤ 3 un modelo entrenado con datos sintéticos de Gemma es *Model Derivative*, y versiones antiguas de Llama prohibían usar salidas para mejorar modelos de terceros. Las ToS de NEXUS deben trasladar estas restricciones a clientes cuando proceda.
7. **Autores de modelos**: deben declarar la licencia del modelo base y garantizar que su adaptador/modelo puede redistribuirse con regalías.

## 3. Pagos a operadores: KYC/AML, facturación, impuestos

Riesgo principal: **NEXUS recibe dinero de clientes y paga a terceros (operadores y autores)**. Eso puede ser un servicio de pago o de dinero electrónico según la estructura.
`[DECISIÓN ABOGADO]` en todo lo siguiente:
- **Estructura**: ¿NEXUS actúa como comisionista/agente (cobra un precio y reparte) o como revendedor (compra capacidad a operadores y revende)? La respuesta cambia IVA, responsabilidad frente al cliente y la necesidad de autorización de pago. Posibles vías: usar un proveedor de pagos con funciones de marketplace/*split payments* (el proveedor lleva KYC y licencia), en lugar de custodiar fondos directamente. `[POR VERIFICAR]` proveedor y comisiones; en el modelo se asume 3 % de coste de cobro.
- **Liquidación en stablecoin**: el escrow (`InferenceEscrow.sol`, testnet) mueve un token ERC-20. Con una stablecoin regulada (p. ej. un *e-money token* bajo MiCA, Reglamento (UE) 2023/1114, https://eur-lex.europa.eu/eli/reg/2023/1114/oj) hay que revisar quién puede emitirla, custodiarla o transferirla en nombre de terceros y qué licencias exige. Para el cliente se recomienda cobrar en fiat y que la conversión sea interna o con un proveedor autorizado, no pedir al cliente cripto.
- **KYC/AML de operadores**: para pagar a una persona hay que identificarla (verificación de identidad y de titular de cuenta); umbrales de pago, sanciones, listas de personas; los operadores en terceros países complican. El modelo asume 8 USD por verificación `[POR VERIFICAR]`.
- **Obligaciones tributarias de plataforma**: la Directiva (UE) 2021/514 (DAC7) obliga a plataformas digitales a comunicar ingresos de vendedores en determinados casos `[POR VERIFICAR]` aplicabilidad. Los operadores aficionados pueden tener obligaciones fiscales propias; hay que no dar la impresión de que los ingresos están "libres de impuestos".
- **Facturación**: NEXUS debe emitir facturas a clientes (IVA, OSS en ventas B2C a la UE, inversión del sujeto pasivo en B2B) y, según el esquema, autofacturas o documentación para los operadores. Normativa española de facturación electrónica y Verifactu `[POR VERIFICAR]` calendario.
- **Disputas y reembolsos**: el escrow tiene ventana de disputa de 7 días y árbitro = owner en testnet; legalmente el árbitro debe ser un procedimiento definido en los términos de servicio, no una dirección.
- **Crédito de arranque a operadores**: debe formularse como pago por trabajo verificado, no como retribución garantizada ni rendimiento; si resulta un rendimiento vinculado a la inversión de hardware puede aparecer riesgo de valores `[DECISIÓN ABOGADO]`.

## 4. ¿Un token sería un valor?

- **Hoy no hay token y el brief lo mantiene así.** Cualquier estudio de un token es una opción futura y no se describe ni vende.
- **UE**: MiCA clasifica los cripto-activos en tokens referenciados a activos, tokens de dinero electrónico y "otros" (incluidos los de utilidad), y su régimen aplica aunque la etiqueta sea "utility". Si el token cumple definición de instrumento financiero, entra MiFID II. `[DECISIÓN ABOGADO]` Art. 2 y test de la ESMA.
- **EE. UU.**: el test de Howey (inversión de dinero, empresa común, expectativa de beneficio, esfuerzo de terceros) y la declaración del personal de la SEC del 10-abr-2025 señalan que si los compradores esperan beneficios del esfuerzo de un equipo central es probable que sea valor (https://cointelegraph.com/explained/secs-2025-guidance-what-tokens-are-and-arent-securities/, secundaria; algunas fuentes mencionan marcos de 2026 no confirmados `[POR VERIFICAR]`). Prohibido en la comunicación: "ganar", "rendimiento", "stake" como inversión, "quema" como revalorización.
- **Señales de alarma en el diseño actual**: `BURN_BPS`, `treasury`, "stake" en el simulador y el lenguaje de rendimiento a operadores; todo lo que se parezca a "compra el token y gana por el trabajo de otros".
- **Recomendación de negocio**: sin token ni venta de token durante el horizonte del modelo; si se estudia, hacerlo después de H1 con trabajo legal específico y probablemente fuera de EE. UU.

## 5. RGPD y datos de prompts

- **Los prompts contienen datos personales con frecuencia** (el cliente decide). NEXUS procesa prompts y respuestas: los recibos guardan hash/metadatos; H0 borra prompts y respuestas tras 30 días por defecto (`EXECUTIVE_BRIEF.md`), pero los snapshots externos, logs y memoria/caché de Atenhea quedan sin cubrir.
- **Roles (RGPD)**: lo probable es que el cliente sea responsable, NEXUS encargado, y cada operador **subencargado** que ve el slot en claro y las activaciones. Hace falta un acuerdo de encargado del tratamiento (art. 28) con clientes y un contrato equivalente con operadores, incluidos los de fuera del EEE (cláusulas contractuales tipo). `[DECISIÓN ABOGADO]` si el operador que solo ve una activación parcial trata datos personales (la primera etapa ve embeddings; el diseño técnico no excluye reconstrucción del texto; no afirmar anonimato).
- **EDPB Opinion 28/2024** (17-dic-2024) sobre modelos de IA: el anonimato de un modelo se evalúa caso por caso y la ilicitud del tratamiento inicial puede afectar al despliegue (https://www.iapp.org/news/a/edpb-weighs-in-on-key-questions-on-personal-data-in-ai-models). Sobre la AEPD y los prompts no se encontró criterio específico `[POR VERIFICAR]`.
- **Medidas**: minimización (ventana de borrado por defecto, opción de cero retención), no entrenar con prompts de clientes, no conservar texto en el ledger, cifrado en tránsito, registro de actividades de tratamiento, DPIA para enclaves y salud/legal, política de brechas (72 h), procedimiento de ejercicio de derechos (acceso/borrado con operadores en cadena).
- **Mensaje a clientes**: "ningún operador tiene el modelo completo" no equivale a privacidad del prompt; un nodo de cómputo ve datos de su slot.

## 6. Términos de servicio y política de uso aceptable

Contenido mínimo (a redactar por abogado): estado alpha/beta sin garantías; sin SLA hasta GA; uso aceptable (heredando la AUP de Meta y, mientras se use, la política de usos prohibidos de Gemma); prohibición de uso ilegal; límites y suspensión; cesión de licencias de modelos; recibos firmados como prueba técnica (no de resultado); responsabilidad limitada; ley y foro; modificaciones con preaviso; cláusula de operadores (no extraer ni redistribuir fragmentos, borrado al salir, seguridad del host, aceptación de verificación); cláusula de autores (garantías de titularidad y de licencia del modelo base); procedimiento de disputa y reembolso.
Operadores: no se promete ingreso; se paga por trabajo verificado.

## 7. Responsabilidad por contenido generado

- **El cliente es el principal responsable de lo que pide y publica**; NEXUS y los operadores no deben ser "editores" de contenido. Necesita AUP, retirada de contenido ilegal y colaboración con autoridades `[DECISIÓN ABOGADO]` (cabe encaje como servicio de alojamiento/intermediación bajo el Reglamento (UE) 2022/2065 DSA `[POR VERIFICAR]`).
- **Reglamento (UE) 2024/1689 (AI Act)**: roles de proveedor, desplegador y proveedor de modelos de IA de propósito general; las obligaciones dependen de qué modelos se pongan en el mercado y si NEXUS los modifica. `[POR VERIFICAR]` y `[DECISIÓN ABOGADO]`. Un operador con un fragmento no es proveedor del modelo, pero NEXUS puede serlo en algunos casos.
- **Seguro**: responsabilidad civil profesional/ciber `[POR VERIFICAR]` coste.
- **Contenido ilícito servido por nodos distribuidos**: dificultad de retirada una vez generado; los recibos solo guardan hash. Definir qué logs existen y durante cuánto.

## 8. Propiedad intelectual de adaptadores y modelos de terceros

- **Adaptadores `.nram`**: son obra derivada de un modelo base; la licencia del base condiciona su distribución (nombre "Llama", AUP, avisos). El autor debe **garantizar** titularidad del adaptador y de sus datos de entrenamiento; NEXUS no verifica derechos y debe tener procedimiento de retirada por reclamación (notice-and-takedown).
- **Regalías**: `royalty_bps` en el manifiesto y 10 % en el escrow; el contrato de autor debe fijar cesión de licencia limitada a NEXUS (distribuir a operadores y ejecutar), pago, auditoría, terminación y qué ocurre con los fragmentos ya distribuidos.
- **Código de NEXUS**: licencia abierta compatible con subvenciones (MIT/Apache probable) y registro de marca; el nombre NEXUS puede chocar con marcas existentes y **no está despejado** (GTM lo investiga) `[POR VERIFICAR]`.
- **Datos de entrenamiento y outputs**: los outputs del modelo pueden no ser protegibles y su titularidad es discutida `[DECISIÓN ABOGADO]`; las ToS no deben prometerla.
- **Código criptográfico propio**: el repositorio marca algunas piezas en Python puro como "NOT AUDITED"; debe sustituirse por librerías auditadas antes de pagos reales (también por responsabilidad).

## 9. Lista de decisiones que requieren abogado
1. Forma y jurisdicción de la sociedad; pacto de socios; cesión de IP de los fundadores.
2. Licencia del código abierto de NEXUS y política de contribuciones.
3. Modelo de pagos (agente vs reventa), proveedor de pagos/KYC, si se necesita licencia y de qué tipo; liquidación en stablecoin sí/no.
4. IVA/OSS, facturación, DAC7, retenciones a operadores no residentes.
5. Contrato de operador (receptor de distribución de materiales con licencia, subencargado RGPD, seguridad, retirada).
6. Contrato de autor y política de PI, retirada y reclamaciones.
7. Licencias de cada modelo del catálogo (Gemma 3/3n vs Gemma 4, Llama, otros), incluida la distribución de fragmentos cifrados.
8. Clasificación de cualquier token futuro (MiCA, Howey) y de cualquier "crédito de arranque" o programa de incentivos.
9. RGPD: roles, DPA, transferencias internacionales, DPIA, política de retención, medidas para evitar ilusión de anonimato.
10. AI Act y DSA: papel de NEXUS y obligaciones asociadas.
11. Marca NEXUS y dominio definitivo (hoy `nexus.example` es un marcador).
12. Seguro y limitación de responsabilidad.
13. Publicación de cualquier cifra de rendimiento, de "ingresos de operadores" o de usuarios: revisión previa (publicidad engañosa).
