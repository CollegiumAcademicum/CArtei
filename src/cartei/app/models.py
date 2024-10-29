from django.contrib.auth.models import User
from django.db import models


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
        unique_together = ("user", "tile")


class Entry(models.Model):
    name = models.CharField(max_length=100)
    pronouns = models.CharField(max_length=50)
    birthday = models.DateField()
    phone_number = models.CharField(max_length=20)
    email = models.EmailField()
    study = models.CharField(max_length=150)
    institution = models.CharField(max_length=150)
    enrollment_certificate = models.FileField(upload_to="certificates/", blank=True, null=True)

    def __str__(self):
        return f"{self.name}"
