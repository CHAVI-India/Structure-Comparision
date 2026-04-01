"""
Views for DICOM Structure Comparison
Essential functions only: home, patients, dicom_web_viewer
"""
import logging
from collections import defaultdict
from datetime import timedelta
from uuid import uuid4

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView
from django.db.models import Q, Count
from django.db.models.functions import TruncDate
from django.http import JsonResponse, HttpResponseForbidden, HttpResponse, QueryDict, FileResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import os
import json
import shutil
from pathlib import Path
import traceback
import zipfile

from .forms import DicomFolderImportForm
from .models import (
    DICOMSeries,
    DICOMInstance,
    DICOMStudy,
    Patient,
    Feedback,
    RTStruct,
    Roi,
    PatientAssignment,
    GroupPatientAssignment,
    UserDetails,
    APIToken,
)
from .services.dicom_import_service import import_dicom_file_objects, DicomImportError
from .services.dicom_viewer_service import build_viewer_context, DicomViewerError
from .services.storage_service import get_s3_client, parse_s3_uri
from .services.admin_dashboard_service import (
    AdminDashboardActionService,
    AdminDashboardStatus,
    build_admin_dashboard_context,
    build_admin_assignments_context,
    build_admin_dashboard_chart_data,
)
from .services.feedback_service import FeedbackSubmissionService
from .services.feedback_query_service import (
    build_feedback_queryset,
    build_querystring,
    build_querystring_without_page,
    paginate_feedback,
    parse_feedback_list_params,
)
from .services.patient_context_service import build_patient_context, is_admin_user
from .services.bulk_invite_service import BulkInviteService
from user.models import UserProfile, UserTypeChoices

logger = logging.getLogger(__name__)
STATUS_MESSAGE_TIMEOUT_MS = 10000


def home(request):
    """Home page view"""
    return render(request, 'home.html')


class RoleBasedLoginView(LoginView):
    def get_success_url(self):
        redirect_url = self.get_redirect_url()
        if redirect_url:
            return redirect_url
        return reverse('patients')


@login_required
def patients(request):
    """Patient list page view"""
    search_query = request.GET.get('search', '')
    group_id = (request.GET.get('group') or '').strip()
    feedback_status = request.GET.get('feedback_status', '')
    page_number = request.GET.get('page')
    context = build_patient_context(
        request.user,
        search_query,
        group_id=group_id,
        feedback_status=feedback_status,
        page_number=page_number,
        paginate=True,
        page_size=8
    )
    return render(request, 'patients.html', context)


def _redirect_back(request):
    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect('patients')


@login_required
@require_http_methods(["POST"])
def remove_patient_access(request, patient_uuid):
    if not is_admin_user(request.user):
        return HttpResponseForbidden('Admin access required.')

    patient = get_object_or_404(Patient, id=patient_uuid)
    deleted_direct, _ = PatientAssignment.objects.filter(patient=patient).delete()
    deleted_group, _ = GroupPatientAssignment.objects.filter(patient=patient).delete()

    messages.success(
        request,
        f"Removed {deleted_direct} direct and {deleted_group} group assignment(s) for {patient.patient_id or patient.id}.",
    )
    return _redirect_back(request)


@login_required
@require_http_methods(["POST"])
def delete_patient(request, patient_uuid):
    if not is_admin_user(request.user):
        return HttpResponseForbidden('Admin access required.')

    patient = get_object_or_404(Patient, id=patient_uuid)
    identifier = patient.patient_id or str(patient_uuid)
    try:
        deleted_objects = _delete_patient_s3_objects(patient)
    except Exception as exc:
        logger.exception("Failed to delete S3 data for patient %s", patient.id)
        messages.error(
            request,
            f"Could not delete S3 objects for patient {identifier}: {exc}",
        )
        return _redirect_back(request)

    patient.delete()

    success_message = f"Deleted patient {identifier} and related data."
    if deleted_objects:
        success_message += f" Removed {deleted_objects} S3 object(s)."
    messages.success(request, success_message)
    return _redirect_back(request)


@login_required
def user_dashboard(request):
    if is_admin_user(request.user):
        return redirect('admin_dashboard')
    search_query = request.GET.get('search', '')
    group_id = (request.GET.get('group') or '').strip()
    context = build_patient_context(request.user, search_query, group_id=group_id)
    return render(request, 'user_dashboard.html', context)


