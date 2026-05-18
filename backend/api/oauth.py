"""
OAuth 2.0 авторизация через ВКонтакте и Яндекс.

Переменные окружения:
  VK_CLIENT_ID, VK_CLIENT_SECRET        — приложение VK OAuth
  YANDEX_OAUTH_CLIENT_ID, YANDEX_OAUTH_CLIENT_SECRET — приложение Яндекс ID
  HELPERA_OAUTH_SALT                     — соль для деривации пароля Supabase
  HELPERA_BASE_URL                       — публичный URL сервера (http://localhost:3000)
"""

import hashlib
import hmac
import json
import os
import secrets
import urllib.parse
from urllib.error import HTTPError
from urllib.request import Request, urlopen

VK_CLIENT_ID = os.environ.get("VK_CLIENT_ID", "")
VK_CLIENT_SECRET = os.environ.get("VK_CLIENT_SECRET", "")
YANDEX_CLIENT_ID = os.environ.get("YANDEX_OAUTH_CLIENT_ID", "")
YANDEX_CLIENT_SECRET = os.environ.get("YANDEX_OAUTH_CLIENT_SECRET", "")
OAUTH_SALT = os.environ.get("HELPERA_OAUTH_SALT", "helpera-oauth-dev-salt-change-in-prod")


def _make_redirect_uri(base_url, provider):
    return f"{base_url.rstrip('/')}/auth/{provider}/callback"


def _derive_password(provider, provider_id):
    """Детерминированный пароль для OAuth-пользователей в Supabase."""
    raw = f"{OAUTH_SALT}:{provider}:{provider_id}"
    return "Hp!" + hashlib.sha256(raw.encode()).hexdigest()[:20]


def _state_encode(data: dict) -> str:
    payload = json.dumps(data, separators=(",", ":"))
    return urllib.parse.quote(payload, safe="")


def _state_decode(state: str) -> dict:
    try:
        return json.loads(urllib.parse.unquote(state))
    except Exception:
        return {}


def _http_post(url, body_dict, headers=None):
    payload = urllib.parse.urlencode(body_dict).encode()
    req = Request(url, data=payload, headers=headers or {}, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8"))
        except Exception:
            return {"error": str(exc)}


def _http_get(url, headers=None):
    req = Request(url, headers=headers or {}, method="GET")
    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8"))
        except Exception:
            return {"error": str(exc)}


# ---------------------------------------------------------------------------
# VK OAuth
# ---------------------------------------------------------------------------

def vk_auth_url(base_url, role):
    if not VK_CLIENT_ID:
        return None
    state = _state_encode({"role": role, "nonce": secrets.token_hex(8)})
    params = urllib.parse.urlencode({
        "client_id": VK_CLIENT_ID,
        "redirect_uri": _make_redirect_uri(base_url, "vk"),
        "scope": "email",
        "response_type": "code",
        "state": state,
        "display": "page",
    })
    return f"https://oauth.vk.com/authorize?{params}"


def vk_exchange(code, base_url):
    """Обменивает code → (email, vk_user_id, first_name, last_name)."""
    data = _http_post("https://oauth.vk.com/access_token", {
        "client_id": VK_CLIENT_ID,
        "client_secret": VK_CLIENT_SECRET,
        "redirect_uri": _make_redirect_uri(base_url, "vk"),
        "code": code,
    })
    if "error" in data:
        raise ValueError(f"VK token error: {data.get('error_description', data['error'])}")
    vk_id = str(data.get("user_id", ""))
    email = data.get("email") or f"{vk_id}@vk-oauth.helpera"
    return email, vk_id, data.get("first_name", ""), data.get("last_name", "")


# ---------------------------------------------------------------------------
# Yandex OAuth
# ---------------------------------------------------------------------------

def yandex_auth_url(base_url, role):
    if not YANDEX_CLIENT_ID:
        return None
    state = _state_encode({"role": role, "nonce": secrets.token_hex(8)})
    params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": YANDEX_CLIENT_ID,
        "redirect_uri": _make_redirect_uri(base_url, "yandex"),
        "state": state,
        "force_confirm": "yes",
    })
    return f"https://oauth.yandex.ru/authorize?{params}"


def yandex_exchange(code, base_url):
    """Обменивает code → (email, yandex_id, first_name, last_name)."""
    token_data = _http_post("https://oauth.yandex.ru/token", {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": YANDEX_CLIENT_ID,
        "client_secret": YANDEX_CLIENT_SECRET,
        "redirect_uri": _make_redirect_uri(base_url, "yandex"),
    })
    if "error" in token_data:
        raise ValueError(f"Yandex token error: {token_data.get('error_description', token_data['error'])}")
    access_token = token_data.get("access_token", "")
    info = _http_get(
        "https://login.yandex.ru/info?format=json",
        headers={"Authorization": f"OAuth {access_token}"},
    )
    if "error" in info:
        raise ValueError(f"Yandex user info error: {info['error']}")
    yandex_id = str(info.get("id", ""))
    email = info.get("default_email") or f"{yandex_id}@yandex-oauth.helpera"
    return email, yandex_id, info.get("first_name", ""), info.get("last_name", "")


