from django.shortcuts import render
from django.http import Http404, HttpResponse
from bookinfo.models import BookModel

# Create your views here.
def MainpageView(r):
    '''这个页面用来随机推荐书籍'''
    return HttpResponse('MAINPAGE HERE.')