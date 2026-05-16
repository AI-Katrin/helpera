import os
import uuid

from .business_rules import business_adjustment, make_recommendation_reason
from .config import DEFAULT_TOP_K, MAX_TOP_K
from .data_repository import CsvRecommendationRepository
from .embeddings import select_top_candidates
from .features import build_pairs, prepare_feature_rows
from .linucb import get_cold_start_info, record_impressions
from .model_loader import load_model_artifact, predict_scores
from .schemas import RecommendationResponse, RecommendedTask

CANDIDATE_POOL_SIZE = int(os.environ.get("HELPERA_CANDIDATE_POOL_SIZE", "200"))


class RecommendationError(RuntimeError):
    pass


class VolunteerNotFound(RecommendationError):
    pass


class RecommendationService:
    def __init__(self, repository=None):
        self.repository = repository or CsvRecommendationRepository()

    def recommend_for_volunteer(self, volunteer_id, k=DEFAULT_TOP_K):
        k = max(1, min(int(k or DEFAULT_TOP_K), MAX_TOP_K))
        volunteer = self.repository.get_volunteer(volunteer_id)
        if not volunteer:
            raise VolunteerNotFound(f"Volunteer not found: {volunteer_id}")

        all_tasks = self.repository.get_candidate_tasks(volunteer_id)
        if not all_tasks:
            return self._response(volunteer_id, k, [], None)

        # Stage 1: semantic embedding candidate generation
        tasks, embedding_sims = select_top_candidates(volunteer, all_tasks, CANDIDATE_POOL_SIZE)

        # Stage 2: CatBoost re-ranking
        ngos = self.repository.get_ngos_for_tasks(tasks)
        pair_rows = build_pairs(volunteer, tasks, ngos, embedding_sims)
        model_artifact = load_model_artifact()
        feature_rows = prepare_feature_rows(pair_rows, model_artifact.feature_cols)
        ml_scores = predict_scores(model_artifact, feature_rows, [volunteer["volunteer_id"]] * len(feature_rows))

        # Stage 3: LinUCB cold-start bonus + business adjustment
        ranked = []
        task_by_id = {task["task_id"]: task for task in tasks}
        for row, ml_score in zip(pair_rows, ml_scores):
            row["ml_score"] = ml_score
            is_cold_task, is_cold_vol, linucb_bonus = get_cold_start_info(row["task_id"], volunteer_id)
            row["cold_start_task"] = is_cold_task
            row["cold_start_volunteer"] = is_cold_vol
            row["business_adjustment"] = business_adjustment(row)
            row["final_score"] = row["ml_score"] + row["business_adjustment"] + linucb_bonus
            row["reason"] = make_recommendation_reason(row)
            ranked.append(row)

        ranked.sort(key=lambda item: item["final_score"], reverse=True)
        self._add_match_percent(ranked)

        items = []
        for rank, row in enumerate(ranked[:k], start=1):
            task = task_by_id[row["task_id"]]
            items.append(
                RecommendedTask(
                    rank=rank,
                    task_id=task["task_id"],
                    ngo_id=task["ngo_id"],
                    title=task.get("title") or "Задача без названия",
                    about_task=task.get("about_task") or task.get("description") or "",
                    work_to_do=task.get("work_to_do") or "",
                    useful_skills=task.get("useful_skills") or task.get("skills") or "",
                    direction_work=task.get("direction_work") or task.get("directions_clean") or "",
                    region=task.get("region") or task.get("city_clean") or "",
                    date_start=task.get("date_start") or "",
                    date_end=task.get("date_end") or task.get("deadline") or "",
                    participation_type=task.get("participation_type") or task.get("format") or "",
                    ngo_name=task.get("ngo_name") or "НКО",
                    ml_score=round(row["ml_score"], 6),
                    business_adjustment=round(row["business_adjustment"], 6),
                    final_score=round(row["final_score"], 6),
                    match_percent=row["match_percent"],
                    reason=row["reason"],
                    payload=task.get("payload") or {},
                )
            )

        # Stage 4: record impressions for LinUCB feedback loop
        record_impressions([item.task_id for item in items], volunteer_id)

        return self._response(volunteer_id, k, items, model_artifact)

    def _add_match_percent(self, ranked_rows):
        if not ranked_rows:
            return
        scores = [row["final_score"] for row in ranked_rows]
        min_score = min(scores)
        max_score = max(scores)
        span = max_score - min_score
        for row in ranked_rows:
            if span <= 0:
                percent = 85
            else:
                percent = 55 + round(((row["final_score"] - min_score) / span) * 43)
            if row.get("eligible_for_recommendations") == 0:
                percent = min(percent, 35)
            row["match_percent"] = max(1, min(98, int(percent)))

    def _response(self, volunteer_id, k, items, model_artifact):
        return RecommendationResponse(
            volunteer_id=str(volunteer_id),
            k=k,
            model_name=model_artifact.model_name if model_artifact else "CatBoost YetiRank",
            variant_name=model_artifact.variant_name if model_artifact else "CatBoost YetiRank + Business Rules",
            schema_version=model_artifact.schema_version if model_artifact else "helpera_recommendations_catboost_production_v1",
            recommendation_session_id=str(uuid.uuid4()),
            items=items,
        )