# ---------------------------------------------------------------------------
# Supabase пользователь
# ---------------------------------------------------------------------------

def _supabase_auth_post(supabase_url, supabase_key, path, body):
    url = f"{supabase_url.rstrip('/')}/auth/v1{path}"
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("apikey", supabase_key)
    try:
        with urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except Exception:
            return exc.code, {"error": str(exc)}


def get_or_create_supabase_user(supabase_url, supabase_key, email, provider, provider_id, role, first_name, last_name):
    """
    Создаёт или находит пользователя Supabase через анонимный API.
    Возвращает (access_token, refresh_token, user_id, is_new).
    """
    password = _derive_password(provider, provider_id)
    display_name = f"{first_name} {last_name}".strip() or email.split("@")[0]

    # Пробуем зарегистрировать нового пользователя
    status, data = _supabase_auth_post(supabase_url, supabase_key, "/signup", {
        "email": email,
        "password": password,
        "data": {
            "role": role,
            "oauth_provider": provider,
            "oauth_provider_id": provider_id,
            "full_name": display_name,
        },
    })

    is_new = True
    if status in (200, 201):
        # Новый пользователь создан
        session = data.get("session") or {}
        # У нового пользователя сессия может отсутствовать (если включено подтверждение email)
        # Тогда сразу логинимся
        if not session.get("access_token"):
            status2, data2 = _supabase_auth_post(supabase_url, supabase_key,
                                                  "/token?grant_type=password",
                                                  {"email": email, "password": password})
            if status2 == 200:
                session = data2
            else:
                raise ValueError(f"Supabase sign-in failed after signup: {data2}")
    elif status == 400 and "already registered" in str(data.get("msg", "") or data.get("message", "") or data.get("error_description", "")):
        # Пользователь уже существует — входим
        is_new = False
        status2, data2 = _supabase_auth_post(supabase_url, supabase_key,
                                              "/token?grant_type=password",
                                              {"email": email, "password": password})
        if status2 != 200:
            raise ValueError(f"Supabase sign-in failed: {data2}")
        session = data2
    else:
        raise ValueError(f"Supabase signup failed ({status}): {data}")

    access_token = session.get("access_token", "")
    refresh_token = session.get("refresh_token", "")
    user_id = (session.get("user") or {}).get("id", "")
    return access_token, refresh_token, user_id, is_new


# ---------------------------------------------------------------------------
# Публичные обработчики
# ---------------------------------------------------------------------------

def oauth_start(provider, role, base_url):
    """
    Возвращает URL для редиректа к OAuth-провайдеру.
    Если провайдер не настроен — возвращает None.
    """
    if provider == "vk":
        return vk_auth_url(base_url, role)
    if provider == "yandex":
        return yandex_auth_url(base_url, role)
    return None


def oauth_callback(provider, query_params, base_url, supabase_url, supabase_key):
    """
    Обрабатывает callback от OAuth-провайдера.
    Возвращает URL для редиректа на фронтенд.

    Успех:  /auth-callback.html?role=...&is_new=1&profileId=...#access_token=...&refresh_token=...
    Ошибка: /auth-callback.html?error=...
    """
    error = query_params.get("error") or query_params.get("error_code")
    if error:
        desc = query_params.get("error_description") or query_params.get("error_reason") or error
        return f"/auth-callback.html?error={urllib.parse.quote(str(desc))}"

    code = query_params.get("code")
    if not code:
        return "/auth-callback.html?error=missing_code"

    state = _state_decode(query_params.get("state", ""))
    role = state.get("role", "volunteer")

    try:
        if provider == "vk":
            email, provider_id, first_name, last_name = vk_exchange(code, base_url)
        elif provider == "yandex":
            email, provider_id, first_name, last_name = yandex_exchange(code, base_url)
        else:
            return "/auth-callback.html?error=unknown_provider"

        if not supabase_url or not supabase_key:
            # Supabase не настроен — локальная разработка, пропускаем Auth
            params = urllib.parse.urlencode({
                "role": role,
                "is_new": "1",
                "email": email,
                "provider": provider,
                "provider_id": provider_id,
                "display_name": f"{first_name} {last_name}".strip(),
                "no_supabase": "1",
            })
            return f"/auth-callback.html?{params}"

        access_token, refresh_token, user_id, is_new = get_or_create_supabase_user(
            supabase_url, supabase_key, email, provider, provider_id, role, first_name, last_name
        )

        params = urllib.parse.urlencode({
            "role": role,
            "is_new": "1" if is_new else "0",
            "user_id": user_id,
        })
        fragment = urllib.parse.urlencode({
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "type": "signup" if is_new else "signin",
        })
        return f"/auth-callback.html?{params}#{fragment}"

    except Exception as exc:
        return f"/auth-callback.html?error={urllib.parse.quote(str(exc)[:200])}"
