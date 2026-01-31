#!/usr/bin/env python
"""
Standalone Python script to import DICOM files from directory structure.

This script can be run directly with:
    python populate_dicom_database.py /path/to/dicom/directory

Or import and use the function:
    from populate_dicom_database import populate_database
    populate_database('/path/to/dicom/directory', clear_existing=True)
"""

import os
import sys
import django
from pathlib import Path

# Setup Django environment
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rtstructcompare.settings')
django.setup()

import pydicom
from datetime import datetime
from django.db import transaction
from rtstructcompare.models import Patient, DICOMStudy, DICOMSeries, DICOMInstance


# ============================================================
# CONFIGURATION: Set your default DICOM directory here
# ============================================================
# DEFAULT_DICOM_LOCATION = '/home/atabur/Documents/DICOMs/patients-dicom-20260131-123331'

DEFAULT_DICOM_LOCATION = "/home/atabur/Downloads/DRAW HEAD & NECK validation metrics filter data set d20.zip/test"

# You can also add multiple locations to choose from:
DICOM_LOCATIONS = {
    'default': DEFAULT_DICOM_LOCATION,
    'draw_client': DEFAULT_DICOM_LOCATION,
    # Add more locations as needed:
    # 'backup': '/path/to/backup/dicom',
    # 'external': '/mnt/external/dicom',
}
# ============================================================


def find_dicom_files(root_directory):
    """
    Recursively find all DICOM files in the directory structure.
    
    Args:
        root_directory (str): Path to root directory
        
    Returns:
        list: List of Path objects for DICOM files
    """
    print(f"Scanning directory: {root_directory}")
    dicom_files = []
    root_path = Path(root_directory)
    
    if not root_path.exists():
        print(f"ERROR: Directory does not exist: {root_directory}")
        return []
    
    for file_path in root_path.rglob('*'):
        if file_path.is_file():
            # Skip hidden files
            if file_path.name.startswith('.'):
                continue
            
            # Try to read as DICOM
            try:
                pydicom.dcmread(str(file_path), stop_before_pixels=True)
                dicom_files.append(file_path)
            except:
                # Not a DICOM file, skip silently
                continue
    
    print(f"Found {len(dicom_files)} DICOM files")
    return dicom_files


def get_dicom_tag(ds, tag_name, default=''):
    """Safely extract DICOM tag value"""
    try:
        value = getattr(ds, tag_name, default)
        if value:
            return str(value).strip()
        return default
    except:
        return default


def parse_dicom_date(date_str):
    """Convert DICOM date (YYYYMMDD) to Python date object"""
    if not date_str or len(date_str) < 8:
        return None
    try:
        return datetime.strptime(date_str[:8], '%Y%m%d').date()
    except:
        return None


def parse_dicom_time(time_str):
    """Convert DICOM time (HHMMSS) to Python time object"""
    if not time_str or len(time_str) < 6:
        return None
    try:
        return datetime.strptime(time_str[:6], '%H%M%S').time()
    except:
        return None


