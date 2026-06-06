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

def _env(key, default=""):
    """Читает env-переменную в момент вызова, а не при импорте модуля."""
    return os.environ.get(key, default) or default


def _get_salt():
    """Читает HELPERA_OAUTH_SALT в момент вызова (после загрузки .env.local)."""
    salt = os.environ.get("HELPERA_OAUTH_SALT", "")
    if not salt:
        raise RuntimeError(
            "HELPERA_OAUTH_SALT не задан. Добавьте случайную строку в .env.local"
        )
    return salt


def _make_redirect_uri(base_url, provider):
    return f"{base_url.rstrip('/')}/auth/{provider}/callback"


def _derive_password(provider, provider_id):
    """Детерминированный пароль для OAuth-пользователей в Supabase."""
    salt = _get_salt()
    return "Hp!" + hmac.new(salt.encode(), f"{provider}:{provider_id}".encode(), hashlib.sha256).hexdigest()[:32]


def _state_encode(data: dict) -> str:
    payload = json.dumps(data, separators=(",", ":"))
    return urllib.parse.quote(payload, safe="")


def _state_decode(state: str) -> dict:
    try:
        return json.loads(urllib.parse.unquote(state))
    except Exception:
        return {}


def _sign_nonce(nonce: str) -> str:
    """HMAC-подпись nonce для верификации state без server-side session."""
    key = os.environ.get("HELPERA_OAUTH_SALT", "fallback").encode()
    return hmac.new(key, nonce.encode(), hashlib.sha256).hexdigest()[:16]


def _make_state(role: str) -> tuple[str, str]:
    """Создаёт state с nonce и его подписью. Возвращает (state_str, nonce)."""
    nonce = secrets.token_hex(16)
    sig = _sign_nonce(nonce)
    state = _state_encode({"role": role, "nonce": nonce, "sig": sig})
    return state, nonce


def _verify_state(state_raw: str) -> dict:
    """Проверяет HMAC-подпись nonce. Возвращает данные или {} при ошибке."""
    data = _state_decode(state_raw)
    nonce = data.get("nonce", "")
    sig = data.get("sig", "")
    if not nonce or not sig:
        return {}
    expected = _sign_nonce(nonce)
    if not secrets.compare_digest(sig, expected):
        return {}
    return data


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
    client_id = _env("VK_CLIENT_ID")
    if not client_id:
        return None
    state, _ = _make_state(role)
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": _make_redirect_uri(base_url, "vk"),
        "scope": "email",
        "response_type": "code",
        "state": state,
        "display": "page",
    })
    return f"https://oauth.vk.com/authorize?{params}"


def vk_exchange(code, base_url):
    """Обменивает code → (email, vk_user_id, first_name, last_name, birthday)."""
    data = _http_post("https://oauth.vk.com/access_token", {
        "client_id": _env("VK_CLIENT_ID"),
        "client_secret": _env("VK_CLIENT_SECRET"),
        "redirect_uri": _make_redirect_uri(base_url, "vk"),
        "code": code,
    })
    if "error" in data:
        raise ValueError(f"VK token error: {data.get('error_description', data['error'])}")
    vk_id = str(data.get("user_id", ""))
    email = data.get("email") or f"{vk_id}@vk-oauth.helpera"
    return email, vk_id, data.get("first_name", ""), data.get("last_name", ""), ""


# ---------------------------------------------------------------------------
# Yandex OAuth
# ---------------------------------------------------------------------------

def yandex_auth_url(base_url, role):
    client_id = _env("YANDEX_OAUTH_CLIENT_ID")
    if not client_id:
        return None
    state, _ = _make_state(role)
    params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": _make_redirect_uri(base_url, "yandex"),
        "state": state,
        "force_confirm": "yes",
    })
    return f"https://oauth.yandex.ru/authorize?{params}"


