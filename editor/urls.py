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
    path('<int:app_id>/edit_application', views.edit_application, name='edit_application'),
    path('<int:app_id>/make_application_release', views.make_application_release, name='make_application_release'),
    
    path('<str:cat>/<int:project_id>/<int:app_id>/<int:val_set_id>/<str:sel_dom>/list_spec_items', views.list_spec_items, name='list_spec_items'),
    path('<str:cat>/<int:project_id>/<int:app_id>/<str:sel_dom>/add_spec_item', views.add_spec_items, name='add_spec_items'),
    path('<str:cat>/<int:project_id>/<int:app_id>/<int:item_id>/<str:sel_dom>/edit_spec_items', views.edit_spec_items, name='edit_spec_items'),
    path('<str:cat>/<int:project_id>/<int:app_id>/<int:item_id>/<str:sel_dom>/copy_spec_items', views.copy_spec_items, name='copy_spec_items'),
    path('<str:cat>/<int:project_id>/<int:app_id>/<int:val_set_id>/<str:sel_dom>/export_spec_items', views.export_spec_items, name='export_spec_items'),
    
]
