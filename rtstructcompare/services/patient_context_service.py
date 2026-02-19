from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.db.models import Q, Count

from ..models import (
    AssignmentGroup,
    DICOMSeries,
    DICOMStudy,
    Feedback,
    Patient,
    Roi,
)


def is_admin_user(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)


def build_patient_context(
    user,
    search_query,
    group_id=None,
    feedback_status=None,
    page_number=None,
    paginate=False,
    page_size=8,
):
    admin_user = is_admin_user(user)
    if admin_user:
        assignment_groups_qs = AssignmentGroup.objects.filter(created_by=user)
        assigned_patients_qs = Patient.objects.all()
    else:
        assignment_groups_qs = AssignmentGroup.objects.filter(users=user)
        assigned_patients_qs = Patient.objects.filter(
            Q(assignments__user=user)
            | Q(group_assignments__group__users=user)
        ).distinct()

    assignment_groups_qs = assignment_groups_qs.order_by("name").prefetch_related("users")
    selected_group = None
    if group_id:
        selected_group = assignment_groups_qs.filter(id=group_id).first()
        if not selected_group:
            group_id = None

    if selected_group:
        assigned_patients_qs = assigned_patients_qs.filter(
            group_assignments__group=selected_group
        ).distinct()

    patients_qs = assigned_patients_qs

    if search_query:
        patients_qs = patients_qs.filter(
            Q(patient_id__icontains=search_query)
            | Q(patient_name__icontains=search_query)
        )

    feedback_status = (feedback_status or "").strip().lower()
    valid_feedback_status = {"pending", "done", "not_started"}
    if feedback_status not in valid_feedback_status:
        feedback_status = ""

    assigned_patients_count = assigned_patients_qs.count()
    assigned_studies_count = DICOMStudy.objects.filter(
        patient__in=assigned_patients_qs
    ).count()
    assigned_series_count = DICOMSeries.objects.filter(
        study__patient__in=assigned_patients_qs
    ).count()

    feedback_qs = (
        Feedback.objects.filter(
            user=user,
            patient__in=assigned_patients_qs,
        )
        .select_related("patient", "roi_rt1", "roi_rt2")
        .order_by("-updated_at")
    )
    feedback_done_count = feedback_qs.count()
    reviewed_patients_count = feedback_qs.values("patient_id").distinct().count()
    pending_feedback_count = max(assigned_patients_count - reviewed_patients_count, 0)
    completion_rate = (
        round((reviewed_patients_count / assigned_patients_count) * 100)
        if assigned_patients_count
        else 0
    )
    recent_feedbacks = list(feedback_qs[:8])
    last_feedback = feedback_qs.first()

    roi_counts = (
        Roi.objects.filter(rtstruct__instance__series__study__patient__in=patients_qs)
        .values("rtstruct__instance__series__study__patient_id")
        .annotate(total=Count("id", distinct=True))
    )
    roi_count_map = {
        entry["rtstruct__instance__series__study__patient_id"]: entry["total"]
        for entry in roi_counts
    }
    feedback_counts = (
        Feedback.objects.filter(
            user=user, patient__in=patients_qs, roi_rt1__isnull=False
        )
        .exclude(rt1_rating__isnull=True, rt2_rating__isnull=True)
        .values("patient_id")
        .annotate(total=Count("common_roi_label", distinct=True))
    )
    feedback_count_map = {entry["patient_id"]: entry["total"] for entry in feedback_counts}

    patients_data = []
    for patient in patients_qs:
        studies = DICOMStudy.objects.filter(patient=patient)
        patient_studies_count = studies.count()

        patient_series_count = 0
        studies_data = []
        for study in studies:
            series = DICOMSeries.objects.filter(study=study)
            series_count = series.count()
            patient_series_count += series_count

            studies_data.append({
                "study": study,
                "series_count": series_count,
            })

        total_rois = roi_count_map.get(patient.id, 0)
        feedback_roi_count = feedback_count_map.get(patient.id, 0)
        pending_roi_count = max(total_rois - feedback_roi_count, 0)

        if total_rois == 0 or feedback_roi_count == 0:
            feedback_state = "not_started"
        elif pending_roi_count == 0:
            feedback_state = "done"
        else:
            feedback_state = "pending"

        patients_data.append({
            "patient": patient,
            "total_studies": patient_studies_count,
            "total_series": patient_series_count,
            "total_rois": total_rois,
            "feedback_roi_count": feedback_roi_count,
            "pending_roi_count": pending_roi_count,
            "feedback_status": feedback_state,
            "studies": studies_data,
        })

    if feedback_status:
        patients_data = [
            patient_data
            for patient_data in patients_data
            if patient_data["feedback_status"] == feedback_status
        ]

    total_patients = len(patients_data)
    total_studies = sum(patient["total_studies"] for patient in patients_data)
    total_series = sum(patient["total_series"] for patient in patients_data)

    page_obj = None
    if paginate:
        paginator = Paginator(patients_data, page_size)
        page_obj = paginator.get_page(page_number)
        patients_data = list(page_obj.object_list)

    query_params = {}
    if search_query:
        query_params["search"] = search_query
    if group_id:
        query_params["group"] = group_id
    if feedback_status:
        query_params["feedback_status"] = feedback_status
    pagination_querystring = urlencode(query_params)

    context = {
        "patients": patients_data,
        "total_patients": total_patients,
        "total_studies": total_studies,
        "total_series": total_series,
        "search_query": search_query,
        "is_admin": admin_user,
        "assigned_patients_count": assigned_patients_count,
        "assigned_studies_count": assigned_studies_count,
        "assigned_series_count": assigned_series_count,
        "feedback_done_count": feedback_done_count,
        "reviewed_patients_count": reviewed_patients_count,
        "pending_feedback_count": pending_feedback_count,
        "completion_rate": completion_rate,
        "recent_feedbacks": recent_feedbacks,
        "last_feedback": last_feedback,
        "assignment_groups": assignment_groups_qs,
        "selected_group": selected_group,
        "group_filter": str(selected_group.id) if selected_group else "",
        "feedback_status": feedback_status,
        "page_obj": page_obj,
        "is_paginated": page_obj.has_other_pages() if page_obj else False,
        "pagination_querystring": pagination_querystring,
    }

    return context
