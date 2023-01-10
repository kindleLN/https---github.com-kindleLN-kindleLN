

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import ErrorModel
from .utils import catchError


# Create your views here.

@catchError
@login_required
def indexView(r):
    errors_read = ErrorModel.objects.filter(read=True).order_by('-raised_time')
    errors_unread = ErrorModel.objects.filter(read=False).order_by('-raised_time')
    num = len(errors_unread)

    dct = {'errors_read': errors_read, 'num': num, 'r': r, 'errors_unread': errors_unread,}

    return render(r, 'initer/index.html', dct)


@catchError
@login_required
def infoView(r, id):
    error = ErrorModel.objects.get(id=id)
    error.read = True
    error.save()

    return render(r, 'initer/info.html', context={'e': error, 'r': r})
