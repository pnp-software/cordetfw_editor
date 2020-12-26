from django.urls import include, path
from django.contrib.auth import views

from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('help/', views.help, name='help'),
]
