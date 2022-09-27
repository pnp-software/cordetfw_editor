from import_export import resources
from editor.convert import convert_db_to_edit
from editor.models import Release, Project, ProjectUser, Application, \
                          SpecItem, ValSet

class ReleaseResource(resources.ModelResource):
    class Meta:
        model = Release

    def dehydrate_release_author(self, release):
        return str(release.release_author)

        
class ProjectResource(resources.ModelResource):
    class Meta:
        model = Project

    def dehydrate_owner(self, project):
        return str(project.owner)
        
                
class ApplicationResource(resources.ModelResource):
    class Meta:
        model = Application
        
class ProjectUserResource(resources.ModelResource):
    class Meta:
        model = ProjectUser        
        
    def dehydrate_user(self, project_user):
        return str(project_user.user)

        
class ValSetResource(resources.ModelResource):
    class Meta:
        model = ValSet                  

class SpecItemResource(resources.ModelResource):
    class Meta:
        model = SpecItem        

    def dehydrate_desc(self, spec_item):
        return convert_db_to_edit(spec_item.desc)

    def dehydrate_rationale(self, spec_item):
        return convert_db_to_edit(spec_item.rationale)

    def dehydrate_remarks(self, spec_item):
        return convert_db_to_edit(spec_item.remarks)
        
    def dehydrate_implementation(self, spec_item):
        return convert_db_to_edit(spec_item.implementation)
        
    def dehydrate_value(self, spec_item):
        return convert_db_to_edit(spec_item.value)

    def dehydrate_t1(self, spec_item):
        return convert_db_to_edit(spec_item.t1)

    def dehydrate_t2(self, spec_item):
        return convert_db_to_edit(spec_item.t2)
        
    def dehydrate_t3(self, spec_item):
        return convert_db_to_edit(spec_item.t3)
        
    def dehydrate_t4(self, spec_item):
        return convert_db_to_edit(spec_item.t4)
        
    def dehydrate_t5(self, spec_item):
        return convert_db_to_edit(spec_item.t5)
        
    def dehydrate_owner(self, spec_item):
        return str(spec_item.owner)
        
        