@login_required
def admin_dashboard(request):
    if not is_admin_user(request.user):
        return HttpResponseForbidden('Admin access required.')

    status = AdminDashboardStatus()
    if request.method == 'POST':
        action_service = AdminDashboardActionService(request.user)
        status = action_service.handle(request.POST)

    context = build_admin_dashboard_context(request.user, request.GET)
    context.update({
        'status_message': status.message,
        'status_type': status.status_type,
        'status_timeout_ms': STATUS_MESSAGE_TIMEOUT_MS,
    })

    return render(request, 'admin_dashboard.html', context)


@login_required
def admin_assignments(request):
    if not is_admin_user(request.user):
        return HttpResponseForbidden('Admin access required.')

    status = AdminDashboardStatus()
    if request.method == 'POST':
        action_service = AdminDashboardActionService(request.user)
        status = action_service.handle(request.POST)

    context = build_admin_assignments_context(request.user, request.GET)
    context.update({
        'status_message': status.message,
        'status_type': status.status_type,
        'status_timeout_ms': STATUS_MESSAGE_TIMEOUT_MS,
    })
    return render(request, 'assignments/admin_assignments.html', context)


@login_required
@require_http_methods(["GET"])
def admin_dashboard_charts(request):
    if not is_admin_user(request.user):
        return HttpResponseForbidden('Admin access required.')

    try:
        range_days = int(request.GET.get("range") or 30)
    except (TypeError, ValueError):
        range_days = 30

    payload = build_admin_dashboard_chart_data(range_days=range_days)
    return JsonResponse(payload)


def _delete_patient_s3_objects(patient):
    """Remove all S3 objects tied to the patient's DICOM instances."""
    instance_paths = list(
        DICOMInstance.objects
        .filter(series__study__patient=patient, instance_path__startswith='s3://')
        .values_list('instance_path', flat=True)
    )

    if not instance_paths:
        return 0

    s3_keys = defaultdict(set)
    for path in instance_paths:
        try:
            bucket, key = parse_s3_uri(path)
        except ValueError:
            logger.warning("Skipping invalid S3 URI for patient %s: %s", patient.id, path)
            continue
        s3_keys[bucket].add(key)

    if not s3_keys:
        return 0

    client = get_s3_client()
    total_deleted = 0

    for bucket, keys in s3_keys.items():
        key_list = [{'Key': key} for key in sorted(keys)]
        for start in range(0, len(key_list), 1000):
            chunk = key_list[start:start + 1000]
            try:
                response = client.delete_objects(Bucket=bucket, Delete={'Objects': chunk})
            except (ClientError, BotoCoreError) as exc:
                raise RuntimeError(f'Failed deleting S3 objects from {bucket}: {exc}') from exc

            total_deleted += len(response.get('Deleted', []))

    return total_deleted


