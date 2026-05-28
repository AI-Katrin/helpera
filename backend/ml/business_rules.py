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

    # Правило 6: жёсткие фильтры по формату, региону и доступности
    vol_fmt = str(row.get("vol_format_norm") or "").strip()
    task_fmt = str(row.get("task_format_norm") or "").strip()
    vol_city = str(row.get("vol_city_norm") or "").strip()
    task_city = str(row.get("task_city_norm") or "").strip()

    # Формат: волонтёр хочет только онлайн, а задача требует оффлайн-присутствия
    if vol_fmt == "Онлайн" and task_fmt == "Оффлайн":
        return 0

    # Регион: задача требует физического присутствия, оба города известны и не совпадают
    if task_fmt in ("Оффлайн", "Смешанный") and vol_city and task_city and not safe_int(row.get("city_match"), 1):
        return 0

    # Доступность: волонтёр уже ведёт ≥5 активных задач — недоступен для новых
    if safe_int(row.get("active_tasks_count")) >= 5:
        return 0

    return 1


def business_adjustment(row):
    adj = 0.0
    # Повышающие корректировки
    # Правило 13: временной коэффициент срочности
    adj += 0.20 * safe_float(get_value(row, ["task_urgency_score"], 0))
    adj += 0.10 * safe_float(get_value(row, ["task_critical_urgency"], 0))
    adj += 0.20 * safe_float(get_value(row, ["ngo_reliability_score"], 0))
    adj += 0.15 * safe_float(get_value(row, ["volunteer_reliability_score"], 0))
    # Правило 20: средняя метка исхода масштабируется к [0, 1] (делим на 2) — буст за стабильное качество
    adj += 0.08 * (safe_float(get_value(row, ["volunteer_avg_outcome"], 1.0)) / 2.0)
    # Правило 23: волонтёр с историей расширенных отзывов — вовлечённый, даём приоритет в подборке
    adj += 0.04 * safe_float(get_value(row, ["volunteer_extended_review_flag"], 0))
    # Правило 24: высокие оценки от НКО (>0.7) дают дополнительный буст надёжности
    review_rating = safe_float(get_value(row, ["volunteer_review_avg_rating"], 0.7))
    adj += 0.06 * max(0.0, review_rating - 0.5)
    adj += 0.10 * safe_float(get_value(row, ["task_quality_final", "task_quality_score"], 0))
    adj += 0.12 * safe_float(get_value(row, ["exploration_slot"], 0))
    adj += 0.08 * safe_float(get_value(row, ["cold_start_task"], 0))
    # Понижающие корректировки
    # Правило 14: квадратичный штраф за частые срывы (мягко при низких, жёстко при высоких)
    cancel_rate = safe_float(get_value(row, ["volunteer_cancel_rate"], 0))
    adj -= 0.30 * (cancel_rate ** 2)
    adj -= 0.15 * safe_float(get_value(row, ["volunteer_high_risk"], 0))
    adj -= 0.12 * safe_float(get_value(row, ["application_pressure"], 0))
    adj -= 0.20 * safe_float(get_value(row, ["complaint_rate", "ngo_complaint_rate"], 0))
    # Правило 15: непрерывный штраф за медленный ответ (заменяет бинарный ngo_response_penalty)
    adj -= 0.20 * (1.0 - safe_float(get_value(row, ["ngo_response_score"], 1.0)))
    adj -= 0.10 * safe_float(get_value(row, ["ngo_ignoring_flag"], 0))
    adj -= 0.15 * safe_float(get_value(row, ["duplicate_final_flag", "task_is_duplicate_candidate"], 0))
    # Правило 16: градуированный штраф за нагрузку (3+ задачи → −0.08, 4+ → ещё −0.12, 5+ → hard-block)
    adj -= 0.08 * safe_float(get_value(row, ["is_overloaded"], 0))
    adj -= 0.12 * safe_float(get_value(row, ["volunteer_nearly_overloaded"], 0))
    # Правило 14: составное — высокий риск + сложная качественная задача
    reliability = safe_float(get_value(row, ["volunteer_reliability_score"], 0.5))
    quality = safe_float(get_value(row, ["task_quality_final", "task_quality_score"], 0))
    if safe_int(get_value(row, ["volunteer_high_risk"], 0)) and quality > 0.6:
        adj -= 0.20
    elif reliability < 0.4 and quality > 0.7:
        adj -= 0.15
    # Правило 25: ненадёжному волонтёру понижаем сложные задачи — снижение вероятности срыва.
    # Сложность (task_complexity_score) = число навыков + объём работы + срочность.
    # Mismatch (volunteer_complexity_mismatch) = complexity × доля навыков, которых нет у волонтёра.
    complexity = safe_float(get_value(row, ["task_complexity_score"], 0))
    mismatch   = safe_float(get_value(row, ["volunteer_complexity_mismatch"], 0))
    is_unreliable = reliability < 0.45 or safe_float(get_value(row, ["volunteer_cancel_rate"], 0)) > 0.30
    is_high_risk  = safe_int(get_value(row, ["volunteer_high_risk"], 0))
    # Уровень 3 — высокий риск (reliability < 0.25 или cancel_rate > 50 %)
    if is_high_risk:
        if complexity > 0.80:
            adj -= 0.35   # очень сложная + критический риск → жёсткий штраф
        elif complexity > 0.65:
            adj -= 0.22   # сложная + высокий риск
        elif complexity > 0.45:
            adj -= 0.10   # умеренно сложная + высокий риск → мягкий штраф
    # Уровень 2 — умеренная ненадёжность (reliability < 0.45 или cancel_rate > 30 %)
    elif is_unreliable:
        if complexity > 0.65:
            adj -= 0.12   # сложная + ненадёжный → умеренный штраф
        elif complexity > 0.45:
            adj -= 0.06   # умеренно сложная + ненадёжный → мягкий штраф
    # Дополнительный штраф за навыковый пробел при сложной задаче (работает независимо от надёжности):
    # при mismatch=0.6 → −0.048, при mismatch=1.0 → −0.08
    if mismatch > 0.50:
        adj -= 0.08 * mismatch
    # Жёсткий фильтр
    adj -= 5.0 * (1 - safe_int(get_value(row, ["eligible_for_recommendations"], 1), 1))
    return round(adj, 6)


