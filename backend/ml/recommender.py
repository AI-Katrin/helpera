import math
import os
import re
import uuid

from .business_rules import business_adjustment, make_recommendation_reason
from .config import COLD_START_THRESH, DEFAULT_TOP_K, MAX_TASKS_PER_NGO, MAX_TOP_K
from .data_repository import CsvRecommendationRepository
from .embeddings import select_top_candidates
from .features import build_pairs, prepare_feature_rows
from .linucb import (
    get_cold_start_info,
    get_cold_task_flags_batch,
    is_cold_start_volunteer,
    record_context,
    record_impressions,
)
from .model_loader import load_model_artifact, predict_scores
from .normalization import normalize_format, safe_float, safe_int
from .schemas import RecommendationResponse, RecommendedTask

CANDIDATE_POOL_SIZE = int(os.environ.get("HELPERA_CANDIDATE_POOL_SIZE", "200"))
# Exploration slots: cold volunteer gets more LinUCB slots than warm
_EXPLORATION_SLOTS_COLD = int(os.environ.get("HELPERA_EXPLORATION_SLOTS_COLD", "2"))
_EXPLORATION_SLOTS_WARM = int(os.environ.get("HELPERA_EXPLORATION_SLOTS_WARM", "1"))
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


def _norm_title(title: str) -> str:
    t = str(title or "").lower().strip()
    return " ".join(re.sub(r"[^а-яёa-z0-9]", " ", t).split()[:6])


def _diversify(ranked, top_k, max_per_ngo=MAX_TASKS_PER_NGO, max_per_direction=4, max_cold_tasks=2):
    """
    Ограничивает число задач в top-K по нескольким осям:
    - не более 1 задачи с одинаковым заголовком (только для малых k ≤ 20);
    - не более max_per_ngo задач от одной НКО;
    - не более max_per_direction по одному направлению;
    - не более max_cold_tasks cold-start задач (Правило 8);
    - не более ceil(top_k * MAX_POPULAR_FRAC) популярных задач (Правило 11).
    Популярная задача: application_pressure >= POPULAR_PRESSURE_THRESHOLD.
    """
    # При большом k (каталог) дедупликация по заголовку не применяется —
    # пользователь должен видеть все задачи. При малом k (рекомендации) ограничиваем 1 per title.
    # Малые k (рекомендации): 1 задача на заголовок — строгое разнообразие.
    # Большие k (каталог): не более 2 — видно разные НКО с похожей задачей, но без 5+ повторов.
    max_per_title = 1 if top_k <= 20 else 2
    selected = []
    seen_titles: dict[str, int] = {}
    ngo_counts = {}
    dir_counts = {}
    cold_count = 0
    popular_count = 0
    max_popular = max(1, math.ceil(top_k * _MAX_POPULAR_FRAC))
    for row in ranked:
        ngo = row.get("ngo_id")
        title_key = _norm_title(row.get("title") or "")
        direction = str(row.get("direction_work") or row.get("directions_clean") or "").strip().split(",")[0].strip().lower()
        is_cold = int(row.get("cold_start_task") or 0)
        is_popular = float(row.get("application_pressure") or 0) >= _POPULAR_PRESSURE_THRESHOLD
        title_ok = not title_key or seen_titles.get(title_key, 0) < max_per_title
        ngo_ok = ngo_counts.get(ngo, 0) < max_per_ngo
        dir_ok = not direction or dir_counts.get(direction, 0) < max_per_direction
        cold_ok = not is_cold or cold_count < max_cold_tasks
        popular_ok = not is_popular or popular_count < max_popular
        if title_ok and ngo_ok and dir_ok and cold_ok and popular_ok:
            selected.append(row)
            if title_key:
                seen_titles[title_key] = seen_titles.get(title_key, 0) + 1
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


def _ensure_exploration_slot(top_rows, ranked, top_k, min_slots=1):
    """
    Правило 9: резервирует минимум min_slots слотов в top-K для cold-start задач.
    Для холодного волонтёра min_slots=2, для тёплого min_slots=1.
    """
    current_cold = sum(1 for r in top_rows if int(r.get("cold_start_task") or 0))
    needed = min_slots - current_cold
    if needed <= 0 or len(top_rows) < top_k:
        return top_rows
    selected_ids = {r["task_id"] for r in top_rows}
    cold_candidates = [
        r for r in ranked
        if int(r.get("cold_start_task") or 0) and r["task_id"] not in selected_ids
    ]
    result = list(top_rows)
    for candidate in cold_candidates[:needed]:
        result = result[:-1] + [candidate]
    return result


