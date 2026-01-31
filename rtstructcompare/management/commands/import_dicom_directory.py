"""
Django management command to import DICOM files from a directory structure into the database.

Usage:
    python manage.py import_dicom_directory /path/to/dicom/root
    
    Options:
        --clear     Clear existing data before import
"""

import os
import pydicom
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from rtstructcompare.models import Patient, DICOMStudy, DICOMSeries, DICOMInstance
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Import DICOM files from a directory structure into the database'

    def add_arguments(self, parser):
        parser.add_argument(
            'directory',
            type=str,
            help='Root directory containing DICOM files'
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing data before import'
        )

    def handle(self, *args, **options):
        directory = options['directory']
        clear_data = options.get('clear', False)

        if not os.path.exists(directory):
            raise CommandError(f'Directory does not exist: {directory}')

        self.stdout.write(self.style.SUCCESS(f'Starting DICOM import from: {directory}'))

        if clear_data:
            self.stdout.write(self.style.WARNING('Clearing existing data...'))
            self.clear_database()

        # Find all DICOM files
        dicom_files = self.find_dicom_files(directory)
        self.stdout.write(f'Found {len(dicom_files)} DICOM files')

        if not dicom_files:
            self.stdout.write(self.style.WARNING('No DICOM files found!'))
            return

        # Process files
        stats = self.process_dicom_files(dicom_files)

        # Print summary
        self.stdout.write(self.style.SUCCESS('\n=== Import Summary ==='))
        self.stdout.write(f'Patients created: {stats["patients"]}')
        self.stdout.write(f'Studies created: {stats["studies"]}')
        self.stdout.write(f'Series created: {stats["series"]}')
        self.stdout.write(f'Instances created: {stats["instances"]}')
        self.stdout.write(f'Files with errors: {stats["errors"]}')
        self.stdout.write(self.style.SUCCESS('\nImport completed successfully!'))

    def clear_database(self):
        """Clear all DICOM-related data from database"""
        DICOMInstance.objects.all().delete()
        DICOMSeries.objects.all().delete()
        DICOMStudy.objects.all().delete()
        Patient.objects.all().delete()
        self.stdout.write(self.style.SUCCESS('Database cleared'))

    def find_dicom_files(self, root_dir):
        """Recursively find all DICOM files in directory"""
        dicom_files = []
        root_path = Path(root_dir)

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
                    # Not a DICOM file, skip
                    continue

        return dicom_files

    def process_dicom_files(self, dicom_files):
        """Process all DICOM files and populate database"""
        stats = {
            'patients': 0,
            'studies': 0,
            'series': 0,
            'instances': 0,
            'errors': 0
        }

        # Track created objects to avoid duplicates
        created_patients = {}
        created_studies = {}
        created_series = {}
        created_instances = {}

        total = len(dicom_files)
        for idx, file_path in enumerate(dicom_files, 1):
            if idx % 10 == 0:
                self.stdout.write(f'Processing {idx}/{total}...')

            try:
                with transaction.atomic():
                    # Read DICOM file
                    ds = pydicom.dcmread(str(file_path))

                    # Extract patient information
                    patient_id = self.get_tag_value(ds, 'PatientID', 'UNKNOWN')
                    patient_name = self.get_tag_value(ds, 'PatientName', '')
                    patient_sex = self.get_tag_value(ds, 'PatientSex', '')
                    patient_birth_date = self.parse_dicom_date(
                        self.get_tag_value(ds, 'PatientBirthDate', '')
                    )

                    # Create or get Patient
                    if patient_id not in created_patients:
                        patient, created = Patient.objects.get_or_create(
                            patient_id=patient_id,
                            defaults={
                                'patient_name': patient_name,
                                'patient_gender': patient_sex,
                                'patient_date_of_birth': patient_birth_date,
                            }
                        )
                        created_patients[patient_id] = patient
                        if created:
                            stats['patients'] += 1
                    else:
                        patient = created_patients[patient_id]

                    # Extract study information
                    study_uid = self.get_tag_value(ds, 'StudyInstanceUID')
                    if not study_uid:
                        self.stdout.write(self.style.WARNING(
                            f'Skipping {file_path}: No StudyInstanceUID'
                        ))
                        stats['errors'] += 1
                        continue

                    study_date = self.parse_dicom_date(
                        self.get_tag_value(ds, 'StudyDate', '')
                    )
                    study_time = self.parse_dicom_time(
                        self.get_tag_value(ds, 'StudyTime', '')
                    )

                    # Create or get Study
                    if study_uid not in created_studies:
                        study, created = DICOMStudy.objects.get_or_create(
                            study_instance_uid=study_uid,
                            defaults={
                                'patient': patient,
                                'study_date': study_date,
                                'study_time': study_time,
                                'study_description': self.get_tag_value(ds, 'StudyDescription', ''),
                                'study_protocol': self.get_tag_value(ds, 'ProtocolName', ''),
                                'study_modality': self.get_tag_value(ds, 'Modality', ''),
                                'study_id': self.get_tag_value(ds, 'StudyID', ''),
                            }
                        )
                        created_studies[study_uid] = study
                        if created:
                            stats['studies'] += 1
                    else:
                        study = created_studies[study_uid]

                    # Extract instance information
                    sop_instance_uid = self.get_tag_value(ds, 'SOPInstanceUID')
                    if not sop_instance_uid:
                        self.stdout.write(self.style.WARNING(
                            f'Skipping {file_path}: No SOPInstanceUID'
                        ))
                        stats['errors'] += 1
                        continue

                    # Read file content
                    with open(file_path, 'rb') as f:
                        file_content = f.read()

                    # Create Instance first (since Series needs it)
                    if sop_instance_uid not in created_instances:
                        instance, created = DICOMInstance.objects.get_or_create(
                            sop_instance_uid=sop_instance_uid,
                            defaults={
                                'instance_path': str(file_path),
                                'file_content': file_content,
                            }
                        )
                        created_instances[sop_instance_uid] = instance
                        if created:
                            stats['instances'] += 1
                    else:
                        instance = created_instances[sop_instance_uid]

                    # Extract series information
                    series_uid = self.get_tag_value(ds, 'SeriesInstanceUID')
                    if not series_uid:
                        self.stdout.write(self.style.WARNING(
                            f'Skipping {file_path}: No SeriesInstanceUID'
                        ))
                        stats['errors'] += 1
                        continue

                    # Create or get Series
                    if series_uid not in created_series:
                        series, created = DICOMSeries.objects.get_or_create(
                            series_instance_uid=series_uid,
                            defaults={
                                'study': study,
                                'dicom_instance_uid': instance,  # Link first instance
                                'series_description': self.get_tag_value(ds, 'SeriesDescription', ''),
                                'series_root_path': str(file_path.parent),
                                'frame_of_reference_uid': self.get_tag_value(ds, 'FrameOfReferenceUID', ''),
                                'series_date': self.parse_dicom_date(
                                    self.get_tag_value(ds, 'SeriesDate', '')
                                ),
                                'instance_count': 1,
                            }
                        )
                        created_series[series_uid] = series
                        if created:
                            stats['series'] += 1
                        else:
                            # Update instance count
                            series.instance_count += 1
                            series.save()

            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f'Error processing {file_path}: {str(e)}'
                ))
                stats['errors'] += 1
                continue

        return stats

    def get_tag_value(self, ds, tag_name, default=''):
        """Safely get a DICOM tag value"""
        try:
            value = getattr(ds, tag_name, default)
            if value:
                return str(value).strip()
            return default
        except:
            return default

    def parse_dicom_date(self, date_str):
        """Parse DICOM date (YYYYMMDD) to Python date"""
        if not date_str or len(date_str) < 8:
            return None
        try:
            return datetime.strptime(date_str[:8], '%Y%m%d').date()
        except:
            return None

    def parse_dicom_time(self, time_str):
        """Parse DICOM time (HHMMSS.FFFFFF) to Python time"""
        if not time_str or len(time_str) < 6:
            return None
        try:
            return datetime.strptime(time_str[:6], '%H%M%S').time()
        except:
            return None
