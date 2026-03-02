from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional, Tuple

from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Q, QuerySet
from django.http import QueryDict
from django.utils import timezone

from ..models import Feedback


@dataclass(frozen=True)
class FeedbackListParams:
    q: str = ""
    username: str = ""
    patient_id: str = ""
    roi_label: str = ""
    rating: str = ""
    date_from: str = ""
    date_to: str = ""
    sort_by: str = "updated_at"
    order: str = "desc"
    page: int = 1
    page_size: int = 25


SORT_FIELDS = {
    "updated_at": "updated_at",
    "created_at": "created_at",
    "username": "user__username",
    "patient_id": "patient__patient_id",
    "roi": "common_roi_label",
    "rt1_rating": "rt1_rating",
    "rt2_rating": "rt2_rating",
}


def _parse_int(value: Optional[str], default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _parse_date(value: str) -> Optional[datetime]:
    value = (value or "").strip()
    if not value:
        return None
    try:
        dt = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None
    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt


def parse_feedback_list_params(query_params: QueryDict) -> FeedbackListParams:
    page_size = _parse_int(query_params.get("page_size"), 25)
    if page_size not in {10, 25, 50, 100}:
        page_size = 25

    order = (query_params.get("order") or "desc").lower()
    if order not in {"asc", "desc"}:
        order = "desc"

    sort_by = (query_params.get("sort_by") or "updated_at").strip()
    if sort_by not in SORT_FIELDS:
        sort_by = "updated_at"

    return FeedbackListParams(
        q=(query_params.get("q") or "").strip(),
        username=(query_params.get("username") or "").strip(),
        patient_id=(query_params.get("patient_id") or "").strip(),
        roi_label=(query_params.get("roi_label") or "").strip(),
        rating=(query_params.get("rating") or "").strip(),
        date_from=(query_params.get("date_from") or "").strip(),
        date_to=(query_params.get("date_to") or "").strip(),
        sort_by=sort_by,
        order=order,
        page=_parse_int(query_params.get("page"), 1) or 1,
        page_size=page_size,
    )


def build_feedback_queryset(*, scope: str, user: User, params: FeedbackListParams) -> QuerySet[Feedback]:
    qs = Feedback.objects.select_related("user", "patient", "roi_rt1", "roi_rt2")

    if scope == "user":
        qs = qs.filter(user=user)

    if params.username:
        qs = qs.filter(user__username__icontains=params.username)

    if params.patient_id:
        qs = qs.filter(patient__patient_id__icontains=params.patient_id)

    if params.roi_label:
        qs = qs.filter(common_roi_label__icontains=params.roi_label)

    if params.q:
        qs = qs.filter(
            Q(user__username__icontains=params.q)
            | Q(patient__patient_id__icontains=params.q)
            | Q(patient__patient_name__icontains=params.q)
            | Q(common_roi_label__icontains=params.q)
            | Q(comment__icontains=params.q)
        )

    rating_value = (params.rating or "").strip()
    if rating_value:
        try:
            r = int(rating_value)
            qs = qs.filter(Q(rt1_rating=r) | Q(rt2_rating=r))
        except (TypeError, ValueError):
            pass

    dt_from = _parse_date(params.date_from)
    if dt_from:
        qs = qs.filter(updated_at__gte=dt_from)

    dt_to = _parse_date(params.date_to)
    if dt_to:
        qs = qs.filter(updated_at__lte=dt_to)

    sort_field = SORT_FIELDS.get(params.sort_by, "updated_at")
    prefix = "" if params.order == "asc" else "-"
    qs = qs.order_by(f"{prefix}{sort_field}", "-id")

    return qs


def paginate_feedback(qs: QuerySet[Feedback], *, params: FeedbackListParams):
    paginator = Paginator(qs, params.page_size)
    page_obj = paginator.get_page(params.page)
    return page_obj


def build_querystring_without_page(query_params: QueryDict) -> str:
    qp = query_params.copy()
    qp.pop("page", None)
    return qp.urlencode()


def build_querystring(query_params: QueryDict, overrides: Dict[str, str]) -> str:
    qp = query_params.copy()
    for k, v in overrides.items():
        qp[k] = v
    return qp.urlencode()
