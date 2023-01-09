import datetime
import hashlib
import json
import os
import random
import re
import shutil
import smtplib
import time
import uuid
from urllib import parse
from zipfile import ZIP_DEFLATED, ZipFile

import cfscrape
import emoji

from email.mime.application import MIMEApplication
from email.mime.text import MIMEText
import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone

from bookinfo.models import VolumeModel
from KindleLN.settings import STATIC_URL

from . import lnd_main
from .models import (CheckUpdateRequestModel, DigestModel, EmailModel,
                     FileModel, PushRequestModel)

from email.mime.multipart import MIMEMultipart

# 我承认一次性导入不太好...谁来改改？（逃

MEDIA_ROOT = os.path.join(settings.MEDIA_ROOT, 'netdisk')
JSON_FILE_PATH = os.path.join(STATIC_URL, 'data.json')

def doCheckUpdateRequest():
    time.sleep(getJsonConfig('time_interval_between_two_update_check'))

    latest_req = CheckUpdateRequestModel.objects.filter(done=False).order_by('request_time')
    if not latest_req:
        return

    req = latest_req[0]
    book = req.book
    book_id_in_source = book.novel_id_in_source
    source_name = book.source.name

    if not book.has_static_files or source_name == 'wenku8': # wenku8全下了
        try:
            data = lnd_main.main(int(book_id_in_source), source_name)
            book.has_static_files = True
            book.save()
        except RuntimeError as e:
            msg = '''
[%s(UTC+8)]程序抛出了如下错误，请人工解决！
正在处理的CheckUpdateRequest ID: %i（已经将该请求设置为Done）
Python返回的错误信息：%s'''%(req, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), repr(e))
            book.has_waring = True
            book.warning = msg  
            book.save()
            return
        finally:
            req.done = True
            req.done_time = timezone.now()
            req.save()

    elif source_name == 'linovelib': 
        # 检查更新并下载linovelib
        # 需要注意，这里的【检查】会下载：
        # 新的单行本
        #
        # 若果最后更新在30day内，没有新的单行本，下载最新一本！
        vols = VolumeModel.objects.filter(book=book)
        last_update_in_linovelib = getLinovelibLastUpdateDate(book.novel_id_in_source)
        linovelib_vols = getLinovelibVolumeUpdates(book.novel_id_in_source)
        last_vol = linovelib_vols[-1]

        try:
            for i in vols:
                linovelib_vols.remove(i.name)
        except:
            # 跑到这里，代表改名了（？
            # 直接重开
            book.has_static_files = False
            for i in vols:
                file_obj = FileModel.objects.get(id=i.file_id)
                file_obj.delete()
            makeCheckUpdateRequset(book)
            book.save()

        # 新的单行本
        if linovelib_vols:
            try:
                data = lnd_main.main(int(book_id_in_source), 'linovelib', download_all_volumes=False, download_vol_names=linovelib_vols)
            except RuntimeError as e:
                msg = '''
[%s(UTC+8)]程序抛出了如下错误，请人工解决！
正在处理的CheckUpdateRequest ID: %i（已经将该请求设置为Done）
Python返回的错误信息：%s'''%(req, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), repr(e))
                book.has_waring = True
                book.warning = msg  
                book.save()
                return
            finally:
                req.done = True
                req.done_time = timezone.now()
                req.save()


        # 最后更新
        elif (timezone.now() - last_update_in_linovelib).days <= 30:
            try:
                data = lnd_main.main(int(book_id_in_source), 'linovelib', download_all_volumes=False, download_vol_names=[last_vol])
            except RuntimeError as e:
                msg = '''
[%s(UTC+8)]程序抛出了如下错误，请人工解决！
正在处理的CheckUpdateRequest ID: %i（已经将该请求设置为Done）
Python返回的错误信息：%s'''%(req, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), repr(e))
                book.has_waring = True
                book.warning = msg  
                book.save()
                return
            finally:
                req.done = True
                req.done_time = timezone.now()
                req.save()
        # 否则，终止这个请求
        else:
            return
                

    # 创建Volume对象并链接FileID
    print('>>> [doCheckUpdateRequest]', data)
    for i in data:
        vol_name, file_name = i
        file_obj = FileModel.objects.get(name=file_name)
        vol_obj = VolumeModel.objects.create(
            name=vol_name, 
            book=book, 
            file_id=file_obj.id
        )
        vol_obj.save()


def doPushRequest():
    print('>>> [SendEmail]Now Trying...')
    time.sleep(getJsonConfig('time_interval_between_two_push'))

    # 基本设置
    fromaddr = getJsonConfig('do_push_email')
    pwd = getJsonConfig('do_push_email_pwd')
    smtp_url = getJsonConfig('do_push_email_smtp_url')
    time_interval = getJsonConfig('time_interval_between_two_push_of_an_email')

    # 找最新的、可以推送的对象
    reqs = PushRequestModel.objects.filter(done=False).order_by('request_time')
    if not reqs:
        return
    now_time = timezone.now()
    for req in reqs:
        if (now_time - req.email.last_push_time).seconds >= time_interval * 60:
            break

    # 要推送的对象、文件
    toaddrs = [req.email.email]
    file_path = os.path.join(MEDIA_ROOT, req.file.digest.digest)
    shutil.copy(file_path, req.file.name)# 拷贝一份到运行目录并重命名，我知道这么做不规范（笑
    file_name = req.file.name

    #发送邮件
    content = 'HELLO! HAVE A NICE DAY! '
    text_apart = MIMEText(content)

    file_apart = MIMEApplication(open(file_name, 'rb').read())
    file_apart.add_header('Content-Disposition', 'attachment', filename=file_name)

    mail = MIMEMultipart()
    mail.attach(text_apart)
    mail.attach(file_apart)
    mail['Subject'] = 'TITLE'

    try:
        server = smtplib.SMTP(smtp_url)
        server.login(fromaddr, pwd)
        server.sendmail(fromaddr, toaddrs, mail.as_string())
        server.quit()
        req.done = True
        req.done_time = timezone.now()
        req.save()
    except Exception:
        print('>>> [SendEmail] 出错了！')
        raise



def getJsonConfig(config_name):
    with open(JSON_FILE_PATH, 'r') as j:
        conf = json.load(j)
    return conf[config_name]


def makeCheckUpdateRequset(book_boj):
    cur = CheckUpdateRequestModel.objects.create(
        book=book_boj,
        done=False,
        done_time=None
    )
    cur.save()


def makePushRequest(email, file_id):
    email_obj, b = EmailModel.objects.get_or_create(email=email)
    for v in file_id:
        pr = PushRequestModel.objects.create(
            email=email_obj,
            file=FileModel.objects.get(id=v.file_id),
            done=False, 
            done_time=None
        )
        pr.save()
        print(pr)


def rename(old_name, new_name):
    file = get_object_or_404(FileModel, name=old_name)
    suffix = os.path.splitext(old_name)[1]

    if not os.path.splitext(new_name)[1]:   # 新名称不含后缀名时添加后缀
        new_name += suffix

    file_list = FileModel.objects.filter()
    new_name = getUniqueFolderName(new_name, file_list)
    file.name = new_name
    file.save()


def checkPathExits(path):
    if not os.path.isdir(path):
        os.makedirs(path)


def handleUploadFilesForLnd(file):
    # 获取当前目录内的文件
    file_list = FileModel.objects.filter()
    # 检查目录是否存在
    checkPathExits(MEDIA_ROOT)

    digest = hashlib.md5()
    # 防止文件重名
    name = file
    unique_name = getUniqueFileName(name, file_list)
    # 计算文件的MD5并作为文件名保存至MEDIA_ROOT
    with open(os.getcwd()+'\\'+file, 'rb') as f_obj:
        while True:
            data = f_obj.read(4096)
            if not data:
                break
            digest.update(data)  # 更新md5对象

    digest = digest.hexdigest()
    file_path = os.path.join(MEDIA_ROOT, digest)
    digest_obj, b = DigestModel.objects.get_or_create(digest=digest)
    # 创建文件对象
    FileModel.objects.create(name=unique_name, digest=digest_obj, size=os.path.getsize(file))
    # 重命名文件
    shutil.move(file, file_path)


def handleUploadFiles(files, user):
    # 获取当前目录内的文件
    file_list = FileModel.objects.filter()
    # 检查目录是否存在
    checkPathExits(MEDIA_ROOT)

    for file in files:
        print(type(file))
        digest = hashlib.md5()
        # 防止文件重名
        name = file.name
        unique_name = getUniqueFileName(name, file_list)
        temp_name = os.path.join(MEDIA_ROOT, str(uuid.uuid1()))
        # 计算文件的MD5并作为文件名保存至MEDIA_ROOT
        with open(temp_name, 'wb+') as destination:
            for chunk in file.chunks(chunk_size=1024):
                destination.write(chunk)
                destination.flush()
                digest.update(chunk)

        digest = digest.hexdigest()
        file_path = os.path.join(MEDIA_ROOT, digest)
        digest_obj, created = DigestModel.objects.get_or_create(digest=digest)
        # 创建文件对象
        FileModel.objects.create(name=unique_name, digest=digest_obj, size=file.size)
        # 重命名文件
        shutil.move(temp_name, file_path)


def getUniqueFolderName(name, content_list):
    ## 检查是否有重名的文件夹并按顺序生成新名称
    folder_list = [content.name for content in content_list]
    if name in folder_list:
        cont = 2
        while f'{name}({cont})' in folder_list:
            cont += 1
        name = f'{name}({cont})'
    return name


def getUniqueFileName(name, content_list):
    ## 检查是否有重名的文件夹并按顺序生成新名称
    prefix, suffix = os.path.splitext(name)
    folder_list = [content.name for content in content_list]
    if name in folder_list:
        cont = 2
        while f'{prefix}({cont}){suffix}' in folder_list:
            cont += 1
        name = f'{prefix}({cont}){suffix}'
    return name


def judgeUa(ua):
    """
    判断访问来源是pc端还是手机端
    :from: https://blog.csdn.net/Q893448322/article/details/108019494
    :ua: 访问来源头信息中的User-Agent字段内容
    :return: 'k'代表Kindle，'m'代表mobile，'c'代表电脑
    """

    if 'kindle' in ua.lower():
        return 'k'

    factor = ua

    _long_matches = r'googlebot-mobile|android|avantgo|blackberry|blazer|elaine|hiptop|ip(hone|od)|kindle|midp|mmp' \
                    r'|mobile|o2|opera mini|palm( os)?|pda|plucker|pocket|psp|smartphone|symbian|treo|up\.(browser|link)' \
                    r'|vodafone|wap|windows ce; (iemobile|ppc)|xiino|maemo|fennec'
    _long_matches = re.compile(_long_matches, re.IGNORECASE)
    _short_matches = r'1207|6310|6590|3gso|4thp|50[1-6]i|770s|802s|a wa|abac|ac(er|oo|s\-)|ai(ko|rn)|al(av|ca|co)' \
                     r'|amoi|an(ex|ny|yw)|aptu|ar(ch|go)|as(te|us)|attw|au(di|\-m|r |s )|avan|be(ck|ll|nq)|bi(lb|rd)' \
                     r'|bl(ac|az)|br(e|v)w|bumb|bw\-(n|u)|c55\/|capi|ccwa|cdm\-|cell|chtm|cldc|cmd\-|co(mp|nd)|craw' \
                     r'|da(it|ll|ng)|dbte|dc\-s|devi|dica|dmob|do(c|p)o|ds(12|\-d)|el(49|ai)|em(l2|ul)|er(ic|k0)|esl8' \
                     r'|ez([4-7]0|os|wa|ze)|fetc|fly(\-|_)|g1 u|g560|gene|gf\-5|g\-mo|go(\.w|od)|gr(ad|un)|haie|hcit' \
                     r'|hd\-(m|p|t)|hei\-|hi(pt|ta)|hp( i|ip)|hs\-c|ht(c(\-| |_|a|g|p|s|t)|tp)|hu(aw|tc)|i\-(20|go|ma)' \
                     r'|i230|iac( |\-|\/)|ibro|idea|ig01|ikom|im1k|inno|ipaq|iris|ja(t|v)a|jbro|jemu|jigs|kddi|keji' \
                     r'|kgt( |\/)|klon|kpt |kwc\-|kyo(c|k)|le(no|xi)|lg( g|\/(k|l|u)|50|54|e\-|e\/|\-[a-w])|libw|lynx' \
                     r'|m1\-w|m3ga|m50\/|ma(te|ui|xo)|mc(01|21|ca)|m\-cr|me(di|rc|ri)|mi(o8|oa|ts)|mmef|mo(01|02|bi' \
                     r'|de|do|t(\-| |o|v)|zz)|mt(50|p1|v )|mwbp|mywa|n10[0-2]|n20[2-3]|n30(0|2)|n50(0|2|5)|n7(0(0|1)' \
                     r'|10)|ne((c|m)\-|on|tf|wf|wg|wt)|nok(6|i)|nzph|o2im|op(ti|wv)|oran|owg1|p800|pan(a|d|t)|pdxg' \
                     r'|pg(13|\-([1-8]|c))|phil|pire|pl(ay|uc)|pn\-2|po(ck|rt|se)|prox|psio|pt\-g|qa\-a|qc(07|12|21' \
                     r'|32|60|\-[2-7]|i\-)|qtek|r380|r600|raks|rim9|ro(ve|zo)|s55\/|sa(ge|ma|mm|ms|ny|va)|sc(01|h\-' \
                     r'|oo|p\-)|sdk\/|se(c(\-|0|1)|47|mc|nd|ri)|sgh\-|shar|sie(\-|m)|sk\-0|sl(45|id)|sm(al|ar|b3|it' \
                     r'|t5)|so(ft|ny)|sp(01|h\-|v\-|v )|sy(01|mb)|t2(18|50)|t6(00|10|18)|ta(gt|lk)|tcl\-|tdg\-|tel(i|m)' \
                     r'|tim\-|t\-mo|to(pl|sh)|ts(70|m\-|m3|m5)|tx\-9|up(\.b|g1|si)|utst|v400|v750|veri|vi(rg|te)' \
                     r'|vk(40|5[0-3]|\-v)|vm40|voda|vulc|vx(52|53|60|61|70|80|81|83|85|98)|w3c(\-| )|webc|whit' \
                     r'|wi(g |nc|nw)|wmlb|wonu|x700|xda(\-|2|g)|yas\-|your|zeto|zte\-'

    _short_matches = re.compile(_short_matches, re.IGNORECASE)

    if _long_matches.search(factor) != None:
        return 'm'
    user_agent = factor[0:4]
    if _short_matches.search(user_agent) != None:
        return 'm'

    return 'c'


def getLinovelibVolumeUpdates(id):
    now_vols = []
    catalog_url = 'https://w.linovelib.com/novel/%s/catalog' %id

    catalog_soup = getPageHtmlSoup(catalog_url)
    vols = catalog_soup.find_all('li', class_=["chapter-bar", "chapter-li"])
    
    for v in vols:
        if v.attrs['class'] == ['chapter-bar', 'chapter-li']:# volume
            now_vols.append(v.get_text())

    return now_vols


def getLinovelibLastUpdateDate(id):
    info_url = 'https://w.linovelib.com/novel/%s.html' %id

    info_soup = getPageHtmlSoup(info_url)
    t = info_soup.find('p', class_=["gray", "ell"])
    text = t.get_text()
    date = text[:10]# 本人瓶颈，见谅
    date += ' 23:59:59'
    print(date)

    update_time = datetime.datetime.strptime(date,'%Y-%m-%d %H:%M:%S')

    return update_time


class File:
    def __init__(self, url: str, name: str) -> None:
        self.url = url
        self.name = name


def makeEpubFile(vol):
    '''
    直接输出.epub文件

    不会新建或者删除epubFile Dir，需在调用前后自行删除

    参数：
    一个**符合规范的**Volume对象

    返回：
    None
    '''

    writeContent(vol)
    writeNcx(vol)
    writeOpf(vol)

    if vol.parent.source == 'linovelib':
        file_name = '[%s]%s-%s[linovelib].epub'%(vol.volume_id, vol.name, vol.parent.name)
        getZip(os.getcwd()+'\\epubFile', file_name)
    elif vol.parent.source == 'wenku8_download':
        file_name = '%s[wenku8].epub'%vol.name
        getZip(os.getcwd()+'\\epubFile', file_name)

    handleUploadFilesForLnd(file_name)

    return (vol.name, file_name)


def writeContent(vol):
    html1 = '''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"
"http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">

<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN" xmlns:epub="http://www.idpf.org/2007/ops" lang="zh-CN">
<head>
<title>目 录</title>
<link href="flow0012.css" rel="stylesheet" type="text/css" />
</head>

<body>
<div class="chapter" id="chapter" />
<h1 class="kindle-cn-heading-2">目 录</h1>
<div class="kindle-cn-blockquote">
<a>系列：%s</a>
</div>
'''

    html2 = '''
<div>
<a href="text%i.html">%s</a>
</div>\n
'''        

    with open(os.getcwd()+'\\epubFile\\OEBPS\\content.html', 'w', encoding='utf-8') as f:
        f.write(html1%vol.parent.name)

        for i in vol.chapters:
            f.write(html2%(i.chapter_id, i.name))

        tmp_html = '''
<div class="kindle-cn-blockquote">
%s
</div>
</body>
</html>\n'''

        f.write(tmp_html%vol.info)


