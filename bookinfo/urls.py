from django.urls import path

from . import views

app_name = 'info'

urlpatterns = [
    path('', views.indexView, name='index'),
    path('<int:id>/', views.infoView, name='info'),
    path('search/', views.searchView, name='search'),
    path('check_update/<int:id>/', views.checkUpdateView, name='check_update'),
]
