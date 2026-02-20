"""
URL configuration for rtstructcompare project.

Simplified to include only essential pages:
1. Home page
2. Patients list page
3. DICOM web viewer page
"""
from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views
from rtstructcompare import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('import/', views.dicom_import, name='dicom_import'),

    path('user-dashboard/', views.user_dashboard, name='user_dashboard'),

    path('', views.home, name='home'),
    path('login/', views.RoleBasedLoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='home'), name='logout'),
    path('patients/', views.patients, name='patients'),
    path('patients/<uuid:patient_uuid>/', views.dicom_web_viewer, name='dicom_web_viewer_patient'),
    path('patients/<uuid:patient_uuid>/remove-access/', views.remove_patient_access, name='remove_patient_access'),
    path('patients/<uuid:patient_uuid>/delete/', views.delete_patient, name='delete_patient'),
    
    path('api/load-dicom-data/', views.load_dicom_data, name='load_dicom_data'),
    path('api/get-dicom-slice/', views.get_dicom_slice, name='get_dicom_slice'),
    path('api/submit-feedback/', views.submit_feedback, name='submit_feedback'),
]