def populate_database(root_directory, clear_existing=False):
    """
    Populate database with DICOM files from directory structure.
    
    Args:
        root_directory (str): Path to root directory containing DICOM files
        clear_existing (bool): If True, clear existing data before import
        
    Returns:
        dict: Statistics about the import
    """
    print("\n" + "="*60)
    print("DICOM Database Population Script")
    print("="*60)
    
    # Clear existing data if requested
    if clear_existing:
        print("\nClearing existing database...")
        from rtstructcompare.models import Roi, RTStruct
        Roi.objects.all().delete()
        RTStruct.objects.all().delete()
        DICOMInstance.objects.all().delete()
        DICOMSeries.objects.all().delete()
        DICOMStudy.objects.all().delete()
        Patient.objects.all().delete()
        print("✓ Database cleared")
    
    # Find DICOM files
    dicom_files = find_dicom_files(root_directory)
    if not dicom_files:
        print("\nNo DICOM files found!")
        return {'patients': 0, 'studies': 0, 'series': 0, 'instances': 0, 'errors': 0}
    
    # Statistics
    stats = {
        'patients': 0,
        'studies': 0,
        'series': 0,
        'instances': 0,
        'rtstructs': 0,
        'rois': 0,
        'errors': 0
    }
    
    # Track created objects
    created_patients = {}
    created_studies = {}
    created_series = {}
    created_instances = {}
    
    print("\nProcessing DICOM files...")
    total = len(dicom_files)
    
    for idx, file_path in enumerate(dicom_files, 1):
        # Progress indicator
        if idx % 10 == 0 or idx == total:
            print(f"  Progress: {idx}/{total} ({idx*100//total}%)")
        
        try:
            with transaction.atomic():
                # Read DICOM file
                ds = pydicom.dcmread(str(file_path))
                
                # === PATIENT ===
                patient_id = get_dicom_tag(ds, 'PatientID', 'UNKNOWN')
                
                if patient_id not in created_patients:
                    patient, created = Patient.objects.get_or_create(
                        patient_id=patient_id,
                        defaults={
                            'patient_name': get_dicom_tag(ds, 'PatientName', ''),
                            'patient_gender': get_dicom_tag(ds, 'PatientSex', ''),
                            'patient_date_of_birth': parse_dicom_date(
                                get_dicom_tag(ds, 'PatientBirthDate', '')
                            ),
                        }
                    )
                    created_patients[patient_id] = patient
                    if created:
                        stats['patients'] += 1
                        print(f"  ✓ Created patient: {patient_id}")
                else:
                    patient = created_patients[patient_id]
                
                # === STUDY ===
                study_uid = get_dicom_tag(ds, 'StudyInstanceUID')
                if not study_uid:
                    print(f"  ✗ Skipping {file_path.name}: No StudyInstanceUID")
                    stats['errors'] += 1
                    continue
                
                if study_uid not in created_studies:
                    study, created = DICOMStudy.objects.get_or_create(
                        study_instance_uid=study_uid,
                        defaults={
                            'patient': patient,
                            'study_date': parse_dicom_date(get_dicom_tag(ds, 'StudyDate', '')),
                            'study_time': parse_dicom_time(get_dicom_tag(ds, 'StudyTime', '')),
                            'study_description': get_dicom_tag(ds, 'StudyDescription', ''),
                            'study_protocol': get_dicom_tag(ds, 'ProtocolName', ''),
                            'study_id': get_dicom_tag(ds, 'StudyID', ''),
                        }
                    )
                    created_studies[study_uid] = study
                    if created:
                        stats['studies'] += 1
                        print(f"  ✓ Created study: {study_uid[:30]}...")
                else:
                    study = created_studies[study_uid]
                
                # === INSTANCE (must be created before Series due to FK) ===
                sop_instance_uid = get_dicom_tag(ds, 'SOPInstanceUID')
                if not sop_instance_uid:
                    print(f"  ✗ Skipping {file_path.name}: No SOPInstanceUID")
                    stats['errors'] += 1
                    continue
                
                # Read file content for storage (COMMENTED OUT - saves disk space)
                # Storing file_content in database can make it very large
                # We rely on instance_path instead
                # with open(file_path, 'rb') as f:
                #     file_content = f.read()
                
                # Get modality
                modality = get_dicom_tag(ds, 'Modality', '')
                
                if sop_instance_uid not in created_instances:
                    instance, created = DICOMInstance.objects.get_or_create(
                        sop_instance_uid=sop_instance_uid,
                        defaults={
                            'instance_path': str(file_path),
                            # 'file_content': file_content,  # COMMENTED OUT - saves disk space
                            'modality': modality,
                        }
                    )
                    created_instances[sop_instance_uid] = instance
                    if created:
                        stats['instances'] += 1
                else:
                    instance = created_instances[sop_instance_uid]
                
                # === SERIES ===
                series_uid = get_dicom_tag(ds, 'SeriesInstanceUID')
                if not series_uid:
                    print(f"  ✗ Skipping {file_path.name}: No SeriesInstanceUID")
                    stats['errors'] += 1
                    continue
                
                if series_uid not in created_series:
                    series, created = DICOMSeries.objects.get_or_create(
                        series_instance_uid=series_uid,
                        defaults={
                            'study': study,
                            'dicom_instance_uid': instance,  # Link to first instance
                            'series_description': get_dicom_tag(ds, 'SeriesDescription', ''),
                            'series_root_path': str(file_path.parent),
                            'frame_of_reference_uid': get_dicom_tag(ds, 'FrameOfReferenceUID', ''),
                            'series_date': parse_dicom_date(get_dicom_tag(ds, 'SeriesDate', '')),
                            'instance_count': 1,
                        }
                    )
                    created_series[series_uid] = series
                    if created:
                        stats['series'] += 1
                        print(f"  ✓ Created series: {series_uid[:30]}...")
                else:
                    # Update instance count for existing series
                    series = created_series[series_uid]
                    series.instance_count += 1
                    series.save()
                
                # === RT STRUCT Processing ===
                if modality == 'RTSTRUCT':
                    try:
                        from rtstructcompare.models import RTStruct, Roi
                        
                        # Create RTStruct entry
                        rtstruct, created = RTStruct.objects.get_or_create(
                            rtstruct_instance_uid=series_uid,
                            defaults={'series': instance}
                        )
                        if created:
                            stats['rtstructs'] += 1
                            print(f"  ✓ Created RT Structure: {series_uid[:30]}...")
                        
                        # Extract ROI information
                        if hasattr(ds, 'StructureSetROISequence'):
                            for roi_item in ds.StructureSetROISequence:
                                roi_number = get_dicom_tag(roi_item, 'ROINumber', '')
                                roi_name = get_dicom_tag(roi_item, 'ROIName', '')
                                roi_description = get_dicom_tag(roi_item, 'ROIDescription', '')
                                
                                # Get ROI color from ROIContourSequence
                                roi_color = ''
                                if hasattr(ds, 'ROIContourSequence'):
                                    for contour in ds.ROIContourSequence:
                                        if get_dicom_tag(contour, 'ReferencedROINumber', '') == roi_number:
                                            if hasattr(contour, 'ROIDisplayColor'):
                                                roi_color = ','.join(map(str, contour.ROIDisplayColor))
                                            break
                                
                                # Create ROI entry
                                roi, roi_created = Roi.objects.get_or_create(
                                    rtstruct=rtstruct,
                                    roi_id=str(roi_number),
                                    defaults={
                                        'roi_name': roi_name,
                                        'roi_description': roi_description,
                                        'roi_color': roi_color,
                                    }
                                )
                                if roi_created:
                                    stats['rois'] += 1
                    except Exception as e:
                        print(f"  ⚠ Warning: Could not process RT Structure data: {str(e)}")
        
        except Exception as e:
            print(f"  ✗ Error processing {file_path.name}: {str(e)}")
            stats['errors'] += 1
            continue
    
    # Print summary
    print("\n" + "="*60)
    print("Import Summary")
    print("="*60)
    print(f"Patients created:   {stats['patients']}")
    print(f"Studies created:    {stats['studies']}")
    print(f"Series created:     {stats['series']}")
    print(f"Instances created:  {stats['instances']}")
    print(f"RT Structs created: {stats['rtstructs']}")
    print(f"ROIs created:       {stats['rois']}")
    print(f"Errors:             {stats['errors']}")
    print("="*60)
    print("✓ Import completed successfully!\n")
    
    return stats


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Import DICOM files from directory into database',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  # Use default configured location
  python populate_dicom_database.py
  
  # Use a named location from DICOM_LOCATIONS
  python populate_dicom_database.py --location draw_client
  
  # Use a custom directory
  python populate_dicom_database.py /custom/path/to/dicom
  
  # Clear database before import
  python populate_dicom_database.py --clear

Default DICOM location: {DEFAULT_DICOM_LOCATION}

Available named locations:
{chr(10).join(f"  - {name}: {path}" for name, path in DICOM_LOCATIONS.items())}
        """
    )
    parser.add_argument(
        'directory',
        nargs='?',  # Make it optional
        default=None,
        help='Root directory containing DICOM files (optional, uses DEFAULT_DICOM_LOCATION if not provided)'
    )
    parser.add_argument(
        '--location', '-l',
        choices=list(DICOM_LOCATIONS.keys()),
        help='Use a named location from DICOM_LOCATIONS configuration'
    )
    parser.add_argument(
        '--clear',
        action='store_true',
        help='Clear existing database before import'
    )
    
    args = parser.parse_args()
    
    # Determine which directory to use
    if args.location:
        # Use named location
        dicom_dir = DICOM_LOCATIONS[args.location]
        print(f"Using named location '{args.location}': {dicom_dir}")
    elif args.directory:
        # Use provided directory
        dicom_dir = args.directory
    else:
        # Use default location
        dicom_dir = DEFAULT_DICOM_LOCATION
        print(f"Using default location: {dicom_dir}")
    
    # Run the import
    populate_database(dicom_dir, clear_existing=args.clear)

