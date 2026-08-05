from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def require_group(*groups):
    def decorator(view_func):
        @wraps(view_func)
        def _check(request, *args, **kwargs):
            if not request.user.groups.filter(name__in=groups).exists():
                raise PermissionDenied
            return view_func(request, *args, **kwargs)
        return login_required(_check)
    return decorator
