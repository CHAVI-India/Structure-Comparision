from django.shortcuts import render, get_object_or_404
from django.db.models import Q, Avg
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.conf import settings
import pydicom
from .models import DICOMSeries, DICOMInstance, DICOMStudy, Patient
from .dicom_scanner import DICOMScanner
import json
from django.core.cache import cache
import base64
from .dicom_overlay_utils import render_ct_with_overlay, load_rtstruct_contours
import os


def home(request):
    return render(request, 'home.html')

def import_dicom(request):
    print("=== IMPORT DICOM VIEW CALLED ===")
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Invalid request"})

    files = request.FILES.getlist("files")
    print(f"Files received: {len(files)}")
    for f in files:
        print(f"  - {f.name}")
    
    if not files:
        return JsonResponse({"success": False, "error": "No files provided"})
    
    try:
        # Use the DICOM scanner for proper database processing
        from .dicom_scanner import DICOMScanner
        scanner = DICOMScanner()
        
        # Check if we should clear existing data
        clear_data = request.POST.get('clear_data', 'false').lower() == 'true'
        if clear_data:
            scanner.clear_existing_data()
        
        # Process files (this will save to database)
        results = scanner.process_files(files)
        
        print(f"Database import results: {results}")
        
        return JsonResponse({
            "success": True,
            "message": f"Successfully imported {results.get('total_files', 0)} files to database",
            "stats": {
                "studies": results.get('studies', 0),
                "series": results.get('series', 0), 
                "instances": results.get('instances', 0),
                "files": results.get('total_files', 0)
            }
        })
        
    except Exception as e:
        print(f"Import error: {e}")
        return JsonResponse({
            "success": False, 
            "error": f"Import failed: {str(e)}"
        })



def get_dicom_directories(request):
    """
    Get list of common DICOM directories for the user to choose from
    """
    # Common DICOM directories on different systems
    common_directories = [
        '/home/atabur/Desktop/DICOM',
        '/home/atabur/Desktop/DICOM_FILES',
        '/home/atabur/Desktop/STRUCTURE_COMP/dicom_data',
        '/home/atabur/Desktop/STRUCTURE_COMP/data',
        '/home/atabur/Desktop/dicom',
        '/home/atabur/Desktop/data',
        '/home/atabur/Desktop/medical_data',
        '/home/atabur/Desktop/patient_data',
        '/home/atabur/Desktop/studies',
        '/home/atabur/Desktop/rt_structures',
        '/tmp/dicom',
        '/var/dicom',
        '/opt/dicom',
    ]
    
    # Filter to only existing directories
    existing_dirs = []
    for directory in common_directories:
        if os.path.exists(directory) and os.path.isdir(directory):
            existing_dirs.append(directory)
    
    # Also check parent directories
    base_path = '/home/atabur/Desktop'
    if os.path.exists(base_path):
        for item in os.listdir(base_path):
            item_path = os.path.join(base_path, item)
            if os.path.isdir(item_path) and any(keyword in item.lower() for keyword in ['dicom', 'medical', 'patient', 'study', 'rt', 'structure']):
                existing_dirs.append(item_path)
    
    return JsonResponse({
        'directories': list(set(existing_dirs))
    })


