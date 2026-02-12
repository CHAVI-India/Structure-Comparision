from django.contrib import admin
from django.contrib.auth.models import User, Group, Permission
from rtstructcompare.models import Patient, DICOMStudy, DICOMSeries, DICOMInstance, RTStruct, Roi, Feedback


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    """Admin interface for Patient model"""
    list_display = ('patient_id', 'patient_name', 'patient_gender', 'patient_date_of_birth', 'created_at', 'updated_at')
    list_filter = ('patient_gender', 'created_at', 'updated_at')
    search_fields = ('patient_id', 'patient_name')
    readonly_fields = ('id', 'created_at', 'updated_at')
    ordering = ('-created_at',)
    
    # Enable autocomplete for foreign key lookups
    def get_search_results(self, request, queryset, search_term):
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        return queryset, use_distinct
    
    fieldsets = (
        ('Patient Information', {
            'fields': ('id', 'patient_id', 'patient_name', 'patient_gender', 'patient_date_of_birth')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(DICOMStudy)
class DICOMStudyAdmin(admin.ModelAdmin):
    """Admin interface for DICOMStudy model"""
    list_display = ('study_instance_uid', 'patient', 'study_date', 'study_time', 'study_description', 'created_at')
    list_filter = ('study_date', 'created_at', 'updated_at')
    search_fields = ('study_instance_uid', 'study_description', 'patient__patient_id', 'patient__patient_name')
    readonly_fields = ('id', 'created_at', 'updated_at')
    ordering = ('-study_date',)
    
    fieldsets = (
        ('Study Information', {
            'fields': ('id', 'patient', 'study_instance_uid', 'study_id')
        }),
        ('Study Details', {
            'fields': ('study_date', 'study_time', 'study_description', 'study_protocol')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    # Show related patient info
    autocomplete_fields = ['patient']


@admin.register(DICOMSeries)
class DICOMSeriesAdmin(admin.ModelAdmin):
    """Admin interface for DICOMSeries model"""
    list_display = ('series_instance_uid', 'study', 'series_description', 'series_date', 'instance_count', 'created_at')
    list_filter = ('series_date', 'created_at', 'updated_at')
    search_fields = ('series_instance_uid', 'series_description', 'study__study_instance_uid', 'study__patient__patient_id')
    readonly_fields = ('id', 'created_at', 'updated_at')
    ordering = ('-series_date',)
    
    fieldsets = (
        ('Series Information', {
            'fields': ('id', 'study', 'dicom_instance_uid', 'series_instance_uid')
        }),
        ('Series Details', {
            'fields': ('series_description', 'series_date', 'instance_count', 'frame_of_reference_uid')
        }),
        ('File Paths', {
            'fields': ('series_root_path',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    # Show related study info
    autocomplete_fields = ['study']


@admin.register(DICOMInstance)
class DICOMInstanceAdmin(admin.ModelAdmin):
    """Admin interface for DICOMInstance model"""
    list_display = ('sop_instance_uid', 'modality', 'instance_path_short', 'created_at')
    list_filter = ('modality', 'created_at', 'updated_at')
    search_fields = ('sop_instance_uid', 'instance_path')
    readonly_fields = ('id', 'created_at', 'updated_at')
    ordering = ('-created_at',)
    
    fieldsets = (
        ('Instance Information', {
            'fields': ('id', 'sop_instance_uid', 'modality')
        }),
        ('File Information', {
            'fields': ('instance_path',)
        }),
        ('Binary Content', {
            'fields': ('file_content',),
            'classes': ('collapse',),
            'description': 'Binary DICOM file content (if stored in database)'
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def instance_path_short(self, obj):
        """Display shortened instance path"""
        if obj.instance_path:
            path = obj.instance_path
            if len(path) > 50:
                return f"...{path[-50:]}"
            return path
        return "-"
    instance_path_short.short_description = 'Instance Path'


@admin.register(RTStruct)
class RTStructAdmin(admin.ModelAdmin):
    """Admin interface for RTStruct model"""
    list_display = ('rtstruct_instance_uid', 'series', 'created_at', 'updated_at')
    list_filter = ('created_at', 'updated_at')
    search_fields = ('rtstruct_instance_uid', 'series__sop_instance_uid')
    readonly_fields = ('id', 'created_at', 'updated_at')
    ordering = ('-created_at',)
    
    fieldsets = (
        ('RTStruct Information', {
            'fields': ('id', 'series', 'rtstruct_instance_uid')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Roi)
class RoiAdmin(admin.ModelAdmin):
    """Admin interface for ROI (Region of Interest) model"""
    list_display = ('roi_label', 'roi_id', 'rtstruct', 'roi_color', 'roi_description')
    list_filter = ('rtstruct',)
    search_fields = ('roi_label', 'roi_id', 'roi_description', 'rtstruct__rtstruct_instance_uid')
    readonly_fields = ('id',)
    
    fieldsets = (
        ('ROI Information', {
            'fields': ('id', 'rtstruct', 'roi_label', 'roi_id')
        }),
        ('ROI Details', {
            'fields': ('roi_description', 'roi_color')
        }),
    )
    
    # Show related RTStruct info
    autocomplete_fields = ['rtstruct']


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    """Admin interface for Feedback model"""
    list_display = ('id', 'user', 'patient', 'roi', 'roi_label', 'rt1_rating', 'rt2_rating', 'comment', 'created_at', 'updated_at')
    list_filter = ('rt1_rating', 'rt2_rating', 'created_at', 'updated_at')
    search_fields = (
        'user__username',
        'patient__patient_id',
        'patient__patient_name',
        'roi__roi_label',
        'comment'
    )
    readonly_fields = ('id', 'created_at', 'updated_at')
    ordering = ('-created_at',)

    fieldsets = (
        ('Feedback Information', {
            'fields': ('id', 'user', 'patient', 'roi', 'roi_label', 'rt1_rating', 'rt2_rating')
        }),
        ('Details', {
            'fields': ('comment',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    autocomplete_fields = ['user', 'patient', 'roi']





# Customize admin site header and title
admin.site.site_header = "DICOM Structure Comparison Admin"
admin.site.site_title = "DICOM Admin Portal"
admin.site.index_title = "Welcome to DICOM Structure Comparison Administration"