from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ClassificationMetrics:
    total: int
    correct: int
    accuracy: float
    accuracy_ci95: tuple[float, float]
    macro_f1: float
    confusion: dict[str, dict[str, int]]
    confidence_brier: float | None = None


@dataclass(frozen=True, slots=True)
class RetrievalMetrics:
    precision_at_k: float
    recall_at_k: float
    reciprocal_rank: float
    ndcg_at_k: float


@dataclass(frozen=True, slots=True)
class DetectionMetrics:
    total: int
    true_positive_rate: float
    true_positive_rate_ci95: tuple[float, float]
    false_positive_rate: float
    false_positive_rate_ci95: tuple[float, float]
    precision: float
    accuracy: float
    accuracy_ci95: tuple[float, float]


def wilson_interval(
    successes: int, total: int, *, z: float = 1.959963984540054
) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    This is deterministic, dependency-free, and behaves sensibly at 0%/100%, unlike the normal
    approximation. It is reported as uncertainty context; CI regression gates still use the point
    estimates so tiny development fixtures do not become pseudo-statistical acceptance tests.
    """
    if total <= 0:
        return (0.0, 0.0)
    if successes < 0 or successes > total:
        raise ValueError("successes must be between zero and total")
    p = successes / total
    z2 = z * z
    denominator = 1.0 + z2 / total
    center = (p + z2 / (2.0 * total)) / denominator
    margin = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * total)) / total) / denominator
    return (max(0.0, center - margin), min(1.0, center + margin))


def classification_metrics(
    expected: list[str], predicted: list[str], *, confidences: list[float] | None = None
) -> ClassificationMetrics:
    if len(expected) != len(predicted) or not expected:
        raise ValueError("expected and predicted must be non-empty and have the same length")
    labels = sorted(set(expected) | set(predicted))
    confusion = {label: {other: 0 for other in labels} for label in labels}
    for truth, guess in zip(expected, predicted, strict=True):
        confusion[truth][guess] += 1

    f1s: list[float] = []
    for label in labels:
        tp = confusion[label][label]
        fp = sum(confusion[truth][label] for truth in labels if truth != label)
        fn = sum(confusion[label][guess] for guess in labels if guess != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)

    correct = sum(int(truth == guess) for truth, guess in zip(expected, predicted, strict=True))
    brier = None
    if confidences is not None:
        if len(confidences) != len(expected):
            raise ValueError("confidences must match classification case count")
        # We have confidence in the selected label rather than a full probability vector. This is
        # therefore a selective-correctness Brier score, useful for regression/calibration trends
        # but not a multiclass proper-scoring-rule substitute.
        brier = sum(
            (float(conf) - float(truth == guess)) ** 2
            for conf, truth, guess in zip(confidences, expected, predicted, strict=True)
        ) / len(expected)

    return ClassificationMetrics(
        total=len(expected),
        correct=correct,
        accuracy=correct / len(expected),
        accuracy_ci95=wilson_interval(correct, len(expected)),
        macro_f1=sum(f1s) / len(f1s),
        confusion=confusion,
        confidence_brier=brier,
    )


def retrieval_metrics(ranked_ids: list[str], relevant_ids: set[str], *, k: int) -> RetrievalMetrics:
    if k < 1:
        raise ValueError("k must be positive")
    if not relevant_ids:
        raise ValueError("relevant_ids must not be empty")
    ranked = ranked_ids[:k]
    hits = [1 if item in relevant_ids else 0 for item in ranked]
    hit_count = sum(hits)
    precision = hit_count / k
    recall = hit_count / len(relevant_ids)
    reciprocal_rank = 0.0
    for rank, item in enumerate(ranked_ids, start=1):
        if item in relevant_ids:
            reciprocal_rank = 1.0 / rank
            break

    dcg = sum(hit / math.log2(index + 2) for index, hit in enumerate(hits))
    ideal_hits = min(len(relevant_ids), k)
    idcg = sum(1.0 / math.log2(index + 2) for index in range(ideal_hits))
    ndcg = dcg / idcg if idcg else 0.0
    return RetrievalMetrics(
        precision_at_k=precision,
        recall_at_k=recall,
        reciprocal_rank=reciprocal_rank,
        ndcg_at_k=ndcg,
    )


def aggregate_retrieval(metrics: list[RetrievalMetrics]) -> dict[str, float]:
    if not metrics:
        raise ValueError("metrics must not be empty")
    names = ("precision_at_k", "recall_at_k", "reciprocal_rank", "ndcg_at_k")
    output: dict[str, float] = {"cases": float(len(metrics))}
    for name in names:
        values = [getattr(item, name) for item in metrics]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        output[name] = mean
        output[f"{name}_std"] = math.sqrt(variance)
    return output


def detection_metrics(expected_risk: list[bool], predicted_risk: list[bool]) -> DetectionMetrics:
    if len(expected_risk) != len(predicted_risk) or not expected_risk:
        raise ValueError("detection vectors must be non-empty and equal length")
    counts = Counter(zip(expected_risk, predicted_risk, strict=True))
    tp = counts[(True, True)]
    fn = counts[(True, False)]
    fp = counts[(False, True)]
    tn = counts[(False, False)]
    positives = tp + fn
    negatives = fp + tn
    correct = tp + tn
    return DetectionMetrics(
        total=len(expected_risk),
        true_positive_rate=tp / positives if positives else 0.0,
        true_positive_rate_ci95=wilson_interval(tp, positives),
        false_positive_rate=fp / negatives if negatives else 0.0,
        false_positive_rate_ci95=wilson_interval(fp, negatives),
        precision=tp / (tp + fp) if tp + fp else 0.0,
        accuracy=correct / len(expected_risk),
        accuracy_ci95=wilson_interval(correct, len(expected_risk)),
    )


def graded_retrieval_metrics(ranked_ids: list[str], grades: dict[str, int], *, k: int) -> RetrievalMetrics:
    """Use annotated relevance gains for nDCG; recall counts unique relevant documents."""
    ranked = list(dict.fromkeys(ranked_ids))
    relevant = {key for key, grade in grades.items() if grade > 0}
    basic = retrieval_metrics(ranked, relevant, k=k)
    gains = [(2 ** grades.get(key, 0)) - 1 for key in ranked[:k]]
    dcg = sum(gain / math.log2(i + 2) for i, gain in enumerate(gains))
    ideal = sorted(((2 ** grade) - 1 for grade in grades.values() if grade > 0), reverse=True)[:k]
    idcg = sum(gain / math.log2(i + 2) for i, gain in enumerate(ideal))
    return RetrievalMetrics(basic.precision_at_k, basic.recall_at_k, basic.reciprocal_rank, dcg / idcg if idcg else 0.0)


def citation_faithfulness(cited: list[set[int]], supporting: list[set[int]]) -> dict[str, float]:
    """Score citation edges against annotations, never merely against resolvable IDs."""
    if len(cited) != len(supporting) or not cited:
        raise ValueError('citation vectors must be non-empty and aligned')
    true_edges = sum(len(actual & expected) for actual, expected in zip(cited, supporting, strict=True))
    actual_edges = sum(map(len, cited))
    expected_edges = sum(map(len, supporting))
    return {'citation_precision': true_edges / actual_edges if actual_edges else 1.0,
            'citation_recall': true_edges / expected_edges if expected_edges else 1.0,
            'citation_edges': float(actual_edges), 'annotated_support_edges': float(expected_edges)}