@login_required
@require_http_methods(["GET"])
def user_dashboard_charts(request):
    if is_admin_user(request.user):
        return HttpResponseForbidden('User access required.')

    try:
        range_days = int(request.GET.get("range") or 30)
    except (TypeError, ValueError):
        range_days = 30

    safe_range = max(7, min(int(range_days or 30), 90))
    start_dt = timezone.now() - timedelta(days=safe_range - 1)
    start_date = start_dt.date()

    labels = [(start_date + timedelta(days=i)).isoformat() for i in range(safe_range)]
    assignment_index = {label: 0 for label in labels}
    feedback_index = {label: 0 for label in labels}

    # Assigned patients for this user (direct + group)
    assigned_patients_qs = Patient.objects.filter(
        Q(assignments__user=request.user)
        | Q(group_assignments__group__users=request.user)
    ).distinct()

    # Assignments by day (direct + group assignments)
    assignment_counts = (
        PatientAssignment.objects.filter(
            user=request.user,
            assigned_at__date__gte=start_date,
        )
        .annotate(day=TruncDate("assigned_at"))
        .values("day")
        .annotate(count=Count("id"))
    )
    for row in assignment_counts:
        day = row.get("day")
        if day:
            key = day.isoformat()
            if key in assignment_index:
                assignment_index[key] += int(row.get("count") or 0)

    group_assignment_counts = (
        GroupPatientAssignment.objects.filter(
            group__users=request.user,
            assigned_at__date__gte=start_date,
        )
        .annotate(day=TruncDate("assigned_at"))
        .values("day")
        .annotate(count=Count("id"))
    )
    for row in group_assignment_counts:
        day = row.get("day")
        if day:
            key = day.isoformat()
            if key in assignment_index:
                assignment_index[key] += int(row.get("count") or 0)

    # Feedback updates by day (only this user's feedback on assigned patients)
    feedback_counts = (
        Feedback.objects.filter(
            user=request.user,
            patient__in=assigned_patients_qs,
            updated_at__date__gte=start_date,
        )
        .annotate(day=TruncDate("updated_at"))
        .values("day")
        .annotate(count=Count("id"))
    )
    for row in feedback_counts:
        day = row.get("day")
        if day:
            key = day.isoformat()
            if key in feedback_index:
                feedback_index[key] += int(row.get("count") or 0)

    assignments_by_day = [assignment_index[d] for d in labels]
    feedback_by_day = [feedback_index[d] for d in labels]

    assigned_patients_count = assigned_patients_qs.count()
    reviewed_patients_count = (
        Feedback.objects.filter(user=request.user, patient__in=assigned_patients_qs)
        .values("patient_id")
        .distinct()
        .count()
    )
    pending_count = max(assigned_patients_count - reviewed_patients_count, 0)

    return JsonResponse(
        {
            "range_days": safe_range,
            "labels": labels,
            "assignments_by_day": assignments_by_day,
            "feedback_by_day": feedback_by_day,
            "review_breakdown": {
                "reviewed": reviewed_patients_count,
                "pending": pending_count,
            },
        }
    )


@login_required
def dicom_import(request):
    if not is_admin_user(request.user):
        return HttpResponseForbidden('Admin access required.')

    status_message = None
    status_type = 'info'
    import_stats = None

    flash = request.session.pop('dicom_import_status', None)
    if flash:
        status_message = flash.get('message')
        status_type = flash.get('type', 'info')
        import_stats = flash.get('stats')

    form = DicomFolderImportForm()

    if request.method == 'POST':
        uploaded_files = request.FILES.getlist('dicom_files')

        if not uploaded_files:
            status_message = 'Please select a folder containing DICOM files.'
            status_type = 'error'
        elif len(uploaded_files) == 1:
            status_message = 'Folder uploads only. Please select a directory, not a single file.'
            status_type = 'error'
        else:
            try:
                import_stats = import_dicom_file_objects(uploaded_files)
                request.session['dicom_import_status'] = {
                    'message': 'DICOM data imported successfully.',
                    'type': 'success',
                    'stats': import_stats,
                }
                return redirect('dicom_import')
            except DicomImportError as exc:
                request.session['dicom_import_status'] = {
                    'message': str(exc),
                    'type': 'error',
                }
                return redirect('dicom_import')
            except Exception as exc:
                request.session['dicom_import_status'] = {
                    'message': f'Unexpected error: {exc}',
                    'type': 'error',
                }
                return redirect('dicom_import')

    context = {
        'status_message': status_message,
        'status_type': status_type,
        'import_stats': import_stats,
        'form': form,
        'patient_count': Patient.objects.count(),
        'study_count': DICOMStudy.objects.count(),
        'series_count': DICOMSeries.objects.count(),
        'instance_count': DICOMInstance.objects.count(),
        'rtstruct_count': RTStruct.objects.count(),
        'roi_count': Roi.objects.count(),
        'status_timeout_ms': STATUS_MESSAGE_TIMEOUT_MS,
    }

    return render(request, 'dicom_import.html', context)


@login_required
def admin_feedbacks(request):
    if not is_admin_user(request.user):
        return HttpResponseForbidden('Admin access required.')

    params = parse_feedback_list_params(request.GET)
    qs = build_feedback_queryset(scope="admin", user=request.user, params=params)
    page_obj = paginate_feedback(qs, params=params)

    base_qs = build_querystring_without_page(request.GET)
    page_prefix = f"?{base_qs}&" if base_qs else "?"

    return render(
        request,
        'admin_feedbacks.html',
        {
            'scope': 'admin',
            'params': params,
            'feedback_page_obj': page_obj,
            'feedbacks': page_obj.object_list,
            'page_prefix': page_prefix,
            'base_querystring': base_qs,
        },
    )


