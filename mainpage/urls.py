from django.urls import path, re_path

from . import views

app_name = 'mainpage'

urlpatterns = [
    path('', views.MainpageView, name='mainpage'), 
]