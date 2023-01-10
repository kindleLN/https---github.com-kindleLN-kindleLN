from django.urls import path

from . import views

app_name = 'error'

urlpatterns = [
    path('', views.indexView, name='index'),
    path('<int:id>/', views.infoView, name='info'),
]