@login_required
def my_feedbacks(request):
    if is_admin_user(request.user):
        return redirect('admin_feedbacks')

    params = parse_feedback_list_params(request.GET)
    qs = build_feedback_queryset(scope="user", user=request.user, params=params)
    page_obj = paginate_feedback(qs, params=params)

    base_qs = build_querystring_without_page(request.GET)
    page_prefix = f"?{base_qs}&" if base_qs else "?"

    return render(
        request,
        'my_feedbacks.html',
        {
            'scope': 'user',
            'params': params,
            'feedback_page_obj': page_obj,
            'feedbacks': page_obj.object_list,
            'page_prefix': page_prefix,
            'base_querystring': base_qs,
        },
    )


@login_required
def export_feedbacks_csv(request):
    if not is_admin_user(request.user):
        return HttpResponseForbidden('Admin access required.')

    import csv
    from django.http import HttpResponse
    from django.utils import timezone

    params = parse_feedback_list_params(request.GET)
    qs = build_feedback_queryset(scope="admin", user=request.user, params=params)

    filename = f"roi_feedbacks_{timezone.now().strftime('%Y%m%d_%H%M%S')}.csv"
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow(
        [
            'id',
            'username',
            'patient_id',
            'rt1_sop_uid',
            'rt2_sop_uid',
            'roi_label',
            'rt1_label',
            'rt1_rating',
            'rt2_label',
            'rt2_rating',
            'comment',
            'created_at',
            'updated_at',
        ]
    )

    for fb in qs.iterator(chunk_size=2000):
        writer.writerow(
            [
                str(fb.id),
                fb.user.username if fb.user else '',
                fb.patient.patient_id if fb.patient else '',
                fb.rt1_sop_uid or '',
                fb.rt2_sop_uid or '',
                fb.common_roi_label or '',
                fb.rt1_label or '',
                fb.rt1_rating if fb.rt1_rating is not None else '',
                fb.rt2_label or '',
                fb.rt2_rating if fb.rt2_rating is not None else '',
                fb.comment or '',
                fb.created_at.isoformat() if fb.created_at else '',
                fb.updated_at.isoformat() if fb.updated_at else '',
            ]
        )

    return response


@login_required
def export_feedbacks_xlsx(request):
    if not is_admin_user(request.user):
        return HttpResponseForbidden('Admin access required.')

    from io import BytesIO
    from django.http import HttpResponse
    from django.utils import timezone

    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise ImportError(
            "openpyxl is required for XLSX export. Install it with: pip install openpyxl"
        ) from exc

    params = parse_feedback_list_params(request.GET)
    qs = build_feedback_queryset(scope="admin", user=request.user, params=params)

    wb = Workbook()
    ws = wb.active
    ws.title = "Feedbacks"

    headers = [
        'id',
        'username',
        'patient_id',
        'rt1_sop_uid',
        'rt2_sop_uid',
        'roi_label',
        'rt1_label',
        'rt1_rating',
        'rt2_label',
        'rt2_rating',
        'comment',
        'created_at',
        'updated_at',
    ]
    ws.append(headers)

    for fb in qs.iterator(chunk_size=2000):
        ws.append(
            [
                str(fb.id),
                fb.user.username if fb.user else '',
                fb.patient.patient_id if fb.patient else '',
                fb.rt1_sop_uid or '',
                fb.rt2_sop_uid or '',
                fb.common_roi_label or '',
                fb.rt1_label or '',
                fb.rt1_rating if fb.rt1_rating is not None else '',
                fb.rt2_label or '',
                fb.rt2_rating if fb.rt2_rating is not None else '',
                fb.comment or '',
                fb.created_at.isoformat() if fb.created_at else '',
                fb.updated_at.isoformat() if fb.updated_at else '',
            ]
        )

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    filename = f"roi_feedbacks_{timezone.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    response = HttpResponse(
        buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def dicom_web_viewer(request, patient_uuid=None):
    """DICOM web viewer for comparing RT structures"""
    try:
        if not patient_uuid:
            if is_admin_user(request.user):
                first_patient = Patient.objects.first()
            else:
                assignment = PatientAssignment.objects.select_related('patient').filter(
                    user=request.user
                ).first()
                if assignment:
                    first_patient = assignment.patient
                else:
                    group_assignment = GroupPatientAssignment.objects.select_related('patient').filter(
                        group__users=request.user
                    ).first()
                    first_patient = group_assignment.patient if group_assignment else None

            if first_patient:
                patient_uuid = first_patient.id
            else:
                return render(request, 'dicom_web_viewer.html', {
                    'error': 'No assigned patients found for your account.'
                })
        
        patient = get_object_or_404(Patient, id=patient_uuid)

        if not is_admin_user(request.user):
            has_direct_assignment = PatientAssignment.objects.filter(
                user=request.user,
                patient=patient
            ).exists()
            has_group_assignment = GroupPatientAssignment.objects.filter(
                patient=patient,
                group__users=request.user
            ).exists()
            if not (has_direct_assignment or has_group_assignment):
                return HttpResponseForbidden('You are not assigned to this patient.')
        
        viewer_payload = build_viewer_context(patient, user=request.user)

        context = {
            **viewer_payload,
            'patient_uuid': patient_uuid,
            'available_patients': Patient.objects.all().order_by('patient_id'),
            'has_user_details': hasattr(request.user, 'details') if request.user.is_authenticated else False,
        }

        return render(request, 'dicom_web_viewer.html', context)

    except DicomViewerError as e:
        return render(request, 'dicom_web_viewer.html', {
            'error': str(e),
            'available_patients': Patient.objects.all().order_by('patient_id'),
        })
    except Exception as e:
        print(f"Error in dicom_web_viewer: {e}")
        traceback.print_exc()
        return render(request, 'dicom_web_viewer.html', {
            'error': f'Error loading DICOM data: {str(e)}',
            'available_patients': Patient.objects.all().order_by('patient_id')
        })


