import os
import datetime

from django.conf import settings
from django.db import models
from bookinfo.models import BookModel, VolumeModel

# Create your models here.

MEDIA_ROOT = os.path.join(settings.MEDIA_ROOT,'netdisk')

class EmailModel(models.Model):
    email = models.CharField(max_length=256, help_text='若修改，请保证以[@kindle.com]结尾')
    last_push_time = models.DateTimeField(
        default=datetime.datetime.strptime('1900-1-1 9:00', '%Y-%m-%d %H:%M'),  
        help_text='1900-1-1 9:00代表最近未推送.'
        )
    total_push_times = models.IntegerField(default=0, help_text='已经推送的次数')

    def __str__(self) -> str:
        return self.email

    class Meta:
        verbose_name = '邮箱'
        verbose_name_plural = '邮箱'


class FileModel(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=256)
    digest = models.ForeignKey('DigestModel', on_delete=models.CASCADE, null=False, help_text='警告：请勿随意修改，除非你知道你在做什么！')
    upload_time = models.DateField(auto_now_add=True)
    size = models.IntegerField(default=0)
    is_auto_upload_file = models.BooleanField(default=True, help_text='是否为系统自动上传的文件')
    
    def __str__(self):
        return self.name

    def getFileInfo(self):
        return '文件大小：%s | 创建时间：%s'%(self.getFileSize(), self.upload_time)

    def delete(self):
        if self.is_auto_upload_file:
            vol_obj = VolumeModel.objects.get(file_id=self.id)
            vol_obj.delete()
        self.digest.checkDigest()
        super().delete(using=None, keep_parents=False)
        
    def getUrlPath(self):
        return self.name

    def getFilePath(self):
        return os.path.join(MEDIA_ROOT, self.digest.digest)

    def removeFile(self):
        os.remove(self.getFilePath())
    
    def getFileSize(self):
        size = self.size
        if size > 1024 ** 3:  # GB
            size = '{:.2f} GB'.format(size / (1024 ** 3))
        elif size > 1024 ** 2:  # MG
            size = '{:.2f} MB'.format(size / (1024 ** 2))
        elif size > 1024:
            size = '{:.2f} KB'.format(size / (1024))
        else:
            size = '{:.2f} Bytes'.format(size)
        return size
    
    class Meta:
        verbose_name = '文件'
        verbose_name_plural = '文件'


class DigestModel(models.Model):
    digest = models.CharField(max_length=32, primary_key=True, help_text='警告：请勿随意修改，除非你知道你在做什么！')

    def __str__(self):
        return '[%s]%s'%(self.digest, str(self.filemodel_set.values_list('name')))

    def getDigestInfo(self):
        return str(self.digest)

    def getMd5Path(self):
        return os.path.join(MEDIA_ROOT, self.digest)

    def checkDigest(self):
        # 实际文件不存在但MD5库有记录，删除该条记录
        if not os.path.isfile(self.getMd5Path()):
            self.delete()
        # 实际文件存在且MD5有记录，但没有关联的FileModel，删除实际文件和MD5记录
        elif not self.filemodel_set.all():
            os.remove(self.getMd5Path())
            self.delete()

    @classmethod
    def digestRepair(cls):
        if not os.path.isdir(MEDIA_ROOT):
            os.makedirs(MEDIA_ROOT)
        # 用于清除数据库没有对应记录的文件
        for file in os.listdir(MEDIA_ROOT):
            if not cls.objects.filter(digest=file):
                print(f"文件'{file}'无对应digest记录，已删除")
                os.remove(os.path.join(MEDIA_ROOT, file))
        # 用于清除没有文件记录或没有对应文件的digest
        for digest in cls.objects.all():
            digest.checkDigest()
    
    class Meta:
        verbose_name = 'Digest'
        verbose_name_plural = 'Digests'


class PushRequestModel(models.Model):
    id = models.AutoField(primary_key=True)
    request_time = models.DateTimeField(auto_now_add=True)
    email = models.ForeignKey(EmailModel, on_delete=models.CASCADE)
    file = models.ForeignKey(FileModel, on_delete=models.CASCADE)
    done = models.BooleanField(default=False, help_text='勾选代表已经完成推送')
    done_time = models.DateTimeField(blank=True, null=True, help_text='完成推送的时间，请不要随意修改')

    def __str__(self) -> str:
        return '[%s]%s'%(self.email, self.file)
   
    class Meta:
        verbose_name = '推送请求'
        verbose_name_plural = '推送请求'


class CheckUpdateRequestModel(models.Model):
    id = models.AutoField(primary_key=True)
    request_time = models.DateTimeField(auto_now_add=True)
    book = models.ForeignKey(BookModel, on_delete=models.CASCADE)
    done = models.BooleanField(default=False, help_text='勾选代表已经完成更新检查')
    done_time = models.DateTimeField(blank=True, null=True, help_text='完成检查的时间，请不要随意修改')

    def __str__(self) -> str:
        return self.book.name
   
    
    class Meta:
        verbose_name = '检查更新请求'
        verbose_name_plural = '检查更新请求'
