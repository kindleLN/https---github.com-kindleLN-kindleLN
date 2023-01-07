from django.contrib import admin
from .models import *

# Register your models here.
admin.site.register(BookModel)
admin.site.register(AuthorModel)
admin.site.register(SourceModel)
admin.site.register(VolumeModel)