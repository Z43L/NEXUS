# Atenhea

**Inferencia local del Gemma 4 E2B con pesos originales, adaptadores `.nram`, memoria episódica CHL y microexpertos entrenables.**

Atenhea reúne un servidor de inferencia, una memoria persistente y herramientas de entrenamiento supervisado. Su comando principal es `atenhea`. El código conserva nombres históricos como `onram.py`, `onram_cli.py` y los archivos `athenea-*`; todos pertenecen al mismo proyecto.

El backend nativo carga los pesos Safetensors del E2B y les aplica los adaptadores y las microextensiones del proyecto. Sirve respuestas en streaming a Pi Agent, Claude Code, Codex CLI y clientes HTTP. **Esta ruta no convierte el modelo a GGUF ni utiliza llama.cpp.**

El repositorio contiene código y documentación. Los pesos, recuerdos, perfiles locales, resultados de entrenamiento y registros se generan o descargan durante la instalación y quedan fuera de Git.

## Índice

- [Capacidades actuales](#capacidades-actuales)
- [Cómo funciona](#cómo-funciona)
- [Requisitos](#requisitos)
- [Instalación](#instalación)
- [Arranque y uso diario](#arranque-y-uso-diario)
- [Pi, Claude Code y Codex CLI](#pi-claude-code-y-codex-cli)
- [API y streaming](#api-y-streaming)
- [Memoria episódica y mapa de hechos](#memoria-episódica-y-mapa-de-hechos)
- [Entrenamiento y evolución](#entrenamiento-y-evolución)
- [Diagnóstico](#diagnóstico)
- [Pruebas](#pruebas)
- [Organización del proyecto](#organización-del-proyecto)

## Capacidades actuales

| Área | Implementación actual | Límite importante |
| --- | --- | --- |
| Inferencia | Checkpoint E2B original en BF16, adaptadores LoRA y microextensiones externas | El modelo base sigue siendo necesario para cada generación. |
| Servidor persistente | Un motor residente y un hilo de inferencia compartido entre sesiones | Las peticiones de generación se atienden en serie. |
| Prefijo reutilizable | Caché KV exacta del prefijo común de instrucciones y herramientas | Una entrada, hasta 2.048 tokens y 32 MiB retenidos; puede fallar la coincidencia al cambiar el contexto. |
| Memoria en Metal | Tabla de embeddings por capa en CPU; cómputo denso en MPS | Sigue requiriendo el checkpoint completo en disco; no cuantiza los pesos. |
| Streaming | Texto incremental mediante SSE en Chat Completions, Responses y Messages | Los argumentos de herramientas se emiten después de completar su análisis. |
| Contexto | Hasta 131.072 tokens declarados por el E2B, compartidos entre entrada y salida | La memoria disponible y el coste de procesar el prompt limitan el uso práctico. |
| Memoria episódica | Recuperación y persistencia CHL en `models/athenea.memory` | Un recuerdo generado por el asistente puede ser incorrecto. |
| Conocimiento explícito | Hechos, eventos, negaciones, fuentes y conflictos en SQLite | No se ha extraído un mapa semántico completo de los pesos. |
| Microexpertos | MLP residuales externos con enrutamiento por activaciones | Son extensiones del E2B, no modelos de lenguaje independientes. |
| Entrenamiento en ejecución | Candidato separado, validación y promoción de una microextensión | Chat autorizado por petición explícita; validación separada; pausa la generación mientras se ejecuta. |
| Evolución LoRA | Rondas acotadas sobre candidatos con evaluación separada | No demuestra auto-mejora general ni promueve automáticamente el candidato al servidor. |
| Explicación visible | Una frase de enfoque seguida de la respuesta, transmitida como texto | Es una explicación pública breve; no es una traza de pensamiento interno. |
| Agentes | Lanzadores para Pi, Claude Code y Codex CLI | Los clientes se instalan por separado; la calidad del uso de herramientas depende del modelo. |

La ruta nativa implementada acepta **texto y herramientas**. No ofrece entrada de imágenes, audio o vídeo, aunque el checkpoint de origen incluya componentes multimodales.

## Cómo funciona

```text
Pi / Claude Code / Codex CLI / cliente HTTP
                    │
                    ▼
          Atenhea — 127.0.0.1:11434
            │ recupera contexto CHL
            │ añade hechos relevantes
            ▼
        Motor nativo — 127.0.0.1:11436
            │
            ├── pesos originales Safetensors del E2B
            ├── adaptadores de athenea-e2b.nram
            └── microexpertos de athenea-e2b.extensions.nram
                    │
                    ▼
          respuesta incremental en SSE
                    │
                    ▼
       episodio CHL si la respuesta terminó
```

El archivo `.nram` principal contiene un manifiesto, tensores de adaptadores, referencias al checkpoint, metadatos y una instantánea documental de código seleccionado. **No contiene todos los pesos base del E2B y no es un ejecutable autónomo.** El checkpoint debe seguir disponible en su ruta local.

La instantánea de código sirve como documentación para preparar análisis y entrenamiento. El sistema no ejecuta código extraído de ese documento.

Cada agente reutiliza el servidor y los pesos ya cargados. Abrir otra sesión de Pi no crea otro modelo. El lanzador verifica el backend, el alias y el `.nram`; el arranque se serializa y el servidor reserva su puerto antes de cargar el checkpoint.

## Requisitos

La ruta principal se ha probado en **macOS con Apple Silicon, Python 3.12 y PyTorch MPS**.

Necesitas:

- Git y acceso a Internet para la descarga inicial.
- Python 3.12 con `venv` y `pip`.
- Node.js accesible como `node`, o una ruta explícita en `ONRAM_NODE`, para CHL.
- Un compilador C para construir el lanzador `build/atenhea`. En macOS puede utilizarse el de Command Line Tools.
- Espacio para un checkpoint de aproximadamente 10 GB, dependencias, cachés y candidatos. Deja margen adicional; el entrenamiento puede crear archivos grandes.
- Memoria suficiente para los pesos y las activaciones. Un equipo de 16 GB puede sufrir presión de memoria e intercambio a disco, especialmente con prompts largos.

El motor selecciona MPS cuando está disponible y CPU en caso contrario. La selección automática no elige CUDA. Linux/CPU y otras configuraciones no tienen la misma validación práctica que la ruta macOS/MPS. Windows no está soportado directamente por los componentes que utilizan `fcntl` y operaciones POSIX.

## Instalación

Ejecuta los pasos desde una carpeta donde quieras conservar el proyecto y sus modelos.

### 1. Clonar y preparar Python

```sh
git clone https://github.com/Z43L/4T3NH34.git
cd 4T3NH34

python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

El lanzador utiliza primero `ONRAM_PYTHON`, si está definido, y después el Python de `.venv`. Para fijarlo explícitamente:

```sh
export ONRAM_PYTHON="$PWD/.venv/bin/python"
```

### 2. Instalar CHL

```sh
mkdir -p third_party
git clone https://github.com/Z43L/CHL-episodic-agent-memory.git third_party/chl
git -C third_party/chl checkout 3d5d7700384b55c2c29c84d8a7becb91eaf210ef
node --version
```

El puente utiliza `NativeCHL` directamente. Para esta integración no hace falta arrancar un segundo servidor CHL.

Si Node.js no está en el PATH, indica su ejecutable:

```sh
export ONRAM_NODE=/ruta/a/node
```

La aceleración nativa de CHL es opcional:

```sh
node third_party/chl/scripts/build-native.js
```

Si el complemento nativo no está disponible, CHL puede utilizar su implementación JavaScript. Comprueba el puente antes de descargar el modelo:

```sh
.venv/bin/python episodic_memory.py recall 'comprobación de instalación'
```

El resultado informa del motor utilizado y puede devolver una lista vacía de recuerdos en una instalación nueva.

### 3. Construir el comando Atenhea

```sh
./build_onram.sh
./atenhea --help
./build/atenhea --version
```

Se genera `build/atenhea`. Los nombres anteriores `onram` y `build/onram-cli` se mantienen como entradas de compatibilidad.

Para instalar el comando en tu PATH:

```sh
mkdir -p "$HOME/.local/bin"
ln -sfn "$PWD/build/atenhea" "$HOME/.local/bin/atenhea"
export PATH="$HOME/.local/bin:$PATH"
```

Añade esta línea al archivo de configuración de tu shell, por ejemplo `~/.zshrc`, para conservarla en nuevas terminales:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

Comprueba la instalación:

```sh
command -v atenhea
atenhea --version
```

Conserva el directorio del proyecto: el binario localiza los módulos Python junto al checkout. Si lo mueves, actualiza el enlace y las rutas de tus perfiles.

### 4. Descargar el E2B y crear el `.nram`

```sh
./atenhea e2b-trainable-setup
```

Este comando descarga `google/gemma-4-E2B-it` en `models/gemma4-e2b-trainable`, fija la revisión en los metadatos locales, reanuda los rangos pendientes y verifica los pesos con los hashes publicados. Después crea `models/athenea-e2b.nram` con adaptadores inicializados a cero mediante conversión de bajo consumo de memoria.

Una segunda ejecución conserva un `.nram` existente. **No crea por sí sola los microexpertos ni el perfil de arranque del siguiente paso.**

Si la descarga devuelve `401` o `403`, comprueba el acceso y las condiciones del checkpoint en Hugging Face. El descargador incluido usa HTTP directo; no añade automáticamente un token de Hugging Face a sus solicitudes.

### 5. Crear las microextensiones

Solo en una instalación nueva:

```sh
./atenhea micro create \
  --bundle models/athenea-e2b.nram \
  --output models/athenea-e2b.extensions.nram \
  --experts 3 --rank 8 --layer 34
```

La operación enlaza la extensión desde el manifiesto del `.nram` principal. Si el archivo de extensión ya existe, el comando se niega a sobrescribirlo para preservar sus pesos entrenados.

En el E2B con dimensión oculta 1.536, esta configuración crea tres expertos de 24.576 parámetros cada uno y un enrutador de 4.608 parámetros. Entrenar un experto y el enrutador modifica **29.184 parámetros**. Sus salidas residuales iniciales son cero: una instalación nueva todavía no contiene expertos entrenados.

### 6. Crear el perfil nativo predeterminado

Los perfiles están bajo `models/` y no se distribuyen en Git. Crea uno con rutas absolutas de tu propia instalación:

```sh
.venv/bin/python - <<'PY'
import json
from pathlib import Path

root = Path.cwd().resolve()
profile = {
    "name": "athenea-e2b:latest",
    "backend": "nram",
    "context_size": 131072,
    "args": [
        "--backend", "nram",
        "--model", str(root / "models/gemma4-e2b-trainable"),
        "--bundle", str(root / "models/athenea-e2b.nram"),
        "--model-name", "athenea-e2b",
        "--ctx-size", "131072",
        "--chl-memory", str(root / "models/athenea.memory"),
        "--no-auto-learn",
        "--no-inference-debug",
    ],
}
(root / "models/onram-launch.json").write_text(
    json.dumps(profile, indent=2) + "\n", encoding="utf-8"
)
PY

./atenhea reasoning on
```

Este perfil mantiene la memoria CHL activa y desactiva el antiguo entrenamiento automático del backend GGUF. El entrenamiento de microexpertos se solicita por separado mediante la API nativa.

### 7. Comprobar y arrancar

```sh
./atenhea serve
```

En otra terminal:

```sh
curl http://127.0.0.1:11434/api/runtime/status
```

Comprueba que aparecen `loaded: true`, `backend: "nram"`, el `.nram` esperado y `device: "mps"` si tu equipo utiliza Metal. Una instalación nueva suele mostrar `micro_version: 0`; la versión aumenta al aceptar entrenamiento.

## Arranque y uso diario

Con el perfil instalado, cualquiera de estas entradas inicia la ruta nativa:

```sh
atenhea
atenhea serve
./start-athenea.sh
```

El servidor se ejecuta en primer plano. Puedes dejarlo abierto en una terminal y abrir los agentes en otras. Para detenerlo, utiliza `Ctrl+C` en la terminal del servidor.

Si lanzas un agente con `atenhea launch` y el servidor local predeterminado está apagado, el lanzador intenta arrancarlo en segundo plano con el perfil guardado. El registro queda en `onram-server.log`; el del motor, en `onram-backend.log`.

Cerrar un agente no apaga el servidor compartido. Los pesos se vuelven a cargar cuando se reinicia ese servidor o se cambia de modelo, no al abrir cada sesión de Pi.

En la ruta Metal, la tabla de embeddings por capa del E2B (aproximadamente 4,7 GB en BF16) permanece en CPU. Solo se transfieren a MPS las filas consultadas; el cómputo denso sigue en GPU. Ver `parameter_devices: ["cpu", "mps"]` es normal en esta configuración y no significa que haya dos modelos.

El motor retiene una caché KV del prefijo anterior al texto del último usuario. Si los tokens iniciales coinciden exactamente y la versión de pesos sigue vigente, reutiliza una copia de esa caché y procesa el resto del prompt. No recorta ni rebobina una caché deslizante ya consumida. La instantánea se limita a una entrada, 2.048 tokens y 32 MiB; la respuesta actual se genera sobre una copia y no modifica la instantánea retenida. Una promoción de microexpertos invalida la instantánea.


El máximo de 131.072 tokens se comparte entre prompt y salida. Por defecto, el motor permite utilizar el espacio restante. Los límites enviados por el cliente también cuentan: `max_output_tokens`, `max_completion_tokens` o `max_tokens`. Alcanzar un límite no obliga al modelo a terminar una frase.

### Explicación breve durante la inferencia

```sh
atenhea reasoning on
atenhea reasoning off
atenhea reasoning status
```

Con el modo activado, las preguntas explicativas reciben una instrucción para empezar con una frase `Enfoque:` y continuar con `Respuesta:`. Ambos forman parte del texto visible y se transmiten en streaming. Se indica al modelo que omita el preámbulo en respuestas literales, formatos estrictos y llamadas de herramientas; el cumplimiento depende del modelo.

La preferencia se guarda en `models/athenea-inference.json` y se consulta en cada petición. Cambiarla no recarga los pesos ni añade una segunda generación. Puede anularse por petición con `show_reasoning_summary: false` o `reasoning: {"summary": null}`.

## Pi, Claude Code y Codex CLI

Instala cada cliente por separado y comprueba que su ejecutable esté en el PATH:

```sh
command -v pi
command -v claude
command -v codex
```

Después utiliza los lanzadores de Atenhea:

```sh
atenhea launch pi
atenhea launch claude
atenhea launch codex
```

| Cliente | Conexión configurada por el lanzador |
| --- | --- |
| Pi Agent | Proveedor `onram`, alias `athenea-e2b:latest`, API Chat Completions. |
| Claude Code | `ANTHROPIC_BASE_URL` local y modelo E2B mediante Anthropic Messages. |
| Codex CLI | Proveedor local `onram`, API Responses y catálogo propio del E2B. |

Los tres comparten el motor, las microextensiones activas y la memoria CHL. El lanzador rechaza un servidor local cuyo backend, alias o `.nram` no coincidan con el perfil nativo.

Para pasar opciones al cliente, sepáralas con `--`:

```sh
atenhea launch pi -- --print 'Explica brevemente qué hace este proyecto.'
atenhea launch claude -- --print 'Responde únicamente: listo'
atenhea launch codex -- exec --skip-git-repo-check --ephemeral \
  --sandbox read-only 'Responde únicamente: listo. No uses herramientas.'
```

El cliente de Claude debe estar instalado para probar su ejecución real. La compatibilidad del endpoint Messages no sustituye esa instalación.

### Configuración particular de Codex

El lanzador nativo utiliza `models/atenhea-agents/codex` como `CODEX_HOME` y el catálogo `docs/atenhea-codex-models.json`. Así evita heredar el volumen de herramientas y ajustes de una configuración cloud que podría superar el contexto del E2B.

Este perfil desactiva la búsqueda web alojada del proveedor, que el motor local no implementa. Conserva las herramientas de código estándar. Las opciones se documentan en la [referencia de configuración de Codex](https://learn.chatgpt.com/docs/config-file/config-reference).

### Abrir Pi directamente con este modelo

`atenhea launch pi` configura el proveedor y lo selecciona explícitamente. Abrir `pi`, `claude` o `codex` directamente utiliza la configuración propia de cada programa y no garantiza que el servidor se arranque automáticamente.

Si quieres seleccionar Atenhea por defecto al abrir Pi directamente, añade estas claves a `~/.pi/agent/settings.json`, conservando sus demás ajustes:

```json
{
  "defaultProvider": "onram",
  "defaultModel": "athenea-e2b:latest"
}
```

Primero ejecuta `atenhea launch pi` para crear el proveedor y deja el servidor disponible. El uso recomendado para gestionar tanto el modelo como el arranque sigue siendo `atenhea launch pi`.

## API y streaming

El proxy público escucha por defecto en `http://127.0.0.1:11434`. El puerto `11436` es del motor interno; utiliza el público para conservar la recuperación y captura CHL.

### Generación en streaming

```sh
curl -N http://127.0.0.1:11434/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "athenea-e2b:latest",
    "messages": [{"role": "user", "content": "Explica qué es la memoria episódica."}],
    "stream": true,
    "max_tokens": 512,
    "temperature": 0.2
  }'
```

`curl -N` evita el almacenamiento intermedio del cliente. Para recibir un único JSON al terminar, utiliza `"stream": false`.

### Endpoints principales

| Método y ruta | Función |
| --- | --- |
| `GET /v1/models` | Alias del modelo servido. |
| `POST /v1/chat/completions` | Conversación y herramientas con formato Chat Completions. |
| `POST /v1/responses` | Formato Responses, historial por `previous_response_id` y herramientas. |
| `POST /v1/messages` | Formato Anthropic Messages. |
| `POST /v1/messages/count_tokens` | Recuento con la plantilla del modelo. |
| `POST /api/chat`, `POST /api/generate` | Adaptación de peticiones con formato Ollama. |
| `GET /api/runtime/status` | PID, carga, actividad, contexto, versión y última inferencia o entrenamiento. |
| `GET /api/health` | Estado del proxy, aprendizaje y memoria. |
| `GET /api/ps`, `GET /api/tags` | Modelo activo y formato nativo. |
| `POST /api/train` | Entrenamiento supervisado de una microextensión. |
| `POST /api/micro-training/train-topic` | Entrenamiento temático con el chat enviado y recuerdos CHL verificados. |
| `GET /api/micro-training/status` | Cadencia y resultado de la última ronda automática. |
| `GET /api/evolve/status` | Estado del flujo de evolución heredado; no es el estado completo de microentrenamiento. |

Las respuestas SSE usan identificadores estables, eventos de finalización y comentarios de mantenimiento de conexión. Cancelar una generación libera el motor cuando termina el paso en curso. Una operación de GPU atascada puede requerir recuperar el servidor.

El historial de Responses mantenido por el motor es limitado y está en memoria. Un reinicio lo pierde; CHL es un almacenamiento separado y no sustituye un identificador `previous_response_id` desconocido.

El servidor se limita a loopback por defecto. Si configuras `--api-key`, los clientes deben enviar esa credencial; el lanzador la toma de `ONRAM_API_KEY`. No se necesita una clave de OpenAI para ejecutar el E2B local.

## Memoria episódica y mapa de hechos

### Memoria CHL

La ruta predeterminada es `models/athenea.memory`, resuelta desde el proyecto. El puente recupera hasta cuatro episodios y utiliza un presupuesto de contexto de aproximadamente 4.000 caracteres, compartido con hechos relevantes del mapa explícito. Este presupuesto no equivale a tokens ni garantiza que una conversación completa quepa en el contexto.

Los turnos de texto completados se guardan como episodios **no verificados**, incluso con el antiguo aprendizaje automático desactivado. Las llamadas de herramientas, errores y respuestas parciales no se convierten en pares de entrenamiento por esta captura.

Consulta recuerdos o incorpora una respuesta que hayas revisado:

```sh
.venv/bin/python episodic_memory.py recall 'ruta de almacenamiento'

.venv/bin/python episodic_memory.py remember \
  '¿Qué comando inicia el servidor local?' 'atenhea serve' --verified

.venv/bin/python episodic_memory.py export \
  --output models/chl-reviewed.jsonl
```

La exportación de entrenamiento incluye solo episodios marcados explícitamente como verificados, deduplicados y con metadatos de procedencia. Un recuerdo recuperable no se convierte automáticamente en verdad ni en un ajuste de pesos.

Los errores CHL durante recuperación aparecen en el registro y en el estado de memoria del proxy. La inicialización del servidor requiere un checkout CHL válido y Node.js disponible.

### Hechos, eventos y negaciones

`world_memory.py` mantiene una base SQLite en `models/athenea.world.sqlite` con sujeto, relación, objeto, polaridad, fuente, fecha opcional y estado de verificación. Señala conflictos y permite retirar registros. Los hechos verificados relevantes pueden añadirse al contexto; la exportación de entrenamiento omite grupos con contradicciones pendientes.

```sh
atenhea world-memory init

atenhea world-memory add \
  --subject Atenhea --relation backend --object nram \
  --source 'perfil local revisado' --verified

atenhea world-memory recall Atenhea
atenhea world-memory export --output models/world-reviewed.jsonl
```

Utiliza `atenhea world-memory add --help` para registrar eventos, fechas o polaridad negativa. El mapa es explícito: no identifica automáticamente dónde está cada hecho dentro de los pesos del E2B.

Los archivos de memoria contienen información de las conversaciones. Conserva las copias de seguridad fuera de repositorios públicos y utiliza archivos separados si necesitas aislar usuarios o proyectos.

## Entrenamiento y evolución

Hay tres operaciones distintas:

1. **Recordar:** recuperar episodios o hechos para mejorar el contexto de la petición actual.
2. **Entrenar microexpertos:** ajustar una extensión pequeña sobre activaciones del E2B congelado.
3. **Entrenar LoRA:** crear y evaluar candidatos de adaptadores sobre el modelo base.

Conversar, guardar un episodio o abrir Pi no dispara una ronda con cada petición. El runtime nativo ofrece una herramienta interna `atenhea_train_microexpert` en Pi Agent, Claude Code y Codex CLI. Cuando el usuario pide entrenar sobre un tema concreto, el modelo puede solicitar esa operación durante la inferencia. Combina pares completos del chat actual con recuerdos CHL pertinentes verificados. La autorización explícita permite usar el chat como material de esa ronda, pero no certifica que las respuestas del asistente sean hechos correctos. Por ejemplo: «Entrena un microexperto sobre redes eléctricas usando este chat y la memoria CHL».

Además, el runtime inicia una revisión automática **cada 24 horas**. La ronda general requiere al menos nueve preguntas distintas en CHL, incluidas cinco con recuerdos verificados. Puede usar pares completos de chat no verificados como datos de entrenamiento; la validación y el control de regresión salen exclusivamente de recuerdos verificados. Si faltan datos, registra el motivo y vuelve a comprobarlo en el siguiente intervalo. La ronda selecciona el siguiente experto y aplica la misma validación y control antes de promoverlo.

Configura el intervalo en `models/athenea-micro-training.json`:

```json
{
  "enabled": true,
  "interval_hours": 24
}
```

`interval_hours` admite de 1 a 720 horas. `{"enabled": false}` desactiva las rondas automáticas, pero mantiene disponibles las solicitudes desde el agente. Reinicia el runtime después de cambiar este archivo. Consulta `GET /api/micro-training/status` o `micro_training_schedule` en `/api/runtime/status`. `base_weights_frozen: true` significa que los pesos base no reciben gradientes; no significa que la inferencia esté detenida.

Las microextensiones no convierten el E2B completo en un modelo MoE disperso: reducen los parámetros que se entrenan, pero no eliminan el cálculo del modelo base. En Metal se calculan residuos enmascarados de tamaño fijo para evitar sincronizaciones problemáticas.

### Microentrenamiento con el servidor cargado

Prepara un archivo JSON con tres conjuntos independientes, revisados y adecuados para el objetivo. Este ejemplo muestra el formato; no es un benchmark ni un conjunto suficiente para afirmar una mejora general:

```json
{
  "train": [
    {
      "prompt": "¿Qué comando inicia el servidor de Atenhea?",
      "completion": "atenhea serve",
      "verified": true
    }
  ],
  "validation": [
    {
      "prompt": "¿En qué formato están los pesos base de la ruta nativa?",
      "completion": "Safetensors.",
      "verified": true
    }
  ],
  "guardrail": [
    {
      "prompt": "¿Cuánto es dos más dos?",
      "completion": "4.",
      "verified": true
    }
  ],
  "expert": 0,
  "epochs": 2,
  "max_length": 64,
  "learning_rate": 0.001
}
```

Guárdalo, con tus propios ejemplos, en `models/train-request.json` y envíalo:

```sh
curl http://127.0.0.1:11434/api/train \
  -H 'Content-Type: application/json' \
  --data-binary @models/train-request.json
```

Condiciones actuales:

- Cada conjunto debe contener entre 1 y 128 ejemplos con `prompt`, `completion` y `verified: true`.
- Los prompts de entrenamiento no deben repetirse en evaluación. La comprobación textual no detecta toda posible filtración semántica.
- `epochs`: 1–20; `max_length`: 16–256; `learning_rate`: mayor que cero y como máximo 0,01.
- Se entrenan el experto seleccionado y el enrutador; los demás expertos y el checkpoint base se conservan.
- Se acepta un candidato si mejora la pérdida de validación y la pérdida de guardrail no empeora más del 2 %.

El servidor calcula características del prefijo congelado, entrena un candidato separado y evalúa su salida. El objetivo de entrenamiento usa por defecto 2.048 candidatos de vocabulario; la validación calcula la normalización sobre el vocabulario completo en bloques FP32.

Si acepta el candidato, copia sus tensores a la extensión activa y guarda el archivo lateral de forma atómica. No necesita recargar el checkpoint. Si lo rechaza, mantiene la extensión anterior. Generación y entrenamiento comparten un bloqueo: **no se modifican los pesos a mitad de una respuesta, y Pi espera si hay una ronda activa**.

Consulta `last_training` y `micro_version` en `/api/runtime/status`. El aprendizaje heredado puede figurar como desactivado mientras este endpoint nativo sigue disponible.

El entrenamiento por tema se pide al agente en lenguaje normal. Para clientes HTTP también existe `POST /api/micro-training/train-topic` con `{"topic":"redes eléctricas","messages":[...]}`. La selección combina el tema, los pares completos del historial enviado y los recuerdos CHL verificados. Los pares del chat se registran como autorizados para ese entrenamiento, no como hechos verificados. Si encuentra menos de tres pares distintos, devuelve `insufficient_topic_data` y conserva los pesos.

### Entrenamiento de microexpertos fuera del servidor

Para preparar una caché y entrenar un candidato por CLI:

```sh
atenhea micro-train cache \
  --bundle models/athenea-e2b.nram \
  --train models/reviewed-train.jsonl \
  --validation models/heldout.jsonl \
  --output models/athenea-cache --max-length 64

atenhea micro-train train \
  --extension models/athenea-e2b.extensions.nram \
  --cache models/athenea-cache \
  --output models/micro-candidate.nram --expert 0
```

Los archivos JSONL contienen un objeto `prompt`/`completion` por línea. El comando de caché carga su propia instancia del modelo: no reutiliza el servidor HTTP residente. En un dispositivo ajustado de memoria, utiliza preferentemente `/api/train` o detén el servidor antes de preparar la caché fuera de él.

Reconstruye la caché si cambian los pesos base o los adaptadores LoRA. El candidato generado por CLI no sustituye por sí solo la extensión del servidor.

Puedes crear un banco candidato con un experto adicional:

```sh
atenhea micro grow \
  --extension models/athenea-e2b.extensions.nram \
  --output models/athenea-expanded.extensions.nram
```

El banco activo no cambia y el experto nuevo queda desactivado. Esta operación no crea conocimiento útil sin entrenamiento y evaluación.

### Autoconocimiento documental y rondas LoRA

```sh
atenhea rsi-prepare --ingest-docs

atenhea rsi-train \
  --bundle models/athenea-e2b.nram \
  --train models/reviewed-train.jsonl \
  --validation models/heldout.jsonl \
  --guardrail models/regression.jsonl \
  --specialization code --rounds 1
```

`rsi-prepare` reúne capacidades documentadas y una selección de fuentes del repositorio. `--analyze` puede pedir al modelo local una propuesta, que se conserva como no verificada. `rsi-train` ejecuta de una a tres rondas sobre copias candidatas y se detiene si una ronda no cumple sus condiciones.

Este flujo utiliza su propio proceso de entrenamiento y no promueve automáticamente el resultado al servidor. Conserva el original y exige evaluación posterior. Reutilizar repetidamente el mismo conjunto de validación tampoco sustituye un benchmark final intacto.

El proyecto implementa herramientas acotadas para preparar y evaluar mejoras. **No demuestra RSI autónomo, edición semántica fiable de los pesos ni mejora general continua.**

## Diagnóstico

### Pi parece congelado

```sh
curl http://127.0.0.1:11434/api/runtime/status
curl http://127.0.0.1:11434/api/health
tail -n 40 onram-backend.log
tail -n 40 onram-server.log
```

Interpreta los campos así:

| Campo | Qué indica |
| --- | --- |
| `loaded` | El motor terminó de cargar. |
| `pid`, `loaded_at` | Identidad del proceso y momento de carga; se mantienen entre sesiones. |
| `weights_load_count` | Una carga de pesos durante la vida de ese motor. |
| `activity.state` | `idle`, preparación o generación. |
| `activity.phase` | `prefix_cache` al preparar o recuperar la caché, `prefill` para el resto del prompt y `decoding` al producir tokens. |
| `prefix_cache` | Tokens y bytes retenidos, límites, aciertos y fallos. |
| `placement` | Colocación de la tabla de embeddings en CPU y ausencia de cuantización. |
| `last_inference` | Duración, tokens, límite, motivo de fin, acierto de caché y tokens reutilizados. En streaming incluye `first_token_seconds`. |
| `last_training` | Etapa o resultado del último microentrenamiento de este proceso. |
| `micro_version` | Versión de la extensión activa. |

Un prompt largo puede tardar antes del primer fragmento. El máximo de contexto no es una promesa de latencia. Los pesos mapeados también pueden verse afectados por presión de memoria del sistema.

La ruta Metal de los microexpertos evita lecturas escalares de GPU y selecciones de tamaño variable por experto; utiliza residuos enmascarados equivalentes a la ruta dispersa. Esto reduce un punto de bloqueo observado, pero no garantiza que cualquier fallo del controlador GPU sea recuperable desde el proceso.

Si cancelaste una petición, espera a que termine su paso activo. Si el proceso no avanza, cancela la petición del agente y reinicia el servidor desde su terminal. No elimines los archivos de pesos o memoria para resolver un bloqueo de ejecución.

### «Response was truncated before completion»

Revisa el límite que envió el cliente y `last_inference.finish_reason`. Un motivo `length`, `max_tokens` o un estado Responses `incomplete` indica un presupuesto agotado. El streaming no elimina esos límites. Reduce el historial o ajusta la salida dejando espacio para la entrada.

### Backend equivocado o modelo no encontrado

Comprueba `models/onram-launch.json` y `/v1/models`. La ruta nativa debe usar `--backend nram` y el alias `athenea-e2b:latest`. Los argumentos explícitos de arranque pueden sustituir el perfil.

Sin el perfil local, otras rutas heredadas pueden seleccionar otro backend. Completa el paso de creación del perfil antes de utilizar el arranque automático.

### Node.js o CHL no disponibles

Comprueba `ONRAM_NODE`, el checkout `third_party/chl` y el resultado de `episodic_memory.py recall`. `ONRAM_CHL_REPO` permite apuntar a otro checkout. La ausencia del complemento nativo no exige desactivar la memoria: existe la alternativa JavaScript.

### Cliente de agente ausente

Un mensaje como `` `claude` was not found on PATH `` indica que falta el cliente o su ruta, no los pesos del E2B. Instala o localiza ese programa y vuelve a ejecutar `atenhea launch ...`.

## Pruebas

Una selección de pruebas del backend nativo, protocolos, memoria y entrenamiento:

```sh
.venv/bin/python -m unittest \
  test_inference_settings test_agent_native test_native_runtime \
  test_prefix_cache test_native_placement \
  test_micro_extensions test_world_memory test_nram_low_memory \
  test_trainable_download test_nram_generic test_nram_evolve_generic \
  test_nram_container test_self_training test_self_improvement \
  test_episodic_memory test_onram_memory test_runtime_attribution \
  test_onram test_strata_backend -q
```

Las pruebas CHL necesitan su checkout y Node.js; algunas pruebas de tokenizador requieren el checkpoint local. Las pruebas de API abren sockets de loopback. Los resultados omitidos por dependencias ausentes deben distinguirse de pruebas ejecutadas y aprobadas.

La verificación local también ha incluido sesiones reales de Pi y Codex, transferencia SSE incremental, reutilización del mismo PID y liberación del motor tras cancelar una respuesta. Son comprobaciones funcionales; no constituyen una evaluación general de precisión.

Los comandos heredados `nram`, `nram-eval`, `nram-sweep`, `nram-memory`, `nram-adapt` y `nram-prepare-data` apuntan a un paquete hermano `nra_m` del workspace original. Ese paquete no se incluye en una clonación independiente de este repositorio; las pruebas que lo exigen pueden fallar aunque la ruta nativa E2B esté instalada.

## Organización del proyecto

| Ruta | Contenido |
| --- | --- |
| `atenhea`, `build_onram.sh`, `onram_launcher.c` | Comando y lanzador compilado. |
| `onram_cli.py` | Despacho de comandos y arranque de agentes. |
| `onram.py` | Proxy público, integración de memoria y API de administración. |
| `native_runtime.py`, `native_protocol.py` | Inferencia nativa, streaming y adaptación de protocolos. |
| `prefix_cache.py`, `native_placement.py` | Reutilización exacta del prefijo KV y colocación CPU/MPS del E2B. |
| `nram_container.py`, `nram_generic.py`, `nram_convert.py` | Contenedor, adaptadores y conversión desde el checkpoint. |
| `micro_extensions.py`, `micro_training.py`, `micro_training_control.py` | Microexpertos, entrenamiento cacheado y solicitudes temáticas o rondas programadas. |
| `episodic_memory.py`, `integrations/chl_bridge.cjs` | Puente de memoria CHL. |
| `world_memory.py` | Registros explícitos de hechos y eventos. |
| `prefix_cache.py`, `native_placement.py` | Caché exacta y colocación de embeddings para reducir el procesamiento repetido y la memoria GPU. |
| `inference_settings.py` | Preferencia de explicación breve, modificable sin recarga. |
| `self_improvement.py`, `rsi_loop.py` | Preparación documental y rondas candidatas LoRA. |
| `docs/athenea-capabilities.json` | Capacidades y límites que se incorporan al autoconocimiento documental. |
| `models/` | Pesos, perfiles, memorias, extensiones y candidatos locales; ignorado por Git. |
| `third_party/` | Dependencias descargadas, incluido CHL; ignorado por Git. |

### Rutas experimentales conservadas

El repositorio también contiene adaptadores y herramientas para llama.cpp/GGUF, Strata, modelos distintos del E2B y mediciones de SSD/Metal. Se seleccionan explícitamente y no son necesarios para la instalación nativa descrita aquí.

Consulta `atenhea --help` y la ayuda de cada subcomando. El trabajo de almacenamiento está descrito en [docs/apple-ssd-performance.md](docs/apple-ssd-performance.md). Sus resultados y los de otros modelos no deben atribuirse a la velocidad de inferencia o entrenamiento del E2B.

Los pesos del modelo y CHL pertenecen a sus respectivos proyectos y condiciones de distribución. Esta instalación no redistribuye el checkpoint ni una memoria personal entrenada.