def patients(request):
    """
    View to display all patients with their DICOM studies and series from database
    Organized by Patient ID
    """
    from django.db.models import Count, Q
    from .models import DICOMStudy, DICOMSeries, Patient
    
    search_query = request.GET.get('search', '')
    
    # Get all patients
    patients_query = Patient.objects.all()
    
    # Apply search filter if provided
    if search_query:
        patients_query = patients_query.filter(
            Q(patient_id__icontains=search_query) |
            Q(patient_name__icontains=search_query) |
            Q(dicomstudy__study_instance_uid__icontains=search_query) |
            Q(dicomstudy__study_description__icontains=search_query)
        ).distinct()
    
    # Get patients with their studies and series
    patients = patients_query.prefetch_related(
        'dicomstudy_set__dicomseries_set'
    ).annotate(
        study_count=Count('dicomstudy', distinct=True)
    ).order_by('patient_id')
    
    # Organize data by patient
    patients_data = []
    for patient in patients:
        # Get all studies for this patient
        studies = patient.dicomstudy_set.all().order_by('-study_date')
        
        patient_info = {
            'patient': patient,
            'studies': []
        }
        
        for study in studies:
            # Get all series for this study
            series_list = study.dicomseries_set.all()
            
            study_info = {
                'study': study,
                'series': series_list,
                'series_count': series_list.count()
            }
            
            patient_info['studies'].append(study_info)
        
        patient_info['total_studies'] = len(patient_info['studies'])
        patient_info['total_series'] = sum(s['series_count'] for s in patient_info['studies'])
        
        patients_data.append(patient_info)
    
    context = {
        'patients': patients_data,
        'search_query': search_query,
        'total_patients': len(patients_data),
        'total_studies': sum(p['total_studies'] for p in patients_data),
        'total_series': sum(p['total_series'] for p in patients_data),
    }
    
    print(f"Database query returned {len(patients_data)} patients")
    return render(request, "patients.html", context)


def patient_compare(request, pk):
    """
    Patient comparison view - shows all series for a patient
    and allows selecting series for side-by-side comparison
    """
    from .models import Patient, DICOMStudy, DICOMSeries
    
    # Get the patient by primary key
    patient = get_object_or_404(Patient, pk=pk)
    
    # Get all studies for this patient
    studies = patient.dicomstudy_set.all().order_by('-study_date')
    
    # Organize series by study
    studies_data = []
    for study in studies:
        series_list = study.dicomseries_set.all()
        
        # Categorize series by modality or description
        ct_series = []
        rtstruct_series = []
        other_series = []
        
        for series in series_list:
            # Get modality from the DICOMInstance
            modality = 'Unknown'
            if series.dicom_instance_uid and hasattr(series.dicom_instance_uid, 'modality'):
                modality = series.dicom_instance_uid.modality or 'Unknown'
            
            # Fallback: Try to infer modality from description if not in instance
            if modality == 'Unknown':
                description = (series.series_description or '').upper()
                if 'CT' in description or 'COMPUTED' in description:
                    modality = 'CT'
                elif 'RTSTRUCT' in description or 'RT STRUCT' in description or 'STRUCTURE' in description:
                    modality = 'RTSTRUCT'
                elif 'MR' in description or 'MAGNETIC' in description:
                    modality = 'MR'
            
            series_info = {
                'series': series,
                'uid': series.series_instance_uid,
                'description': series.series_description or 'Unnamed Series',
                'modality': modality,
                'instances': series.instance_count or 0
            }
            
            # Categorize by modality
            if modality == 'CT':
                ct_series.append(series_info)
            elif modality == 'RTSTRUCT':
                rtstruct_series.append(series_info)
            else:
                other_series.append(series_info)
        
        studies_data.append({
            'study': study,
            'ct_series': ct_series,
            'rtstruct_series': rtstruct_series,
            'other_series': other_series,
            'total_series': len(ct_series) + len(rtstruct_series) + len(other_series)
        })
    
    context = {
        'patient': patient,
        'studies': studies_data,
        'total_studies': len(studies_data),
    }
    
    return render(request, "patient_compare.html", context)


def dicom_dual_viewer(request, left_series_uid, right_series_uid):
    """
    Dual DICOM viewer - displays two series side-by-side for comparison
    Left: typically CT, Right: typically RTSTRUCT
    """
    from .models import DICOMSeries
    
    # Get both series
    left_series = get_object_or_404(DICOMSeries, series_instance_uid=left_series_uid)
    right_series = get_object_or_404(DICOMSeries, series_instance_uid=right_series_uid)
    
    context = {
        'left_series': left_series,
        'right_series': right_series,
        'left_series_uid': left_series_uid,
        'right_series_uid': right_series_uid,
    }
    
    return render(request, "dicom_dual_viewer.html", context)


