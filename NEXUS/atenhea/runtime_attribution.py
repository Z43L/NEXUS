"""Build quality-gated layer priors from live GGUF traces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _normalized_layer_values(report: dict[str, Any]) -> dict[int, float]:
    values = {
        item["layer"]: float(item.get("output_rms", 0.0))
        for item in report.get("layers", [])
        if isinstance(item, dict) and isinstance(item.get("layer"), int)
        and isinstance(item.get("output_rms"), (int, float))
        and float(item.get("output_rms", 0.0)) >= 0
    }
    mean = sum(values.values()) / len(values) if values else 0.0
    if mean <= 0:
        return {}
    return {layer: value / mean for layer, value in values.items()}


def build_runtime_activation_profile(trace_path: Path | None,
                                     training_rows: list[dict[str, Any]],
                                     *, minimum_bad_corrections: int = 3) -> dict[str, Any]:
    """Compare layers active in user-corrected answers with user-approved answers.

    The report contains no conversation text. At least three distinct corrected
    bad traces are required before the GGUF signal can steer adapter selection.
    """
    result: dict[str, Any] = {
        "enabled": False,
        "method": "feedback_labeled_gguf_layer_rms",
        "minimum_bad_corrections": minimum_bad_corrections,
        "matched_bad_corrections": 0,
        "matched_good_examples": 0,
        "layer_scores": {},
    }
    if trace_path is None or not trace_path.is_file():
        result["reason"] = "trace_ledger_unavailable"
        return result

    requested: dict[str, str] = {}
    for row in training_rows:
        trace_id = row.get("runtime_trace_id")
        feedback = row.get("runtime_feedback")
        if isinstance(trace_id, str) and trace_id and feedback in {"good", "bad_corrected"}:
            requested[trace_id] = feedback
    if not requested:
        result["reason"] = "no_feedback_labeled_training_rows"
        return result

    reports: dict[str, dict[str, Any]] = {}
    try:
        with trace_path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    report = json.loads(line)
                except json.JSONDecodeError:
                    continue
                trace_id = report.get("trace_id") if isinstance(report, dict) else None
                if (trace_id in requested and report.get("backend") == "llama.cpp-gguf"
                        and report.get("callback_events", 0) > 0):
                    reports[trace_id] = report
    except OSError as exc:
        result["reason"] = f"trace_ledger_unreadable: {exc}"
        return result

    bad_profiles: list[dict[int, float]] = []
    good_profiles: list[dict[int, float]] = []
    for trace_id, report in reports.items():
        values = _normalized_layer_values(report)
        if not values:
            continue
        target = bad_profiles if requested[trace_id] == "bad_corrected" else good_profiles
        target.append(values)

    result["matched_bad_corrections"] = len(bad_profiles)
    result["matched_good_examples"] = len(good_profiles)
    if len(bad_profiles) < minimum_bad_corrections:
        result["reason"] = "insufficient_bad_corrections"
        return result

    layers = set().union(*(profile.keys() for profile in bad_profiles + good_profiles))
    bad_mean = {
        layer: sum(profile.get(layer, 0.0) for profile in bad_profiles) / len(bad_profiles)
        for layer in layers
    }
    if good_profiles:
        good_mean = {
            layer: sum(profile.get(layer, 0.0) for profile in good_profiles) / len(good_profiles)
            for layer in layers
        }
        scores = {layer: max(0.0, bad_mean[layer] - good_mean[layer]) for layer in layers}
        if max(scores.values(), default=0.0) <= 1e-9:
            result["comparison"] = "bad_only_fallback_no_positive_contrast"
            scores = bad_mean
        else:
            result["comparison"] = "bad_minus_good_relative_layer_rms"
    else:
        result["comparison"] = "bad_relative_layer_rms"
        scores = bad_mean

    maximum = max(scores.values(), default=0.0)
    if maximum <= 0:
        result["reason"] = "no_activation_signal"
        return result
    result["layer_scores"] = {str(layer): score / maximum
                               for layer, score in sorted(scores.items()) if score > 0}
    result["enabled"] = len(result["layer_scores"]) >= 2
    if not result["enabled"]:
        result["reason"] = "insufficient_layer_variation"
    return result
