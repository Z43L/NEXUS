"""Generates the H0 dogfood batch: 100 novel-factory style jobs + 1 tools probe.

Tasks mirror the real internal demand of spec section 10 (summaries, character
sheets, continuity checks) over short original chapter fragments written for
this test batch. Swap the fragments for real chapters at any time: the metering
and ledger do not care about the text.
"""
from __future__ import annotations

import json
from pathlib import Path

FRAGMENTS = [
    "La inspectora Vidal llegó al puerto de Getxo con la lluvia pegada al abrigo. "
    "El farero juraba haber visto una luz verde sobre el agua a las tres de la mañana, "
    "pero el registro del faro no marcaba ninguna señal. En el muelle, un hombre sin "
    "nombre vendía relojes que solo marcaban horas pasadas. Vidal anotó el detalle "
    "en su libreta y sintió que el caso de los martes empezaba otra vez.",
    "Marta guardó la carta de su madre en el cajón de las mecanógrafas sin leerla. "
    "Llevaba veinte años tecleando informes ajenos en Lisboa y aquella letra inclinada "
    "era lo único que no se atrevía a transcribir. Cuando la oficina cerró, quemó la "
    "primera página y guardó las cenizas en un sobre con su nombre.",
    "El capitán del Meridiano ordenó arriar las velas antes de la tormenta anunciada. "
    "Su segundo, un joven de Arnedo que nunca había salido de puerto, encontró en la "
    "bodega un cofre con mapas de costas que no existían. La tripulación votó seguir "
    "la ruta del cofre. Nadie preguntó quién lo había dejado allí.",
    "En la lista de mi madre había cuarenta nombres y solo tres tachados. Mi abuela "
    "decía que tachar un nombre era una forma de perdonar, y que mi madre jamás "
    "perdonaba dos veces. Encontré la lista dentro de un misal, entre una estampa de "
    "Arnedo y una factura de 1974 que nadie había pagado nunca.",
    "Noventa días sin puerto enseñan a contar el agua y las mentiras. El cocinero "
    "del Ajuar racionaba el pan y las noticias por igual: un cuarto para cada hombre, "
    "nada para el polizón. Cuando por fin vieron tierra, el polizón era el único que "
    "sabía leer la carta de navegación que llevaban usando al revés.",
    "La casa de Urduliz tenía una habitación que solo aparecía en los planos antiguos. "
    "El casero la alquilaba más barata porque, decía, el inquilino anterior seguía "
    "recibiendo cartas allí. La primera noche, alguien deslizó un sobre bajo la puerta "
    "que no existía, con una llave y una fecha: el próximo martes.",
    "El relojero de la calle Mayor reparaba relojes que nadie le llevaba. Los recibía "
    "por correo, sin remitente, siempre parados a la misma hora. Cuando la inspectora "
    "le preguntó por el hombre del muelle, el relojero abrió un cajón con treinta "
    "relojes iguales y dijo que uno de ellos era el original.",
    "La última mecanógrafa de Lisboa guardaba una copia de cada carta que escribía. "
    "Su archivo ocupaba dos habitaciones y contenía, según ella, la verdadera historia "
    "de la ciudad: no la de los periódicos, sino la de las despedidas. El día que "
    "cerró la oficina, un desconocido le encargó mecanografiar su propia esquela.",
]

TASKS = [
    ("resumen", "Resume el siguiente fragmento de novela en exactamente 3 frases, "
                "conservando nombres propios y lugares. Fragmento:\n\n{}", 40),
    ("ficha_personaje", "Del siguiente fragmento, extrae una ficha de personaje con: "
                        "nombre, rasgo principal, motivación y un detalle verificable "
                        "del texto. Fragmento:\n\n{}", 30),
    ("continuidad", "Actúa como editor de continuidad. Del siguiente fragmento, lista "
                    "los hechos establecidos (lugar, época, objetos, promesas) que un "
                    "capítulo posterior no debe contradecir. Fragmento:\n\n{}", 30),
]


def main() -> None:
    jobs = []
    idx = 0
    for kind, template, count in TASKS:
        for i in range(count):
            fragment = FRAGMENTS[(idx + i) % len(FRAGMENTS)]
            jobs.append({
                "kind": kind,
                "model": "athenea-e2b",
                "nram": [],
                "messages": [{"role": "user", "content": template.format(fragment)}],
                "params": {"temperature": 0.3, "max_tokens": 220},
            })
        idx += count
    assert len(jobs) == 100, len(jobs)
    probe = {
        "kind": "probe_tools",
        "model": "athenea-e2b",
        "nram": [],
        "messages": [{"role": "user", "content": "Di hola."}],
        "params": {"temperature": 0.0, "max_tokens": 16},
        "tools": [{"type": "function",
                   "function": {"name": "read_file", "parameters": {"type": "object"}}}],
    }
    out = Path(__file__).resolve().parent / "jobs.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for job in jobs:
            fh.write(json.dumps(job, ensure_ascii=False) + "\n")
        fh.write(json.dumps(probe, ensure_ascii=False) + "\n")
    print(f"wrote {out}: 100 jobs + 1 tools probe")


if __name__ == "__main__":
    main()
