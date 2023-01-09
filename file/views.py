import os

from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render, reverse
from django.urls import reverse

from .models import FileModel
from .utils import *

# Create your views here.
@login_required
def indexView(r):
    if r.method != 'GET' or not r.user.is_superuser:
        raise Http404
    files = FileModel.objects.order_by('-upload_time')
    ua = r.headers["User-Agent"]
    request_from_kindle = (judgeUa(ua)=='k')

    return render(r, 'file/index.html', {'files': files, 'request_from_kindle': request_from_kindle, 'r': r})


@login_required
def deleteConfirmationView(r, file_name):
    if r.method != 'GET' or not r.user.is_superuser:
        raise Http404

    file = get_object_or_404(FileModel, name=file_name)
    
    return render(r, 'file/delete_confirmation.html', {'file': file, 'r': r})


@login_required
def deleteView(r, path):
    if not r.user.is_superuser:
        raise Http404

    name = os.path.basename(path)
    print('>>> [deleteView]', name)
    file = get_object_or_404(FileModel, name=name)
    file.delete()
    return redirect('file:index')


@login_required
def renameView(r, file_name):
    doCheckUpdateRequest()
    if not r.user.is_superuser:
        raise Http404('应该是503')

    if r.method == 'GET':
        print(file_name)
        file = get_object_or_404(FileModel, name=file_name)

        return render(r, 'file/rename.html', {'file': file, 'r': r})

    else:
        new_name = r.POST.get('new_name')
        old_name = r.path.split('/')[-2] # 这里真的不会写，谁改一改

        rename(old_name, new_name)

        return HttpResponseRedirect(reverse('file:index'))
        

@login_required
def uploadView(r, path):
    if r.method != 'POST' or not r.user.is_superuser:
        raise Http404

    files = r.FILES.getlist("files")
    handleUploadFiles(files, r.user)

    return HttpResponseRedirect(reverse('file:index'))


@login_required
def downloadView(r, path):
    if r.method != 'GET' or not r.user.is_superuser:
        raise Http404

    name = os.path.basename(path)
    file = get_object_or_404(FileModel, name=name)
    response = FileResponse(open(file.getFilePath(), 'rb'))
    response["Content-Length"] = file.size
    response['Content-Disposition'] = 'attachment;filename=%s'%name

    return response

