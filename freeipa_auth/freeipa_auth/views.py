# myapp/views.py

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django_auth_ldap.backend import LDAPBackend

@login_required
def profile(request):
    user = request.user

    # Initialize the LDAPBackend
    ldap_backend = LDAPBackend()
    ldap_user = ldap_backend.populate_user(user.username)
    
    if ldap_user:
        # Fetch groups from the LDAP
        groups = ldap_user.ldap_user.group_names
    else:
        groups = []

    return render(request, 'profile.html', {
        'username': user.username,
        'groups': groups,
    })
