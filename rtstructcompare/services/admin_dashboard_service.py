from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Q, Count, Min, Exists, OuterRef
from django.utils import timezone
from django.http import QueryDict

from ..models import (
    AssignmentGroup,
    Feedback,
    GroupPatientAssignment,
    Patient,
    PatientAssignment,
)


@dataclass
class AdminDashboardStatus:
    message: Optional[str] = None
    status_type: str = "info"


class AdminDashboardActionService:
    """Encapsulates admin dashboard POST side effects for easier testing."""

    def __init__(self, acting_user: User):
        self.user = acting_user

    def handle(self, post_data: QueryDict) -> AdminDashboardStatus:
        action = (post_data.get("action") or "").strip()
        if not action:
            return AdminDashboardStatus("Unknown action.", "error")

        handler_map = {
            "create_group": self._handle_create_group,
            "edit_group": self._handle_edit_group,
            "delete_group": self._handle_delete_group,
            "assign_groups": self._handle_assign_groups,
            "assign": self._handle_assignments,
            "unassign": self._handle_assignments,
            "unassign_all": self._handle_unassign_all,
        }
        handler = handler_map.get(action)
        if not handler:
            return AdminDashboardStatus("Unknown action.", "error")

        return handler(post_data, action=action)

    def _handle_create_group(self, post_data: QueryDict, **_) -> AdminDashboardStatus:
        group_name = (post_data.get("group_name") or "").strip()
        group_description = (post_data.get("group_description") or "").strip()
        group_user_ids = [uid for uid in post_data.getlist("group_user_ids") if uid]

        if not group_name:
            return AdminDashboardStatus("Group name is required.", "error")
        if not group_user_ids:
            return AdminDashboardStatus("Select at least one user for the group.", "error")

        group, created = AssignmentGroup.objects.get_or_create(
            name=group_name,
            created_by=self.user,
            defaults={"description": group_description},
        )
        if not created:
            return AdminDashboardStatus("A group with this name already exists.", "error")

        group.users.set(User.objects.filter(id__in=group_user_ids))
        return AdminDashboardStatus(f'Group "{group.name}" created.', "success")

    def _handle_edit_group(self, post_data: QueryDict, **_) -> AdminDashboardStatus:
        group_id = (post_data.get("group_id") or "").strip()
        group_name = (post_data.get("group_name") or "").strip()
        group_description = (post_data.get("group_description") or "").strip()
        group_user_ids = [uid for uid in post_data.getlist("group_user_ids") if uid]

        if not group_id:
            return AdminDashboardStatus("Select a group to edit.", "error")

        group = self._get_group_for_user(group_id)
        if not group:
            return AdminDashboardStatus("Group not found or access denied.", "error")
        if not group_name:
            return AdminDashboardStatus("Group name is required.", "error")
        if not group_user_ids:
            return AdminDashboardStatus("Select at least one user for the group.", "error")
        if (
            AssignmentGroup.objects.filter(name=group_name, created_by=self.user)
            .exclude(id=group.id)
            .exists()
        ):
            return AdminDashboardStatus("Another group with this name already exists.", "error")

        group.name = group_name
        group.description = group_description
        group.save(update_fields=["name", "description", "updated_at"])
        group.users.set(User.objects.filter(id__in=group_user_ids))
        return AdminDashboardStatus(f'Group "{group.name}" updated.', "success")

    def _handle_delete_group(self, post_data: QueryDict, **_) -> AdminDashboardStatus:
        group_id = (post_data.get("group_id") or "").strip()
        if not group_id:
            return AdminDashboardStatus("Select a group to delete.", "error")

        group = self._get_group_for_user(group_id)
        if not group:
            return AdminDashboardStatus("Group not found or access denied.", "error")

        group_name = group.name
        group.delete()
        return AdminDashboardStatus(f'Group "{group_name}" deleted.', "success")

    def _handle_assign_groups(self, post_data: QueryDict, **_) -> AdminDashboardStatus:
        bulk_group_ids = [gid for gid in post_data.getlist("bulk_group_ids") if gid]
        bulk_patient_ids = [pid for pid in post_data.getlist("bulk_patient_ids") if pid]

        if not bulk_group_ids or not bulk_patient_ids:
            return AdminDashboardStatus("Select at least one group and one patient.", "error")

        groups = list(
            AssignmentGroup.objects.filter(id__in=bulk_group_ids, created_by=self.user).prefetch_related(
                "users"
            )
        )
        if len(groups) != len(set(bulk_group_ids)):
            return AdminDashboardStatus("One or more selected groups could not be found.", "error")

        empty_groups = [group.name for group in groups if not group.users.exists()]
        if empty_groups:
            names = ", ".join(empty_groups)
            return AdminDashboardStatus(
                f"Add users to these groups before assigning patients: {names}", "error"
            )

        patients = list(Patient.objects.filter(id__in=bulk_patient_ids))
        if not patients:
            return AdminDashboardStatus("No valid patients selected.", "error")

        created_count = 0
        for group in groups:
            for patient in patients:
                _, created = GroupPatientAssignment.objects.get_or_create(
                    group=group,
                    patient=patient,
                )
                if created:
                    created_count += 1

        message = (
            f"Assigned {len(patients)} patient(s) across {len(groups)} group(s). "
            f"Created {created_count} new group assignment(s)."
        )
        return AdminDashboardStatus(message, "success")

    def _handle_assignments(self, post_data: QueryDict, *, action: str) -> AdminDashboardStatus:
        patient_ids = [pid for pid in post_data.getlist("patient_ids") if pid]
        user_ids = [uid for uid in post_data.getlist("user_ids") if uid]
        group_id = (post_data.get("group_id") or "").strip()

        if not patient_ids or (not user_ids and not group_id):
            return AdminDashboardStatus(
                "Select at least one user or a group, and at least one patient.", "error"
            )

        target_users = list(User.objects.filter(id__in=user_ids)) if user_ids else []
        selected_group = None
        if group_id:
            selected_group = AssignmentGroup.objects.filter(id=group_id).first()
            if not selected_group:
                return AdminDashboardStatus("Selected group not found.", "error")

        patients = list(Patient.objects.filter(id__in=patient_ids))
        if not patients:
            return AdminDashboardStatus("No valid patients selected.", "error")

        if action == "assign":
            return self._assign_patients(target_users, selected_group, patients)
        if action == "unassign":
            return self._unassign_patients(target_users, selected_group, patients)
        return AdminDashboardStatus("Unknown action.", "error")

    def _assign_patients(
        self,
        target_users: List[User],
        selected_group: Optional[AssignmentGroup],
        patients: List[Patient],
    ) -> AdminDashboardStatus:
        direct_created = 0
        group_created = 0

        for target_user in target_users:
            for patient in patients:
                _, created = PatientAssignment.objects.get_or_create(
                    user=target_user,
                    patient=patient,
                )
                if created:
                    direct_created += 1

        if selected_group:
            for patient in patients:
                _, created = GroupPatientAssignment.objects.get_or_create(
                    group=selected_group,
                    patient=patient,
                )
                if created:
                    group_created += 1

        message = (
            f"Assigned {direct_created} direct assignment(s) "
            f"and {group_created} group assignment(s)."
        )
        return AdminDashboardStatus(message, "success")

    def _unassign_patients(
        self,
        target_users: List[User],
        selected_group: Optional[AssignmentGroup],
        patients: List[Patient],
    ) -> AdminDashboardStatus:
        direct_deleted = 0
        group_deleted = 0

        if target_users:
            direct_deleted, _ = PatientAssignment.objects.filter(
                user__in=target_users,
                patient__in=patients,
            ).delete()

        if selected_group:
            group_deleted, _ = GroupPatientAssignment.objects.filter(
                group=selected_group,
                patient__in=patients,
            ).delete()

        message = (
            f"Removed {direct_deleted} direct assignment(s) "
            f"and {group_deleted} group assignment(s)."
        )
        return AdminDashboardStatus(message, "success")

    def _handle_unassign_all(self, *_args, **_kwargs) -> AdminDashboardStatus:
        direct_deleted, _ = PatientAssignment.objects.all().delete()
        group_deleted, _ = GroupPatientAssignment.objects.all().delete()
        message = (
            f"Removed {direct_deleted} direct assignment(s) "
            f"and {group_deleted} group assignment(s)."
        )
        return AdminDashboardStatus(message, "success")

    def _get_group_for_user(self, group_id: str) -> Optional[AssignmentGroup]:
        return AssignmentGroup.objects.filter(id=group_id, created_by=self.user).first()


