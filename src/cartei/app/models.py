from django.db import models


class Entry(models.Model):
    name = models.CharField(max_length=100)
    pronouns = models.CharField(max_length=50)
    birthday = models.DateField()
    phone_number = models.CharField(max_length=20)
    email = models.EmailField()
    study = models.CharField(max_length=150)
    institution = models.CharField(max_length=150)
    enrollment_certificate = models.FileField(upload_to='certificates/', blank=True, null=True)

    def __str__(self):
        return f"{self.name}"
