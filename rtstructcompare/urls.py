"""
URL configuration for rtstructcompare project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from rtstructcompare import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.home, name='home'),
    path('patients/', views.patients, name='patients'),
    path('dicom_viewer/<str:series_uid>/<uuid:rt_structure_id>/', views.dicom_viewer, name='dicom_viewer'),
    path('dicom-directories/', views.get_dicom_directories, name='get_dicom_directories'),
    path("import-dicom/", views.import_dicom, name="import_dicom"),
    
    # DICOM handler URLs for the new viewer
    path('dicom-handler/', include(([
        path('load-dicom-data/', views.load_dicom_data, name='load_dicom_data'),
        path('get-dicom-slice/', views.get_dicom_slice, name='get_dicom_slice'),
        path('render-all-slices/', views.render_all_slices, name='render_all_slices'),
        path('save-contour-ratings/', views.save_contour_ratings, name='save_contour_ratings'),
        path('get-modification-types/', views.get_modification_types, name='get_modification_types'),
        path('cleanup-temp-files/', views.cleanup_temp_files, name='cleanup_temp_files'),
        path('view-rt-structure-list/<str:series_uid>/', views.view_rt_structure_list, name='view_rt_structure_list'),
    ], 'dicom_handler'), namespace='dicom_handler')),
]
