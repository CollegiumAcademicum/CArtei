# myapp/views.py

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django_auth_ldap.backend import LDAPBackend
from .models import Tile, UserTileSetting
from django.http import JsonResponse

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


@login_required
def dashboard(request):
    # Überprüfe, ob `UserTileSetting`-Einträge für den aktuellen Benutzer existieren
    existing_user_tiles = UserTileSetting.objects.filter(user=request.user)
    existing_tile_ids = existing_user_tiles.values_list('tile_id', flat=True)

    # Initialisiere nur die `Tile`-Einträge, die noch nicht für diesen Benutzer existieren
    new_tiles = Tile.objects.exclude(id__in=existing_tile_ids)
    if new_tiles.exists():
        for index, tile in enumerate(new_tiles, start=len(existing_user_tiles)):
            UserTileSetting.objects.create(user=request.user, tile=tile, position=index)

    # Lade nur die `UserTileSetting`-Einträge für den aktuellen Benutzer
    user_tiles = UserTileSetting.objects.filter(user=request.user).order_by('position')
    context = {'user_tiles': user_tiles}
    return render(request, 'dashboard.html', context)


@login_required
def save_tile_order(request):
    if request.method == 'POST':
        order = request.POST.getlist('order[]')
        if not order:
            return JsonResponse({'status': 'error', 'message': 'Keine Reihenfolge übergeben'})

        # Aktualisiere die `position`-Felder basierend auf der übergebenen Reihenfolge
        for index, tile_id in enumerate(order):
            try:
                user_tile_setting = UserTileSetting.objects.get(user=request.user, tile_id=tile_id)
                user_tile_setting.position = index
                user_tile_setting.save()
            except UserTileSetting.DoesNotExist:
                return JsonResponse({'status': 'error', 'message': f'Kachel mit ID {tile_id} existiert nicht.'})

        return JsonResponse({'status': 'success'})
    else:
        return JsonResponse({'status': 'error', 'message': 'Ungültige Anfrage'})