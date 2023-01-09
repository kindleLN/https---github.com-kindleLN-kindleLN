# -*- coding: utf-8 -*-

import os
import shutil
import uuid
from random import choice
from urllib import parse

from .utils import *


class Book:
    def __init__(self, id: int) -> None:
        self.id = id
        self.source = 'wenku8_download'
        self.catalog_link = 'https://www.wenku8.net/novel/%i/%i/index.htm' %(self.id//1000, self.id)
        self.volumes = []
        
        getInfo(self)
        self.getTxtFileDownloadLinks()

    def getTxtFileDownloadLinks(self):
        self.txt_download_links = {
            'utf8': [],
            'big5': []
        }

        for i in range(1, 4):
            self.txt_download_links['utf8'].append('https://dl%i.wenku8.com/down.php?type=utf8&id=%i' %(i, self.id))
            self.txt_download_links['utf8'].append('https://dl%i.wenku8.com/down.php?type=utf8&id=%i&fname=%s' %(i, self.id, parse.quote(self.name)))

            self.txt_download_links['big5'].append('https://dl%i.wenku8.com/down.php?type=big5&id=%i' %(i, self.id))
            self.txt_download_links['big5'].append('https://dl%i.wenku8.com/down.php?type=big5&id=%i&fname=%s' %(i, self.id, parse.quote(self.name)))

        self.utf8_link = choice(self.txt_download_links['utf8'])

    def download(self, output_type='epub', download_all_volumes=True):

        downloadFiles([File(self.utf8_link, '%s.txt'%self.name)], os.getcwd())

        txtToEpub('%s\\%s.txt'%(os.getcwd(), self.name), self)


class Volume:
    def __init__(self, parent: Book, name: str) -> None:
        self.parent = parent
        self.name = name
        self.uuid = str(uuid.uuid4())
        self.chapters = []
        self.imgs_id = set()
        self.volume_id = 'ALL'
        self.imgs_url = set()
        self.emojis = []
        self.emojis_file = []

        self.info = '''
    
    <p>注意：</p>
    <p>本书使用LightNovelDownloader生成，软件开源。</p>
    <p>由KindleLN修改代码后，集成进网站中，提供推送服务。</p>
    <p>LightNovelDownloader链接：https://gitee.com/baishuibaiwater/lightnoveldownloader</p>
    <p>KindleLN源码链接：https://github.com/kindleLN/kindleLN</p>
    <p>---</p>
    <p>免责：</p>
    <p>本书仅供试看，下载后请在24h内删除，软件作者不担负任何责任。</p>
    <p>如果喜欢，请支持正版！</p>\n''' 


class Chapter:
    def __init__(self, parent: Volume, name: str, chapter_id: int) -> None:
        self.parent = parent
        self.name = name
        self.chapter_id = chapter_id

        heading_html = '''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"
  "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">

<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN" xmlns:epub="http://www.idpf.org/2007/ops" lang="zh-CN">
<head>
  <title>%s</title>
  <link href="flow0012.css" rel="stylesheet" type="text/css" />
</head>

<body>
  <div class="chapter" id="chapter"></div>
  <h1 class="kindle-cn-heading-1">%s</h1>
  <div class="kindle-cn-blockquote">
    <p>系列：%s</p>
    <p>来源：wenku8(txt->epub)</p>
  </div>
'''
        self.html = [heading_html%(self.name, self.name, self.parent.parent.name)]

    def getHtmlInEpub(self):
        with open(os.getcwd()+'\\epubFile\\OEBPS\\text%i.html'%self.chapter_id, 'w', encoding='utf-8') as h:
            h.writelines(self.html)


def txtToEpub(txt_path: str, book: Book) -> None:
    f = open(txt_path, 'r', encoding='utf-8')
    vol = Volume(book, book.name)
    cnt = 1
    ending_html = '''
</body>
</html>
'''

    try:
        shutil.rmtree('epubFile')
    finally:
        makeEpubFileDir(os.getcwd())


    for i in range(0, 5):
        f.readline()# 这一步是去除前摇

    while True:
        line = f.readline()
        if line.startswith(r'◆◇'):# 去除结尾，也起到if not line:break的作用
            break

        if not line.startswith('    ') and line != '\n':# 是Chap标题
            try:
                chap.html.append(ending_html)
                chap.getHtmlInEpub()
            except:
                pass

            chap = Chapter(vol, textReplacer(line, vol), cnt)
            vol.chapters.append(chap)
            cnt += 1

        else:# 是Chapter的内容
            line = line[4:]
            chap.html.append('<p>%s</p>\n'%textReplacer(line, vol))

    f.close()
    downloadFiles(vol.emojis_file, os.getcwd()+'\\epubFile\\OEBPS')
    
    makeEpubFile(vol)


            
def getInfo(book: Book) -> None:
    info_link = 'https://www.wenku8.net/book/%i.htm' %book.id
    info_page_soup = getPageHtmlSoup(info_link, encode='iso-8859-1', use_request=True)

    #这里拿到的是GBK编码
    main_soup = info_page_soup.find('div', style="width:99%;margin:auto;")
    
    # Name
    name_soup = main_soup.b
    book.name = name_soup.get_text()

    # Introduction
    introdaction = []
    try:
        introdaction_soup = main_soup.find_all('td', width="20%")
        for i in range(0, 5):
            text = introdaction_soup[i].get_text()
            if '小说作者：' in text:
                book.author = text.split('小说作者：')[-1]
                continue
            introdaction.append(text)
    except:
        pass
    book.introduction = introdaction

    # Cover
    pic_soup = main_soup.find('img', border="0", align="center")
    book.cover_pic_link = pic_soup.attrs['src']

