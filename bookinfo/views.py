# from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render, redirect
from django.http import Http404, HttpResponse

from .models import BookModel, VolumeModel
from file.models import CheckUpdateRequestModel, FileModel
from file.utils import makeCheckUpdateRequset, makePushRequest
from django.utils import timezone
from initer.utils import catchError


# Create your views here.
@catchError
def indexView(r):
    books = BookModel.objects.filter(is_deleted=False).order_by('-last_update_time')
    # msg = '您现在在的是【所有书籍】页面，需要热门推送请点击LOGO前往首页。'
    msg = '【2023年1月10日 17:40:34】主页还在建设中！'

    return render(r, 'bookinfo/index.html', {'books': books, 'r': r, 'msg': msg})


@catchError
def searchView(r):
    import jieba

    keywords = jieba.lcut_for_search(r.GET.get('keyword'))
    print('>>> [Search] %s'%str(keywords))

    del jieba # 真的卡...
    hitted_books = []
    books = []
    
    # 不想写相似度，直接用for&if x in xx写
    for b in BookModel.objects.order_by('-last_update_time'):# 也许用户会搜最近热门呢？
        cnt = 0

        for k in keywords:
            if k in b.name:
                cnt += 1
            if k in b.author.name:
                cnt += 1
        if cnt != 0:
            hitted_books.append((cnt, b))
    
    if hitted_books:
        hitted_books.sort()
        for (cnt, b) in hitted_books:
            books.append(b)

    msg = '''搜索到%i个对象。\n没有您要找的搜索结果？请确保输入内容准确，“宁少勿错”！另，您可试试别的译名。'''%len(hitted_books)

    return render(r, 'bookinfo/index.html', {'books': books, 'r': r, 'msg': msg})


@catchError
def infoView(r, id):
    downloading, downloaded = False, False
    msg, activate, email = None, None, None

    book_obj = get_object_or_404(BookModel, id=id, is_deleted=False)
    source = book_obj.source
    vols = VolumeModel.objects.filter(book=book_obj)
    
    last_update_req = CheckUpdateRequestModel.objects.filter(book=book_obj).order_by('-request_time')
    if last_update_req and (timezone.now() - last_update_req[0].request_time).days <= 2:# 这里是运用 A and B
        update_checked = True
    else:
        update_checked = False

    # 有已经下载的文件了
    if book_obj.has_static_files:
        downloaded = True
        for i in vols:
            f_obj = FileModel.objects.get(id=i.file_id)
            i.file_name = f_obj.name
    # 没有文件，但是来源的下载函数写好了，可以下载
    elif source is not None and source.has_download_function:
        makeCheckUpdateRequset(book_obj)
        update_checked = True
        downloading = True
        book_obj.has_static_files = True
        book_obj.save()
    # 剩下的没有文件无法下载



    if r.method == 'POST':
        print('?')
        file_id = []
        files = []
        dct = dict(r.POST)
        email = (dct['email'][0] + '@kindle.com').replace(' ', '')

        if 'all' in dct.keys():# 全部推送
            for i in vols:
                file_id.append(i.id)
        else:
            for i in dct.keys():# 排除干扰项
                if str(i) == 'csrfmiddlewaretoken' or str(i) == 'email':
                    continue
                elif dct[str(i)] == ['on']:# 如果开了就加进去
                    file_id.append(int(i))
                    # 其实这里可以利用不选中无key的特性，懒得弄了

        # 转换为Vol对象
        for i in file_id:
            file = VolumeModel.objects.get(id=i)
            files.append(file)

        if makePushRequest(email, files):
            msg = '成功登记 %i 个对象至 %s.'%(len(files), email)
        else:
            msg = '您没有对邮箱 %s 进行过验证，我们不能确保文件可以送至您的Kindle账号。\
                请点击【验证邮箱】来验证并激活您的邮箱。（不必担心，这完全免费！）'%email
            activate = True

    dct = {
        'book': book_obj, 
        'downloading': downloading, 
        'downloaded': downloaded, 
        'update_checked': update_checked,
        'vols': vols,
        'msg': msg,
        'activate': activate, 
        'r': r, 
        'email':email, 
    }


    return render(r, 'bookinfo/info.html', context=dct)


@catchError
def checkUpdateView(r, id):
    book_obj = get_object_or_404(BookModel, id=id, is_deleted=False)
    last_update_req = CheckUpdateRequestModel.objects.filter(book=book_obj).order_by('-request_time')
    if last_update_req and (timezone.now() - last_update_req[0].request_time).days <= 2:# 这里是运用 A and B
        raise Http404

    makeCheckUpdateRequset(book_obj)

    return redirect('/info/%i'%id) # 下下策
