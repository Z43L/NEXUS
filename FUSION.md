# NEXUS × Atenhea — proyecto unificado

> **Estado de ejecución actualizado a 2026-10-25:** este documento conserva la propuesta y las notas originales de integración. Las frases de estado y «pendiente» en el cuerpo son históricas. Para el estado verificado actual, límites y puertas restantes, consulta [EXECUTIVE_BRIEF.md](EXECUTIVE_BRIEF.md) y [PROJECT_DELIVERY.md](PROJECT_DELIVERY.md).

Desde el 2026-10-20 todo vive en este único repositorio: NEXUS deja de ser solo
el plano económico/red y Atenhea deja de ser un repo separado. Un proyecto,
dos capas:

| Capa | Qué es | Dónde |
|---|---|---|
| **Motor de nodo** | Atenhea: runtime local de inferencia (Gemma E2B nativo, API compatible OpenAI, adaptadores `.nram`, memoria episódica CHL privada) | `NEXUS/atenhea/` |
| **Plano de control** | NEXUS: red P2P, descubrimiento, enrutado, medición, reputación, contratos y token NEX | `NEXUS/nexus/`, `NEXUS/contracts/` |
| **Integración H0** | Router + ledger local, worker sidecar con recibos firmados Ed25519, cliente dogfood de 100 trabajos | `NEXUS/nexus/h0/` |
| **Diseño** | Spec de fusión v0.1: arquitectura, protocolo, verificación, economía NEX v2, hitos H0–H4 | `docs/spec-fusion-nexus-atenea.md` |

## Principios (spec §0)

- Los pesos base **no** viajan por la red: cada nodo descarga el modelo de la
  fuente oficial y verifica hashes. Lo que la red distribuye y comercia son
  los `.nram` (MBs, verificables por SHA-256).
- La memoria episódica CHL de cada nodo es local y privada: nunca se sincroniza.
- Los trabajos remotos se ejecutan contra el **motor** de Atenhea (`:11436`),
  nunca contra el proxy de agentes: sin herramientas, sin CHL.
- La emisión de NEX se ata a trabajo pagado verificado (recibos firmados),
  no a subvenciones.

## Estado

- **H0** (integración en un solo equipo): código completo y probado de extremo
  a extremo contra un motor simulado (100/100 trabajos, 100 recibos
  verificados, discrepancia de conteo 0 %, sonda con `tools` rechazada,
  recibo manipulado rechazado). Ejecución contra el motor real en el Mac del
  autor: primera corrida detectó que el motor local solo expone el conteo de
  tokens en `/v1/messages/count_tokens`; el worker ya trae el fallback
  (probado) y la re-ejecución de la puerta H0 queda pendiente de esa corrida.
- Siguientes hitos (spec §11): H1 dos nodos + liquidación en testnet Base,
  H2 `.nram` por la red + verificación por canarios, H3 nodos externos,
  H4 beta pública.

## Ejecutar H0

En cualquier máquina con Atenhea (o con el mock para pruebas):

```sh
cd NEXUS/nexus/h0
python3 test_h0.py        # E2E contra el mock, sin motor real
./run_h0_mac.sh           # Mac del autor: motor real + 100 trabajos
```

El informe de la puerta queda en `h0_report.json` (`gate_passed`).

## Enmienda de medición H0 (2026-10-20)

La primera corrida real contra el motor (Mac del autor) completó 100/100
trabajos con 100 recibos verificados a 14,6 tok/s de salida, pero la
comparación bruta de tokens divergía hasta un 59,7 %. Causa medida, no
supuesta: el motor de Atenhea renderiza en cada generación un andamiaje fijo
de agente (instrucción de sistema + esquema de su herramienta de
entrenamiento, ≈428 tokens constantes por petición) que su endpoint de
conteo no incluye. Es sobrecarga del nodo, no trabajo del cliente:

- El cliente paga los tokens de su carga útil (conteo del tokenizer) + los de
  salida, nunca el andamiaje.
- El worker calibra el andamiaje al arrancar (una generación sonda de
  1 token) y lo declara en cada recibo (`scaffolding_tokens`); el Router lo
  resta antes de comparar, y la discrepancia vuelve a medir lo que debe:
  carga útil contra carga útil.
- Pendiente para H1: modo worker en el motor que no inyecte la herramienta
  de entrenamiento en trabajos remotos (ahorra el cómputo del andamiaje y
  evita que el modelo la vea).
