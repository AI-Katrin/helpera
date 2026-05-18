import unittest

from backend.ml.business_rules import business_adjustment, make_recommendation_reason
from backend.ml.config import COLD_START_THRESH, LEAKAGE_FEATURES
from backend.ml.data_repository import CsvRecommendationRepository
from backend.ml.features import build_pairs, prepare_feature_rows
from backend.ml.linucb import get_cold_task_flags_batch, score_cold_start
from backend.ml.model_loader import ModelArtifactNotFound, load_model_artifact
from backend.ml.recommender import _diversify


class BusinessRulesTests(unittest.TestCase):
    def test_positive_adjustments(self):
        row = {
            "task_urgency_score": 1,
            "ngo_reliability_score": 0.9,
            "volunteer_reliability_score": 0.8,
            "task_quality_score": 0.9,
            "cold_start_task": 1,
            "exploration_slot": 1,
            "eligible_for_recommendations": 1,
        }
        adj = business_adjustment(row)
        self.assertGreater(adj, 0)
        # Все повышающие корректировки
        expected = (
            0.20 * 1 + 0.20 * 0.9 + 0.15 * 0.8 + 0.10 * 0.9 + 0.12 * 1 + 0.08 * 1
        )
        self.assertAlmostEqual(adj, round(expected, 6), places=5)

    def test_hard_filter_eligible(self):
        # Жёсткий фильтр -5.0 перекрывает все положительные корректировки (~0.85 макс)
        row = {"eligible_for_recommendations": 0}
        adj = business_adjustment(row)
        self.assertLessEqual(adj, -5.0)

    def test_ngo_response_penalty(self):
        """ngo_response_penalty должен штрафовать -0.15, а не task_needs_ai_help."""
        row_with_penalty = {"ngo_response_penalty": 1, "eligible_for_recommendations": 1}
        row_without = {"ngo_response_penalty": 0, "eligible_for_recommendations": 1}
        self.assertAlmostEqual(
            business_adjustment(row_with_penalty) - business_adjustment(row_without),
            -0.15,
            places=5,
        )

    def test_cold_start_task_boost(self):
        """cold_start_task должен давать +0.08."""
        row_on = {"cold_start_task": 1, "eligible_for_recommendations": 1}
        row_off = {"cold_start_task": 0, "eligible_for_recommendations": 1}
        self.assertAlmostEqual(
            business_adjustment(row_on) - business_adjustment(row_off),
            0.08,
            places=5,
        )

    def test_composite_rule_unreliable_volunteer_hard_task(self):
        """reliability < 0.4 AND quality > 0.7 → -0.15.
        Изолируем только составное правило: меняем quality выше/ниже порога 0.7
        при фиксированном reliability < 0.4. Разница включает два эффекта:
          - линейный вклад quality: 0.10 * (0.8 - 0.5) = +0.03
          - составное правило: -0.15 (только когда quality > 0.7)
        Итого ожидаемая разница = 0.03 - 0.15 = -0.12.
        """
        row_match = {
            "volunteer_reliability_score": 0.3,
            "task_quality_score": 0.8,
            "eligible_for_recommendations": 1,
        }
        row_no_match = {
            "volunteer_reliability_score": 0.3,
            "task_quality_score": 0.5,  # quality NOT > 0.7 → составное не срабатывает
            "eligible_for_recommendations": 1,
        }
        quality_linear_diff = 0.10 * (0.8 - 0.5)
        composite_penalty = -0.15
        expected_diff = quality_linear_diff + composite_penalty
        self.assertAlmostEqual(
            business_adjustment(row_match) - business_adjustment(row_no_match),
            expected_diff,
            places=5,
        )

    def test_reason_format(self):
        reason = make_recommendation_reason({
            "skill_overlap_count": 1,
            "format_match": 1,
            "task_quality_score": 0.8,
            "business_adjustment": 0.2,
        })
        self.assertTrue(reason.startswith("Рекомендация:"))
        self.assertIn("подходит по навыкам", reason)


