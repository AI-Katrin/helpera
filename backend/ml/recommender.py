import math
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
    record_context,
    record_impressions,
    score_cold_start,
)
from .model_loader import load_model_artifact, predict_scores
from .normalization import safe_float
from .schemas import RecommendationResponse, RecommendedTask

CANDIDATE_POOL_SIZE = int(os.environ.get("HELPERA_CANDIDATE_POOL_SIZE", "200"))
# Правило 11: не более MAX_POPULAR_FRAC позиций в top-K могут занимать популярные задачи.
# Задача считается популярной, если application_pressure >= POPULAR_PRESSURE_THRESHOLD.
_MAX_POPULAR_FRAC = float(os.environ.get("HELPERA_MAX_POPULAR_FRAC", "0.6"))
_POPULAR_PRESSURE_THRESHOLD = float(os.environ.get("HELPERA_POPULAR_PRESSURE_THRESHOLD", "0.5"))
# Правило 12: lambda для MMR-re-ranking; 0 = чистый скор, 1 = чистое разнообразие.
_DIVERSITY_LAMBDA = float(os.environ.get("HELPERA_DIVERSITY_LAMBDA", "0.25"))


class RecommendationError(RuntimeError):
    pass


class VolunteerNotFound(RecommendationError):
    pass


def _parse_directions(row):
    raw = str(row.get("direction_work") or row.get("directions_clean") or "").strip()
    return {d.strip().lower() for d in raw.split(",") if d.strip()}


def _diversity_rerank(scored_rows, lambda_div=None):
    """
    Правило 12: MMR-style re-ranking для принудительного разнообразия тематик.
    На каждом шаге выбирает кандидата с максимальным:
      final_score - lambda_div * (1 если любое направление уже представлено, 0 иначе)
    lambda_div=0 → чистый скор, lambda_div=1 → чистое разнообразие.
    Порядок на выходе используется вместо исходного score-sorted для _diversify.
    """
    if lambda_div is None:
        lambda_div = _DIVERSITY_LAMBDA
    if not scored_rows or lambda_div <= 0:
        return list(scored_rows)
    remaining = list(scored_rows)
    selected = []
    covered = set()
    while remaining:
        best_idx = 0
        best_val = float("-inf")
        for i, row in enumerate(remaining):
            dirs = _parse_directions(row)
            penalty = lambda_div if dirs & covered else 0.0
            val = row["final_score"] - penalty
            if val > best_val:
                best_val = val
                best_idx = i
        chosen = remaining.pop(best_idx)
        selected.append(chosen)
        covered |= _parse_directions(chosen)
    return selected


def _diversify(ranked, top_k, max_per_ngo=MAX_TASKS_PER_NGO, max_per_direction=4, max_cold_tasks=2):
    """
    Ограничивает число задач в top-K по нескольким осям:
    - не более max_per_ngo задач от одной НКО;
    - не более max_per_direction по одному направлению;
    - не более max_cold_tasks cold-start задач (Правило 8);
    - не более ceil(top_k * MAX_POPULAR_FRAC) популярных задач (Правило 11).
    Популярная задача: application_pressure >= POPULAR_PRESSURE_THRESHOLD.
    """
    selected = []
    ngo_counts = {}
    dir_counts = {}
    cold_count = 0
    popular_count = 0
    max_popular = max(1, math.ceil(top_k * _MAX_POPULAR_FRAC))
    for row in ranked:
        ngo = row.get("ngo_id")
        direction = str(row.get("direction_work") or row.get("directions_clean") or "").strip().split(",")[0].strip().lower()
        is_cold = int(row.get("cold_start_task") or 0)
        is_popular = float(row.get("application_pressure") or 0) >= _POPULAR_PRESSURE_THRESHOLD
        ngo_ok = ngo_counts.get(ngo, 0) < max_per_ngo
        dir_ok = not direction or dir_counts.get(direction, 0) < max_per_direction
        cold_ok = not is_cold or cold_count < max_cold_tasks
        popular_ok = not is_popular or popular_count < max_popular
        if ngo_ok and dir_ok and cold_ok and popular_ok:
            selected.append(row)
            ngo_counts[ngo] = ngo_counts.get(ngo, 0) + 1
            if direction:
                dir_counts[direction] = dir_counts.get(direction, 0) + 1
            if is_cold:
                cold_count += 1
            if is_popular:
                popular_count += 1
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


