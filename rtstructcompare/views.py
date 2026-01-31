"""
Views for DICOM Structure Comparison
Essential functions only: home, patients, dicom_web_viewer
"""
from django.shortcuts import render, get_object_or_404
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import pydicom
from .models import DICOMSeries, DICOMInstance, DICOMStudy, Patient
import json
import numpy as np
from pathlib import Path
import traceback


def home(request):
    """Home page view"""
    return render(request, 'home.html')


def patients(request):
    """Patient list page view"""
    search_query = request.GET.get('search', '')
    
    patients_qs = Patient.objects.all()
    
    if search_query:
        patients_qs = patients_qs.filter(
            Q(patient_id__icontains=search_query) |
            Q(patient_name__icontains=search_query)
        )
    
    patients_data = []
    for patient in patients_qs:
        studies = DICOMStudy.objects.filter(patient=patient)
        total_studies = studies.count()
        
        total_series = 0
        studies_data = []
        for study in studies:
            series = DICOMSeries.objects.filter(study=study)
            series_count = series.count()
            total_series += series_count
            
            studies_data.append({
                'study': study,
                'series_count': series_count
            })
        
        patients_data.append({
            'patient': patient,
            'total_studies': total_studies,
            'total_series': total_series,
            'studies': studies_data
        })
    
    context = {
        'patients': patients_data,
        'total_patients': patients_qs.count(),
        'total_studies': DICOMStudy.objects.count(),
        'total_series': DICOMSeries.objects.count(),
        'search_query': search_query,
    }
    
    return render(request, 'patients.html', context)


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
            roi_name = str(roi.ROIName)
            
            roi_generation_algorithm = getattr(roi, 'ROIGenerationAlgorithm', 'Unknown')
            if hasattr(roi_generation_algorithm, '__iter__'):
                roi_generation_algorithm = str(roi_generation_algorithm[0]) if roi_generation_algorithm else 'Unknown'
            else:
                roi_generation_algorithm = str(roi_generation_algorithm) if roi_generation_algorithm else 'Unknown'
            
            structures.append({
                'number': roi_number,
                'name': roi_name,
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
            roi_name = str(roi.ROIName)
            roi_number_to_name[roi_number] = roi_name
        
        for contour_seq in rtstruct_file.ROIContourSequence:
            roi_number = int(contour_seq.ReferencedROINumber)
            roi_name = roi_number_to_name.get(roi_number, f"ROI_{roi_number}")
            
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
                
                roi_contours[roi_name] = {
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
            first_patient = Patient.objects.first()
            if first_patient:
                patient_uuid = first_patient.id
            else:
                return render(request, 'dicom_web_viewer.html', {
                    'error': 'No patients found in database'
                })
        
        patient = get_object_or_404(Patient, id=patient_uuid)
        
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
        
        rtstruct1_data = []
        rtstruct2_data = []
        rtstruct1_contours = {}
        rtstruct2_contours = {}
        common_structures = []
        unique_to_1 = []
        unique_to_2 = []
        
        if len(rtstruct_files) >= 2:
            rtstruct1_data = analyze_rtstruct(rtstruct_files[0])
            rtstruct2_data = analyze_rtstruct(rtstruct_files[1])
            
            rtstruct1_contours = extract_roi_contours(rtstruct_files[0])
            rtstruct2_contours = extract_roi_contours(rtstruct_files[1])
            
            names1 = {s['name'] for s in rtstruct1_data}
            names2 = {s['name'] for s in rtstruct2_data}
            
            common_structures = sorted(list(names1 & names2))
            unique_to_1 = sorted(list(names1 - names2))
            unique_to_2 = sorted(list(names2 - names1))
        
        ct_data = prepare_ct_data(ct_files)
        
        context = {
            'patient_id': patient_id_display,
            'patient_name': patient.patient_name,
            'patient_uuid': patient_uuid,
            'study_date': study_date,
            'study_description': latest_study.study_description,
            'ct_count': len(ct_files),
            'rtstruct_count': len(rtstruct_files),
            'ct_data': json.dumps(ct_data),
            'rtstruct1_data': json.dumps(rtstruct1_data),
            'rtstruct2_data': json.dumps(rtstruct2_data),
            'rtstruct1_contours': json.dumps(rtstruct1_contours),
            'rtstruct2_contours': json.dumps(rtstruct2_contours),
            'common_structures': common_structures,
            'unique_to_1': unique_to_1,
            'unique_to_2': unique_to_2,
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


# API Endpoints (not currently used by the viewer)
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
