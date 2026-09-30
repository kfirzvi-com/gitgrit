"""Pure scoring helpers shared by the eval commands (``eval_topology``,
``eval_jev_links``). No Django, no I/O: every function takes plain numbers,
sets and tuples so it can be unit-tested without a database."""
from __future__ import annotations

import math
from collections import Counter
from typing import Iterable, Sequence

SECTIONS = ("components", "internal", "externals", "infrastructure")
EDGE_SECTIONS = ("internal", "externals")


# --- Map-level (eval_topology) ------------------------------------------------------


def f1(precision: float, recall: float) -> float:
    """Harmonic mean of precision and recall; 0 when both are 0."""
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def jaccard_distance(a: set, b: set) -> float:
    """1 - |a ∩ b| / |a ∪ b|; 0 when both sets are empty."""
    union = a | b
    if not union:
        return 0.0
    return 1 - len(a & b) / len(union)


def edge_keys(keys: dict[str, set]) -> set:
    """The edge set of one run: ``internal`` ∪ ``externals`` keys, tagged by section."""
    return {(section, *key) for section in EDGE_SECTIONS for key in keys[section]}


def flip_rate(edge_sets: list[set]) -> float:
    """Mean Jaccard distance between consecutive runs' edge sets; 0 for one run."""
    if len(edge_sets) < 2:
        return 0.0
    distances = [jaccard_distance(a, b) for a, b in zip(edge_sets, edge_sets[1:])]
    return sum(distances) / len(distances)


def summarize(rows_per_run: list[list[dict]]) -> dict[str, dict[str, float]]:
    """Per section: mean precision, mean recall and mean F1 over the runs.

    ``rows_per_run`` is one ``score()`` result per run. F1 is computed per run
    and then averaged, so a run that scores 0 on both drags the mean down
    instead of vanishing into a mean-of-means.
    """
    by_section: dict[str, list[dict]] = {section: [] for section in SECTIONS}
    for rows in rows_per_run:
        for row in rows:
            by_section[row["section"]].append(row)
    out = {}
    for section, rows in by_section.items():
        n = len(rows)
        if n == 0:
            out[section] = {"precision": 0.0, "recall": 0.0, "f1": 0.0}
            continue
        out[section] = {
            "precision": sum(r["precision"] for r in rows) / n,
            "recall": sum(r["recall"] for r in rows) / n,
            "f1": sum(f1(r["precision"], r["recall"]) for r in rows) / n,
        }
    return out


# --- Candidate-level (eval_jev_links) --------------------------------------------------
#
# A labelled case is the tuple ``(score, positive, correct)``:
#   score     the "add this edge" score the decision would be thresholded on
#             (``link``; 0 when the model chose none / an unnamed external)
#   positive  the label says an edge exists (expected is a ref or external)
#   correct   the decision's target equals the label


def precision_recall_at(
    cases: Iterable[tuple[float, bool, bool]], thresholds: Iterable[float]
) -> list[dict]:
    """Precision / recall of "add an edge" for every threshold.

    An edge is added when ``score ≥ threshold``; it counts as a true positive
    only when the label has an edge *and* the target is right — an edge to
    the wrong component is a false positive even when some edge was expected.
    With nothing added, precision is 1.0 when nothing was expected and 0.0
    otherwise (a too-timid model must not pass the bar vacuously).
    """
    rows = list(cases)
    positives = sum(1 for _, positive, _ in rows if positive)
    out = []
    for threshold in thresholds:
        added = [(positive, correct) for score, positive, correct in rows if score >= threshold]
        tp = sum(1 for positive, correct in added if positive and correct)
        if added:
            precision = tp / len(added)
        else:
            precision = 1.0 if positives == 0 else 0.0
        recall = tp / positives if positives else 1.0
        out.append(
            {
                "threshold": round(threshold, 2),
                "added": len(added),
                "tp": tp,
                "precision": precision,
                "recall": recall,
            }
        )
    return out


def threshold_grid(start: float = 0.50, stop: float = 0.95, step: float = 0.05) -> list[float]:
    n = int(round((stop - start) / step)) + 1
    return [round(start + i * step, 2) for i in range(n)]


def calibration_buckets(cases: Iterable[tuple[float, bool]], width: float = 0.1) -> list[dict]:
    """How often the edge was right per ``width``-wide bucket of the score.

    ``cases`` are ``(score, correct)``. A calibrated model is right ~80 % of
    the time in the 0.8–0.9 bucket. Score 1.0 falls into the top bucket.
    Buckets with no case are omitted.
    """
    buckets = int(round(1 / width))
    counts: dict[int, list[int]] = {}
    for score, correct in cases:
        index = min(buckets - 1, max(0, int(math.floor(score / width + 1e-9))))
        entry = counts.setdefault(index, [0, 0])
        entry[0] += 1
        entry[1] += 1 if correct else 0
    out = []
    for index in sorted(counts):
        n, right = counts[index]
        out.append(
            {
                "lo": round(index * width, 2),
                "hi": round((index + 1) * width, 2),
                "n": n,
                "right": right,
                "share": right / n,
            }
        )
    return out


def flip_share(bands_per_run: Sequence[Sequence[str]]) -> float:
    """Share of cases whose band differed between any two runs; 0 for one run.
    Every run must list the same cases in the same order."""
    runs = [list(bands) for bands in bands_per_run]
    if len(runs) < 2 or not runs[0]:
        return 0.0
    n = len(runs[0])
    flipped = sum(1 for i in range(n) if len({bands[i] for bands in runs}) > 1)
    return flipped / n


def accuracy(hits: int, total: int) -> float:
    """``hits / total``; 1.0 when there was nothing to score."""
    return hits / total if total else 1.0


def confusion(pairs: Iterable[tuple[str, str]]) -> Counter:
    """``Counter`` of ``(expected, predicted)`` class pairs."""
    return Counter(pairs)