def _make_fallback_hints(volunteer):
    """
    Правило 10: генерирует подсказки для волонтёра при нулевой выдаче.
    Анализирует профиль и возвращает до 3 конкретных рекомендаций.
    """
    hints = []
    vol_format = str(volunteer.get("format_clean") or volunteer.get("task_format") or "").strip()
    vol_city = str(volunteer.get("city_clean") or volunteer.get("city") or "").strip()
    vol_skills = str(volunteer.get("skills_clean") or volunteer.get("skills") or "").strip()
    vol_dirs = str(volunteer.get("directions_clean") or volunteer.get("help_directions") or "").strip()
    completeness = safe_float(volunteer.get("profile_completeness"), 0.0)

    if vol_format == "Оффлайн" and not vol_city:
        hints.append("Укажите ваш город — офлайн-задачи подбираются по региону")
    if vol_format == "Оффлайн":
        hints.append("Попробуйте добавить онлайн-формат участия — это расширит число доступных задач")
    if not vol_skills:
        hints.append("Добавьте навыки в профиль — система сможет точнее подобрать задачи")
    if not vol_dirs:
        hints.append("Укажите направления волонтёрства, которые вам интересны")
    if completeness < 0.6 and not hints:
        hints.append("Заполните профиль подробнее — чем больше данных, тем точнее подборка")
    if not hints:
        hints.append("Новые задачи появляются регулярно — загляните позже")
    return hints[:3]


def _ensure_exploration_slot(top_rows, ranked, top_k):
    """
    Правило 9: резервирует минимум один слот в top-K для cold-start задачи.
    Если диверсификация вытеснила все cold-задачи — заменяет последний элемент
    на лучшую cold-задачу из отсортированного ranked, которой ещё нет в выдаче.
    """
    has_cold = any(int(r.get("cold_start_task") or 0) for r in top_rows)
    if has_cold or len(top_rows) < top_k:
        return top_rows
    selected_ids = {r["task_id"] for r in top_rows}
    cold_candidates = [
        r for r in ranked
        if int(r.get("cold_start_task") or 0) and r["task_id"] not in selected_ids
    ]
    if not cold_candidates:
        return top_rows
    return top_rows[:-1] + [cold_candidates[0]]


