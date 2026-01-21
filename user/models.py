from django.db import models
from django.contrib.auth.models import User
# Create your models here.

class UserTypeChoices(models.TextChoices):
    'Rater' = 'RATER', 'Rater'
    'Viewer' = 'VIEWER', 'Viewer'
    'Provider' = 'PROVIDER', 'Provider'


class UserProfile(models.Model):
    '''
    Model to store the user profile information
    '''    
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    user_type = models.CharField(max_length=10, choices=UserTypeChoices.choices, default=UserTypeChoices.RATER)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'