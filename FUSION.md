# NEXUS × Atenhea — proyecto unificado

> **Estado de ejecución actualizado a 2026-10-26:** para límites, pruebas y puertas abiertas, consulta [EXECUTIVE_BRIEF.md](EXECUTIVE_BRIEF.md) y [PROJECT_DELIVERY.md](PROJECT_DELIVERY.md). Las notas de diseño posteriores a esta sección pueden ser históricas.

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

- **H0**: el E2E mock pasa 100/100 jobs, recibos verificados, discrepancia 0%,
  rechazos de tools/firma/replay y prueba de workers. La corrida Atenhea real
  también pasó 100/100, con salida limitada a 24 tokens/job; no se registró el
  hash de pesos ni se completó la puerta económica de la spec.
- **API y Compose**: SDK → FastAPI autenticada → Router → worker está probado
  localmente. Compose ahora define esa misma entrada, con TLS/CA privada entre
  API y Router y Router sin puerto del host; el build/runtime Docker y CI aún
  deben ejecutarse.
- **H1–H4**: no se ha validado conectividad entre redes ni liquidación en
  testnet. Adaptadores `.nram` por red, canarios, nodos externos y beta pública
  siguen pendientes; véanse las puertas en la hoja ejecutiva.

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