def writeOpf(vol):
    html = '''
<?xml version="1.0" encoding="utf-8" ?>
<package unique-identifier="BookId" version="2.0" xmlns="http://www.idpf.org/2007/opf">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:creator opf:file-as="%s" opf:role="aut">%s</dc:creator>
    <dc:title>[%s]%s - %s</dc:title>
    <dc:identifier id="BookId" opf:scheme="UUID">urn:uuid:%s</dc:identifier>
    <dc:language>zh-CN</dc:language>
</metadata>
<manifest>
    <item href="toc.ncx" id="ncx" media-type="application/x-dtbncx+xml"/>
    <item href="content.html" id="content" media-type="application/xhtml+xml"/>\n'''

    with open(os.getcwd()+'\\epubFile\\OEBPS\\content.opf', 'w', encoding='utf-8') as f:
        f.write(html%(vol.parent.author, vol.parent.author, vol.volume_id, vol.name, vol.parent.name, vol.uuid))

        #<item href="text00000.html" id="id_1" media-type="application/xhtml+xml"/>
        tmp_html = '''\n
    <item href="text%i.html" id="id_%i" media-type="application/xhtml+xml"/>'''         
        for i in vol.chapters:
            f.write(tmp_html%(i.chapter_id, i.chapter_id))

        #<item id="jpg.jpg" href="jpg.jpg" media-type="image/jpeg"/>
        tmp_html_jpg = '''\n
    <item id="pic_%s" href="%s" media-type="image/jpeg"/>'''  
        tmp_html_png = '''\n
    <item id="pic_%s" href="%s" media-type="image/png"/>'''  
        for i in vol.imgs_id:
            if i.endswith('jpg'):
                f.write(tmp_html_jpg%(i.replace('.', '_'), i))
            else:
                f.write(tmp_html_png%(i.replace('.', '_'), i))


        f.write('\n      <item href="flow0012.css" id="css" media-type="text/css"/>')

        tmp_html = '''
</manifest>
<spine toc="ncx">
    <itemref idref="content"/>\n'''
        f.write(tmp_html)

        #<itemref idref="id_46"/>
        tmp_html = '''
    <itemref idref="id_%i"/>\n'''
        for i in vol.chapters:
            f.write(tmp_html%i.chapter_id)

        tmp_html = '''
</spine>
    <guide>
        <reference type="toc" title="目录" href="content.html" />
    </guide>
</package>\n'''
        f.write(tmp_html)


def writeNcx(vol):
    html1 = '''
<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
<head>
<meta name="dtb:uid" content="urn:uuid:%s" />
<meta name="dtb:depth" content="0"/>
<meta name="dtb:totalPageCount" content="0"/>
<meta name="dtb:maxPageNumber" content="0"/>
</head>
<docTitle>
<text>linovelib</text>
</docTitle>

<navMap>
<navPoint id="content" playOrder="1">
<navLabel>
    <text>目录</text>
</navLabel>
<content src="content.html"/>
</navPoint>\n'''

    html2 = '''<navPoint id="id_%i" playOrder="%i">
<navLabel>
    <text>%s</text>
</navLabel>
<content src="text%i.html"/>
</navPoint>\n'''

    with open(os.getcwd()+'\\epubFile\\OEBPS\\toc.ncx', 'w', encoding='utf-8') as f:
        f.write(html1%vol.uuid)

        for i in vol.chapters:
            f.write(html2%(i.chapter_id, i.chapter_id+1, i.name, i.chapter_id))


def getZip(dir_path: str, file_full_name: str):
    zip_ = ZipFile(file_full_name, "w", ZIP_DEFLATED)
    for path, dirnames, filenames in os.walk(dir_path):
        # 去掉目标跟路径，只对目标文件夹下边的文件及文件夹进行压缩
        fpath = path.replace(dir_path, '')

        for filename in filenames:
            zip_.write(os.path.join(path, filename), os.path.join(fpath, filename))

    zip_.close()


def textReplacer(string: str, vol):
    string = string.replace('\n', '')
    string = string.replace('\r', '')
    string = string.replace('&', '&amp;')
    string = string.replace('<', '&lt;')
    string = string.replace('>', '&gt;')
    string = string.replace(' ', '&nbsp;')

    if emoji.demojize(string) != string:
        html = '<img class="kindle-cn-inline-character" src="emoji%i.png" alt="emoji%s_png" />'

        for i in string[:]:
            if emoji.demojize(i) != i: #是emoji的单字
                if i not in vol.emojis:
                    vol.emojis.append(i)
                    vol.emojis_file.append(File(getEmojiUrl(i), 'emoji%i.png'%vol.emojis.index(i)))
                i_id = vol.emojis.index(i)

                string = string.replace(i, html%(i_id, i_id))
                
    return string
            

def getEmojiUrl(emoji: str):
    url = 'https://www.emojiall.com/zh-hans/image/%s'%parse.quote(emoji)
    soup = getPageHtmlSoup(url)

    emoji_imgs_soup = soup.find('ul', class_="emoji_imgs imgs_lg row row-cols-1 row-cols-lg-2 mb-0")
    img_attr = emoji_imgs_soup.contents[1].contents[1].contents[1].attrs
    
    return 'https://www.emojiall.com%s'%img_attr['data-src']
    

def getPageHtmlSoup(url: str, retry_times=3, print_msg=True, encode='utf-8', use_request=False, use_pc_ua=False) -> BeautifulSoup:

    time.sleep(random.randint(5, 20)/10)
    for i in range(1, retry_times+1):
        try:
            if print_msg:
                print('[爬取HTML]尝试(%i/%i): %s\r' %(i, retry_times, url), end='')
                
            if use_pc_ua:
                header = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36 Edg/108.0.1462.54'}
            else:
                header = {'User-Agent': getFakeUA()}

            if use_request:
                req = requests.get(url, headers=header, timeout = (15.06, 27))
                page_html = req.text.encode(encode)
            else:
                scraper = cfscrape.create_scraper(delay = 5)
                page_html = scraper.get(url, headers=header, timeout=(15.06, 27)).content.decode(encode)

                if 'Cloudflare' in page_html:
                    raise RuntimeError('触发反爬机制!')

            if print_msg:
                print('\n[爬取HTML]成功! ')

            return BeautifulSoup(page_html, 'html.parser')

        except RuntimeError:
            print('\n[爬取HTML]!!警告!!触发反爬机制，休息30s后继续.')
            for i in range(1, 31):
                print('\r%is/30s'%i, end='')
                time.sleep(1)
            print()

        except:
            if print_msg:
                print('[爬取HTML]失败')

    """ raise RuntimeError('''
[爬取HTML]失败.
在爬取%s时3次超时.
    '''%url) """
    # 将这里修改为超时则一直尝试，中间休眠10min
    time.sleep(600)
    return getPageHtmlSoup(url)


def downloadFiles(files: list, save_path: str, print_msg=True, mode='wb'):
    time.sleep(random.randint(5, 20)/10)

    for file in files:
        # 修改为尝试5次，报错休息30s，否则不下了
        success = False
        for i in range(1, 5):
            if success:
                continue
            try:
                if print_msg:
                    print('[下载]尝试(%i/5): %s\r' %(i, file.url), end='')

                header = {'User-Agent': getFakeUA()}
                file_req = requests.get(file.url, headers=header, timeout = (15.06, 27))
                with open(save_path+'\\'+file.name, mode) as f:
                    f.write(file_req.content)

                if print_msg:
                    print('\n[下载]下载成功! ')
                success = True

            except:
                if print_msg:  
                    print('[下载]下载失败. ')
                time.sleep(30)


