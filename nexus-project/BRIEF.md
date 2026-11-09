# NEXUS — brief compartido para todos los agentes

Fecha: 2026-10-27. Idioma de documentos y landing: **español** (landing también en inglés bajo `site/en/`). Código, identificadores
y comentarios breves: **inglés**. Este brief manda: si algo choca con tu criterio, sigue el brief y anótalo en tu informe final.

## 1. Qué es el producto

**NEXUS** es una red descentralizada de IA donde **ningún operador posee el modelo completo** y el cómputo (inferencia primero,
fine-tuning después) se reparte entre nodos independientes **en proporción a lo que cada uno aporta**.

- **Demanda**: desarrolladores y empresas que quieren una API compatible con OpenAI sobre modelos abiertos, con recibos firmados
  verificables y precio por debajo de proveedores centralizados; y **autores de modelos** que quieren publicar y cobrar regalías
  sin entregar los pesos en claro a un único operador.
- **Oferta**: dueños de GPU (aficionados, pequeños centros de datos, universidades) que cobran por trabajo verificado.
- **Producto v0.1 (alpha cerrada, testnet, sin token)**: (1) gateway OpenAI-compatible; (2) agente de nodo; (3) CLI de publicación
  de modelos (partir → cifrar → erasure coding → manifiesto firmado); (4) coordinador con asignación de slots y enrutado
  proporcional a capacidad; (5) recibos firmados y libro de contribuciones con lotes de liquidación; (6) demo multiproceso con un
  modelo pequeño real repartido por etapas. Reutiliza `NEXUS/nexus/h0` (router/worker/recibos), `NEXUS/settlement-evm`
  (escrow por lotes) y `NEXUS/atenhea` (motor local). La landing de borrador está en `NEXUS/site/`.

## 2. Diseño técnico decidido (sale de `research/swarm-sim`, léelo)

- El modelo se parte en **S slots** (rangos de capas). Cada **operador queda fijo en un único slot** ⇒ ningún operador reúne más de
  1/S. La asignación usa una permutación aleatoria por bloques de capacidad (**estratificada**, baliza aleatoria tras cerrar el
  registro): eficiencia 0,96 y el atacante no elige slot.
- Dentro de un slot, el trabajo se enruta **proporcional a la velocidad** de cada nodo; el pago es proporcional al trabajo
  verificado (`work_share`).
- Pesos en reposo: trozos cifrados + **erasure coding k-de-n** (p. ej. 10-de-16, 1,6× de sobrecarga) con manifiesto Merkle
  anclado on-chain. Los nodos de almacenamiento solo ven ciphertext; la clave se libera a un nodo asignado.
- Un nodo de cómputo **sí tiene en claro su slot en memoria**. Eso es inevitable sin TEE/MPC.
- Opciones de mayor secreto, no para el MVP: corte de cada capa en T trozos (coste ~0,6 s/token con T=8 en el mejor caso),
  TEE con attestation, huella por nodo con detección y recorte de stake.
- Números del simulador (orden de magnitud, no medidas). **Diseño de slots (el del producto, S=16, ~300 nodos por slot, T=1):**
  ≈ 2,8 tok/s por stream; una coalición del 2 % de operadores reúne el modelo con P≈0,44 y del 5 % con P≈0,99; cortando cada capa
  en T=8 trozos baja a ≈ 0 (2–5 %) y 0,007 (10 %), con ≈ 0,6 s/token extra en el mejor caso. **No mezcles con las cifras de "3 réplicas
  por etapa" (30 % → 0,03 con S=8): son otro diseño y no se aplican a v0.1.** Entrenar 70B en GPUs de 24 GB exige ~59 etapas y
  compresión de activaciones ≥10×; DiLoCo exige réplica completa.
  Un Sybil sin huella ni comisión reúne un modelo de 16 slots por ~770 $ (parámetros ilustrativos): el stake solo no protege.
  Unir un nodo a un slot de 2,2 GB tarda ~60 s; la salida del operador mayor tarda ~27 min en restaurarse.

## 3. Reglas de honestidad (obligatorias, afectan a código, docs, web y marketing)

1. **No prometas lo que no existe.** No digas "trustless", "imposible de copiar", "pesos nunca descargables", "privacidad total",
   "descentralizado" sin matiz. Di: "ningún operador tiene el modelo completo; una coalición lo bastante grande sí podría
   reconstruirlo; quien consulta puede destilarlo".
2. **Sin datos inventados**: ni clientes, logos, testimonios, métricas de usuarios, benchmarks, rondas, ingresos ni partners. Si falta
   un dato, escribe `[POR VERIFICAR]` o presenta un supuesto etiquetado como tal. Toda cifra de mercado lleva fuente (URL y fecha).
