import json
from io import BytesIO
from pathlib import Path

import boto3
import pydicom
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

from ..models import (
    DICOMStudy,
    DICOMSeries,
    DICOMInstance,
    RTStruct,
    Roi,
    Feedback,
)

_s3_client = None
_DEFAULT_SORT_VALUE = 0.0


class DicomViewerError(Exception):
    """Raised when the viewer cannot prepare the requested patient."""


def build_viewer_context(patient, *, user=None):
    """Build the data payload required by the DICOM web viewer template."""
    studies = DICOMStudy.objects.filter(patient=patient)
    if not studies.exists():
        raise DicomViewerError(f'No studies found for patient {patient.patient_id}')

    latest_study = studies.first()
    ct_instances, rtstruct_file_paths = _load_dicom_files_from_database(patient)

    if not ct_instances:
        raise DicomViewerError(f'No CT files found for patient {patient.patient_id}')

    if len(rtstruct_file_paths) < 2:
        raise DicomViewerError(
            f'Need at least 2 RTSTRUCT files for comparison, found {len(rtstruct_file_paths)}. '
            f'Found {len(ct_instances)} CT files.'
        )

    rtstruct_files = _load_rtstruct_datasets(rtstruct_file_paths)

    rt1_data, rt2_data = [], []
    rt1_contours, rt2_contours = {}, {}
    common_structures = []
    rt1_label = rt2_label = 'RTSTRUCT'
    rt1_dicom_label = rt2_dicom_label = 'RTSTRUCT'
    rt1_sop_uid = rt2_sop_uid = ''

    if len(rtstruct_files) >= 2:
        rt1_dicom_label = _build_rtstruct_label_dicom(rtstruct_files[0], 1)
        rt2_dicom_label = _build_rtstruct_label_dicom(rtstruct_files[1], 2)
        rt1_label = _get_rtstruct_label(rtstruct_files[0], 1)
        rt2_label = _get_rtstruct_label(rtstruct_files[1], 2)
        rt1_sop_uid = getattr(rtstruct_files[0], 'SOPInstanceUID', '') or ''
        rt2_sop_uid = getattr(rtstruct_files[1], 'SOPInstanceUID', '') or ''

        rt1_data = _analyze_rtstruct(rtstruct_files[0])
        rt2_data = _analyze_rtstruct(rtstruct_files[1])

        rt1_contours = _extract_roi_contours(rtstruct_files[0])
        rt2_contours = _extract_roi_contours(rtstruct_files[1])

        names1 = {s['name'] for s in rt1_data}
        names2 = {s['name'] for s in rt2_data}
        common_structures = sorted(list(names1 & names2))

    ct_data = _prepare_ct_data(ct_instances)

    roi_data = {}
    if common_structures:
        roi_objects = {}
        if rtstruct_files:
            first_sop_uid = getattr(rtstruct_files[0], 'SOPInstanceUID', '')
            rtstruct_instance = RTStruct.objects.filter(instance__sop_instance_uid=first_sop_uid).first()
            if rtstruct_instance:
                roi_objects = {r.roi_label: str(r.id) for r in Roi.objects.filter(rtstruct=rtstruct_instance)}

        for structure in common_structures:
            roi_data[structure] = roi_objects.get(structure, '')

    roi_feedback = {}
    if user and common_structures:
        roi_ids = [r_id for r_id in roi_data.values() if r_id]
        if roi_ids:
            feedback_filter = {
                'patient': patient,
                'user': user,
                'roi_rt1__in': roi_ids,
            }
            if latest_study and latest_study.study_instance_uid:
                feedback_filter['study_uid'] = latest_study.study_instance_uid

            feedback_objects = Feedback.objects.filter(**feedback_filter).select_related('roi_rt1', 'roi_rt2')
            for feedback in feedback_objects:
                if feedback.roi_rt1 and feedback.roi_rt1.roi_label:
                    roi_feedback[feedback.roi_rt1.roi_label] = {
                        'rt1_rating': feedback.rt1_rating,
                        'rt2_rating': feedback.rt2_rating,
                        'comment': feedback.comment or '',
                    }

    return {
        'patient_id': patient.patient_id,
        'patient_name': patient.patient_name,
        'study_date': str(latest_study.study_date) if latest_study.study_date else 'Unknown',
        'study_description': latest_study.study_description,
        'study_uid': latest_study.study_instance_uid,
        'ct_count': len(ct_data),
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
    }


def _load_dicom_files_from_database(patient):
    ct_instances = []
    rtstruct_file_refs = []

    instances = (
        DICOMInstance.objects
        .select_related('series', 'series__study')
        .filter(series__study__patient=patient)
    )

    for instance in instances:
        modality = (instance.series.modality or '').upper()
        path = instance.instance_path
        if not path:
            continue
        if modality == 'CT':
            ct_instances.append({
                'path': path,
                'instance_number': instance.instance_number,
                'sop_instance_uid': instance.sop_instance_uid,
            })
        elif modality == 'RTSTRUCT':
            rtstruct_file_refs.append(path)

    return ct_instances, rtstruct_file_refs


def _load_rtstruct_datasets(file_paths):
    datasets = []
    for file_path in file_paths:
        try:
            dataset = _read_dicom_dataset(file_path, stop_before_pixels=True)
            if dataset:
                datasets.append(dataset)
        except Exception:
            continue
    return datasets