MOBILE = (
	'Mozilla/5.0 (iPod; CPU iPhone OS 6_0_1 like Mac OS X) AppleWebKit/536.26 (KHTML, like Gecko) Version/6.0 Mobile/10A523 Safari/8536.25', 
	'Mozilla/5.0 (iPod; CPU iPhone OS 6_0_1 like Mac OS X) AppleWebKit/536.26 (KHTML, like Gecko) Mobile/10A523', 
	'Mozilla/5.0 (Linux; U; Android 2.3.5; zh-cn; U8800 Build/HuaweiU8800) AppleWebKit/533.1 (KHTML, like Gecko) Version/4.0 Mobile Safari/533.1', 
	'Mozilla/5.0 (Linux; U; Android 2.3.5; zh-cn) AppleWebKit/530.17 (KHTML, like Gecko) FlyFlow/2.2 Version/4.0 Mobile Safari/530.17', 
	'Mozilla/5.0 (Linux; U; Android 2.3.5; zh-cn; U8800 Build/HuaweiU8800) UC AppleWebKit/534.31 (KHTML, like Gecko) Mobile Safari/534.31', 
	'Mozilla/5.0 (Linux; Android 4.0.3; M031 Build/IML74K) AppleWebKit/535.19 (KHTML, like Gecko) Chrome/18.0.1025.166 Mobile Safari/535.19', 
	'Opera/9.80 (Android 4.0.3; Linux; Opera Mobi/ADR-1210241511) Presto/2.11.355 Version/12.10', 
	'Mozilla/5.0 (Linux; U; Android 4.0.3; zh-cn; M031 Build/IML74K) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30', 
	'Mozilla/5.0 (Linux; U; Android 4.0.3; zh-cn) AppleWebKit/530.17 (KHTML, like Gecko) FlyFlow/2.2 Version/4.0 Mobile Safari/530.17', 
	'Mozilla/5.0 (Linux; U; Android 4.0.3; zh-cn; M031 Build/IML74K) UC AppleWebKit/534.31 (KHTML, like Gecko) Mobile Safari/534.31', 
	'MQQBrowser/3.7/Mozilla/5.0 (Linux; U; Android 2.3.5; zh-cn; U8800 Build/HuaweiU8800) AppleWebKit/533.1 (KHTML, like Gecko) Version/4.0 Mobile Safari/533.1', 
	'Mozilla/5.0 (Linux; U; Android 2.3.5; zh-cn; U8800 Build/HuaweiU8800) AppleWebKit/533.1 (KHTML, like Gecko) Version/4.0 Mobile Safari/533.1', 
	'Mozilla/5.0 (iPad; U; CPU OS 6 like Mac OS X; zh-cn Model:iPad2,1) UC AppleWebKit/534.46 (KHTML, like Gecko) Version/5.1 Mobile/9B176 Safari/7543.48.3', 
	'Mozilla/5.0 (iPad; CPU OS 6_0_1 like Mac OS X) AppleWebKit/536.26 (KHTML, like Gecko) Version/6.0 Mobile/10A523 Safari/8536.25', 
	'MQQBrowser/2.7 Mozilla/5.0 (iPad; CPU OS 6_0_1 like Mac OS X) AppleWebKit/536.26 (KHTML, like Gecko) Mobile/10A523 Safari/7534.48.3', 
	'MQQBrowser/3.7/Adr (Linux; U; 2.3.5; zh-cn; U8800 Build/U8800V100R001C00B528G002;480*800)', 
	'Mozilla/5.0 (Linux; U; Android 4.0.3; zh-cn; M031 Build/IML74K) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30', 
	'Mozilla/5.0 (iPad; CPU OS 6_0_1 like Mac OS X) AppleWebKit/536.26 (KHTML, like Gecko) Mobile/10A523', 
	'Mozilla/5.0 (iPad; CPU OS 6_0_1 like Mac OS X) AppleWebKit/536.26 (KHTML, like Gecko) Mobile/10A523', 
	'Mozilla/5.0 (iPad; U; CPU  OS 4_1 like Mac OS X; en-us)AppleWebKit/532.9(KHTML, like Gecko) Version/4.0.5 Mobile/8B117 Safari/6531.22.7', 
	'Mozilla/5.0 (iPad; CPU OS 6_0_1 like Mac OS X) AppleWebKit/536.26 (KHTML, like Gecko) Mobile/10A523', 
	'MQQBrowser/3.5/Mozilla/5.0 (Linux; U; Android 4.0.3; zh-cn; M9 Build/IML74K) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30', 
	'Mozilla/5.0 (Linux; U; Android 4.0.3; zh-cn; M9 Build/IML74K) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30', 
	'MQQBrowser/3.5/Adr (Linux; U; 4.0.3; zh-cn; M9 Build/Flyme 1.0.1;640*960)', 
	'MQQBrowser/3.7/Mozilla/5.0 (Linux; U; Android 4.0.3; zh-cn; M9 Build/IML74K) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30', 
	'MQQBrowser/3.7/Adr (Linux; U; 4.0.3; zh-cn; M9 Build/Flyme 1.0.1;640*960)', 
	'MQQBrowser/4.0/Mozilla/5.0 (Linux; U; Android 4.0.3; zh-cn; M031 Build/IML74K) AppleWebKit/533.1 (KHTML, like Gecko) Mobile Safari/533.1', 
	'Mozilla/5.0 (Linux; U; Android 4.0.3; zh-cn; M031 Build/IML74K) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30', 
	'Mozilla/5.0 (Linux; U; Android 4.0.4; zh-cn; HTC S720e Build/IMM76D) UC AppleWebKit/534.31 (KHTML, like Gecko) Mobile Safari/534.31', 
	'Mozilla/5.0 (Linux; U; Android 4.0.4; zh-cn; HTC S720e Build/IMM76D) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30', 
	'Mozilla/5.0 (Linux; U; Android 2.3.5; zh-cn; U8800 Build/HuaweiU8800) AppleWebKit/530.17 (KHTML, like Gecko) FlyFlow/2.3 Version/4.0 Mobile Safari/530.17 baidubrowser/042_1.6.3.2_diordna_008_084/IEWAUH_01_5.3.2_0088U/1001a/BE44DF7FABA8768B2A1B1E93C4BAD478%7C898293140340353/1', 
	'Mozilla/5.0 (Linux; U; Android 4.0.3; zh-cn; M031 Build/IML74K) AppleWebKit/530.17 (KHTML, like Gecko) FlyFlow/2.3 Version/4.0 Mobile Safari/530.17 baidubrowser/023_1.41.3.2_diordna_069_046/uzieM_51_3.0.4_130M/1200a/963E77C7DAC3FA587DF3A7798517939D%7C408994110686468/1', 
	'Mozilla/5.0 (Linux; U; Android 2.3.5; zh-cn; U8800 Build/HuaweiU8800) AppleWebKit/533.1 (KHTML, like Gecko) Version/4.0 Mobile Safari/533.1', 
	'Mozilla/5.0 (Linux; U; Android 3.2; zh-cn; GT-P6200 Build/HTJ85B) AppleWebKit/534.13 (KHTML, like Gecko) Version/4.0 Safari/534.13', 
	'Mozilla/5.0 (Macintosh; U; Intel Mac OS X 10_6_3) AppleWebKit/534.31 (KHTML, like Gecko) Chrome/17.0.558.0 Safari/534.31 UCBrowser/2.3.1.257', 
	'Mozilla/5.0 (Macintosh; U; Intel Mac OS X 10_6_3; en-us) AppleWebKit/533.16 (KHTML, like Gecko) Version/5.0 Safari/533.16', 
	'Mozilla/5.0 (Linux; U; Android 4.1.1; zh-cn; M040 Build/JRO03H) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30', 
	'Mozilla/5.0 (Linux; U; Android 4.1.1; zh-cn; M040 Build/JRO03H) AppleWebKit/533.1 (KHTML, like Gecko)Version/4.0 MQQBrowser/4.1 Mobile Safari/533.1', 
	'Mozilla/5.0 (Linux; U; Android 4.1.1; zh-CN; M031 Build/JRO03H) AppleWebKit/534.31 (KHTML, like Gecko) UCBrowser/8.8.3.278 U3/0.8.0 Mobile Safari/534.31', 
	'Mozilla/5.0 (Linux; U; Android 4.1.1; zh-cn; M031 Build/JRO03H) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30', 
	'Mozilla/5.0 (iPhone 5CGLOBAL; CPU iPhone OS 7_0_6 like Mac OS X) AppleWebKit/537.51.1 (KHTML, like Gecko) Version/6.0 MQQBrowser/5.0.5 Mobile/11B651 Safari/8536.25', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 7_0_4 like Mac OS X) AppleWebKit/537.51.1 (KHTML, like Gecko) Version/7.0 Mobile/11B554a Safari/9537.53', 
	'Mozilla/5.0 (Linux; U; Android 4.1.1; zh-cn; M040 Build/JRO03H) AppleWebKit/534.24 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.24 T5/2.0 baidubrowser/4.2.4.0 (Baidu; P1 4.1.1)', 
	'Mozilla/5.0 (Linux; Android 4.1.1; M040 Build/JRO03H) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/28.0.1500.64 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; Android 4.1.1; M040 Build/JRO03H) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/31.0.1650.59 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 7_0_4 like Mac OS X) AppleWebKit/537.51.1 (KHTML, like Gecko) Mobile/11B554a Safari/7534.48.3', 
	'Mozilla/5.0 (Windows NT 6.3; Win64; x64; Trident/7.0; Touch; rv:11.0) like Gecko', 
	'Mozilla/5.0 (Linux; U; Android 4.1.1; zh-CN; M040 Build/JRO03H) AppleWebKit/533.1 (KHTML, like Gecko) Version/4.0 UCBrowser/9.4.1.362 U3/0.8.0 Mobile Safari/533.1', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 7_0_4 like Mac OS X; zh-CN) AppleWebKit/537.51.1 (KHTML, like Gecko) Mobile/11B554a UCBrowser/9.3.1.339 Mobile', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 7_0_4 like Mac OS X) AppleWebKit/537.51.1 (KHTML, like Gecko) Mobile/11B554a', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 7_0_4 like Mac OS X) AppleWebKit/537.51.1 (KHTML, like Gecko) CriOS/31.0.1650.18 Mobile/11B554a Safari/8536.25', 
	'Mozilla/5.0 (Linux; Android 4.2.1; M040 Build/JOP40D) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/31.0.1650.59 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 4.2.1; zh-cn; M040 Build/JOP40D) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30 Maxthon/4.1.3.2000', 
	'Mozilla/5.0 (Linux; U; Android 4.2.1; zh-cn; M040 Build/JOP40D) AppleWebKit/534.24 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.24 T5/2.0 baidubrowser/4.1.3.1 (Baidu; P1 4.2.1)', 
	'Mozilla/5.0 (Linux; U; Android 4.2.1; zh-cn; M040 Build/JOP40D) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30', 
	'Mozilla/5.0 (Linux; U; Android 4.2.1; zh-cn; M040 Build/JOP40D) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30 baidubrowser/4.2.9.2 (Baidu; P1 4.2.1)', 
	'Mozilla/5.0 (Linux; U; Android 4.2.1; zh-cn; M040 Build/JOP40D) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 MQQBrowser/5.0 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone 5CGLOBAL; CPU iPhone OS 7_0_5 like Mac OS X) AppleWebKit/537.51.1 (KHTML, like Gecko) Version/6.0 MQQBrowser/5.0.4 Mobile/11B601 Safari/8536.25', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 7_0_5 like Mac OS X) AppleWebKit/537.51.1 (KHTML, like Gecko) Mobile/11B601 baiduboxapp/0_0.0.1.5_enohpi_6311_046/5.0.7_4C2%255enohPi/1099a/0E12BC204E06E175FD283E21BFE1661EE0A20B6CAFNTCGOKCPB/1', 
	'Mozilla/5.0 (Linux; U; Android 4.2.1; zh-cn; M040 Build/JOP40D) AppleWebKit/534.24 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.24 T5/2.0 baiduboxapp/5.1 (Baidu; P1 4.2.1)', 
	'Mozilla/5.0 (Linux; U; Android 4.2.1; zh-cn; M040 Build/JOP40D) AppleWebKit/534.24 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.24 T5/2.0 baidubrowser/4.3.16.2 (Baidu; P1 4.2.1)', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 7_0_6 like Mac OS X) AppleWebKit/537.51.1 (KHTML, like Gecko) Version/7.0 Mobile/11B651 Safari/9537.53', 
	'Mozilla/5.0 (Linux; U; Android 4.2.1; zh-CN; M040 Build/JOP40D) AppleWebKit/533.1 (KHTML, like Gecko) Version/4.0 UCBrowser/9.6.0.378 U3/0.8.0 Mobile Safari/533.1', 
	'Mozilla/5.0 (iPad; CPU OS 7_1 like Mac OS X) AppleWebKit/537.51.2 (KHTML, like Gecko) Version/6.0 MQQBrowser/4.0.2 Mobile/11D167 Safari/7534.48.3', 
	'Mozilla/5.0 (iPad; CPU OS 7_1 like Mac OS X) AppleWebKit/537.51.2 (KHTML, like Gecko) Version/7.0 Mobile/11D167 Safari/9537.53', 
	'Mozilla/5.0 (Linux; Android 4.2.1; M040 Build/JOP40D) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/33.0.1750.117 Mobile Safari/537.36 OPR/20.0.1396.72047', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-cn; M351 Build/KTU84P) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-CN; M351 Build/KTU84P) AppleWebKit/533.1 (KHTML, like Gecko) Version/4.0 UCBrowser/9.9.5.489 U3/0.8.0 Mobile Safari/533.1', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-cn; M351 Build/KTU84P) AppleWebKit/534.24 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.24 T5/2.0 baiduboxapp/6.0 (Baidu; P1 4.4.4)', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 8_0_2 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Version/8.0 Mobile/12A405 Safari/600.1.4', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 8_0_2 like Mac OS X; zh-CN) AppleWebKit/537.51.1 (KHTML, like Gecko) Mobile/12A405 UCBrowser/10.0.2.497 Mobile', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 8_0_2 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Mobile/12A405 baiduboxapp/0_0.0.6.5_enohpi_6311_046/2.0.8_4C2%255enohPi/1099a/0E12BC204E06E175FD283E21BFE1661EE0A20B6CAFNTCGOKCPB/1', 
	'Mozilla/5.0 (iPad; CPU OS 8_0_2 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Version/8.0 Mobile/12A405 Safari/600.1.4', 
	'Mozilla/5.0 (iPad; U; CPU OS 8 like Mac OS X; zh-CN; iPad2,1) AppleWebKit/534.46 (KHTML, like Gecko) UCBrowser/2.7.0.448 U3/ Mobile/10A403 Safari/7543.48.3', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 8_1 like Mac OS X; zh-CN) AppleWebKit/537.51.1 (KHTML, like Gecko) Mobile/12B411 UCBrowser/10.0.5.508 Mobile', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 8_1 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Mobile/12B411 MicroMessenger/6.0 NetType/WIFI', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 8_1 like Mac OS X; zh-CN) AppleWebKit/537.51.1 (KHTML, like Gecko) Mobile/12B411 UCBrowser/10.1.0.518 Mobile WindVane tae_sdk_ios_1.0.1', 
	'Mozilla/5.0 (Linux; U; Android 4.0.3; zh-cn; GT-N7000 Build/IML74K) AppleWebKit/533.1 (KHTML, like Gecko) Mobile MQQBrowser/4.0 Safari/533.1', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 8_0_2 like Mac OS X; zh-CN) AppleWebKit/537.51.1 (KHTML, like Gecko) Mobile/12A405 UCBrowser/10.0.2.497 Mobile', 
	'Mozilla/5.0 (Linux; U; Android 4.0.4; zh-cn; HS-EG906 Build/IMM76D) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30 MicroMessenger/5.3.1.67_r745169.462', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 8_1 like Mac OS X; zh-CN) AppleWebKit/537.51.1 (KHTML, like Gecko) Mobile/12B411 UCBrowser/10.0.5.508 Mobile', 
	'Mozilla/5.0 (Linux; Android 4.4.4; Hisense E621T Build/KTU84P) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/33.0.0.0 Mobile Safari/537.36 baiduboxapp/5.0 (Baidu; P1 4.4.4)', 
	'Mozilla/5.0 (Linux; U; Android 4.2.2; zh-cn; Q3迷你版 Build/JDQ39) AppleWebKit/534.24 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.24 T5/2.0 baiduboxapp/5.3.5 (Baidu; P1 4.2.2)', 
	'Mozilla/5.0 (Linux; Android 4.4.4; M351 Build/KTU84P) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/33.0.0.0 Mobile Safari/537.36 MicroMessenger/6.0.0.50_r844973.501 NetType/WIFI', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 8_1 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Version/8.0 Mobile/12B411 Safari/600.1.4', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-cn; HM NOTE 1LTETD Build/KTU84P) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Mobile Safari/537.36 XiaoMi/MiuiBrowser/2.0.1', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-CN; HM NOTE 1LTETD Build/KTU84P) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 UCBrowser/9.9.7.500 U3/0.8.0 Mobile Safari/534.30', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-cn; HM NOTE 1LTETD Build/KTU84P) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 MQQBrowser/5.5 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-cn; HM NOTE 1LTETD Build/KTU84P) AppleWebKit/534.24 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.24 T5/2.0 baiduboxapp/6.1 (Baidu; P1 4.4.4)', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-cn; HM NOTE 1LTETD Build/KTU84P) AppleWebKit/533.1 (KHTML, like Gecko)Version/4.0 MQQBrowser/5.5 Mobile Safari/533.1 MicroMessenger/6.0.0.54_r849063.501 NetType/WIFI', 
	'Mozilla/5.0 (iPhone 5CGLOBAL; CPU iPhone OS 8_1_1 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Version/6.0 MQQBrowser/5.5 Mobile/12B435 Safari/8536.25', 
	'Mozilla/5.0 (Linux; U; Android 4.1.1; zh-cn; MI 2S Build/JRO03L) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30 MicroMessenger/6.0.2.58_r984381.520 NetType/WIFI', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-cn; HM NOTE 1LTE Build/KTU84P) AppleWebKit/533.1 (KHTML, like Gecko)Version/4.0 MQQBrowser/5.4 TBS/025410 Mobile Safari/533.1 MicroMessenger/6.1.0.40_r1018582.540 NetType/WIFI', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-cn; HM NOTE 1LTE Build/KTU84P) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 MQQBrowser/5.6 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone 5CGLOBAL; CPU iPhone OS 8_1_2 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Version/6.0 MQQBrowser/5.6 Mobile/12B440 Safari/8536.25', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-CN; HM NOTE 1LTE Build/KTU84P) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 UCBrowser/10.1.0.527 U3/0.8.0 Mobile Safari/534.30', 
	'Mozilla/5.0 (iPhone 5CGLOBAL; CPU iPhone OS 8_1_3 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Version/6.0 MQQBrowser/5.7 Mobile/12B466 Safari/8536.25', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-CN; HM NOTE 1LTE Build/KTU84P) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 UCBrowser/10.2.0.535 U3/0.8.0 Mobile Safari/534.30', 
	'Mozilla/5.0 (Linux; Android 4.1.1; Nexus 7 Build/JRO03D) AppleWebKit/535.19 (KHTML, like Gecko) Chrome/18.0.1025.166  Safari/535.19', 
	'Mozilla/5.0 (Linux; U; Android 4.2.1; zh-cn; 2013022 Build/HM2013022) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Mobile Safari/537.36 XiaoMi/MiuiBrowser/2.1.1', 
	'Mozilla/5.0 (Linux; U; Android 4.4.2; zh-cn; X9180 Build/KVT49L) AppleWebKit/533.1 (KHTML, like Gecko)Version/4.0 MQQBrowser/5.4 TBS/025411 Mobile Safari/533.1 MicroMessenger/6.1.0.66_r1062275.542 NetType/WIFI', 
	'Mozilla/5.0 (Linux; U; Android 4.1.1; zh-cn; SCH-N719 Build/JRO03C) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-cn; HM NOTE 1LTE Build/KTU84P) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 MQQBrowser/5.8 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-cn; HM NOTE 1LTE Build/KTU84P) AppleWebKit/534.24 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.24 T5/2.0 baiduboxapp/6.5 (Baidu; P1 4.4.4)', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-cn; MI 4LTE Build/KTU84P) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 MQQBrowser/5.8 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-cn; MI 4LTE Build/KTU84P) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/39.0.0.0 Mobile Safari/537.36 XiaoMi/MiuiBrowser/2.1.1', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-cn; MI 4LTE Build/KTU84P) AppleWebKit/534.24 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.24 T5/2.0 baiduboxapp/6.5.1 (Baidu; P1 4.4.4)', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 8_3 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Version/8.0 Mobile/12F70 Safari/600.1.4', 
	'Mozilla/5.0 (iPhone 5CGLOBAL; CPU iPhone OS 8_3 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Version/6.0 MQQBrowser/5.8 Mobile/12F70 Safari/8536.25', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 8_3 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Mobile/12F70 baiduboxapp/0_0.0.5.6_enohpi_6311_046/3.8_4C2%255enohPi/1099a/0E12BC204E06E175FD283E21BFE1661EE0A20B6CAFNTCGOKCPB/1', 
	'Mozilla/5.0 (Linux; U; Android 4.1.2; zh-cn; XT885 Build/6.7.2_GC-385) AppleWebKit/533.1 (KHTML, like Gecko)Version/4.0 MQQBrowser/5.4 TBS/025440 Mobile Safari/533.1 MicroMessenger/6.2.4.51_rdf8da56.600 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (Linux; Android 5.0.1; GEM-702L Build/HUAWEIGEM-702L) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/37.0.0.0 Mobile Safari/537.36 MicroMessenger/6.3.18.800 NetType/WIFI Language/zh_TW', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; MI 5s Build/MXB48T) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/46.0.2490.85 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.4', 
	'Mozilla/5.0 (iPhone 5SGLOBAL; CPU iPhone OS 8_3 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Version/8.0 MQQBrowser/7.1.1 Mobile/12F70 Safari/8536.25 MttCustomUA/2', 
	'Mozilla/5.0 (iPhone 6p; CPU iPhone OS 10_0_2 like Mac OS X) AppleWebKit/602.1.50 (KHTML, like Gecko) Version/10.0 MQQBrowser/7.1.1 Mobile/14A456 Safari/8536.25 MttCustomUA/2', 
	'Mozilla/5.0 (iPhone 6sp; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Version/6.0 MQQBrowser/6.9.1 Mobile/14B100 Safari/8536.25 MttCustomUA/2', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B72 rabbit/1.0 baiduboxapp/0_0.0.1.7_enohpi_4331_057/1.01_2C2%7enohPi/1099a/6C098F1CCE0764F9FA70F99DA9974B9B200A469E0FCHCTFCNPL/1', 
	'Mozilla/5.0 (Linux; Android 6.0; MI 5 Build/MRA58K) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/37.0.0.0 Mobile MQQBrowser/6.8 TBS/036887 Safari/537.36 MicroMessenger/6.3.32.960 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-CN; HUAWEI GRA-UL10 Build/HUAWEIGRA-UL10) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.5.884 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; Android 6.0; HUAWEI VIE-AL10 Build/HUAWEIVIE-AL10) AppleWebKit/537.36(KHTML,like Gecko) Version/4.0 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; Android 5.1; HUAWEI RIO-UL00 Build/HUAWEIRIO-UL00) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/39.0.0.0 Mobile Safari/537.36 baiduboxapp/5.0 (Baidu; P1 5.1)', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; MI 5 Build/MXB48T) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/46.0.2490.85 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.4', 
	'Mozilla/5.0 (Linux; U; Android 4.4.2; zh-cn; SM701 Build/SANFRANCISCO) AppleWebKit/533.1 (KHTML, like Gecko)Version/4.0 MQQBrowser/5.4 TBS/025469 Mobile Safari/533.1 MicroMessenger/6.2.5.49_r7ead8bf.620 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (Linux; U; Android 5.1.1; zh-cn; Redmi 3 Build/LMY47V) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/46.0.2490.85 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.4', 
	'Mozilla/5.0 (Linux; Android 4.4.2; HUAWEI MT7-TL10 Build/HuaweiMT7-TL10) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.1 baiduboxapp/8.0 (Baidu; P1 4.4.2)', 
	'Mozilla/5.0 (iPhone 6; CPU iPhone OS 8_1_2 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Version/8.0 MQQBrowser/7.1.1 Mobile/12B440 Safari/8536.25 MttCustomUA/2', 
	'Mozilla/5.0 (Linux; Android 6.0.1; SM-A9100 Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/37.0.0.0 Mobile MQQBrowser/6.8 TBS/036887 Safari/537.36 MicroMessenger/6.3.31.940 NetType/cmnet Language/zh_CN', 
	'Mozilla/5.0 (Linux; U; Android 5.1; zh-CN; 8681-A01 Build/LMY47D) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 UCBrowser/10.9.2.712 U3/0.8.0 Mobile Safari/534.30', 
	'Mozilla/5.0 (Linux; Android 5.0.2; SM-A5000 Build/LRX22G) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/37.0.0.0 Mobile MQQBrowser/6.8 TBS/036887 Safari/537.36 MicroMessenger/6.3.31.940 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (Linux; Android 6.0; MI 5 Build/MRA58K) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/37.0.0.0 Mobile MQQBrowser/6.8 TBS/036887 Safari/537.36 MicroMessenger/6.3.31.940 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (Linux; Android 4.4.4; 3007 Build/KTU84P) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/37.0.0.0 Mobile MQQBrowser/6.8 TBS/036872 Safari/537.36 MicroMessenger/6.3.31.940 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 MicroMessenger/6.3.31 NetType/4G Language/zh_CN', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 8_1_3 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Mobile/12B466 MicroMessenger/6.3.25 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-cn; HM 2A Build/KTU84Q) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-cn; BLN-AL10 Build/HONORBLN-AL10) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/6.0 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 5.1.1; zh-cn; Redmi Note 3 Build/LMY47V) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/46.0.2490.85 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.2.10', 
	'Mozilla/5.0 (Linux; U; Android 5.1.1; zh-cn; Redmi Note 3 Build/LMY47V) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 4.4.2; zh-cn; SM701 Build/SANFRANCISCO) AppleWebKit/533.1 (KHTML, like Gecko)Version/4.0 MQQBrowser/5.4 TBS/025469 Mobile Safari/533.1 MicroMessenger/6.2.5.49_r7ead8bf.620 NetType/WIFI Language/zh_CN QQ/6.6.0.2935', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_3_4 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13G35 QQ/6.5.3.410 V1_IPH_SQ_6.5.3_1_APP_A Pixel/750 Core/UIWebView NetType/2G Mem/117', 
	'Mozilla/5.0 (Linux; U; Android 4.4.2; zh-cn; HUAWEI C199 Build/HuaweiC199) AppleWebKit/534.24 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.24 T5/2.0 baiduboxapp/6.9.1 (Baidu; P1 4.4.2)', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-cn; Le X620 Build/HEXCNFN5801708221S) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 4.3; zh-CN; SCH-N719 Build/JSS15J) AppleWebKit/533.1 (KHTML, like Gecko) Version/4.0 UCBrowser/9.9.5.489 U3/0.8.0 Mobile Safari/533.1', 
	'Mozilla/5.0 (Linux; U; Android 7.0; zh-cn; MI 5 Build/NRD90M) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.146 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.5.8', 
	'Mozilla/5.0 (iPhone 6; CPU iPhone OS 9_3_2 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Version/6.0 MQQBrowser/6.3 Mobile/13F69 Safari/8536.25', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_3_4 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13G35 baiduboxapp/0_11.0.1.8_enohpi_4331_057/4.3.9_2C2%257enohPi/1099a/59F82D9544E5148BEABAEC021D139750A60B19447FRDBKOKIPL/1', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 baiduboxapp/0_11.0.1.8_enohpi_4331_057/1.1.01_2C2%257enohPi/1099a/6CB513C895DB7CC7ED4D68C22346381C5D3B7D63AFCBASLOSLA/1', 
	'Mozilla/5.0 (Linux; U; Android 5.1.1; zh-cn; MI NOTE Pro Build/LMY47V) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/46.0.2490.85 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.4', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 baiduboxapp/0_11.0.1.8_enohpi_8022_2421/1.1.01_2C2%258enohPi/1099a/B48CB688D97A000A4EAF4B07020F7C58749C7A3BBFCRLQHBLAK/1', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; MI 4LTE Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/46.0.2490.85 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.4', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-cn; PLK-TL01H Build/HONORPLK-TL01H) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/6.0 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; Android 5.1; OPPO R9m Build/LMY47I) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 5.1)', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-cn; MX4 Pro Build/KTU84P) AppleWebKit/533.1 (KHTML, like Gecko)Version/4.0 MQQBrowser/5.4 TBS/025469 Mobile Safari/533.1 MicroMessenger/6.2.0.52_r1162382.561 NetType/WIFI Language/zh_CN QQ/6.6.0.2935', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-CN; HUAWEI MT7-CL00 Build/HuaweiMT7-CL00) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.5.884 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; Android 6.0.1) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/37.0.0.0 Mobile MQQBrowser/6.8 TBS/036887 Safari/537.36 V1_AND_SQ_6.6.0_432_YYB_D QQ/6.6.0.2935 NetType/WIFI WebP/0.3.0 Pixel/1080', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-cn; 1505-A01 Build/MRA58K) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.0 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 baiduboxapp/0_11.0.1.8_enohpi_6311_046/1.1.01_2C2%256enohPi/1099a/5B8948B232A282C658E8A275E25732696F87C379DOCBCKFLCRC/1', 
	'Mozilla/5.0 (Linux; U; Android 5.1.1; zh-CN; HUAWEI M2-A01L Build/HUAWEIM2-A01L) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.5.884 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-cn; HM NOTE 1S Build/KTU84P) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/46.0.2490.85 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.4', 
	'Mozilla/5.0 (Linux; Android 6.0; FRD-AL00 Build/HUAWEIFRD-AL00) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 6.0)', 
	'Mozilla/5.0 (Linux; Android 6.0; PRO 6 Build/MRA58K) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/37.0.0.0 Mobile MQQBrowser/6.8 TBS/036887 Safari/537.36 MicroMessenger/6.3.31.940 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (Linux; Android 4.4.4; iToolsVM Build/KTU84P) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/33.0.0.0 Mobile Safari/537.36 MicroMessenger/6.3.31.940 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_0_2 like Mac OS X) AppleWebKit/602.1.50 (KHTML, like Gecko) Mobile/14A456 MicroMessenger/6.5.1 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; MI 5s Build/MXB48T) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.146 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.6', 
	'Mozilla/5.0 (Linux; Android 6.0; HUAWEI MT7-CL00 Build/HuaweiMT7-CL00; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/54.0.2840.68 Mobile Safari/537.36 baiduboxapp/6.3.1 (Baidu; P1 6.0)', 
	'Mozilla/5.0 (Linux; Android 6.0; HUAWEI MT7-TL10 Build/HuaweiMT7-TL10) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/6.3 baiduboxapp/7.2 (Baidu; P1 6.0)', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-cn; EVA-AL10 Build/HUAWEIEVA-AL10) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.0 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; Android 6.0; HUAWEI CRR-UL00 Build/HUAWEICRR-UL00) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 6.0)', 
	'Mozilla/5.0 (Linux; Android 6.0; HUAWEI GRA-TL00 Build/HUAWEIGRA-TL00) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 6.0)', 
	'Mozilla/5.0 (Linux; U; Android 5.1.1; zh-cn; Redmi Note 3 Build/LMY47V) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.146 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.6', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-tw; MI NOTE LTE Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/46.0.2490.85 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.4', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 MicroMessenger/6.3.31 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 MicroMessenger/6.5.1 NetType/4G Language/zh_CN', 
	'Mozilla/5.0 (Linux; Android 4.4.2; Che2-TL00 Build/HonorChe2-TL00) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/30.0.0.0 Mobile Safari/537.36 baidubrowser/4.0.18.7 (Baidu; P1 4.4.2)', 
	'Mozilla/5.0 (iPhone 6; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Version/10.0 MQQBrowser/7.1 Mobile/14B100 Safari/8536.25 MttCustomUA/2', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-CN; MI 5 Build/MRA58K) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 UCBrowser/11.0.0.818 U3/0.8.0 Mobile Safari/534.30', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-CN; SM-G9350 Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.5.884 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_1 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13B143 baiduboxapp/0_9.1.0.8_enohpi_4331_057/1.9_2C2%257enohPi/1099a/756767DF0D52EA9AC7FAD5F6CB8569A51169AD34FFRQMQOMOPL/1', 
	'Mozilla/5.0 (Linux; Android 5.1.1; SM-J3119 Build/LMY47X) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.1 rabbit/1.0 baiduboxapp/7.5.1 (Baidu; P1 5.1.1)', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 baiduboxapp/0_11.0.1.8_enohpi_4331_057/1.1.01_2C2%257enohPi/1099a/2C1ED716FFB303A6EE0BC907FCB29AB76A5F9CC2CORHORADLFG/1', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_0_2 like Mac OS X) AppleWebKit/602.1.50 (KHTML, like Gecko) Mobile/14A456 baiduboxapp/0_11.0.1.8_enohpi_8022_2421/2.0.01_2C2%258enohPi/1099a/88D9A3B372D39F0C64AA8F4E99D056B33FF34092COCCJFJKBJL/1', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-cn; FRD-AL00 Build/HUAWEIFRD-AL00) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/6.0 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-CN; N5209 Build/KTU84P) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 UCBrowser/10.10.0.800 U3/0.8.0 Mobile Safari/534.30', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 baiduboxapp/0_11.0.1.8_enohpi_8022_2421/1.1.01_1C2%257enohPi/1099a/752A993C0AEC43B6407895135DB16B54CF97E7CA0OCQHDDTBHR/1', 
	'Mozilla/5.0 (iPhone 6p; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Version/10.0 MQQBrowser/7.1.1 Mobile/14B100 Safari/8536.25 MttCustomUA/2', 
	'Mozilla/5.0 (Linux; U; Android 5.1.1; zh-cn; vivo X7Plus Build/LMY47V) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-CN; MI NOTE LTE Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.5.884 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 baiduboxapp/0_11.0.1.8_enohpi_1002_5211/1.1.01_1C2%257enohPi/1099a/F05ABD424D307E0FFB1E50CF5370E081E85EAA1DCOCGCMHQEJF/1', 
	'Mozilla/5.0 (Linux; U; Android 5.1; zh-CN; P01 Build/LMY47D) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 UCBrowser/11.0.4.846 U3/0.8.0 Mobile Safari/534.30', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 baiduboxapp/0_11.0.1.8_enohpi_1002_5211/1.1.01_2C2%259enohPi/1099a/D9E41401243D2BF49B3F1025023FB28BE2B1806FAFCTELCAFAM/1', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-cn; SM-G8508S Build/KTU84P) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.0 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-tw; 3007 Build/KTU84P) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.0 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B72 search%2F1.0 baiduboxapp/0_0.0.1.7_enohpi_4331_057/1.01_2C2%257enohPi/1099a/6C098F1CCE0764F9FA70F99DA9974B9B200A469E0FCHCTFCNPL/1', 
	'Mozilla/5.0 (Linux; Android 6.0.1; SM-A9000 Build/MMB29M; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/49.0.2623.105 Mobile Safari/537.36 rabbit/1.0 baiduboxapp/7.1 (Baidu; P1 6.0.1)', 
	'Mozilla/5.0 (Linux; Android 5.0.1; M355 Build/LRX22C) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 5.0.1)', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_0_1 like Mac OS X) AppleWebKit/602.1.50 (KHTML, like Gecko) Mobile/14A403 baiduboxapp/0_11.0.1.8_enohpi_8022_2421/1.0.01_1C2%257enohPi/1099a/335E9AB11CE04E10F6A72096F5FDBB5A7636DC06AFCBDJDKRDF/1', 
	'Mozilla/5.0 (Linux; Android 6.0; PRO 6 Build/MRA58K) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 6.0)', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-cn; HM NOTE 1LTE Build/KTU84P) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/46.0.2490.85 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.1.4', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; Redmi 3S Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/46.0.2490.85 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.4', 
	'Mozilla/5.0 (Linux; U; Android 5.1.1; zh-CN; R7Plusm Build/LMY47V) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.5.884 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 5.0.2; zh-CN; ZTE A2015 Build/LRX22G) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 UCBrowser/10.5.2.598 U3/0.8.0 Mobile Safari/534.30', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 baiduboxapp/0_11.0.1.8_enohpi_4331_057/1.1.01_2C2%257enohPi/1099a/8FE439171945D5357F343E920EC24A8EC36B102F6ORTOHTRBNQ/1', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_0_2 like Mac OS X) AppleWebKit/602.1.50 (KHTML, like Gecko) Mobile/14A456 MicroMessenger/6.3.31 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_3_5 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13G36 MicroMessenger/6.3.31 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-cn; VIE-AL10 Build/HUAWEIVIE-AL10) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; MI 4LTE Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.146 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.6', 
	'Mozilla/5.0 (Linux; U; Android 7.0; zh-cn; HUAWEI NXT-AL10 Build/HUAWEINXT-AL10) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-CN; OPPO R9s Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.5.884 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_2 like Mac OS X) AppleWebKit/602.3.12 (KHTML, like Gecko) Mobile/14C92 baiduboxapp/0_9.1.0.8_enohpi_8022_2421/2.01_2C2%259enohPi/1099a/7BFBC8133E01585727F0D0DAEA85ECB05BBDA3239FCLBEQODGS/1', 
	'Mozilla/5.0 (Linux; U; Android Marshmallow 6.0; zh-cn; LG-D857 Build/MRA58K) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/6.3 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone 92; CPU iPhone OS 10_2 like Mac OS X) AppleWebKit/602.3.12 (KHTML, like Gecko) Version/10.0 MQQBrowser/7.1.1 Mobile/14C92 Safari/8536.25 MttCustomUA/2', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B72 rabbit%2F1.0 baiduboxapp/0_0.0.1.7_enohpi_4331_057/1.01_2C2%257enohPi/1099a/6C098F1CCE0764F9FA70F99DA9974B9B200A469E0FCHCTFCNPL/1', 
	'Mozilla/5.0 (Linux; Android 5.0.2; SM-A5000 Build/LRX22G; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/45.0.2454.95 Mobile Safari/537.36 baiduboxapp/6.3.1 (Baidu; P1 5.0.2)', 
	'Mozilla/5.0 (Linux; Android 6.0; HUAWEI NXT-TL00 Build/HUAWEINXT-TL00) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.1 baiduboxapp/8.0 (Baidu; P1 6.0)', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_3_3 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13G34 baiduboxapp/0_0.2.0.6_enohpi_8022_2421/3.3.9_1C2%257enohPi/1099a/C4E5EC24B39915CE768255A294BBD6CCC1C0D066BOROAORHNQB/1', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-cn; MI 5 Build/MRA58K) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/46.0.2490.85 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.2.10', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-cn; H2 Build/KTU84P) AppleWebKit/534.24 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.24 T5/2.0 baidubrowser/5.6.4.7 (Baidu; P1 4.4.4)', 
	'Mozilla/5.0 (Linux; Android 6.0; HUAWEI NXT-AL10 Build/HUAWEINXT-AL10) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 6.0)', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-cn; Redmi Note 4 Build/MRA58K) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.146 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.6', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-CN; HUAWEI NXT-AL10 Build/HUAWEINXT-AL10) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.5.884 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_3_3 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13G34 search%2F1.0 baiduboxapp/0_7.0.5.7_enohpi_4331_057/3.3.9_1C2%258enohPi/1099a/591F7EA5466A5F2BD0F1944370B33E9FCF294080CORCCADISSI/1', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-cn; CAM-AL00 Build/HONORCAM-AL00) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.0 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B72 MicroMessenger/6.3.31 NetType/4G Language/zh_CN', 
	'Mozilla/5.0 (Linux; U; Android 5.1.1; zh-cn; SM-J5108 Build/LMY47X) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 5.1; zh-cn; m1 metal Build/LMY47I) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 4.4.2; zh-CN; Coolpad 8297W Build/KOT49H) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.5.884 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_3_2 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13F69 baiduboxapp/0_11.0.1.8_enohpi_4331_057/2.3.9_1C2%258enohPi/1099a/75E19099B81694E3716130D650008D6953AD6FA6BOCRKRCHBIS/1', 
	'Mozilla/5.0 (iPhone 6p; CPU iPhone OS 9_2_1 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Version/9.0 MQQBrowser/7.1.1 Mobile/13D15 Safari/8536.25 MttCustomUA/2', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 8_1_1 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Mobile/12B435 baiduboxapp/0_11.0.1.8_enohpi_6311_046/1.1.8_2C2%256enohPi/1099a/B1462749FF0C14103293010233DFF116329A79106FCFHIOKAAO/1', 
	'Mozilla/5.0 (Linux; Android 5.0.2; PLK-AL10 Build/HONORPLK-AL10) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/37.0.0.0 Mobile MQQBrowser/6.8 TBS/036887 Safari/537.36 MicroMessenger/6.3.32.960 NetType/4G Language/zh_CN', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-CN; SM-C7000 Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.5.884 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-CN; MI 5s Build/MXB48T) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.5.884 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; Android 5.1; HUAWEI TAG-AL00 Build/HUAWEITAG-AL00) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 5.1)', 
	'Mozilla/5.0 (Linux; U; Android 4.2.1; zh-cn; 2013022 Build/HM2013022) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30 XiaoMi/MiuiBrowser/1.0', 
	'Mozilla/5.0 (Linux; Android 6.0; HUAWEI CRR-UL00 Build/HUAWEICRR-UL00) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/6.3 rabbit/1.0 baiduboxapp/7.3.1 (Baidu; P1 6.0)', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-CN; MI 3W Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.5.884 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; Android 5.0.2; vivo X6Plus A Build/LRX22G) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.1 baiduboxapp/8.0 (Baidu; P1 5.0.2)', 
	'Mozilla/5.0 (iPhone 5SGLOBAL; CPU iPhone OS 9_3_5 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Version/6.0 MQQBrowser/6.1.1 Mobile/13G36 Safari/8536.25', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; ZTE B2015 Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/6.0 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_0_1 like Mac OS X) AppleWebKit/602.1.50 (KHTML, like Gecko) Mobile/14A403 baiduboxapp/0_11.0.1.8_enohpi_8022_2421/1.0.01_1C2%257enohPi/1099a/18AD075E3CBD0462C9617711F06F0DC478A60A43CORGEOCQSTA/1', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_2 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13C75 search%2F1.0 baiduboxapp/0_2.0.4.7_enohpi_4331_057/2.9_2C2%257enohPi/1099a/8B57FF7B17EC30BCA1645DDEE6A9FA55F2533EC77FRRTATLJPT/1', 
	'Mozilla/5.0 (Linux; Android 4.4.4; R8207 Build/KTU84P) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/37.0.0.0 Mobile MQQBrowser/6.8 TBS/036887 Safari/537.36 MicroMessenger/6.3.32.960 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (Linux; U; Android 4.4.2; zh-CN; H60-L01 Build/HDH60-L01) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.5.884 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 7.0; zh-CN; HUAWEI NXT-DL00 Build/HUAWEINXT-DL00) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.8.885 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 5.1.1; zh-cn; MI NOTE Pro Build/LMY47V) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/46.0.2490.85 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.2.15', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_0_2 like Mac OS X) AppleWebKit/602.1.50 (KHTML, like Gecko) Mobile/14A456 MicroMessenger/6.3.31 NetType/4G Language/zh_CN', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; Redmi 4 Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.146 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.6', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_2 like Mac OS X) AppleWebKit/602.3.12 (KHTML, like Gecko) Mobile/14C92 baiduboxapp/0_11.0.1.8_enohpi_4331_057/2.01_2C2%257enohPi/1099a/123DE89DA7B2F985D5B30E4BB97D464839D5888EFFRQLCHEMJA/1', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; Mi Note 2 Build/MXB48T) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.146 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.6', 
	'Mozilla/5.0 (Linux; U; Android 5.0.2; zh-cn; Redmi Note 3 Build/LRX22G) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; MI 5 Build/MXB48T) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.146 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.6', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-CN; ATH-AL00 Build/HONORATH-AL00) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.1.888 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 5.1.1; zh-cn; H60-L03 Build/HDH60-L03) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B72 baiduboxapp/0_0.0.1.7_enohpi_4331_057/1.01_2C2%257enohPi/1099a/6C098F1CCE0764F9FA70F99DA9974B9B200A469E0FCHCTFCNPL/1', 
	'Mozilla/5.0 (Linux; U; Android 5.1.1; zh-CN; Redmi Note 3 Build/LMY47V) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.1.888 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 baiduboxapp/0_11.0.1.8_enohpi_1002_5211/1.1.01_2C2%259enohPi/1099a/F43FDC43F8C35D60A7CA4FCB5C46D81F2B32273D4OCIKSQKFGF/1', 
	'Mozilla/5.0 (Linux; U; Android 5.1.1; zh-CN; Mi-4c Build/LMY47V) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.5.884 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone 6; CPU iPhone OS 10_2 like Mac OS X) AppleWebKit/602.3.12 (KHTML, like Gecko) Version/10.0 MQQBrowser/7.1.1 Mobile/14C92 Safari/8536.25 MttCustomUA/2', 
	'Mozilla/5.0 (iPhone 6p; CPU iPhone OS 10_2 like Mac OS X) AppleWebKit/602.3.12 (KHTML, like Gecko) Version/10.0 MQQBrowser/7.1.1 Mobile/14C92 Safari/8536.25 MttCustomUA/2', 
	'Mozilla/5.0 (Linux; U; Android 4.4.2; zh-cn; CHM-TL00H Build/HonorCHM-TL00H) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 MQQBrowser/5.3 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 5.0; zh-cn; vivo X5Pro D Build/LRX21M) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 4.4.2; zh-cn; 2014011 Build/HM2014011) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.146 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.6', 
	'Mozilla/5.0 (Linux; U; Android 5.1; zh-CN; MX5 Build/LMY47I) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.0.880 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 baiduboxapp/0_11.0.1.8_enohpi_1002_5211/1.1.01_2C2%259enohPi/1099a/92C8BA18492BB3828CC4EAC668B57F226E53C75A0FCLKEASDJI/1', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 baiduboxapp/0_11.0.1.8_enohpi_4331_057/1.1.01_1C2%258enohPi/1099a/7120825E4587BDA5841C4BCB46FD17F28960A9B7CORMBPONISH/1', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_2 like Mac OS X) AppleWebKit/602.3.12 (KHTML, like Gecko) Mobile/14C92 MicroMessenger/6.5.1 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (Linux; Android 6.0.1; C106-6 Build/ZOXCNFN5801710251S) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 6.0.1)', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 8_4 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Mobile/12H143 baiduboxapp/0_11.0.1.8_enohpi_8022_2421/4.8_1C2%257enohPi/1099a/2B2EE77DD24DF84D74B6A0FE95860D3FCCEEC6931FCCRRBETHP/1', 
	'Mozilla/5.0 (Linux; U; Android 4.4.2; zh-cn; PE-TL20 Build/HuaweiPE-TL20) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.0 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; MI NOTE LTE Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.146 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.6', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 baiduboxapp/0_11.0.1.8_enohpi_8022_2421/1.1.01_1C2%257enohPi/1099a/6417E5B84CE6F787C41B42AB1485E3FD82A305451FCNFGHEJOQ/1', 
	'Mozilla/5.0 (iPhone 6; CPU iPhone OS 9_3_1 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Version/9.0 MQQBrowser/7.1.1 Mobile/13E238 Safari/8536.25 MttCustomUA/2', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_3_5 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13G36 MicroMessenger/6.3.31 NetType/4G Language/en', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_3_4 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13G35 baiduboxapp/0_11.0.1.8_enohpi_6311_046/4.3.9_1C2%258enohPi/1099a/3D17F7183A02694CDFB8EAD47ACE34ADFCABE5C4CFCRMPJCNIT/1', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_0_2 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13A452 MicroMessenger/6.5.1 NetType/4G Language/zh_HK', 
	'Mozilla/5.0 (iPhone 6; CPU iPhone OS 9_3_4 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Version/9.0 MQQBrowser/7.1.1 Mobile/13G35 Safari/8536.25 MttCustomUA/2', 
	'Mozilla/5.0 (Linux; Android 5.0.2; CHE-TL00H Build/HonorCHE-TL00H) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 5.0.2)', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 baiduboxapp/0_11.0.1.8_enohpi_6311_046/1.1.01_4C2%258enohPi/1099a/FA2F975DEDF8C4854AD1FA83AE17405D77A668812OCMKCLFACM/1', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-cn; 2014812 Build/KTU84P) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.146 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.6', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_0_2 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13A452 MicroMessenger/6.5.1 NetType/WIFI Language/zh_HK', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_0_2 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13A452 MicroMessenger/6.5.2 NetType/WIFI Language/zh_HK', 
	'Mozilla/5.0 (Linux; U; Android 5.1.1; zh-cn; Mi-4c Build/LMY47V) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.146 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.6', 
	'Mozilla/5.0 (Linux; Android 6.0; PLK-TL01H Build/HONORPLK-TL01H) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 6.0)', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_2_1 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13D15 baiduboxapp/0_11.0.1.8_enohpi_8022_2421/1.2.9_2C2%258enohPi/1099a/5FFD596738FD9AFC3C7CBF5306823B976AAD62255FCCIOMGABP/1', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_3_5 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13G36 baiduboxapp/0_11.0.1.8_enohpi_6311_046/5.3.9_1C2%258enohPi/1099a/C9862C9728FE44B7E7F67206DD31DF71E464A2D3DFRMAGIFCCE/1', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_3_5 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13G36 baiduboxapp/0_11.0.1.8_enohpi_4331_057/5.3.9_2C2%257enohPi/1099a/97829D6966BEDAFF982333CCA59C711CB1365693CFCMIIFKHSC/1', 
	'Mozilla/5.0 (Linux; U; Android 7.0; zh-CN; HUAWEI NXT-AL10 Build/HUAWEINXT-AL10) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.5.884 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone 6p; CPU iPhone OS 10_2 like Mac OS X) AppleWebKit/602.3.12 (KHTML, like Gecko) Version/10.0 MQQBrowser/7.1.1 Mobile/14C92 Safari/8536.25 MttCustomUA/2 QBWebViewType/1', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-cn; HUAWEI NXT-AL10 Build/HUAWEINXT-AL10) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 7_1_1 like Mac OS X) AppleWebKit/537.51.2 (KHTML, like Gecko) Mobile/11D201 MicroMessenger/6.5.1 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-CN; KIW-AL10 Build/HONORKIW-AL10) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.5.884 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; Android 6.0.1; SM-A9100 Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/37.0.0.0 Mobile MQQBrowser/6.8 TBS/036887 Safari/537.36 MicroMessenger/6.3.31.940 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-CN; SM-G9300 Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.5.884 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 4.3; zh-CN; SCH-N719 Build/JSS15J) AppleWebKit/533.1 (KHTML, like Gecko) Version/4.0 UCBrowser/9.9.5.489 U3/0.8.0 Mobile Safari/533.1', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; MI MAX Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.146 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.6', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-CN; KNT-AL20 Build/HUAWEIKNT-AL20) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.8.885 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_3_5 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13G36 search%2F1.0 baiduboxapp/0_0.0.3.7_enohpi_8022_2421/5.3.9_1C2%257enohPi/1099a/9505E9159CC43BA967F76982E26CFC3489DF3D7E9ORDOACSBGC/1', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 baiduboxapp/0_11.0.1.8_enohpi_8022_2421/1.1.01_2C2%259enohPi/1099a/9986F0DD6A3045728A5362A8D3F0494565FA71F98OCTFNGQADF/1', 
	'Mozilla/5.0 (Linux; U; Android 5.1.1; zh-CN; HUAWEI P7-L09 Build/HuaweiP7-L09) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.8.885 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-CN; Redmi Note 4 Build/MRA58K) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.5.884 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 5.0; zh-cn; SM-N9008S Build/LRX21V) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.0 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 MicroMessenger/6.3.6 NetType/3G+ Language/zh_CN', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; SM-N9200 Build/MMB29K) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-CN; H60-L02 Build/HDH60-L02) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 UCBrowser/11.0.0.818 U3/0.8.0 Mobile Safari/534.30', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_3_5 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13G36 baiduboxapp/0_9.1.0.8_enohpi_4331_057/5.3.9_2C2%257enohPi/1099a/EC4D10A669EDC181E9000FFA5623373A2F05EDDACORHRDOOCMB/1', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; HUAWEI RIO-TL00 Build/HuaweiRIO-TL00) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; Android 6.0.1; Redmi 4A Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/37.0.0.0 Mobile MQQBrowser/6.8 TBS/036887 Safari/537.36 V1_AND_SQ_6.6.2_450_YYB_D QQ/6.6.2.2980 NetType/WIFI WebP/0.3.0 Pixel/720', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-cn; HUAWEI CRR-CL00 Build/HUAWEICRR-CL00) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_3_2 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13F69 MicroMessenger/6.3.29 NetType/4G Language/zh_CN', 
	'Mozilla/5.0 (Linux; Android 4.4.2; H60-L02 Build/HDH60-L02) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/37.0.0.0 Mobile MQQBrowser/6.8 TBS/036887 Safari/537.36 V1_AND_SQ_6.5.8_422_YYB_D QQ/6.5.8.2910 NetType/WIFI WebP/0.3.0 Pixel/1080', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-CN; EVA-AL00 Build/HUAWEIEVA-AL00) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.8.885 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; ONEPLUS A3000 Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/6.0 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone 6s; CPU iPhone OS 9_2 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Version/9.0 MQQBrowser/7.1.1 Mobile/13C75 Safari/8536.25 MttCustomUA/2', 
	'Mozilla/5.0 (Linux; U; Android 5.1.1; zh-cn; YQ601 Build/LMY47V) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/6.8 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-cn; FRD-AL10 Build/HUAWEIFRD-AL10) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/6.0 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; Android 4.3; GT-I9152P Build/JLS36C; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/48.0.2564.116 Mobile Safari/537.36 baidubrowser/7.7.13.0 (Baidu; P1 4.3)', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_2 like Mac OS X) AppleWebKit/602.3.12 (KHTML, like Gecko) Mobile/14C92 baiduboxapp/0_11.0.1.8_enohpi_4331_057/2.01_2C2%257enohPi/1099a/82EE4425D6A12D1D196B3BB4E5850821E99EF4152FCNHSBNLGB/1', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; MI NOTE LTE Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_0_2 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13A452 MicroMessenger/6.5.2 NetType/4G Language/zh_HK', 
	'Mozilla/5.0 (Linux; U; Android 5.1.1; zh-CN; MI NOTE Pro Build/LMY47V) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.8.885 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 4.4.2; zh-cn; PE-TL10 Build/HuaweiPE-TL10) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 MQQBrowser/5.3 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_2 like Mac OS X) AppleWebKit/602.3.12 (KHTML, like Gecko) Mobile/14C92 baiduboxapp/0_7.0.2.8_enohpi_1002_5211/2.01_1C2%257enohPi/1099a/703456D6EEFD5453516573CC3C67C372D33B8DBFDOCBCCOJMFB/1', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 8_1_3 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Mobile/12B466 search%2F1.0 baiduboxapp/0_0.0.3.7_enohpi_6311_046/3.1.8_2C2%256enohPi/1099a/E530FD26DEC287B026607DD3984204F61CF9E3C63ONKJQFFGFA/1', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_3_5 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13G36 baiduboxapp/0_9.1.0.8_enohpi_6311_046/5.3.9_2C2%256enohPi/1099a/9C76F9B6AF590DDDC17ECBA62C5392F7E342C6279ORIKHNDSKI/1', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 MicroMessenger/6.5.2 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (Linux; Android 5.1; OPPO R9tm Build/LMY47I) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/37.0.0.0 Mobile MQQBrowser/6.8 TBS/036887 Safari/537.36 MicroMessenger/6.3.32.960 NetType/4G Language/zh_CN', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_3_2 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13F69 MicroMessenger/6.5.2 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_2 like Mac OS X) AppleWebKit/602.3.12 (KHTML, like Gecko) Mobile/14C92 MicroMessenger/6.5.2 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (Linux; Android 5.1; OPPO R9m Build/LMY47I) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/37.0.0.0 Mobile MQQBrowser/6.8 TBS/036887 Safari/537.36 MicroMessenger/6.3.32.960 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_2 like Mac OS X) AppleWebKit/602.3.12 (KHTML, like Gecko) Mobile/14C92 MicroMessenger/6.5.2 NetType/4G Language/zh_CN', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_3_2 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13F69 MicroMessenger/6.5.2 NetType/4G Language/zh_CN', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_3_5 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13G36 MicroMessenger/6.5.2 NetType/2G Language/zh_CN', 
	'Mozilla/5.0 (iPhone 6s; CPU iPhone OS 10_2 like Mac OS X) AppleWebKit/602.3.12 (KHTML, like Gecko) Version/10.0 MQQBrowser/7.1.1 Mobile/14C92 Safari/8536.25 MttCustomUA/2', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 8_2 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Mobile/12D508 MicroMessenger/6.5.2 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (Linux; Android 4.4.4; HUAWEI C8818 Build/HuaweiC8818) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/37.0.0.0 Mobile MQQBrowser/6.8 TBS/036887 Safari/537.36 MicroMessenger/6.3.31.940 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (Linux; U; Android 5.1.1; zh-CN; YQ601 Build/LMY47V) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 UCBrowser/10.9.3.727 U3/0.8.0 Mobile Safari/534.30', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 baiduboxapp/0_9.1.0.8_enohpi_6311_046/1.1.01_2C2%257enohPi/1099a/6502BC3980350DAD660746C937376C109750F0D6CFRFIBJHJHT/1', 
	'Mozilla/5.0 (Linux; U; Android 5.1.1; zh-cn; NX511J Build/LMY47V) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 5.0.2; zh-CN; PLK-AL10 Build/HONORPLK-AL10) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 UCBrowser/11.1.5.871 U3/0.8.0 Mobile Safari/534.30', 
	'Mozilla/5.0 (Linux; U; Android 5.1.1; zh-cn; MI NOTE Pro Build/LMY47V) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.146 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.6', 
	'Mozilla/5.0 (Linux; Android 6.0; PE-TL10 Build/HuaweiPE-TL10) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 6.0)', 
	'Mozilla/5.0 (Linux; Android 5.1.1; vivo X7 Build/LMY47V) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 5.1.1)', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 baiduboxapp/0_7.0.2.8_enohpi_4331_057/1.1.01_2C2%257enohPi/1099a/0F29982BEFA84B843587AA62BE5DF0918A12CFC1AFCAPCKHJTK/1', 
	'Mozilla/5.0 (Linux; U; Android 5.1.1; zh-CN; CHM-TL00H Build/HonorCHM-TL00H) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.8.885 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_2 like Mac OS X) AppleWebKit/602.3.12 (KHTML, like Gecko) Mobile/14C92 baiduboxapp/0_7.0.2.8_enohpi_4331_057/2.01_1C2%258enohPi/1099a/95841D7D6A8609B59D7B81396543FB72A3850F2A3OCCNMBIAGJ/1', 
	'Mozilla/5.0 (Linux; Android 5.1.1; OPPO A33 Build/LMY47V) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 5.1.1)', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-CN; MI 4LTE Build/NDE63X) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.5.884 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 baiduboxapp/0_7.0.2.8_enohpi_8022_2421/1.1.01_1C2%257enohPi/1099a/91F2B64962AE6CF53AC95F7F142D7C72F03EEF42BFCDIJRPHQQ/1', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; Le X820 Build/FEXCNFN5902012151S) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-CN; GEM-703LT Build/HUAWEIGEM-703LT) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 UCBrowser/11.1.0.870 U3/0.8.0 Mobile Safari/534.30', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; Redmi 4A Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.146 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.6', 
	'Mozilla/5.0 (Linux; U; Android 5.1.1; zh-cn; vivo X7 Build/LMY47V) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.0 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 5.1; zh-cn; m3 note Build/LMY47I) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; Android 5.1; OPPO R9tm Build/LMY47I) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 5.1)', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; MI MAX Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_2 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13C75 MicroMessenger/6.3.31 NetType/4G Language/zh_CN', 
	'Mozilla/5.0 (Linux; U; Android 4.4.2; zh-cn; PE-CL00 Build/HuaweiPE-CL00) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; Android 6.0; HUAWEI NXT-AL10 Build/HUAWEINXT-AL10) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/6.3 rabbit/1.0 baiduboxapp/7.4 (Baidu; P1 6.0)', 
	'Xiaomi_2016035_TD-LTE/V1 Linux/3.18.20 Android/6.0 Release/5.5.2016 Browser/AppleWebKit537.36 Mobile Safari/537.36 System/Android 6.0 XiaoMi/MiuiBrowser/2.4.9', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; MI 5s Build/MXB48T) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (Symbian/3; Android 7.1 MI 4LTE Build/NDE63X; ) AppleWebKit/537.36 (KHTML, like Gecko) UCBrowser/10.9.2.712 U3/0.8.0 Mobile Safari/534.30', 
	'Mozilla/5.0 (Linux; Series60/5.0; Android 7.1; MI 4LTE Build/NDE63X; ) AppleWebKit/537.36 (KHTML, like Gecko) UCBrowser/10.9.2.712 U3/0.8.0 Mobile Safari/534.30', 
	'Mozilla/5.0 (Linux; Android 6.0.1; MI 4LTE Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 6.0.1)', 
	'Mozilla/5.0 (Linux; U; Android 5.1; zh-cn; ZTE C880U Build/LMY47D) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.2 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 5_1 like Mac OS X) AppleWebKit/534.46 (KHTML, like Gecko) Mobile/9B176 MicroMessenger/4.3.2', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-cn; MI 3 Build/KTU84P) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.146 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.6', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_2 like Mac OS X) AppleWebKit/602.3.12 (KHTML, like Gecko) Mobile/14C92 baiduboxapp/0_7.0.2.8_enohpi_4331_057/2.01_1C2%258enohPi/1099a/163E5BBDF16859FE12FDF6C994E30DC7F2AA87EC3OCBFGJPKGT/1', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-cn; 2014813 Build/KTU84P) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 5.0.1; zh-CN; SCH-I959 Build/LRX22C) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.5.884 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-cn; Redmi Pro Build/MRA58K) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.146 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.6', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-cn; HUAWEI MT7-TL10 Build/HuaweiMT7-TL10) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; Android 6.0.1; KIW-AL10 Build/HONORKIW-AL10; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/49.0.2623.105 Mobile Safari/537.36 baiduboxapp/6.9.6 (Baidu; P1 6.0.1)', 
	'Mozilla/5.0 (iPhone 6sp; CPU iPhone OS 10_2 like Mac OS X) AppleWebKit/602.3.12 (KHTML, like Gecko) Version/10.0 MQQBrowser/7.2 Mobile/14C92 Safari/8536.25 MttCustomUA/2 QBWebViewType/1', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-CN; SM-G9350 Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.8.885 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 4.4.2; zh-cn; HUAWEI MT7-CL00 Build/HuaweiMT7-CL00) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/6.6 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 8_4 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Mobile/12H143 baiduboxapp/0_7.0.2.8_enohpi_6311_046/4.8_2C2%256enohPi/1099a/E007DEB9794F7FCBB43E43D7EFB059F85C239B189FNKSKBOPHL/1', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 8_4_1 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Mobile/12H321 MicroMessenger/6.3.31 NetType/4G Language/zh_CN', 
	'Mozilla/5.0 (Linux; Android 6.0.1; MI 5 Build/MXB48T) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.1 baiduboxapp/8.0 (Baidu; P1 6.0.1)', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-CN; Letv X500 Build/DBXCNOP5801810092S) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.1.888 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_2_1 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13D15 baiduboxapp/0_7.0.2.8_enohpi_1002_5211/1.2.9_2C2%258enohPi/1099a/388CCD633C1096CF05F8913A5A24700BA7650CA09ORMTECSGGJ/1', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_2 like Mac OS X) AppleWebKit/602.3.12 (KHTML, like Gecko) Mobile/14C92 baiduboxapp/0_7.0.2.8_enohpi_6311_046/2.01_1C2%258enohPi/1099a/C15E908D582704314E1D3DE6D0903738251339373OCBBBSNLTH/1', 
	'Mozilla/5.0 (Linux; Android 6.0; PE-TL00M Build/HuaweiPE-TL00M) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 6.0)', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-CN; HUAWEI CRR-UL00 Build/HUAWEICRR-UL00) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.8.885 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 5.0.2; zh-cn; Redmi Note 2 Build/LRX22G) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-CN; Redmi 3S Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.5.884 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; Android 7.0; MHA-AL00 Build/HUAWEIMHA-AL00) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 7.0)', 
	'Mozilla/5.0 (Linux; Android 4.4.4; R8207 Build/KTU84P) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.1 baiduboxapp/8.0 (Baidu; P1 4.4.4)', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-cn; NEM-AL10 Build/HONORNEM-AL10) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; Android 5.1.1; OPPO R9 Plustm A Build/LMY47V) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 5.1.1)', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_3_5 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13G36 baiduboxapp/0_7.0.2.8_enohpi_8022_2421/5.3.9_1C2%257enohPi/1099a/B0CED66676D177D648612EB26EEBF26B46D2B3CC8FCRBALOQFP/1', 
	'Mozilla/5.0 (Linux; U; Android 5.0.2; zh-cn; Redmi Note 2 Build/LRX22G) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/6.8 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 baiduboxapp/0_7.0.2.8_enohpi_1002_5211/1.1.01_2C2%259enohPi/1099a/F43FDC43F8C35D60A7CA4FCB5C46D81F2B32273D4OCIKSQKFGF/1', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_1 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13B143 MicroMessenger/6.3.13 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_3_5 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13G36 baiduboxapp/0_7.0.2.8_enohpi_1002_5211/5.3.9_1C2%257enohPi/1099a/2CAF8EF6F7377A9D9A1A2BF9BC3DEA9861789D59CFCSKHNDCPT/1', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_3_5 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13G36 baiduboxapp/0_7.0.2.8_enohpi_8022_2421/5.3.9_2C2%258enohPi/1099a/2C8C0E4C39FC33E9F7E4666C1CAE681E8A72A0928FCBOROQRST/1', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 8_1_1 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Mobile/12B435 search%2F1.0 baiduboxapp/0_21.0.6.7_enohpi_6311_046/1.1.8_2C2%256enohPi/1099a/5B95D2B0485C4012AFC1A141F60C008D3E9F27053FRDAOGNOKS/1', 
	'Mozilla/5.0 (Linux; Android 6.0; HUAWEI NXT-AL10 Build/HUAWEINXT-AL10; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/49.0.2623.105 Mobile Safari/537.36 baiduboxapp/5.0 (Baidu; P1 6.0)', 
	'Mozilla/5.0 (Linux; U; Android 4.2.1; zh-cn; M040 Build/JOP40D) AppleWebKit/534.24 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.24 T5/2.0 baidubrowser/4.3.16.2 (Baidu; P1 4.2.1)', 
	'Mozilla/5.0 (Linux; U; Android 4.2.2; zh-cn; GT-I9505 Build/JDQ39) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_2 like Mac OS X) AppleWebKit/602.3.12 (KHTML, like Gecko) Mobile/14C92 search%2F1.0 baiduboxapp/0_0.0.1.7_enohpi_6311_046/2.01_2C2%256enohPi/1099a/0D7200A1DC5F5CBE3B8DCABCC30D14D367AB10E24FRFEKQOTCN/1', 
	'Mozilla/5.0 (Linux; Android 5.1.1; vivo X6S A Build/LMY47V) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 5.1.1)', 
	'Mozilla/5.0 (Linux; Android 5.0.2; Redmi Note 3 Build/LRX22G) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 5.0.2)', 
	'Mozilla/5.0 (Linux; Android 5.1.1; MX4 Pro Build/LMY48W) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 5.1.1)', 
	'Mozilla/5.0 (Linux; Android 5.1.1; SM801 Build/LMY47V) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/37.0.0.0 Mobile MQQBrowser/6.8 TBS/036887 Safari/537.36 V1_AND_SQ_6.6.1_442_YYB_D QQ/6.6.1.2960 NetType/2G WebP/0.3.0 Pixel/1080', 
	'Mozilla/5.0 (Linux; Android 5.0.2; vivo Y51 Build/LRX22G) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 5.0.2)', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-CN; HUAWEI MT7-CL00 Build/HuaweiMT7-CL00) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.8.885 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; Android 5.1; HUAWEI TIT-TL00 Build/HUAWEITIT-TL00) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.1 baiduboxapp/8.0 (Baidu; P1 5.1)', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-CN; SM-N9200 Build/MMB29K) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 UCBrowser/11.0.8.858 U3/0.8.0 Mobile Safari/534.30', 
	'Mozilla/5.0 (Linux; Android 5.0; vivo X5Pro D Build/LRX21M) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 5.0)', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; MI 4LTE Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.2 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 5.1.1; zh-CN; ZUK Z1 Build/LMY47V) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 UCBrowser/11.0.4.846 U3/0.8.0 Mobile Safari/534.30', 
	'Mozilla/5.0 (iPhone 6s; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Version/10.0 MQQBrowser/7.0.1 Mobile/14B100 Safari/8536.25 MttCustomUA/2', 
	'Mozilla/5.0 (Linux; Android 6.0.1; MIX Build/MXB48T) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 6.0.1)', 
	'Mozilla/5.0 (Linux; U; Android 5.1; zh-cn; MX5 Build/LMY47I) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-cn; HUAWEI MT7-TL10 Build/HuaweiMT7-TL10) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0   MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 5.0.2; zh-CN; vivo X6A Build/LRX22G) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.8.885 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 5.0; zh-cn; SM-G9006W Build/LRX21T) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/6.7 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 5.1; zh-CN; m2 note Build/LMY47D) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.8.885 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-CN; EVA-DL00 Build/HUAWEIEVA-DL00) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.8.885 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; SM-G9308 Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.1 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_2 like Mac OS X) AppleWebKit/602.3.12 (KHTML, like Gecko) Mobile/14C92 baiduboxapp/0_7.0.2.8_enohpi_6311_046/2.01_2C2%256enohPi/1099a/DBAB61466DAD7F85F9190B852920A7C7B8C1F37EEFCTOBITMOB/1', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 baiduboxapp/0_7.0.2.8_enohpi_4331_057/1.1.01_1C2%258enohPi/1099a/A1EEA09A310BA85EEF9DAFB7151392871B6CC3358FCBPNAOKSB/1', 
	'Mozilla/5.0 (iPhone 6; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Version/10.0 MQQBrowser/7.2 Mobile/14B100 Safari/8536.25 MttCustomUA/2 QBWebViewType/1', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-cn; PLK-TL01H Build/HONORPLK-TL01H) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.0 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 8_1_3 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Mobile/12B466 rabbit%2F1.0 baiduboxapp/0_0.0.1.7_enohpi_8022_2421/3.1.8_1C2%257enohPi/1099a/5BCDF4ABCF2CFC73BC8DE68BFA6DA5DFDF28CA5C1FRDLPONMDE/1', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 search%2F1.0 baiduboxapp/0_0.0.3.7_enohpi_8022_2421/1.1.01_1C2%257enohPi/1099a/75E153C908663866FEBA39B6463E914703DC0E8ADFCSSFGKJAN/1', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_2_1 like Mac OS X) AppleWebKit/602.4.2 (KHTML, like Gecko) Mobile/14D10 baiduboxapp/0_7.0.2.8_enohpi_8022_2421/1.2.01_2C2%258enohPi/1099a/E5463706B6649B5B9A4D2FCB273FB73ADF3B69C8AFRRAGDQFCP/1', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; MIX Build/MXB48T) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.146 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.6', 
	'Mozilla/5.0 (iPhone 6s; CPU iPhone OS 9_0_2 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Version/9.0 MQQBrowser/7.0.1 Mobile/13A452 Safari/8536.25 MttCustomUA/2', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_0_2 like Mac OS X) AppleWebKit/602.1.50 (KHTML, like Gecko) Mobile/14A456 MicroMessenger/6.5.2 NetType/WIFI Language/zh_TW', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-CN; SM-N9200 Build/MMB29K) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 UCBrowser/11.0.5.841 U3/0.8.0 Mobile Safari/534.30', 
	'Mozilla/5.0 (Linux; Android 7.0; MHA-AL00 Build/HUAWEIMHA-AL00; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/48.0.2564.116 Mobile Safari/537.36 baidubrowser/7.8.12.0 (Baidu; P1 7.0)', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 8_4 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Mobile/12H143 baiduboxapp/0_7.0.2.8_enohpi_8022_2421/4.8_1C2%257enohPi/1099a/2B2EE77DD24DF84D74B6A0FE95860D3FCCEEC6931FCCRRBETHP/1', 
	'Mozilla/5.0 (Linux; U; Android 4.4.4; zh-cn; MI NOTE LTE Build/KTU84P) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.146 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.6', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_2 like Mac OS X) AppleWebKit/602.3.12 (KHTML, like Gecko) Mobile/14C92 baiduboxapp/0_7.0.2.8_enohpi_8022_2421/2.01_1C2%257enohPi/1099a/752A993C0AEC43B6407895135DB16B54CF97E7CA0OCQHDDTBHR/1', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_0_2 like Mac OS X) AppleWebKit/602.1.50 (KHTML, like Gecko) Mobile/14A456 baiduboxapp/0_11.0.1.8_enohpi_8022_2421/2.0.01_2C2%258enohPi/1099a/5E7B68382DADC810B3B3FF63ED7B2C9D2E96DDC11OCMSTANAOL/1', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_3_2 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13F69 baiduboxapp/0_7.0.2.8_enohpi_8022_2421/2.3.9_1C2%257enohPi/1099a/30DA9C718740F17767CB50C1D203BB3DADE7EF114FRSNBBCIHS/1', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 baiduboxapp/0_7.0.2.8_enohpi_4331_057/1.1.01_2C2%257enohPi/1099a/5C517B4B160A9ED866A0F8BA655EE866360E82CD8OCOMHRKBCA/1', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; MI 5 Build/MXB48T) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/46.0.2490.85 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.3.2', 
	'Mozilla/5.0 (Linux; Android 6.0; HUAWEI VNS-DL00 Build/HUAWEIVNS-DL00) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.1 rabbit/1.0 baiduboxapp/7.6.1 (Baidu; P1 6.0)', 
	'Mozilla/5.0 (Linux; Android 4.4.4; G621-TL00 Build/HonorG621-TL00) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/33.0.0.0 Mobile Safari/537.36 baiduboxapp/4.2 (Baidu; P1 4.4.4)', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-CN; MI 5 Build/MXB48T) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.8.885 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 baiduboxapp/0_11.0.1.8_enohpi_8022_2421/1.1.01_2C2%258enohPi/1099a/5B5510289CD854BB14FB03C547D47EF52F828B20BOCDFTODLTE/1', 
	'Mozilla/5.0 (Linux; Android 6.0.1; MI 4W Build/MMB29M; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/48.0.2564.116 Mobile Safari/537.36 baidubrowser/7.8.12.0 (Baidu; P1 6.0.1)', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-cn; EVA-AL10 Build/HUAWEIEVA-AL10) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.2 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; Android 4.4.4; vivo X5Max+ Build/KTU84P) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.1 baiduboxapp/8.0 (Baidu; P1 4.4.4)', 
	'Mozilla/5.0 (iPhone 91; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Version/10.0 MQQBrowser/7.2 Mobile/14B100 Safari/8536.25 MttCustomUA/2 QBWebViewType/1', 
	'Mozilla/5.0 (Linux; U; Android 4.4.2; zh-cn; HM NOTE 1LTETD Build/KVT49L) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Mobile Safari/537.36 XiaoMi/MiuiBrowser/2.0.1', 
	'Mozilla/5.0 (Linux; Android 5.1.1; Hisense E51-M Build/LMY47V) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.1 baiduboxapp/8.0 (Baidu; P1 5.1.1)', 
	'Mozilla/5.0 (iPhone 6; CPU iPhone OS 10_2 like Mac OS X) AppleWebKit/602.3.12 (KHTML, like Gecko) Version/6.0 MQQBrowser/6.8 Mobile/14C92 Safari/8536.25 MttCustomUA/2', 
	'Mozilla/5.0 (iPhone 6s; CPU iPhone OS 10_2 like Mac OS X) AppleWebKit/602.3.12 (KHTML, like Gecko) Version/10.0 MQQBrowser/7.2 Mobile/14C92 Safari/8536.25 MttCustomUA/2 QBWebViewType/1', 
	'Mozilla/5.0 (Linux; Android 4.4.4; SM-G5308W Build/KTU84P) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.1 baiduboxapp/8.0 (Baidu; P1 4.4.4)', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; MI MAX Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/46.0.2490.85 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.0.11', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 baiduboxapp/0_7.0.2.8_enohpi_8022_2421/1.1.01_1C2%257enohPi/1099a/E9AD90D3F5F9328DEDC6090B355478B92F73FB3FCOCBGPMCKNB/1', 
	'Mozilla/5.0 (Linux; U; Android 5.1.1; zh-cn; 2014813 Build/LMY47V) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.146 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.6', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 baiduboxapp/0_7.0.2.8_enohpi_4331_057/1.1.01_1C2%259enohPi/1099a/8754616FF92C4079B05AD166A84FB74E5490F32ABORLIAHOOMF/1', 
	'Mozilla/5.0 (Linux; U; Android 4.0.4; zh-cn; LT25c Build/9.0.E.0.287) AppleWebKit/534.24 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.24 T5/2.0 baiduboxapp/5.0 (Baidu; P1 4.0.4)', 
	'Mozilla/5.0 (SymbianOS/9.4; Series60/5.0; Android 7.1; MI 4LTE Build/NDE63X; ) AppleWebKit/537.36 (KHTML, like Gecko) UCBrowser/10.9.2.712 U3/0.8.0 Mobile Safari/534.30', 
	'Mozilla/5.0 (Linux; Android 6.0; HUAWEI NXT-AL10 Build/HUAWEINXT-AL10) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/37.0.0.0 Mobile MQQBrowser/6.9 TBS/036902 Safari/537.36 MicroMessenger/6.5.3.980 NetType/4G Language/zh_CN', 
	'Mozilla/5.0 (Linux; Android 5.1.1; vivo X7Plus Build/LMY47V) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.2 (Baidu; P1 5.1.1)', 
	'Mozilla/5.0 (Linux; Android 6.0.1; ZUK Z2131 Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 6.0.1)', 
	'Mozilla/5.0 (Linux; Android 6.0; HUAWEI NXT-AL10 Build/HUAWEINXT-AL10) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/37.0.0.0 Mobile MQQBrowser/6.9 TBS/036903 Safari/537.36 MicroMessenger/6.5.3.980 NetType/4G Language/zh_CN', 
	'Mozilla/5.0 (Linux; Android 5.1.1; ATH-TL00H Build/HONORATH-TL00H) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/37.0.0.0 Mobile MQQBrowser/6.9 TBS/036903 Safari/537.36 MicroMessenger/6.3.13.49_r4080b63.740 NetType/cmnet Language/zh_CN', 
	'Mozilla/5.0 (Linux; Android 6.0; HUAWEI MT7-TL10 Build/HuaweiMT7-TL10) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/37.0.0.0 Mobile MQQBrowser/6.9 TBS/036903 Safari/537.36 MicroMessenger/6.3.32.960 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_3_5 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13G36 MicroMessenger/6.5.1 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_2 like Mac OS X) AppleWebKit/602.3.12 (KHTML, like Gecko) Mobile/14C92 baiduboxapp/0_7.0.2.8_enohpi_4331_057/2.01_1C2%259enohPi/1099a/4270183DAF54D0DF310B7DF5EF0B472FBCEC58A1DORRNCHHTKO/1', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_2 like Mac OS X) AppleWebKit/602.3.12 (KHTML, like Gecko) Mobile/14C92 baiduboxapp/0_7.0.2.8_enohpi_6311_046/2.01_2C2%256enohPi/1099a/0D7200A1DC5F5CBE3B8DCABCC30D14D367AB10E24FRFEKQOTCN/1', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-CN; SM-C7000 Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.8.885 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 4.4.2; zh-cn; PE-TL20 Build/HuaweiPE-TL20) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 MQQBrowser/5.3 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; ONEPLUS A3010 Build/MXB48T) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/6.0 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-cn; PE-TL20 Build/HuaweiPE-TL20) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/6.0 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; Android 4.4.4; Nexus 4 Build/KTU84P) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/37.0.0.0 Mobile MQQBrowser/6.8 TBS/036887 Safari/537.36 MicroMessenger/6.3.22.821 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (Linux; U; Android 5.1.1; zh-CN; KIW-TL00H Build/HONORKIW-TL00H) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.8.885 Mobile Safari/537.36', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 baiduboxapp/0_7.0.2.8_enohpi_4331_057/1.1.01_2C2%257enohPi/1099a/A903E616FD547EC05F556ADB6F2E046651B336D13FRSAPHIKAN/1', 
	'Mozilla/5.0 (Linux; Android 6.0; VIE-AL10 Build/HUAWEIVIE-AL10) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 6.0)', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; SM-A9000 Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.2 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; Android 4.4.2; PE-TL10 Build/HuaweiPE-TL10) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/37.0.0.0 Mobile MQQBrowser/6.8 TBS/036887 Safari/537.36 MicroMessenger/6.3.31.940 NetType/cmnet Language/zh_CN', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_3_5 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13G36 MicroMessenger/6.5.2 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (Linux; Android 5.0.2; PLK-AL10 Build/HONORPLK-AL10) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/37.0.0.0 Mobile MQQBrowser/6.9 TBS/036903 Safari/537.36 MicroMessenger/6.5.3.980 NetType/4G Language/zh_CN', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_2_1 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13D15 MicroMessenger/6.5.2 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (Linux; Android 5.0.2; D6683 Build/23.1.2.E.0.13) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/37.0.0.0 Mobile MQQBrowser/6.9 TBS/036903 Safari/537.36 MicroMessenger/6.3.31.940 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-cn; KNT-AL20 Build/HUAWEIKNT-AL20) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/6.0 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; Android 7.0; LON-AL00 Build/HUAWEILON-AL00) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 7.0)', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; Mi Note 2 Build/MXB48T) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.146 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.5.10', 
	'Mozilla/5.0 (Linux; Android 6.0; MI 5 Build/MRA58K) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/37.0.0.0 Mobile MQQBrowser/6.9 TBS/036903 Safari/537.36 MicroMessenger/6.5.3.980 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; Mi Note 2 Build/MXB48T) AppleWebKit/537.36 (KHTML, like Gecko)Version/4.0 Chrome/37.0.0.0 MQQBrowser/7.2 Mobile Safari/537.36', 
	'Xiaomi_2014022_TD-LTE/V1 Linux/3.4.67 Android/4.4.2 Release/04.07.2014 Browser/AppleWebKit537.36 Chrome/30.0.0.0 Mobile Safari/537.36 System/Android 4.4.2 XiaoMi/MiuiBrowser/1.0', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 9_2_1 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Mobile/13D15 baiduboxapp/0_9.1.0.8_enohpi_1002_5211/1.2.9_2C2%258enohPi/1099a/7CA555419EAFDAEC020AD591D11BC4D5EB5593FA8FCMPJNESSR/1', 
	'Mozilla/5.0 (Linux; U; Android 5.1.1; zh-cn; 2014811 Build/LMY47V) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.146 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.6', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-CN; HTC M8t Build/MRA58K) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.1.888 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; Android 5.0; ASUS_Z00ADB Build/LRX21V; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/43.0.2357.121 Mobile Safari/537.36 MicroMessenger/6.3.31.940 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_2 like Mac OS X) AppleWebKit/602.3.12 (KHTML, like Gecko) Mobile/14C92 baiduboxapp/0_7.0.2.8_enohpi_4331_057/2.01_1C2%259enohPi/1099a/67328188D51A6D36D25B811EB79B50F59FA62A48AFRTDOOQJPL/1', 
	'Mozilla/5.0 (iPhone 5SGLOBAL; CPU iPhone OS 8_3 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Version/8.0 MQQBrowser/7.2 Mobile/12F70 Safari/8536.25 MttCustomUA/2 QBWebViewType/1', 
	'Mozilla/5.0 (Linux; Android 6.0; MI 5 Build/MRA58K) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/37.0.0.0 Mobile MQQBrowser/6.9 TBS/036903 Safari/537.36 MicroMessenger/6.3.32.940 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_1_1 like Mac OS X) AppleWebKit/602.2.14 (KHTML, like Gecko) Mobile/14B100 baiduboxapp/0_11.0.1.8_enohpi_4331_057/1.1.01_2C2%257enohPi/1099a/4787349F9F4BE12D8219084E2B79F3D80ADE20295ORLSPDDTAM/1', 
	'Mozilla/5.0 (Linux; U; Android 6.0; zh-CN; HUAWEI NXT-AL10 Build/HUAWEINXT-AL10) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.3.0.907 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-cn; Redmi 3S Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.146 Mobile Safari/537.36 XiaoMi/MiuiBrowser/8.4.6', 
	'Mozilla/5.0 (Linux; U; Android 6.0.1; zh-CN; MI NOTE LTE Build/MMB29M) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.2.8.885 Mobile Safari/537.36', 
	'Mozilla/5.0 (Linux; Android 6.0; EVA-AL10 Build/HUAWEIEVA-AL10) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/35.0.1916.138 Mobile Safari/537.36 T7/7.4 baiduboxapp/8.1 (Baidu; P1 6.0)', 
	'Mozilla/5.0 (Linux; Android 6.0; HUAWEI NXT-AL10 Build/HUAWEINXT-AL10) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/37.0.0.0 Mobile MQQBrowser/6.9 TBS/036903 Safari/537.36 MicroMessenger/6.5.3.980 NetType/WIFI Language/zh_CN', 
	'Mozilla/5.0 (iPhone; CPU iPhone OS 10_2 like Mac OS X) AppleWebKit/602.3.12 (KHTML, like Gecko) Mobile/14C92 MicroMessenger/6.5.3 NetType/WIFI Language/zh_CN', 
)


