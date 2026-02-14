from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.contrib.auth.models import User
import uuid


class Patient(models.Model):
    '''
    This is a model to store data about the patients.
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient_id = models.CharField(max_length=256,null=True,blank=True, unique=True, db_index=True)
    patient_name = models.CharField(max_length=100,null=True,blank=True, db_index=True)
    patient_gender = models.CharField(max_length=10,null=True,blank=True)
    patient_date_of_birth = models.DateField(null=True,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.patient_name or self.patient_id

    class Meta:
        db_table = 'patients'
        ordering = ["-updated_at"]


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
        db_table = "dicom_studies"


class DICOMSeries(models.Model):
    '''
    This is a model to store data about the DICOM series. The primary matching of the rules will always be done with the DICOM series.
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    study = models.ForeignKey(DICOMStudy,on_delete=models.CASCADE)
    series_instance_uid = models.CharField(max_length=256,null=True,blank=True, db_index=True)
    series_root_path = models.CharField(max_length=256,null=True,blank=True)
    frame_of_reference_uid = models.CharField(max_length=256,null=True,blank=True)
    modality = models.CharField(max_length=50, db_index=True)
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


class DICOMInstance(models.Model):
    """
    Represents a single .dcm file (one CT slice or one RTSTRUCT file)
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    series = models.ForeignKey(DICOMSeries,on_delete=models.CASCADE)
    sop_instance_uid = models.CharField(max_length=256,null=True,blank=True, db_index=True)
    instance_number = models.IntegerField(null=True, blank=True)
    instance_path = models.CharField(max_length=256,null=True,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.sop_instance_uid
    
    class Meta:
        verbose_name = "DICOM Instance"
        verbose_name_plural = "DICOM Instances"
        db_table = "dicom_instances"


class RTStruct(models.Model):
    """
    Metadata specific to an RTSTRUCT file
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instance = models.OneToOneField(DICOMInstance, on_delete=models.CASCADE)
    referenced_series_uid = models.CharField(max_length=256, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.referenced_series_uid or str(self.instance)
    
    class Meta:
        verbose_name = "RT Structure"
        verbose_name_plural = "RT Structures"
        db_table = "rtstructs"


class Roi(models.Model):
    """
    Individual Structures (e.g., Lung, Heart, PTV) within an RTSTRUCT
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    roi_number = models.IntegerField(db_index=True)
    rtstruct = models.ForeignKey(RTStruct, on_delete=models.CASCADE)
    roi_label = models.CharField(max_length=256,null=True,blank=True, db_index=True)
    roi_id = models.CharField(max_length=256,null=True,blank=True, db_index=True)
    roi_description = models.CharField(max_length=256,null=True,blank=True)
    roi_color = models.CharField(max_length=256,null=True,blank=True)
    # Production: Store the geometric stats or a pointer to the contour data
    volume_cc = models.FloatField(null=True, blank=True)
    
    def __str__(self):
        return f"{self.roi_label} ({self.rtstruct})"
    
    class Meta:
        db_table = "rtstruct_rois"
        constraints = [
            models.UniqueConstraint(fields=['rtstruct', 'roi_label'], name='unique_roi_per_struct')
        ]


class PatientAssignment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='patient_assignments')
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='assignments')
    assigned_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} → {self.patient.patient_id}"

    class Meta:
        db_table = 'patient_assignments'
        ordering = ['-assigned_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'patient'], name='uniq_patient_assignment_user_patient')
        ]


class AssignmentGroup(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120, db_index=True)
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
        db_table = 'assignment_groups'
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


class Feedback(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    study_uid = models.CharField(max_length=256, null=True, blank=True, db_index=True)
    
    roi_rt1 = models.ForeignKey(Roi, on_delete=models.CASCADE, related_name='feedback_rt1')
    roi_rt2 = models.ForeignKey(Roi, on_delete=models.CASCADE, related_name='feedback_rt2')
    
    common_roi_label = models.CharField(max_length=256, db_index=True, help_text='Common ROI structure name')
    
    rt1_label = models.CharField(max_length=512, null=True, blank=True, help_text='Identifying label for RTSTRUCT 1')
    rt2_label = models.CharField(max_length=512, null=True, blank=True, help_text='Identifying label for RTSTRUCT 2')
    
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

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.roi_rt1.roi_label != self.roi_rt2.roi_label:
            raise ValidationError("You cannot compare two ROIs with different labels.")
        
        if self.roi_rt1.rtstruct.instance.series.study.patient != self.roi_rt2.rtstruct.instance.series.study.patient:
            raise ValidationError("ROIs must belong to the same patient.")
        
        if self.roi_rt1.rtstruct.instance.series.study != self.roi_rt2.rtstruct.instance.series.study:
            raise ValidationError("ROIs must belong to the same study.")

    def __str__(self):
        return f"{self.user} - {self.common_roi_label} ({self.roi_rt1} vs {self.roi_rt2})"
    class Meta:
        db_table = "roi_feedbacks"
        ordering = ['-created_at']

