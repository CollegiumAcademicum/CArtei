# signals.py (optional für Initialisierung)
from django.db.models.signals import post_save
from django.contrib.auth.models import User
from .models import Tile, UserTileSetting

def create_user_tiles(sender, instance, created, **kwargs):
    if created:
        for index, tile in enumerate(Tile.objects.all()):
            UserTileSetting.objects.create(user=instance, tile=tile, position=index)

post_save.connect(create_user_tiles, sender=User)
