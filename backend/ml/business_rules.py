from .normalization import safe_float, safe_int


def get_value(row, names, default=0):
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return default


def is_eligible(row):
    if str(row.get("publication_status") or "published").lower() not in {"published", "active"}:
        return 0
    if safe_int(row.get("deadline_passed"), 0):
        return 0
    if safe_int(row.get("task_is_full"), 0):
        return 0
    return 1


def business_adjustment(row):
    adj = 0.0
    adj += 0.20 * safe_float(get_value(row, ["task_urgency_score"], 0))
    adj += 0.12 * safe_float(get_value(row, ["exploration_slot"], 0))
    adj += 0.20 * safe_float(get_value(row, ["ngo_reliability_score"], 0))
    adj += 0.15 * safe_float(get_value(row, ["volunteer_reliability_score"], 0))
    adj += 0.10 * safe_float(get_value(row, ["task_quality_final", "task_quality_score"], 0))

    adj -= 0.15 * safe_float(get_value(row, ["volunteer_cancel_rate"], 0))
    adj -= 0.12 * safe_float(get_value(row, ["application_pressure"], 0))
    adj -= 0.20 * safe_float(get_value(row, ["complaint_rate", "ngo_complaint_rate"], 0))
    adj -= 0.15 * safe_float(get_value(row, ["duplicate_final_flag", "task_is_duplicate_candidate"], 0))
    adj -= 0.20 * safe_float(get_value(row, ["task_needs_ai_help"], 0))
    adj -= 0.10 * safe_float(get_value(row, ["is_overloaded"], 0))
    adj -= 5.0 * (1 - safe_int(get_value(row, ["eligible_for_recommendations"], 1), 1))
    return round(adj, 6)


def make_recommendation_reason(row):
    reasons = []
    if safe_float(get_value(row, ["skill_overlap_from_raw", "skill_overlap_count"], 0)) > 0:
        reasons.append("подходит по навыкам")
    if safe_int(get_value(row, ["format_match_from_raw", "format_match"], 0), 0) == 1:
        reasons.append("совпадает формат участия")
    if safe_int(row.get("city_match"), 0) == 1:
        reasons.append("совпадает город или регион")
    if safe_float(get_value(row, ["task_quality_final", "task_quality_score"], 0)) >= 0.7:
        reasons.append("качественно описана задача")
    if safe_float(row.get("business_adjustment"), 0) > 0:
        reasons.append("есть положительные продуктовые факторы")
    if not reasons:
        reasons.append("есть базовое соответствие профиля и задачи")
    return "Рекомендация: " + ", ".join(reasons) + "."
