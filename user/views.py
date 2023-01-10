from django.contrib.auth import authenticate, login, logout
from django.http import HttpResponseRedirect
from django.shortcuts import render
from initer.utils import catchError
from django.urls import reverse


# Create your views here.
@catchError
def loginView(r):
    if r.method != 'POST':#不是POST，空表过去
        return render(r, 'user/login.html', {'r': r})

    else:# 是POST，验证
        name = r.POST.get('username')
        pwd = r.POST.get('pwd')
        remember = r.POST.get('rememberme')
        print(remember)
        user = authenticate(r, username=name, password=pwd)

        if user is not None:# 密码正确！
            login(r, user)

            if remember is None:# 没勾
                r.session.set_expiry(0)

            return HttpResponseRedirect(reverse('file:index'))
        else:# :(
            return render(r, 'user/login.html', context={'msg': '用户名或密码错误。', 'r': r})


@catchError
def logoutView(r):
    logout(r)
    return HttpResponseRedirect(reverse('info:index'))