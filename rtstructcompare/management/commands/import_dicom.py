from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from rtstructcompare.dicom_scanner import DICOMScanner
import os

class Command(BaseCommand):
    help = 'Import DICOM files from a directory into the database'
    
    def add_arguments(self, parser):
        parser.add_argument(
            'directory_path',
            type=str,
            help='Path to the directory containing DICOM files'
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing DICOM data before importing',
        )
        parser.add_argument(
            '--recursive',
            action='store_true',
            default=True,
            help='Search recursively in subdirectories (default: True)',
        )
    
    def handle(self, *args, **options):
        directory_path = options['directory_path']
        clear_existing = options['clear']
        
        # Validate directory path
        if not os.path.exists(directory_path):
            raise CommandError(f'Directory does not exist: {directory_path}')
        
        if not os.path.isdir(directory_path):
            raise CommandError(f'Path is not a directory: {directory_path}')
        
        self.stdout.write(f'Starting DICOM import from: {directory_path}')
        
        # Clear existing data if requested
        if clear_existing:
            from rtstructcompare.models import DICOMInstance, DICOMSeries, DICOMStudy, RTStructureFileImport
            self.stdout.write('Clearing existing DICOM data...')
            DICOMInstance.objects.all().delete()
            DICOMSeries.objects.all().delete()
            DICOMStudy.objects.all().delete()
            RTStructureFileImport.objects.all().delete()
            self.stdout.write(self.style.SUCCESS('Cleared existing data'))
        
        # Initialize scanner
        scanner = DICOMScanner(directory_path)
        
        # Perform the scan
        try:
            success = scanner.scan_directory()
            
            if success:
                self.stdout.write(self.style.SUCCESS(
                    f'Successfully imported DICOM files from {directory_path}'
                ))
                self.stdout.write(f'Processed {len(scanner.processed_studies)} studies')
                self.stdout.write(f'Processed {len(scanner.processed_series)} series')
                self.stdout.write(f'Processed {len(scanner.processed_instances)} instances')
            else:
                self.stdout.write(self.style.ERROR('Failed to import DICOM files'))
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error during import: {str(e)}'))
            raise CommandError(f'Import failed: {str(e)}')
