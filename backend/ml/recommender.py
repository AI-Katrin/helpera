import os
import uuid

from .business_rules import business_adjustment, make_recommendation_reason
from .config import COLD_START_THRESH, DEFAULT_TOP_K, MAX_TASKS_PER_NGO, MAX_TOP_K
from .data_repository import CsvRecommendationRepository
from .embeddings import select_top_candidates
from .features import build_pairs, prepare_feature_rows
from .linucb import (
    get_cold_start_info,
    get_cold_task_flags_batch,
    record_impressions,
    score_cold_start,
)
from .model_loader import load_model_artifact, predict_scores
from .normalization import safe_float
from .schemas import RecommendationResponse, RecommendedTask

CANDIDATE_POOL_SIZE = int(os.environ.get("HELPERA_CANDIDATE_POOL_SIZE", "200"))


class RecommendationError(RuntimeError):
    pass


class VolunteerNotFound(RecommendationError):
    pass


def _diversify(ranked, top_k, max_per_ngo=MAX_TASKS_PER_NGO, max_per_direction=4):
    """
    Ограничивает не более max_per_ngo задач от одной НКО и max_per_direction
    задач по одному направлению в итоговом top-k.
    """
    selected = []
    ngo_counts = {}
    dir_counts = {}
    for row in ranked:
        ngo = row.get("ngo_id")
        direction = str(row.get("direction_work") or row.get("directions_clean") or "").strip().split(",")[0].strip().lower()
        ngo_ok = ngo_counts.get(ngo, 0) < max_per_ngo
        dir_ok = not direction or dir_counts.get(direction, 0) < max_per_direction
        if ngo_ok and dir_ok:
            selected.append(row)
            ngo_counts[ngo] = ngo_counts.get(ngo, 0) + 1
            if direction:
                dir_counts[direction] = dir_counts.get(direction, 0) + 1
        if len(selected) >= top_k:
            break
    # Если после диверсификации не хватает позиций — дополняем оставшимися
    if len(selected) < top_k:
        already = {id(r) for r in selected}
        for row in ranked:
            if id(row) not in already:
                selected.append(row)
            if len(selected) >= top_k:
                break
    return selected


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

        # Stage 1: Semantic candidate generation
        tasks, embedding_sims = select_top_candidates(volunteer, all_tasks, CANDIDATE_POOL_SIZE)

        # Определяем cold-start статус задач (batch) ДО построения признаков,
        # чтобы CatBoost видел правильный флаг cold_start_task.
        cold_task_flags = get_cold_task_flags_batch([t["task_id"] for t in tasks])

        is_cold_volunteer = (
            safe_float(volunteer.get("profile_completeness"), 0.5) < COLD_START_THRESH
        )

        ngos = self.repository.get_ngos_for_tasks(tasks)
        pair_rows = build_pairs(volunteer, tasks, ngos, embedding_sims, cold_task_flags)

        # Stage 2: CatBoost re-ranking (для тёплых) или LinUCB (для cold-start)
        model_artifact = load_model_artifact()
        feature_rows = prepare_feature_rows(pair_rows, model_artifact.feature_cols)

        if is_cold_volunteer:
            # Для cold-start волонтёров используем LinUCB вместо CatBoost
            ml_scores = [
                score_cold_start(row, row["task_id"], volunteer_id)
                for row in pair_rows
            ]
        else:
            ml_scores = predict_scores(
                model_artifact,
                feature_rows,
                [volunteer["volunteer_id"]] * len(feature_rows),
            )

        # Stage 3 + Stage 4: LinUCB exploration bonus + business rules
        task_by_id = {task["task_id"]: task for task in tasks}
        ranked = []
        for row, ml_score in zip(pair_rows, ml_scores):
            task_id = row["task_id"]
            is_cold_task, _, linucb_bonus = get_cold_start_info(task_id, volunteer_id)
            row["ml_score"] = ml_score
            row["cold_start_volunteer"] = int(is_cold_volunteer)
            # cold_start_task уже выставлен через cold_task_flags в build_pairs,
            # но синхронизируем со статистикой LinUCB для бизнес-правил
            row["cold_start_task"] = is_cold_task
            row["business_adjustment"] = business_adjustment(row)
            # Для cold-start волонтёра: score_cold_start уже включает UCB-бонус
            row["final_score"] = (
                ml_score + row["business_adjustment"]
                if is_cold_volunteer
                else ml_score + linucb_bonus + row["business_adjustment"]
            )
            row["reason"] = make_recommendation_reason(row)
            ranked.append(row)

        ranked.sort(key=lambda item: item["final_score"], reverse=True)
        self._add_match_percent(ranked)

        # Diversity post-processing: не более MAX_TASKS_PER_NGO задач от одной НКО
        top_rows = _diversify(ranked, k)

        # Нулевая выдача: ослабляем диверсификацию, если результатов нет
        fallback_mode = None
        if not top_rows and ranked:
            top_rows = _diversify(ranked, k, max_per_ngo=k, max_per_direction=k)
            fallback_mode = "relaxed_diversity"
        elif not top_rows:
            fallback_mode = "no_tasks"

        items = []
        for rank, row in enumerate(top_rows, start=1):
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

        # Stage 4 feedback: записываем показы для LinUCB
        record_impressions([item.task_id for item in items], volunteer_id)

        return self._response(volunteer_id, k, items, model_artifact, fallback_mode)

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

    def _response(self, volunteer_id, k, items, model_artifact, fallback_mode=None):
        return RecommendationResponse(
            volunteer_id=str(volunteer_id),
            k=k,
            model_name=model_artifact.model_name if model_artifact else "CatBoost YetiRank",
            variant_name=model_artifact.variant_name if model_artifact else "CatBoost YetiRank + Business Rules",
            schema_version=model_artifact.schema_version if model_artifact else "helpera_recommendations_catboost_production_v1",
            recommendation_session_id=str(uuid.uuid4()),
            items=items,
            fallback_mode=fallback_mode,
        )