def _read_dicom_dataset(file_reference, *, stop_before_pixels=True):
    if not file_reference:
        return None

    if str(file_reference).startswith('s3://'):
        bucket, key = _parse_s3_uri(file_reference)
        client = _get_s3_client()
        try:
            obj = client.get_object(Bucket=bucket, Key=key)
            body = obj['Body'].read()
            ds = pydicom.dcmread(BytesIO(body), stop_before_pixels=stop_before_pixels)
            # Store the original reference so we can generate a URL later
            ds.file_reference = file_reference 
            return ds
        except Exception:
            return None
    else:
        path = Path(file_reference)
        if path.exists():
            return pydicom.dcmread(path, stop_before_pixels=stop_before_pixels)
    return None


def _parse_s3_uri(uri: str):
    without_scheme = uri[5:]
    if '/' not in without_scheme:
        raise ValueError(f'Invalid S3 URI: {uri}')
    bucket, key = without_scheme.split('/', 1)
    return bucket, key


def _get_s3_client():
    global _s3_client
    if _s3_client is None:
        client_kwargs = {}
        access_key = getattr(settings, 'AWS_ACCESS_KEY_ID', None)
        secret_key = getattr(settings, 'AWS_SECRET_ACCESS_KEY', None)
        region_name = getattr(settings, 'AWS_S3_REGION_NAME', None)
        signature_version = getattr(settings, 'AWS_S3_SIGNATURE_VERSION', None)

        if access_key and secret_key:
            client_kwargs['aws_access_key_id'] = access_key
            client_kwargs['aws_secret_access_key'] = secret_key
        if region_name:
            client_kwargs['region_name'] = region_name
        if signature_version:
            client_kwargs.setdefault('config', boto3.session.Config(signature_version=signature_version))

        _s3_client = boto3.client('s3', **client_kwargs)
    return _s3_client


def _analyze_rtstruct(rtstruct_file):
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
            'algorithm': roi_generation_algorithm,
        })
    return structures


def _extract_roi_contours(rtstruct_file):
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
        roi_label = roi_number_to_name.get(roi_number, f'ROI_{roi_number}')

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
                                float(contour_data[i + 1]),
                                float(contour_data[i + 2]),
                            ])

                    if len(points) >= 3:
                        geometric_type = getattr(contour, 'ContourGeometricType', 'CLOSED_PLANAR')
                        if hasattr(geometric_type, '__iter__'):
                            geometric_type = str(geometric_type[0]) if geometric_type else 'CLOSED_PLANAR'
                        else:
                            geometric_type = str(geometric_type) if geometric_type else 'CLOSED_PLANAR'

                        contours.append({
                            'points': points,
                            'geometric_type': geometric_type,
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
                'color': color,
            }

    return roi_contours


def _prepare_ct_data(ct_instances):
    if not ct_instances:
        return []

    s3_client = _get_s3_client()
    ct_metadata = []

    for instance in ct_instances:
        file_reference = instance.get('path')
        if not file_reference:
            continue

        metadata = _read_ct_metadata(file_reference)
        if not metadata:
            continue

        metadata['file_reference'] = file_reference
        metadata['instance_number'] = instance.get('instance_number')
        metadata['sort_key'] = _derive_slice_sort_key(metadata, instance)
        ct_metadata.append(metadata)

    if not ct_metadata:
        return []

    ct_metadata.sort(key=lambda item: item.get('sort_key', _DEFAULT_SORT_VALUE))

    ct_data = []
    for idx, slice_meta in enumerate(ct_metadata):
        bucket, key = _parse_s3_uri(slice_meta['file_reference'])
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket, 'Key': key},
            ExpiresIn=3600,
        )

        ct_data.append({
            'index': idx,
            'url': presigned_url,
            'width': slice_meta['width'],
            'height': slice_meta['height'],
            'image_position': slice_meta['image_position'],
            'pixel_spacing': slice_meta['pixel_spacing'],
            'intercept': slice_meta['intercept'],
            'slope': slice_meta['slope'],
        })

    return ct_data


def _read_ct_metadata(file_reference):
    ds = _read_dicom_dataset(file_reference, stop_before_pixels=True)
    if not ds:
        return None

    def _safe_list(value, default):
        if value is None:
            return default
        try:
            return [float(x) for x in value]
        except Exception:
            return default

    def _safe_float(value, default):
        try:
            if value is None:
                return default
            return float(value)
        except Exception:
            return default

    metadata = {
        'width': int(getattr(ds, 'Columns', 512)),
        'height': int(getattr(ds, 'Rows', 512)),
        'image_position': _safe_list(getattr(ds, 'ImagePositionPatient', [0, 0, 0]), [0.0, 0.0, 0.0]),
        'pixel_spacing': _safe_list(getattr(ds, 'PixelSpacing', [1.0, 1.0]), [1.0, 1.0]),
        'intercept': _safe_float(getattr(ds, 'RescaleIntercept', 0), 0.0),
        'slope': _safe_float(getattr(ds, 'RescaleSlope', 1), 1.0),
        'slice_location': _safe_float(getattr(ds, 'SliceLocation', None), None),
        'instance_number_from_file': getattr(ds, 'InstanceNumber', None),
    }

    return metadata


def _derive_slice_sort_key(metadata, instance):
    image_position = metadata.get('image_position')
    if image_position and len(image_position) >= 3:
        try:
            return float(image_position[2])
        except (TypeError, ValueError):
            pass

    slice_location = metadata.get('slice_location')
    if slice_location is not None:
        return slice_location

    for candidate in (
        metadata.get('instance_number_from_file'),
        instance.get('instance_number'),
    ):
        if candidate is not None:
            try:
                return float(candidate)
            except (TypeError, ValueError):
                continue

    return _DEFAULT_SORT_VALUE


def _get_rtstruct_label(rtstruct_file, index):
    label = getattr(rtstruct_file, 'StructureSetLabel', None)
    if label:
        return str(label)
    return f'RTSTRUCT {index}'


def _build_rtstruct_label_dicom(ds, index):
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