@csrf_exempt
@require_http_methods(["POST"])
def load_dicom_data(request):
    """API endpoint to load DICOM data"""
    try:
        data = json.loads(request.body)
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def get_dicom_slice(request):
    """API endpoint to get DICOM slice"""
    try:
        data = json.loads(request.body)
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def submit_feedback(request):
    """Save ROI rating feedback to the database."""
    try:
        data = json.loads(request.body or '{}')

        if not request.user.is_authenticated:
            return JsonResponse({'success': False, 'error': 'Authentication required'}, status=401)

        submission_service = FeedbackSubmissionService(request.user)
        result = submission_service.submit(data)

        if not result.success and result.error:
            return JsonResponse({'success': False, 'error': result.error}, status=result.status_code)

        response = {
            'success': result.success,
            'saved_count': result.saved_count,
        }
        if result.errors:
            response['errors'] = result.errors

        return JsonResponse(response, status=result.status_code)
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def submit_user_details(request):

    """Save user profile details from the viewer modal."""
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': 'Authentication required'}, status=401)
        
    try:
        data = json.loads(request.body or '{}')
        experience_val = data.get('experience_post_md_dnb')
        if experience_val == "" or experience_val is None:
            return JsonResponse({'success': False, 'error': 'Experience is required.'}, status=400)
            
        try:
            exp_val = float(experience_val)
        except ValueError:
            return JsonResponse({'success': False, 'error': 'Experience must be a valid number.'}, status=400)
            
        UserDetails.objects.update_or_create(
            user=request.user,
            defaults={
                'experience_post_md_dnb': exp_val,
                'specialization_in_breast': bool(data.get('specialization_in_breast')),
                'specialization_in_head_neck': bool(data.get('specialization_in_head_neck')),
                'routinely_segment_brachial_plexus': bool(data.get('routinely_segment_brachial_plexus')),
                'experience_in_autosegmentation': bool(data.get('experience_in_autosegmentation')),
                'works_in_teaching_institute': bool(data.get('works_in_teaching_institute')),
            }
        )
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ─── Bulk Invite Users ────────────────────────────────────────────────────────

