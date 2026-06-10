import json
import math
from datetime import date, datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .data_repository import pre_filter_tasks
from .normalization import safe_float, safe_int


# Правило 29: поля payload задачи, которые могут содержать персональные данные НКО.
_TASK_PAYLOAD_PII_KEYS = frozenset({
    "contact", "contacts", "email", "phone", "phone_number",
    "birthDate", "birth_date", "passport", "inn", "snils",
    "address", "personal_address",
})


def _safe_task_payload(payload):
    """Правило 29: возвращает payload задачи без PII-ключей (контакты, e-mail и т.п.)."""
    if not isinstance(payload, dict):
        return {}
    return {k: v for k, v in payload.items() if k not in _TASK_PAYLOAD_PII_KEYS}


def _calc_description_quality_score(about_task, work_to_do="", useful_skills="", direction_work="", region=""):
    """Правило 2: слишком короткое описание → низкий score → понижение в рекомендациях.
    Совпадает с порогом needs_ai_help в features.py (< 80 символов → score < 0.45).
    """
    n = len(str(about_task or "").strip())
    if n < 30:
        base = 0.0
    elif n < 80:
        base = 0.20   # warn-зона: AI-помощник обязателен
    elif n < 150:
        base = 0.45   # info-зона: желательно дополнить
    elif n < 300:
        base = 0.65
    elif n < 500:
        base = 0.80
    else:
        base = 0.90
    bonus = 0.0
    if str(work_to_do or "").strip():
        bonus += 0.05
    if str(direction_work or "").strip():
        bonus += 0.03
    if str(useful_skills or "").strip():
        bonus += 0.02
    if str(region or "").strip():
        bonus += 0.02
    return round(min(base + bonus, 1.0), 3)


class SupabaseError(RuntimeError):
    pass