class RecommendationService:
    def __init__(self, repository=None):
        self.repository = repository or CsvRecommendationRepository()

    def recommend_for_volunteer(self, volunteer_id, k=DEFAULT_TOP_K, hidden_task_ids=None):
        k = max(1, min(int(k or DEFAULT_TOP_K), MAX_TOP_K))
        volunteer = self.repository.get_volunteer(volunteer_id)
        if not volunteer:
            raise VolunteerNotFound(f"Volunteer not found: {volunteer_id}")

        # Early exit: волонтёр уже ведёт 5+ задач — новые недоступны
        if safe_int(volunteer.get("active_tasks_count")) >= 5:
            hints = ["Вы уже ведёте максимальное число задач (5). Завершите одну из активных, чтобы взять новую."]
            return self._response(volunteer_id, k, [], None, fallback_mode="overloaded", fallback_hints=hints)

        all_tasks = self.repository.get_candidate_tasks(volunteer_id)
        if hidden_task_ids:
            all_tasks = [t for t in all_tasks if t.get("task_id") not in hidden_task_ids]

        # Фильтр формата до Stage 1: волонтёр хочет только онлайн, задача только оффлайн
        vol_fmt = normalize_format(volunteer.get("format_clean") or volunteer.get("task_format") or "")
        if vol_fmt == "Онлайн":
            all_tasks = [
                t for t in all_tasks
                if normalize_format(
                    t.get("format_clean") or t.get("participation_type") or t.get("format") or ""
                ) != "Оффлайн"
            ]

        if not all_tasks:
            # Правило 10: нулевая выдача — формируем подсказки по профилю
            hints = _make_fallback_hints(volunteer)
            return self._response(volunteer_id, k, [], None, fallback_mode="no_tasks", fallback_hints=hints)

        # Stage 1: Semantic candidate generation
        tasks, embedding_sims = select_top_candidates(volunteer, all_tasks, CANDIDATE_POOL_SIZE)

        # Определяем cold-start статус задач (batch) ДО построения признаков,
        # чтобы CatBoost видел правильный флаг cold_start_task.
        cold_task_flags = get_cold_task_flags_batch([t["task_id"] for t in tasks])

        is_cold_volunteer = is_cold_start_volunteer(str(volunteer_id))

        ngos = self.repository.get_ngos_for_tasks(tasks)
        pair_rows = build_pairs(volunteer, tasks, ngos, embedding_sims, cold_task_flags)

        # Stage 2: CatBoost re-ranking для всех волонтёров
        model_artifact = load_model_artifact()
        feature_rows = prepare_feature_rows(pair_rows, model_artifact.feature_cols)
        ml_scores = predict_scores(
            model_artifact,
            feature_rows,
            [volunteer["volunteer_id"]] * len(feature_rows),
        )

        # Stage 3: LinUCB exploration bonus + business rules
        # Холодный волонтёр получает тот же CatBoost-скор, но больше exploration слотов.
        # Сохраняем контекст для cold-задач, чтобы LinUCB θ обновлялся из фидбека.
        task_by_id = {task["task_id"]: task for task in tasks}
        ranked = []
        for row, ml_score in zip(pair_rows, ml_scores):
            task_id = row["task_id"]
            is_cold_task, _, linucb_bonus = get_cold_start_info(task_id, volunteer_id)
            row["ml_score"] = ml_score
            row["cold_start_volunteer"] = int(is_cold_volunteer)
            row["cold_start_task"] = is_cold_task
            row["business_adjustment"] = business_adjustment(row)
            row["linucb_bonus"] = linucb_bonus
            row["final_score"] = ml_score + linucb_bonus + row["business_adjustment"]
            row["reason"] = make_recommendation_reason(row)
            ranked.append(row)
            if is_cold_task:
                record_context(str(volunteer_id), str(task_id), row)

        ranked.sort(key=lambda item: item["final_score"], reverse=True)
        self._add_match_percent(ranked)

        # Правило 12: MMR re-ranking — принудительное разнообразие тематик
        reranked = _diversity_rerank(ranked)

        # Правила 8, 11: hard-cap по НКО, направлению, cold-задачам, популярным задачам
        exploration_slots = _EXPLORATION_SLOTS_COLD if is_cold_volunteer else _EXPLORATION_SLOTS_WARM
        top_rows = _diversify(reranked, k, max_cold_tasks=exploration_slots)

        # Правило 9: гарантируем минимум exploration_slots для cold задач в top-K
        top_rows = _ensure_exploration_slot(top_rows, ranked, k, min_slots=exploration_slots)

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
                    date_end=task.get("date_end") or "",
                    participation_type=task.get("participation_type") or task.get("format") or "",
                    ngo_name=task.get("ngo_name") or "НКО",
                    ml_score=round(row["ml_score"], 6),
                    linucb_bonus=round(row.get("linucb_bonus", 0.0), 6),
                    business_adjustment=round(row["business_adjustment"], 6),
                    final_score=round(row["final_score"], 6),
                    match_percent=row["match_percent"],
                    reason=row["reason"],
                    # Правило 13: флаг срочности для отображения на фронте
                    is_urgent=bool(row.get("task_critical_urgency")),
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
