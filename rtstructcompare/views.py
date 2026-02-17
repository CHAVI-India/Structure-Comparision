"""
Views for DICOM Structure Comparison
Essential functions only: home, patients, dicom_web_viewer
"""
from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Q, Count
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponseForbidden
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.contrib.auth.models import User
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings
from django.utils import timezone
from urllib.parse import urlencode
import pydicom
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
    AssignmentGroup,
    GroupPatientAssignment,
)
import json
import numpy as np
from pathlib import Path
import traceback
from .services.dicom_import_service import import_dicom_directory, DicomImportError
from .services.dicom_viewer_service import build_viewer_context, DicomViewerError
from .services.admin_dashboard_service import (
    AdminDashboardActionService,
    AdminDashboardStatus,
    build_admin_dashboard_context,
)
from .services.feedback_service import FeedbackSubmissionService

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


def is_admin_user(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)


def build_patient_context(
    user,
    search_query,
    group_id=None,
    feedback_status=None,
    page_number=None,
    paginate=False,
    page_size=8
):
    admin_user = is_admin_user(user)
    if admin_user:
        assignment_groups_qs = AssignmentGroup.objects.filter(created_by=user)
        assigned_patients_qs = Patient.objects.all()
    else:
        assignment_groups_qs = AssignmentGroup.objects.filter(users=user)
        assigned_patients_qs = Patient.objects.filter(
            Q(assignments__user=user) |
            Q(group_assignments__group__users=user)
        ).distinct()

    assignment_groups_qs = assignment_groups_qs.order_by('name').prefetch_related('users')
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
            Q(patient_id__icontains=search_query) |
            Q(patient_name__icontains=search_query)
        )

    feedback_status = (feedback_status or '').strip().lower()
    valid_feedback_status = {'pending', 'done', 'not_started'}
    if feedback_status not in valid_feedback_status:
        feedback_status = ''

    assigned_patients_count = assigned_patients_qs.count()
    assigned_studies_count = DICOMStudy.objects.filter(patient__in=assigned_patients_qs).count()
    assigned_series_count = DICOMSeries.objects.filter(study__patient__in=assigned_patients_qs).count()

    feedback_qs = Feedback.objects.filter(
        user=user,
        patient__in=assigned_patients_qs
    ).select_related('patient', 'roi_rt1', 'roi_rt2').order_by('-updated_at')
    feedback_done_count = feedback_qs.count()
    reviewed_patients_count = feedback_qs.values('patient_id').distinct().count()
    pending_feedback_count = max(assigned_patients_count - reviewed_patients_count, 0)
    completion_rate = round((reviewed_patients_count / assigned_patients_count) * 100) if assigned_patients_count else 0
    recent_feedbacks = list(feedback_qs[:8])
    last_feedback = feedback_qs.first()

    roi_counts = (
        Roi.objects.filter(rtstruct__instance__series__study__patient__in=patients_qs)
        .values('rtstruct__instance__series__study__patient_id')
        .annotate(total=Count('id', distinct=True))
    )
    roi_count_map = {
        entry['rtstruct__instance__series__study__patient_id']: entry['total']
        for entry in roi_counts
    }
    feedback_counts = (
        Feedback.objects.filter(user=user, patient__in=patients_qs, roi_rt1__isnull=False)
        .exclude(rt1_rating__isnull=True, rt2_rating__isnull=True)
        .values('patient_id')
        .annotate(total=Count('common_roi_label', distinct=True))
    )
    feedback_count_map = {entry['patient_id']: entry['total'] for entry in feedback_counts}

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
                'study': study,
                'series_count': series_count
            })

        total_rois = roi_count_map.get(patient.id, 0)
        feedback_roi_count = feedback_count_map.get(patient.id, 0)
        pending_roi_count = max(total_rois - feedback_roi_count, 0)

        if total_rois == 0 or feedback_roi_count == 0:
            feedback_state = 'not_started'
        elif pending_roi_count == 0:
            feedback_state = 'done'
        else:
            feedback_state = 'pending'

        patients_data.append({
            'patient': patient,
            'total_studies': patient_studies_count,
            'total_series': patient_series_count,
            'total_rois': total_rois,
            'feedback_roi_count': feedback_roi_count,
            'pending_roi_count': pending_roi_count,
            'feedback_status': feedback_state,
            'studies': studies_data
        })

    if feedback_status:
        patients_data = [
            patient_data
            for patient_data in patients_data
            if patient_data['feedback_status'] == feedback_status
        ]

    total_patients = len(patients_data)
    total_studies = sum(patient['total_studies'] for patient in patients_data)
    total_series = sum(patient['total_series'] for patient in patients_data)

    page_obj = None
    if paginate:
        paginator = Paginator(patients_data, page_size)
        page_obj = paginator.get_page(page_number)
        patients_data = list(page_obj.object_list)

    query_params = {}
    if search_query:
        query_params['search'] = search_query
    if group_id:
        query_params['group'] = group_id
    if feedback_status:
        query_params['feedback_status'] = feedback_status
    pagination_querystring = urlencode(query_params)

    context = {
        'patients': patients_data,
        'total_patients': total_patients,
        'total_studies': total_studies,
        'total_series': total_series,
        'search_query': search_query,
        'is_admin': admin_user,
        'assigned_patients_count': assigned_patients_count,
        'assigned_studies_count': assigned_studies_count,
        'assigned_series_count': assigned_series_count,
        'feedback_done_count': feedback_done_count,
        'reviewed_patients_count': reviewed_patients_count,
        'pending_feedback_count': pending_feedback_count,
        'completion_rate': completion_rate,
        'recent_feedbacks': recent_feedbacks,
        'last_feedback': last_feedback,
        'assignment_groups': assignment_groups_qs,
        'selected_group': selected_group,
        'group_filter': str(selected_group.id) if selected_group else '',
        'feedback_status': feedback_status,
        'page_obj': page_obj,
        'is_paginated': page_obj.has_other_pages() if page_obj else False,
        'pagination_querystring': pagination_querystring,
    }

    return context


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