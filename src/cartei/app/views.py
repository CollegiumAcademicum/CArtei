import csv

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django_auth_ldap.backend import LDAPBackend

from .forms import EntryForm
from .models import Entry, Tile, UserTileSetting


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

    return render(
        request,
        "profile.html",
        {
            "username": user.username,
            "groups": groups,
        },
    )


@login_required
def dashboard(request):
    # Suchanfrage aus den GET-Parametern abrufen
    query = request.GET.get("search", "")

    # Überprüfe, ob `UserTileSetting`-Einträge für den aktuellen Benutzer existieren
    existing_user_tiles = UserTileSetting.objects.filter(user=request.user)
    existing_tile_ids = existing_user_tiles.values_list("tile_id", flat=True)

    # Initialisiere nur die `Tile`-Einträge, die noch nicht für diesen Benutzer existieren
    new_tiles = Tile.objects.exclude(id__in=existing_tile_ids)
    if new_tiles.exists():
        for index, tile in enumerate(new_tiles, start=len(existing_user_tiles)):
            UserTileSetting.objects.create(user=request.user, tile=tile, position=index)

    # Lade nur die `UserTileSetting`-Einträge für den aktuellen Benutzer und filtere nach der Suchanfrage
    user_tiles = UserTileSetting.objects.filter(user=request.user).order_by("position")

    # Filtern der `user_tiles` basierend auf dem Titel des Tiles, wenn eine Suchanfrage vorhanden ist
    if query:
        user_tiles = user_tiles.filter(tile__title__icontains=query)

    context = {"user_tiles": user_tiles, "query": query}
    return render(request, "dashboard.html", context)


@login_required
def search_suggestions(request):
    query = request.GET.get("q", "")
    suggestions = []

    if query:
        # Suche alle `Tile`-Objekte, deren Titel die Anfrage enthalten
        matching_tiles = Tile.objects.filter(title__icontains=query).values("id", "title")
        suggestions = list(matching_tiles)

    return JsonResponse({"suggestions": suggestions})


@login_required
def save_tile_order(request):
    if request.method == "POST":
        order = request.POST.getlist("order[]")
        if not order:
            return JsonResponse({"status": "error", "message": "Keine Reihenfolge übergeben"})

        # Aktualisiere die `position`-Felder basierend auf der übergebenen Reihenfolge
        for index, tile_id in enumerate(order):
            try:
                user_tile_setting = UserTileSetting.objects.get(user=request.user, tile_id=tile_id)
                user_tile_setting.position = index
                user_tile_setting.save()
            except UserTileSetting.DoesNotExist:
                return JsonResponse({"status": "error", "message": f"Kachel mit ID {tile_id} existiert nicht."})

        return JsonResponse({"status": "success"})
    else:
        return JsonResponse({"status": "error", "message": "Ungültige Anfrage"})


@login_required()
def entry_list(request):
    search_query = request.GET.get("search", "")
    if search_query:
        entries = Entry.objects.filter(name__icontains=search_query)
    else:
        entries = Entry.objects.all()
    return render(request, "entry_list.html", {"entries": entries})


@login_required()
def entry_create(request):
    if request.method == "POST":
        form = EntryForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect("entry_list")
    else:
        form = EntryForm()
    return render(request, "entry_form.html", {"form": form})


@login_required()
def entry_update(request, pk):
    entry = get_object_or_404(Entry, pk=pk)
    if request.method == "POST":
        form = EntryForm(request.POST, request.FILES, instance=entry)
        if form.is_valid():
            form.save()
            return redirect("entry_list")
    else:
        form = EntryForm(instance=entry)
    return render(request, "entry_form.html", {"form": form})


@login_required()
def entry_delete(request, pk):
    entry = get_object_or_404(Entry, pk=pk)
    if request.method == "POST":
        entry.delete()
        return redirect("entry_list")
    return render(request, "entry_confirm_delete.html", {"entry": entry})


@login_required()
def populate_from_csv(request):
    if request.method == "POST" and request.FILES["csv_file"]:
        csv_file = request.FILES["csv_file"]
        decoded_file = csv_file.read().decode("utf-8").splitlines()
        reader = csv.DictReader(decoded_file)
        for row in reader:
            Entry.objects.create(
                name=row["Name"],
                pronouns=row["Pronomen"],
                birthday=row["Geburtsdatum"],
                phone_number=row["Telefonnummer"],
                email=row["E-Mail"],
                study=row["Studiengang/Ausbildung"],
                institution=row["Hochschule/Ausbildungsstätte"],
            )
        return redirect("entry_list")
    return render(request, "populate_from_csv.html")
