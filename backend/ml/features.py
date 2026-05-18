from datetime import date, datetime
import hashlib
import math

from .business_rules import is_eligible
from .config import COLD_START_THRESH, LEAKAGE_FEATURES
from .normalization import normalize_city, normalize_format, normalize_skills, normalize_text, safe_float, safe_int


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
    deadline = parse_date(task.get("deadline") or task.get("date_end"))
    days_to_deadline = max((deadline - today).days, 0) if deadline else 0
    deadline_passed = int(bool(deadline and deadline < today))
    capacity = max(safe_int(task.get("capacity"), 1), 1)
    current_applications = safe_int(task.get("current_applications"))
    task_is_full = int(current_applications >= capacity)
    application_pressure = round(ratio(current_applications, capacity), 4)
    urgency = 0.0
    if deadline:
        urgency = 1.0 if days_to_deadline <= 7 else 0.6 if days_to_deadline <= 21 else 0.2

    description = " ".join(
        str(task.get(name) or "")
        for name in ("title", "about_task", "work_to_do", "useful_skills", "direction_work", "region", "participation_type")
    )
    quality = safe_float(task.get("task_quality_score"))
    if not quality:
        filled = sum(1 for name in ("title", "about_task", "work_to_do", "useful_skills", "direction_work", "date_end") if task.get(name))
        quality = round(filled / 6, 3)
    needs_ai_help = int(len(str(task.get("about_task") or "")) < 80 or quality < 0.45)

    row = {
        "volunteer_id": volunteer.get("volunteer_id"),
        "task_id": task.get("task_id"),
        "ngo_id": task.get("ngo_id"),
        "qid": volunteer.get("volunteer_id"),
        "label_relevance": 0,
        "skill_overlap_count": len(intersection),
        "skill_overlap_from_raw": len(intersection),
        "skill_jaccard": ratio(len(intersection), len(union)),
        "skill_jaccard_from_raw": ratio(len(intersection), len(union)),
        "skill_coverage": ratio(len(intersection), len(task_skill_set)),
        "skill_coverage_from_raw": ratio(len(intersection), len(task_skill_set)),
        "direction_overlap": len(vol_dirs & task_dirs),
        "format_match": int(bool(vol_format and task_format and vol_format == task_format)),
        "format_match_from_raw": int(bool(vol_format and task_format and vol_format == task_format)),
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
        "task_is_new": int((today - created).days <= 14),
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
        "volunteer_reliability_score": safe_float(volunteer.get("volunteer_reliability_score"), 0.5),
        "volunteer_reliability_score_x": safe_float(volunteer.get("volunteer_reliability_score"), 0.5),
        "volunteer_reliability_score_y": safe_float(volunteer.get("volunteer_reliability_score"), 0.5),
        "volunteer_cancel_rate": safe_float(volunteer.get("volunteer_cancel_rate")),
        "volunteer_cancel_rate_x": safe_float(volunteer.get("volunteer_cancel_rate")),
        "volunteer_cancel_rate_y": safe_float(volunteer.get("volunteer_cancel_rate")),
        "volunteer_active_tasks_count": safe_int(volunteer.get("active_tasks_count")),
        "volunteer_profile_completeness": safe_float(volunteer.get("profile_completeness")),
        "volunteer_availability_hours_week": safe_int(volunteer.get("availability_hours_week")),
        "age": safe_int(volunteer.get("age")),
        "availability_hours_week": safe_int(volunteer.get("availability_hours_week")),
        "profile_completeness": safe_float(volunteer.get("profile_completeness")),
        "active_tasks_count": safe_int(volunteer.get("active_tasks_count")),
        "is_overloaded": int(safe_int(volunteer.get("active_tasks_count")) >= 3),
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
        "cold_start_volunteer": int(safe_float(volunteer.get("profile_completeness"), 0.5) < COLD_START_THRESH),
        "cold_start_task": cold_start_task,
        "exploration_slot": int((safe_int(task.get("current_applications")) == 0) and (stable_bucket(task.get("task_id"), 10) == 0)),
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
