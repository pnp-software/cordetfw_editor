from django.db import models
from django.contrib.auth.models import User
from editor.choices import SPEC_ITEM_CAT, VER_STATUS, HISTORY_STATUS,\
                           REQ_KIND, DI_KIND, DIT_KIND, MODEL_KIND, PCKT_KIND, \
                           PCKT_PAR_KIND, PCKT_APP_KIND, VER_ITEM_KIND, REQ_VER_METHOD 

class Release(models.Model):
    release_author = models.ForeignKey(User, on_delete=models.PROTECT)
    desc = models.TextField()
    updated_at = models.DateTimeField()
    project_version = models.PositiveSmallIntegerField(default="0")
    application_version = models.PositiveSmallIntegerField(default="0")
    previous =  models.OneToOneField('self', on_delete=models.SET_DEFAULT, null=True, default=None)
    def __str__(self):
        return str(self.project_version)+'.'+str(self.application_version)   
    
class Project(models.Model):
    name = models.CharField(max_length=255)
    desc = models.TextField()
    updated_at= models.DateTimeField(auto_now=True)
    owner = models.ForeignKey(User, related_name='owned_projects', on_delete=models.PROTECT)
    release = models.ForeignKey(Release, on_delete=models.PROTECT)
    def __str__(self):
        return self.name
    
class ProjectUser(models.Model):
    updated_at = models.DateField(auto_now=True)
    user = models.ForeignKey(User, related_name='used_projects', on_delete=models.PROTECT)
    project = models.ForeignKey(Project, related_name='project_users', on_delete=models.PROTECT)
    def __str__(self):
        return self.user.username + ' as user of: ' + self.project.name    

class Application(models.Model):
    name = models.CharField(max_length=255)
    desc = models.TextField()
    project = models.ForeignKey(Project, related_name='applications', on_delete=models.PROTECT)
    updated_at= models.DateTimeField(auto_now=True)
    release = models.ForeignKey(Release, on_delete=models.PROTECT)
    def __str__(self):
        return self.name

class ValSet(models.Model):
    updated_at = models.DateField(auto_now=True)
    project = models.ForeignKey(Project, related_name='val_sets', on_delete=models.PROTECT) 
    name = models.CharField(max_length=24, default="Default")
    desc = models.TextField()
    def __str__(self):
        return self.name

class SpecItem(models.Model):    
    cat = models.CharField(max_length=24, choices=SPEC_ITEM_CAT)
    name = models.CharField(max_length=255)
    domain = models.CharField(max_length=255)
    project = models.ForeignKey(Project, related_name='project_spec_items', on_delete=models.PROTECT)
    application = models.ForeignKey(Application, related_name='application_spec_items', 
                                    on_delete=models.PROTECT, null=True, default=None)
    title = models.CharField(max_length=255)
    desc = models.TextField(blank=True, default='')
    owner = models.ForeignKey(User, related_name='owned_spec_items', on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=HISTORY_STATUS, default='NEW')
    updated_at = models.DateTimeField()  
    previous = models.OneToOneField('self', on_delete=models.SET_DEFAULT, null=True, default=None)
    rationale = models.TextField(blank=True, default='')
    remarks = models.TextField(blank=True, default='')
    val_set = models.ForeignKey(ValSet, related_name='val_set_spec_items', on_delete=models.PROTECT)
    p_link = models.ForeignKey('self', related_name='p_children', on_delete=models.PROTECT, null=True, blank=True, default=None)
    s_link = models.ForeignKey('self', related_name='s_children', on_delete=models.PROTECT, null=True, blank=True, default=None)
    p_kind = models.CharField(max_length=24, choices=REQ_KIND+DI_KIND+DIT_KIND+MODEL_KIND+PCKT_KIND+\
                                                     PCKT_PAR_KIND+PCKT_APP_KIND+VER_ITEM_KIND)
    s_kind = models.CharField(max_length=24, choices=VER_STATUS)
    value = models.TextField(blank=True, default='')
    t1 = models.TextField(blank=True, default='')
    t2 = models.TextField(blank=True, default='')
    t3 = models.TextField(blank=True, default='')
    t4 = models.TextField(blank=True, default='')
    t5 = models.TextField(blank=True, default='')
    n1  = models.IntegerField(blank=True, default=0)
    n2  = models.IntegerField(blank=True, default=0)
    n3  = models.IntegerField(blank=True, default=0)
    def __str__(self):
        return self.domain + ':' + self.name + ' (' + self.title + ')'
  
class VerItemToSpecItem(models.Model):
    ver_item = models.ForeignKey(SpecItem, related_name='spec_item_links', on_delete=models.PROTECT) 
    spec_item = models.ForeignKey(SpecItem, related_name='ver_item_links', on_delete=models.PROTECT)   
    title = models.CharField(max_length=255)
    desc = models.TextField(blank=True, default='')
    
