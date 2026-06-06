import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import logging
from pathlib import Path
from urllib.parse import quote, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

from backend.api.oauth import oauth_callback, oauth_start, vk_token_auth
from backend.api.recommendations import recommendations_event_response, recommendations_for_path, recommendations_health_response
from backend.api.tasks import task_duplicate_check_response
from backend.ml.deduplication import check_duplicate
from backend.ml.linucb import reset_task_stats


ROOT_DIR = Path(__file__).resolve().parent

# Интервал фоновых задач (секунды). По умолчанию — раз в час.
_BACKGROUND_INTERVAL = int(os.environ.get("HELPERA_BACKGROUND_INTERVAL", "3600"))
# Таймаут ответа НКО на отклик (часы). Если НКО не ответила за это время — фиксируем событие.
_NGO_RESPONSE_TIMEOUT_HOURS = int(os.environ.get("HELPERA_NGO_RESPONSE_TIMEOUT_HOURS", "72"))
# Правило 18: таймаут статуса "review". Если НКО не обработала отклик за N дней — статус меняется на "timeout".
_APPLICATION_TIMEOUT_DAYS = int(os.environ.get("HELPERA_APPLICATION_TIMEOUT_DAYS", "7"))
# Правило 5: максимальное число активных задач для одной НКО.
NGO_TASK_LIMIT = int(os.environ.get("HELPERA_NGO_TASK_LIMIT", "10"))


def load_env_file(file_name):
    file_path = ROOT_DIR / file_name
    if not file_path.exists():
        return

    for line in file_path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#") or "=" not in value:
            continue

        key, raw = value.split("=", 1)
        key = key.strip()
        raw = raw.strip()
        if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
            raw = raw[1:-1]
        if key and not os.environ.get(key):
            os.environ[key] = raw


load_env_file(".env.local")
load_env_file(".env")

PORT = int(os.environ.get("PORT", "3000"))
YANDEX_API_KEY = os.environ.get("YANDEX_CLOUD_API_KEY") or ""
YANDEX_FOLDER = os.environ.get("YANDEX_CLOUD_FOLDER") or ""


def json_response(handler, status_code, body):
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    handler.send_response(status_code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "DENY")
    handler.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
    handler.end_headers()
    handler.wfile.write(payload)


def task_prompt(action, task, user_prompt="", style=""):
    title = task.get("title") or "Название пока не заполнено"
    description = task.get("description") or "Описание пока не заполнено"
    skills = task.get("skills") or "Навыки пока не указаны"
    task_format = task.get("format") or "Формат пока не указан"
    directions = task.get("directions") or "Направление пока не указано"
    comment = task.get("comment") or "Комментарий не указан"

    if action == "draft":
        return "\n".join([
            "Составь понятное описание волонтёрской задачи для платформы Helpera.",
            "Пиши на русском, дружелюбно и конкретно. Без markdown, списков и заголовков.",
            "В первую очередь учитывай уже заполненное поле «Описание задачи»: сохрани его факты, смысл и ограничения.",
            "Если описание уже заполнено, не начинай с нуля, а перепиши и улучши именно этот текст.",
            "Остальные поля используй как контекст для уточнения формулировок.",
            f"Пожелание пользователя: {user_prompt or 'нет'}",
            f"Стиль варианта: {style or 'ясный и дружелюбный'}",
            f"Название: {title}",
            f"Текущее описание: {description}",
            f"Формат: {task_format}",
            f"Навыки: {skills}",
            f"Направление: {directions}",
            f"Комментарий НКО: {comment}",
            "Текст должен быть 3-5 предложений и объяснять, что нужно сделать, какой результат ожидается и почему помощь важна.",
        ])

    return "\n".join([
        "Улучши описание волонтёрской задачи для платформы Helpera.",
        "Сохрани смысл, не выдумывай факты, пиши на русском. Без markdown, списков и заголовков.",
        f"Пожелание пользователя: {user_prompt or 'нет'}",
        f"Стиль варианта: {style or 'ясный и дружелюбный'}",
        f"Название: {title}",
        f"Текущее описание: {description}",
        f"Формат: {task_format}",
        f"Навыки: {skills}",
        f"Направление: {directions}",
        f"Комментарий НКО: {comment}",
        "Сделай текст яснее, теплее и конкретнее. Длина 3-5 предложений.",
    ])


def parse_yandex_text(data):
    if isinstance(data.get("output_text"), str):
        return data["output_text"].strip()

    parts = []
    for item in data.get("output") or []:
        for content in item.get("content") or []:
            if content.get("text"):
                parts.append(content["text"])
    return "".join(parts).strip()


def resolve_yandex_model(folder):
    model = os.environ.get("YANDEX_CLOUD_MODEL") or "yandexgpt-lite/latest"
    if model.startswith("gpt://"):
        return model.replace("YANDEX_CLOUD_FOLDER", folder or "")
    return f"gpt://{folder}/{model}"


YANDEX_MODEL = resolve_yandex_model(YANDEX_FOLDER)

# OAuth Supabase connection (populated at startup)
_OAUTH_SUPABASE_URL = ""
_OAUTH_SUPABASE_KEY = ""
_OAUTH_BASE_URL = ""


def clamp_number(value, default, min_value, max_value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(number, max_value))