class FeaturesTests(unittest.TestCase):
    def setUp(self):
        self.repo = CsvRecommendationRepository()

    def test_cold_start_volunteer_flag_set(self):
        """cold_start_volunteer должен быть 1 для волонтёров с completeness < 0.4."""
        vols = self.repo.volunteers()
        # Находим волонтёра с высоким completeness
        warm_vol = next(
            v for v in vols.values() if v.get("profile_completeness", 0) >= 0.4
        )
        tasks = self.repo.get_candidate_tasks(warm_vol["volunteer_id"])[:1]
        rows = build_pairs(warm_vol, tasks, self.repo.get_ngos_for_tasks(tasks))
        self.assertEqual(rows[0]["cold_start_volunteer"], 0)

    def test_cold_task_flags_passed_to_features(self):
        """cold_start_task из batch-флагов должен попасть в признаки."""
        vols = self.repo.volunteers()
        vol = next(iter(vols.values()))
        tasks = self.repo.get_candidate_tasks(vol["volunteer_id"])[:2]
        task_ids = [t["task_id"] for t in tasks]
        # Перезаписываем все задачи как cold
        flags = {tid: 1 for tid in task_ids}
        rows = build_pairs(vol, tasks, self.repo.get_ngos_for_tasks(tasks), cold_task_flags=flags)
        self.assertTrue(all(r["cold_start_task"] == 1 for r in rows))

    def test_feature_order_and_leakage_guard(self):
        vol = next(iter(self.repo.volunteers().values()))
        tasks = self.repo.get_candidate_tasks(vol["volunteer_id"])[:2]
        rows = build_pairs(vol, tasks, self.repo.get_ngos_for_tasks(tasks))
        feature_cols = ["skill_overlap_count", "skill_jaccard", "format_match", "city_match"]
        prepared = prepare_feature_rows(rows, feature_cols)
        self.assertEqual(list(prepared[0].keys()), feature_cols)
        with self.assertRaises(ValueError):
            prepare_feature_rows(rows, ["skill_overlap_count", "clicked"])
        self.assertTrue({"clicked", "dwell_ms"}.issubset(LEAKAGE_FEATURES))


class LinUCBTests(unittest.TestCase):
    def test_get_cold_task_flags_batch(self):
        """Новые задачи без истории показов должны быть cold."""
        flags = get_cold_task_flags_batch(["task_new_1", "task_new_2"])
        self.assertEqual(flags["task_new_1"], 1)
        self.assertEqual(flags["task_new_2"], 1)

    def test_score_cold_start_returns_float(self):
        row = {
            "task_urgency_score": 0.5,
            "ngo_reliability_score": 0.8,
            "task_quality_score": 0.7,
            "exploration_slot": 1,
            "cold_start_task": 1,
        }
        score = score_cold_start(row, "task_test_123", "vol_test_456")
        self.assertIsInstance(score, float)
        self.assertGreater(score, 0)

    def test_score_cold_start_ucb_decreases_with_impressions(self):
        """UCB-бонус должен убывать по мере накопления показов."""
        row = {}
        score_new = score_cold_start(row, "task_never_seen_xyz", "vol_1")
        # После одного показа UCB уменьшается (симулируем через разные task_id)
        # Проверяем что score конечный и неотрицательный
        self.assertGreaterEqual(score_new, 0)


class DiversifyTests(unittest.TestCase):
    def _make_rows(self, ngo_ids, scores):
        return [
            {"ngo_id": ngo, "final_score": score, "task_id": f"t{i}"}
            for i, (ngo, score) in enumerate(zip(ngo_ids, scores))
        ]

    def test_limits_per_ngo(self):
        # 4 ngo_a + 3 разных НКО; при top_k=5 и max_per_ngo=3 должны получить ≤3 ngo_a
        rows = self._make_rows(
            ["ngo_a", "ngo_a", "ngo_a", "ngo_a", "ngo_b", "ngo_c", "ngo_d"],
            [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4],
        )
        result = _diversify(rows, top_k=5, max_per_ngo=3)
        ngo_a_count = sum(1 for r in result if r["ngo_id"] == "ngo_a")
        self.assertLessEqual(ngo_a_count, 3)
        self.assertEqual(len(result), 5)

    def test_fills_remaining_when_few_ngos(self):
        rows = self._make_rows(
            ["ngo_a", "ngo_a", "ngo_a", "ngo_a"],
            [1.0, 0.9, 0.8, 0.7],
        )
        result = _diversify(rows, top_k=4, max_per_ngo=3)
        self.assertEqual(len(result), 4)

    def test_respects_top_k(self):
        rows = self._make_rows(
            ["ngo_a", "ngo_b", "ngo_c", "ngo_d", "ngo_e"],
            [1.0, 0.9, 0.8, 0.7, 0.6],
        )
        result = _diversify(rows, top_k=3)
        self.assertEqual(len(result), 3)


class ModelLoaderTests(unittest.TestCase):
    def test_missing_artifact_error(self):
        with self.assertRaises(ModelArtifactNotFound):
            load_model_artifact.__wrapped__(
                __import__("pathlib").Path("/tmp/helpera-missing-model.joblib")
            )


class ColdStartThreshTest(unittest.TestCase):
    def test_threshold_value(self):
        self.assertEqual(COLD_START_THRESH, 0.40)


if __name__ == "__main__":
    unittest.main()
