from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.contrib.auth.models import User
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
        db_table = 'patient'
        verbose_name = "Patient"
        verbose_name_plural = "Patients"
        ordering = ["-patient_date_of_birth"]  


class PatientAssignment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='patient_assignments')
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='assignments')
    assigned_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} → {self.patient.patient_id}"

    class Meta:
        db_table = 'patient_assignment'
        ordering = ['-assigned_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'patient'], name='uniq_patient_assignment_user_patient')
        ]


class AssignmentGroup(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_assignment_groups'
    )
    users = models.ManyToManyField(User, related_name='assignment_groups', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'assignment_group'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['name', 'created_by'], name='uniq_assignment_group_name_creator')
        ]


class GroupPatientAssignment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group = models.ForeignKey(AssignmentGroup, on_delete=models.CASCADE, related_name='patient_assignments')
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='group_assignments')
    assigned_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.group.name} → {self.patient.patient_id}"

    class Meta:
        db_table = 'group_patient_assignment'
        ordering = ['-assigned_at']
        constraints = [
            models.UniqueConstraint(fields=['group', 'patient'], name='uniq_group_patient_assignment')
        ]

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
    roi_label = models.CharField(max_length=256,null=True,blank=True)
    roi_id = models.CharField(max_length=256,null=True,blank=True)
    roi_description = models.CharField(max_length=256,null=True,blank=True)
    roi_color = models.CharField(max_length=256,null=True,blank=True)


class Feedback(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    roi = models.ForeignKey(Roi, on_delete=models.CASCADE, null=True, blank=True)
    roi_label = models.CharField(max_length=256, null=True, blank=True, help_text='Common ROI structure name')
    study_uid = models.CharField(max_length=256, null=True, blank=True, help_text='StudyInstanceUID for study-wise ratings')
    rt1_label = models.CharField(
        max_length=512, null=True, blank=True,
        help_text='Identifying label for RTSTRUCT 1 (e.g. series description, SOP UID)'
    )
    rt2_label = models.CharField(
        max_length=512, null=True, blank=True,
        help_text='Identifying label for RTSTRUCT 2 (e.g. series description, SOP UID)'
    )
    rt1_sop_uid = models.CharField(max_length=256, null=True, blank=True)
    rt2_sop_uid = models.CharField(max_length=256, null=True, blank=True)
    rt1_rating = models.IntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text='Rating from 1 to 10 for RTSTRUCT 1'
    )
    rt2_rating = models.IntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text='Rating from 1 to 10 for RTSTRUCT 2'
    )
    comment = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'feedback'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['rt1_sop_uid', 'rt2_sop_uid', 'roi_label'], name='uniq_feedback_user_patient_roi')
        ]
