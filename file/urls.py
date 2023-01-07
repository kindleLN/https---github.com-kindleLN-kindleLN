from django.urls import path, re_path

from . import views

app_name = 'file'

""" urlpatterns = [
    # ./file/
    path('', views.indexView, name='index'),
    # ./file/upload/FILEPATH/
    path('upload/<path:path>', views.uploadView, name='upload'),
    # ./file/delete/FILEPATH/
    path('delete/<path:path>', views.deleteView, name='delete'),
    # ./file/rename/OLDNAME/NEWNAME/
    path('rename/<path:path>', views.renameView, name='rename'),
    # ./file/download/FILEPATH/
    path('download/<path:path>', views.downloadView, name='download'),
] """

urlpatterns = [
    re_path(r'^$', views.indexView, name='index'),
    path('rename/<str:file_name>/', views.renameView, name='rename'),
    re_path(r'^upload/(?P<path>(\S+/?)*)$', views.uploadView, name='upload'),
    re_path(r'^download/(?P<path>(\S+/?)*)$', views.downloadView, name='download'),
    re_path(r'^delete/(?P<path>([\S]+/?)*)$', views.deleteView, name='delete'),
    path('delete_confirmation/<str:file_name>', views.deleteConfirmationView, name='delete_confirmation'),
]
