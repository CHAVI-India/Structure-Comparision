from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Q, Count, Min, Exists, OuterRef
from django.db.models.functions import TruncDate
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
            "deactivate_user": self._handle_deactivate_user,
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

    def _handle_deactivate_user(self, post_data: QueryDict, **_) -> AdminDashboardStatus:
        user_id = (post_data.get("user_id") or "").strip()
        if not user_id:
            return AdminDashboardStatus("Select a user to deactivate.", "error")

        target = User.objects.filter(id=user_id).first()
        if not target:
            return AdminDashboardStatus("User not found.", "error")
        if target.is_staff:
            return AdminDashboardStatus("Staff users cannot be deactivated here.", "error")

        target.is_active = False
        target.save(update_fields=["is_active"])

        deleted_count, _ = PatientAssignment.objects.filter(user=target).delete()
        return AdminDashboardStatus(
            f'Deactivated user "{target.username}" and removed {deleted_count} assignment(s).',
            "success",
        )

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

    def _handle_unassign_all(self, post_data: QueryDict, **_) -> AdminDashboardStatus:
        patient_ids = [pid for pid in post_data.getlist("bulk_patient_ids") if pid]
        if not patient_ids:
            patient_ids = [pid for pid in post_data.getlist("patient_ids") if pid]
        group_id = (post_data.get("group_id") or "").strip()
        user_ids = [uid for uid in post_data.getlist("user_ids") if uid]

        if patient_ids and (group_id or user_ids):
            patients = list(Patient.objects.filter(id__in=patient_ids))
            if not patients:
                return AdminDashboardStatus("No valid patients selected.", "error")

            selected_group = None
            if group_id:
                selected_group = self._get_group_for_user(group_id)
                if not selected_group:
                    return AdminDashboardStatus("Group not found or access denied.", "error")

            target_users = list(User.objects.filter(id__in=user_ids)) if user_ids else []
            return self._unassign_patients(target_users, selected_group, patients)

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

    latest_feedbacks = feedbacks[:10]

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

    assignment_rows = assignment_rows[:8]

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
    users_with_feedback_count = (
        Feedback.objects.exclude(user__isnull=True)
        .values("user_id")
        .distinct()
        .count()
    )

    # Oldest pending patients (top 6)
    pending_patients_rows = []
    if pending_patients_ids:
        pending_sorted = []
        for pid in pending_patients_ids:
            assigned_at = assignment_first_map.get(pid)
            if not assigned_at:
                continue
            pending_sorted.append((pid, assigned_at))
        pending_sorted.sort(key=lambda item: item[1])

        for pid, assigned_at in pending_sorted[:6]:
            row = assignment_map.get(pid)
            if not row:
                continue
            days = max((now - assigned_at).days, 0)
            pending_patients_rows.append(
                {
                    "patient_id": row["patient"].patient_id,
                    "patient_uuid": str(row["patient"].id),
                    "pending_days": days,
                    "assigned_users": sorted(row.get("usernames") or []),
                    "groups": sorted(row.get("groups") or []),
                }
            )

    # Users with highest pending workload (top 6)
    pending_by_user = (
        pending_assignment_qs.values("user_id", "user__username")
        .annotate(pending_pairs=Count("id"))
        .order_by("-pending_pairs", "user__username")
    )
    top_pending_users = [
        {
            "user_id": str(row["user_id"]),
            "username": row["user__username"],
            "pending_pairs": int(row["pending_pairs"] or 0),
        }
        for row in pending_by_user[:6]
    ]

    # Alerts / needs attention
    alerts = []
    if unassigned_patients_count > 0:
        alerts.append(
            {
                "level": "warn",
                "title": "Unassigned patients",
                "message": f"{unassigned_patients_count} patient(s) are not assigned to any user/group.",
            }
        )
    if oldest_pending_days >= 7:
        alerts.append(
            {
                "level": "warn",
                "title": "Stale pending reviews",
                "message": f"Oldest pending review is {oldest_pending_days} day(s) old.",
            }
        )
    if idle_reviewers_count > 0:
        alerts.append(
            {
                "level": "info",
                "title": "Idle reviewers",
                "message": f"{idle_reviewers_count} reviewer(s) have assignments but no feedback yet.",
            }
        )
    if recent_feedback_count == 0:
        alerts.append(
            {
                "level": "info",
                "title": "No recent feedback",
                "message": "No feedback updates in the last 7 days.",
            }
        )

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
            "users_with_feedback": users_with_feedback_count,
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
        "assignment_rows": assignment_rows,
        "feedbacks": latest_feedbacks,
        "assigned_users_count": len(assigned_user_ids),
        "assigned_patients_count": assigned_patients_count,
        "total_assignments": total_assignments,
        "assignment_groups": assignment_groups,
        "group_assignments": group_assignments,
        "assigned_feedbacks_count": assigned_feedbacks_count,
        "patient_assignments_map": patient_assignment_map,
        "dashboard_metrics": dashboard_metrics,
        "oldest_pending_patients": pending_patients_rows,
        "top_pending_users": top_pending_users,
        "dashboard_alerts": alerts,
    }