def build_admin_dashboard_context(user: User, query_params: QueryDict) -> dict:
    users = User.objects.order_by("username")
    patients = Patient.objects.order_by("patient_id")
    assignments = (
        PatientAssignment.objects.select_related("user", "patient").order_by("-assigned_at")
    )
    group_assignments = (
        GroupPatientAssignment.objects.select_related("group", "patient")
        .prefetch_related("group__users")
        .order_by("-assigned_at")
    )
    assignment_groups = AssignmentGroup.objects.filter(created_by=user).prefetch_related("users")
    feedbacks = Feedback.objects.select_related("user", "patient", "roi_rt1", "roi_rt2").order_by(
        "-updated_at"
    )
    total_feedback_count = feedbacks.count()

    assigned_user_ids = set(assignments.values_list("user_id", flat=True).distinct())
    group_user_ids = set(
        group_assignments.values_list("group__users__id", flat=True).distinct()
    )
    assigned_user_ids = assigned_user_ids.union(group_user_ids)

    assigned_patients_qs = (
        Patient.objects.filter(Q(assignments__isnull=False) | Q(group_assignments__isnull=False))
        .distinct()
    )
    assigned_patients_ids = set(assigned_patients_qs.values_list("id", flat=True))
    assigned_patients_count = len(assigned_patients_ids)
    assigned_feedbacks_count = Feedback.objects.filter(user_id__in=assigned_user_ids).count()
    total_assignments = assignments.count() + group_assignments.count()

    assignment_map = {
        patient.id: {
            "patient": patient,
            "usernames": set(),
            "groups": set(),
            "last_assigned": None,
            "first_assigned": None,
            "user_ids": set(),
            "group_ids": set(),
        }
        for patient in patients
    }

    for assignment in assignments:
        entry = assignment_map.get(assignment.patient_id)
        if not entry:
            continue
        entry["usernames"].add(assignment.user.username)
        entry["user_ids"].add(str(assignment.user_id))
        if entry["last_assigned"] is None or assignment.assigned_at > entry["last_assigned"]:
            entry["last_assigned"] = assignment.assigned_at
        if entry["first_assigned"] is None or assignment.assigned_at < entry["first_assigned"]:
            entry["first_assigned"] = assignment.assigned_at

    for assignment in group_assignments:
        entry = assignment_map.get(assignment.patient_id)
        if not entry:
            continue
        entry["groups"].add(assignment.group.name)
        entry["group_ids"].add(str(assignment.group_id))
        for group_user in assignment.group.users.all():
            entry["usernames"].add(group_user.username)
            entry["user_ids"].add(str(group_user.id))
        if entry["last_assigned"] is None or assignment.assigned_at > entry["last_assigned"]:
            entry["last_assigned"] = assignment.assigned_at
        if entry["first_assigned"] is None or assignment.assigned_at < entry["first_assigned"]:
            entry["first_assigned"] = assignment.assigned_at

    # Precompute patient feedback info
    feedback_patient_rows = list(
        feedbacks.values("patient_id").annotate(first_feedback=Min("created_at"))
    )
    feedback_patient_ids = {row["patient_id"] for row in feedback_patient_rows}

    assignment_rows = []
    patient_assignment_map = {}
    for patient in patients:
        entry = assignment_map[patient.id]
        entry["usernames"] = sorted(entry["usernames"])
        entry["groups"] = sorted(entry["groups"])
        entry["review_state"] = "Reviewed" if patient.id in feedback_patient_ids else "Pending"
        assignment_rows.append(entry)

        patient_assignment_map[str(patient.id)] = {
            "user_ids": sorted(entry["user_ids"]),
            "group_ids": sorted(entry["group_ids"]),
        }

    assignment_page_number = query_params.get("assignment_page") or 1
    assignment_paginator = Paginator(assignment_rows, 8)
    assignment_page_obj = assignment_paginator.get_page(assignment_page_number)

    feedback_page_number = query_params.get("feedback_page") or 1
    feedback_paginator = Paginator(feedbacks, 10)
    feedback_page_obj = feedback_paginator.get_page(feedback_page_number)

    assignment_query_params = query_params.copy()
    assignment_query_params.pop("assignment_page", None)
    assignment_querystring = assignment_query_params.urlencode()
    assignment_page_prefix = f'?{assignment_querystring}&' if assignment_querystring else "?"

    feedback_query_params = query_params.copy()
    feedback_query_params.pop("feedback_page", None)
    feedback_querystring = feedback_query_params.urlencode()
    feedback_page_prefix = f'?{feedback_querystring}&' if feedback_querystring else "?"

    # Build dashboard metrics
    total_patients = patients.count()
    unassigned_patients_count = max(total_patients - assigned_patients_count, 0)

    fully_reviewed_patients = len(assigned_patients_ids.intersection(feedback_patient_ids))
    pending_review_patients = max(assigned_patients_count - fully_reviewed_patients, 0)

    assignment_first_map = {}
    for row in PatientAssignment.objects.values("patient_id").annotate(first_assigned=Min("assigned_at")):
        pid = row["patient_id"]
        assignment_first_map[pid] = row["first_assigned"]
    for row in GroupPatientAssignment.objects.values("patient_id").annotate(first_assigned=Min("assigned_at")):
        pid = row["patient_id"]
        current = assignment_first_map.get(pid)
        if current is None or (row["first_assigned"] and row["first_assigned"] < current):
            assignment_first_map[pid] = row["first_assigned"]

    pending_patients_ids = assigned_patients_ids.difference(feedback_patient_ids)
    oldest_pending_days = 0
    now = timezone.now()
    for pid in pending_patients_ids:
        assigned_at = assignment_first_map.get(pid)
        if assigned_at:
            delta_days = (now - assigned_at).days
            if delta_days > oldest_pending_days:
                oldest_pending_days = delta_days

    turnaround_days = []
    for row in feedback_patient_rows:
        pid = row["patient_id"]
        first_feedback = row["first_feedback"]
        assigned_at = assignment_first_map.get(pid)
        if assigned_at and first_feedback:
            delta = (first_feedback - assigned_at).total_seconds() / 86400
            if delta >= 0:
                turnaround_days.append(delta)
    avg_turnaround_days = round(sum(turnaround_days) / len(turnaround_days), 1) if turnaround_days else 0

    twelve_four_hours = timezone.now() - timedelta(days=7)
    recent_assignment_count = (
        PatientAssignment.objects.filter(assigned_at__gte=twelve_four_hours).count()
        + GroupPatientAssignment.objects.filter(assigned_at__gte=twelve_four_hours).count()
    )
    recent_feedback_count = Feedback.objects.filter(updated_at__gte=twelve_four_hours).count()

    # Pending assignment user-level metrics
    pending_assignment_qs = PatientAssignment.objects.annotate(
        has_feedback=Exists(
            Feedback.objects.filter(
                user_id=OuterRef("user_id"),
                patient_id=OuterRef("patient_id"),
            )
        )
    ).filter(has_feedback=False)
    pending_assignment_pairs = pending_assignment_qs.count()
    pending_assignment_user_count = pending_assignment_qs.values("user_id").distinct().count()

    active_reviewers_count = (
        Feedback.objects.filter(user_id__in=assigned_user_ids)
        .values("user_id")
        .distinct()
        .count()
    )
    idle_reviewers_count = max(len(assigned_user_ids) - active_reviewers_count, 0)

    dashboard_metrics = {
        "coverage": {
            "total_patients": total_patients,
            "assigned_patients": assigned_patients_count,
            "unassigned_patients": unassigned_patients_count,
            "fully_reviewed_patients": fully_reviewed_patients,
            "pending_review_patients": pending_review_patients,
        },
        "feedback": {
            "total_feedback": total_feedback_count,
            "pending_assignment_pairs": pending_assignment_pairs,
            "pending_assignment_users": pending_assignment_user_count,
            "active_reviewers": active_reviewers_count,
            "idle_reviewers": idle_reviewers_count,
        },
        "activity": {
            "assignments_last_7_days": recent_assignment_count,
            "feedback_last_7_days": recent_feedback_count,
            "avg_turnaround_days": avg_turnaround_days,
            "oldest_pending_days": oldest_pending_days,
        },
    }

    return {
        "users": users,
        "patients": patients,
        "assignments": assignments,
        "assignment_rows": assignment_page_obj.object_list,
        "assignment_page_obj": assignment_page_obj,
        "feedback_page_obj": feedback_page_obj,
        "feedbacks": feedback_page_obj.object_list,
        "assigned_users_count": len(assigned_user_ids),
        "assigned_patients_count": assigned_patients_count,
        "total_assignments": total_assignments,
        "assignment_groups": assignment_groups,
        "group_assignments": group_assignments,
        "assigned_feedbacks_count": assigned_feedbacks_count,
        "assignment_page_prefix": assignment_page_prefix,
        "feedback_page_prefix": feedback_page_prefix,
        "patient_assignments_map": patient_assignment_map,
        "dashboard_metrics": dashboard_metrics,
    }
