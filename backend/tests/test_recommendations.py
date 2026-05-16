import unittest

from backend.ml.business_rules import business_adjustment, make_recommendation_reason
from backend.ml.config import LEAKAGE_FEATURES
from backend.ml.data_repository import CsvRecommendationRepository
from backend.ml.features import build_pairs, prepare_feature_rows
from backend.ml.model_loader import ModelArtifactNotFound, load_model_artifact


class RecommendationTests(unittest.TestCase):
    def test_business_adjustment_rewards_and_penalizes(self):
        good = {
            "task_urgency_score": 1,
            "ngo_reliability_score": 0.9,
            "volunteer_reliability_score": 0.8,
            "task_quality_score": 0.9,
            "eligible_for_recommendations": 1,
        }
        bad = {
            "complaint_rate": 0.5,
            "task_is_duplicate_candidate": 1,
            "is_overloaded": 1,
            "eligible_for_recommendations": 0,
        }
        self.assertGreater(business_adjustment(good), 0)
        self.assertLess(business_adjustment(bad), -5)

    def test_feature_order_and_leakage_guard(self):
        repo = CsvRecommendationRepository()
        volunteer = next(iter(repo.volunteers().values()))
        tasks = repo.get_candidate_tasks(volunteer["volunteer_id"])[:2]
        rows = build_pairs(volunteer, tasks, repo.get_ngos_for_tasks(tasks))
        feature_cols = ["skill_overlap_count", "skill_jaccard", "format_match", "city_match"]
        prepared = prepare_feature_rows(rows, feature_cols)
        self.assertEqual(list(prepared[0].keys()), feature_cols)
        with self.assertRaises(ValueError):
            prepare_feature_rows(rows, ["skill_overlap_count", "clicked"])
        self.assertTrue({"clicked", "dwell_ms"}.issubset(LEAKAGE_FEATURES))

    def test_reason_format(self):
        reason = make_recommendation_reason({
            "skill_overlap_count": 1,
            "format_match": 1,
            "task_quality_score": 0.8,
            "business_adjustment": 0.2,
        })
        self.assertTrue(reason.startswith("Рекомендация:"))
        self.assertIn("подходит по навыкам", reason)

    def test_missing_artifact_error(self):
        with self.assertRaises(ModelArtifactNotFound):
            load_model_artifact.__wrapped__(__import__("pathlib").Path("/tmp/helpera-missing-model.joblib"))


if __name__ == "__main__":
    unittest.main()
