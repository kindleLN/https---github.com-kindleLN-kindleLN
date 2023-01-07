# from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from .models import BookModel


# Create your views here.
def infoView(r, id):
    downloading, downloaded = False, False

    book_obj = get_object_or_404(BookModel, id=id, is_deleted=False)
    source = book_obj.source

    # 有已经下载的文件了
    if book_obj.has_static_files:
        downloaded = True
    # 没有文件，但是来源的下载函数写好了，可以下载
    elif source is not None and source.has_download_function:
        from file.utils import downloadBook
        downloadBook(book_obj.novel_id_in_source, source.name)
        downloading = True
    # 剩下的没有文件无法下载

        
    dct = {
        'book_obj': book_obj, 
        'downloading': downloading, 
        'downloaded': downloaded, 
    }
    return render(r, 'bookinfo/info.html', context=dct)


