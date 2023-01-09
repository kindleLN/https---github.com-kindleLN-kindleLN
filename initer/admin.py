from django.contrib import admin
from .models import Initer
import json, threading
from django.contrib import messages
import os
from KindleLN.settings import STATIC_URL
from file.utils import doCheckUpdateRequest, doPushRequest

# Register your models here.
class IniterAdmin(admin.ModelAdmin):
    actions = [
        'saveSettings', 
        'startThreading'
    ]

    @admin.action(description='【1】保存初始设置')
    def saveSettings(self, r, qureyset):
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

        self.message_user(
            r, 
            '成功保存！现在，您需要再次全选，并执行名为【2.启动处理请求的线程】的动作', 
            messages.SUCCESS
        )


    @admin.action(description='【2】启动处理请求的线程')
    def startThreading(self, r, qureyset):
        check_thr = threading.Thread(
            target=doCheckUpdateRequest, 
            name='处理检查更新请求'
        )
        push_thr = threading.Thread(
            target=doPushRequest, 
            name='处理推送请求'
        )
        check_thr.start()
        push_thr.start()

        self.message_user(
            r, 
            '成功启动线程！同时，我们不建议您删除刚刚创建的初始化器。'+
            '这样一来，如您需要修改设置，可编辑下方的初始化器并保存，再次执行'+
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
            '另请千万注意，若服务器重启，或者您保存了Django监测的文件，使得终端提示类似下方的信息，则需要再次执行【2.启动处理请求的线程】动作！', 
            messages.WARNING
        )
        self.message_user(
            r, 
            'Starting development server at xxxxxxxxxx Quit the server with CTRL-BREAK.', 
            messages.WARNING
        )


admin.site.register(Initer, IniterAdmin)