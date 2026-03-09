import logging
import pydicom
import tempfile
import posixpath
from uuid import uuid4
from datetime import datetime
from pathlib import Path
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.db import transaction
from django.db.models import F
from ..models import (
    Patient,
    DICOMStudy,
    DICOMSeries,
    DICOMInstance,
    RTStruct,
    Roi,
)


logger = logging.getLogger(__name__)


class DicomImportError(Exception):
    """Raised when the import process encounters a fatal error."""


def _get_dicom_upload_prefix():
    return getattr(settings, 'DICOM_S3_PREFIX', 'dicom_uploads')


def _build_s3_storage_context(root_directory: Path):
    bucket = getattr(settings, 'AWS_STORAGE_BUCKET_NAME', None)
    access_key = getattr(settings, 'AWS_ACCESS_KEY_ID', None)
    secret_key = getattr(settings, 'AWS_SECRET_ACCESS_KEY', None)
    region_name = getattr(settings, 'AWS_S3_REGION_NAME', None)
    if not bucket:
        raise DicomImportError('AWS_STORAGE_BUCKET_NAME is not configured for DICOM uploads.')
    if not access_key or not secret_key:
        raise DicomImportError('AWS credentials (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY) are not configured.')

    base_prefix = _get_dicom_upload_prefix()
    return {
        'type': 's3',
        'bucket': bucket,
        'client': boto3.client(
            's3',
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region_name,
        ),
        'base_prefix': base_prefix,
        'base_uri': f's3://{bucket}/{base_prefix}',
        'root_directory': root_directory,
    }


def _store_file_reference(file_path: Path, root_directory: Path, storage_context, *, patient_identifier=None):
    relative_path = file_path.relative_to(root_directory)

    if storage_context and storage_context.get('type') == 's3':
        patient_segment = patient_identifier or uuid4().hex
        key = posixpath.join(
            storage_context['base_prefix'],
            patient_segment,
            relative_path.as_posix(),
        )
        try:
            storage_context['client'].upload_file(str(file_path), storage_context['bucket'], key)
        except (BotoCoreError, ClientError) as exc:
            raise DicomImportError(f'Failed to upload {relative_path} to S3: {exc}') from exc

        file_uri = f"s3://{storage_context['bucket']}/{key}"

        if relative_path.parent and relative_path.parent.as_posix() not in ('', '.'):
            dir_key = posixpath.join(storage_context['base_prefix'], patient_segment, relative_path.parent.as_posix())
        else:
            dir_key = posixpath.join(storage_context['base_prefix'], patient_segment)
        dir_uri = f"s3://{storage_context['bucket']}/{dir_key}"
        return file_uri, dir_uri

    return str(file_path), str(file_path.parent)


def _get_dicom_tag(ds, tag_name, default=''):
    try:
        value = getattr(ds, tag_name, default)
        return str(value).strip() if value else default
    except Exception:
        return default


def _parse_dicom_date(date_str):
    if not date_str or len(date_str) < 8:
        return None
    try:
        return datetime.strptime(date_str[:8], '%Y%m%d').date()
    except Exception:
        return None


def _parse_dicom_time(time_str):
    if not time_str or len(time_str) < 6:
        return None
    try:
        return datetime.strptime(time_str[:6], '%H%M%S').time()
    except Exception:
        return None


def _find_dicom_files(root_directory: Path):
    root_path = Path(root_directory)
    if not root_path.exists():
        raise DicomImportError(f"Directory does not exist: {root_directory}")

    dicom_files = []
    for file_path in root_path.rglob('*'):
        if not file_path.is_file():
            continue
        if file_path.name.startswith('.'):
            continue
        try:
            pydicom.dcmread(str(file_path), stop_before_pixels=True)
            dicom_files.append(file_path)
        except Exception:
            continue
    return dicom_files


