from django.db import models
from django.contrib.auth.models import User

class Release(models.Model):
    release_author = models.ForeignKey(User, on_delete=models.PROTECT)
    desc = models.TextField(default='')
    updated_at = models.DateTimeField()
    project_version = models.PositiveSmallIntegerField(default="0")
    application_version = models.PositiveSmallIntegerField(default="0")
    previous =  models.ForeignKey('self', on_delete=models.SET_DEFAULT, null=True, default=None)
    def __str__(self):
        return str(self.project_version)+'.'+str(self.application_version)   
    
class Project(models.Model):
    name = models.CharField(max_length=255)
    desc = models.TextField(default='')
    updated_at= models.DateTimeField(auto_now=True)
    owner = models.ForeignKey(User, on_delete=models.PROTECT)
    release = models.ForeignKey(Release, on_delete=models.PROTECT, null=True, default=None)
    def __str__(self):
        return self.name
    
class ProjectUser(models.Model):
    updated_at = models.DateField(auto_now=True)
    user = models.ForeignKey(User, on_delete=models.PROTECT)
    project = models.ForeignKey(Project, on_delete=models.PROTECT) 
    role = models.CharField(max_length=24, choices=PROJECT_ROLE, default="RO")
    def __str__(self):
        return self.user.username + ' - ' + self.project.name    

class Application(models.Model):
    name = models.CharField(max_length=255)
    desc = models.TextField(default='')
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    updated_at= models.DateTimeField(auto_now=True)
    release = models.ForeignKey(Release, on_delete=models.PROTECT, null=True, default=None)
    def __str__(self):
        return self.name
    
class Type(models.Model):    
    cat = models.CharField(max_length=24, choices=TYPE_CAT, default='DTI')
    name = models.CharField(max_length=255)
    domain = models.CharField(max_length=255)
    desc = models.TextField(default='')
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    native_type = models.TextField(default='')
    size = models.PositiveSmallIntegerField(null=True, blank=True)
    enum = models.BooleanField(default=False)
    owner = models.ForeignKey(User, on_delete=models.PROTECT)
    previous = models.ForeignKey('self', on_delete=models.SET_DEFAULT, null=True, default=None)
    status = models.CharField(max_length=20, choices=HISTORY_STATUS, default="NEW")
    updated_at= models.DateTimeField()    
    
