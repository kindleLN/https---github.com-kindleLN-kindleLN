import datetime
import os
import random
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from django.utils import timezone
from docx import Document

from file.models import EmailModel
from file.utils import getJsonConfig


def sendEmail(email_obj: EmailModel):
    """ 这个函数只应该被用来送出激活邮箱的验证码 """
    try:
        if (timezone.now() - email_obj.last_send_code_time).seconds <= 600:
            return
    except:
        pass

    email_obj.code = random.randint(1, 999999999)
    email_obj.save()
    fromaddr = getJsonConfig('do_push_email')
    pwd = getJsonConfig('do_push_email_pwd')
    smtp_url = getJsonConfig('do_push_email_smtp_url')
    toaddrs = [email_obj.email]

    # 写docx
    file_name = 'code_for_%s.docx' % email_obj.email.replace(
        '@kindle.com', '_kindle_com')
    doc = Document()
    doc.add_paragraph('您好，%s！' % email_obj.email)
    doc.add_paragraph('这是您在KindleLN的验证码：')
    code_para = doc.add_paragraph()
    code_para.add_run('%i' % email_obj.code).blod = True
    doc.add_paragraph('')
    doc.add_paragraph('邮件由系统自动在【%s】发送，有效期10分钟。' %
                      datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    doc.save(file_name)

    # 发送邮件
    content = '[%s]UTC+8\nTO:%s\nCODE:%i' % (datetime.datetime.now().strftime(
        '%Y-%m-%d %H:%M:%S'), str(toaddrs), email_obj.code)
    text_apart = MIMEText(content)

    file_apart = MIMEApplication(open(file_name, 'rb').read())
    file_apart.add_header('Content-Disposition',
                          'attachment', filename=file_name)

    mail = MIMEMultipart()
    mail.attach(text_apart)
    mail.attach(file_apart)
    mail['Subject'] = 'TITLE'

    try:
        server = smtplib.SMTP(smtp_url)
        server.login(fromaddr, pwd)
        server.sendmail(fromaddr, toaddrs, mail.as_string())
        server.quit()
    except:
        raise
    finally:
        os.remove(file_name)
