

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import ErrorModel
from .utils import catchError


# Create your views here.

@catchError
@login_required
def indexView(r):
    errors = ErrorModel.objects.order_by('-raised_time').order_by('read')
    num = len(errors)

    return render(r, 'initer/index.html', context={'errors': errors, 'num': num, 'r': r})


@catchError
@login_required
def infoView(r, id):
    error = ErrorModel.objects.get(id=id)
    error.read = True
    error.save()

    return render(r, 'initer/info.html', context={'e': error, 'r': r})
