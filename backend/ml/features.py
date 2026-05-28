from datetime import date, datetime
import hashlib
import math

from .business_rules import is_eligible
from .config import COLD_START_THRESH, LEAKAGE_FEATURES
from .normalization import normalize_city, normalize_format, normalize_skills, normalize_text, safe_float, safe_int


_OUTCOME_COMPLETED = frozenset({"completed", "done", "finished"})
_OUTCOME_PARTIAL   = frozenset({"partial_done", "partial"})
_OUTCOME_CANCELLED = frozenset({"cancelled", "cancelled_by_volunteer", "volunteer_cancelled", "not_done"})


def outcome_label_from_status(status: str) -> int:
    """
    Правило 20: целевая переменная для обучения ранкера.
    2 = выполнено полностью, 1 = частично, 0 = отменено / не выполнено.
    """
    s = str(status or "").lower()
    if s in _OUTCOME_COMPLETED:
        return 2
    if s in _OUTCOME_PARTIAL:
        return 1
    return 0


def parse_date(value):
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def ratio(numerator, denominator):
    return numerator / denominator if denominator else 0.0


def stable_bucket(value, modulo):
    digest = hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % modulo


def build_pair_features(volunteer, task, ngo, embedding_sim=0.0, cold_start_task=0):
    vol_skills, vol_unknown = normalize_skills(volunteer.get("skills_clean") or volunteer.get("skills") or volunteer.get("skills_raw"))
    task_skills, task_unknown = normalize_skills(task.get("skills_clean") or task.get("useful_skills") or task.get("skills"))
    vol_dirs = set(normalize_text(x) for x in (volunteer.get("directions_clean") or volunteer.get("help_directions") or "").split(",") if x.strip())
    task_dirs = set(normalize_text(x) for x in (task.get("directions_clean") or task.get("direction_work") or "").split(",") if x.strip())
    vol_skill_set = set(vol_skills)
    task_skill_set = set(task_skills)
    intersection = vol_skill_set & task_skill_set
    union = vol_skill_set | task_skill_set

    vol_format = normalize_format(volunteer.get("format_clean") or volunteer.get("task_format"))
    task_format = normalize_format(task.get("format_clean") or task.get("participation_type") or task.get("format"))
    vol_city = normalize_city(volunteer.get("city_clean") or volunteer.get("city"))
    task_city = normalize_city(task.get("city_clean") or task.get("region") or task.get("city_raw"))

    today = date.today()
    created = parse_date(task.get("created_at")) or today
    # Правило 4: учитываем дату обновления задачи для task_is_new
    updated = parse_date(task.get("updated_at"))
    deadline = parse_date(task.get("deadline") or task.get("date_end"))
    days_to_deadline = max((deadline - today).days, 0) if deadline else 0
    deadline_passed = int(bool(deadline and deadline < today))
    capacity = max(safe_int(task.get("capacity"), 1), 1)
    current_applications = safe_int(task.get("current_applications"))
    task_is_full = int(current_applications >= capacity)
    application_pressure = round(ratio(current_applications, capacity), 4)
    # Правило 13: плавный временной коэффициент срочности.
    # Максимум 1.0 при ≤3 дня, далее экспоненциальный спад с полупериодом 14 дней.
    urgency = 0.0
    if deadline and not deadline_passed:
        if days_to_deadline <= 3:
            urgency = 1.0
        else:
            urgency = round(math.exp(-(days_to_deadline - 3) / 14), 4)

    description = " ".join(
        str(task.get(name) or "")
        for name in ("title", "about_task", "work_to_do", "useful_skills", "direction_work", "region", "participation_type")
    )
    quality = safe_float(task.get("task_quality_score"))
    if not quality:
        filled = sum(1 for name in ("title", "about_task", "work_to_do", "useful_skills", "direction_work", "date_end") if task.get(name))
        quality = round(filled / 6, 3)
    needs_ai_help = int(len(str(task.get("about_task") or "")) < 80 or quality < 0.45)

    # Правило 25: сложность задачи — комбинация числа навыков, объёма работы и срочности.
    # Чем сложнее задача, тем выше риск срыва у ненадёжного волонтёра.
    task_skill_count = len(task_skill_set)
    work_scope_len = len(str(task.get("work_to_do") or "").strip()) + len(str(task.get("about_task") or "").strip()) // 2
    skill_complexity  = min(1.0, task_skill_count / 5.0)        # 5+ навыков → максимум
    scope_complexity  = min(1.0, work_scope_len / 800.0)        # 800+ символов → максимум
    task_complexity_score = round(skill_complexity * 0.45 + scope_complexity * 0.35 + urgency * 0.20, 4)

    # Правило 25: пробел навыков — доля требуемых навыков, которых НЕТ у волонтёра.
    # 0.0 = волонтёр владеет всеми требуемыми навыками, 1.0 = не владеет ни одним.
    skill_gap_count = len(task_skill_set - vol_skill_set)
    skill_gap_ratio = round(ratio(skill_gap_count, len(task_skill_set)) if task_skill_set else 0.0, 4)
    # Относительная сложность: насколько ЭТОТ волонтёр не готов к ЭТОЙ задаче.
    # Высокая при сложной задаче И большом пробеле навыков.
    volunteer_complexity_mismatch = round(task_complexity_score * skill_gap_ratio, 4)

    row = {
        "volunteer_id": volunteer.get("volunteer_id"),
        "task_id": task.get("task_id"),
        "ngo_id": task.get("ngo_id"),
        "qid": volunteer.get("volunteer_id"),
        # Правило 20: для обучающей выборки label вычисляется из финального статуса заявки.
        # При инференсе остаётся 0 — CatBoost его игнорирует (не leakage при правильном pipeline).
        "label_relevance": outcome_label_from_status(volunteer.get("outcome_status") or ""),
        "skill_overlap_count": len(intersection),
        "skill_overlap_from_raw": len(intersection),
        "skill_jaccard": ratio(len(intersection), len(union)),
        "skill_jaccard_from_raw": ratio(len(intersection), len(union)),
        "skill_coverage": ratio(len(intersection), len(task_skill_set)),
        "skill_coverage_from_raw": ratio(len(intersection), len(task_skill_set)),
        "direction_overlap": len(vol_dirs & task_dirs),
        "format_match": int(bool(vol_format and task_format and (
            vol_format == task_format or task_format == "Смешанный"
        ))),
        "format_match_from_raw": int(bool(vol_format and task_format and (
            vol_format == task_format or task_format == "Смешанный"
        ))),
        "city_match": int(bool(vol_city and task_city and vol_city == task_city) or task_format == "Онлайн"),
        "embedding_cosine_sim": embedding_sim,
        "task_quality_score": quality,
        "task_quality_final": quality,
        "task_description_len": len(description),
        "task_age_days": max((today - created).days, 0),
        "days_to_deadline": days_to_deadline,
        "days_until_deadline": days_to_deadline,
        "deadline_passed": deadline_passed,
        "task_urgency_score": urgency,
        "task_critical_urgency": int(bool(deadline and not deadline_passed and days_to_deadline <= 3)),
        "task_is_new": int(
            (today - created).days <= 14
            or (updated is not None and (today - updated).days <= 14)
        ),
        "task_is_duplicate_candidate": safe_int(task.get("is_duplicate_candidate")),
        "duplicate_final_flag": safe_int(task.get("is_duplicate_candidate")),
        "duplicate_score_recomputed": safe_int(task.get("is_duplicate_candidate")),
        "capacity": capacity,
        "capacity_x": capacity,
        "capacity_y": capacity,
        "current_applications": current_applications,
        "current_applications_x": current_applications,
        "current_applications_y": current_applications,
        "application_pressure": application_pressure,
        "task_is_full": task_is_full,
        "task_needs_ai_help": needs_ai_help,
        # Правило 25: сложность задачи (0–1), пробел навыков и относительная сложность для пары
        "task_complexity_score": task_complexity_score,
        "task_skill_count": task_skill_count,
        "skill_gap_count": skill_gap_count,
        "skill_gap_ratio": skill_gap_ratio,
        "volunteer_complexity_mismatch": volunteer_complexity_mismatch,
        "volunteer_reliability_score": safe_float(volunteer.get("volunteer_reliability_score"), 0.5),
        "volunteer_reliability_score_x": safe_float(volunteer.get("volunteer_reliability_score"), 0.5),
        "volunteer_reliability_score_y": safe_float(volunteer.get("volunteer_reliability_score"), 0.5),
        "volunteer_cancel_rate": safe_float(volunteer.get("volunteer_cancel_rate")),
        "volunteer_cancel_rate_x": safe_float(volunteer.get("volunteer_cancel_rate")),
        "volunteer_cancel_rate_y": safe_float(volunteer.get("volunteer_cancel_rate")),
        # Правило 14: высокий риск срыва — надёжность < 0.25 ИЛИ срывы > 50 %
        "volunteer_high_risk": int(
            safe_float(volunteer.get("volunteer_reliability_score"), 0.5) < 0.25
            or safe_float(volunteer.get("volunteer_cancel_rate")) > 0.5
        ),
        "volunteer_active_tasks_count": safe_int(volunteer.get("active_tasks_count")),
        "volunteer_profile_completeness": safe_float(volunteer.get("profile_completeness")),
        "volunteer_availability_hours_week": safe_int(volunteer.get("availability_hours_week")),
        "age": safe_int(volunteer.get("age")),
        "availability_hours_week": safe_int(volunteer.get("availability_hours_week")),
        "profile_completeness": safe_float(volunteer.get("profile_completeness")),
        "active_tasks_count": safe_int(volunteer.get("active_tasks_count")),
        "is_overloaded": int(safe_int(volunteer.get("active_tasks_count")) >= 3),
        # Правило 16: приближение к лимиту 5 задач — дополнительный штраф
        "volunteer_nearly_overloaded": int(safe_int(volunteer.get("active_tasks_count")) >= 4),
        # Правило 20: средняя метка исхода 0–2 (2=выполнено, 1=частично, 0=отменено/срыв)
        # Нейтральное значение 1.0 при отсутствии истории: лучше, чем штрафовать новых.
        "volunteer_avg_outcome": safe_float(volunteer.get("volunteer_avg_outcome"), 1.0),
        # Правило 23: волонтёр хотя бы раз оставил расширенный отзыв — сигнал вовлечённости
        "volunteer_extended_review_flag": safe_int(volunteer.get("volunteer_extended_review_flag")),
        # Правило 24: средняя оценка волонтёра от НКО по завершённым задачам (0–1, нейтраль 0.7)
        "volunteer_review_avg_rating": safe_float(volunteer.get("volunteer_review_avg_rating"), 0.7),
        "ngo_reliability_score": safe_float(ngo.get("ngo_reliability_score"), 0.5),
        "ngo_reliability_score_ngo_table": safe_float(ngo.get("ngo_reliability_score"), 0.5),
        "ngo_avg_response_time_hours": safe_int(ngo.get("avg_response_time_hours"), 24),
        "avg_response_time_hours": safe_int(ngo.get("avg_response_time_hours"), 24),
        "ngo_complaint_rate": safe_float(ngo.get("complaint_rate")),
        "complaint_rate": safe_float(ngo.get("complaint_rate")),
        "ngo_response_penalty": int(safe_int(ngo.get("avg_response_time_hours"), 24) > 72),
        "ngo_slow_response_flag": int(safe_int(ngo.get("avg_response_time_hours"), 24) > 72),
        "ngo_complaint_flag": int(safe_float(ngo.get("complaint_rate")) > 0.18),
        "ngo_low_reliability_flag": int(safe_float(ngo.get("ngo_reliability_score"), 0.5) < 0.55),
        # Правило 15: непрерывная оценка скорости ответа НКО (1.0 — быстро, 0.0 — игнорирует)
        # Экспоненциальный спад от порога 24 ч, полупериод 48 ч.
        "ngo_response_score": round(math.exp(-max(0, safe_int(ngo.get("avg_response_time_hours"), 24) - 24) / 48), 4),
        # Флаг игнорирования: нет ответа более 5 дней — задачи понижаются в выдаче
        "ngo_ignoring_flag": int(safe_int(ngo.get("avg_response_time_hours"), 24) > 120),
        "vol_format_norm": vol_format,
        "task_format_norm": task_format,
        "vol_city_norm": vol_city,
        "task_city_norm": task_city,
        "cold_start_volunteer": int(safe_float(volunteer.get("profile_completeness"), 0.5) < COLD_START_THRESH),
        "cold_start_task": cold_start_task,
        # Правило 8: cold-задача всегда получает слот исследования; для тёплых — только 10% по хешу
        "exploration_slot": int(
            bool(cold_start_task)
            or (safe_int(task.get("current_applications")) == 0 and stable_bucket(task.get("task_id"), 10) == 0)
        ),
        "task_popularity_score": application_pressure,
        "publication_status": task.get("publication_status") or "published",
        "is_published": int(str(task.get("publication_status") or "published").lower() == "published"),
        "vol_unknown_skill_count": len(vol_unknown),
        "task_unknown_skill_count": len(task_unknown),
        "vol_skills_unknown": vol_unknown,
        "task_skills_unknown": task_unknown,
    }
    row["eligible_for_recommendations"] = is_eligible(row)
    return row


def build_pairs(volunteer, tasks, ngos, embedding_sims=None, cold_task_flags=None):
    sims = embedding_sims or {}
    flags = cold_task_flags or {}
    return [
        build_pair_features(
            volunteer,
            task,
            ngos.get(task.get("ngo_id"), {}),
            sims.get(task.get("task_id"), 0.0),
            cold_start_task=flags.get(task.get("task_id"), 0),
        )
        for task in tasks
    ]


def prepare_feature_rows(rows, feature_cols):
    missing = [col for col in feature_cols if col not in rows[0]] if rows else []
    if missing:
        raise ValueError(f"В данных для recommendations не хватает признаков: {missing}")
    clean_rows = []
    for row in rows:
        clean_row = {}
        for col in feature_cols:
            value = row.get(col)
            if isinstance(value, float) and math.isinf(value):
                value = None
            clean_row[col] = value
        clean_rows.append(clean_row)
    leakage = [col for col in feature_cols if col in LEAKAGE_FEATURES]
    if leakage:
        raise ValueError(f"Артефакт содержит leakage-признаки: {leakage}")
    return clean_rows
