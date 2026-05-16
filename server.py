import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.api.recommendations import recommendations_event_response, recommendations_for_path, recommendations_health_response


ROOT_DIR = Path(__file__).resolve().parent


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


class HelperaHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT_DIR), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
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
    server = ThreadingHTTPServer(("localhost", PORT), HelperaHandler)
    print(f"Helpera is running at http://localhost:{PORT}")
    print(f"YANDEX_CLOUD_FOLDER: {'set' if YANDEX_FOLDER else 'missing'}")
    print(f"YANDEX_CLOUD_API_KEY: {'set' if YANDEX_API_KEY else 'missing'}")
    print(f"YANDEX_CLOUD_MODEL: {YANDEX_MODEL}")
    server.serve_forever()
