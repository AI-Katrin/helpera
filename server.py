import json
import os
import threading
import time
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.api.oauth import oauth_callback, oauth_start
from backend.api.recommendations import recommendations_event_response, recommendations_for_path, recommendations_health_response
from backend.api.tasks import task_duplicate_check_response


ROOT_DIR = Path(__file__).resolve().parent

# Интервал фоновых задач (секунды). По умолчанию — раз в час.
_BACKGROUND_INTERVAL = int(os.environ.get("HELPERA_BACKGROUND_INTERVAL", "3600"))
# Таймаут ответа НКО на отклик (часы). Если НКО не ответила за это время — фиксируем событие.
_NGO_RESPONSE_TIMEOUT_HOURS = int(os.environ.get("HELPERA_NGO_RESPONSE_TIMEOUT_HOURS", "72"))


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
    params = f"select={select}&limit={limit}"
    if filters:
        for key_f, value in filters.items():
            params += f"&{key_f}={value}"
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


def run_expire_tasks(supabase_url, supabase_key):
    """
    Автозакрытие задач: снимает с публикации задачи, у которых дедлайн прошёл.
    Вызывает Supabase RPC helpera_expire_tasks() если Supabase доступен,
    иначе ничего не делает (CSV-режим не поддерживает мутации).
    """
    if not supabase_url or not supabase_key:
        return 0
    result = _supabase_rpc(supabase_url, supabase_key, "helpera_expire_tasks")
    if isinstance(result, dict) and "error" in result:
        return -1
    count = result if isinstance(result, int) else 0
    return count


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


class HelperaHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT_DIR), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)

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

        if parsed.path.startswith("/api/recommendations/volunteers/"):
            status_code, payload = recommendations_for_path(self.path)
            json_response(self, status_code, payload)
            return

        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/recommendations/events":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length > 0 else b""
            except ValueError:
                body = b""
            status_code, payload = recommendations_event_response(body)
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

    server = ThreadingHTTPServer(("localhost", PORT), HelperaHandler)
    print(f"Helpera is running at http://localhost:{PORT}")
    print(f"YANDEX_CLOUD_FOLDER: {'set' if YANDEX_FOLDER else 'missing'}")
    print(f"YANDEX_CLOUD_API_KEY: {'set' if YANDEX_API_KEY else 'missing'}")
    print(f"YANDEX_CLOUD_MODEL: {YANDEX_MODEL}")
    print(f"Background: task expiration every {_BACKGROUND_INTERVAL}s, NGO timeout={_NGO_RESPONSE_TIMEOUT_HOURS}h")
    server.serve_forever()
