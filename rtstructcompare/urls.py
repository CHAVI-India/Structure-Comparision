"""
URL configuration for rtstructcompare project.

Simplified to include only essential pages:
1. Home page
2. Patients list page
3. DICOM web viewer page
"""
from django.contrib import admin
from django.urls import path
from rtstructcompare import views

urlpatterns = [
    # Admin
    path('admin/', admin.site.urls),
    
    # Main pages
    path('', views.home, name='home'),
    path('patients/', views.patients, name='patients'),
    path('dicom_web_viewer/', views.dicom_web_viewer, name='dicom_web_viewer'),
    path('dicom_web_viewer/<uuid:patient_uuid>/', views.dicom_web_viewer, name='dicom_web_viewer_patient'),
    
    # API endpoints for DICOM viewer
    path('api/load-dicom-data/', views.load_dicom_data, name='load_dicom_data'),
    path('api/get-dicom-slice/', views.get_dicom_slice, name='get_dicom_slice'),
]
