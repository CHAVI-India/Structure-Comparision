from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
import uuid


class DICOMInstance(models.Model):
    '''
    This is a model to store data about the DICOM instances.
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # series_instance_uid = models.ForeignKey(DICOMSeries,on_delete=models.CASCADE)
    sop_instance_uid = models.CharField(max_length=256,null=True,blank=True)
    instance_path = models.CharField(max_length=256,null=True,blank=True)
    modality = models.CharField(max_length=256,null=True,blank=True)
    # file_content = models.BinaryField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.sop_instance_uid
    
    class Meta:
        verbose_name = "DICOM Instance"
        verbose_name_plural = "DICOM Instances"
        db_table = "dicom_instance"

class DICOMSeries(models.Model):
    '''
    This is a model to store data about the DICOM series. The primary matching of the rules will always be done with the DICOM series.
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    study = models.ForeignKey('DICOMStudy',on_delete=models.CASCADE)
    dicom_instance_uid = models.ForeignKey(DICOMInstance,on_delete=models.CASCADE)
    series_instance_uid = models.CharField(max_length=256,null=True,blank=True)
    series_root_path = models.CharField(max_length=256,null=True,blank=True)
    frame_of_reference_uid = models.CharField(max_length=256,null=True,blank=True)
    series_description = models.CharField(max_length=256,null=True,blank=True)
    series_date = models.DateField(null=True,blank=True)
    instance_count = models.IntegerField(null=True,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.series_instance_uid
    
    class Meta:
        verbose_name = "DICOM Series"
        verbose_name_plural = "DICOM Series"
        db_table = "dicom_series"

class Patient(models.Model):
    '''
    This is a model to store data about the patients.
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient_id = models.CharField(max_length=256,null=True,blank=True, unique=True)
    patient_name = models.CharField(max_length=100,null=True,blank=True)
    patient_gender = models.CharField(max_length=10,null=True,blank=True)
    patient_date_of_birth = models.DateField(null=True,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.patient_name

    class Meta:
        verbose_name = "Patient"
        verbose_name_plural = "Patients"
        ordering = ["-patient_date_of_birth"]  

class DICOMStudy(models.Model):
    '''
    This is a model to store data about the DICOM studies.
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient,on_delete=models.CASCADE)
    study_instance_uid = models.CharField(max_length=256,null=True,blank=True)
    study_date = models.DateField(null=True,blank=True)
    study_time = models.TimeField(null=True,blank=True,help_text="Time the study was performed")
    study_description = models.CharField(max_length=256,null=True,blank=True)
    study_protocol = models.CharField(max_length=256,null=True,blank=True)
    study_id = models.CharField(max_length=256,null=True,blank=True,help_text="Study ID")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)    

    def __str__(self):
        return self.study_instance_uid
    
    class Meta:
        verbose_name = "DICOM Study"
        verbose_name_plural = "DICOM Studies"
        ordering = ["-study_date"]
        db_table = "dicom_study"

class RTStruct(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    series = models.ForeignKey(DICOMInstance,on_delete=models.CASCADE)
    rtstruct_instance_uid = models.CharField(max_length=256,null=True,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class Roi(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rtstruct = models.ForeignKey('RTStruct',on_delete=models.CASCADE)
    roi_name = models.CharField(max_length=256,null=True,blank=True)
    roi_id = models.CharField(max_length=256,null=True,blank=True)
    roi_description = models.CharField(max_length=256,null=True,blank=True)
    roi_color = models.CharField(max_length=256,null=True,blank=True)
    


