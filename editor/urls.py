from django.urls import include, path
from django.contrib.auth import views

from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('help/', views.help, name='help'),
    path('', include('django.contrib.auth.urls')),
    path('change_password', views.change_password, name='change_password'),
    
    path('add_project', views.add_project, name='add_project'),
    path('<int:project_id>/edit_project', views.edit_project, name='edit_project'),
    path('<int:project_id>/export_project', views.export_project, name='export_project'),
    path('<int:project_id>/make_project_release', views.make_project_release, name='make_project_release'),
 
    path('<int:project_id>/add_application', views.add_application, name='add_application'),
    path('<int:application_id>/edit_application', views.edit_application, name='edit_application'),
    path('<int:application_id>/make_application_release', views.make_application_release, name='make_application_release'),
    
    
    
]
