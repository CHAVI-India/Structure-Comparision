from django import forms

from s3file.forms import S3FileInputMixin


class DicomFolderInput(forms.FileInput, S3FileInputMixin):
    allow_multiple_selected = True


class DicomFolderImportForm(forms.Form):
    dicom_files = forms.FileField(
        required=True,
        widget=DicomFolderInput(
            attrs={
                "id": "dicom_files",
                "multiple": True,
                "webkitdirectory": True,
                "directory": True,
                "accept": ".dcm,application/dicom",
                "class": "sr-only",
            }
        ),
    )