_DEFAULT_INVITE_BODY = """Thank you for agreeing to be a part of the segmentation comparison study. To provide some background, we are testing two automatic segmentation models using different loss functions. This work is being conducted in collaboration with the Indian Institute of Technology Kharagpur.

Your Username: {username}
Your Password:  {password}

Please follow the following steps to participate in the process

1. First, go to the website https://compare.chavi.ai
2. Log in by clicking on the Login button on the front page or on the top right of the navigation bar using the username and password provided above
3. After logging in, you will go to the patient page, where you will see 5 patients for whom the rating has to be provided.
4. Click on any patient you want to rate first.
5. A new page will open (it will take some time depending on the network speed so please be patient).
6. First, the system will ask you to provide details about your experience and familiarity with autosegmentation systems.
7. Then you will see two CT images side by side. Please make a note of the name of the image series.
8. Scroll down, and you will be able to toggle the two regions of interest, which have been segmented - Brachial Plexus Left and Brachial Plexus Right.
9. Please go through the images (see the attached manual), slice by slice, and review the contours.
10. Please rate the contour with a higher star rating to indicate better contour quality.
11. Click the submit button to save your rating.
12. If you have any comments, please provide them in the comment box.

Once you have rated all the 5 patients, you can log out of the system.
We would like to thank you for your time and effort.
Kindly ensure that you are using a desktop/laptop to do the rating for the best experience.

Thanking You,

Sincerely Yours,
Santam Chakraborty
On behalf of the DRAW Autosegmentation Team."""

_DEFAULT_INVITE_SUBJECT = "Invitation to the Segmentation Comparison Study"


@login_required
@require_http_methods(["GET", "POST"])
def bulk_invite_users(request):
    """Admin-only view: bulk-create users and send personalised invitation emails."""
    if not is_admin_user(request.user):
        return HttpResponseForbidden("Admin access required.")

    if request.method == "POST":
        first_names = request.POST.getlist("first_name[]")
        last_names  = request.POST.getlist("last_name[]")
        usernames   = request.POST.getlist("username[]")
        emails      = request.POST.getlist("email[]")

        subject = request.POST.get("subject", _DEFAULT_INVITE_SUBJECT).strip() or _DEFAULT_INVITE_SUBJECT
        body    = request.POST.get("body",    _DEFAULT_INVITE_BODY).strip()    or _DEFAULT_INVITE_BODY
        attachment = request.FILES.get("attachment")

        recipients = []
        for f, l, u, e in zip(first_names, last_names, usernames, emails):
            if f.strip() or e.strip():
                recipients.append({
                    "first_name": f.strip(),
                    "last_name":  l.strip(),
                    "username":   u.strip(),
                    "email":      e.strip()
                })
        
        if recipients:
            results = BulkInviteService.process_bulk_invite(recipients, subject, body, attachment=attachment)
            request.session['bulk_invite_results'] = results
            status_msg = f"Done: {results['sent_count']} sent, {results['skipped_count']} skipped, {results['error_count']} failed."
            if results['sent_count'] > 0:
                messages.success(request, status_msg)
            else:
                messages.error(request, status_msg)
        else:
            messages.error(request, "No valid recipients provided.")
            request.session['bulk_invite_post_rows'] = [
                {"first_name": f, "last_name": l, "username": u, "email": e}
                for f, l, u, e in zip(first_names, last_names, usernames, emails)
            ]

        return redirect('bulk_invite_users')

    # ── Handle GET: Display form / results ───────────────────────────────────
    # Pull data from session if this is a redirect after a POST
    results_data = request.session.pop('bulk_invite_results', {})
    post_rows    = request.session.pop('bulk_invite_post_rows', [])

    context = {
        "default_body":  _DEFAULT_INVITE_BODY,
        "subject":       _DEFAULT_INVITE_SUBJECT,
        "body":          _DEFAULT_INVITE_BODY,
        "results":       results_data.get('results'),
        "sent_count":    results_data.get('sent_count', 0),
        "skipped_count": results_data.get('skipped_count', 0),
        "error_count":   results_data.get('error_count', 0),
        "post_rows":     post_rows,
    }

    return render(request, "bulk_invite.html", context)


_DEFAULT_REMINDER_BODY = """This is a friendly reminder to complete the structure comparison ratings assigned to you.

You have {pending_count} pending patient(s) to review. Your contributions are vital to this study.

Please log in to https://compare.chavi.ai to complete your assignments.

If you have already completed your tasks or have any questions, please ignore this email or reach out to us.

Thanking You,
Santam Chakraborty
On behalf of the DRAW Autosegmentation Team"""


