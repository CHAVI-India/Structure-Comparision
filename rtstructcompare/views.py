from django.shortcuts import render, get_object_or_404
from django.db.models import Q, Avg
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.conf import settings
import pydicom
from .models import DICOMSeries, RTStructureFileImport, DICOMInstance, RTStructureFileVOIData, ContourModificationTypeChoices, DICOMStudy
from .dicom_scanner import DICOMScanner
import json
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
    View to display all patients with their DICOM studies and RT structures from database
    """
    from django.db.models import Avg, Q
    from .models import DICOMStudy, DICOMSeries, RTStructureFileImport
    
    search_query = request.GET.get('search', '')
    
    # Get all studies with their series and RT structures
    studies_query = DICOMStudy.objects.all()
    
    # Apply search filter if provided
    if search_query:
        studies_query = studies_query.filter(
            Q(study_instance_uid__icontains=search_query) |
            Q(study_description__icontains=search_query) |
            Q(study_protocol__icontains=search_query) |
            Q(study_modality__icontains=search_query) |
            Q(accession_number__icontains=search_query) |
            Q(study_id__icontains=search_query)
        )
    
    studies = studies_query.select_related().prefetch_related('dicomseries_set').order_by('-study_date')
    
    patients_data = []
    for study in studies:
        # Get all series for this study
        series_list = study.dicomseries_set.all()
        
        for series in series_list:
            # Get RT structures for this series
            rt_structures = RTStructureFileImport.objects.filter(
                deidentified_series_instance_uid=series
            )
            
            # Calculate rating statistics
            rated_structures = rt_structures.filter(date_contour_reviewed__isnull=False)
            rating_stats = {
                'total_structures': rt_structures.count(),
                'rated_structures': rated_structures.count(),
                'average_rating': rated_structures.aggregate(
                    avg_rating=Avg('overall_rating')
                )['avg_rating'] or 0
            }
            
            patients_data.append({
                'study': study,
                'series': series,
                'rt_structures': rt_structures,
                'rating_stats': rating_stats
            })
    
    context = {
        'patients': patients_data,
        'search_query': search_query,
        'total_patients': len(patients_data),
        'total_studies': studies.count(),
    }
    
    print(f"Database query returned {len(patients_data)} patient records")
    return render(request, "patients.html", context)


def dicom_viewer(request, series_uid, rt_structure_id):
    series = get_object_or_404(DICOMSeries, series_instance_uid=series_uid)
    rt_structure = get_object_or_404(RTStructureFileImport, id=rt_structure_id)
    
    # Get all DICOM instances for this series
    instances = DICOMInstance.objects.filter(
        series_instance_uid=series
    ).order_by('sop_instance_uid')
    
    # Prepare instance data
    instance_data = []
    for idx, instance in enumerate(instances):
        instance_data.append({
            'index': idx,
            'sop_instance_uid': instance.sop_instance_uid,
            'instance_path': instance.instance_path,
        })
    
    # Get available modification types
    modification_types = ContourModificationTypeChoices.objects.all().order_by('modification_type')
    
    # Check if this RT Structure has already been rated
    has_existing_rating = rt_structure.date_contour_reviewed is not None
    
    # Get existing VOI ratings if they exist
    existing_voi_ratings = {}
    if has_existing_rating:
        voi_data_list = RTStructureFileVOIData.objects.filter(
            rt_structure_file_import=rt_structure
        ).prefetch_related('contour_modification_type')
        
        for voi_data in voi_data_list:
            # Get modification type IDs
            mod_type_ids = [str(mod_type.id) for mod_type in voi_data.contour_modification_type.all()]
            
            existing_voi_ratings[voi_data.volume_name] = {
                'modification': voi_data.contour_modification,
                'modification_types': mod_type_ids,
                'comments': voi_data.contour_modification_comments or '',
            }
    
    context = {
        'series': series,
        'rt_structure': rt_structure,
        'patient_name': f"Study {series.study.study_instance_uid[:20]}...",
        'patient_id': series.study.study_instance_uid[:10],
        'study_date': series.study.study_date,
        'series_description': series.series_description,
        'instance_count': len(instance_data),
        'series_uid': series_uid,
        'rt_structure_id': str(rt_structure_id),
        'modification_types': modification_types,
        'has_existing_rating': has_existing_rating,
        'existing_assessor': rt_structure.assessor_name,
        'existing_date_reviewed': rt_structure.date_contour_reviewed,
        'existing_modification_time': rt_structure.contour_modification_time_required,
        'existing_overall_rating': rt_structure.overall_rating,
        'existing_voi_ratings_json': json.dumps(existing_voi_ratings),
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
        
        # Get series and RT structure
        series = get_object_or_404(DICOMSeries, series_instance_uid=series_uid)
        rt_structure = get_object_or_404(RTStructureFileImport, id=rt_structure_id)
        
        # Get instances
        instances = DICOMInstance.objects.filter(
            series_instance_uid=series
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
            series_instance_uid=series
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

@csrf_exempt
@require_http_methods(["POST"])
def save_contour_ratings(request):
    """Save contour ratings to the database"""
    try:
        data = json.loads(request.body)
        series_uid = data.get('series_uid')
        overall_rating = data.get('overall_rating')
        assessor_name = data.get('assessor_name')
        modification_time = data.get('modification_time')
        date_reviewed = data.get('date_reviewed')
        structure_ratings = data.get('structure_ratings', {})
        
        # Get the RT structure (this is a simplified approach)
        series = get_object_or_404(DICOMSeries, series_instance_uid=series_uid)
        rt_structure = RTStructureFileImport.objects.filter(
            deidentified_series_instance_uid=series
        ).first()
        
        if not rt_structure:
            return JsonResponse({
                'success': False,
                'error': 'RT Structure not found for this series'
            })
        
        # Update the RT structure with overall rating
        rt_structure.assessor_name = assessor_name
        rt_structure.overall_rating = overall_rating
        rt_structure.modification_time_required = modification_time
        rt_structure.date_contour_reviewed = date_reviewed
        rt_structure.save()
        
        # Save individual structure ratings
        for roi_name, rating_data in structure_ratings.items():
            # Create or update VOI data
            voi_data, created = RTStructureFileVOIData.objects.update_or_create(
                rt_structure_file_import=rt_structure,
                volume_name=roi_name,
                defaults={
                    'contour_modification': rating_data.get('modification', 'NO_MODIFICATION'),
                    'contour_modification_comments': rating_data.get('comments', ''),
                }
            )
            
            if not created:
                voi_data.contour_modification = rating_data.get('modification', 'NO_MODIFICATION')
                voi_data.contour_modification_comments = rating_data.get('comments', '')
                voi_data.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Ratings saved successfully'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@require_http_methods(["GET"])
def get_modification_types(request):
    """Get available modification types"""
    try:
        modification_types = ContourModificationTypeChoices.objects.all().order_by('modification_type')
        
        types_data = []
        for mod_type in modification_types:
            types_data.append({
                'id': str(mod_type.id),
                'name': mod_type.modification_type
            })
        
        return JsonResponse({
            'success': True,
            'modification_types': types_data
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@csrf_exempt
@require_http_methods(["POST"])
def cleanup_temp_files(request):
    """Clean up temporary files"""
    try:
        # This would clean up any temporary files created during viewing
        return JsonResponse({
            'success': True
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

def view_rt_structure_list(request, series_uid):
    """View list of RT structures for a series"""
    try:
        series = get_object_or_404(DICOMSeries, series_instance_uid=series_uid)
        rt_structures = RTStructureFileImport.objects.filter(
            deidentified_series_instance_uid=series
        )
        
        context = {
            'series': series,
            'rt_structures': rt_structures,
        }
        
        return render(request, 'rt_structure_list.html', context)
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })
