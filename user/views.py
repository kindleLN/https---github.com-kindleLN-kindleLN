import datetime

from django.contrib.auth import authenticate, login, logout
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from file.models import EmailModel
from initer.utils import catchError

from .utils import sendEmail


# Create your views here.
@catchError
def loginView(r):
    if r.method != "POST":  # 不是POST，空表过去
        return render(r, "user/login.html", {"r": r})

    else:  # 是POST，验证
        name = r.POST.get("username")
        pwd = r.POST.get("pwd")
        remember = r.POST.get("rememberme")
        print(remember)
        user = authenticate(r, username=name, password=pwd)

        if user is not None:  # 密码正确！
            login(r, user)

            if remember is None:  # 没勾
                r.session.set_expiry(0)

            return HttpResponseRedirect(reverse("file:index"))
        else:  # :(
            return render(r, "user/login.html", context={"msg": "用户名或密码错误。", "r": r})


@catchError
def logoutView(r):
    logout(r)
    return HttpResponseRedirect(reverse("mainpage:mainpage"))


@catchError
def activateEmailView(r, email, step):
    email_obj = get_object_or_404(EmailModel, email=email.lower(), active=False)

    if r.method == "GET":
        if step != 1:
            dct = {"email": email, "r": r}
        else:
            # 如果是首次发送，就无法【-】
            try:
                if (timezone.now() - email_obj.last_send_code_time).seconds <= 600:
                    dct = {"msg": "已成功发送验证码，请在10分钟内输入。", "sent": True, "r": r}
            except:
                raise Http404

        return render(r, "user/enter_code.html", dct)
    else:
        code = r.POST.get("code")
        if (
            int(code) == email_obj.code
            and (timezone.now() - email_obj.last_send_code_time).seconds <= 600
        ):
            email_obj.active = True
            email_obj.save()
            dct = {
                "time": datetime.datetime.now().strftime("%Y-%m-%d"),
                "email": email,
                "r": r,
            }

            return render(r, "user/activate_success.html", dct)
        else:
            try:
                if (timezone.now() - email_obj.last_send_code_time).seconds <= 600:
                    dct = {"msg": "验证码错误，请检查输入", "sent": True, "r": r}
            except:
                raise Http404

            return render(r, "user/enter_code.html", dct)


@catchError
def sendCodeView(r, email):
    email_obj = get_object_or_404(EmailModel, email=email.lower(), active=False)
    sendEmail(email_obj)
    email_obj.last_send_code_time = timezone.now()
    email_obj.save()

    return redirect("user:activate_email", email=email, step=1)
