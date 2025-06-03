from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from django.utils import timezone

class StreetSearch(models.Model):
    query = models.CharField(max_length=255)
    created_at = models.DateTimeField(default=timezone.now)
    total_trees = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, default='processing')
    processing_message = models.CharField(max_length=255, null=True, blank=True, default='Initializing search...')
    # Route information
    start_lat = models.FloatField(null=True, blank=True)
    start_lng = models.FloatField(null=True, blank=True)
    end_lat = models.FloatField(null=True, blank=True)
    end_lng = models.FloatField(null=True, blank=True)
    
    def __str__(self):
        return f"{self.query} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"

class StreetViewImage(models.Model):
    street_search = models.ForeignKey(StreetSearch, on_delete=models.CASCADE, related_name='images')
    image_path = models.CharField(max_length=255)
    location = models.CharField(max_length=255, null=True, blank=True)
    tree_count = models.IntegerField(null=True, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    sequence_number = models.IntegerField(default=0)
    
    def __str__(self):
        return f"Image {self.sequence_number} for {self.street_search.query}"

class Subscription(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    start_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField(default=timezone.now)
    active = models.BooleanField(default=False)

    def activate(self):
        self.start_date = timezone.now()
        self.end_date = self.start_date + timedelta(days=30)
        self.active = True
        self.save()

    def is_active(self):
        return self.active and self.end_date > timezone.now()

