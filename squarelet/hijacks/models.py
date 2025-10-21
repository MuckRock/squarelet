# hijacks/models.py
from django.db import models
from squarelet.users.models import User

class HijackLog(models.Model):
    hijacker = models.ForeignKey(User, on_delete=models.CASCADE, related_name="hijacker_logs")
    hijacked = models.ForeignKey(User, on_delete=models.CASCADE, related_name="hijacked_logs")
    action = models.CharField(max_length=10, choices=[("start", "Started"), ("end", "Ended")])
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.hijacker} → {self.hijacked} ({self.action})"