def dicom_overlay_viewer(request, ct_series_uid, rtstruct_series_uid):
    """
    View CT with RT Structure overlay using canvas rendering
    """
    from .models import DICOMSeries
    
    # Get both series
    ct_series = get_object_or_404(DICOMSeries, series_instance_uid=ct_series_uid)
    rtstruct_series = get_object_or_404(DICOMSeries, series_instance_uid=rtstruct_series_uid)
    
    context = {
        'ct_series': ct_series,
        'rtstruct_series': rtstruct_series,
        'ct_series_uid': ct_series_uid,
        'rtstruct_series_uid': rtstruct_series_uid,
    }
    
    return render(request, "dicom_overlay_viewer.html", context)


def modern_dicom_viewer(request):
    """
    Modern DICOM viewer with improved UI/UX
    """
    return render(request, "modern_dicom_viewer.html")


def improved_dicom_viewer(request):
    """
    Improved DICOM viewer with smooth scrolling and no lower bar
    """
    return render(request, "improved_dicom_viewer.html")


def debug_viewer(request):
    """
    Debug DICOM viewer to troubleshoot issues
    """
    return render(request, "debug_viewer.html")


def professional_dicom_viewer(request):
    """
    Professional DICOM viewer with client-side rendering and proper ROI alignment
    """
    return render(request, "professional_dicom_viewer.html")


def professional_dicom_viewer_fixed(request):
    """
    Professional DICOM viewer - Fixed version with proper image rendering
    """
    return render(request, "professional_dicom_viewer_fixed.html")


def simple_test_viewer(request):
    """
    Simple test viewer to debug CT image loading issues
    """
    return render(request, "simple_test_viewer.html")


# Helper to get sorted CT paths
def get_sorted_ct_paths(series):
    cache_key = f"sorted_paths_{series.series_instance_uid}"
    paths = cache.get(cache_key)
    if paths:
        return paths
        
    paths = []
    root = series.series_root_path
    if root and os.path.exists(root):
        for f in os.listdir(root):
            if f.endswith('.dcm'):
                fp = os.path.join(root, f)
                try:
                    ds = pydicom.dcmread(fp, stop_before_pixels=True)
                    if ds.SeriesInstanceUID == series.series_instance_uid:
                        z = float(ds.ImagePositionPatient[2]) if 'ImagePositionPatient' in ds else 0
                        paths.append((z, fp))
                except:
                    pass
    
    paths.sort(key=lambda x: x[0])
    paths = [p[1] for p in paths]
    cache.set(cache_key, paths, 3600)
    return paths

def get_viewer_data(request, ct_series_uid, rtstruct_series_uid):
    from .models import DICOMSeries
    
    ct_series = get_object_or_404(DICOMSeries, series_instance_uid=ct_series_uid)
    rtstruct_series = get_object_or_404(DICOMSeries, series_instance_uid=rtstruct_series_uid)
    
    # Get slice count
    paths = get_sorted_ct_paths(ct_series)
    
    # Get ROIs
    rois = []
    rt_path = rtstruct_series.dicom_instance_uid.instance_path if rtstruct_series.dicom_instance_uid else None
    if rt_path and os.path.exists(rt_path):
        contours = load_rtstruct_contours(rt_path)
        for name, data in contours.items():
            # Convert color float array to hex string
            color = data.get('color', [1, 0, 0])
            hex_color = '#{:02x}{:02x}{:02x}'.format(
                int(color[0]*255), int(color[1]*255), int(color[2]*255)
            )
            rois.append({
                'id': name,
                'name': name,
                'color': hex_color
            })
    
    return JsonResponse({
        'slice_count': len(paths),
        'rois': rois
    })

