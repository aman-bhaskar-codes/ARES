from ares.evaluation.metrics import aggregate_retrieval, classification_metrics, detection_metrics, retrieval_metrics, wilson_interval


def test_classification_metrics_include_macro_f1_and_selective_brier() -> None:
    result = classification_metrics(["a", "a", "b"], ["a", "b", "b"], confidences=[0.9, 0.8, 0.7])
    assert result.accuracy == 2 / 3
    assert 0 < result.macro_f1 < 1
    assert result.confidence_brier is not None
    assert 0 <= result.accuracy_ci95[0] <= result.accuracy <= result.accuracy_ci95[1] <= 1


def test_retrieval_metrics_compute_recall_mrr_and_ndcg() -> None:
    result = retrieval_metrics(["x", "r1", "r2"], {"r1", "r2"}, k=3)
    assert result.recall_at_k == 1.0
    assert result.reciprocal_rank == 0.5
    assert 0 < result.ndcg_at_k < 1
    aggregate = aggregate_retrieval([result, result])
    assert aggregate["cases"] == 2.0
    assert aggregate["recall_at_k_std"] == 0.0


def test_detection_metrics_separate_attack_detection_from_benign_false_positives() -> None:
    result = detection_metrics([True, True, False, False], [True, False, True, False])
    assert result.true_positive_rate == 0.5
    assert result.false_positive_rate == 0.5
    assert result.true_positive_rate_ci95[0] < result.true_positive_rate < result.true_positive_rate_ci95[1]
    assert result.false_positive_rate_ci95[0] < result.false_positive_rate < result.false_positive_rate_ci95[1]


def test_wilson_interval_remains_bounded_at_extremes() -> None:
    low = wilson_interval(0, 10)
    high = wilson_interval(10, 10)
    assert low[0] == 0.0 and 0 < low[1] < 1
    assert 0 < high[0] < 1 and abs(high[1] - 1.0) < 1e-12