def build_admin_dashboard_chart_data(*, range_days: int = 30) -> dict:
    """Returns compact time-series data for charts on the admin dashboard.

    The returned dict is JSON-serializable.
    """
    safe_range = max(7, min(int(range_days or 30), 90))
    start_dt = timezone.now() - timedelta(days=safe_range - 1)
    start_date = start_dt.date()

    def _blank_series() -> dict:
        labels = [(start_date + timedelta(days=i)).isoformat() for i in range(safe_range)]
        index = {label: 0 for label in labels}
        return {"labels": labels, "index": index}

    assignments_series = _blank_series()
    feedback_series = _blank_series()

    assignment_counts = (
        PatientAssignment.objects.filter(assigned_at__date__gte=start_date)
        .annotate(day=TruncDate("assigned_at"))
        .values("day")
        .annotate(count=Count("id"))
    )
    for row in assignment_counts:
        day = row.get("day")
        if day:
            key = day.isoformat()
            if key in assignments_series["index"]:
                assignments_series["index"][key] += int(row.get("count") or 0)

    group_assignment_counts = (
        GroupPatientAssignment.objects.filter(assigned_at__date__gte=start_date)
        .annotate(day=TruncDate("assigned_at"))
        .values("day")
        .annotate(count=Count("id"))
    )
    for row in group_assignment_counts:
        day = row.get("day")
        if day:
            key = day.isoformat()
            if key in assignments_series["index"]:
                assignments_series["index"][key] += int(row.get("count") or 0)

    feedback_counts = (
        Feedback.objects.filter(updated_at__date__gte=start_date)
        .annotate(day=TruncDate("updated_at"))
        .values("day")
        .annotate(count=Count("id"))
    )
    for row in feedback_counts:
        day = row.get("day")
        if day:
            key = day.isoformat()
            if key in feedback_series["index"]:
                feedback_series["index"][key] += int(row.get("count") or 0)

    labels = assignments_series["labels"]
    assignments_by_day = [assignments_series["index"][d] for d in labels]
    feedback_by_day = [feedback_series["index"][d] for d in labels]

    assigned_patients_qs = (
        Patient.objects.filter(Q(assignments__isnull=False) | Q(group_assignments__isnull=False))
        .distinct()
    )
    assigned_patients_count = assigned_patients_qs.count()

    reviewed_patient_ids = set(Feedback.objects.values_list("patient_id", flat=True).distinct())
    reviewed_count = sum(1 for pid in assigned_patients_qs.values_list("id", flat=True) if pid in reviewed_patient_ids)
    pending_count = max(assigned_patients_count - reviewed_count, 0)

    return {
        "range_days": safe_range,
        "labels": labels,
        "assignments_by_day": assignments_by_day,
        "feedback_by_day": feedback_by_day,
        "review_breakdown": {
            "reviewed": reviewed_count,
            "pending": pending_count,
        },
    }


