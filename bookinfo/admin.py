from django.contrib import admin
from .models import *
from file.models import FileModel
from django.contrib import messages
from initer.utils import catchError

# Register your models here.
class BookAdmin(admin.ModelAdmin):
    list_display = (
        'id', 
        'name', 
        'author', 
        'source', 
        'has_static_files', 
        'last_update_time', 
        'is_deleted',
        )
    list_display_links = (
        'name', 
        )
    list_filter = (
        'source', 
        'has_static_files', 
        'is_deleted',
        )
    actions = [
        'checkHasStaticFiles'
    ]

    @admin.action(description='检查并更新所选书籍的静态文件状态')
    @catchError
    def checkHasStaticFiles(self, r, queryset):
        ttl = len(queryset)
        changed = 0

        for i in queryset:
            if i.has_static_files:
                vols = VolumeModel.objects.filter(book=i)
                if len(vols) == 0:
                    i.has_static_files = False
                    i.save()
                    changed += 1
            else:
                vols = VolumeModel.objects.filter(book=i)
                if len(vols) != 0:
                    i.has_static_files = True
                    i.save()
                    changed += 1

        self.message_user(
            r, 
            '成功检查了%i个对象，并修改了%i个对象的信息。'%(ttl, changed), 
            messages.SUCCESS
        )


class SourceAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'name', 
        'has_download_function', 
        'link',
    )
    list_display_links = (
        'name', 
    )
    list_filter = (
        'has_download_function', 
    )


class VolumeAdmin(admin.ModelAdmin):
    list_display = (
        'id', 
        'name', 
        'book', 
        'added_date', 
        'file_id', 
    )
    list_display_links = (
        'name', 
    )
    actions = [
        'checkAndRemoveUnavailableObject', 
    ]


    @admin.action(description='检查并移除对应文件已不存在的单行本')
    @catchError
    def checkAndRemoveUnavailableObject(self, r, queryset):
        ttl = len(queryset)
        sces = 0
        for i in queryset:
            try:
                FileModel.objects.get(id=i.file_id)
            except:
                sces += 1
                i.delete()
        
        self.message_user(
            r, 
            '成功检查了%i个对象，并移除了%i个对应文件不存在的对象。'%(ttl, sces), 
            messages.SUCCESS
        )


admin.site.register(BookModel, BookAdmin)
admin.site.register(AuthorModel)
admin.site.register(SourceModel, SourceAdmin)
admin.site.register(VolumeModel, VolumeAdmin)