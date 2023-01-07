from django.db import models
from django.conf import settings
import os

MEDIA_ROOT = os.path.join(settings.MEDIA_ROOT,'netdisk')

# Create your models here.
class File(models.Model):
    name = models.CharField(max_length=256)
    # owner = models.ForeignKey(User, on_delete=models.CASCADE,null=True,default=None)
    # dir = models.ForeignKey('Folder', on_delete=models.CASCADE, null=False)
    digest = models.ForeignKey('Digest', on_delete=models.CASCADE, null=False, help_text='警告：请勿随意修改，除非你知道你在做什么！')
    upload_time = models.DateField(auto_now_add=True)
    size = models.IntegerField(default=0)
    

    def __str__(self):
        return self.name

    def getFileInfo(self):
        return '文件大小：%s | 创建时间：%s | %s'%(self.getFileSize(),self.upload_time, self.digest.getDigestInfo())

    def delete(self):
        super().delete(using=None, keep_parents=False)
        self.digest.checkDigest()

    def showName(self):
        return self.name
        
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


class Digest(models.Model):
    digest = models.CharField(max_length=32, primary_key=True, help_text='警告：请勿随意修改，除非你知道你在做什么！')

    def __str__(self):
        return '[%s]%s'%(self.digest, str(self.file_set.values_list('name')))

    def getDigestInfo(self):
        return str(self.digest)

    def getMd5Path(self):
        return os.path.join(MEDIA_ROOT, self.digest)

    def checkDigest(self):
        digest = self.digest
        # 文件不存在但库有记录，删除该条记录
        if not os.path.isfile(self.getMd5Path()):
            self.delete()
        # 文件存在且有记录，但没有关联的文件记录，删除文件和记录
        elif not self.file_set.all():
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