import os
import pydicom
import logging
import zipfile
import tempfile
from pathlib import Path
from django.core.management.base import BaseCommand
from django.db import transaction
from .models import DICOMStudy, DICOMSeries, DICOMInstance, Patient

logger = logging.getLogger(__name__)

class DICOMScanner:
    """
    Scanner for importing DICOM files from system folders into the database
    """
    
    def __init__(self, root_path=None):
        self.root_path = Path(root_path) if root_path else None
        # Start with fresh data structures
        self.processed_studies = {}
        self.processed_series = {}
        self.processed_instances = []
        print(f"Initialized DICOMScanner with fresh data structures")
        
    def scan_directory(self):
        """
        Scan the root directory for DICOM files and import them
        """
        if not self.root_path.exists():
            logger.error(f"Root path does not exist: {self.root_path}")
            return False
            
        logger.info(f"Starting DICOM scan in: {self.root_path}")
        
        # Find all DICOM files recursively
        dicom_files = self._find_dicom_files(self.root_path)
        logger.info(f"Found {len(dicom_files)} DICOM files")
        
        if not dicom_files:
            logger.warning("No DICOM files found in the specified directory")
            return False
            
        # Process each DICOM file
        with transaction.atomic():
            for dicom_file in dicom_files:
                try:
                    self._process_dicom_file(dicom_file)
                except Exception as e:
                    logger.error(f"Error processing {dicom_file}: {str(e)}")
                    continue
        # Save all processed data
        self._save_to_database()
        
        return self._get_import_stats()
    
    def clear_existing_data(self):
        """
        Clear all existing DICOM data from database
        """
        print("Clearing existing DICOM data...")
        DICOMInstance.objects.all().delete()
        # RTStructureFileImport.objects.all().delete()  # Model not available
        DICOMSeries.objects.all().delete()
        DICOMStudy.objects.all().delete()
        Patient.objects.all().delete()
        print("Cleared all existing DICOM data")
    
    def process_files(self, uploaded_files):
        """
        Process uploaded DICOM files directly
        """
        logger.info(f"Processing {len(uploaded_files)} uploaded files")
        
        if not uploaded_files:
            logger.warning("No files provided")
            return {"total_files": 0, "studies": 0, "series": 0, "instances": 0}
        
        # Process each uploaded file
        with transaction.atomic():
            for uploaded_file in uploaded_files:
                try:
                    self._process_uploaded_file(uploaded_file)
                except Exception as e:
                    logger.error(f"Error processing uploaded file {uploaded_file.name}: {str(e)}")
                    continue
                    
        # Save all processed data
        self._save_to_database()
        
        return self._get_import_stats()
    
    def _process_uploaded_file(self, uploaded_file):
        """
        Process a single uploaded DICOM file (or ZIP containing DICOM files)
        """
        print("Started processing uploaded file: ", uploaded_file.name, "\n =========================")
        try:
            # Check if it's a ZIP file
            if uploaded_file.name.lower().endswith('.zip'):
                print("Detected ZIP file, extracting...")
                return self._process_zip_file(uploaded_file)
            
            # Read DICOM data from uploaded file
            ds = pydicom.dcmread(uploaded_file, stop_before_pixels=True)
            
            # Extract metadata
            study_instance_uid = getattr(ds, "StudyInstanceUID", None)
            series_instance_uid = getattr(ds, "SeriesInstanceUID", None)
            sop_instance_uid = getattr(ds, "SOPInstanceUID", None)
            
            if not study_instance_uid:
                logger.warning(f"Missing StudyInstanceUID in file {uploaded_file.name}")
                return
            if not series_instance_uid:
                logger.warning(f"Missing SeriesInstanceUID in file {uploaded_file.name}")
                return
            if not sop_instance_uid:
                logger.warning(f"Missing SOPInstanceUID in file {uploaded_file.name}")
                return
            
            # Process study
            if study_instance_uid not in self.processed_studies:
                self.processed_studies[study_instance_uid] = {
                    'study_instance_uid': study_instance_uid,
                    'study_date': getattr(ds, "StudyDate", ""),
                    'study_time': getattr(ds, "StudyTime", ""),
                    'study_description': getattr(ds, "StudyDescription", ""),
                    'study_protocol': getattr(ds, "StudyDescription", ""),
                    'study_modality': getattr(ds, "Modality", ""),
                    'accession_number': getattr(ds, "AccessionNumber", ""),
                    'study_id': getattr(ds, "StudyID", ""),
                }
            
            # Process series
            if series_instance_uid not in self.processed_series:
                self.processed_series[series_instance_uid] = {
                    'series_instance_uid': series_instance_uid,
                    'study_instance_uid': study_instance_uid,
                    'series_description': getattr(ds, "SeriesDescription", ""),
                    'frame_of_reference_uid': getattr(ds, "FrameOfReferenceUID", ""),
                    'instance_count': 0,
                }
            
            # Process instance - store file content directly in database
            # Read the file content
            if hasattr(uploaded_file, 'read'):
                # It's an uploaded file, read from memory
                file_content = uploaded_file.read()
                uploaded_file.seek(0)  # Reset file pointer
            else:
                # It's a file path, read from disk
                with open(uploaded_file, 'rb') as f:
                    file_content = f.read()
            
            self.processed_instances.append({
                'sop_instance_uid': sop_instance_uid,
                'series_instance_uid': series_instance_uid,
                'instance_path': uploaded_file.name if hasattr(uploaded_file, 'name') else str(uploaded_file),
                'file_content': file_content,
            })
            
            # Update series instance count
            self.processed_series[series_instance_uid]['instance_count'] += 1
            
            # RT structure processing disabled - model not available
            # if getattr(ds, "Modality", "") == "RTSTRUCT":
            #     self._process_rt_structure_upload(ds, uploaded_file, series_instance_uid)
                
        except Exception as e:
            logger.error(f"Error processing uploaded DICOM file {uploaded_file.name}: {str(e)}")
            raise
    
    def _process_zip_file(self, uploaded_file):
        """
        Process a ZIP file containing DICOM files
        """
        try:
            # Create temporary directory
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                
                # Extract ZIP file
                with zipfile.ZipFile(uploaded_file, 'r') as zip_ref:
                    zip_ref.extractall(temp_path)
                
                print(f"Extracted ZIP to: {temp_path}")
                
                # Find all DICOM files in extracted content
                dicom_files = self._find_dicom_files(temp_path)
                print(f"Found {len(dicom_files)} DICOM files in ZIP")
                
                # Process each DICOM file
                for dicom_file in dicom_files:
                    try:
                        # Read the file content directly
                        with open(dicom_file, 'rb') as f:
                            file_content = f.read()
                        
                        # Create a file-like object from the content
                        from io import BytesIO
                        file_obj = BytesIO(file_content)
                        file_obj.name = dicom_file.name
                        
                        # Process the file-like object
                        self._process_uploaded_file(file_obj)
                        
                    except Exception as e:
                        logger.error(f"Error processing DICOM file {dicom_file}: {str(e)}")
                        continue
                        
        except Exception as e:
            logger.error(f"Error processing ZIP file {uploaded_file.name}: {str(e)}")
            raise
    
    def _process_rt_structure_upload(self, ds, uploaded_file, series_instance_uid):
        """
        Process RT Structure file from upload
        """
        try:
            # Create RT structure record
            # Get SOP Instance UID for the RT structure
            sop_instance_uid = getattr(ds, "SOPInstanceUID", None)
            
            if not sop_instance_uid:
                logger.warning(f"RT Structure file {uploaded_file.name} missing SOPInstanceUID")
                return
            
            rt_structure = {
                'sop_instance_uid': sop_instance_uid,
                'deidentified_series_instance_uid': series_instance_uid,
                'deidentified_rt_structure_file_path': uploaded_file.name,
            }
            
            # Store for later database insertion
            if 'rt_structures' not in self.processed_series[series_instance_uid]:
                self.processed_series[series_instance_uid]['rt_structures'] = []
            self.processed_series[series_instance_uid]['rt_structures'].append(rt_structure)
            
        except Exception as e:
            logger.error(f"Error processing RT structure from {uploaded_file.name}: {str(e)}")
    
    def _get_import_stats(self):
        """
        Get statistics about the import
        """
        return {
            'total_files': len(self.processed_instances),
            'studies': len(self.processed_studies),
            'series': len(self.processed_series),
            'instances': len(self.processed_instances),
        }
        
    def _find_dicom_files(self, directory):
        """
        Find all DICOM files in the directory recursively
        """
        dicom_files = []
        
        # Common DICOM file extensions
        dicom_extensions = ['.dcm', '.dicom', '.dicm', '', '.IMA', '.img']
        
        for file_path in directory.rglob('*'):
            if file_path.is_file():
                # Check if it's a DICOM file by trying to read it
                try:
                    # Skip hidden files and common non-DICOM files
                    if file_path.name.startswith('.'):
                        continue
                        
                    # Check extension
                    if file_path.suffix.lower() not in dicom_extensions:
                        # Try to read anyway (some DICOM files have no extension)
                        try:
                            pydicom.dcmread(str(file_path), stop_before_pixels=True)
                        except:
                            continue
                            
                    dicom_files.append(file_path)
                except Exception:
                    continue
                    
        return dicom_files
        
    def _process_dicom_file(self, file_path):
        """
        Process a single DICOM file and extract metadata
        """
        print("_process_dicom_file ------------: ", file_path)
        try:
            # Read DICOM file
            ds = pydicom.dcmread(str(file_path), stop_before_pixels=True)
            
            # Extract study information
            study_instance_uid = self._get_dicom_value(ds, 'StudyInstanceUID')
            if not study_instance_uid:
                logger.warning(f"No StudyInstanceUID found in {file_path}")
                return
                
            if study_instance_uid not in self.processed_studies:
                self.processed_studies[study_instance_uid] = {
                    'study_instance_uid': study_instance_uid,
                    'study_date': self._parse_dicom_date(ds.get('StudyDate')),
                    'study_time': self._parse_dicom_time(ds.get('StudyTime')),
                    'study_description': self._get_dicom_value(ds, 'StudyDescription'),
                    'study_protocol': self._get_dicom_value(ds, 'ProtocolName'),
                    'study_modality': self._get_dicom_value(ds, 'Modality'),
                    'accession_number': self._get_dicom_value(ds, 'AccessionNumber'),
                    'study_id': self._get_dicom_value(ds, 'StudyID'),
                }
            
            # Extract series information
            series_instance_uid = self._get_dicom_value(ds, 'SeriesInstanceUID')
            if not series_instance_uid:
                logger.warning(f"No SeriesInstanceUID found in {file_path}")
                return
                
            if series_instance_uid not in self.processed_series:
                self.processed_series[series_instance_uid] = {
                    'series_instance_uid': series_instance_uid,
                    'study_instance_uid': study_instance_uid,
                    'series_description': self._get_dicom_value(ds, 'SeriesDescription'),
                    'series_date': self._parse_dicom_date(ds.get('SeriesDate')),
                    'series_root_path': str(file_path.parent),
                    'frame_of_reference_uid': self._get_dicom_value(ds, 'FrameOfReferenceUID'),
                    'instance_count': 0,
                }
            
            # Extract instance information
            sop_instance_uid = self._get_dicom_value(ds, 'SOPInstanceUID')
            if not sop_instance_uid:
                logger.warning(f"No SOPInstanceUID found in {file_path}")
                return
                
            instance_data = {
                'series_instance_uid': series_instance_uid,
                'sop_instance_uid': sop_instance_uid,
                'instance_path': str(file_path),
            }
            
            self.processed_instances.append(instance_data)
            
            # Update instance count for the series
            self.processed_series[series_instance_uid]['instance_count'] += 1
            
            # RT structure processing disabled - model not available
            # if self._get_dicom_value(ds, 'Modality') == 'RTSTRUCT':
            #     self._process_rt_structure(ds, file_path,series_instance_uid)
                
        except Exception as e:
            logger.error(f"Error processing DICOM file {file_path}: {str(e)}")
            raise
            
    def _process_rt_structure(self, ds, file_path, series_instance_uid):
        """
        Process RT Structure file specifically
        """
        try:
            # This will be processed later when we have the series created
            # For now, just mark that this series has RT structures
            if 'rt_structures' not in self.processed_series[series_instance_uid]:
                self.processed_series[series_instance_uid]['rt_structures'] = []
                
            rt_data = {
                'file_path': str(file_path),
                'sop_instance_uid': self._get_dicom_value(ds, 'SOPInstanceUID'),
                'series_description': self._get_dicom_value(ds, 'SeriesDescription'),
            }
            
            self.processed_series[series_instance_uid]['rt_structures'].append(rt_data)
            
        except Exception as e:
            logger.error(f"Error processing RT structure {file_path}: {str(e)}")
            
    def _save_to_database(self):
        """
        Save all processed data to the database
        """
        print(f"Saving to database: {len(self.processed_studies)} studies, {len(self.processed_series)} series")
        
        # Create studies
        created_studies = {}
        for study_uid, study_data in self.processed_studies.items():
            # Check if study already exists
            existing_study = DICOMStudy.objects.filter(study_instance_uid=study_uid).first()
            if existing_study:
                print(f"Study {study_uid} already exists, updating...")
                study = existing_study
                # Update fields
                for field, value in study_data.items():
                    if hasattr(study, field) and value is not None:
                        setattr(study, field, value)
                study.save()
                created = False
            else:
                print(f"Creating new study {study_uid}")
                study = DICOMStudy.objects.create(**study_data)
                created = True
                
            created_studies[study_uid] = study
            logger.info(f"{'Created' if created else 'Updated'} study: {study_uid}")
        
        # Create series
        created_series = {}
        for series_uid, series_data in self.processed_series.items():
            study = created_studies[series_data['study_instance_uid']]
            
            # Remove rt_structures and study_instance_uid from series_data as they're not model fields
            rt_structures = series_data.pop('rt_structures', [])
            series_data.pop('study_instance_uid', None)
            
            # Only use essential fields that definitely exist in the model
            essential_data = {
                'series_instance_uid': series_uid,
            }
            
            # Only add description if it exists
            if 'series_description' in series_data and series_data['series_description']:
                essential_data['series_description'] = series_data['series_description']
            
            print(f"Creating series {series_uid} with data: {essential_data}")
            
            try:
                series, created = DICOMSeries.objects.get_or_create(
                    series_instance_uid=series_uid,
                    defaults={
                        'study': study,
                        **essential_data
                    }
                )
            except Exception as e:
                logger.error(f"Error with series {series_uid}: {e}")
                continue
                
            created_series[series_uid] = series
            logger.info(f"{'Created' if created else 'Updated'} series: {series_uid}")
            
            # RT Structure processing disabled - model not available
            # for rt_data in rt_structures:
            #     RTStructureFileImport.objects.update_or_create(
            #         deidentified_sop_instance_uid=rt_data['sop_instance_uid'],
            #         defaults={
            #             'deidentified_series_instance_uid': series,
            #             'deidentified_rt_structure_file_path': rt_data['deidentified_rt_structure_file_path'],
            #         }
            #     )
            #     logger.info(f"Created RT Structure: {rt_data['sop_instance_uid']}")
        
        # Create instances
        for instance_data in self.processed_instances:
            series_uid = instance_data['series_instance_uid']
            
            # Check if series exists in created_series
            if series_uid not in created_series:
                logger.error(f"Series {series_uid} not found in created_series. Available series: {list(created_series.keys())}")
                continue
                
            series = created_series[series_uid]
            
            # Get sop_instance_uid before modifying the dict
            sop_instance_uid = instance_data.get('sop_instance_uid')
            
            if not sop_instance_uid:
                logger.warning(f"Skipping instance with missing sop_instance_uid: {instance_data}")
                continue
            
            print(f"Creating instance: SOP={sop_instance_uid}, Series={series_uid}")
            
            # Remove series_instance_uid from instance_data as it's not a model field (we use the series object for the FK)
            instance_data_copy = instance_data.copy()
            instance_data_copy.pop('series_instance_uid', None)
            
            try:
                # Get the first instance to link the series to
                first_instance = DICOMInstance.objects.filter(sop_instance_uid=sop_instance_uid).first()
                
                if not first_instance:
                    # Create instance first
                    first_instance = DICOMInstance.objects.create(
                        sop_instance_uid=sop_instance_uid,
                        **instance_data_copy
                    )
                
                # Update or create with the instance link
                DICOMInstance.objects.update_or_create(
                    sop_instance_uid=sop_instance_uid,
                    defaults=instance_data_copy
                )
            except Exception as e:
                logger.error(f"Error creating instance {sop_instance_uid}: {e}")
                continue
            
        logger.info(f"Created {len(self.processed_instances)} DICOM instances")
        
    def _get_dicom_value(self, ds, tag):
        """
        Safely get a value from DICOM dataset
        """
        try:
            value = ds.get(tag)
            if value is not None:
                return str(value).strip()
        except Exception:
            pass
        return None
        
    def _parse_dicom_date(self, date_str):
        """
        Parse DICOM date string (YYYYMMDD) to date object
        """
        if not date_str or len(date_str) < 8:
            return None
            
        try:
            from datetime import datetime
            return datetime.strptime(date_str[:8], '%Y%m%d').date()
        except Exception:
            return None
            
    def _parse_dicom_time(self, time_str):
        """
        Parse DICOM time string (HHMMSS) to time object
        """
        if not time_str or len(time_str) < 6:
            return None
            
        try:
            from datetime import datetime
            return datetime.strptime(time_str[:6], '%H%M%S').time()
        except Exception:
            return None


def scan_dicom_directory(directory_path):
    """
    Convenience function to scan a DICOM directory
    """
    scanner = DICOMScanner(directory_path)
    return scanner.scan_directory()