def make_recommendation_reason(row):
    reasons = []
    urgency = safe_float(get_value(row, ["task_urgency_score"], 0))
    # Правило 13: срочность идёт первым — самый важный сигнал для волонтёра
    if safe_int(get_value(row, ["task_critical_urgency"], 0)):
        reasons.append("осталось менее 3 дней — задача требует срочного волонтёра")
    elif urgency >= 0.6:
        reasons.append("срок выполнения приближается")
    if safe_float(get_value(row, ["skill_overlap_from_raw", "skill_overlap_count"], 0)) > 0:
        reasons.append("подходит по навыкам")
    if safe_int(get_value(row, ["format_match_from_raw", "format_match"], 0), 0) == 1:
        reasons.append("совпадает формат участия")
    if safe_int(row.get("city_match"), 0) == 1:
        reasons.append("совпадает город или регион")
    if safe_float(get_value(row, ["task_quality_final", "task_quality_score"], 0)) >= 0.7:
        reasons.append("качественно описана задача")
    # Правило 25: позитивный сигнал — волонтёр готов к этой сложной задаче
    if (safe_float(get_value(row, ["task_complexity_score"], 0)) > 0.50
            and safe_float(get_value(row, ["volunteer_complexity_mismatch"], 0)) < 0.25):
        reasons.append("у вас есть необходимые навыки для этой задачи")
    if safe_float(row.get("business_adjustment"), 0) > 0 and not reasons:
        reasons.append("есть положительные продуктовые факторы")
    if not reasons:
        reasons.append("есть базовое соответствие профиля и задачи")
    return "Рекомендация: " + ", ".join(reasons) + "."