class SupabaseRecommendationRepository:
    def __init__(self, url, anon_key):
        self.url = url.rstrip("/")
        self.anon_key = anon_key

    def _get(self, table, params, select):
        query = dict(params)
        query["select"] = select
        endpoint = f"{self.url}/rest/v1/{table}?{urlencode(query)}"
        req = Request(
            endpoint,
            headers={
                "apikey": self.anon_key,
                "Authorization": f"Bearer {self.anon_key}",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as error:
            body = error.read().decode("utf-8")[:300]
            raise SupabaseError(f"Supabase {error.code}: {body}") from error
        except URLError as error:
            raise SupabaseError(f"Supabase connection error: {error.reason}") from error

    # ------------------------------------------------------------------
    # Volunteer
    # ------------------------------------------------------------------

    def get_volunteer(self, volunteer_id):
        rows = self._get(
            "volunteer_profiles",
            {"id": f"eq.{volunteer_id}"},
            "id,contact,about,skills,interests,"
            "skills_clean,skills_raw,directions_clean,directions_raw,"
            "city_clean,city_raw,format_clean,age,"
            "availability_hours_week,profile_completeness,"
            "volunteer_reliability_score,volunteer_cancel_rate,active_tasks_count,"
            "volunteer_avg_outcome,volunteer_extended_review_flag,volunteer_review_avg_rating",
        )
        if not rows:
            return None
        return self._map_volunteer(rows[0])

    def _map_volunteer(self, row):
        about = row.get("about") or {}
        skills_json = row.get("skills") or {}
        interests = row.get("interests") or {}

        skills_text = row.get("skills_clean") or ", ".join(skills_json.get("skills") or [])
        directions_text = row.get("directions_clean") or ", ".join(skills_json.get("helpDirections") or [])
        city = row.get("city_clean") or row.get("city_raw") or about.get("city") or ""

        fmt = row.get("format_clean") or ""
        if not fmt:
            raw_fmt = interests.get("format")
            if isinstance(raw_fmt, list):
                fmt = raw_fmt[0] if raw_fmt else ""
            else:
                fmt = raw_fmt or ""

        age = safe_int(row.get("age"))
        if not age and about.get("birthDate"):
            try:
                birth = date.fromisoformat(str(about["birthDate"])[:10])
                today = date.today()
                age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
            except (ValueError, TypeError):
                age = 0

        return {
            "volunteer_id": str(row["id"]),
            "skills": skills_text,
            "skills_raw": row.get("skills_raw") or skills_text,
            "skills_clean": row.get("skills_clean") or skills_text,
            "help_directions": directions_text,
            "directions_clean": row.get("directions_clean") or directions_text,
            "city": city,
            "city_clean": city,
            "task_format": fmt,
            "format_clean": fmt,
            "age": age,
            "availability_hours_week": safe_int(row.get("availability_hours_week")),
            "profile_completeness": safe_float(row.get("profile_completeness"), 0.5),
            "volunteer_reliability_score": safe_float(row.get("volunteer_reliability_score"), 0.5),
            "volunteer_cancel_rate": safe_float(row.get("volunteer_cancel_rate")),
            "active_tasks_count": safe_int(row.get("active_tasks_count")),
            # Правило 20: средняя метка исхода (0–2), нейтральное значение 1.0 при отсутствии истории
            "volunteer_avg_outcome": safe_float(row.get("volunteer_avg_outcome"), 1.0),
            # Правило 23: волонтёр оставлял развёрнутые отзывы — сигнал вовлечённости
            "volunteer_extended_review_flag": int(bool(row.get("volunteer_extended_review_flag"))),
            # Правило 24: средняя оценка по отзывам НКО (0–1, нейтральный дефолт 0.7)
            "volunteer_review_avg_rating": safe_float(row.get("volunteer_review_avg_rating"), 0.7),
        }

    # Правило 20: градуированная шкала исходов для целевой переменной
    _OUTCOME_CANCELLED = frozenset({"cancelled", "cancelled_by_volunteer", "volunteer_cancelled", "not_done"})
    _OUTCOME_PARTIAL   = frozenset({"partial_done", "partial"})
    _OUTCOME_COMPLETED = frozenset({"completed", "done", "finished"})

    @staticmethod
    def outcome_label(status: str) -> int:
        """Возвращает метку качества исхода: 2=выполнено, 1=частично, 0=не выполнено/отменено."""
        s = str(status or "").lower()
        if s in SupabaseRecommendationRepository._OUTCOME_COMPLETED:
            return 2
        if s in SupabaseRecommendationRepository._OUTCOME_PARTIAL:
            return 1
        return 0

    def compute_volunteer_reliability(self, volunteer_id):
        """
        Правила 14, 20, 24: вычисляет volunteer_cancel_rate, volunteer_reliability_score
        и volunteer_review_avg_rating из статусов заявок и оценок НКО в отзывах.
        Рейтинг = статусная часть × 0.6 + средняя оценка НКО × 0.4 (когда есть отзывы).
        """
        try:
            rows = self._get(
                "applications",
                {"volunteer_profile_id": f"eq.{volunteer_id}", "limit": "500"},
                "status,payload",
            )
        except SupabaseError:
            return None
        if not isinstance(rows, list):
            return None

        cancelled = sum(1 for r in rows if str(r.get("status") or "").lower() in self._OUTCOME_CANCELLED)
        partial   = sum(1 for r in rows if str(r.get("status") or "").lower() in self._OUTCOME_PARTIAL)
        completed = sum(1 for r in rows if str(r.get("status") or "").lower() in self._OUTCOME_COMPLETED)
        effective_completed = completed + partial * 0.5
        total_final = cancelled + partial + completed
        if total_final == 0:
            return None

        cancel_rate = round(cancelled / total_final, 4)
        experience_bonus = min(0.10, effective_completed * 0.01)
        status_score = min(1.0, effective_completed / total_final + experience_bonus)

        # Правило 24: агрегация оценок из отзывов НКО (ratings.quality/communication/responsibility)
        ngo_rating_sums = []
        for r in rows:
            ngo_review = ((r.get("payload") or {}).get("reviews") or {}).get("ngo") or {}
            ratings = ngo_review.get("ratings") or {}
            vals = [v for v in ratings.values() if isinstance(v, (int, float)) and 1 <= v <= 10]
            if vals:
                ngo_rating_sums.append(sum(vals) / len(vals))

        if ngo_rating_sums:
            avg_ngo_rating_norm = round(sum(ngo_rating_sums) / len(ngo_rating_sums) / 10.0, 4)
            reliability = round(min(1.0, status_score * 0.6 + avg_ngo_rating_norm * 0.4), 4)
        else:
            avg_ngo_rating_norm = None
            reliability = round(min(1.0, status_score), 4)

        result = {
            "volunteer_cancel_rate": cancel_rate,
            "volunteer_reliability_score": reliability,
            "applications_analysed": total_final,
        }
        if avg_ngo_rating_norm is not None:
            result["volunteer_review_avg_rating"] = avg_ngo_rating_norm
        return result

    def compute_volunteer_avg_outcome(self, volunteer_id):
        """
        Правило 20: средняя метка исхода по истории волонтёра (шкала 0–2).
        Используется как признак для ранжирующей модели.
        """
        try:
            rows = self._get(
                "applications",
                {"volunteer_profile_id": f"eq.{volunteer_id}", "limit": "500"},
                "status",
            )
        except SupabaseError:
            return None
        if not isinstance(rows, list) or not rows:
            return None
        terminal = [r for r in rows if str(r.get("status") or "").lower() in (
            self._OUTCOME_CANCELLED | self._OUTCOME_PARTIAL | self._OUTCOME_COMPLETED
        )]
        if not terminal:
            return None
        avg = round(sum(self.outcome_label(r.get("status")) for r in terminal) / len(terminal), 4)
        return {"volunteer_avg_outcome": avg, "outcomes_analysed": len(terminal)}

    def compute_volunteer_workload(self, volunteer_id):
        """
        Правило 16: подсчёт активных задач из актуальных статусов заявок волонтёра.
        Активные статусы: 'invite' (подтверждено НКО) и 'active' (в работе).
        """
        _ACTIVE = {"invite", "active", "in_progress", "accepted"}
        try:
            rows = self._get(
                "applications",
                {"volunteer_profile_id": f"eq.{volunteer_id}", "limit": "200"},
                "status",
            )
        except SupabaseError:
            return None
        if not isinstance(rows, list):
            return None
        active_count = sum(1 for r in rows if str(r.get("status") or "").lower() in _ACTIVE)
        return {"active_tasks_count": active_count}

    # ------------------------------------------------------------------
    # NGO reliability (Правило 15)
    # ------------------------------------------------------------------

    def compute_ngo_reliability(self, ngo_id):
        """
        Правило 15: вычисляет avg_response_time_hours и ngo_reliability_score
        на основе фактического времени реакции НКО на отклики волонтёров.
        """
        # Шаг 1: получаем task_id задач этой НКО
        try:
            tasks = self._get("tasks", {"ngo_profile_id": f"eq.{ngo_id}", "limit": "200"}, "id")
        except SupabaseError:
            return None
        task_ids = [str(t["id"]) for t in (tasks or []) if t.get("id")]
        if not task_ids:
            return None

        # Шаг 2: запрашиваем заявки с payload для агрегации отзывов (Правило 24)
        ids_str = ",".join(task_ids[:50])
        endpoint = (
            f"{self.url}/rest/v1/applications"
            f"?select=status,created_at,updated_at,payload"
            f"&task_id=in.({ids_str})"
            f"&limit=500"
        )
        req = Request(endpoint, headers={
            "apikey": self.anon_key,
            "Authorization": f"Bearer {self.anon_key}",
            "Accept": "application/json",
        })
        try:
            with urlopen(req, timeout=15) as resp:
                apps = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

        if not isinstance(apps, list) or not apps:
            return None

        # Шаг 3: вычисляем метрики
        response_hours = []
        responded = 0
        for app in apps:
            status = str(app.get("status") or "").lower()
            if status == "review":
                continue
            responded += 1
            created_s = app.get("created_at")
            updated_s = app.get("updated_at")
            if created_s and updated_s:
                try:
                    dt_c = datetime.fromisoformat(str(created_s).replace("Z", "+00:00"))
                    dt_u = datetime.fromisoformat(str(updated_s).replace("Z", "+00:00"))
                    h = max(0.0, (dt_u - dt_c).total_seconds() / 3600)
                    if h > 0:
                        response_hours.append(h)
                except (ValueError, TypeError):
                    pass

        total = len(apps)
        response_rate = round(responded / max(1, total), 4)
        avg_hours = round(sum(response_hours) / max(1, len(response_hours)), 1) if response_hours else None

        # Правило 24: агрегация оценок волонтёров (ratings.taskAccuracy/communication/experience)
        vol_rating_sums = []
        for app in apps:
            vol_review = ((app.get("payload") or {}).get("reviews") or {}).get("volunteer") or {}
            ratings = vol_review.get("ratings") or {}
            vals = [v for v in ratings.values() if isinstance(v, (int, float)) and 1 <= v <= 10]
            if vals:
                vol_rating_sums.append(sum(vals) / len(vals))

        speed_score = math.exp(-max(0, (avg_hours or 168) - 24) / 48)

        if vol_rating_sums:
            avg_vol_rating_norm = round(sum(vol_rating_sums) / len(vol_rating_sums) / 10.0, 4)
            # Надёжность: скорость 50% + охват 20% + оценки волонтёров 30%
            reliability = round(min(1.0, speed_score * 0.5 + response_rate * 0.2 + avg_vol_rating_norm * 0.3), 4)
        else:
            avg_vol_rating_norm = None
            # Надёжность без отзывов: скорость 70% + охват 30%
            reliability = round(min(1.0, speed_score * 0.7 + response_rate * 0.3), 4)

        result = {
            "avg_response_time_hours": int(avg_hours) if avg_hours else 168,
            "ngo_reliability_score": reliability,
            "applications_analysed": total,
            "response_rate": response_rate,
        }
        if avg_vol_rating_norm is not None:
            result["ngo_review_avg_rating"] = avg_vol_rating_norm
        return result

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    def get_candidate_tasks(self, volunteer_id):
        rows = self._get(
            "tasks",
            {"status": "eq.published", "limit": "600"},
            "id,ngo_profile_id,title,description,format,skills,"
            "date_start,date_end,status,payload,created_at,updated_at,"
            "ngo_profiles(id,org_name,about,avg_response_time_hours,ngo_reliability_score,complaint_rate)",
        )
        tasks = [self._map_task(row) for row in (rows or [])]
        return pre_filter_tasks(tasks)

    def _map_task(self, row):
        payload = _safe_task_payload(row.get("payload") or {})
        ngo = row.get("ngo_profiles") or {}
        ngo_about = ngo.get("about") or {}

        about_task = row.get("description") or payload.get("description") or ""
        work_to_do = payload.get("actionItems") or ""
        useful_skills = row.get("skills") or payload.get("skills") or ""
        direction_work = payload.get("directions") or ""
        region = payload.get("city") or ngo_about.get("city") or ""

        return {
            "task_id": str(row["id"]),
            "ngo_id": str(row.get("ngo_profile_id") or ""),
            "title": row.get("title") or "",
            "about_task": about_task,
            "work_to_do": work_to_do,
            "useful_skills": useful_skills,
            "direction_work": direction_work,
            "region": region,
            "participation_type": row.get("format") or payload.get("format") or "",
            "date_start": str(row.get("date_start") or payload.get("dateStart") or ""),
            "date_end": str(row.get("date_end") or payload.get("dateEnd") or ""),
            "publication_status": row.get("status") or "published",
            "ngo_name": ngo.get("org_name") or "НКО",
            "capacity": safe_int(payload.get("capacity"), 1),
            "current_applications": 0,
            "task_quality_score": _calc_description_quality_score(
                about_task, work_to_do, useful_skills, direction_work, region
            ),
            "is_duplicate_candidate": 0,
            "created_at": str(row.get("created_at") or ""),
            "updated_at": str(row.get("updated_at") or payload.get("updatedAt") or ""),
            "payload": payload,
            # keep raw NGO for get_ngos_for_tasks
            "_ngo": ngo,
            "ngo_profiles": {
                "org_name": ngo.get("org_name") or "НКО",
                "about": ngo_about,
                "contacts": {},
            },
        }

    def get_ngos_for_tasks(self, tasks):
        result = {}
        for task in tasks:
            ngo_id = task.get("ngo_id")
            if not ngo_id or ngo_id in result:
                continue
            ngo = task.get("_ngo") or {}
            result[ngo_id] = {
                "ngo_id": ngo_id,
                "ngo_name": ngo.get("org_name") or "НКО",
                "ngo_city_clean": (ngo.get("about") or {}).get("city") or "",
                "avg_response_time_hours": safe_int(ngo.get("avg_response_time_hours"), 24),
                "ngo_reliability_score": safe_float(ngo.get("ngo_reliability_score"), 0.5),
                "complaint_rate": safe_float(ngo.get("complaint_rate")),
            }
        return result
