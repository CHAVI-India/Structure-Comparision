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
from urllib.parse import urlencode
import pydicom
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

    status_message = None
    status_type = 'info'
    if request.method == 'POST':
        action = request.POST.get('action')
        user_ids = request.POST.getlist('user_ids')
        patient_ids = request.POST.getlist('patient_ids')
        group_id = (request.POST.get('group_id') or '').strip()

        if action == 'create_group':
            group_name = (request.POST.get('group_name') or '').strip()
            group_description = (request.POST.get('group_description') or '').strip()
            group_user_ids = request.POST.getlist('group_user_ids')

            if not group_name:
                status_message = 'Group name is required.'
                status_type = 'error'
            elif not group_user_ids:
                status_message = 'Select at least one user for the group.'
                status_type = 'error'
            else:
                group, created = AssignmentGroup.objects.get_or_create(
                    name=group_name,
                    created_by=request.user,
                    defaults={'description': group_description}
                )
                if not created:
                    status_message = 'A group with this name already exists.'
                    status_type = 'error'
                else:
                    if group_user_ids:
                        group.users.set(User.objects.filter(id__in=group_user_ids))
                    status_message = f'Group "{group.name}" created.'
                    status_type = 'success'
        elif action == 'edit_group':
            group_id = (request.POST.get('group_id') or '').strip()
            group_name = (request.POST.get('group_name') or '').strip()
            group_description = (request.POST.get('group_description') or '').strip()
            group_user_ids = request.POST.getlist('group_user_ids')

            if not group_id:
                status_message = 'Select a group to edit.'
                status_type = 'error'
            else:
                group = AssignmentGroup.objects.filter(id=group_id, created_by=request.user).first()
                if not group:
                    status_message = 'Group not found or access denied.'
                    status_type = 'error'
                elif not group_name:
                    status_message = 'Group name is required.'
                    status_type = 'error'
                elif not group_user_ids:
                    status_message = 'Select at least one user for the group.'
                    status_type = 'error'
                elif AssignmentGroup.objects.filter(name=group_name, created_by=request.user).exclude(id=group.id).exists():
                    status_message = 'Another group with this name already exists.'
                    status_type = 'error'
                else:
                    group.name = group_name
                    group.description = group_description
                    group.save(update_fields=['name', 'description', 'updated_at'])
                    group.users.set(User.objects.filter(id__in=group_user_ids))
                    status_message = f'Group "{group.name}" updated.'
                    status_type = 'success'
        elif action == 'delete_group':
            group_id = (request.POST.get('group_id') or '').strip()
            if not group_id:
                status_message = 'Select a group to delete.'
                status_type = 'error'
            else:
                group = AssignmentGroup.objects.filter(id=group_id, created_by=request.user).first()
                if not group:
                    status_message = 'Group not found or access denied.'
                    status_type = 'error'
                else:
                    group_name = group.name
                    group.delete()
                    status_message = f'Group "{group_name}" deleted.'
                    status_type = 'success'
        elif action == 'assign_groups':
            bulk_group_ids = request.POST.getlist('bulk_group_ids')
            bulk_patient_ids = request.POST.getlist('bulk_patient_ids')

            if not bulk_group_ids or not bulk_patient_ids:
                status_message = 'Select at least one group and one patient.'
                status_type = 'error'
            else:
                groups = list(
                    AssignmentGroup.objects.filter(id__in=bulk_group_ids, created_by=request.user).prefetch_related('users')
                )
                if len(groups) != len(set(bulk_group_ids)):
                    status_message = 'One or more selected groups could not be found.'
                    status_type = 'error'
                else:
                    empty_groups = [group.name for group in groups if not group.users.exists()]
                    if empty_groups:
                        status_message = (
                            'Add users to these groups before assigning patients: '
                            + ', '.join(empty_groups)
                        )
                        status_type = 'error'
                    else:
                        patients = list(Patient.objects.filter(id__in=bulk_patient_ids))
                        if not patients:
                            status_message = 'No valid patients selected.'
                            status_type = 'error'
                        else:
                            created_count = 0
                            for group in groups:
                                for patient in patients:
                                    _, created = GroupPatientAssignment.objects.get_or_create(
                                        group=group,
                                        patient=patient
                                    )
                                    if created:
                                        created_count += 1
                            status_message = (
                                f'Assigned {len(patients)} patient(s) across {len(groups)} group(s). '
                                f'Created {created_count} new group assignment(s).'
                            )
                            status_type = 'success'
        elif action in {'assign', 'unassign'}:
            if not patient_ids or (not user_ids and not group_id):
                status_message = 'Select at least one user or a group, and at least one patient.'
                status_type = 'error'
            else:
                target_users = list(User.objects.filter(id__in=user_ids)) if user_ids else []
                selected_group = None
                if group_id:
                    selected_group = AssignmentGroup.objects.filter(id=group_id).first()
                    if not selected_group:
                        status_message = 'Selected group not found.'
                        status_type = 'error'
                if status_type != 'error':
                    patients = list(Patient.objects.filter(id__in=patient_ids))
                    if not patients:
                        status_message = 'No valid patients selected.'
                        status_type = 'error'
                    elif action == 'assign':
                        direct_created = 0
                        group_created = 0
                        for target_user in target_users:
                            for patient in patients:
                                _, created = PatientAssignment.objects.get_or_create(
                                    user=target_user,
                                    patient=patient
                                )
                                if created:
                                    direct_created += 1

                        if selected_group:
                            for patient in patients:
                                _, created = GroupPatientAssignment.objects.get_or_create(
                                    group=selected_group,
                                    patient=patient
                                )
                                if created:
                                    group_created += 1

                        status_message = (
                            f'Assigned {direct_created} direct assignment(s) '
                            f'and {group_created} group assignment(s).'
                        )
                        status_type = 'success'
                    elif action == 'unassign':
                        direct_deleted = 0
                        group_deleted = 0
                        if target_users:
                            direct_deleted, _ = PatientAssignment.objects.filter(
                                user__in=target_users,
                                patient__in=patients
                            ).delete()
                        if selected_group:
                            group_deleted, _ = GroupPatientAssignment.objects.filter(
                                group=selected_group,
                                patient__in=patients
                            ).delete()
                        status_message = (
                            f'Removed {direct_deleted} direct assignment(s) '
                            f'and {group_deleted} group assignment(s).'
                        )
                        status_type = 'success'
                    else:
                        status_message = 'Unknown action.'
                        status_type = 'error'

    users = User.objects.order_by('username')
    patients = Patient.objects.order_by('patient_id')
    assignments = PatientAssignment.objects.select_related('user', 'patient').order_by('-assigned_at')
    group_assignments = GroupPatientAssignment.objects.select_related('group', 'patient').prefetch_related(
        'group__users'
    ).order_by('-assigned_at')
    assignment_groups = AssignmentGroup.objects.filter(created_by=request.user).prefetch_related('users')
    feedbacks = Feedback.objects.select_related('user', 'patient', 'roi_rt1', 'roi_rt2').order_by('-updated_at')
    feedbacks = Feedback.objects.select_related('user', 'patient', 'roi_rt1', 'roi_rt2').order_by('-updated_at')

    assigned_user_ids = set(assignments.values_list('user_id', flat=True).distinct())
    group_user_ids = set(
        group_assignments.values_list('group__users__id', flat=True).distinct()
    )
    assigned_user_ids = assigned_user_ids.union(group_user_ids)
    assigned_users_count = len(assigned_user_ids)
    assigned_patients_count = Patient.objects.filter(
        Q(assignments__isnull=False) | Q(group_assignments__isnull=False)
    ).distinct().count()
    assigned_feedbacks_count = Feedback.objects.filter(user_id__in=assigned_user_ids).count()
    total_assignments = assignments.count() + group_assignments.count()

    assignment_map = {
        patient.id: {
            'patient': patient,
            'usernames': set(),
            'groups': set(),
            'last_assigned': None,
        }
        for patient in patients
    }

    for assignment in assignments:
        entry = assignment_map.get(assignment.patient_id)
        if not entry:
            continue
        entry['usernames'].add(assignment.user.username)
        if entry['last_assigned'] is None or assignment.assigned_at > entry['last_assigned']:
            entry['last_assigned'] = assignment.assigned_at

    for assignment in group_assignments:
        entry = assignment_map.get(assignment.patient_id)
        if not entry:
            continue
        entry['groups'].add(assignment.group.name)
        for group_user in assignment.group.users.all():
            entry['usernames'].add(group_user.username)
        if entry['last_assigned'] is None or assignment.assigned_at > entry['last_assigned']:
            entry['last_assigned'] = assignment.assigned_at

    assignment_rows = []
    for patient in patients:
        entry = assignment_map[patient.id]
        entry['usernames'] = sorted(entry['usernames'])
        entry['groups'] = sorted(entry['groups'])
        assignment_rows.append(entry)

    assignment_page_number = request.GET.get('assignment_page') or 1
    assignment_paginator = Paginator(assignment_rows, 8)
    assignment_page_obj = assignment_paginator.get_page(assignment_page_number)

    feedback_page_number = request.GET.get('feedback_page') or 1
    feedback_paginator = Paginator(feedbacks, 10)
    feedback_page_obj = feedback_paginator.get_page(feedback_page_number)

    assignment_query_params = request.GET.copy()
    assignment_query_params.pop('assignment_page', None)
    assignment_querystring = assignment_query_params.urlencode()
    assignment_page_prefix = f'?{assignment_querystring}&' if assignment_querystring else '?'

    feedback_query_params = request.GET.copy()
    feedback_query_params.pop('feedback_page', None)
    feedback_querystring = feedback_query_params.urlencode()
    feedback_page_prefix = f'?{feedback_querystring}&' if feedback_querystring else '?'

    context = {
        'users': users,
        'patients': patients,
        'assignments': assignments,
        'assignment_rows': assignment_page_obj.object_list,
        'assignment_page_obj': assignment_page_obj,
        'feedback_page_obj': feedback_page_obj,
        'feedbacks': feedback_page_obj.object_list,
        'assigned_users_count': assigned_users_count,
        'assigned_patients_count': assigned_patients_count,
        'total_assignments': total_assignments,
        'assignment_groups': assignment_groups,
        'group_assignments': group_assignments,
        'assigned_feedbacks_count': assigned_feedbacks_count,
        'assignment_page_prefix': assignment_page_prefix,
        'feedback_page_prefix': feedback_page_prefix,
        'status_message': status_message,
        'status_type': status_type,
    }

    return render(request, 'admin_dashboard.html', context)


