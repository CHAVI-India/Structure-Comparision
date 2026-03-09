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
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

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