from django.db import models
from django.contrib.auth.models import User

class Tile(models.Model):
    id = models.BigAutoField(primary_key=True)  # Definiert explizit den Primärschlüssel
    title = models.CharField(max_length=100)
    link = models.URLField()
    
    def __str__(self):
        return self.title

class UserTileSetting(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    tile = models.ForeignKey(Tile, on_delete=models.CASCADE)
    position = models.IntegerField()

    class Meta:
        unique_together = ('user', 'tile')

