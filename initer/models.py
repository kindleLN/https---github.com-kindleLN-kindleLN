from django.db import models

# Create your models here.
class Initer(models.Model):
    '''这个app被用于初始化网站和便捷管理网站'''
    readme1 = models.TextField(
        help_text='请仔细阅读上方说明，并按提示操作。', 
        blank=True, 
        null=True, 
        default='您好！欢迎来到KindleLN！\n首先，请您按照提示文本，填写以下表单，以完成基本信息的设置。'
        )
    contact_email = models.EmailField(help_text='出现在【页脚】的联系邮箱，请确保您可以收到此邮箱的信息。')
    do_push_email = models.EmailField(help_text='用于【发送】邮件的邮箱，稍后您需要提供它的密码/授权码。')
    do_push_email_smtp_url = models.CharField(
        max_length=256, 
        help_text='用于【发送】邮件的邮箱的STMP地址，请确保您已经开启了POP3/SMTP/IMAP服务。'+
        '如何开启？请前往https://github.com/kindleLN/kindleLN查询文档'
        )
    do_push_email_pwd = models.CharField(
        max_length=256, 
        help_text='用于【发送】邮件的邮箱的密码/授权码。'+
        '【我应该输入密码还是授权码？】这取决于您的邮箱安全设置。如果您在开启POP3/SMTP/IMAP服务时，'+
        '邮箱明确提示您“在第三方客户端登录时，登录密码输入以下授权码”，则请输入授权码；否则，请输入密码。'+
        '【警告】这个密码/授权码会明文保存于本地文件，请确保您的邮箱不会暴露您的个人信息！'
        )
    
    readme2 = models.TextField(
        help_text='请仔细阅读上方说明，并按提示操作。', 
        blank=True, 
        null=True, 
        default='以下是对服务器【后台】的线程处理间隔的设置，请按照提示和您的服务器性能填写。'
    )  
    time_interval_between_two_push = models.IntegerField(
        default=60, 
        help_text='处理两个推送请求的时间间隔，单位：秒(s)，请不要输入负数。我们建议您至少设置为60。'
        )
    time_interval_between_two_update_check = models.IntegerField(
        default=120, 
        help_text='处理两个检查更新请求的时间间隔，单位：秒(s)，请不要输入负数。我们建议您至少设置为120。'
        )
    
    readme3 = models.TextField(
        help_text='请仔细阅读上方说明，并按提示操作。', 
        blank=True, 
        null=True, 
        default='以下是对服务器【前台】的处理间隔的设置，请按照提示和您的服务器性能填写。'
    )
    time_interval_between_two_push_of_an_email = models.IntegerField(
        default=720, 
        help_text='对于同一个邮箱，两次推送的间隔时间，单位：分(min)，请不要输入负数。如果您对您的服务器很有信心，可以设置为0.'
    )
    time_interval_between_two_update_check_request = models.IntegerField(
        default=48, 
        help_text='对于一本书籍，允许提交更新检查的时间间隔，单位：小时(h)，输入负数代表禁止用户提交更新检查。我们建议您至少设置为48。'
    )

    readme4 = models.TextField(
        help_text='请仔细阅读上方说明，并按提示操作。', 
        blank=True, 
        null=True, 
        default='如果您已经完成了上方表单的填写，请点击下方的【保存】，回到Initer（初始化器）的管理页面，'+
        '全选并使用【1.保存初始设置】操作，并按照提示继续操作。\n如您需要帮助，'+
        '可前往https://github.com/kindleLN/kindleLN查询文档。'
    )

    def __str__(self) -> str:
        return '[<--]点左边的这个框选中，然后点击上方【---】的下拉框，选中对应选项，再点击【执行】'

    class Meta:
        verbose_name = '初始化器'
        verbose_name_plural = '初始化器'