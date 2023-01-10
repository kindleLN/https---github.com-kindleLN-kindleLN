from django.contrib import admin
from .models import *
from django.contrib import messages
from initer.utils import catchError

# Register your models here.
class FileAdmin(admin.ModelAdmin):
    list_display = (
        'id', 
        'name', 
        'is_auto_upload_file', 
        'upload_time', 
        'size', 
    )
    list_display_links = (
        'name', 
    )
    list_filter = (
        'is_auto_upload_file', 
    )
    actions = [
        'safeDeleteQueryset', 
        'forceDeleteQueryset', 
    ]

    def delete_queryset(self, r, queryset):
        self.message_user(
            r, 
            '注意：Django自带的删除已弃用，请使用【安全删除】或【强制删除】。'+
            '也请您不要使用详情界面的【删除】'+
            '另请忽略下方的【成功删除】提示，实际上你刚刚什么也没有做。',
            messages.WARNING
        )
        pass

    @admin.action(description='【强制删除】所选的对象')
    @catchError
    def forceDeleteQueryset(self, r, queryset):
        ttl = len(queryset)
        queryset.delete()
        for i in queryset:
            i.digest.checkDigest()
        self.message_user(
            r, 
            '成功【强制删除】了%i个对象。'%ttl, 
            messages.SUCCESS
        )
        self.message_user(
            r, 
            '另请注意：可能已经出现了隐含的BUG（特别是单行本的file_id），请尽快检查。\n'+
            '如您可打开单行本的管理界面，并全选执行【检查并移除对应文件已不存在的 单行本】这一动作。',
            messages.WARNING, 
        )

    @admin.action(description='【安全删除】所选的对象')
    @catchError
    def safeDeleteQueryset(self, r, queryset):
        ttl = len(queryset)
        last = ttl
        try:
            for i in queryset:
                i.delete()
                last -= 1
            self.message_user(
                r, 
                '成功【安全删除】%i个对象。'%ttl, 
                messages.SUCCESS, 
                )
        except Exception as e:
            self.message_user(
                r, 
                '警告：尝试【安全删除】对象时出现错误，请前往命令行查看报错。\n'+
                '另外，在选中的%i个对象中，剩余%i个对象无法【安全删除】，'%(ttl, last)+
                '这意味着可能在某些地方（特别是单行本的file_id）会出现/已出现BUG，请尽快检查！\n'+
                '您可以打开单行本的管理界面，并全选执行【检查并移除对应文件已不存在的 单行本】这一动作。\n'
                '另外，如果您知道您在做什么，您可使用【强制删除】。',
                messages.ERROR, 
            )
            print('\n%s\n'%repr(e))


class EmailAdmin(admin.ModelAdmin):
    list_display = (
        'email', 
        'active', 
        'last_push_time', 
        'total_push_times', 
        'code', 
    )
    list_display_links = (
        'email', 
    )
    list_filter = (
        'active', 
    )


class PushRequsetAdmin(admin.ModelAdmin):
    list_display = (
        'id', 
        'email', 
        'file', 
        'request_time', 
        'done', 
        'done_time', 
    )
    list_display_links = (
        'email', 
    )
    list_filter = (
        'done', 
        'email', 
    )


class CheckUpdateRequestAdmin(admin.ModelAdmin):
    list_display = (
        'id', 
        'book', 
        'request_time', 
        'done', 
        'done_time', 
    )
    list_display_links = (
        'book', 
    )
    list_filter = (
        'done', 
    )


admin.site.register(FileModel, FileAdmin)
admin.site.register(DigestModel)
admin.site.register(EmailModel, EmailAdmin)
admin.site.register(PushRequestModel, PushRequsetAdmin)
admin.site.register(CheckUpdateRequestModel, CheckUpdateRequestAdmin)