class RecommendationService:
    def __init__(self, repository=None):
        self.repository = repository or CsvRecommendationRepository()

    def recommend_for_volunteer(self, volunteer_id, k=DEFAULT_TOP_K, hidden_task_ids=None):
        k = max(1, min(int(k or DEFAULT_TOP_K), MAX_TOP_K))
        volunteer = self.repository.get_volunteer(volunteer_id)
        if not volunteer:
            raise VolunteerNotFound(f"Volunteer not found: {volunteer_id}")

        all_tasks = self.repository.get_candidate_tasks(volunteer_id)
        if hidden_task_ids:
            all_tasks = [t for t in all_tasks if t.get("task_id") not in hidden_task_ids]
        if not all_tasks:
            # Правило 10: нулевая выдача — формируем подсказки по профилю
            hints = _make_fallback_hints(volunteer)
            return self._response(volunteer_id, k, [], None, fallback_mode="no_tasks", fallback_hints=hints)

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
            # Сохраняем признаковые векторы для онлайн-обновления θ при фидбеке
            for row in pair_rows:
                record_context(str(volunteer_id), str(row["task_id"]), row)
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
            if is_cold_volunteer:
                row["linucb_bonus"] = 0.0
                row["final_score"] = ml_score + row["business_adjustment"]
            else:
                row["linucb_bonus"] = linucb_bonus
                row["final_score"] = ml_score + linucb_bonus + row["business_adjustment"]
            row["reason"] = make_recommendation_reason(row)
            ranked.append(row)

        ranked.sort(key=lambda item: item["final_score"], reverse=True)
        self._add_match_percent(ranked)

        # Правило 12: MMR re-ranking — принудительное разнообразие тематик
        reranked = _diversity_rerank(ranked)

        # Правила 8, 11: hard-cap по НКО, направлению, cold-задачам, популярным задачам
        top_rows = _diversify(reranked, k)

        # Правило 9: гарантируем минимум один слот для cold-start задачи в top-K
        top_rows = _ensure_exploration_slot(top_rows, ranked, k)

        # Нулевая выдача: ослабляем диверсификацию, если результатов нет
        fallback_mode = None
        fallback_hints = []
        if not top_rows and ranked:
            top_rows = _diversify(ranked, k, max_per_ngo=k, max_per_direction=k)
            fallback_mode = "relaxed_diversity"
        elif not top_rows:
            # Правило 10: нет кандидатов — возвращаем подсказки
            fallback_mode = "no_tasks"
            fallback_hints = _make_fallback_hints(volunteer)
        if is_cold_volunteer:
            fallback_mode = fallback_mode or "cold_start"

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
                    linucb_bonus=round(row.get("linucb_bonus", 0.0), 6),
                    business_adjustment=round(row["business_adjustment"], 6),
                    final_score=round(row["final_score"], 6),
                    match_percent=row["match_percent"],
                    reason=row["reason"],
                    # Правило 13: флаг срочности для отображения на фронте
                    is_urgent=bool(row.get("task_critical_urgency") or safe_float(row.get("task_urgency_score")) >= 0.7),
                    # Задача показана преимущественно из-за UCB-бонуса (exploration), а не релевантности
                    is_exploration=row.get("linucb_bonus", 0.0) > 0.1 and row.get("cold_start_task", False),
                    payload=task.get("payload") or {},
                )
            )

        # Stage 4 feedback: записываем показы для LinUCB (сбор первичных сигналов)
        record_impressions([item.task_id for item in items], volunteer_id)

        # Правило 27: структурированный лог показов для дообучения модели.
        # Каждый показ фиксируется с позицией, скорами и session_id —
        # чтобы позже объединить с кликами/откликами по (vol, task, session_id).
        session_id = str(uuid.uuid4())
        try:
            from .event_logger import log_impression_batch
            log_impression_batch(session_id, volunteer_id, items)
        except Exception:
            pass

        cold_tasks_in_batch = sum(1 for row in top_rows if int(row.get("cold_start_task") or 0))
        return self._response(volunteer_id, k, items, model_artifact, fallback_mode, is_cold_volunteer, cold_tasks_in_batch, fallback_hints, session_id)

    def _add_match_percent(self, ranked_rows):
        if not ranked_rows:
            return
        # Используем ml_score (без UCB-бонуса) — чтобы процент отражал реальное
        # совпадение навыков, а не exploration-буст незнакомых задач
        scores = [row.get("ml_score", row["final_score"]) for row in ranked_rows]
        min_score = min(scores)
        max_score = max(scores)
        span = max_score - min_score
        for row in ranked_rows:
            base = row.get("ml_score", row["final_score"])
            if span <= 0:
                percent = 85
            else:
                percent = 55 + round(((base - min_score) / span) * 43)
            if row.get("eligible_for_recommendations") == 0:
                percent = min(percent, 35)
            row["match_percent"] = max(1, min(98, int(percent)))

    def _response(self, volunteer_id, k, items, model_artifact, fallback_mode=None, is_cold_start=False, cold_tasks_in_batch=0, fallback_hints=None, session_id=None):
        return RecommendationResponse(
            volunteer_id=str(volunteer_id),
            k=k,
            model_name=model_artifact.model_name if model_artifact else "CatBoost YetiRank",
            variant_name=model_artifact.variant_name if model_artifact else "CatBoost YetiRank + Business Rules",
            schema_version=model_artifact.schema_version if model_artifact else "helpera_recommendations_catboost_production_v1",
            recommendation_session_id=session_id or str(uuid.uuid4()),
            items=items,
            fallback_mode=fallback_mode,
            is_cold_start=is_cold_start,
            cold_tasks_in_batch=cold_tasks_in_batch,
            fallback_hints=fallback_hints or [],
        )