3. **Estado real**: alpha cerrada, testnet, sin token, sin liquidación con dinero real. La web debe decirlo con claridad.
4. **Nada de promesas financieras ni de rendimiento a operadores.** No "gana X al mes". Habla de "pago por trabajo verificado".
5. **Token**: no hay token en v0.1. Si un documento lo discute, que sea como opción futura con riesgos regulatorios (valores) explícitos.
6. **Licencias**: respeta las licencias de los modelos base (p. ej. Gemma, Llama); cualquier modelo del catálogo lleva su licencia.
7. **Seguridad**: no pongas secretos, claves ni credenciales reales en ningún archivo. Hay una credencial antigua expuesta en el historial
   (`8445b54`) que el equipo debe rotar; no la reproduzcas.
8. **Marca/dominio**: la web usa `https://nexus.example` como marcador. El nombre NEXUS puede chocar con marcas existentes: el
   agente de go-to-market lo investiga y lo deja como riesgo; no lo des por resuelto.

## 4. Entorno

- Python **3.9.6**, **solo biblioteca estándar** disponible de serie (no hay numpy, cryptography, fastapi, torch, node).
  Puedes intentar `python3 -m venv nexus-project/code/.venv && .venv/bin/pip install cryptography numpy` (si hay red). Si falla,
  usa solo stdlib: `hashlib`, `hmac`, `secrets`, `struct`, `asyncio`, `http.server`, `sqlite3`, `unittest`. Escribe el código con
  interfaces que permitan sustituir piezas (p. ej. `Cipher`, `Signer`) por librerías auditadas. Si implementas cripto en Python
  puro (Ed25519 RFC 8032, cifrado por flujo con HMAC), márcalo `NOT AUDITED – replace with vetted library` en el código y en el README.
- Docker existe (`/opt/homebrew/bin/docker`); no asumas que corre. Sin `node`, `forge` ni `anvil`.
- Los tests se ejecutan con `python3 -m unittest` (no hay pytest). Todo el código nuevo lleva tests que **debes ejecutar** y cuyo
  resultado real reportas.
- No hagas `git commit`, `git push` ni cambios fuera de tu carpeta. No modifiques `NEXUS/` ni `research/` (léelos y reutiliza copiando
  o importando por ruta). No instales nada globalmente.

## 5. Propiedad de carpetas (no escribas fuera de la tuya)

| Agente | Carpeta |
|---|---|
| product-architect | `nexus-project/docs/product/` |
| eng-storage | `nexus-project/code/nexus_storage/` (+ `code/tests/storage/`) |
| eng-runtime | `nexus-project/code/nexus_runtime/`, `code/nexus_api/`, `code/nexus_cli/`, `code/deploy/`, `code/tests/runtime/` |
| gtm | `nexus-project/docs/go-to-market/` |
| landing | `nexus-project/site/` |
| business | `nexus-project/docs/business/` y `nexus-project/finance/` |

Raíz de `nexus-project/` (README, INDEX) la escribe el agente principal. Cada agente termina con un **informe final de ≤ 300
palabras**: qué creó (rutas), qué verificó (comandos y resultados reales), qué quedó pendiente o `[POR VERIFICAR]`, y decisiones que tomó
sin consultar.

## 6. Contrato entre `nexus_storage` y `nexus_runtime`

`eng-storage` expone (paquete `nexus_storage`, importable con `PYTHONPATH=nexus-project/code`):

```python
# manifest.py
@dataclass class ModelManifest: model_id:str; version:str; n_layers:int; n_slots:int; n_slices:int; ec_k:int; ec_n:int
    cipher:str; license:str; author_pubkey:str; royalty_bps:int; slots:list  # [{slot:int, slice:int, chunk_cids:[str], merkle_root:str, size:int}]
    signature:str
    def to_json(self)->str; @staticmethod def from_json(s:str)->"ModelManifest"; def verify(self)->bool
# store.py
class FragmentStore: def put(self,data:bytes)->str; def get(self,cid:str)->bytes|None; def has(self,cid:str)->bool  # contenido-direccionado (sha256)
class DirStore(FragmentStore): ...
# publish.py
def publish_model(layers:list[bytes], *, model_id, version, n_slots, ec_k, ec_n, store, author_signer, license, royalty_bps=0, n_slices=1)->tuple[ModelManifest, bytes]  # (manifest, master_key)
def fetch_slot(manifest, slot:int, store, key:bytes, slice:int=0)->list[bytes]  # capas del slot, en claro, verificadas contra Merkle
# vault.py
class KeyVault: def grant(self, node_id:str, slot:int, *, attestation:dict|None=None)->bytes; def revoke(self,node_id:str)->None  # clave derivada por slot
# erasure.py: encode(data,k,n)->list[bytes]; decode(frags:dict[int,bytes],k,n,length)->bytes
```

`eng-runtime` programa contra esta firma. Si `nexus_storage` no existe aún al integrarse, crea un stub mínimo en sus propios tests y
déjalo anotado; al final comprueba si ya existe y, si es así, ejecuta la integración real.
