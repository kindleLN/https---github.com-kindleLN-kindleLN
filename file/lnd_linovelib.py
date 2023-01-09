# -*- coding: utf-8 -*-

import os
import shutil
import time
import uuid

from .utils import *


class Book:
    def __init__(self, id: int) -> None:
        self.id = id
        self.source = 'linovelib'
        self.info_url = 'https://w.linovelib.com/novel/%i.html' %self.id
        self.catalog_url = 'https://w.linovelib.com/novel/%i/catalog' %self.id
        self.last_chapter_is_js_chapter = False
        self.total_chapters = 0
        self.downloaded_chapters = 0

        self.volumes = []
        self.getInfo()
        self.getCatalog()


    def getCatalog(self) -> list:
        '''
        ### 根本就没想过写MD，请直接`转到定义`阅读

        这一整个函数架构比较【抽象】，在这里写个注释
        代码还有问题，连爆两个JS就GG了
        但是linovelib好像不会出这种问题！

        ---

        获取到soup后，扫描出装有单行本名&章节名的按钮
        然后for进去：

        [1]如果是单行本名：加入列表
        [1]再如果是章节：
            [2]如果是JS章节：标记本章
            [2]否则：正常获取url

            [3]如果单行本列表长度不为0：添加至最后一项
            [3]否则：新建一个名为【写在正文之前的内容】的单行本，并添加本章节

            [4]如果当前章节长度不为1：上一章节在本单行本获取
            [4]再如果当前单章节为1，且单行本总述不为1：上一章节为上本单行本最后一章
            [4]再如果手气不好，第一个章节就是JS（else）：continue

            [5]如果上一章节是js，且自己不是js：跑获取上一章节链接的函数

        [6]如果是js章节仍为True： ~~传进download()，在跑道倒数第二章节的时候留意一下footer即可~~
        #### 直接找用户！！！
        '''
        cnt = 1
        soup = getPageHtmlSoup(self.catalog_url)


        # 每一个单行本 
        vol_soup = soup.find('ol', id='volumes')
        vol_books = vol_soup.find_all('li')# 排除AD干扰

        for v in vol_books:
            if v.attrs['class'] == ['chapter-bar', 'chapter-li']:# volume
                vol_name = v.get_text()
                self.volumes.append(Volume(vol_name, self, cnt))
                cnt += 1
                continue

            elif v.attrs['class'] == ['chapter-li', 'jsChapter']:# chapter
                chap_name = v.get_text()
                is_js_chapter = False

                if 'java' in v.a.attrs['href']:
                    msg = '''[linovelib]!!警告!!在单行本【%s】章节【%s】找到了JS按钮，请坐和放宽，我们将尝试自行获取......'''
                    print(msg%(self.volumes[-1], chap_name))
                    is_js_chapter = True
                    chap_url = 'NULL'
                else:
                    chap_url = v.a.attrs['href']

                if len(self.volumes) != 0:
                    self.volumes[-1].chapters.append(Chapter(chap_name, chap_url, is_js_chapter))
                else:
                    vol_object = Volume('写在正文之前的内容', self, cnt)
                    vol_object.info += '''
    <p>---</p>
    <p>Q：这本单行本的书名是什么鬼？</p>
    <p>A：这是由于在linovelib中，有的书籍在单行本之前有一个名为《作品相关》的章节，不从属于任何一本单行本</p>
    <p>为了程序正常运行，故添加这样一本单行本，专门存放这些章节。</p>
    '''

                    self.volumes.append(vol_object)
                    vol_object.chapters.append(Chapter(chap_name, chap_url, is_js_chapter))
                    cnt += 1

                now_chapter = self.volumes[-1].chapters[-1]
                if len(self.volumes[-1].chapters) != 1:
                    last_chapter = self.volumes[-1].chapters[-2]
                elif len(self.volumes) != 1:
                    last_chapter = self.volumes[-2].chapters[-1]
                else:
                    continue

                if last_chapter.is_js_chapter and not is_js_chapter:
                    getLastChapterUrl(now_chapter, last_chapter)

        if is_js_chapter:
            # 概率极小，暂时不予理睬
            self.last_chapter_is_js_chapter = True
            raise RuntimeError('最后一章是JS章节，请人工下载。')


    def download(self, with_images=True, output_type='epub', download_all_volumes=True, **kwargs):
        data = []

        if download_all_volumes:
            for i in self.volumes:
                data.append(i.download(with_images=True, output_type='epub'))
        else:
            #print(kwargs)
            download_vol_names = kwargs['kwargs']['download_vol_names']
            download_vols = []

            # 将名字转换为Volume对象
            for i in download_vol_names:
                for j in self.volumes:
                    if j.name == i:
                        download_vols.append(j)

            for vol_book in download_vols:
                data.append(vol_book.download(with_images=with_images, output_type=output_type))

        return data


    def getInfo(self):
        soup = getPageHtmlSoup(self.info_url)

        self.name = soup.find('h2', class_='book-title').get_text()
        self.author = soup.find('div', class_='book-rand-a').span.get_text()


    def __str__(self) -> str:
        return self.name