def build_admin_assignments_context(user: User, query_params: QueryDict, paginate=True) -> dict:
    users = User.objects.order_by("username")
    patients = Patient.objects.order_by("patient_id")
    assignments = PatientAssignment.objects.select_related("user", "patient").order_by("-assigned_at")
    group_assignments = (
        GroupPatientAssignment.objects.select_related("group", "patient")
        .prefetch_related("group__users")
        .order_by("-assigned_at")
    )
    assignment_groups = AssignmentGroup.objects.filter(created_by=user).prefetch_related("users")

    # Filters (server-side)
    search_term = (query_params.get("q") or "").strip()
    status_filter = (query_params.get("status") or "").strip().lower()
    group_filter = (query_params.get("group") or "").strip()
    page_number = query_params.get("page") or 1

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

    feedback_patient_ids = set(Feedback.objects.values_list("patient_id", flat=True).distinct())

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

    # Search filter
    if search_term:
        lowered = search_term.lower()
        assignment_rows = [
            row
            for row in assignment_rows
            if lowered in (row["patient"].patient_id or "").lower()
            or lowered in (getattr(row["patient"], "patient_name", "") or "").lower()
            or any(lowered in u.lower() for u in row.get("usernames") or [])
            or any(lowered in g.lower() for g in row.get("groups") or [])
        ]

    # Status filter
    if status_filter in {"reviewed", "pending", "unassigned"}:
        if status_filter == "reviewed":
            assignment_rows = [row for row in assignment_rows if row.get("review_state") == "Reviewed"]
        elif status_filter == "pending":
            assignment_rows = [row for row in assignment_rows if row.get("review_state") != "Reviewed"]
        elif status_filter == "unassigned":
            assignment_rows = [row for row in assignment_rows if not row.get("usernames") and not row.get("groups")]

    # Group filter (id)
    if group_filter:
        assignment_rows = [
            row for row in assignment_rows if group_filter in (row.get("group_ids") or set())
        ]

    # --- User-centric assignment rows ---
    user_map = {
        u.id: {
            "user": u,
            "patient_ids": set(),
            "groups": set(),
            "group_ids": set(),
            "last_assigned": None,
        }
        for u in users
    }

    # Re-calculate assignments for users
    for assignment in assignments:
        u_entry = user_map.get(assignment.user_id)
        if u_entry:
            u_entry["patient_ids"].add(assignment.patient_id)
            if u_entry["last_assigned"] is None or assignment.assigned_at > u_entry["last_assigned"]:
                u_entry["last_assigned"] = assignment.assigned_at

    for assignment in group_assignments:
        for group_user in assignment.group.users.all():
            u_entry = user_map.get(group_user.id)
            if u_entry:
                u_entry["patient_ids"].add(assignment.patient_id)
                u_entry["groups"].add(assignment.group.name)
                u_entry["group_ids"].add(str(assignment.group_id))
                if u_entry["last_assigned"] is None or assignment.assigned_at > u_entry["last_assigned"]:
                    u_entry["last_assigned"] = assignment.assigned_at

    user_patient_feedback = set(
        Feedback.objects.values_list("user_id", "patient_id").distinct()
    )

    p_id_map = {p.id: p for p in patients}
    user_assignment_rows = []
    for u_id, entry in user_map.items():
        # Logic: If we are not filtering by "unassigned", we might want to skip users with 0 patients
        # However, to keep it consistent with the patient table, let's include those who pass filters.
        
        patients_list = []
        reviewed_count = 0
        for pid in entry["patient_ids"]:
            p_obj = p_id_map.get(pid)
            if p_obj:
                patients_list.append(p_obj)
                if (u_id, pid) in user_patient_feedback:
                    reviewed_count += 1
        
        entry["patients"] = sorted(patients_list, key=lambda p: p.patient_id)
        entry["total_count"] = len(patients_list)
        entry["reviewed_count"] = reviewed_count
        entry["pending_count"] = entry["total_count"] - reviewed_count
        entry["reviewed_percent"] = round(reviewed_count / entry["total_count"] * 100) if entry["total_count"] > 0 else 0
        entry["groups"] = sorted(list(entry["groups"]))
        
        user_assignment_rows.append(entry)

    # Search filter for users
    if search_term:
        lowered = search_term.lower()
        user_assignment_rows = [
            row
            for row in user_assignment_rows
            if lowered in row["user"].username.lower()
            or any(lowered in p.patient_id.lower() for p in row["patients"])
            or any(lowered in g.lower() for g in row["groups"])
        ]

    # Sort users: most recently assigned first
    user_assignment_rows.sort(
        key=lambda r: (r.get("last_assigned") is not None, r.get("last_assigned")),
        reverse=True,
    )

    # Apply Status and Group filters to user rows
    if status_filter:
        if status_filter == "reviewed":
            user_assignment_rows = [row for row in user_assignment_rows if row.get("total_count") > 0 and row.get("pending_count") == 0]
        elif status_filter == "pending":
            user_assignment_rows = [row for row in user_assignment_rows if row.get("pending_count") > 0]
        elif status_filter == "unassigned":
            user_assignment_rows = [row for row in user_assignment_rows if row.get("total_count") == 0]
    else:
        # Default: hide unassigned users unless specifically requested
        user_assignment_rows = [row for row in user_assignment_rows if row.get("total_count") > 0]

    if group_filter:
        user_assignment_rows = [
            row for row in user_assignment_rows if group_filter in row.get("group_ids", set())
        ]

    # Re-paginating user rows after filters
    if paginate:
        user_page_number = query_params.get("user_page") or 1
        user_paginator = Paginator(user_assignment_rows, 8)
        user_page_obj = user_paginator.get_page(user_page_number)
        final_user_rows = user_page_obj.object_list
    else:
        user_page_obj = None
        final_user_rows = user_assignment_rows

    user_query_params_wo_page = query_params.copy()
    user_query_params_wo_page.pop("user_page", None)
    user_querystring = user_query_params_wo_page.urlencode()
    user_page_prefix = f"?{user_querystring}&" if user_querystring else "?"

    # Sort: most recently assigned first
    assignment_rows.sort(
        key=lambda r: (r.get("last_assigned") is not None, r.get("last_assigned")),
        reverse=True,
    )

    if paginate:
        paginator = Paginator(assignment_rows, 8)
        page_obj = paginator.get_page(page_number)
        final_assignment_rows = page_obj.object_list
    else:
        page_obj = None
        final_assignment_rows = assignment_rows

    query_params_wo_page = query_params.copy()
    query_params_wo_page.pop("page", None)
    querystring = query_params_wo_page.urlencode()
    page_prefix = f"?{querystring}&" if querystring else "?"

    return {
        "users": users,
        "patients": patients,
        "assignments": assignments,
        "group_assignments": group_assignments,
        "assignment_groups": assignment_groups,
        "patient_assignments_map": patient_assignment_map,
        "assignment_rows": final_assignment_rows,
        "assignment_page_obj": page_obj,
        "assignment_page_prefix": page_prefix,
        "assignment_search": search_term,
        "assignment_status": status_filter,
        "assignment_group_filter": group_filter,
        "user_assignment_rows": final_user_rows,
        "user_page_obj": user_page_obj,
        "user_page_prefix": user_page_prefix,
    }
