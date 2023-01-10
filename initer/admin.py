from django.contrib import admin
from .models import *
import json
import threading
from django.contrib import messages
import os
from KindleLN.settings import STATIC_URL
from file.utils import doCheckUpdateRequest, doPushRequest, getJsonConfig
from .utils import catchError, replaceTemplatesText

# Register your models here.


class IniterAdmin(admin.ModelAdmin):
    actions = [
        'saveSettings',
        'startThreading',
    ]

    @admin.action(description='【1】保存初始设置')
    @catchError
    def saveSettings(self, r, qureyset):
        try:
            old_contact_email = getJsonConfig(contact_email)
        except:
            old_contact_email = r'{{ contact_email }}'

        # obj = Initer()
        obj = qureyset[0]

        contact_email = obj.contact_email
        do_push_email = obj.do_push_email
        do_push_email_pwd = obj.do_push_email_pwd
        do_push_email_smtp_url = obj.do_push_email_smtp_url
        time_interval_between_two_push = obj.time_interval_between_two_push
        time_interval_between_two_update_check = obj.time_interval_between_two_update_check
        time_interval_between_two_push_of_an_email = obj.time_interval_between_two_push_of_an_email
        time_interval_between_two_update_check_request = obj.time_interval_between_two_update_check_request

        if (time_interval_between_two_push_of_an_email < 0 or
            time_interval_between_two_push < 0 or
                time_interval_between_two_update_check < 0):
            self.message_user(
                r,
                '输入有误，无法初始化，请确保输入的数据符合要求。如您需要帮助，可前往https://github.com/kindleLN/kindleLN查询文档。',
                messages.ERROR
            )
            return

        dct = {
            'contact_email': contact_email,
            'do_push_email': do_push_email,
            'do_push_email_pwd': do_push_email_pwd,
            'do_push_email_smtp_url': do_push_email_smtp_url,
            'time_interval_between_two_push': time_interval_between_two_push,
            'time_interval_between_two_update_check': time_interval_between_two_update_check,
            'time_interval_between_two_push_of_an_email': time_interval_between_two_push_of_an_email,
            'allow_user_send_check_update_reqest': (time_interval_between_two_update_check_request >= 0),
            'time_interval_between_two_update_check_request': time_interval_between_two_update_check_request,
        }

        json_path = os.path.join(STATIC_URL, 'data.json')
        with open(json_path, 'w') as j:
            json.dump(dct, j)

        replaceTemplatesText(old_contact_email, contact_email)

        self.message_user(
            r,
            '成功保存！现在，您需要再次全选，并执行名为【2.启动处理请求的线程】的动作',
            messages.SUCCESS
        )

    @admin.action(description='【2】启动处理请求的线程')
    @catchError
    def startThreading(self, r, qureyset):
        check_thr = threading.Thread(
            target=fixedDoCheckUpdateRequest,
            name='处理检查更新请求'
        )
        push_thr = threading.Thread(
            target=fixedDoPushRequest,
            name='处理推送请求'
        )
        check_thr.start()
        push_thr.start()

        self.message_user(
            r,
            '成功启动线程！同时，我们不建议您删除刚刚创建的初始化器。' +
            '这样一来，如您需要修改设置，可编辑下方的初始化器并保存，再次执行' +
            '名为【1.保存初始设置】的动作即可更新设置。',
            messages.SUCCESS
        )
        self.message_user(
            r,
            '如您需要帮助，可前往https://github.com/kindleLN/kindleLN查询文档。',
            messages.SUCCESS
        )
        self.message_user(
            r,
            '另请千万注意，若服务器重启，或者您保存了Django监测的文件，使得终端Reload，则需要再次执行【2.启动处理请求的线程】动作！',
            messages.WARNING
        )
        self.message_user(
            r,
            '若您不想看到这些提示，请使用【常规管理器】而非【初始化器】',
            messages.WARNING
        )


class ManagerAdmin(admin.ModelAdmin):
    actions = [
        'checkAndRestartThreading',
        'querySettings'
    ]

    @admin.action(description='维护处理请求的线程')
    @catchError
    def checkAndRestartThreading(self, r, q):  # [q]从这里开始偷懒
        push = False
        check_update = False

        for i in threading.enumerate():
            if i.name == '处理推送请求':
                push = True
            elif i.name == '处理检查更新请求':
                check_update = True

        if not check_update:
            check_thr = threading.Thread(
                target=fixedDoCheckUpdateRequest,
                name='处理检查更新请求'
            )
            check_thr.start()
            self.message_user(
                r,
                '检查发现【处理检查更新请求】线程不存在，已重新创建。',
                messages.SUCCESS
            )
        if not push:
            push_thr = threading.Thread(
                target=fixedDoPushRequest,
                name='处理推送请求'
            )
            push_thr.start()
            self.message_user(
                r,
                '检查发现【处理推送请求】线程不存在，已重新创建。',
                messages.SUCCESS
            )

    @admin.action(description='查询现有设置')
    @catchError
    def querySettings(self, r, q):
        from file.utils import getJsonConfig

        self.message_user(
            r,
            '查询到以下信息',
            messages.SUCCESS
        )

        keys = [
            ('contact_email', '联系邮箱/页脚邮箱'),
            ('do_push_email', '发送邮件的邮箱'),
            ('do_push_email_pwd', '发送邮件的邮箱的密码/授权码'),
            ('do_push_email_smtp_url', '发送邮件的邮箱的SMTP地址'),
            ('time_interval_between_two_push', '处理两个推送请求的时间间隔，单位：秒(s)'),
            ('time_interval_between_two_update_check', '处理两个检查更新请求的时间间隔，单位：秒(s)'),
            ('time_interval_between_two_push_of_an_email',
             '对于同一个邮箱，两次推送的间隔时间，单位：分(min)'),
            ("allow_user_send_check_update_reqest", '允许用户提交更新请求'),
            ('time_interval_between_two_update_check_request',
             '对于一本书籍，允许提交更新检查的时间间隔，单位：小时(h)'),
        ]

        for k, n in keys:
            self.message_user(
                r,
                '【%s】：%s' % (n, getJsonConfig(k)),
                messages.SUCCESS
            )


class ErrorAdmin(admin.ModelAdmin):
    list_display = (
        'read',
        'raised_time',
        'raised_by',
        'error_repr',
    )
    list_display_links = (
        'raised_time',
    )
    list_filter = (
        'read',
    )
    actions = [
        'makeAllErrorsRead',
    ]

    @admin.action(description='标记所选错误为已读')
    @catchError
    def makeAllErrorsRead(self, r, queryset):
        queryset.update(read=True)
        self.message_user(
            r,
            '成功标记%i个对象为已读。另外，我们真的建议您了解一下报错信息，以维护网站运行。' % len(queryset),
            messages.SUCCESS
        )


admin.site.register(IniterModel, IniterAdmin)
admin.site.register(ManagerModel, ManagerAdmin)
admin.site.register(ErrorModel, ErrorAdmin)


def fixedDoCheckUpdateRequest():
    while True:
        try:
            doCheckUpdateRequest()
        except:
            pass


def fixedDoPushRequest():
    while True:
        try:
            doPushRequest()
        except:
            pass
