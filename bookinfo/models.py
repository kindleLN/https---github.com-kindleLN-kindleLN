from django.db import models

# Create your models here.
class SourceModel(models.Model):
    name = models.CharField(max_length=256)
    link = models.URLField()
    has_download_function = models.BooleanField(default=False, help_text='是否拥有“下载”方法')
    info = models.TextField(blank=True, help_text='''
请简述有关的爬取情况，越详细越好，如：
https://www.linovelib.com/novel/2580.html为简介
https://w.linovelib.com/novel/2580/catalog为目录
    ''')

    def __str__(self) -> str:
        return self.name

    class Meta:
        verbose_name = '来源'
        verbose_name_plural = '来源'


class AuthorModel(models.Model):
    name = models.CharField(max_length=256)

    def __str__(self) -> str:
        return self.name

    class Meta:
        verbose_name = '作者'
        verbose_name_plural = '作者'


class BookModel(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=256)
    author = models.ForeignKey(AuthorModel, on_delete=models.CASCADE)
    last_update_time = models.DateTimeField()
    added_time = models.DateTimeField(auto_now_add=True)
    source = models.ForeignKey(SourceModel, on_delete=models.CASCADE, blank=True, null=True)
    novel_id_in_source = models.CharField(max_length=256, blank=True, help_text='指在来源站点中的ID')
    has_static_files = models.BooleanField(default=False, help_text='是否已经有静态文件于服务器中')
    is_deleted = models.BooleanField(default=False, help_text='如果勾选，则会404')
    has_warning = models.BooleanField(default=False)
    warning = models.TextField(null=True, blank=True, help_text='系统会在此给出警告')
    

    def __str__(self) -> str:
        return self.name

    class Meta:
        verbose_name = '书籍'
        verbose_name_plural = '书籍'


class VolumeModel(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=256)
    book = models.ForeignKey(BookModel, on_delete=models.CASCADE, help_text='从属的书籍系列')
    file_id = models.IntegerField(help_text='这里是下下策，想着“拿到ID就和拿到FileOBJ差不多嘛”...（笑')
    added_date = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name

    class Meta:
        verbose_name = '单行本'
        verbose_name_plural = '单行本'

