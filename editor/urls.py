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

    path('<int:project_id>/add_val_set', views.add_val_set, name='add_val_set'),
    path('<int:project_id>/<int:val_set_id>/edit_val_set', views.edit_val_set, name='edit_val_set'),
 
    path('<int:project_id>/add_application', views.add_application, name='add_application'),
    path('<int:application_id>/edit_application', views.edit_application, name='edit_application'),
    path('<int:application_id>/make_application_release', views.make_application_release, name='make_application_release'),

    path('<int:project_id>/<int:application_id>/<int:ver_item_id>/<str:sel_dom>/add_ver_link', views.add_ver_link, name='add_ver_link'),


    
    path('<str:cat>/<int:project_id>/<int:application_id>/<int:val_set_id>/<str:sel_dom>/list_spec_items', views.list_spec_items, name='list_spec_items'),
    path('<str:cat>/<int:project_id>/<int:application_id>/<str:sel_dom>/add_spec_item', views.add_spec_item, name='add_spec_item'),
    path('<str:cat>/<int:project_id>/<int:application_id>/<int:item_id>/<str:sel_dom>/edit_spec_item', views.edit_spec_item, name='edit_spec_item'),
    path('<str:cat>/<int:project_id>/<int:application_id>/<int:item_id>/<str:sel_dom>/copy_spec_item', views.copy_spec_item, name='copy_spec_item'),
    path('<str:cat>/<int:project_id>/<int:application_id>/<int:item_id>/<str:sel_dom>/split_spec_item', views.split_spec_item, name='split_spec_item'),
    path('<str:cat>/<int:project_id>/<int:application_id>/<int:item_id>/<str:sel_dom>/del_spec_item', views.del_spec_item, name='del_spec_item'),
    path('<str:cat>/<int:project_id>/<int:application_id>/<int:val_set_id>/<str:sel_dom>/export_spec_items', views.export_spec_items, name='export_spec_items'),
    path('<str:cat>/<int:project_id>/<int:application_id>/<int:val_set_id>/<str:sel_dom>/import_spec_items', views.import_spec_items, name='import_spec_items'),
    path('<str:cat>/<int:project_id>/<int:application_id>/<int:item_id>/<str:sel_dom>/list_spec_item_history', views.list_spec_item_history, name='list_spec_item_history'),
    
]
