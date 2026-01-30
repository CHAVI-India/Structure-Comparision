from django.contrib import admin
from django.contrib.auth.models import User, Group, Permission
from rtstructcompare.models import DICOMSeries, DICOMInstance, RTStructureFileImport, RTStructureFileVOIData, ContourModificationTypeChoices

# Register your models here.

admin.site.register(DICOMSeries)
admin.site.register(DICOMInstance)
admin.site.register(RTStructureFileImport)
admin.site.register(RTStructureFileVOIData)
admin.site.register(ContourModificationTypeChoices)
admin.site.register(Permission)