class Volume:
    def __init__(self, name: str, parent: Book, volume_id: int) -> None:
        self.chapters = []
        self.name = name
        self.imgs_url = set()
        self.imgs_id = set()
        self.emojis = []
        self.emojis_file = []
        self.parent = parent
        self.volume_id = '%02d'%volume_id
        self.uuid = str(uuid.uuid4())

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


    def __str__(self) -> str:
        return self.name


    def download(self, with_images=True, output_type='epub'):
        counter = 1
        files_list = []
        
        try:
            shutil.rmtree('epubFile')
        except:
            pass
        makeEpubFileDir(os.getcwd())

        for chap in self.chapters:
            chap.download(self, counter, with_images=with_images, output_type=output_type)
            counter += 1
            self.parent.downloaded_chapters += 1

        for i in self.imgs_url:
            pic_name = i.split('/')[-1]
            self.imgs_id.add(pic_name)
            files_list.append(File(i, pic_name))
        downloadFiles(files_list, os.getcwd()+'\\epubFile\\OEBPS')
        downloadFiles(self.emojis_file, os.getcwd()+'\\epubFile\\OEBPS')

        for i in self.emojis_file:
            self.imgs_id.add(i.name)

        return makeEpubFile(self)
   

class Chapter:
    def __init__(self, name: str, short_url: str, is_js_chapter=False) -> None:
        self.name = name
        self.short_url = short_url
        self.is_js_chapter = is_js_chapter

    def __str__(self) -> str:
        return '[%s] %s'%(self.name, self.short_url)

    def download(self, parent: Volume, chapter_id: int, with_images=True, output_type='epub'):
        self.chapter_id = chapter_id
        self.parent = parent
        is_last_page = False
        counter = 1
        texts = []
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
    <p>单行本：%s</p>
    <p>来源：linovelib</p>
  </div>
'''
        ending_html = '''
</body>
</html>
'''


        while not is_last_page:

            url = getFullUrl(self.short_url, counter)
            soup = getPageHtmlSoup(url)
            
            # Texts&Images
            reading_page_data_soup = soup.find('div', id="acontent")
            for para in reading_page_data_soup:
                if output_type.lower() == 'epub': # EPUB

                    if para.get_text() == '\n':
                        continue
                    elif para.name == 'br':
                        texts.append('<p>&nbsp;</p>\n')
                    else:
                        texts.append('<p>%s</p>\n'%textReplacer(para.get_text(), self.parent))

                    try:
                        if para.name == 'img' and with_images:
                            parent.imgs_url.add(imgLinkFixer(para.attrs['src']))
                            pic_name = para.attrs['src'].split('/')[-1]
                            pic_id = pic_name.replace('.', '_')
                            texts.append('<img alt="'+pic_id+'" width="500" src="'+pic_name+'"/>\n')
                            continue
                        elif para.img.name == 'img' and with_images:
                            # 在https://www.linovelib.com/novel/2499/91785_6.html里发现了这么一个图片元素
                            # <img src="//img.linovelib.com/2/2499/109421/144517.jpg" border="0" class="imagecontent">
                            # 有点阴...考虑到有的图片并不会在插图出现，这里还得硬写修复器
                            parent.imgs_url.add(imgLinkFixer(para.img.attrs['src']))
                            pic_name = para.img.attrs['src'].split('/')[-1]
                            pic_id = pic_name.replace('.', '_')
                            texts.append('<img alt="'+pic_id+'" width="500" src="'+pic_name+'"/>\n')
                            continue
                    except:
                        pass


                else: #TXT
                    try:
                        if para.name == 'br':
                            texts.append('\n\n')
                        else:
                            texts.append('%s\n'%para.get_text()) # 我也不知道为什么TXT也要replace...
                    except:
                        pass


            # LastPageCheck
            footer_soup = soup.find('div', id="footlink")
            for i in footer_soup:
                if i.get_text() in  ['下一章', '返回目录']: #  爬了15页的后记...
                    is_last_page = True
            counter += 1


        if output_type.lower() == 'epub':
            with open(os.getcwd()+'\\epubFile\\OEBPS\\text%i.html'%self.chapter_id, 'w', encoding='utf-8') as f:
                f.write(heading_html%(self.name, self.name, self.parent.parent.name, self.parent.name))
                f.writelines(texts)
                f.write(ending_html)
        else:
            with open(os.getcwd()+'\\epubFile\\OEBPS\\text%i.txt'%self.chapter_id, 'w', encoding='utf-8') as f:
                f.writelines(texts)

  
def getFullUrl(short_url: str, id: int):
    tmp_list = short_url.split('.html')# /novel/8/1843
    tmp_url = 'https://w.linovelib.com%s_%i.html'%(tmp_list[0], id)

    return tmp_url


def imgLinkFixer(url: str):
    if url.startswith('https://img.linovelib.com'):
        return url
    elif url.startswith('//img.linovelib.com'):
        return 'https:'+url
    else:
        raise RuntimeError(
            '''在获取图片链接时出现了意料之外的情况.
            获取到的图片链接为 %s'''%url
        )


def getLastChapterUrl(now_chapter: Chapter, js_chapter: Chapter):
    '''没办法 只能用电脑版网页...'''
    url = 'https://www.linovelib.com%s'%now_chapter.short_url
    soup = getPageHtmlSoup(url, use_pc_ua=True)
    footer_soup = soup.find_all('p', class_="mlfy_page")
    for i in footer_soup[0]:
        if i.get_text() == '上一章':
            js_chapter.short_url = i.attrs['href']
            return