def get_dicom_slice_overlay(request, ct_series_uid, rtstruct_series_uid, slice_index=0):
    from .models import DICOMSeries
    
    ct_series = get_object_or_404(DICOMSeries, series_instance_uid=ct_series_uid)
    rtstruct_series = get_object_or_404(DICOMSeries, series_instance_uid=rtstruct_series_uid)
    
    paths = get_sorted_ct_paths(ct_series)
    if not paths or int(slice_index) >= len(paths):
        return HttpResponse('Invalid slice', status=404)
        
    ct_path = paths[int(slice_index)]
    rt_path = rtstruct_series.dicom_instance_uid.instance_path if rtstruct_series.dicom_instance_uid else None
    
    # Get requested ROIs
    rois_param = request.GET.get('rois', '')
    rois_to_include = rois_param.split(',') if rois_param else None
    
    img_base64 = render_ct_with_overlay(ct_path, rt_path, rois_to_include)
    
    if img_base64:
        img_data = base64.b64decode(img_base64)
        return HttpResponse(img_data, content_type="image/png")
    else:
        return HttpResponse('Error rendering', status=500)




def dicom_viewer(request, series_uid, rt_structure_id=None):
    """DICOM viewer - RT Structure features disabled (models not available)"""
    series = get_object_or_404(DICOMSeries, series_instance_uid=series_uid)
    
    # Get all DICOM instances for this series
    instances = DICOMInstance.objects.filter(
        dicom_instance_uid__series=series
    ).order_by('sop_instance_uid')
    
    # Prepare instance data
    instance_data = []
    for idx, instance in enumerate(instances):
        instance_data.append({
            'index': idx,
            'sop_instance_uid': instance.sop_instance_uid,
            'instance_path': instance.instance_path,
        })
    
    context = {
        'series': series,
        'patient_name': f"Patient {series.study.patient.patient_id if series.study.patient else 'N/A'}",
        'patient_id': series.study.patient.patient_id if series.study.patient else 'N/A',
        'study_date': series.study.study_date,
        'series_description': series.series_description,
        'instance_count': len(instance_data),
        'series_uid': series_uid,
    }
    
    return render(request, 'dicom_viewer.html', context)


# DICOM Handler Views for the new viewer
import json
import tempfile
import os
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

