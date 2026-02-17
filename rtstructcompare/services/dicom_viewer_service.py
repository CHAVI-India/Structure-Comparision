import json
from pathlib import Path
import pydicom

from ..models import (
    DICOMStudy,
    DICOMSeries,
    RTStruct,
    Roi,
    Feedback,
)


class DicomViewerError(Exception):
    """Raised when the viewer cannot prepare the requested patient."""


def build_viewer_context(patient, *, user=None):
    """Build the data payload required by the DICOM web viewer template."""
    studies = DICOMStudy.objects.filter(patient=patient)
    if not studies.exists():
        raise DicomViewerError(f'No studies found for patient {patient.patient_id}')

    latest_study = studies.first()
    ct_file_paths, rtstruct_file_paths = _load_dicom_files_from_database(patient)

    if not ct_file_paths:
        raise DicomViewerError(f'No CT files found for patient {patient.patient_id}')

    if len(rtstruct_file_paths) < 2:
        raise DicomViewerError(
            f'Need at least 2 RTSTRUCT files for comparison, found {len(rtstruct_file_paths)}. '
            f'Found {len(ct_file_paths)} CT files.'
        )

    dicom_files = _load_dicom_files_from_paths(ct_file_paths + rtstruct_file_paths)
    ct_files, rtstruct_files = _analyze_dicom_data(dicom_files)

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

    ct_data = _prepare_ct_data(ct_files)

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
    }


def _load_dicom_files_from_database(patient):
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

                dicom_files = list(series_path.glob('*.dcm'))
                for dicom_file in dicom_files:
                    try:
                        ds = pydicom.dcmread(dicom_file, stop_before_pixels=True)
                        modality = getattr(ds, 'Modality', None)
                        if modality == 'CT':
                            ct_file_paths.append(str(dicom_file))
                        elif modality == 'RTSTRUCT':
                            rtstruct_file_paths.append(str(dicom_file))
                    except Exception:
                        continue

    return ct_file_paths, rtstruct_file_paths


def _load_dicom_files_from_paths(file_paths):
    dicom_files = []
    for file_path in file_paths:
        try:
            if Path(file_path).exists():
                ds = pydicom.dcmread(file_path)
                dicom_files.append(ds)
        except Exception:
            continue
    return dicom_files


def _analyze_dicom_data(dicom_files):
    ct_files = []
    rtstruct_files = []
    for ds in dicom_files:
        modality = getattr(ds, 'Modality', None)
        if modality == 'CT':
            ct_files.append(ds)
        elif modality == 'RTSTRUCT':
            rtstruct_files.append(ds)
    return ct_files, rtstruct_files


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


def _prepare_ct_data(ct_files):
    if not ct_files:
        return []

    ct_files_sorted = sorted(
        ct_files,
        key=lambda x: float(getattr(x, 'ImagePositionPatient', [0, 0, 0])[2]) if hasattr(x, 'ImagePositionPatient') else 0,
    )

    ct_data = []
    for i, ct_file in enumerate(ct_files_sorted):
        if not hasattr(ct_file, 'pixel_array'):
            continue

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

        instance_number = getattr(ct_file, 'InstanceNumber', i + 1)
        if hasattr(instance_number, '__iter__'):
            instance_number = int(instance_number[0]) if instance_number else i + 1
        else:
            instance_number = int(instance_number) if instance_number else i + 1

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
            'image_orientation': image_orientation,
        }
        ct_data.append(slice_data)

    return ct_data


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