@login_required
def dicom_web_viewer(request, patient_uuid=None):
    """DICOM web viewer for comparing RT structures"""
    
    def load_dicom_files_from_database(patient):
        """Load DICOM files from database"""
        ct_file_paths = []
        rtstruct_file_paths = []
        processed_dirs = set()
        
        studies = DICOMStudy.objects.filter(patient=patient)
        
        for study in studies:
            series_list = DICOMSeries.objects.filter(study=study)
            
            for series in series_list:
                if series.series_root_path and Path(series.series_root_path).exists():
                    series_path = Path(series.series_root_path)
                    
                    series_path_str = str(series_path)
                    if series_path_str in processed_dirs:
                        continue
                    processed_dirs.add(series_path_str)
                    
                    dicom_files = list(series_path.glob("*.dcm"))
                    
                    for dicom_file in dicom_files:
                        try:
                            ds = pydicom.dcmread(dicom_file, stop_before_pixels=True)
                            modality = getattr(ds, 'Modality', None)
                            
                            if modality == 'CT':
                                ct_file_paths.append(str(dicom_file))
                            elif modality == 'RTSTRUCT':
                                rtstruct_file_paths.append(str(dicom_file))
                        except Exception as e:
                            print(f"Error reading {dicom_file.name}: {e}")
                            continue
        
        return ct_file_paths, rtstruct_file_paths
    
    def load_dicom_files_from_paths(file_paths):
        """Load DICOM files from paths"""
        dicom_files = []
        
        for file_path in file_paths:
            try:
                if Path(file_path).exists():
                    ds = pydicom.dcmread(file_path)
                    dicom_files.append(ds)
            except Exception as e:
                print(f"Error reading {file_path}: {e}")
        
        return dicom_files
    
    def analyze_dicom_data(dicom_files):
        """Separate CT and RTSTRUCT files"""
        ct_files = []
        rtstruct_files = []
        
        for ds in dicom_files:
            modality = getattr(ds, 'Modality', None)
            if modality == 'CT':
                ct_files.append(ds)
            elif modality == 'RTSTRUCT':
                rtstruct_files.append(ds)
        
        return ct_files, rtstruct_files
    
    def analyze_rtstruct(rtstruct_file):
        """Analyze structures in RTSTRUCT file"""
        if not hasattr(rtstruct_file, 'StructureSetROISequence'):
            return []
        
        structures = []
        for roi in rtstruct_file.StructureSetROISequence:
            roi_number = int(roi.ROINumber)
            roi_label = str(roi.ROIName)
            
            roi_generation_algorithm = getattr(roi, 'ROIGenerationAlgorithm', 'Unknown')
            if hasattr(roi_generation_algorithm, '__iter__'):
                roi_generation_algorithm = str(roi_generation_algorithm[0]) if roi_generation_algorithm else 'Unknown'
            else:
                roi_generation_algorithm = str(roi_generation_algorithm) if roi_generation_algorithm else 'Unknown'
            
            structures.append({
                'number': roi_number,
                'name': roi_label,
                'algorithm': roi_generation_algorithm
            })
        
        return structures
    
    def extract_roi_contours(rtstruct_file):
        """Extract ROI contour data"""
        if not hasattr(rtstruct_file, 'StructureSetROISequence') or not hasattr(rtstruct_file, 'ROIContourSequence'):
            return {}
        
        roi_contours = {}
        
        roi_number_to_name = {}
        for roi in rtstruct_file.StructureSetROISequence:
            roi_number = int(roi.ROINumber)
            roi_label = str(roi.ROIName)
            roi_number_to_name[roi_number] = roi_label
        
        for contour_seq in rtstruct_file.ROIContourSequence:
            roi_number = int(contour_seq.ReferencedROINumber)
            roi_label = roi_number_to_name.get(roi_number, f"ROI_{roi_number}")
            
            contours = []
            if hasattr(contour_seq, 'ContourSequence'):
                for contour in contour_seq.ContourSequence:
                    if hasattr(contour, 'ContourData') and len(contour.ContourData) >= 6:
                        points = []
                        contour_data = contour.ContourData
                        for i in range(0, len(contour_data), 3):
                            if i + 2 < len(contour_data):
                                points.append([
                                    float(contour_data[i]),
                                    float(contour_data[i+1]),
                                    float(contour_data[i+2])
                                ])
                        
                        if len(points) >= 3:
                            geometric_type = getattr(contour, 'ContourGeometricType', 'CLOSED_PLANAR')
                            if hasattr(geometric_type, '__iter__'):
                                geometric_type = str(geometric_type[0]) if geometric_type else 'CLOSED_PLANAR'
                            else:
                                geometric_type = str(geometric_type) if geometric_type else 'CLOSED_PLANAR'
                            
                            contours.append({
                                'points': points,
                                'geometric_type': geometric_type
                            })
            
            if contours:
                color = [1.0, 0.0, 0.0]
                if hasattr(contour_seq, 'ROIDisplayColor'):
                    roi_color = contour_seq.ROIDisplayColor
                    if hasattr(roi_color, '__iter__') and len(roi_color) >= 3:
                        color = [float(roi_color[0]), float(roi_color[1]), float(roi_color[2])]
                
                roi_contours[roi_label] = {
                    'number': roi_number,
                    'contours': contours,
                    'color': color
                }
        
        return roi_contours
    
    def prepare_ct_data(ct_files):
        """Prepare CT data for viewer"""
        if not ct_files:
            return []
        
        ct_files_sorted = sorted(ct_files, key=lambda x: float(getattr(x, 'ImagePositionPatient', [0, 0, 0])[2]) if hasattr(x, 'ImagePositionPatient') else 0)
        
        ct_data = []
        for i, ct_file in enumerate(ct_files_sorted):
            if hasattr(ct_file, 'pixel_array'):
                pixel_array = ct_file.pixel_array
                
                image_position = getattr(ct_file, 'ImagePositionPatient', [0, 0, 0])
                if hasattr(image_position, '__iter__'):
                    image_position = [float(x) for x in image_position]
                else:
                    image_position = [0, 0, 0]
                
                slice_location = getattr(ct_file, 'SliceLocation', 0)
                if hasattr(slice_location, '__iter__'):
                    slice_location = float(slice_location[0]) if slice_location else 0
                else:
                    slice_location = float(slice_location) if slice_location else 0
                
                instance_number = getattr(ct_file, 'InstanceNumber', i+1)
                if hasattr(instance_number, '__iter__'):
                    instance_number = int(instance_number[0]) if instance_number else i+1
                else:
                    instance_number = int(instance_number) if instance_number else i+1
                
                pixel_spacing = getattr(ct_file, 'PixelSpacing', [1.0, 1.0])
                if hasattr(pixel_spacing, '__iter__'):
                    pixel_spacing = [float(x) for x in pixel_spacing]
                else:
                    pixel_spacing = [1.0, 1.0]
                
                image_orientation = getattr(ct_file, 'ImageOrientationPatient', [1, 0, 0, 0, 1, 0])
                if hasattr(image_orientation, '__iter__'):
                    image_orientation = [float(x) for x in image_orientation]
                else:
                    image_orientation = [1, 0, 0, 0, 1, 0]
                
                slice_data = {
                    'index': i,
                    'width': int(pixel_array.shape[1]),
                    'height': int(pixel_array.shape[0]),
                    'pixels': pixel_array.flatten().tolist(),
                    'image_position': image_position,
                    'slice_location': slice_location,
                    'instance_number': instance_number,
                    'pixel_spacing': pixel_spacing,
                    'image_orientation': image_orientation
                }
                ct_data.append(slice_data)
        
        return ct_data
    
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
        
        studies = DICOMStudy.objects.filter(patient=patient)
        
        if not studies.exists():
            return render(request, 'dicom_web_viewer.html', {
                'error': f'No studies found for patient {patient.patient_id}'
            })
        
        latest_study = studies.first()
        
        ct_file_paths, rtstruct_file_paths = load_dicom_files_from_database(patient)
        
        print(f"DEBUG: Patient ID: {patient.patient_id}")
        print(f"DEBUG: Found {len(ct_file_paths)} CT files from database")
        print(f"DEBUG: Found {len(rtstruct_file_paths)} RTSTRUCT files from database")
        
        if not ct_file_paths:
            return render(request, 'dicom_web_viewer.html', {
                'error': f'No CT files found for patient {patient.patient_id}'
            })
        
        if len(rtstruct_file_paths) < 2:
            return render(request, 'dicom_web_viewer.html', {
                'error': f'Need at least 2 RTSTRUCT files for comparison, found {len(rtstruct_file_paths)}. Found {len(ct_file_paths)} CT files.'
            })
        
        dicom_files = load_dicom_files_from_paths(ct_file_paths + rtstruct_file_paths)
        ct_files, rtstruct_files = analyze_dicom_data(dicom_files)
        
        patient_id_display = patient.patient_id
        study_date = str(latest_study.study_date) if latest_study.study_date else 'Unknown'
        
        rt1_data = []
        rt2_data = []
        rt1_contours = {}
        rt2_contours = {}
        common_structures = []
        rt1_label = 'RTSTRUCT 1'
        rt2_label = 'RTSTRUCT 2'
        rt1_dicom_label = 'RTSTRUCT 1'
        rt2_dicom_label = 'RTSTRUCT 2'
        rt1_sop_uid = ''
        rt2_sop_uid = ''

        def get_rtstruct_label(rtstruct_file, index):
            """Get a human-readable label from RTSTRUCT DICOM metadata."""
            label = getattr(rtstruct_file, 'StructureSetLabel', None)
            if label:
                return str(label)
            return f'RTSTRUCT {index}'
        
        def build_rtstruct_label_dicom(ds, index):
            """Build a human-readable label from RTSTRUCT DICOM metadata."""
            parts = []
            label = getattr(ds, 'StructureSetLabel', None)
            if label:
                parts.append(str(label))
            desc = getattr(ds, 'SeriesDescription', None)
            if desc and str(desc) != str(label):
                parts.append(str(desc))
            sop_uid = getattr(ds, 'SOPInstanceUID', None)
            if sop_uid:
                parts.append(f'SOP: ...{str(sop_uid)[-12:]}')
            if parts:
                return ' | '.join(parts)
            return f'RTSTRUCT {index}'
        
        if len(rtstruct_files) >= 2:
            rt1_dicom_label = build_rtstruct_label_dicom(rtstruct_files[0], 1)
            rt2_dicom_label = build_rtstruct_label_dicom(rtstruct_files[1], 2)
            rt1_label = get_rtstruct_label(rtstruct_files[0], 1)
            rt2_label = get_rtstruct_label(rtstruct_files[1], 2)
            rt1_sop_uid = getattr(rtstruct_files[0], 'SOPInstanceUID', '') or ''
            rt2_sop_uid = getattr(rtstruct_files[1], 'SOPInstanceUID', '') or ''
            
            rt1_data = analyze_rtstruct(rtstruct_files[0])
            rt2_data = analyze_rtstruct(rtstruct_files[1])
            
            rt1_contours = extract_roi_contours(rtstruct_files[0])
            rt2_contours = extract_roi_contours(rtstruct_files[1])
            
            names1 = {s['name'] for s in rt1_data}
            names2 = {s['name'] for s in rt2_data}
            
            common_structures = sorted(list(names1 & names2))
        
        ct_data = prepare_ct_data(ct_files)
        
        # Prepare ROI data mapping for frontend
        roi_data = {}
        if common_structures:
            # Get ROI objects for common structures
            roi_objects = {}
            if rtstruct_files:
                # Try to get ROI objects from the first RTSTRUCT
                rtstruct_instance = RTStruct.objects.filter(instance__sop_instance_uid=rtstruct_files[0].get('SOPInstanceUID', '')).first()
                if rtstruct_instance:
                    roi_objects = {r.roi_label: str(r.id) for r in Roi.objects.filter(rtstruct=rtstruct_instance)}
            
            # Map ROI names to their IDs
            for structure in common_structures:
                roi_data[structure] = roi_objects.get(structure, '')

        # Load ROI-specific feedback (ratings) for the user
        roi_feedback = {}
        if request.user.is_authenticated and common_structures:
            feedback_filter = {
                'patient': patient,
                'user': request.user,
                'roi_rt1__in': [r_id for r_id in roi_data.values() if r_id],
            }
            if latest_study and latest_study.study_instance_uid:
                feedback_filter['study_uid'] = latest_study.study_instance_uid

            feedback_objects = Feedback.objects.filter(**feedback_filter).select_related('roi_rt1', 'roi_rt2')
            
            for feedback in feedback_objects:
                if feedback.roi_rt1 and feedback.roi_rt1.roi_label:
                    roi_feedback[feedback.roi_rt1.roi_label] = {
                        'rt1_rating': feedback.rt1_rating,
                        'rt2_rating': feedback.rt2_rating,
                        'comment': feedback.comment or ''
                    }

        context = {
            'patient_id': patient_id_display,
            'patient_name': patient.patient_name,
            'patient_uuid': patient_uuid,
            'study_date': study_date,
            'study_description': latest_study.study_description,
            'study_uid': latest_study.study_instance_uid,
            'ct_count': len(ct_files),
            'rtstruct_count': len(rtstruct_files),
            'rt1_roi_count': len(rt1_data),
            'rt2_roi_count': len(rt2_data),
            'common_roi_count': len(common_structures),
            'rt1_dicom_label': rt1_dicom_label,
            'rt2_dicom_label': rt2_dicom_label,
            'rt1_label': rt1_label,
            'rt2_label': rt2_label,
            'rt1_sop_uid': rt1_sop_uid,
            'rt2_sop_uid': rt2_sop_uid,
            'ct_data': json.dumps(ct_data),
            'rt1_data': json.dumps(rt1_data),
            'rt2_data': json.dumps(rt2_data),
            'rt1_contours': json.dumps(rt1_contours),
            'rt2_contours': json.dumps(rt2_contours),
            'common_structures': common_structures,
            'roi_data': json.dumps(roi_data),
            'initial_feedback': json.dumps(roi_feedback),
            'available_patients': Patient.objects.all().order_by('patient_id')
        }
        
        return render(request, 'dicom_web_viewer.html', context)
        
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

        patient_id = data.get('patient_id')
        if not patient_id:
            return JsonResponse({'success': False, 'error': 'Missing patient_id'}, status=400)

        # Accept bulk ratings: list of {roi_id, rating_rtstruct1, rating_rtstruct2, comment}
        ratings = data.get('ratings')
        if not ratings or not isinstance(ratings, list):
            return JsonResponse({'success': False, 'error': 'Missing ratings'}, status=400)

        try:
            patient = Patient.objects.get(patient_id=patient_id)
        except Patient.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Invalid patient_id'}, status=400)

        rt1_label = (data.get('rt1_label') or '').strip()
        rt2_label = (data.get('rt2_label') or '').strip()
        rt1_sop_uid = (data.get('rt1_sop_uid') or '').strip()
        rt2_sop_uid = (data.get('rt2_sop_uid') or '').strip()
        study_uid = (data.get('study_uid') or '').strip()

        saved = 0
        errors = []
        for item in ratings:
            roi_id = item.get('roi_id')
            if not roi_id:
                continue

            try:
                roi_rt1 = Roi.objects.get(id=roi_id)
            except Roi.DoesNotExist:
                errors.append(f'Invalid roi_id: {roi_id}')
                continue

            roi_label = item.get('roi_label') or roi_rt1.roi_label
            if not roi_label:
                errors.append(f'Missing roi_label for roi_id: {roi_id}')
                continue

            # Find roi_rt2 from rt2_sop_uid
            try:
                rtstruct2 = RTStruct.objects.get(instance__sop_instance_uid=rt2_sop_uid)
                roi_rt2 = Roi.objects.get(rtstruct=rtstruct2, roi_label=roi_label)
            except (RTStruct.DoesNotExist, Roi.DoesNotExist):
                errors.append(f'Could not find matching ROI for rt2: {roi_label}')
                continue

            defaults = {'common_roi_label': roi_label}
            if study_uid:
                defaults['study_uid'] = study_uid
            if rt1_label:
                defaults['rt1_label'] = rt1_label
            if rt2_label:
                defaults['rt2_label'] = rt2_label
            if rt1_sop_uid:
                defaults['rt1_sop_uid'] = rt1_sop_uid
            if rt2_sop_uid:
                defaults['rt2_sop_uid'] = rt2_sop_uid
            r1 = item.get('rt1_rating')
            r2 = item.get('rt2_rating')
            comment = (item.get('comment') or '').strip()

            if r1 is not None:
                r1 = int(r1)
                if r1 < 1 or r1 > 10:
                    errors.append(f'{roi_label}: RTSTRUCT 1 rating must be 1-10')
                    continue
                defaults['rt1_rating'] = r1

            if r2 is not None:
                r2 = int(r2)
                if r2 < 1 or r2 > 10:
                    errors.append(f'{roi_label}: RTSTRUCT 2 rating must be 1-10')
                    continue
                defaults['rt2_rating'] = r2

            if comment:
                defaults['comment'] = comment

            if defaults:
                lookup = {
                    'user': request.user,
                    'patient': patient,
                    'roi_rt1': roi_rt1,
                    'roi_rt2': roi_rt2,
                }
                if study_uid:
                    lookup['study_uid'] = study_uid

                Feedback.objects.update_or_create(
                    **lookup,
                    defaults=defaults
                )
                saved += 1

        result = {'success': True, 'saved_count': saved}
        if errors:
            result['errors'] = errors
        return JsonResponse(result)
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)