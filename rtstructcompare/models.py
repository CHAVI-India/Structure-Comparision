from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
import uuid

class DICOMSeries(models.Model):
    '''
    This is a model to store data about the DICOM series. The primary matching of the rules will always be done with the DICOM series.
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    study = models.ForeignKey('DICOMStudy',on_delete=models.CASCADE)
    series_instance_uid = models.CharField(max_length=256,null=True,blank=True)
    deidentified_series_instance_uid = models.CharField(max_length=256,null=True,blank=True)
    series_root_path = models.CharField(max_length=256,null=True,blank=True)
    frame_of_reference_uid = models.CharField(max_length=256,null=True,blank=True)
    deidentified_frame_of_reference_uid = models.CharField(max_length=256,null=True,blank=True)
    series_description = models.CharField(max_length=256,null=True,blank=True)
    series_date = models.DateField(null=True,blank=True)
    deidentified_series_date = models.DateField(null=True,blank=True)
    series_files_fully_read = models.BooleanField(default=False)
    series_files_fully_read_datetime = models.DateTimeField(null=True,blank=True)
    instance_count = models.IntegerField(null=True,blank=True)
    # matched_rule_sets = models.ManyToManyField('RuleSet')
    # matched_templates = models.ManyToManyField('AutosegmentationTemplate')
    series_processsing_status = models.CharField(max_length=256, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.series_instance_uid
    
    class Meta:
        verbose_name = "DICOM Series"
        verbose_name_plural = "DICOM Series"
        db_table = "dicom_series"


class RTStructureFileImport(models.Model):
    '''
    This is a model to store data about the RT structure files imported from DRAW server
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    deidentified_series_instance_uid = models.ForeignKey(DICOMSeries,on_delete=models.CASCADE,null=True,blank=True)
    deidentified_sop_instance_uid = models.CharField(max_length=256,null=True,blank=True)
    deidentified_rt_structure_file_path = models.CharField(max_length=256,null=True,blank=True)
    received_rt_structure_file_checksum = models.CharField(max_length=256,null=True,blank=True)
    received_rt_structure_file_download_datetime = models.DateTimeField(null=True,blank=True)
    server_segmentation_status = models.CharField(max_length=256,null=True, blank=True)
    server_segmentation_updated_datetime = models.DateTimeField(null=True,blank=True)
    reidentified_rt_structure_file_path = models.CharField(max_length=256,null=True,blank=True)
    reidentified_rt_structure_file_export_datetime = models.DateTimeField(null=True,blank=True)
    reidentified_rt_structure_file_sop_instance_uid = models.CharField(max_length=256,null=True,blank=True)
    reidentified_rt_structure_file_series_instance_uid = models.CharField(max_length=256,null=True,blank=True)
    reidentified_rt_structure_file_study_instance_uid = models.CharField(max_length=256,null=True,blank=True)
    reidentified_rt_structure_file_sop_class_uid = models.CharField(max_length=256,null=True,blank=True)
    date_contour_reviewed = models.DateField(null=True,blank=True,help_text="Date when the contour was reviewed")
    contour_modification_time_required = models.IntegerField(null=True,blank=True,help_text="Time required to modify the contours in this structure set in minutes. Please do not include time required to create or edit new structures which were not supposed to be autosegmented.")
    assessor_name = models.CharField(max_length=256,null=True,blank=True,help_text="Name of the assessor who reviewed the contour")
    overall_rating = models.IntegerField(null=True,blank=True,
    help_text="Overall rating of the automatic segementation quality between 0 to 10 where 10 indicates an excellent quality and 0 the worst possible quality.",
    default=5, validators=[MinValueValidator(0), MaxValueValidator(10)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)    
    
    def __str__(self):
        return self.deidentified_rt_structure_file_path or self.reidentified_rt_structure_file_path or f"RTStruct Import {self.id}"  

    class Meta:
        verbose_name = "RT Structure File Import"
        verbose_name_plural = "RT Structure File Imports"
        db_table = "rt_structure_import"


class DICOMInstance(models.Model):
    '''
    This is a model to store data about the DICOM instances.
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    series_instance_uid = models.ForeignKey(DICOMSeries,on_delete=models.CASCADE)
    sop_instance_uid = models.CharField(max_length=256,null=True,blank=True)
    deidentified_sop_instance_uid = models.CharField(max_length=256,null=True,blank=True)
    instance_path = models.CharField(max_length=256,null=True,blank=True)
    file_content = models.BinaryField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.sop_instance_uid
    
    class Meta:
        verbose_name = "DICOM Instance"
        verbose_name_plural = "DICOM Instances"
        db_table = "dicom_instance"


class ContourModificationTypeChoices(models.Model):
    '''
    This is a model to store data about the contour modification type choices.
    This model will available as a many to many relationship to the RTStructureFileVOIData model.
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    modification_type = models.CharField(max_length=256,unique=True,null=True,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)    
    
    def __str__(self):
        return self.modification_type
    
    class Meta:
        verbose_name = "Contour Modification Type Choice"
        verbose_name_plural = "Contour Modification Type Choices"
        db_table = "contour_modification_type"


class RTStructureFileVOIData(models.Model):
    '''
    This is a model to store data about the RT structure file void data
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rt_structure_file_import = models.ForeignKey(RTStructureFileImport,on_delete=models.CASCADE,null=True,blank=True)
    volume_name = models.CharField(max_length=256,null=True,blank=True,help_text="Name of the volume")
    contour_modification = models.CharField(max_length=256, null=True, blank=True,help_text="Contour modification required. If the contour was blank choose Not Segmented. Note that the definiton of major modification can include scenarios where you had to completely redraw the structure, where there was significant risk of underdose to the target or overdose to the organs at risk due to error, and any modification in an axial plane exceeding 1 cm. Additionally any other criteria that you feel made you label this as major modification is also fine as long as that is documented in the comments. ")
    contour_modification_type = models.ManyToManyField(ContourModificationTypeChoices,blank=True,help_text="Type of contour modification made. You can select multiple options here or leave blank if this is not applicable. To add a new type of modification please contact your Administrator. ")
    contour_modification_comments = models.TextField(null=True,blank=True,help_text="Comments about the contour modification.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)    
    
    def __str__(self):
        return self.rt_structure_file_import.deidentified_rt_structure_file_path or self.rt_structure_file_import.reidentified_rt_structure_file_path or f"RTStruct Import {self.id}"  

    class Meta:
        verbose_name = "RT Structure File VOI Data"
        verbose_name_plural = "RT Structure File VOI Data"
        db_table = "rt_structure_voi"

class DICOMStudy(models.Model):
    '''
    This is a model to store data about the DICOM studies.
    '''
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # patient = models.ForeignKey('Patient',on_delete=models.CASCADE)
    study_instance_uid = models.CharField(max_length=256,null=True,blank=True)
    deidentified_study_instance_uid = models.CharField(max_length=256,null=True,blank=True)
    study_date = models.DateField(null=True,blank=True)
    deidentified_study_date = models.DateField(null=True,blank=True)
    study_time = models.TimeField(null=True,blank=True,help_text="Time the study was performed")
    study_description = models.CharField(max_length=256,null=True,blank=True)
    study_protocol = models.CharField(max_length=256,null=True,blank=True)
    study_modality = models.CharField(max_length=256,null=True,blank=True)
    accession_number = models.CharField(max_length=256,null=True,blank=True,help_text="Accession number for the study")
    deidentified_accession_number = models.CharField(max_length=256,null=True,blank=True,help_text="Deidentified accession number")
    study_id = models.CharField(max_length=256,null=True,blank=True,help_text="Study ID")
    deidentified_study_id = models.CharField(max_length=256,null=True,blank=True,help_text="Deidentified study ID")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)    

    def __str__(self):
        return self.study_instance_uid
    
    class Meta:
        verbose_name = "DICOM Study"
        verbose_name_plural = "DICOM Studies"
        ordering = ["-study_date"]
        db_table = "dicom_study"