MINETYPE = '''application/epub+zip'''


CONTAINER = '''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
    <rootfiles>
        <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
   </rootfiles>
</container>
'''


FLOW0012 = '''/** ------------------------------------------------------------------------------------------------------ **/
/** 全局样式设定 **/
/** ------------------------------------------------------------------------------------------------------ **/

/** ----------------------------------------------- **/
/** 全局样式 **/
/** ----------------------------------------------- **/

/** 行高字号设定 **/
body {
	font-size: 1em;
	text-align: justify;
	line-height: 1.618em;
}

/*书名页*/
.smy-sm{font-size:2em;font-family:hei;margin-top:2em;margin-bottom:0em;text-align:center;font-weight:bold;text-indent:0em;}
/*书名页*/
.smy-sm1{font-size:1.5em;font-family:hei;margin-top:1em;margin-bottom:0em;text-align:center;font-weight:normal;text-indent:0em;}
/*书名页丛书名*/
.smy-csm{font-size:1.7em;font-family:hei;margin-top:0em;margin-bottom:0em;text-align:center;font-weight:normal;text-indent:0em;}
/*书名页副书名*/
.smy-fsm{font-size:1.7em;font-family:hei;margin-bottom:2em;margin-top:0em;text-align:left;font-weight:normal;}
/*书名页副书名*/
.smy-fsm1{font-size:1.7em;font-family:hei;margin-bottom:0em;margin-top:0.5em;text-align:center;font-weight:normal;text-indent:0em;}
/*书名页作者*/
.smy-zz{font-size:1.5em;font-family:hei;margin-top:1em;margin-bottom:0em;text-align:center;font-weight:normal;text-indent:0em;}

.smy-zz1{font-size:1.5em;font-family:hei;margin-top:1em;margin-bottom:0em;text-align:center;font-weight:normal;text-indent:0em;}

.smy-cbs{font-size:1.5em;font-family:hei;margin-top:6em;text-align:center;font-weight:normal;text-indent:0em;}
/*书名页其它*/
.smy-qt{font-size:1.5em;font-family:hei;text-align:center;font-weight:normal;text-indent:0em;}

/** 全文首行缩进2个中文字符 **/
p {
	text-indent: 2em;
}

/** 版权信息页正文 **/
p.kindle-cn-copyright-text {
	line-height: 1.618em;
	text-indent: 0em;
}
/** 作者名居右楷体 **/
p.zuozhe-juyou-kaiti {
	text-align: right;
	font-family: STKai, "MKai PRC", Kai,"楷体"; 
}

/** 引用框 **/
blockquote.kindle-cn-blockquote {
	background: #DCDCDC;
 	border-left: 0.5em solid #c7c7c7;
  	margin: 1.5em;
  	padding: 1em;
 	text-indent:2em;
  	line-height:1.5em;
}

div.kindle-cn-blockquote {
	border-left: 0.5em solid #c7c7c7;
	margin: 1.5em;
 	padding: 0.5em;
 	text-indent:2em;
	font-family:STKai, "MKai PRC", Kai,"楷体";
  	line-height:1.5em;
}


/** 日语 **/
:lang(ja) {
    font-family: TBGothic, TBMincho, TBGothic, HYGothic, TsukushiMincho;
}

/** 文字居右 **/
p.kindle-cn-signature {
	text-align: right;
}


/** 首字下沉 **/
span.kindle-cn-dropcap {
	float:left;
	font-size:2.85em;
	line-height: 1em;
	padding:0em 0em 0em 0em;
	text-indent:0
}
p.kindle-cn-dropcap{
	text-indent:0em;
}


/** 行间图 **/
img.kindle-cn-inline-image {
	height: 1em;
	vertical-align: middle;
	margin-left: 0em ;
	margin-right: 0em  ;
}
/* 根据原文调整图片大小 plus1*/
img.kindle-cn-inline-image2 {
	height: 2em;
	vertical-align: middle;
	margin-left: 0em ;
	margin-right: 0em  ;
}
/** 生僻字 **/
img.kindle-cn-inline-character{
	width: 1em;
	vertical-align:middle;
}

/** 段落里的引用部分 **/
p.kindle-cn-ref {
	margin:0em 1em 0em 1em;
	font-family: STKai, "MKai PRC", Kai,"楷体"; 
}


/** ----------------------------------------------- **/




/** ----------------------------------------------- **/
/** 多字体 **/
/** ----------------------------------------------- **/

/** 黑体文字 **/
.kindle-cn-hei { 
	font-family: "MYing Hei S", Hei,"黑体"; 
}

/** 宋体文字 **/
.kindle-cn-song { 
	font-family: STSong, "Song S", Song,"宋体"; 
}

/** 楷体文字 **/
.kindle-cn-kai { 
	font-family: STKai, "MKai PRC", Kai,"楷体"; 
}

/** ----------------------------------------------- **/




/** ----------------------------------------------- **/
/** 列表样式 **/
/** ----------------------------------------------- **/

/** 无序列表样式 **/
/** 圈标签 **/
ul.kindle-cn-ul-disc {
	list-style-type: disc;
}

/** 圆环标签 **/
ul.kindle-cn-ul-circle {
	list-style-type: circle;
}

/** 方形标签 **/
ul.kindle-cn-ul-square {
	list-style-type: square;
}


/** 有序列表样式 **/
/** 此样式会显示1. 2. 3. **/
ol.kindle-cn-ol-decimal {
	list-style-type: decimal;
} 
 
/** 此样式会显示i. ii. iii. **/
ol.kindle-cn-ol-lroman {
	list-style-type: lower-roman;
}

/** 此样式会显示I. II. III. **/
ol.kindle-cn-ol-uroman {
	list-style-type: upper-roman;
} 

/** 此样式会显示a. b. c. **/
ol.kindle-cn-ol-lalpha {
	list-style-type: lower-alpha;
}

/** ----------------------------------------------- **/




/** ----------------------------------------------- **/
/** 标题样式 **/
/** ----------------------------------------------- **/


/** 双线标题 **/
h1.kindle-cn-heading-1 {
	border-bottom: 2px dashed #c7c7c7;
	border-top: 2px dashed #c7c7c7;
	padding: 0.75em 0 0.75em 0;
	width: 100%;
	page-break-before: always;
	font-size: 3em;
	font-family:"MYing Hei S", Hei,"黑体";
}


/** 下单线标题 **/
h1.kindle-cn-heading-2 {
	font-size: 3em;
	font-family:"MYing Hei S", Hei,"黑体";
	border-bottom: 2px dashed #c7c7c7;
	margin-bottom: -0em;
	width: 100%;
	page-break-before: always;
}

h2.kindle-cn-heading2 {
	width: 100%;
	font-size: 2.5em;
}

h3.kindle-cn-heading2 {
	font-size: 2em;
}
h4.kindle-cn-heading2 {
	font-size: 1.5em;
}
h5.kindle-cn-heading2 {
	font-size: 1em;
}
h1{font-size:2.5em;text-align: center;}/*一级标题*/
h2{font-size:2em;text-align: center;}/*二级标题*/
h3{font-size:1.75em;}/*三级标题*/
h4{font-size:1.5em;text-align: center;}/*四级标题*/
h5{font-size:1.25em;}/*五级标题*/
h6{font-size:1em;}/*六级标题*/
/**/

/** 页眉标题 **/
div.kindle-cn-page-header-outer{
	border-bottom: 1px solid #FF9900;
	margin-bottom: 0em;
	width: 100%;
}

h1.kindle-cn-heading-3{
	padding:0.4em;
	margin:0;
	width: 100%;
	color: white;
	background-color:#FF9900;
	display: inline;
	font-size:0.8em;
	page-break-before: always;
}


/** ----------------------------------------------- **/







/** ----------------------------------------------- **/
/** 图片样式设定 **/
/** ----------------------------------------------- **/


/** ----------------------------- **/
/** 图片居中样式 **/
/** ----------------------------- **/

/** Div居中样式 **/
div.kindle-cn-bodycontent-div-alone100  {
    width: 100%;
    text-align: center;
}
div.kindle-cn-bodycontent-div-alone100a  {
    width: 100%;
    text-align: left;
	text-indent: 2em;
}

/** 图片80%大小，带图说 **/
img.kindle-cn-bodycontent-image-alone80-withnote  {
	width: 80%;
	margin-bottom: 0em;
}

/** 图片80%大小，不带图说 **/
img.kindle-cn-bodycontent-image-alone80  {
	width: 80%;
	margin-bottom: 0.5em;
}
img.kindle-cn-bodycontent-image-alone100  {
	width: 100%;
	margin-bottom: 0.5em;
}
/** 图片50%大小，带图说 **/
img.kindle-cn-bodycontent-image-alone50-withnote  {
	width: 50%;
	margin-bottom: 0em;
}
img.kindle-cn-bodycontent-image-alone40-withnote  {
	width: 40%;
	margin-bottom: 0em;
}
img.kindle-cn-bodycontent-image-alone30-withnote  {
	width: 30%;
	margin-bottom: 0em;
}
img.kindle-cn-bodycontent-image-alone20-withnote  {
	width: 20%;
	margin-bottom: 0em;
}
img.kindle-cn-bodycontent-image-alone45-withnote  {
	width: 45%;
	margin-bottom: 0em;
}
/** 图片50%大小，不带图说 **/
img.kindle-cn-bodycontent-image-alone50  {
	width: 50%;
	margin-bottom: 0.5em;
}
img.kindle-cn-bodycontent-image-alone40  {
	width: 40%;
	margin-bottom: 0.5em;
}
img.kindle-cn-bodycontent-image-alone30  {
	width: 30%;
	margin-bottom: 0.5em;
}
img.kindle-cn-bodycontent-image-alone20  {
	width: 20%;
	margin-bottom: 0.5em;
}
img.kindle-cn-bodycontent-image-alone45  {
	width: 45%;
	margin-bottom: 0.5em;
}
/** 图片80%大小，图说在图上方，通常用于表格 **/
img.kindle-cn-bodycontent-image-alone80-1  {
	width: 80%;
	margin-top: -0.3em;
}

/** 图说文字少，居中对齐 **/
p.kindle-cn-picture-txt-withfewcharactors {
	font-size: 0.85em;
	font-family: STKai, "MKai PRC", Kai,"楷体";
	text-align: center;
	margin-top: 0.3em;
	text-indent: 0;
}

/** 图说文字多，左对齐 **/
p.kindle-cn-picture-txt-withmanycharactors {
	font-size: 0.85em;
	font-family: STKai, "MKai PRC", Kai,"楷体";
	text-align: left;
	margin-top: 0.3em;
	text-indent: 0;
}
/** ----------------------------- **/



/** ----------------------------- **/
/** 右绕排图样式（图片在右侧） **/
/** ----------------------------- **/

/** div样式 **/
div.kindle-cn-bodycontent-div-right  {
	width: 45%;
	margin-left: 1em;
	float: right;
	font-size: 1em;
}

/** 图片样式1(不带图说) **/
img.kindle-cn-bodycontent-divright-image-withoutnote {
	width: 100%;
	margin-bottom:0.5em
}

/** 图片样式2(带图说) **/
img.kindle-cn-bodycontent-divright-image-withnote {
	width: 100%;
	margin-bottom:0em
}

/** 图说样式(左对齐，左侧边与图片边缘对齐 **/
p.kindle-cn-picture-txt-right {
	font-size: 0.85em;
	font-family: STKai, "MKai PRC", Kai,"楷体";
	text-align: left;
	text-indent: 0;
	margin-top: 0em;
}
/** ----------------------------- **/



/** ----------------------------- **/
/** 左绕排图(图片在左侧 **/
/** ----------------------------- **/

/** div样式 **/
div.kindle-cn-bodycontent-div-left  {
	width: 45%;
	margin-right: 1em;
	float: left;
	font-size: 1em;
}

/** 图片样式1(不带图说 **/
img.kindle-cn-bodycontent-divleft-image-withoutnote {
	width: 100%;
	margin-bottom:0.5em
}

/** 图片样式2(带图说 **/
img.kindle-cn-bodycontent-divleft-image-withnote {
	width: 100%;
	margin-bottom:0em
}

/** 图说样式(左对齐，左侧边与图片边缘对齐 **/
p.kindle-cn-picture-txt-left {
	font-size: 0.85em;
	font-family: STKai, "MKai PRC", Kai,"楷体";
	text-align: left;
	margin-top: 0em;
	text-indent: 0;
}
/** ----------------------------- **/




/** ----------------------------- **/
/** 并列图片 **/
/** ----------------------------- **/
/** 无图注 **/
table.kindle-cn-picture-parallel-1 {
	margin: 1em auto 1em auto; 
	text-align: center;
}

td.kindle-cn-picture-parallel-2 {
	vertical-align: bottom; 
	text-align: center;
	width: 40%;
}
img.kindle-cn-picture-parallel-3 {
	text-align:center; 
	width:90%;
}

/** ----四图一页无图注---- **/
table.kindle-cn-picture-four-1 {
                margin:auto;
}

td.kindle-cn-picture-four-2 {
                width:40%;
                vertical-align:bottom
}

img.kindle-cn-tourism-four_images-3 {
	width:100%;
}
/** ----------------------------- **/



/** ----------------------------- **/
/** 并列图片 **/
/** ----------------------------- **/
/** 无图注 **/
table.kindle-cn-picture-parallel-1 {
	margin: 1em auto 1em auto; 
	text-align: center;
}

td.kindle-cn-picture-parallel-2 {
	vertical-align: bottom; 
	text-align: center;
	width: 40%;
}
img.kindle-cn-picture-parallel-3 {
	text-align:center; 
	width:90%;
}


/** ----------------------------- **/
/** 并列图文横排 **/
/** ----------------------------- **/

table.kindle-cn-tourism-double_image_with_notes-1 {
	margin: 1em auto 1em auto; 
	text-align: center;
}

td.kindle-cn-tourism-double_image_with_notes-2 {
	vertical-align: bottom; 
	width: 48%;
}

td.kindle-cn-tourism-double_image_with_notes-3 {
	vertical-align:top;
	text-align:justify;
	font-size:0.85em;
	padding : 0.8em;
	font-family: STKai, "MKai PRC", Kai,"楷体"; 
}


img.kindle-cn-tourism-double_image_with_notes-4 {
	width: 95%; 
}/** ----------------------------- **/


/** ----------------------------- **/
/** 三图文并列横排 **/
/** ----------------------------- **/

table.kindle-cn-tourism-triple_image_with_notes-1 {
	margin: 1em auto 1em auto; 
	text-align: center;
}

td.kindle-cn-tourism-triple_image_with_notes_2 {
	vertical-align: bottom; 
	width: 30%;
}

td.kindle-cn-tourism-triple_image_with_notes-3 {
	vertical-align:top;
	text-align:justify;
	font-size:0.85em;
	padding: 0em 1em 0em 1em;
	font-family: STKai, "MKai PRC", Kai,"楷体"; 
}


img.kindle-cn-tourism-triple_image_with_notes-4 {
	width: 95%;
}
/** ----------------------------- **/


/** ----------------------------------------------- **/






/** ----------------------------------------------- **/
/** 表格样式设定 **/
/** ----------------------------------------------- **/


/** ----------------------------- **/
/** 横向表头 **/
/** ----------------------------- **/

table.kindle-cn-table-body6 {
	margin: 1em auto 1em auto;
	border-style: solid solid none solid;
	width: 100%;
	border-width: 1px;
}

td.kindle-cn-table-th{
	vertical-align: middle;
	padding: 0.5em 0.5em 0.5em 0.5em;
	border-style: none none solid solid;
	border-width: 1px;
	font-weight: bold;
	text-align:center;
}
td.kindle-cn-table-dg6 {
	vertical-align: middle;
	padding: 0.5em 0.5em 0.5em 0.5em;
	border-style: solid solid solid solid;
	border-width: 1px;
	text-align:center;
}
/** ----------------------------- **/




/** ----------------------------- **/
/** 纵向表头 **/
/** ----------------------------- **/
table.kindle-cn-table-body {
	margin: 1em auto 1em auto;
	border-style: solid solid none none;
	width: 100%;
	border-width: 1px;
}

/** 普通单元格1 **/
td.kindle-cn-table-dg1c {
	vertical-align: middle;
	padding: 0.5em 0.5em 0.5em 0.5em;
	border-style: none none none solid;
	border-width: 1px;
	text-align:center;
}
td.kindle-cn-table-dg1 {
	vertical-align: middle;
	padding: 0.5em 0.5em 0.5em 0.5em;
	border-style: none none solid solid;
	border-width: 1px;
	text-align:center;
}
td.kindle-cn-table-dg1l {
	vertical-align: middle;
	padding: 0.5em 0.5em 0.5em 0.5em;
	border-style: none none solid solid;
	border-width: 1px;
	text-align:left;
}
/** 普通单元格2 **/
td.kindle-cn-table-dg2 {
	vertical-align: middle;
	padding: 0.5em 0.5em 0.5em 0.5em;
	border-style: none none solid solid;
	border-width: 1px;
	text-align: left;
}
td.kindle-cn-table-dg2c {
	vertical-align: middle;
	padding: 0.5em 0.5em 0.5em 0.5em;
	border-style: none none solid solid;
	border-width: 1px;
	text-align: center;
}
/** ----------------------------- **/




/** ----------------------------- **/
/** 带底色无边框表格 **/
/** ----------------------------- **/
table.kindle-cn-bodyt {
	margin: 1em 0em 0.5em 0em;
	border-style: solid none solid none;
	border-width: 2px;
	border-color: #000000;
}

td.kindle-cn-table-rt {
	vertical-align: middle;
	padding: 0.5em 0.5em 0.5em 0.5em;
	background-color: #c7c7c7;
	text-align: center;
	font-weight: bold;
}

/** 普通单元格 **/
td.kindle-cn-table-rn {
	vertical-align: top;
	padding: 0.5em 0.5em 0.5em 0.5em;
	background-color: #DCDCDC;
	text-align:left;
}

/** ----------------------------- **/



/** ----------------------------- **/
/** 内部无边框表格 **/
/** ----------------------------- **/

table.kindle-cn-table-bodyt-1 {
	margin: 1em 0em 1em 0em;
	border-style: solid none solid none;
	border-width: 2px;
}

td.kindle-cn-table-rt1 {
	vertical-align: middle;
	border-style: none none solid none;
	padding: 0.5em 0.5em 0.5em 0.5em;
	border-width: 1px;
	text-align: center;
	font-weight: bold;
}

/** 普通单元格 **/
td.kindle-cn-table-rn1 {
	vertical-align: top;
	padding: 0.5em 0.5em 0.5em 0.5em;
	text-align:left;
}
/** ----------------------------- **/





/** ----------------------------------------------- **/
/** 边框样式 **/
/** ----------------------------------------------- **/
/** ----------------------------- **/
/** 阴影边框样式 **/
/** ----------------------------- **/
div.kindle-cn-frame-shadow{
	border: 1px solid #146eb4;
	box-shadow: 5px 5px 5px #c7c7c7;
	width: 95%;
	padding: 0.3em;
	margin-left: 2%;
	margin-right: 3%;
}


/** 边框内文字无缩进 **/
p.kindle-cn-noindent{
	text-indent:0
}

/** ----------------------------- **/
/** 提示框 **/
/** ----------------------------- **/
div.kindle-cn-tip-box {
	padding:1em 1em 1em 1em; 
	margin: 1em 0 1em 0em;
	background-color: #DCDCDC;
	font-family:STKai, "MKai PRC", Kai,"楷体";
	line-height:1.5em;
}

/** ----------------------------- **/
/** 直角框 **/
/** ----------------------------- **/
div.kindle-cn-frame-zhijiao {
	font-size: 1em;
	padding: 0.5em;
	margin: 1.5em 0em 1.5em 0em;
	border-style: solid solid solid solid;
	border-width: 1px;
}
/** ----------------------------- **/
/** 圆角框 **/
/** ----------------------------- **/
div.kindle-cn-frame-yuanjiao{
	font-size: 1em;
	padding: 0.5em;
	margin: 1.5em 0em 1.5em 0em;
	border-style: solid solid solid solid;
	border-width: 1px;
	border-radius: 0.5em;
}

/** ----------------------------- **/
/** 带底色知识点文本框**/
/** ----------------------------- **/
div.kindle-cn-frame-zhishidian1 {
	font-size: 1em;
	padding: 0.5em;
	margin: 1.5em 0em 1.5em 0em;
	background-color: #DCDCDC;
	border-bottom: solid 1px #666666;
}


/** ----------------------------- **/
/** 诗歌**/
/** ----------------------------- **/
p.kindle-cn-poem-left {
	margin-left: 2em;
	font-family:STKai, "MKai PRC", Kai,"楷体";
	text-indent: 0em;

}
p.kindle-cn-poem-center {
	font-family:STKai, "MKai PRC", Kai,"楷体";
	text-align: center;
	text-indent:0em;
}

/** 底纹知识点 **/
p.kindle-cn-frame-zsdtext1 {
	padding: 0.3em 0em 0.25em 0.3em;
	margin-top: -0.5em;
	margin-left: -0.5em;
	font-weight: bold;
	margin-right: -0.5em;
	text-align: center;
	color: #000000;
	border-bottom: solid 1px #666666;
	background-color: #c7c7c7;
	text-indent:0em;
}

/** ----------------------------- **/
/** 知识点标题虚线文本框 **/
/** ----------------------------- **/
p.kindle-cn-frame-zsdtext2 {
	padding-bottom: 0.2em;
	font-size: 1em;
	font-weight: bold;
	text-indent: 0em;
	border-bottom: solid 1px #666666;
}



/** ----------------------------- **/



/** ----------------------------------------------- **/
/** 文字特殊样式 **/
/** ----------------------------------------------- **/

/** 加粗 **/
span.kindle-cn-bold{
font-weight: bold;
}

/** 斜体字 **/
span.kindle-cn-italic{
font-style: italic;
}

/** 斜体加粗字体**/
span.kindle-cn-bold-italic{
font-weight: bold;
font-style: italic;
}

/** 下划线**/
span.kindle-cn-underline{
text-decoration: underline;
}

/** 删除线 **/
 span.kindle-cn-strike{
text-decoration: line-through;
}

/** 双下划线 **/ 
span.kindle-cn-specialtext-double{
	border-bottom:0.2em double;
}

/** 点线式边框 **/ 
span.kindle-cn-specialtext-dot{
	border-style:dotted;
}

/** 破折线式边框 **/ 
span.kindle-cn-specialtext-dash{
	border-style:dashed;
	border-width: 1px;
}

/** 直线式边框 **/ 
span.kindle-cn-specialtext-dot{
	border-style:solid;
	border-width: 1px;
}

/* 数学上标字体 */
span.math-super {
	font-size: 0.7em;
	vertical-align: super;
}

/* 数学上标倾斜字体 */
span.math-super-italic {
	font-size: 0.7em;
	font-style: italic;
	vertical-align: super;
}

/* 数学下标字体 */
span.math-sub {
	font-size: 0.7em;
	vertical-align: sub;
}

/** ----------------------------------------------- **/


/** ----------------------------------------------- **/
/** 带侧向竖线引用框 **/
/** ----------------------------------------------- **/
 
 
/* 带侧向竖线引用框 */
blockquote.kindle-cn-blockquote {
  	background: #f9f9f9;
	border-left: 0.5em solid #ccc;
	margin: 1.5em;
 	padding: 0.5em;
 	text-indent:2em;
	font-family:STKai, "MKai PRC", Kai,"楷体";
  	line-height:1.5em;
}

/** ----------------------------- **/


/** ------------------------------------------------------------------------------------------------------ **/









/** ------------------------------------------------------------------------------------------------------ **/
/** 英语样式 **/  

/** ------------------------------------------------------------------------------------------------------ **/

/** ----------------------------- **/
/** 音标样式 **/
/** ----------------------------- **/

/**音标区块不使用粗体，嵌入西文字体。 **/
span.kindle-cn-eng-yinbiao
{
	font-family:yinbiao;
}
/**单词区块使用粗体，字体为默认字体。 **/
p.kindle-cn-bold
{
	font-weight: bold;
}
/** ----------------------------- **/

/** ------------------------------------------------------------------------------------------------------ **/

 

/** ------------------------------------------------------------------------------------------------------ **/
/** 摄影类样式 **/
/** ------------------------------------------------------------------------------------------------------ **/

/** 步骤，白字 **/
span.kindle-cn-photography-step-white {
	background-color: #FF9900;
	font-family: "verdana";
	font-style: "italic" ;
	font-weight: bold;
	color: white;
	padding: 0.3em;
	box-shadow: 0px 3px 3px #666666;
}

/** 步骤，黑字 **/
span.kindle-cn-photography-step-black {
	background-color: #FF9900;
	font-family: "verdana";
	font-style: "italic" ;
	font-weight: bold;
	color: black;
	padding: 0.3em;
	box-shadow: 0px 3px 3px #666666;
	border-bottom: 2px solid #666666;
	margin-bottom: -0.5em;
	width: 100%;
}

/** 问答 **/
span.kindle-cn-qa {
	font-weight: bold;
	color: #EE1475;
	font-family: "MYing Hei S", Hei,"黑体"; 
}
/** ------------------------------------------------------------------------------------------------------ **/





/** ------------------------------------------------------------------------------------------------------ **/
/** 旅行类样式 **/
/** ------------------------------------------------------------------------------------------------------ **/

/** 旅行类信息文本框 **/
div.kindle-cn-tourism-lnfo-tags-1 {
background-color:#c7c7c7; 
font-family: 宋体; 
float: left; 
border-radius: 1em;
margin:0em 1em 1em 0em; 
padding: 1em; 
border-width: 0.1em; 
border-style: solid; 
box-shadow:0em 0em 2em #c7c7c7;
font-weight:500;
font-size:0.85em;
border-color:black;
}

p.kindle-cn-tourism-lnfo-tags-2 {
	border-radius: 1em;
	color:white;
	line-height:1.5em;
	background-color:#146eb4;
}
/** ------------------------------------------------------------------------------------------------------ **/


/** ------------------------------------------------------------------------------------------------------ **/
/** 计算机类样式 **/
/** ------------------------------------------------------------------------------------------------------ **/
/** 行间代码 **/
code.kindle-cn-computer-code{
	font-family: monospace;
}
/** ------------------------------------------------------------------------------------------------------ **/

/** 考试类样式 **/
/*选择题*/
p.kindle-cn-exam-choice{
	text-indent: 0em;
	font-size: 1em;
	margin-left: 2em;
}


/**字符样式**/
span.kindle-cn-char-bold{
	font-weight: bold;
}

span.kindle-cn-char-italic{
	font-style: italic;
}

span.kindle-cn-char-bolditalic{
	font-weight: bold;
	font-style: italic;
}

span.kindle-cn-char-underline{
	text-decoration: underline;
}

span.kindle-cn-char-delete{
	text-decoration: line-through;
}

span.kindle-cn-char-doubleunderline{
	text-decoration: line-through;
}

/** 加粗 **/
span.kindle-cn-bold{
font-weight: bold;
}

/** 斜体字 **/
span.kindle-cn-italic{
font-style: italic;
}

/** 斜体加粗字体**/
span.kindle-cn-bold-italic{
font-weight: bold;
font-style: italic;
}

/** 下划线**/
span.kindle-cn-underline{
text-decoration: underline;
}

/** 删除线 **/
span.kindle-cn-strike{
text-decoration: line-through;
}

/** 双下划线 **/ 
span.kindle-cn-specialtext-double{
	border-bottom:0.2em double;
}

/**背景色**/
span.kindle-cn-specialtext-bg{
	background-color:red;
}

/**部分楷体**/
span.kindle-cn-specialtext-kaiti{
	font-family: STKai, "MKai PRC", Kai,"楷体"; 
}


/** 点线式边框 **/ 
span.kindle-cn-specialtext-dot{
	border-style:dotted;
}

/** 破折线式边框 **/ 
span.kindle-cn-specialtext-dash{
	border-style:dashed;
	border-width: 1px;
}

/** 直线式边框 **/ 
span.kindle-cn-specialtext-str-line{
	border-style:solid;
	border-width: 1px;
}

/* 数学上标字体 */
span.math-super {
	font-size: 0.7em;
	vertical-align: super;
}

/* 数学上标倾斜字体 */
span.math-super-italic {
	font-size: 0.7em;
	font-style: italic;
	vertical-align: super;
}

/* 数学下标字体 */
span.math-sub {
	font-size: 0.7em;
	vertical-align: sub;
}
/**段落样式**/
/*无缩进*/
p.kindle-cn-para-no-indent{
	text-indent: 0em;
}

p.kindle-cn-para-no-indent1{
	text-indent: 0em;
	margin-left: 1em;
}

p.kindle-cn-para-no-indent2{
	text-indent: 0em;
	margin-left: 2em;
}

p.kindle-cn-para-no-indent3{
	text-indent: 0em;
	margin-left: 6em;
}



/*2em 无缩进*/
div.kindle-cn-para-2em-indent{
	margin-left: 2em;
}
p.kindle-cn-para-2em-indent{
	margin-left: 2em;
}



/*倒悬*/

p.kindle-cn-para-1em-indent1{
	text-indent: -1em;
	padding-left: 1em;
}


p.kindle-cn-para-2em-indent2{
	text-indent: -2em;
	padding-left: 2em;
}


p.kindle-cn-para-3em-indent3{
	text-indent: -3em;
	padding-left: 3em;
}

p.kindle-cn-para-4em-indent4{
	text-indent: -4.5em;
	padding-left: 6.5em;
}
p.kindle-cn-para-5em-indent5{
	text-indent: -5.5em;
	padding-left: 7.5em;
}
/*居左*/
p.kindle-cn-para-left{
	text-align: left;
}



/*居中*/
p.kindle-cn-para-center{
	text-align: center;
	text-indent: 0em;
}
.kindle-cn-para-center{
	text-align: center;
	text-indent: 0em;
}
/*居右*/
p.kindle-cn-para-right{
	text-align: right;
}

/*居中*/
p.kindle-cn-para-align-center{
	text-align:center;
}
.kindle-cn-bottom-border-heading{
	border-bottom: 2px dashed grey;
	margin-bottom: -0em;
	width: 100%;
}
/*背景色*/
.color1 
	{background-color:#146eb4}
.color2 
	{background-color:#FF9900}
.color3 
	{background-color:#666666}
.color4 
	{background-color:#c7c7c7}
.color5 
	{background-color:#DCDCDC}
.color6 
	{background-color:#b8f1cc}
.color7 
	{background-color:#18ca68}
.color8 
	{background-color:#A8D700}
.color9 
	{background-color:#ffd801}
.color10 
	{background-color:#EE1475}
.color11 
	{background-color:#009ee7}
.color12 
	{background-color:#e3393c}
.page-break
	{page-break-after:always}

/*绕排解除*/

.kindle-cn-bodycontent-div-left-clear{
	clear:left;
}

.kindle-cn-bodycontent-div-right-clear{
	clear:right;
}
/*字号*/
.font2{
	font-size:0.8em;
}
.font3{
	font-size:1.3em;
}
/*注解*/
.fnote{
	font-size: 0.9em;
	line-height: 1.5em;
	text-align: justify;
	text-indent:2em
}

/*空白行*/
.empty{
	margin-bottom:2.2em;
	margin-top:2.2em;
}

/*英文小大写*/
.specialtext-smallcaps{
	font-variant:small-caps
}
.specialtext-overline{
	text-decoration:overline
}
.kindle-cn-ul-image {
	list-style:outside;
}/*列表-列表符为图像*/

/*字下带点*/
.kindle-cn-dotundertext{
	-webkit-text-emphasis-style:dot;
		 -moz-text-emphasis-style:dot;
		  -ms-text-emphasis-style:dot;
		      text-emphasis-style:dot;
	-webkit-text-emphasis-position:under;
		 -moz-text-emphasis-position:under;
		  -ms-text-emphasis-position:under;
		      text-emphasis-position:under;
}
pre { 
white-space: pre-wrap; /*css-3*/ 
white-space: -moz-pre-wrap; /*Mozilla,since1999*/ 
white-space: -pre-wrap; /*Opera4-6*/ 
white-space: -o-pre-wrap; /*Opera7*/ 
word-wrap: break-word; /*InternetExplorer5.5+*/ 
} 

span.kk
{letter-spacing:0.5em;
}

'''


def getFakeUA():
    global MOBILE
    return random.choice(MOBILE)


def makeEpubFileDir(path: str):
    '''在path下新建一个epubFile，代替原本的copytree'''
    global MINETYPE, CONTAINER, FLOW0012
    
    os.mkdir(path+'\\epubFile')
    os.mkdir(path+'\\epubFile\\META-INF')
    os.mkdir(path+'\\epubFile\\OEBPS')

    with open(path+'\\epubFile\\mimetype', 'w', encoding='utf-8') as f:
        f.write(MINETYPE)
    with open(path+'\\epubFile\\META-INF\\container.xml', 'w', encoding='utf-8') as f:
        f.write(CONTAINER)
    with open(path+'\\epubFile\\OEBPS\\flow0012.css', 'w', encoding='utf-8') as f:
        f.write(FLOW0012)