def yandex_exchange(code, base_url):
    """Обменивает code → (email, yandex_id, first_name, last_name, birthday)."""
    token_data = _http_post("https://oauth.yandex.ru/token", {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": _env("YANDEX_OAUTH_CLIENT_ID"),
        "client_secret": _env("YANDEX_OAUTH_CLIENT_SECRET"),
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
    # birthday: "YYYY-MM-DD" или "0000-00-00" если не указана
    raw_birthday = info.get("birthday") or ""
    birthday = raw_birthday if (raw_birthday and not raw_birthday.startswith("0000")) else ""
    return email, yandex_id, info.get("first_name", ""), info.get("last_name", ""), birthday


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


def _supabase_admin_find_user_by_email(supabase_url, service_key, email):
    """Admin API: ищет пользователя Supabase по email. Возвращает dict или None."""
    encoded = urllib.parse.quote(email, safe="")
    url = f"{supabase_url.rstrip('/')}/auth/v1/admin/users?filter=email%3D{encoded}&page=1&per_page=10"
    req = Request(url, method="GET")
    req.add_header("apikey", service_key)
    req.add_header("Authorization", f"Bearer {service_key}")
    try:
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    users = data.get("users") or []
    for u in users:
        if (u.get("email") or "").lower() == email.lower():
            return u
    return None


def _supabase_admin_update_user_password(supabase_url, service_key, user_id, password):
    """Admin API: устанавливает новый пароль пользователю Supabase."""
    url = f"{supabase_url.rstrip('/')}/auth/v1/admin/users/{user_id}"
    payload = json.dumps({"password": password}).encode("utf-8")
    req = Request(url, data=payload, method="PUT")
    req.add_header("Content-Type", "application/json")
    req.add_header("apikey", service_key)
    req.add_header("Authorization", f"Bearer {service_key}")
    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8"))
        except Exception:
            return {"error": str(exc)}


def get_or_create_supabase_user(supabase_url, supabase_key, email, provider, provider_id, role, first_name, last_name, birthday=""):
    """
    Создаёт или находит пользователя Supabase через анонимный API.
    Возвращает (access_token, refresh_token, user_id, is_new).
    """
    password = _derive_password(provider, provider_id)
    display_name = f"{first_name} {last_name}".strip() or email.split("@")[0]

    user_meta = {
        "role": role,
        "oauth_provider": provider,
        "oauth_provider_id": provider_id,
        "full_name": display_name,
        "first_name": first_name,
        "last_name": last_name,
    }
    if birthday:
        user_meta["birthday"] = birthday

    # Пробуем зарегистрировать нового пользователя
    status, data = _supabase_auth_post(supabase_url, supabase_key, "/signup", {
        "email": email,
        "password": password,
        "data": user_meta,
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
    elif (
        data.get("error_code") == "user_already_exists"
        or "already registered" in str(data.get("msg", "") or data.get("message", "") or data.get("error_description", ""))
    ):
        # Пользователь уже существует — входим (Supabase возвращает 400 или 422)
        is_new = False
        status2, data2 = _supabase_auth_post(supabase_url, supabase_key,
                                              "/token?grant_type=password",
                                              {"email": email, "password": password})
        if status2 != 200:
            if data2.get("error_code") == "invalid_credentials":
                # Аккаунт зарегистрирован через форму — нельзя перезаписывать пароль.
                # Предлагаем войти по email и привязать OAuth в настройках.
                raise ValueError(
                    "Этот email уже зарегистрирован. Войдите по email и паролю — "
                    "привязку через Яндекс можно добавить в настройках профиля."
                )
            raise ValueError("Не удалось войти. Попробуйте ещё раз.")
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

def vk_token_auth(access_token, role, supabase_url, supabase_key):
    """Аутентификация через VK ID SDK (клиентский Callback-flow).
    access_token уже получен браузером через VKID.Auth.exchangeCode.
    """
    info = _http_get(
        f"https://api.vk.com/method/users.get?access_token={urllib.parse.quote(access_token)}&v=5.131&fields=first_name,last_name"
    )
    error = info.get("error")
    if error:
        raise ValueError(f"VK API: {error.get('error_msg', 'ошибка')}")
    users = info.get("response", [])
    if not users:
        raise ValueError("VK API не вернул данные пользователя")
    user = users[0]
    vk_id = str(user.get("id", ""))
    first_name = user.get("first_name", "")
    last_name = user.get("last_name", "")
    email = f"{vk_id}@vk-oauth.helpera"

    if not supabase_url or not supabase_key:
        params = urllib.parse.urlencode({
            "role": role, "is_new": "1", "email": email,
            "provider": "vk", "provider_id": vk_id,
            "display_name": f"{first_name} {last_name}".strip(),
            "no_supabase": "1",
        })
        return f"/auth-callback.html?{params}"

    sb_access, refresh, user_id, is_new = get_or_create_supabase_user(
        supabase_url, supabase_key, email, "vk", vk_id, role, first_name, last_name
    )
    params = urllib.parse.urlencode({
        "role": role, "is_new": "1" if is_new else "0", "user_id": user_id,
    })
    fragment = urllib.parse.urlencode({
        "access_token": sb_access, "refresh_token": refresh,
        "token_type": "bearer", "type": "signup" if is_new else "signin",
    })
    return f"/auth-callback.html?{params}#{fragment}"


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

    state = _verify_state(query_params.get("state", ""))
    if not state:
        return "/auth-callback.html?error=invalid_state"
    role = state.get("role", "volunteer")

    try:
        if provider == "vk":
            email, provider_id, first_name, last_name, birthday = vk_exchange(code, base_url)
        elif provider == "yandex":
            email, provider_id, first_name, last_name, birthday = yandex_exchange(code, base_url)
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
            supabase_url, supabase_key, email, provider, provider_id, role, first_name, last_name, birthday
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

    except ValueError as exc:
        # ValueError содержит пользовательское сообщение — показываем
        return f"/auth-callback.html?error={urllib.parse.quote(str(exc)[:300])}"
    except Exception as exc:
        import logging as _log
        _log.error("OAuth callback internal error: %s", exc, exc_info=True)
        return "/auth-callback.html?error=Ошибка авторизации. Попробуйте ещё раз."