@csrf_exempt
@require_http_methods(["POST"])
def load_dicom_data(request):
    """Load DICOM data for the viewer"""
    try:
        data = json.loads(request.body)
        series_uid = data.get('series_uid')
        rt_structure_id = data.get('rt_structure_id')
        
        # Get series
        series = get_object_or_404(DICOMSeries, series_instance_uid=series_uid)
        
        # Get instances
        instances = DICOMInstance.objects.filter(
            dicom_instance_uid__series=series
        ).order_by('sop_instance_uid')
        
        # Get ROI names from RT structure (simplified for now)
        roi_names = []  # This would come from parsing the RT structure file
        
        return JsonResponse({
            'success': True,
            'instance_count': instances.count(),
            'roi_names': roi_names,
            'roi_colors': {},  # This would come from RT structure parsing
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@csrf_exempt
@require_http_methods(["POST"])
def get_dicom_slice(request):
    """Get a specific DICOM slice as an image"""
    try:
        data = json.loads(request.body)
        slice_index = data.get('slice_index')
        series_uid = data.get('series_uid')
        window_center = data.get('window_center', 40)
        window_width = data.get('window_width', 400)
        selected_rois = data.get('selected_rois', [])
        
        # Get the specific instance
        series = get_object_or_404(DICOMSeries, series_instance_uid=series_uid)
        instances = DICOMInstance.objects.filter(
            dicom_instance_uid__series=series
        ).order_by('sop_instance_uid')
        
        if slice_index >= instances.count():
            return JsonResponse({
                'success': False,
                'error': 'Slice index out of range'
            })
        
        instance = instances[slice_index]
        
        # Try to read the DICOM file from database
        try:
            import pydicom
            import numpy as np
            from PIL import Image
            import io
            import base64
            
            # Read DICOM data from database
            if instance.file_content:
                # Use BytesIO to read from binary field
                ds = pydicom.dcmread(io.BytesIO(instance.file_content))
            else:
                # Fallback to file path if file_content is empty
                ds = pydicom.dcmread(instance.instance_path)
            
            # Get pixel data
            if hasattr(ds, 'pixel_array'):
                pixel_array = ds.pixel_array
                
                # Apply window/level
                min_val = window_center - window_width // 2
                max_val = window_center + window_width // 2
                
                # Clip values to window range
                pixel_array = np.clip(pixel_array, min_val, max_val)
                
                # Normalize to 0-255
                if pixel_array.max() > pixel_array.min():
                    pixel_array = ((pixel_array - min_val) / (max_val - min_val) * 255).astype(np.uint8)
                else:
                    pixel_array = np.zeros_like(pixel_array, dtype=np.uint8)
                
                # Convert to PIL Image
                image = Image.fromarray(pixel_array, mode='L')
                
                # Convert to base64
                buffer = io.BytesIO()
                image.save(buffer, format='PNG')
                image_base64 = base64.b64encode(buffer.getvalue()).decode()
                
                return JsonResponse({
                    'success': True,
                    'image': image_base64,
                    'metadata': {
                        'slice_index': slice_index,
                        'window_center': window_center,
                        'window_width': window_width,
                        'rows': getattr(ds, 'Rows', 0),
                        'columns': getattr(ds, 'Columns', 0),
                    }
                })
            else:
                # No pixel data, return placeholder
                placeholder_image = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
                return JsonResponse({
                    'success': True,
                    'image': placeholder_image,
                    'metadata': {
                        'slice_index': slice_index,
                        'window_center': window_center,
                        'window_width': window_width,
                        'error': 'No pixel data in DICOM file'
                    }
                })
                
        except Exception as dicom_error:
            print(f"Error reading DICOM data: {dicom_error}")
            # Return placeholder if DICOM reading fails
            placeholder_image = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
            return JsonResponse({
                'success': True,
                'image': placeholder_image,
                'metadata': {
                    'slice_index': slice_index,
                    'window_center': window_center,
                    'window_width': window_width,
                    'error': f'Cannot read DICOM data: {str(dicom_error)}'
                }
            })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@csrf_exempt
@require_http_methods(["POST"])
def render_all_slices(request):
    """Pre-render all slices for faster navigation"""
    try:
        data = json.loads(request.body)
        window_center = data.get('window_center', 40)
        window_width = data.get('window_width', 400)
        selected_rois = data.get('selected_rois', [])
        
        # For now, return empty slices array
        # In a real implementation, you would render all slices
        
        return JsonResponse({
            'success': True,
            'slices': []
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

# @csrf_exempt
# @require_http_methods(["POST"])
# def save_contour_ratings(request):
#     """Save contour ratings to the database"""
#     try:
#         data = json.loads(request.body)
#         series_uid = data.get('series_uid')
#         overall_rating = data.get('overall_rating')
#         assessor_name = data.get('assessor_name')
#         modification_time = data.get('modification_time')
#         date_reviewed = data.get('date_reviewed')
#         structure_ratings = data.get('structure_ratings', {})
        
#         # Get the RT structure (this is a simplified approach)
#         series = get_object_or_404(DICOMSeries, series_instance_uid=series_uid)
#         rt_structure = RTStructureFileImport.objects.filter(
#             deidentified_series_instance_uid=series
#         ).first()
        
#         if not rt_structure:
#             return JsonResponse({
#                 'success': False,
#                 'error': 'RT Structure not found for this series'
#             })
        
#         # Update the RT structure with overall rating
#         rt_structure.assessor_name = assessor_name
#         rt_structure.overall_rating = overall_rating
#         rt_structure.modification_time_required = modification_time
#         rt_structure.date_contour_reviewed = date_reviewed
#         rt_structure.save()
        
#         # Save individual structure ratings
#         for roi_name, rating_data in structure_ratings.items():
#             # Create or update VOI data
#             voi_data, created = RTStructureFileVOIData.objects.update_or_create(
#                 rt_structure_file_import=rt_structure,
#                 volume_name=roi_name,
#                 defaults={
#                     'contour_modification': rating_data.get('modification', 'NO_MODIFICATION'),
#                     'contour_modification_comments': rating_data.get('comments', ''),
#                 }
#             )
            
#             if not created:
#                 voi_data.contour_modification = rating_data.get('modification', 'NO_MODIFICATION')
#                 voi_data.contour_modification_comments = rating_data.get('comments', '')
#                 voi_data.save()
        
#         return JsonResponse({
#             'success': True,
#             'message': 'Ratings saved successfully'
#         })
        
#     except Exception as e:
#         return JsonResponse({
#             'success': False,
#             'error': str(e)
#         })



def view_rt_structure_list(request, series_uid):
    """View list of RT structures for a series - Feature disabled (models not available)"""
    return JsonResponse({
        'success': False,
        'error': 'RT Structure feature not available - models not configured'
    })


def dicom_web_viewer(request, patient_uuid=None):
    """
    Web-based DICOM viewer for CT and RTSTRUCT visualization
    Connects to database to load patient-specific DICOM data
    """
    import pydicom
    import numpy as np
    from pathlib import Path
    from django.shortcuts import get_object_or_404
    
    def load_dicom_files_from_database(patient):
        """
        Load DICOM files from database using Patient → Study → Series
        Scans series_root_path and checks EACH file's modality individually
        Returns separate lists of CT and RTSTRUCT file paths
        """
        import pydicom
        ct_file_paths = []
        rtstruct_file_paths = []
        processed_dirs = set()  # Track processed directories to avoid duplicates
        
        # Get all studies for this patient
        studies = DICOMStudy.objects.filter(patient=patient)
        
        for study in studies:
            # Get all series for this study
            series_list = DICOMSeries.objects.filter(study=study)
            
            for series in series_list:
                # Use series_root_path to find DICOM files
                if series.series_root_path and Path(series.series_root_path).exists():
                    series_path = Path(series.series_root_path)
                    
                    # Skip if we've already processed this directory
                    series_path_str = str(series_path)
                    if series_path_str in processed_dirs:
                        continue
                    processed_dirs.add(series_path_str)
                    
                    # Find all .dcm files in the series directory
                    dicom_files = list(series_path.glob("*.dcm"))
                    
                    # Check EACH file's modality individually
                    # (CT and RTSTRUCT files may be in the same directory)
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
        """Load DICOM files from a list of file paths"""
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
        """Analyze DICOM files and separate CT and RTSTRUCT datasets"""
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
        """Analyze structures in an RTSTRUCT file"""
        if not hasattr(rtstruct_file, 'StructureSetROISequence'):
            return []
        
        structures = []
        for roi in rtstruct_file.StructureSetROISequence:
            roi_number = int(roi.ROINumber)
            roi_name = str(roi.ROIName)
            
            # Handle ROIGenerationAlgorithm which might be a MultiValue
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
        """Extract ROI contour data from RTSTRUCT file"""
        if not hasattr(rtstruct_file, 'StructureSetROISequence') or not hasattr(rtstruct_file, 'ROIContourSequence'):
            return {}
        
        roi_contours = {}
        
        # Create mapping from ROI number to contour data
        roi_number_to_name = {}
        for roi in rtstruct_file.StructureSetROISequence:
            roi_number = int(roi.ROINumber)
            roi_name = str(roi.ROIName)
            roi_number_to_name[roi_number] = roi_name
        
        # Get contour sequences
        for contour_seq in rtstruct_file.ROIContourSequence:
            roi_number = int(contour_seq.ReferencedROINumber)
            roi_name = roi_number_to_name.get(roi_number, f"ROI_{roi_number}")
            
            contours = []
            if hasattr(contour_seq, 'ContourSequence'):
                for contour in contour_seq.ContourSequence:
                    if hasattr(contour, 'ContourData') and len(contour.ContourData) >= 6:
                        # Convert contour data to points
                        points = []
                        contour_data = contour.ContourData
                        for i in range(0, len(contour_data), 3):
                            if i + 2 < len(contour_data):
                                points.append([
                                    float(contour_data[i]),     # X
                                    float(contour_data[i+1]), # Y  
                                    float(contour_data[i+2])  # Z
                                ])
                        
                        if len(points) >= 3:  # Need at least 3 points for a valid contour
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
                # Handle ROI display color
                color = [1.0, 0.0, 0.0]  # Default red
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
        """Prepare CT data for web viewer with proper slice ordering"""
        if not ct_files:
            return []
        
        # Sort CT files by slice position
        ct_files_sorted = sorted(ct_files, key=lambda x: float(getattr(x, 'ImagePositionPatient', [0, 0, 0])[2]) if hasattr(x, 'ImagePositionPatient') else 0)
        
        ct_data = []
        for i, ct_file in enumerate(ct_files_sorted):
            if hasattr(ct_file, 'pixel_array'):
                pixel_array = ct_file.pixel_array
                
                # Convert MultiValue objects to regular lists
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
                
                # Get pixel spacing for coordinate transformation
                pixel_spacing = getattr(ct_file, 'PixelSpacing', [1.0, 1.0])
                if hasattr(pixel_spacing, '__iter__'):
                    pixel_spacing = [float(x) for x in pixel_spacing]
                else:
                    pixel_spacing = [1.0, 1.0]
                
                # Get image orientation (important for coordinate transformation)
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
        # If no patient_uuid provided, get the first patient from database
        if not patient_uuid:
            first_patient = Patient.objects.first()
            if first_patient:
                patient_uuid = first_patient.id
            else:
                return render(request, 'dicom_web_viewer.html', {
                    'error': 'No patients found in database'
                })
        
        # Get patient from database using UUID
        patient = get_object_or_404(Patient, id=patient_uuid)
        
        # Get all studies for this patient
        studies = DICOMStudy.objects.filter(patient=patient)
        
        if not studies.exists():
            return render(request, 'dicom_web_viewer.html', {
                'error': f'No studies found for patient {patient.patient_id}'
            })
        
        # Get the most recent study
        latest_study = studies.first()
        
        # Load DICOM file paths from database using the helper function
        ct_file_paths, rtstruct_file_paths = load_dicom_files_from_database(patient)
        
        print(f"DEBUG: Patient ID: {patient.patient_id}")
        print(f"DEBUG: Found {len(ct_file_paths)} CT files from database")
        print(f"DEBUG: Found {len(rtstruct_file_paths)} RTSTRUCT files from database")
        
        # Validate we have the necessary files
        if not ct_file_paths:
            return render(request, 'dicom_web_viewer.html', {
                'error': f'No CT files found for patient {patient.patient_id}'
            })
        
        if len(rtstruct_file_paths) < 2:
            return render(request, 'dicom_web_viewer.html', {
                'error': f'Need at least 2 RTSTRUCT files for comparison, found {len(rtstruct_file_paths)}. Found {len(ct_file_paths)} CT files.'
            })
        
        # Load DICOM files from the paths retrieved from database
        dicom_files = load_dicom_files_from_paths(ct_file_paths + rtstruct_file_paths)
        ct_files, rtstruct_files = analyze_dicom_data(dicom_files)
        
        # Get patient info
        patient_id_display = patient.patient_id
        study_date = str(latest_study.study_date) if latest_study.study_date else 'Unknown'
        
        # Analyze RTSTRUCTs and extract contour data
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
            
            # Extract contour data
            rtstruct1_contours = extract_roi_contours(rtstruct_files[0])
            rtstruct2_contours = extract_roi_contours(rtstruct_files[1])
            
            # Find common structures
            names1 = {s['name'] for s in rtstruct1_data}
            names2 = {s['name'] for s in rtstruct2_data}
            
            common_structures = sorted(list(names1 & names2))
            unique_to_1 = sorted(list(names1 - names2))
            unique_to_2 = sorted(list(names2 - names1))
        
        # Prepare CT data
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
        import traceback
        print(f"Error in dicom_web_viewer: {e}")
        traceback.print_exc()
        
        return render(request, 'dicom_web_viewer.html', {
            'error': f'Error loading DICOM data: {str(e)}',
            'available_patients': Patient.objects.all().order_by('patient_id')
        })
