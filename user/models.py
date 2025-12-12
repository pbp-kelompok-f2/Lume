from django.contrib.auth.models import AbstractUser
from django.db import models

# Create your models here.

class User(AbstractUser):
    phone = models.CharField(max_length=30, blank=True)
    profile_picture = models.URLField(max_length=500, blank=True, null=True)
    def __str__(self):
        return self.username