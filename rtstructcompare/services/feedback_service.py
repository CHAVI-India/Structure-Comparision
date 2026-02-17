from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from django.contrib.auth.models import User

from ..models import Feedback, Patient, Roi, RTStruct


@dataclass
class FeedbackSubmissionResult:
    success: bool
    status_code: int
    saved_count: int = 0
    error: Optional[str] = None
    errors: List[str] = field(default_factory=list)


class FeedbackSubmissionService:
    """Encapsulates feedback submission validation and persistence."""

    def __init__(self, user: User):
        self.user = user

    def submit(self, payload: Dict) -> FeedbackSubmissionResult:
        patient_id = payload.get("patient_id")
        if not patient_id:
            return FeedbackSubmissionResult(False, 400, error="Missing patient_id")

        ratings = payload.get("ratings")
        if not ratings or not isinstance(ratings, list):
            return FeedbackSubmissionResult(False, 400, error="Missing ratings")

        try:
            patient = Patient.objects.get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return FeedbackSubmissionResult(False, 400, error="Invalid patient_id")

        rt1_label = (payload.get("rt1_label") or "").strip()
        rt2_label = (payload.get("rt2_label") or "").strip()
        rt1_sop_uid = (payload.get("rt1_sop_uid") or "").strip()
        rt2_sop_uid = (payload.get("rt2_sop_uid") or "").strip()
        study_uid = (payload.get("study_uid") or "").strip()

        rtstruct2 = None
        if rt2_sop_uid:
            try:
                rtstruct2 = RTStruct.objects.get(instance__sop_instance_uid=rt2_sop_uid)
            except RTStruct.DoesNotExist:
                return FeedbackSubmissionResult(False, 400, error="Invalid rt2_sop_uid")

        saved = 0
        errors: List[str] = []
        for item in ratings:
            roi_id = item.get("roi_id")
            if not roi_id:
                continue

            roi_rt1 = self._get_roi_by_id(roi_id, errors)
            if not roi_rt1:
                continue

            roi_label = item.get("roi_label") or roi_rt1.roi_label
            if not roi_label:
                errors.append(f"Missing roi_label for roi_id: {roi_id}")
                continue

            roi_rt2 = self._get_roi_for_rt2(rtstruct2, rt2_sop_uid, roi_label, errors)
            if rtstruct2 and not roi_rt2:
                continue

            defaults = self._build_defaults(
                item,
                roi_label,
                study_uid,
                rt1_label,
                rt2_label,
                rt1_sop_uid,
                rt2_sop_uid,
                errors,
            )

            if defaults is None:
                # Validation error already recorded
                continue

            lookup = {
                "user": self.user,
                "patient": patient,
                "roi_rt1": roi_rt1,
                "roi_rt2": roi_rt2,
            }
            if study_uid:
                lookup["study_uid"] = study_uid

            Feedback.objects.update_or_create(
                **lookup,
                defaults=defaults,
            )
            saved += 1

        result = FeedbackSubmissionResult(True, 200, saved_count=saved, errors=errors)
        return result

    def _get_roi_by_id(self, roi_id: int, errors: List[str]) -> Optional[Roi]:
        try:
            return Roi.objects.get(id=roi_id)
        except Roi.DoesNotExist:
            errors.append(f"Invalid roi_id: {roi_id}")
            return None

    def _get_roi_for_rt2(
        self,
        rtstruct2: Optional[RTStruct],
        rt2_sop_uid: str,
        roi_label: str,
        errors: List[str],
    ) -> Optional[Roi]:
        if not rtstruct2:
            return None
        try:
            return Roi.objects.get(rtstruct=rtstruct2, roi_label=roi_label)
        except Roi.DoesNotExist:
            errors.append(f"Could not find matching ROI for rt2: {roi_label}")
            return None

    def _build_defaults(
        self,
        item: Dict,
        roi_label: str,
        study_uid: str,
        rt1_label: str,
        rt2_label: str,
        rt1_sop_uid: str,
        rt2_sop_uid: str,
        errors: List[str],
    ) -> Optional[Dict]:
        defaults = {"common_roi_label": roi_label}
        if study_uid:
            defaults["study_uid"] = study_uid
        if rt1_label:
            defaults["rt1_label"] = rt1_label
        if rt2_label:
            defaults["rt2_label"] = rt2_label
        if rt1_sop_uid:
            defaults["rt1_sop_uid"] = rt1_sop_uid
        if rt2_sop_uid:
            defaults["rt2_sop_uid"] = rt2_sop_uid

        r1 = item.get("rt1_rating")
        if r1 is not None:
            try:
                r1 = int(r1)
            except (TypeError, ValueError):
                errors.append(f"{roi_label}: RTSTRUCT 1 rating must be an integer")
                return None
            if r1 < 1 or r1 > 10:
                errors.append(f"{roi_label}: RTSTRUCT 1 rating must be 1-10")
                return None
            defaults["rt1_rating"] = r1

        r2 = item.get("rt2_rating")
        if r2 is not None:
            try:
                r2 = int(r2)
            except (TypeError, ValueError):
                errors.append(f"{roi_label}: RTSTRUCT 2 rating must be an integer")
                return None
            if r2 < 1 or r2 > 10:
                errors.append(f"{roi_label}: RTSTRUCT 2 rating must be 1-10")
                return None
            defaults["rt2_rating"] = r2

        comment = (item.get("comment") or "").strip()
        if comment:
            defaults["comment"] = comment

        return defaults