def call_yandex_ai(action, task, user_prompt="", options=None):
    if not YANDEX_API_KEY or not YANDEX_FOLDER:
        return 500, {"error": "Не заданы YANDEX_CLOUD_API_KEY и YANDEX_CLOUD_FOLDER в .env.local"}

    options = options or {}
    temperature = clamp_number(options.get("temperature"), 0.3, 0.0, 1.0)
    max_output_tokens = int(clamp_number(options.get("maxOutputTokens"), 500, 150, 900))
    style = str(options.get("style") or "")[:300]

    payload = {
        "model": YANDEX_MODEL,
        "temperature": temperature,
        "instructions": "Ты помогаешь НКО формулировать задачи для волонтёров. Отвечай только готовым текстом для поля описания.",
        "input": task_prompt(action, task, str(user_prompt or "")[:500], style),
        "max_output_tokens": max_output_tokens,
    }
    request = Request(
        "https://ai.api.cloud.yandex.net/v1/responses",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {YANDEX_API_KEY}",
            "OpenAI-Project": YANDEX_FOLDER,
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        try:
            data = json.loads(error.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = {}
        message = data.get("error", {}).get("message") or "Yandex AI вернул ошибку"
        return error.code, {"error": message}
    except URLError as error:
        return 502, {"error": f"Не удалось подключиться к Yandex AI: {error.reason}"}

    text = parse_yandex_text(data)
    if not text:
        return 502, {"error": "Yandex AI вернул пустой ответ"}
    return 200, {"text": text}


def _verify_token(handler, supabase_url, supabase_key):
    """
    Валидирует Bearer-токен из заголовка Authorization через Supabase.
    Возвращает dict пользователя или None (ответ 401 уже отправлен).
    В dev-режиме (Supabase не настроен) пропускает проверку.
    """
    if not supabase_url or not supabase_key:
        return {"id": "dev-user", "email": "dev@local"}  # local dev без Supabase

    raw = handler.headers.get("Authorization") or ""
    token = raw.removeprefix("Bearer ").strip() if raw.startswith("Bearer ") else ""
    if not token:
        json_response(handler, 401, {"error": "Требуется авторизация", "code": "unauthorized"})
        return None

    req = Request(
        f"{supabase_url.rstrip('/')}/auth/v1/user",
        headers={"apikey": supabase_key, "Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in (401, 403):
            json_response(handler, 401, {"error": "Недействительный токен авторизации", "code": "invalid_token"})
        else:
            json_response(handler, 503, {"error": "Сервис авторизации недоступен"})
        return None
    except Exception:
        json_response(handler, 503, {"error": "Сервис авторизации недоступен"})
        return None


def _is_localhost(handler):
    """Проверяет, что запрос пришёл с localhost (для admin-эндпоинтов)."""
    client_addr = handler.client_address[0] if handler.client_address else ""
    return client_addr in ("127.0.0.1", "::1", "localhost")


def _check_volunteer_owner(supabase_url, supabase_key, profile_id, user_id):
    """True если user_id совпадает с владельцем volunteer_profiles.id."""
    row = _supabase_get_one(supabase_url, supabase_key, "volunteer_profiles", profile_id, select="user_id")
    return row and str(row.get("user_id", "")) == str(user_id)


def _check_ngo_owner(supabase_url, supabase_key, profile_id, user_id):
    """True если user_id совпадает с владельцем ngo_profiles.id."""
    row = _supabase_get_one(supabase_url, supabase_key, "ngo_profiles", profile_id, select="user_id")
    return row and str(row.get("user_id", "")) == str(user_id)


def _check_task_ngo_owner(supabase_url, supabase_key, task_id, user_id):
    """True если user_id владеет НКО, которой принадлежит задача."""
    task = _supabase_get_one(supabase_url, supabase_key, "tasks", task_id, select="ngo_profile_id")
    if not task:
        return False
    return _check_ngo_owner(supabase_url, supabase_key, task.get("ngo_profile_id"), user_id)


def _supabase_rpc(url, key, function_name, params=None):
    """Вызов Supabase RPC функции через REST API."""
    endpoint = f"{url.rstrip('/')}/rest/v1/rpc/{function_name}"
    payload = json.dumps(params or {}, ensure_ascii=False).encode("utf-8")
    req = Request(
        endpoint,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "apikey": key,
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"error": str(exc)}


def _supabase_query(url, key, table, filters=None, select="*", limit=200):
    """Простой SELECT из Supabase через REST API."""
    params = f"select={quote(select, safe='*,')}&limit={limit}"
    if filters:
        for key_f, value in filters.items():
            params += f"&{quote(str(key_f), safe='')}={quote(str(value), safe='.')}"
    endpoint = f"{url.rstrip('/')}/rest/v1/{table}?{params}"
    req = Request(
        endpoint,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
        },
        method="GET",
    )
    try:
        with urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return []


def _supabase_patch(url, key, table, row_filter, patch):
    """PATCH одной или нескольких строк Supabase через REST API."""
    params = "&".join(f"{k}=eq.{v}" for k, v in row_filter.items())
    endpoint = f"{url.rstrip('/')}/rest/v1/{table}?{params}"
    payload = json.dumps(patch, ensure_ascii=False).encode("utf-8")
    req = Request(
        endpoint,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Prefer": "return=minimal",
        },
        method="PATCH",
    )
    try:
        with urlopen(req, timeout=30) as response:
            response.read()
            return True
    except Exception:
        return False


def _supabase_insert(url, key, table, row):
    """INSERT строки в Supabase через REST API."""
    endpoint = f"{url.rstrip('/')}/rest/v1/{table}"
    payload = json.dumps(row, ensure_ascii=False).encode("utf-8")
    req = Request(
        endpoint,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Prefer": "return=minimal",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=30) as response:
            response.read()
            return True
    except Exception:
        return False


def _supabase_get_one(url, key, table, row_id, select="*"):
    """GET a single row by id from Supabase."""
    endpoint = (
        f"{url.rstrip('/')}/rest/v1/{table}"
        f"?id=eq.{quote(str(row_id))}&select={quote(select)}&limit=1"
    )
    req = Request(endpoint, headers={"apikey": key, "Authorization": f"Bearer {key}"}, method="GET")
    try:
        with urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data[0] if isinstance(data, list) and data else None
    except Exception:
        return None


def _supabase_list(url, key, table, filters=None, select="*", limit=200, order=None):
    """GET list from Supabase using PostgREST filter format.

    filters: list of strings in PostgREST notation, e.g. ["status=eq.published"].
    """
    parts = [f"select={quote(select)}", f"limit={limit}"]
    if filters:
        parts.extend(filters)
    if order:
        parts.append(f"order={quote(order)}")
    endpoint = f"{url.rstrip('/')}/rest/v1/{table}?" + "&".join(parts)
    req = Request(endpoint, headers={"apikey": key, "Authorization": f"Bearer {key}"}, method="GET")
    try:
        with urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return []


def _supabase_insert_repr(url, key, table, row):
    """INSERT row and return the created record."""
    endpoint = f"{url.rstrip('/')}/rest/v1/{table}"
    payload = json.dumps(row, ensure_ascii=False).encode("utf-8")
    req = Request(
        endpoint,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Prefer": "return=representation",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data[0] if isinstance(data, list) and data else data
    except Exception:
        return None


def _supabase_patch_repr(url, key, table, row_id, patch):
    """PATCH row by id and return the updated record."""
    endpoint = f"{url.rstrip('/')}/rest/v1/{table}?id=eq.{quote(str(row_id))}"
    payload = json.dumps(patch, ensure_ascii=False).encode("utf-8")
    req = Request(
        endpoint,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Prefer": "return=representation",
        },
        method="PATCH",
    )
    try:
        with urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data[0] if isinstance(data, list) and data else data
    except Exception:
        return None


# Правило 29: конфиденциальность — ключи, содержащие персональные данные.
_PII_KEYS = frozenset({
    "contact", "contacts", "email", "phone", "phone_number",
    "birthDate", "birth_date", "passport", "inn", "snils",
    "address", "personal_address",
})


def _strip_pii(obj):
    """Правило 29: рекурсивно удаляет PII-ключи из ответа API."""
    if isinstance(obj, dict):
        return {k: _strip_pii(v) for k, v in obj.items() if k not in _PII_KEYS}
    if isinstance(obj, list):
        return [_strip_pii(item) for item in obj]
    return obj


def _check_application_eligibility(sb_url, sb_key, task_id, volunteer_id):
    """
    Правило 17: проверяет право волонтёра на отклик.
    Возвращает строку с ошибкой или None если отклик допустим.
    Проверяет: статус задачи, дедлайн, заполненность, дубликат заявки.
    """
    if not task_id:
        return "Задача не указана"
    task = _supabase_get_one(sb_url, sb_key, "tasks", task_id)
    if not task:
        return "Задача не найдена"

    # Статус задачи
    if str(task.get("status") or "").lower() not in ("published", "active"):
        return "Задача закрыта и не принимает новых участников"

    # Дедлайн
    payload = task.get("payload") or {}
    deadline_str = task.get("date_end") or payload.get("dateEnd") or payload.get("deadline")
    if deadline_str:
        try:
            from datetime import date as _d
            dl = _d.fromisoformat(str(deadline_str)[:10])
            if dl < _d.today():
                return "Срок подачи заявок истёк"
        except (ValueError, TypeError):
            pass

    # Заполненность
    capacity = int(payload.get("capacity") or task.get("capacity") or 0)
    current = int(payload.get("currentApplications") or task.get("current_applications") or 0)
    if capacity and current >= capacity:
        return "Набор волонтёров завершён — все места заняты"

    # Дубликат заявки
    if volunteer_id:
        existing = _supabase_query(
            sb_url, sb_key, "applications",
            filters={"task_id": f"eq.{task_id}", "volunteer_profile_id": f"eq.{volunteer_id}"},
            select="id,status",
            limit=10,
        )
        _ACTIVE_STATUSES = {"review", "invite", "active", "draft"}
        if any(str(r.get("status") or "").lower() in _ACTIVE_STATUSES for r in (existing or [])):
            return "Вы уже подали заявку на эту задачу"

    return None


def _text_quality_score(text: str, target_words: int = 5) -> float:
    """
    Правило 22: оценка содержательности текстового отзыва (0.0–1.0).
    Учитывает количество слов и уникальность символов.
    """
    stripped = text.strip()
    words = [w for w in stripped.split() if len(w) >= 2]
    word_score = min(1.0, len(words) / target_words)
    # Отношение уникальных символов к общей длине без пробелов — детектор спама
    body = stripped.replace(" ", "")
    unique_ratio = len(set(body.lower())) / max(len(body), 1)
    unique_score = min(1.0, unique_ratio / 0.15)
    return round(word_score * unique_score, 3)


def _check_review_text(text: str, min_len: int, min_words: int, field_name: str):
    """
    Правило 22: валидация содержательности текстового отзыва.
    Возвращает строку ошибки или None при успехе.
    """
    stripped = str(text or "").strip()
    if len(stripped) < min_len:
        return f"{field_name}: минимальная длина — {min_len} символов"
    words = [w for w in stripped.split() if len(w) >= 2]
    if len(words) < min_words:
        return f"{field_name}: напишите не менее {min_words} слов — это помогает системе корректно интерпретировать сигнал"
    # Спам-детектор: слишком низкое разнообразие символов
    body = stripped.replace(" ", "")
    unique_ratio = len(set(body.lower())) / max(len(body), 1)
    if unique_ratio < 0.08:
        return f"{field_name}: текст кажется автоматическим — постарайтесь написать содержательный комментарий"
    return None


def _process_application_timeouts(sb_url, sb_key):
    """
    Правило 18: переводит заявки со статусом 'review', ожидающие ответа дольше
    _APPLICATION_TIMEOUT_DAYS дней, в статус 'timeout'. Логирует событие для каждой.
    Возвращает (всего_найдено, переведено_в_timeout).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=_APPLICATION_TIMEOUT_DAYS)
    cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    stale = _supabase_list(
        sb_url, sb_key, "applications",
        filters=[f"status=eq.review", f"created_at=lt.{quote(cutoff_iso)}"],
        select="id,task_id,volunteer_profile_id,payload",
        limit=500,
    )
    timed_out = 0
    for app in (stale or []):
        app_id = app.get("id")
        if not app_id:
            continue
        app_payload = dict(app.get("payload") or {})
        app_payload["timedOutAt"] = datetime.now(timezone.utc).isoformat()
        app_payload["timeoutDays"] = _APPLICATION_TIMEOUT_DAYS
        ok = _supabase_patch(
            sb_url, sb_key, "applications",
            {"id": app_id},
            {"status": "timeout", "payload": app_payload},
        )
        if ok:
            timed_out += 1
            _supabase_insert(sb_url, sb_key, "app_events", {
                "event_type": "application_timed_out",
                "actor_role": "system",
                "application_id": app_id,
                "task_id": app.get("task_id"),
                "payload": {
                    "volunteer_profile_id": app.get("volunteer_profile_id"),
                    "timeout_days": _APPLICATION_TIMEOUT_DAYS,
                    "source": "process-timeouts",
                },
            })
    return len(stale or []), timed_out


def _validate_task(data):
    """Правило 1: задача не публикуется при отсутствии обязательных полей.
    Проверяет title, description, skills, format, directions, даты и город (для офлайн).
    Возвращает список ошибок; пустой список — данные корректны.
    """
    errors = []
    title = (data.get("title") or "").strip()
    if not title or len(title) < 5:
        errors.append("Название задачи обязательно (минимум 5 символов)")

    desc = (data.get("description") or "").strip()
    if not desc or len(desc) < 30:
        errors.append("Описание задачи обязательно (минимум 30 символов)")

    skills = (data.get("skills") or "").strip()
    if not skills:
        errors.append("Навыки обязательны")

    fmt = (data.get("format") or "").strip()
    if not fmt:
        errors.append("Формат участия обязателен")

    if not (data.get("date_start") or data.get("dateStart") or "").strip():
        errors.append("Дата начала обязательна")
    if not (data.get("date_end") or data.get("dateEnd") or "").strip():
        errors.append("Дата окончания обязательна")

    payload = data.get("payload") or {}
    directions = (
        (payload.get("directions") if isinstance(payload, dict) else None)
        or data.get("directions")
        or ""
    ).strip()
    if not directions:
        errors.append("Направление деятельности обязательно")

    if fmt in ("Оффлайн", "Смешанный"):
        city = (
            (payload.get("city") if isinstance(payload, dict) else None)
            or data.get("city")
            or ""
        ).strip()
        if not city:
            errors.append("Город обязателен для оффлайн/смешанного формата")

    return errors


def _flag_duplicate(data, sb_url, sb_key):
    """Правило 3: дедупликация — выставляет is_duplicate_candidate в payload задачи.
    Запускается при создании и обновлении задачи. Не блокирует публикацию.
    """
    try:
        from backend.ml.supabase_repository import SupabaseRecommendationRepository
        repo = SupabaseRecommendationRepository(sb_url, sb_key)
        all_tasks = repo.get_candidate_tasks(None)
        ngo_id = str(data.get("ngoProfileId") or data.get("ngo_profile_id") or "")
        if ngo_id:
            all_tasks = [t for t in all_tasks if t.get("ngo_id") != ngo_id]
        result = check_duplicate(data, all_tasks)
        task_payload = data.get("payload")
        if not isinstance(task_payload, dict):
            task_payload = {}
        task_payload["is_duplicate_candidate"] = result["is_duplicate"]
        data["payload"] = task_payload
    except Exception:
        pass


def _count_ngo_active_tasks(sb_url, sb_key, ngo_id):
    """Правило 5: возвращает число активных (published) задач НКО."""
    if not ngo_id:
        return 0
    rows = _supabase_list(
        sb_url, sb_key, "tasks",
        filters=[f"ngo_profile_id=eq.{quote(str(ngo_id))}", "status=eq.published"],
        select="id",
        limit=NGO_TASK_LIMIT + 1,
    )
    return len(rows) if isinstance(rows, list) else 0


def read_json_body(handler, max_size=64 * 1024):
    """Read and parse JSON body from an HTTP request. Returns (data, None, None) or (None, status, error_body)."""
    try:
        length = int(handler.headers.get("Content-Length", "0"))
        if length > max_size:
            return None, 413, {"error": "Слишком большой запрос"}
        body = handler.rfile.read(length).decode("utf-8") if length > 0 else ""
        return json.loads(body or "{}"), None, None
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None, 400, {"error": "Некорректный JSON"}


def _sb_guard(handler):
    """Return (url, key) if Supabase is configured; otherwise send 503 and return (None, None)."""
    url = _OAUTH_SUPABASE_URL
    key = _OAUTH_SUPABASE_KEY
    if not url or not key:
        json_response(
            handler, 503,
            {"error": "Supabase не настроен. Задайте HELPERA_SUPABASE_URL и HELPERA_SUPABASE_ANON_KEY в .env.local"}
        )
        return None, None
    return url, key


def _fetch_expiring_task_ids(supabase_url, supabase_key):
    """
    Правило 26: возвращает ID задач, которые должны быть закрыты.
    Вызывается ДО смены статуса — чтобы зафиксировать IDs для очистки LinUCB и заявок.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    endpoint = (
        f"{supabase_url.rstrip('/')}/rest/v1/tasks"
        f"?status=eq.published"
        f"&or=(deadline.lt.{today},date_end.lt.{today})"
        f"&select=id"
        f"&limit=500"
    )
    req = Request(endpoint, headers={"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"})
    try:
        with urlopen(req, timeout=15) as r:
            rows = json.loads(r.read().decode("utf-8"))
            return [str(row["id"]) for row in (rows or []) if row.get("id")]
    except Exception:
        return []


def _expire_tasks_via_rest(supabase_url, supabase_key, task_ids):
    """
    Правило 26: REST API fallback когда RPC helpera_expire_tasks() недоступна.
    Переводит каждую задачу из списка в status=closed, publication_status=expired.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    count = 0
    for task_id in task_ids:
        ok = _supabase_patch(
            supabase_url, supabase_key, "tasks",
            {"id": task_id},
            {"status": "closed", "publication_status": "expired"},
        )
        if ok:
            count += 1
    return count


def _expire_pending_applications(supabase_url, supabase_key, task_id):
    """
    Правило 26: переводит открытые заявки на истёкшую задачу в статус 'expired'.
    Критически важно: НЕ считается срывом для волонтёра — задача закрыта системой.
    """
    endpoint = (
        f"{supabase_url.rstrip('/')}/rest/v1/applications"
        f"?task_id=eq.{task_id}"
        f"&status=in.(review,invite,active)"
        f"&select=id,volunteer_profile_id,status"
        f"&limit=200"
    )
    req = Request(endpoint, headers={"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"})
    try:
        with urlopen(req, timeout=15) as r:
            apps = json.loads(r.read().decode("utf-8"))
    except Exception:
        return 0

    count = 0
    for app in (apps or []):
        app_id = app.get("id")
        if not app_id:
            continue
        ok = _supabase_patch(supabase_url, supabase_key, "applications", {"id": app_id}, {"status": "expired"})
        if ok:
            _supabase_insert(supabase_url, supabase_key, "app_events", {
                "event_type": "application_expired",
                "actor_role": "system",
                "application_id": app_id,
                "task_id": task_id,
                "payload": {
                    "reason": "task_deadline_passed",
                    "previous_status": app.get("status"),
                },
            })
            count += 1
    return count


def run_expire_tasks(supabase_url, supabase_key):
    """
    Правило 26: Автоматическое снятие задач после дедлайна — контроль жизненного цикла.

    Pipeline:
      1. Зафиксировать IDs задач с истёкшим дедлайном (до смены статуса).
      2. Снять статус через RPC helpera_expire_tasks() или REST-fallback.
      3. Сбросить LinUCB-статистику → задача не получает UCB-бонус после истечения.
      4. Записать событие task_expired в app_events для аналитики/дообучения.
      5. Перевести открытые заявки (review/invite/active) в status=expired —
         НЕ засчитывается как срыв волонтёра.

    Возвращает число задач, снятых в этом запуске.
    """
    if not supabase_url or not supabase_key:
        return 0

    # Шаг 1: зафиксировать IDs до смены статуса
    expired_ids = _fetch_expiring_task_ids(supabase_url, supabase_key)
    if not expired_ids:
        return 0

    # Шаг 2: снять статус — RPC (транзакционно) или REST fallback
    rpc_result = _supabase_rpc(supabase_url, supabase_key, "helpera_expire_tasks")
    if isinstance(rpc_result, dict) and "error" in rpc_result:
        _expire_tasks_via_rest(supabase_url, supabase_key, expired_ids)

    # Шаги 3–5: очистка для каждой истёкшей задачи
    now_iso = datetime.now(timezone.utc).isoformat()
    for task_id in expired_ids:
        # Правило 4: сброс LinUCB — после истечения задача больше не исследуется
        reset_task_stats(task_id)
        # Лог события для аналитики и дообучения модели
        _supabase_insert(supabase_url, supabase_key, "app_events", {
            "event_type": "task_expired",
            "actor_role": "system",
            "task_id": task_id,
            "payload": {"expiredAt": now_iso, "reason": "deadline_passed"},
        })
        # Закрыть незавершённые заявки без штрафа для волонтёра
        _expire_pending_applications(supabase_url, supabase_key, task_id)

    return len(expired_ids)


def run_ngo_response_timeout_check(supabase_url, supabase_key, timeout_hours):
    """
    Таймаут отклика НКО: находит заявки в статусе 'review', созданные более
    timeout_hours назад, и логирует событие ngo_response_timeout.
    Только для Supabase-режима.
    """
    if not supabase_url or not supabase_key:
        return 0

    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=timeout_hours)).isoformat()

    # Фильтруем заявки: status=review AND created_at < cutoff
    # Supabase REST поддерживает операторы через имя_колонки=lt.значение
    endpoint = (
        f"{supabase_url.rstrip('/')}/rest/v1/applications"
        f"?select=id,task_id,volunteer_profile_id,created_at"
        f"&status=eq.review"
        f"&created_at=lt.{cutoff}"
        f"&limit=100"
    )
    req = Request(
        endpoint,
        headers={
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
        },
        method="GET",
    )
    try:
        with urlopen(req, timeout=30) as response:
            stale = json.loads(response.read().decode("utf-8"))
    except Exception:
        return 0

    if not isinstance(stale, list):
        return 0

    count = 0
    for app in stale:
        # Проверяем, нет ли уже события таймаута для этой заявки
        existing_endpoint = (
            f"{supabase_url.rstrip('/')}/rest/v1/app_events"
            f"?application_id=eq.{app['id']}"
            f"&event_type=eq.ngo_response_timeout"
            f"&limit=1&select=id"
        )
        req_check = Request(
            existing_endpoint,
            headers={"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"},
            method="GET",
        )
        try:
            with urlopen(req_check, timeout=10) as r:
                existing = json.loads(r.read().decode("utf-8"))
        except Exception:
            continue
        if existing:
            continue

        ok = _supabase_insert(supabase_url, supabase_key, "app_events", {
            "event_type": "ngo_response_timeout",
            "actor_role": "system",
            "application_id": app["id"],
            "task_id": app.get("task_id"),
            "payload": {
                "reason": f"НКО не ответила на отклик в течение {timeout_hours} ч.",
                "created_at_application": app.get("created_at"),
            },
        })
        if ok:
            count += 1

    return count


def _background_loop(supabase_url, supabase_key, interval, timeout_hours):
    """Фоновый поток: периодически закрывает просроченные задачи и проверяет таймаут НКО."""
    while True:
        try:
            expired = run_expire_tasks(supabase_url, supabase_key)
            timeouts = run_ngo_response_timeout_check(supabase_url, supabase_key, timeout_hours)
            if expired or timeouts:
                now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                print(f"[{now}] Background: expired={expired} tasks, ngo_timeouts={timeouts}")
        except Exception as exc:
            print(f"[background] error: {exc}")
        time.sleep(interval)


_BLOCKED_PATH = re.compile(
    r"(^/\.|/\.|"           # скрытые файлы и директории (.env, .git и т.д.)
    r"/backend/|"           # серверный Python-код
    r"/deploy/|"            # скрипты деплоя
    r"server\.py$|"         # главный модуль сервера
    r"requirements\.txt$|"  # зависимости
    r"supabase-seed\.sql$|" # данные БД
    r"supabase-schema\.sql$|"
    r"CNAME$|"
    r"README\.md$|"
    r"Procfile$|"
    r"\.pyc$|\.py$|\.sh$|\.env)",
    re.IGNORECASE,
)


class HelperaHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT_DIR), **kwargs)

    def _send_security_headers(self):
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")

    def do_GET(self):
        parsed = urlparse(self.path)

        # Блокируем доступ к чувствительным файлам и директориям
        if _BLOCKED_PATH.search(parsed.path):
            self.send_error(403, "Forbidden")
            return

        # OAuth: /auth/{provider}/start?role=volunteer|ngo
        if parsed.path in ("/auth/vk/start", "/auth/yandex/start"):
            provider = parsed.path.split("/")[2]
            from urllib.parse import parse_qs
            role = parse_qs(parsed.query).get("role", ["volunteer"])[0]
            redirect_url = oauth_start(provider, role, _OAUTH_BASE_URL)
            if redirect_url:
                self.send_response(302)
                self.send_header("Location", redirect_url)
                self.end_headers()
            else:
                json_response(self, 503, {"error": f"OAuth провайдер '{provider}' не настроен. Задайте VK_CLIENT_ID / YANDEX_OAUTH_CLIENT_ID в .env.local"})
            return

        # OAuth: /auth/{provider}/callback
        if parsed.path in ("/auth/vk/callback", "/auth/yandex/callback"):
            provider = parsed.path.split("/")[2]
            from urllib.parse import parse_qs
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            redirect_url = oauth_callback(provider, query, _OAUTH_BASE_URL, _OAUTH_SUPABASE_URL, _OAUTH_SUPABASE_KEY)
            self.send_response(302)
            self.send_header("Location", redirect_url)
            self.end_headers()
            return

        if parsed.path == "/api/recommendations/health":
            status_code, payload = recommendations_health_response()
            json_response(self, status_code, payload)
            return

        # GET /api/recommendations/events/stats — Правило 27: статистика лога событий.
        # Показывает число событий по типам, размер файла и утилизацию буфера.
        if parsed.path == "/api/recommendations/events/stats":
            try:
                from backend.ml.event_logger import get_stats
                json_response(self, 200, get_stats())
            except Exception as exc:
                logging.error("Internal error: %s", exc, exc_info=True)
                json_response(self, 500, {"error": "Внутренняя ошибка сервера"})
            return

        if parsed.path.startswith("/api/recommendations/volunteers/"):
            status_code, payload = recommendations_for_path(self.path)
            json_response(self, status_code, payload)
            return

        if parsed.path == "/api/health":
            json_response(self, 200, {"status": "ok"})
            return

        # GET /api/volunteers/{id}
        m = re.match(r"^/api/volunteers/([^/]+)$", parsed.path)
        if m:
            sb_url, sb_key = _sb_guard(self)
            if not sb_url:
                return
            # Правило 29: возвращаем только публичные поля профиля волонтёра.
            row = _supabase_get_one(
                sb_url, sb_key, "volunteer_profiles", m.group(1),
                select=(
                    "id,skills_clean,directions_clean,city_clean,format_clean,age,"
                    "profile_completeness,volunteer_reliability_score,active_tasks_count"
                ),
            )
            json_response(self, 200 if row else 404, _strip_pii(row) if row else {"error": "Волонтёр не найден"})
            return

        # GET /api/ngos/{id}
        m = re.match(r"^/api/ngos/([^/]+)$", parsed.path)
        if m:
            sb_url, sb_key = _sb_guard(self)
            if not sb_url:
                return
            # Правило 29: только публичные поля НКО, без контактных данных.
            row = _supabase_get_one(
                sb_url, sb_key, "ngo_profiles", m.group(1),
                select="id,org_name,about,ngo_reliability_score,complaint_rate,avg_response_time_hours",
            )
            json_response(self, 200 if row else 404, _strip_pii(row) if row else {"error": "НКО не найдена"})
            return

        # GET /api/tasks  (list)
        if parsed.path == "/api/tasks":
            sb_url, sb_key = _sb_guard(self)
            if not sb_url:
                return
            # Правило 29: явный список полей задачи, контакты НКО не включаем.
            rows = _supabase_list(
                sb_url, sb_key, "tasks",
                filters=["status=eq.published"],
                select=(
                    "id,title,description,format,skills,date_start,date_end,"
                    "status,payload,created_at,ngo_profile_id,"
                    "ngo_profiles(org_name,about)"
                ),
                limit=200,
                order="created_at.desc",
            )
            json_response(self, 200, _strip_pii(rows))
            return

        # GET /api/tasks/{id}
        m = re.match(r"^/api/tasks/([^/]+)$", parsed.path)
        if m:
            sb_url, sb_key = _sb_guard(self)
            if not sb_url:
                return
            # Правило 29: явный список полей, контакты НКО не включаем.
            row = _supabase_get_one(
                sb_url, sb_key, "tasks", m.group(1),
                select=(
                    "id,title,description,format,skills,date_start,date_end,"
                    "status,payload,created_at,ngo_profile_id,"
                    "ngo_profiles(org_name,about)"
                ),
            )
            json_response(self, 200 if row else 404, _strip_pii(row) if row else {"error": "Задача не найдена"})
            return

        # GET /api/applications/{id}
        m = re.match(r"^/api/applications/([^/]+)$", parsed.path)
        if m:
            sb_url, sb_key = _sb_guard(self)
            if not sb_url:
                return
            # Правило 29: только статусные поля заявки, payload с рецензиями не раскрываем.
            row = _supabase_get_one(
                sb_url, sb_key, "applications", m.group(1),
                select="id,task_id,volunteer_profile_id,status,created_at,updated_at",
            )
            json_response(self, 200 if row else 404, row or {"error": "Заявка не найдена"})
            return

        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/auth/vk-token":
            data, err_code, err_body = read_json_body(self, max_size=4 * 1024)
            if err_code:
                json_response(self, err_code, err_body)
                return
            token = data.get("access_token", "")
            role = data.get("role", "volunteer")
            if not token:
                json_response(self, 422, {"error": "access_token required"})
                return
            try:
                redirect = vk_token_auth(token, role, _OAUTH_SUPABASE_URL, _OAUTH_SUPABASE_KEY)
                json_response(self, 200, {"redirect": redirect})
            except ValueError as exc:
                json_response(self, 400, {"error": str(exc)})
            except Exception as exc:
                logging.error("vk-token error: %s", exc, exc_info=True)
                json_response(self, 500, {"error": "Внутренняя ошибка сервера"})
            return

        if parsed.path == "/api/recommendations/events":
            data, err_code, err_body = read_json_body(self, max_size=8 * 1024)
            if err_code:
                json_response(self, err_code, err_body)
                return
            status_code, payload = recommendations_event_response(
                json.dumps(data, ensure_ascii=False).encode()
            )
            json_response(self, status_code, payload)
            return

        if parsed.path == "/api/tasks/check-duplicate":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length > 0 else b""
            except ValueError:
                body = b""
            status_code, payload = task_duplicate_check_response(body)
            json_response(self, status_code, payload)
            return

        # POST /api/tasks/expire  — Правило 26: ручной триггер снятия просроченных задач.
        # Используется для тестирования и admin-панели; в проде запускается фоновым потоком.
        if parsed.path == "/api/tasks/expire":
            if not _is_localhost(self):
                json_response(self, 403, {"error": "Forbidden"})
                return
            sb_url, sb_key = _sb_guard(self)
            if not sb_url:
                return
            count = run_expire_tasks(sb_url, sb_key)
            json_response(self, 200, {
                "ok": True,
                "expired": count,
                "message": f"Снято {count} задач с истёкшим дедлайном.",
            })
            return

        # POST /api/volunteers/{id}/refresh-workload — Правило 16
        m = re.match(r"^/api/volunteers/([^/]+)/refresh-workload$", parsed.path)
        if m:
            sb_url, sb_key = _sb_guard(self)
            if not sb_url:
                return
            volunteer_id = m.group(1)
            try:
                from backend.ml.supabase_repository import SupabaseRecommendationRepository
                repo = SupabaseRecommendationRepository(sb_url, sb_key)
                computed = repo.compute_volunteer_workload(volunteer_id)
            except Exception as exc:
                logging.error("Internal error: %s", exc, exc_info=True)
                json_response(self, 500, {"error": "Внутренняя ошибка сервера"})
                return
            if computed is None:
                json_response(self, 200, {"updated": False, "reason": "Не удалось получить данные о заявках"})
                return
            _supabase_patch_repr(sb_url, sb_key, "volunteer_profiles", volunteer_id, computed)
            json_response(self, 200, {"updated": True, **computed})
            return

        # POST /api/volunteers/{id}/refresh-reliability — Правило 14
        m = re.match(r"^/api/volunteers/([^/]+)/refresh-reliability$", parsed.path)
        if m:
            sb_url, sb_key = _sb_guard(self)
            if not sb_url:
                return
            volunteer_id = m.group(1)
            try:
                from backend.ml.supabase_repository import SupabaseRecommendationRepository
                repo = SupabaseRecommendationRepository(sb_url, sb_key)
                computed = repo.compute_volunteer_reliability(volunteer_id)
            except Exception as exc:
                logging.error("Internal error: %s", exc, exc_info=True)
                json_response(self, 500, {"error": "Внутренняя ошибка сервера"})
                return
            if not computed:
                json_response(self, 200, {"updated": False, "reason": "Недостаточно данных о завершённых заявках"})
                return
            patch = {
                "volunteer_cancel_rate": computed["volunteer_cancel_rate"],
                "volunteer_reliability_score": computed["volunteer_reliability_score"],
            }
            # Правило 24: сохраняем агрегированную оценку от НКО если есть отзывы
            if "volunteer_review_avg_rating" in computed:
                patch["volunteer_review_avg_rating"] = computed["volunteer_review_avg_rating"]
            _supabase_patch_repr(sb_url, sb_key, "volunteer_profiles", volunteer_id, patch)
            json_response(self, 200, {"updated": True, **computed})
            return

        # POST /api/ngos/{id}/refresh-reliability — Правило 15
        m = re.match(r"^/api/ngos/([^/]+)/refresh-reliability$", parsed.path)
        if m:
            sb_url, sb_key = _sb_guard(self)
            if not sb_url:
                return
            ngo_id = m.group(1)
            try:
                from backend.ml.supabase_repository import SupabaseRecommendationRepository
                repo = SupabaseRecommendationRepository(sb_url, sb_key)
                computed = repo.compute_ngo_reliability(ngo_id)
            except Exception as exc:
                logging.error("Internal error: %s", exc, exc_info=True)
                json_response(self, 500, {"error": "Внутренняя ошибка сервера"})
                return
            if not computed:
                json_response(self, 200, {"updated": False, "reason": "Недостаточно данных об откликах"})
                return
            patch = {
                "avg_response_time_hours": computed["avg_response_time_hours"],
                "ngo_reliability_score": computed["ngo_reliability_score"],
            }
            _supabase_patch_repr(sb_url, sb_key, "ngo_profiles", ngo_id, patch)
            json_response(self, 200, {"updated": True, **computed})
            return

        # POST /api/volunteers
        if parsed.path == "/api/volunteers":
            sb_url, sb_key = _sb_guard(self)
            if not sb_url:
                return
            data, err_code, err_body = read_json_body(self)
            if err_code:
                json_response(self, err_code, err_body)
                return
            row = _supabase_insert_repr(sb_url, sb_key, "volunteer_profiles", data)
            json_response(self, 201 if row else 500, row or {"error": "Не удалось создать профиль волонтёра"})
            return

        # POST /api/ngos
        if parsed.path == "/api/ngos":
            sb_url, sb_key = _sb_guard(self)
            if not sb_url:
                return
            data, err_code, err_body = read_json_body(self)
            if err_code:
                json_response(self, err_code, err_body)
                return
            row = _supabase_insert_repr(sb_url, sb_key, "ngo_profiles", data)
            json_response(self, 201 if row else 500, row or {"error": "Не удалось создать профиль НКО"})
            return

        # POST /api/tasks
        if parsed.path == "/api/tasks":
            sb_url, sb_key = _sb_guard(self)
            if not sb_url:
                return
            data, err_code, err_body = read_json_body(self)
            if err_code:
                json_response(self, err_code, err_body)
                return
            errors = _validate_task(data)
            if errors:
                json_response(self, 422, {"error": errors[0], "errors": errors})
                return
            # Правило 5: лимит активных задач НКО
            ngo_id = str(data.get("ngoProfileId") or data.get("ngo_profile_id") or "")
            if ngo_id and _count_ngo_active_tasks(sb_url, sb_key, ngo_id) >= NGO_TASK_LIMIT:
                json_response(self, 422, {
                    "error": f"Достигнут лимит: не более {NGO_TASK_LIMIT} активных задач. Закройте неактуальные задачи, чтобы создать новую.",
                    "code": "ngo_task_limit_exceeded"
                })
                return
            _flag_duplicate(data, sb_url, sb_key)
            row = _supabase_insert_repr(sb_url, sb_key, "tasks", data)
            json_response(self, 201 if row else 500, row or {"error": "Не удалось создать задачу"})
            return

        # POST /api/applications/process-timeouts  — Правило 18
        if parsed.path == "/api/applications/process-timeouts":
            if not _is_localhost(self):
                json_response(self, 403, {"error": "Forbidden"})
                return
            sb_url, sb_key = _sb_guard(self)
            if not sb_url:
                return
            processed, timed_out = _process_application_timeouts(sb_url, sb_key)
            json_response(self, 200, {"processed": processed, "timed_out": timed_out, "timeout_days": _APPLICATION_TIMEOUT_DAYS})
            return

        # POST /api/applications
        if parsed.path == "/api/applications":
            sb_url, sb_key = _sb_guard(self)
            if not sb_url:
                return
            data, err_code, err_body = read_json_body(self)
            if err_code:
                json_response(self, err_code, err_body)
                return
            # Правило 17: проверка права на отклик
            eligibility_error = _check_application_eligibility(
                sb_url, sb_key,
                data.get("task_id"),
                data.get("volunteer_profile_id"),
            )
            if eligibility_error:
                json_response(self, 409, {"error": eligibility_error, "code": "application_not_eligible"})
                return
            row = _supabase_insert_repr(sb_url, sb_key, "applications", data)
            # Правило 27: фиксируем отклик как сильный сигнал для дообучения (reward +3)
            if row:
                try:
                    from backend.ml.linucb import record_apply as _record_apply
                    _record_apply(
                        str(data.get("task_id") or ""),
                        str(data.get("volunteer_profile_id") or ""),
                    )
                except Exception:
                    pass
            json_response(self, 201 if row else 500, row or {"error": "Не удалось создать заявку"})
            return

        # POST /api/applications/{id}/cancel — Правило 19
        m = re.match(r"^/api/applications/([^/]+)/cancel$", parsed.path)
        if m:
            sb_url, sb_key = _sb_guard(self)
            if not sb_url:
                return
            auth_user = _verify_token(self, sb_url, sb_key)
            if not auth_user:
                return
            aid = m.group(1)
            data, _ec, _eb = read_json_body(self)
            app_row = _supabase_get_one(sb_url, sb_key, "applications", aid)
            if not app_row:
                json_response(self, 404, {"error": "Заявка не найдена"})
                return
            # IDOR: только владелец профиля волонтёра может отменить свою заявку
            vol_profile_id = app_row.get("volunteer_profile_id")
            if not _check_volunteer_owner(sb_url, sb_key, vol_profile_id, auth_user.get("id")):
                json_response(self, 403, {"error": "Нет прав на отмену этой заявки", "code": "forbidden"})
                return
            current_status = str(app_row.get("status") or "").lower()
            _CANCELLABLE = {"review", "invite", "active", "timeout"}
            if current_status not in _CANCELLABLE:
                json_response(self, 409, {
                    "error": f"Нельзя отменить заявку со статусом «{current_status}»",
                    "code": "cannot_cancel",
                })
                return
            app_payload = dict(app_row.get("payload") or {})
            app_payload["cancelledAt"] = datetime.now(timezone.utc).isoformat()
            app_payload["cancelledFromStatus"] = current_status
            if data and data.get("reason"):
                app_payload["cancelReason"] = str(data["reason"])[:500]
            # Поздняя отмена (после подтверждения НКО) — отдельная метка для аналитики
            is_late = current_status in {"invite", "active"}
            if is_late:
                app_payload["lateCancellation"] = True
            row = _supabase_patch_repr(sb_url, sb_key, "applications", aid, {
                "status": "cancelled_by_volunteer",
                "payload": app_payload,
            })
            if not row:
                json_response(self, 500, {"error": "Не удалось обновить заявку"})
                return
            volunteer_id = app_row.get("volunteer_profile_id") or (data or {}).get("volunteer_profile_id")
            _supabase_insert(sb_url, sb_key, "app_events", {
                "event_type": "application_cancelled",
                "actor_role": "volunteer",
                "actor_profile_id": volunteer_id,
                "application_id": aid,
                "task_id": app_row.get("task_id"),
                "payload": {
                    "previous_status": current_status,
                    "late_cancellation": is_late,
                    "source": "cancel-endpoint",
                },
            })
            if volunteer_id:
                # Правило 27: фиксируем отмену как негативный исход (reward −3)
                try:
                    from backend.ml.linucb import record_outcome as _record_outcome
                    _record_outcome(
                        str(app_row.get("task_id") or ""),
                        str(volunteer_id),
                        "cancelled_by_volunteer",
                    )
                except Exception:
                    pass
                try:
                    from backend.ml.supabase_repository import SupabaseRecommendationRepository
                    repo = SupabaseRecommendationRepository(sb_url, sb_key)
                    computed = repo.compute_volunteer_reliability(volunteer_id)
                    if computed:
                        _supabase_patch(sb_url, sb_key, "volunteer_profiles",
                            {"id": volunteer_id},
                            {
                                "volunteer_cancel_rate": computed["volunteer_cancel_rate"],
                                "volunteer_reliability_score": computed["volunteer_reliability_score"],
                            })
                except Exception:
                    pass
            json_response(self, 200, {**row, "reliability_refreshed": bool(volunteer_id)})
            return

        # POST /api/applications/{id}/(accept|reject|complete|partial)  — Правило 20: partial_done
        m = re.match(r"^/api/applications/([^/]+)/(accept|reject|complete|partial)$", parsed.path)
        if m:
            sb_url, sb_key = _sb_guard(self)
            if not sb_url:
                return
            auth_user = _verify_token(self, sb_url, sb_key)
            if not auth_user:
                return
            aid, action = m.group(1), m.group(2)
            # IDOR: accept/reject/complete только представитель НКО-владельца задачи
            app_for_check = _supabase_get_one(sb_url, sb_key, "applications", aid, select="task_id")
            if app_for_check and not _check_task_ngo_owner(sb_url, sb_key, app_for_check.get("task_id"), auth_user.get("id")):
                json_response(self, 403, {"error": "Нет прав на управление этой заявкой", "code": "forbidden"})
                return
            # Правило 20: partial → partial_done — учитывается как 0.5 в шкале надёжности
            status_map = {"accept": "invite", "reject": "rejected", "complete": "done", "partial": "partial_done"}
            new_status = status_map[action]
            row = _supabase_patch_repr(sb_url, sb_key, "applications", aid, {"status": new_status})
            if row and action in ("complete", "partial"):
                volunteer_id = row.get("volunteer_profile_id")
                task_id_outcome = str(row.get("task_id") or "")
                if volunteer_id:
                    # Правило 27: фиксируем исход — сильнейший сигнал для дообучения
                    try:
                        from backend.ml.linucb import record_outcome as _record_outcome
                        _record_outcome(
                            task_id_outcome,
                            str(volunteer_id),
                            new_status,   # "done" или "partial_done"
                        )
                    except Exception:
                        pass
                    try:
                        from backend.ml.supabase_repository import SupabaseRecommendationRepository
                        repo = SupabaseRecommendationRepository(sb_url, sb_key)
                        computed = repo.compute_volunteer_reliability(volunteer_id)
                        avg = repo.compute_volunteer_avg_outcome(volunteer_id)
                        patch = {}
                        if computed:
                            patch["volunteer_cancel_rate"] = computed["volunteer_cancel_rate"]
                            patch["volunteer_reliability_score"] = computed["volunteer_reliability_score"]
                        if avg:
                            patch["volunteer_avg_outcome"] = avg["volunteer_avg_outcome"]
                        if patch:
                            _supabase_patch(sb_url, sb_key, "volunteer_profiles", {"id": volunteer_id}, patch)
                    except Exception:
                        pass
            json_response(self, 200 if row else 404, row or {"error": "Заявка не найдена"})
            return

        # POST /api/reviews  — Правило 21: двусторонняя оценка, условие закрытия задачи
        if parsed.path == "/api/reviews":
            sb_url, sb_key = _sb_guard(self)
            if not sb_url:
                return
            auth_user = _verify_token(self, sb_url, sb_key)
            if not auth_user:
                return
            data, err_code, err_body = read_json_body(self)
            if err_code:
                json_response(self, err_code, err_body)
                return
            application_id = data.get("application_id")
            if not application_id:
                json_response(self, 422, {"error": "application_id обязателен"})
                return
            app_row = _supabase_get_one(sb_url, sb_key, "applications", application_id)
            if app_row is None:
                json_response(self, 404, {"error": "Заявка не найдена"})
                return

            review_data = data.get("review") or {}
            actor_role = data.get("actor_role", "volunteer")

            # IDOR: волонтёр может оставить отзыв только за себя, НКО — только за свою задачу
            user_id = auth_user.get("id")
            if actor_role == "volunteer":
                if not _check_volunteer_owner(sb_url, sb_key, app_row.get("volunteer_profile_id"), user_id):
                    json_response(self, 403, {"error": "Нет прав оставить отзыв от имени этого волонтёра", "code": "forbidden"})
                    return
            elif actor_role == "ngo":
                if not _check_task_ngo_owner(sb_url, sb_key, app_row.get("task_id"), user_id):
                    json_response(self, 403, {"error": "Нет прав оставить отзыв от имени этой НКО", "code": "forbidden"})
                    return

            # Правило 21: валидация — все три оценки 1–10 обязательны
            ratings = review_data.get("ratings") or {}
            if len(ratings) < 3:
                json_response(self, 422, {"error": "Необходимо выставить все три оценки (1–10)", "code": "ratings_required"})
                return
            for val in ratings.values():
                if not isinstance(val, (int, float)) or not (1 <= val <= 10):
                    json_response(self, 422, {"error": "Каждая оценка должна быть от 1 до 10", "code": "ratings_invalid"})
                    return
            # Правило 22: содержательность текстового отзыва — длина + количество слов + спам-детектор
            short_text = str(review_data.get("shortReview") or "").strip()
            short_err = _check_review_text(short_text, min_len=50, min_words=5, field_name="Короткий отзыв")
            if short_err:
                json_response(self, 422, {"error": short_err, "code": "short_review_invalid"})
                return
            extended_text = str(review_data.get("extendedReview") or "").strip()
            has_extended = bool(extended_text)
            if has_extended:
                ext_err = _check_review_text(extended_text, min_len=200, min_words=15, field_name="Расширенный отзыв")
                if ext_err:
                    json_response(self, 422, {"error": ext_err, "code": "extended_review_invalid"})
                    return
            # Правило 22/23: сохраняем оценки содержательности как ML-сигналы
            review_data = {
                **review_data,
                "textQualityScore": _text_quality_score(short_text, target_words=5),
                "hasExtendedReview": has_extended,
                **({"extendedTextQualityScore": _text_quality_score(extended_text, target_words=15)} if has_extended else {}),
            }

            app_payload = dict(app_row.get("payload") or {})
            reviews = dict(app_payload.get("reviews") or {})

            # Правило 21: повторный отзыв от той же стороны запрещён
            if actor_role in reviews:
                json_response(self, 409, {"error": "Отзыв от этой стороны уже оставлен", "code": "review_already_submitted"})
                return

            reviews[actor_role] = {**review_data, "submittedAt": datetime.now(timezone.utc).isoformat()}
            app_payload["reviews"] = reviews

            # Правило 21: задача закрывается только при двустороннем отзыве
            both_reviewed = "volunteer" in reviews and "ngo" in reviews
            if both_reviewed:
                # Completion от НКО → outcome_status для целевой переменной (Правило 20)
                ngo_completion = reviews.get("ngo", {}).get("completion", "completed")
                _COMPLETION_MAP = {"completed": "done", "partial": "partial_done", "not_completed": "not_done"}
                app_payload["outcomeStatus"] = _COMPLETION_MAP.get(ngo_completion, "done")
                new_status = "done"
            else:
                new_status = app_row.get("status")

            updated = _supabase_patch_repr(
                sb_url, sb_key, "applications", application_id,
                {"payload": app_payload, "status": new_status},
            )
            if not updated:
                json_response(self, 500, {"error": "Не удалось сохранить отзыв"})
                return

            # Правило 23: мотивационная механика — фиксируем флаг расширенного отзыва на профиле
            if has_extended:
                if actor_role == "volunteer":
                    vol_id = app_row.get("volunteer_profile_id")
                    if vol_id:
                        _supabase_patch(sb_url, sb_key, "volunteer_profiles",
                            {"id": vol_id}, {"volunteer_extended_review_flag": True})
                elif actor_role == "ngo":
                    task_row_ext = _supabase_get_one(sb_url, sb_key, "tasks", app_row.get("task_id") or "")
                    ngo_id_ext = (task_row_ext or {}).get("ngo_profile_id")
                    if ngo_id_ext:
                        _supabase_patch(sb_url, sb_key, "ngo_profiles",
                            {"id": ngo_id_ext}, {"ngo_extended_review_flag": True})

            # После двустороннего закрытия — пересчёт надёжности обеих сторон
            if both_reviewed:
                volunteer_id = app_row.get("volunteer_profile_id")
                task_id_for_ngo = app_row.get("task_id")
                if volunteer_id:
                    try:
                        from backend.ml.supabase_repository import SupabaseRecommendationRepository
                        repo = SupabaseRecommendationRepository(sb_url, sb_key)
                        reliability = repo.compute_volunteer_reliability(volunteer_id)
                        avg_outcome = repo.compute_volunteer_avg_outcome(volunteer_id)
                        v_patch = {}
                        if reliability:
                            v_patch["volunteer_cancel_rate"] = reliability["volunteer_cancel_rate"]
                            v_patch["volunteer_reliability_score"] = reliability["volunteer_reliability_score"]
                            # Правило 24: сохраняем агрегированную оценку от НКО
                            if "volunteer_review_avg_rating" in reliability:
                                v_patch["volunteer_review_avg_rating"] = reliability["volunteer_review_avg_rating"]
                        if avg_outcome:
                            v_patch["volunteer_avg_outcome"] = avg_outcome["volunteer_avg_outcome"]
                        if v_patch:
                            _supabase_patch(sb_url, sb_key, "volunteer_profiles", {"id": volunteer_id}, v_patch)
                    except Exception:
                        pass
                if task_id_for_ngo:
                    try:
                        task_row = _supabase_get_one(sb_url, sb_key, "tasks", task_id_for_ngo)
                        ngo_id = task_row.get("ngo_profile_id") if task_row else None
                        if ngo_id:
                            from backend.ml.supabase_repository import SupabaseRecommendationRepository
                            repo = SupabaseRecommendationRepository(sb_url, sb_key)
                            ngo_computed = repo.compute_ngo_reliability(ngo_id)
                            if ngo_computed:
                                _supabase_patch(sb_url, sb_key, "ngo_profiles", {"id": ngo_id}, {
                                    "avg_response_time_hours": ngo_computed["avg_response_time_hours"],
                                    "ngo_reliability_score": ngo_computed["ngo_reliability_score"],
                                })
                    except Exception:
                        pass

            json_response(self, 201, {**updated, "both_reviewed": both_reviewed})
            return

        # POST /api/events
        if parsed.path == "/api/events":
            sb_url, sb_key = _sb_guard(self)
            if not sb_url:
                return
            data, err_code, err_body = read_json_body(self)
            if err_code:
                json_response(self, err_code, err_body)
                return
            row = _supabase_insert_repr(sb_url, sb_key, "app_events", data)
            json_response(self, 201 if row else 500, row or {"error": "Не удалось записать событие"})
            return

        if parsed.path != "/api/ai/task":
            json_response(self, 404, {"error": "Endpoint не найден"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 64 * 1024:
                json_response(self, 413, {"error": "Слишком большой запрос"})
                return
            body = self.rfile.read(length).decode("utf-8")
            data = json.loads(body or "{}")
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            json_response(self, 400, {"error": "Некорректный JSON"})
            return

        action = "draft" if data.get("action") == "draft" else "transform"
        status_code, payload = call_yandex_ai(
            action,
            data.get("task") or {},
            data.get("prompt") or "",
            data.get("options") or {},
        )
        json_response(self, status_code, payload)


    def do_PATCH(self):
        parsed = urlparse(self.path)
        sb_url, sb_key = _sb_guard(self)
        if not sb_url:
            return
        auth_user = _verify_token(self, sb_url, sb_key)
        if not auth_user:
            return
        user_id = auth_user.get("id")

        # PATCH /api/volunteers/{id}
        m = re.match(r"^/api/volunteers/([^/]+)$", parsed.path)
        if m:
            if not _check_volunteer_owner(sb_url, sb_key, m.group(1), user_id):
                json_response(self, 403, {"error": "Нет прав на изменение этого профиля", "code": "forbidden"})
                return
            data, err_code, err_body = read_json_body(self)
            if err_code:
                json_response(self, err_code, err_body)
                return
            row = _supabase_patch_repr(sb_url, sb_key, "volunteer_profiles", m.group(1), data)
            json_response(self, 200 if row else 404, row or {"error": "Волонтёр не найден"})
            return

        # PATCH /api/ngos/{id}
        m = re.match(r"^/api/ngos/([^/]+)$", parsed.path)
        if m:
            if not _check_ngo_owner(sb_url, sb_key, m.group(1), user_id):
                json_response(self, 403, {"error": "Нет прав на изменение профиля НКО", "code": "forbidden"})
                return
            data, err_code, err_body = read_json_body(self)
            if err_code:
                json_response(self, err_code, err_body)
                return
            row = _supabase_patch_repr(sb_url, sb_key, "ngo_profiles", m.group(1), data)
            json_response(self, 200 if row else 404, row or {"error": "НКО не найдена"})
            return

        # PATCH /api/tasks/{id}
        m = re.match(r"^/api/tasks/([^/]+)$", parsed.path)
        if m:
            if not _check_task_ngo_owner(sb_url, sb_key, m.group(1), user_id):
                json_response(self, 403, {"error": "Нет прав на изменение этой задачи", "code": "forbidden"})
                return
            data, err_code, err_body = read_json_body(self)
            if err_code:
                json_response(self, err_code, err_body)
                return
            if "title" in data:
                errors = _validate_task(data)
                if errors:
                    json_response(self, 422, {"error": errors[0], "errors": errors})
                    return
                _flag_duplicate(data, sb_url, sb_key)
                reset_task_stats(m.group(1))
            row = _supabase_patch_repr(sb_url, sb_key, "tasks", m.group(1), data)
            json_response(self, 200 if row else 404, row or {"error": "Задача не найдена"})
            return

        # PATCH /api/applications/{id} — только участники заявки
        m = re.match(r"^/api/applications/([^/]+)$", parsed.path)
        if m:
            app = _supabase_get_one(sb_url, sb_key, "applications", m.group(1), select="volunteer_profile_id,task_id")
            is_volunteer = app and _check_volunteer_owner(sb_url, sb_key, app.get("volunteer_profile_id"), user_id)
            is_ngo = app and _check_task_ngo_owner(sb_url, sb_key, app.get("task_id"), user_id)
            if not (is_volunteer or is_ngo):
                json_response(self, 403, {"error": "Нет прав на изменение этой заявки", "code": "forbidden"})
                return
            data, err_code, err_body = read_json_body(self)
            if err_code:
                json_response(self, err_code, err_body)
                return
            row = _supabase_patch_repr(sb_url, sb_key, "applications", m.group(1), data)
            json_response(self, 200 if row else 404, row or {"error": "Заявка не найдена"})
            return

        json_response(self, 404, {"error": "Endpoint не найден"})


if __name__ == "__main__":
    _supabase_url = os.environ.get("HELPERA_SUPABASE_URL") or os.environ.get("SUPABASE_URL", "")
    _supabase_key = (
        os.environ.get("HELPERA_SUPABASE_ANON_KEY")
        or os.environ.get("SUPABASE_ANON_KEY")
        or os.environ.get("SUPABASE_KEY", "")
    )
    _BASE_URL = os.environ.get("HELPERA_BASE_URL", f"http://localhost:{PORT}")

    # Пробрасываем в глобальные переменные для OAuth-обработчика
    _OAUTH_SUPABASE_URL = _supabase_url
    _OAUTH_SUPABASE_KEY = _supabase_key
    _OAUTH_BASE_URL = _BASE_URL

    bg = threading.Thread(
        target=_background_loop,
        args=(_supabase_url, _supabase_key, _BACKGROUND_INTERVAL, _NGO_RESPONSE_TIMEOUT_HOURS),
        daemon=True,
    )
    bg.start()

    host = os.environ.get("HOST", "0.0.0.0")
    server = ThreadingHTTPServer((host, PORT), HelperaHandler)
    print(f"Helpera is running at http://localhost:{PORT}")
    print(f"YANDEX_CLOUD_FOLDER: {'set' if YANDEX_FOLDER else 'missing'}")
    print(f"YANDEX_CLOUD_API_KEY: {'set' if YANDEX_API_KEY else 'missing'}")
    print(f"YANDEX_CLOUD_MODEL: {YANDEX_MODEL}")
    print(f"Background: task expiration every {_BACKGROUND_INTERVAL}s, NGO timeout={_NGO_RESPONSE_TIMEOUT_HOURS}h")
    server.serve_forever()