def import_dicom_directory(root_directory, *, progress_callback=None, storage_context=None):
    root_directory = Path(root_directory)

    dicom_files = _find_dicom_files(root_directory)
    if not dicom_files:
        raise DicomImportError('No DICOM files found in the uploaded archive.')

    stats = {
        'patients': 0,
        'studies': 0,
        'series': 0,
        'instances': 0,
        'rtstructs': 0,
        'rois': 0,
        'errors': 0,
    }

    created_patients = {}
    created_studies = {}
    created_series = {}
    created_instances = {}

    total = len(dicom_files)

    for idx, file_path in enumerate(dicom_files, 1):
        if progress_callback:
            progress_callback(idx, total, file_path.name)

        try:
            with transaction.atomic():
                ds = pydicom.dcmread(str(file_path))
                patient_id = _get_dicom_tag(ds, 'PatientID', 'UNKNOWN')
                patient_segment = patient_id or None
                file_uri, dir_uri = _store_file_reference(
                    file_path,
                    root_directory,
                    storage_context,
                    patient_identifier=patient_segment,
                )

                if patient_id not in created_patients:
                    patient, created = Patient.objects.get_or_create(
                        patient_id=patient_id,
                        defaults={
                            'patient_name': _get_dicom_tag(ds, 'PatientName', ''),
                            'patient_gender': _get_dicom_tag(ds, 'PatientSex', ''),
                            'patient_date_of_birth': _parse_dicom_date(
                                _get_dicom_tag(ds, 'PatientBirthDate', '')
                            ),
                        },
                    )
                    created_patients[patient_id] = patient
                    if created:
                        stats['patients'] += 1
                else:
                    patient = created_patients[patient_id]

                study_uid = _get_dicom_tag(ds, 'StudyInstanceUID')
                if not study_uid:
                    stats['errors'] += 1
                    continue

                if study_uid not in created_studies:
                    study, created = DICOMStudy.objects.get_or_create(
                        study_instance_uid=study_uid,
                        defaults={
                            'patient': patient,
                            'study_date': _parse_dicom_date(_get_dicom_tag(ds, 'StudyDate', '')),
                            'study_time': _parse_dicom_time(_get_dicom_tag(ds, 'StudyTime', '')),
                            'study_description': _get_dicom_tag(ds, 'StudyDescription', ''),
                            'study_protocol': _get_dicom_tag(ds, 'ProtocolName', ''),
                            'study_id': _get_dicom_tag(ds, 'StudyID', ''),
                        },
                    )
                    created_studies[study_uid] = study
                    if created:
                        stats['studies'] += 1
                else:
                    study = created_studies[study_uid]

                series_uid = _get_dicom_tag(ds, 'SeriesInstanceUID')
                if not series_uid:
                    stats['errors'] += 1
                    continue

                modality = _get_dicom_tag(ds, 'Modality', '')
                if series_uid not in created_series:
                    series, created = DICOMSeries.objects.get_or_create(
                        series_instance_uid=series_uid,
                        defaults={
                            'study': study,
                            'series_description': _get_dicom_tag(ds, 'SeriesDescription', ''),
                            'series_root_path': dir_uri,
                            'frame_of_reference_uid': _get_dicom_tag(ds, 'FrameOfReferenceUID', ''),
                            'modality': modality,
                            'series_date': _parse_dicom_date(_get_dicom_tag(ds, 'SeriesDate', '')),
                            'instance_count': 1,
                        },
                    )
                    created_series[series_uid] = series
                    if created:
                        stats['series'] += 1
                else:
                    series = created_series[series_uid]
                    DICOMSeries.objects.filter(pk=series.pk).update(instance_count=F('instance_count') + 1)
                    if modality and not series.modality:
                        DICOMSeries.objects.filter(pk=series.pk).update(modality=modality)
                        series.modality = modality

                sop_instance_uid = _get_dicom_tag(ds, 'SOPInstanceUID')
                if not sop_instance_uid:
                    stats['errors'] += 1
                    continue

                if sop_instance_uid not in created_instances:
                    instance, created = DICOMInstance.objects.get_or_create(
                        sop_instance_uid=sop_instance_uid,
                        defaults={
                            'series': series,
                            'instance_path': file_uri,
                            'instance_number': _get_dicom_tag(ds, 'InstanceNumber', None),
                        },
                    )
                    created_instances[sop_instance_uid] = instance
                    if created:
                        stats['instances'] += 1
                else:
                    instance = created_instances[sop_instance_uid]

                modality = _get_dicom_tag(ds, 'Modality', '')
                if modality == 'RTSTRUCT':
                    rtstruct, created = RTStruct.objects.get_or_create(
                        instance=instance,
                        defaults={'referenced_series_uid': series_uid},
                    )
                    if created:
                        stats['rtstructs'] += 1

                    if hasattr(ds, 'StructureSetROISequence'):
                        for roi_item in ds.StructureSetROISequence:
                            roi_number = _get_dicom_tag(roi_item, 'ROINumber', '')
                            roi_label = _get_dicom_tag(roi_item, 'ROIName', '')
                            roi_description = _get_dicom_tag(roi_item, 'ROIDescription', '')

                            roi_color = ''
                            if hasattr(ds, 'ROIContourSequence'):
                                for contour in ds.ROIContourSequence:
                                    if _get_dicom_tag(contour, 'ReferencedROINumber', '') == roi_number:
                                        if hasattr(contour, 'ROIDisplayColor'):
                                            roi_color = ','.join(map(str, contour.ROIDisplayColor))
                                        break

                            roi, roi_created = Roi.objects.get_or_create(
                                rtstruct=rtstruct,
                                roi_label=roi_label,
                                defaults={
                                    'roi_number': roi_number,
                                    'roi_id': str(roi_number),
                                    'roi_description': roi_description,
                                    'roi_color': roi_color,
                                },
                            )
                            if roi_created:
                                stats['rois'] += 1

        except Exception as exc:
            stats['errors'] += 1
            logger.exception("Failed to ingest %s", file_path)
            continue

    return stats


def _safe_relative_path(filename: str, fallback_index: int) -> Path:
    """Return a safe, relative path derived from an uploaded filename."""
    if not filename:
        return Path(f"uploaded_{fallback_index}.dcm")

    normalized = str(filename).replace("\\", "/")
    parts = [part for part in normalized.split("/") if part not in ("", ".", "..")]
    if not parts:
        return Path(f"uploaded_{fallback_index}.dcm")
    return Path(*parts)


def import_dicom_file_objects(uploaded_files, *, progress_callback=None):
    """Persist uploaded file objects, upload to S3 if configured, and import."""
    if not uploaded_files:
        raise DicomImportError('No files uploaded for import.')

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        storage_context = None

        for index, uploaded_file in enumerate(uploaded_files, start=1):
            relative_path = _safe_relative_path(getattr(uploaded_file, 'name', ''), index)
            destination = temp_root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)

            with destination.open('wb') as dest_fp:
                if hasattr(uploaded_file, 'chunks'):
                    for chunk in uploaded_file.chunks():
                        dest_fp.write(chunk)
                else:
                    dest_fp.write(uploaded_file.read())

            if hasattr(uploaded_file, 'seek'):
                uploaded_file.seek(0)

        if getattr(settings, 'AWS_STORAGE_BUCKET_NAME', None):
            storage_context = _build_s3_storage_context(temp_root)

        stats = import_dicom_directory(
            temp_root,
            progress_callback=progress_callback,
            storage_context=storage_context,
        )
        stats['total_files'] = len(uploaded_files)
        if storage_context:
            stats['storage_location'] = storage_context.get('base_uri')
        return stats
