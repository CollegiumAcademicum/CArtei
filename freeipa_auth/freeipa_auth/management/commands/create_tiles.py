# freeipa_auth/management/commands/create_tiles.py
from django.core.management.base import BaseCommand
from django.urls import get_resolver, reverse, NoReverseMatch
from freeipa_auth.models import Tile

class Command(BaseCommand):
    help = 'Erstellt automatisch Kacheln für alle verfügbaren URLs, falls sie nicht existieren'

    def handle(self, *args, **kwargs):
        # Hole alle URLs aus der URL-Konfiguration
        urls = get_resolver().url_patterns

        # Filtere nur die URLs, die angezeigt werden sollen (ohne Admin, Auth etc.)
        for pattern in urls:
            if hasattr(pattern, 'name') and pattern.name:
                # Überspringe URLs ohne Namen oder spezifische Seiten wie den Admin
                if pattern.name not in ['admin', 'login', 'logout']:
                    try:
                        # URL umkehren, um den vollständigen Link zu erhalten
                        link = reverse(pattern.name)
                    except NoReverseMatch:
                        continue  # Falls `reverse` fehlschlägt, überspringe diese URL

                    # Überprüfen, ob die Kachel bereits existiert (gleicher Titel oder Link)
                    if not Tile.objects.filter(title=pattern.name.capitalize(), link=link).exists():
                        # Erstelle eine Kachel mit dem Namen der URL und dem Link, falls sie noch nicht existiert
                        Tile.objects.create(title=pattern.name.capitalize(), link=link)
                        self.stdout.write(f"Kachel '{pattern.name.capitalize()}' für URL '{link}' erstellt.")
                    else:
                        self.stdout.write(f"Kachel '{pattern.name.capitalize()}' für URL '{link}' existiert bereits.")
