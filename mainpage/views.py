from django.shortcuts import render, redirect
from django.http import Http404, HttpResponse
from bookinfo.models import BookModel
from django.urls import reverse

# Create your views here.
def MainpageView(r):
    ''' 这个页面用来随机推荐书籍 '''
    # return HttpResponse('MAINPAGE HERE.')
    return redirect(reverse('info:index'))