@login_required
@require_http_methods(["GET", "POST"])
def bulk_reminder_users(request):
    """Admin-only view: select raters and send reminder emails."""
    if not is_admin_user(request.user):
        return HttpResponseForbidden("Admin access required.")

    if request.method == "POST":
        user_ids = request.POST.getlist("user_ids[]")
        subject = request.POST.get("subject", "Reminder: Segmentation Comparison Study").strip()
        body = request.POST.get("body", _DEFAULT_REMINDER_BODY).strip() or _DEFAULT_REMINDER_BODY
        attachment = request.FILES.get("attachment")

        if not user_ids:
            messages.error(request, "No recipients selected.")
            return redirect('bulk_reminder_users')

        users = User.objects.filter(id__in=user_ids)
        
        admin_context = build_admin_assignments_context(request.user, QueryDict(''), paginate=False)
        user_rows = admin_context.get('user_assignment_rows', [])
        user_data_map = {str(row['user'].id): row for row in user_rows}

        recipients = []
        for u in users:
            row = user_data_map.get(str(u.id))
            if row:
                recipients.append({
                    "user_id": u.id,
                    "email": u.email,
                    "name": f"{u.first_name} {u.last_name}".strip() or u.username,
                    "pending_count": row.get('pending_count', 0)
                })
        
        if recipients:
            results = BulkInviteService.process_bulk_reminder(recipients, subject, body, attachment=attachment)
            request.session['bulk_reminder_results'] = results
            status_msg = f"Reminders sent: {results['sent_count']} successful, {results['error_count']} failed."
            if results['sent_count'] > 0:
                messages.success(request, status_msg)
            else:
                messages.error(request, status_msg)
        
        return redirect('bulk_reminder_users')

    admin_context = build_admin_assignments_context(request.user, request.GET, paginate=False)
    user_rows = admin_context.get('user_assignment_rows', [])
    
    results_data = request.session.pop('bulk_reminder_results', {})

    context = {
        "user_rows": user_rows,
        "default_body": _DEFAULT_REMINDER_BODY,
        "subject": "Reminder: Segmentation Comparison Study",
        "body": _DEFAULT_REMINDER_BODY,
        "results": results_data.get('results'),
        "sent_count": results_data.get('sent_count', 0),
        "error_count": results_data.get('error_count', 0),
    }

    return render(request, "bulk_reminder.html", context)


@login_required
@require_http_methods(["POST"])
def test_email_connection(request):
    """Admin-only view: test SMTP connection through BulkInviteService."""
    if not is_admin_user(request.user):
        return JsonResponse({"success": False, "error": "Admin access required."}, status=403)

    to_email = (request.user.email or "").strip()
    if not to_email:
        return JsonResponse({"success": False, "error": "Your admin account has no email set."})

    success, msg = BulkInviteService.test_smtp_connection(to_email)
    return JsonResponse({"success": success, "message": msg})


@login_required
@require_http_methods(["POST"])
def delete_feedback(request, feedback_id):
    if not is_admin_user(request.user):
        return HttpResponseForbidden('Admin access required.')
    feedback = get_object_or_404(Feedback, id=feedback_id)
    feedback.delete()
    next_url = request.POST.get('next') or reverse('admin_feedbacks')
    return redirect(next_url)


# ─── API Token Management (superuser only) ────────────────────────────────────

