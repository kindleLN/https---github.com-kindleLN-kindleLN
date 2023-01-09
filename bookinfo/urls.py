from django.urls import path

from . import views

app_name = 'info'

urlpatterns = [
    path('<int:id>/', views.infoView, name='info'),
    path('', views.indexView, name='index'),
    path('check_update/<int:id>/', views.checkUpdateView, name='check_update'),
]
