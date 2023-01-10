from django.urls import path

from . import views

app_name = 'user'

urlpatterns = [
    path('login/', views.loginView, name='login'),
    path('logout/', views.logoutView, name='logout'),
    path('activate_email/<str:email>/<int:step>', views.activateEmailView, name='activate_email'),
    path('send_code/<str:email>/', views.sendCodeView, name='send_code'),
]
