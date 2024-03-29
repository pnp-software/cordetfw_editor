from django.urls import include, path
from django.contrib.auth import views

from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('help/', views.help, name='help'),
    path('repair/', views.repair, name='repair'),
    path('', include('django.contrib.auth.urls')),
    path('change_password', views.change_password, name='change_password'),
    
    path('add_project', views.add_project, name='add_project'),
    path('<int:project_id>/edit_project', views.edit_project, name='edit_project'),
    path('<int:project_id>/del_project', views.del_project, name='del_project'),
    path('<int:project_id>/export_project', views.export_project, name='export_project'),
    path('import_project', views.import_project, name='import_project'),
    path('<int:project_id>/make_project_release', views.make_project_release, name='make_project_release'),

    path('<int:project_id>/add_val_set', views.add_val_set, name='add_val_set'),
    path('<int:project_id>/<int:val_set_id>/edit_val_set', views.edit_val_set, name='edit_val_set'),
 
    path('<int:project_id>/add_application', views.add_application, name='add_application'),
    path('<int:application_id>/edit_application', views.edit_application, name='edit_application'),
    path('<int:application_id>/make_application_release', views.make_application_release, name='make_application_release'),

    path('<str:cat>/<int:project_id>/<int:application_id>/<int:val_set_id>/<str:sel_val>/<int:sel_rel_id>/list_spec_items', views.list_spec_items, name='list_spec_items'),
    path('<str:cat>/<int:project_id>/<int:application_id>/<int:item_id>/<str:sel_val>/list_spec_item_history', views.list_spec_item_history, name='list_spec_item_history'),
    path('<str:cat>/<int:project_id>/<int:application_id>/<str:sel_val>/<int:sel_rel_id>/add_spec_item', views.add_spec_item, name='add_spec_item'),
    path('<str:cat>/<int:project_id>/<int:application_id>/<int:item_id>/<str:sel_val>/<int:sel_rel_id>/edit_spec_item', views.edit_spec_item, name='edit_spec_item'),
    path('<str:cat>/<int:project_id>/<int:application_id>/<int:item_id>/<str:sel_val>/<int:sel_rel_id>/copy_spec_item', views.copy_spec_item, name='copy_spec_item'),
    path('<str:cat>/<int:project_id>/<int:application_id>/<int:item_id>/<str:sel_val>/<int:sel_rel_id>/split_spec_item', views.split_spec_item, name='split_spec_item'),
    path('<str:cat>/<int:project_id>/<int:application_id>/<int:item_id>/<str:sel_val>/<int:sel_rel_id>/del_spec_item', views.del_spec_item, name='del_spec_item'),
    path('<str:cat>/<int:project_id>/<int:application_id>/<int:val_set_id>/<str:sel_val>/<int:sel_rel_id>/export_spec_items', views.export_spec_items, name='export_spec_items'),
    path('<str:cat>/<int:project_id>/<int:application_id>/<int:val_set_id>/<str:sel_val>/import_spec_items', views.import_spec_items, name='import_spec_items'),
    path('<str:cat>/<int:project_id>/<int:application_id>/<int:item_id>/<str:sel_val>/<int:sel_rel_id>/refresh_spec_item', views.refresh_spec_item, name='refresh_spec_item'),
    
]