@login_required
@require_http_methods(["GET", "POST"])
def api_token_management(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden('Superuser access required.')

    if request.method == "POST":
        action = request.POST.get('action')

        if action == 'create':
            import secrets
            label = request.POST.get('label', '').strip()
            raw = secrets.token_hex(32)
            APIToken.objects.create(user=request.user, token=raw, label=label)
            messages.success(request, f'New token created: {raw}')

        elif action == 'revoke':
            token_id = request.POST.get('token_id')
            updated = APIToken.objects.filter(id=token_id, is_active=True).update(is_active=False)
            if updated:
                messages.success(request, 'Token revoked.')
            else:
                messages.error(request, 'Token not found or already revoked.')

        return redirect('api_token_management')

    tokens = APIToken.objects.select_related('user').all()
    return render(request, 'api_tokens.html', {'tokens': tokens})


# ─── External API ─────────────────────────────────────────────────────────────

def _authenticate_api_token(request):
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if not auth_header:
        return None, JsonResponse({'error': 'Authorization header missing.'}, status=401)

    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() not in ('token', 'bearer'):
        return None, JsonResponse(
            {'error': 'Invalid Authorization header. Expected: Authorization: Token <your_token>'},
            status=401,
        )

    raw_token = parts[1]
    try:
        api_token = APIToken.objects.select_related('user').get(token=raw_token, is_active=True)
    except APIToken.DoesNotExist:
        return None, JsonResponse({'error': 'Invalid or inactive token.'}, status=401)

    if not is_admin_user(api_token.user):
        return None, JsonResponse({'error': 'Token does not belong to an admin user.'}, status=403)

    APIToken.objects.filter(pk=api_token.pk).update(last_used_at=timezone.now())
    return api_token, None


def _feedback_to_dict(fb):
    return {
        'id': str(fb.id),
        'username': fb.user.username if fb.user else '',
        'patient_id': fb.patient.patient_id if fb.patient else '',
        'rt1_sop_uid': fb.rt1_sop_uid or '',
        'rt2_sop_uid': fb.rt2_sop_uid or '',
        'roi_label': fb.common_roi_label or '',
        'rt1_label': fb.rt1_label or '',
        'rt1_rating': fb.rt1_rating,
        'rt2_label': fb.rt2_label or '',
        'rt2_rating': fb.rt2_rating,
        'comment': fb.comment or '',
        'created_at': fb.created_at.isoformat() if fb.created_at else '',
        'updated_at': fb.updated_at.isoformat() if fb.updated_at else '',
    }


_FEEDBACK_CSV_HEADERS = [
    'id', 'username', 'patient_id',
    'rt1_sop_uid', 'rt2_sop_uid',
    'roi_label', 'rt1_label', 'rt1_rating',
    'rt2_label', 'rt2_rating',
    'comment', 'created_at', 'updated_at',
]


@csrf_exempt
@require_http_methods(["GET"])
def api_feedbacks(request):
    """
    External REST API – returns all feedbacks.

    Authentication
    --------------
    Include in every request:
        Authorization: Token <your_token>

    Optional query params (same filters as the admin feedback page)
    --------------------------------------------------------------
    q, username, patient_id, roi_label, rating,
    date_from (YYYY-MM-DD), date_to (YYYY-MM-DD),
    sort_by, order, page, page_size

    Response format  (default: JSON)
    ---------------------------------
    ?format=json   paginated JSON
    ?format=csv    CSV file download
    ?format=xlsx   XLSX file download
    """
    api_token, err = _authenticate_api_token(request)
    if err:
        return err

    params = parse_feedback_list_params(request.GET)
    qs = build_feedback_queryset(scope="admin", user=api_token.user, params=params)
    fmt = (request.GET.get('format') or 'json').lower()

    if fmt == 'csv':
        import csv
        filename = f"roi_feedbacks_{timezone.now().strftime('%Y%m%d_%H%M%S')}.csv"
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        writer = csv.writer(response)
        writer.writerow(_FEEDBACK_CSV_HEADERS)
        for fb in qs.iterator(chunk_size=2000):
            d = _feedback_to_dict(fb)
            writer.writerow([d[h] for h in _FEEDBACK_CSV_HEADERS])
        return response

    if fmt == 'xlsx':
        from io import BytesIO
        try:
            from openpyxl import Workbook
        except ImportError:
            return JsonResponse({'error': 'openpyxl is not installed on this server.'}, status=500)
        wb = Workbook()
        ws = wb.active
        ws.title = "Feedbacks"
        ws.append(_FEEDBACK_CSV_HEADERS)
        for fb in qs.iterator(chunk_size=2000):
            d = _feedback_to_dict(fb)
            ws.append([d[h] for h in _FEEDBACK_CSV_HEADERS])
        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        filename = f"roi_feedbacks_{timezone.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        response = HttpResponse(
            buf.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    page_obj = paginate_feedback(qs, params=params)
    return JsonResponse({
        'count': page_obj.paginator.count,
        'page': page_obj.number,
        'page_size': params.page_size,
        'num_pages': page_obj.paginator.num_pages,
        'has_next': page_obj.has_next(),
        'has_previous': page_obj.has_previous(),
        'results': [_feedback_to_dict(fb) for fb in page_obj.object_list],
    })


# @login_required
# @require_http_methods(["GET"])
# def serve_local_dicom(request, sop_instance_uid):
#     """Serve a locally-stored DICOM file by SOP Instance UID (dev/local use only)."""
#     instance = get_object_or_404(DICOMInstance, sop_instance_uid=sop_instance_uid)
#     path = Path(instance.instance_path or '')
#     if not path.exists():
#         return HttpResponse(status=404)
#     return FileResponse(open(path, 'rb'), content_type='application/dicom')