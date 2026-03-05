"""
Views for DICOM Structure Comparison
Essential functions only: home, patients, dicom_web_viewer
"""
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponseForbidden
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings
from django.db.models import Q, Count
from django.db.models.functions import TruncDate
from django.utils import timezone
from datetime import timedelta
import zipfile
import shutil
from uuid import uuid4
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
import json
from pathlib import Path
import traceback
from .services.dicom_import_service import import_dicom_directory, DicomImportError
from .services.dicom_viewer_service import build_viewer_context, DicomViewerError
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

STATUS_MESSAGE_TIMEOUT_MS = 10000


def home(request):
    """Home page view"""
    return render(request, 'home.html')


class RoleBasedLoginView(LoginView):
    def get_success_url(self):
        redirect_url = self.get_redirect_url()
        if redirect_url:
            return redirect_url
        if is_admin_user(self.request.user):
            return reverse('admin_dashboard')
        return reverse('user_dashboard')


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
    patient.delete()

    messages.success(request, f"Deleted patient {identifier} and related data.")
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

    if request.method == 'POST':
        uploaded_file = request.FILES.get('dicom_archive')

        if not uploaded_file:
            status_message = 'Please select a ZIP file to upload.'
            status_type = 'error'
        elif not uploaded_file.name.lower().endswith('.zip'):
            status_message = 'Only .zip archives are supported.'
            status_type = 'error'
        else:
            storage_root = Path(settings.DICOM_STORAGE_ROOT)
            storage_root.mkdir(parents=True, exist_ok=True)

            timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
            import_slug = f"import_{timestamp}_{uuid4().hex[:8]}"
            import_root = storage_root / import_slug
            upload_dir = import_root / 'uploads'
            extract_dir = import_root / 'extracted'

            zip_path = upload_dir / uploaded_file.name if uploaded_file else None

            try:
                upload_dir.mkdir(parents=True, exist_ok=True)
                extract_dir.mkdir(parents=True, exist_ok=True)

                with zip_path.open('wb+') as destination:
                    for chunk in uploaded_file.chunks():
                        destination.write(chunk)

                with zipfile.ZipFile(zip_path) as archive:
                    archive.extractall(extract_dir)

                import_stats = import_dicom_directory(extract_dir)
                request.session['dicom_import_status'] = {
                    'message': 'DICOM data imported successfully.',
                    'type': 'success',
                    'stats': import_stats,
                }
                return redirect('dicom_import')
            except zipfile.BadZipFile:
                shutil.rmtree(import_root, ignore_errors=True)
                request.session['dicom_import_status'] = {
                    'message': 'Uploaded file is not a valid ZIP archive.',
                    'type': 'error',
                }
                return redirect('dicom_import')
            except DicomImportError as exc:
                shutil.rmtree(import_root, ignore_errors=True)
                request.session['dicom_import_status'] = {
                    'message': str(exc),
                    'type': 'error',
                }
                return redirect('dicom_import')
            except Exception as exc:
                shutil.rmtree(import_root, ignore_errors=True)
                request.session['dicom_import_status'] = {
                    'message': f'Unexpected error: {exc}',
                    'type': 'error',
                }
                return redirect('dicom_import')
            finally:
                if zip_path and zip_path.exists():
                    zip_path.unlink(missing_ok=True)

    context = {
        'status_message': status_message,
        'status_type': status_type,
        'import_stats': import_stats,
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