from django.urls import path

from . import views

app_name = 'info'

urlpatterns = [
    #./info/2580/
    path('<int:id>/', views.infoView, name='info'),
]
