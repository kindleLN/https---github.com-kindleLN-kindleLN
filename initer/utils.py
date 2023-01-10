import json
import traceback

from .models import ErrorModel


def catchError(func):
    """ 
    使用这个装饰器，可以捕获报错信息，并存储于【initer/ErrorModel】中。

    一般而言，除了`@admin.action()`，您应该把这个装饰器放在所有装饰器之前

    注意：只是【捕获】，该报的还是得报
    """

    def innner(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            _info = traceback.format_exc()
            _repr = repr(e)
            try:
                _by = func.__name__
            except:
                _by = '[Error]这个对象没有.__name__'

            e = ErrorModel.objects.create(
                raised_by=_by,
                error_repr=_repr,
                error_info=_info,
            )
            e.save()

            raise

    return innner

@catchError
def replaceTemplatesText(old_contact_email, new_contact_email):
    with open('mainpage\\templates\\mainpage\\base.html', 'r', encoding='utf-8') as f:
        html = f.read()

    html = html.replace(old_contact_email, new_contact_email)

    with open('mainpage\\templates\\mainpage\\base.html', 'w', encoding='utf-8') as f:
        html = f.write(html)