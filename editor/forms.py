import re
from django import forms
from django.forms import formsets
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from itertools import chain
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit, Button
from .utilities import get_user_choices, get_p_kind_choices, get_s_kind_choices
from editor.convert import pattern_edit, pattern_db, convert_edit_to_db
from editor.models import Application, ValSet, Project, SpecItem
from editor.configs import configs, get_p_link_choices, get_s_link_choices, do_cat_specific_checks
from editor import ext_cats

# Regex pattern for 'domain' and 'name' (alphanumeric characters and underscores)
pattern_name = re.compile('[a-zA-Z0-9_]+$')     

class ProjectForm(forms.Form):
    name = forms.CharField()
    owner = forms.ChoiceField(choices=())
    cats = forms.CharField()
    description = forms.CharField(widget=forms.Textarea)
    predefined_cats = ''
    for item in configs['cats'].keys():
        predefined_cats = predefined_cats + item + ', '
    predefined_cats = predefined_cats[:-2] if len(predefined_cats)>2 else predefined_cats
    
    def __init__(self, project, *args, **kwargs):
        super(ProjectForm, self).__init__(*args, **kwargs)
        self.fields['owner'].choices = get_user_choices(project)
        self.helper = FormHelper(self)
        self.helper.wrapper_class = 'row'
        self.helper.label_class = 'col-md-2'
        self.helper.field_class = 'col-md-8'
        self.helper.add_input(Submit('submit', 'Submit'))
        self.fields['description'].widget.attrs.update(rows = 2)
        self.fields['cats'].label = 'Categories'
        self.fields['cats'].help_text = 'A subset of: ' + self.predefined_cats

    def clean_owner(self):    
        owner_id = self.cleaned_data['owner']
        return User.objects.get(id=owner_id)
        
    def clean_cats(self):
        cats = self.cleaned_data['cats']
        cat_list = cats.split(',')
        err_msg = 'Must contain a comma-separated list of categories from: ' + self.predefined_cats
        if len(cat_list) == 0:
            raise forms.ValidationError(err_msg)
        for cat_item in cat_list:
            if not cat_item.strip() in configs['cats']:
                raise forms.ValidationError(err_msg)
        return cats


class ApplicationForm(forms.Form):
    name = forms.CharField()
    description = forms.CharField(widget=forms.Textarea)
    cats = forms.CharField()
    
    def __init__(self, project, *args, **kwargs):
        super(ApplicationForm, self).__init__(*args, **kwargs)
        self.project = project
        self.helper = FormHelper(self)
        self.helper.wrapper_class = 'row'
        self.helper.label_class = 'col-md-2'
        self.helper.field_class = 'col-md-8'
        self.helper.add_input(Submit('submit', 'Submit'))
        self.fields['description'].widget.attrs.update(rows = 2)
        self.fields['cats'].label = 'Categories'
        self.fields['cats'].help_text = 'A subset of: ' + project.cats

    def clean_cats(self):
        cats = self.cleaned_data['cats']
        cat_list = cats.split(',')
        err_msg = 'Must contain a comma-separated list of categories from: ' + self.project.cats
        if len(cat_list) == 0:
            raise forms.ValidationError(err_msg)
        for cat_item in cat_list:
            if not cat_item.strip() in self.project.cats:
                raise forms.ValidationError(err_msg)
        return cats


class ValSetForm(forms.Form):
    name = forms.CharField()
    description = forms.CharField(widget=forms.Textarea(attrs={'size': '255'}))
    
    def __init__(self, *args, **kwargs):
        super(ValSetForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper(self)
        self.helper.wrapper_class = 'row'
        self.helper.label_class = 'col-md-2'
        self.helper.field_class = 'col-md-8'
        self.helper.add_input(Submit('submit', 'Submit'))
        self.fields['description'].widget.attrs.update(rows = 2)


class ReleaseForm(forms.Form):
    description = forms.CharField(widget=forms.Textarea)
    
    def __init__(self, *args, **kwargs):
        super(ReleaseForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper(self)
        self.helper.wrapper_class = 'row'
        self.helper.label_class = 'col-md-2'
        self.helper.field_class = 'col-md-8'
        self.helper.add_input(Submit('submit', 'Submit'))
        self.fields['description'].widget.attrs.update(rows = 2)


class SpecItemForm(forms.Form):
    domain = forms.CharField(max_length=255)
    name = forms.CharField(max_length=255)
    title = forms.CharField(max_length=255)
    desc = forms.CharField(widget=forms.Textarea(attrs={'class': 'link-suggest'}))
    value = forms.CharField(widget=forms.Textarea(attrs={'class': 'link-suggest'}))
    n1 = forms.IntegerField(min_value=0)
    rationale = forms.CharField(widget=forms.Textarea(attrs={'class': 'link-suggest'}))
    implementation = forms.CharField(widget=forms.Textarea(attrs={'class': 'link-suggest'}))
    remarks = forms.CharField(widget=forms.Textarea(attrs={'class': 'link-suggest'}))
    change_log = forms.CharField(widget=forms.Textarea(attrs={'class': 'link-suggest'}))
    p_kind = forms.ChoiceField(choices=())
    s_kind = forms.ChoiceField(choices=())
    val_set = forms.ModelChoiceField(queryset=None, empty_label=None)
    p_link = forms.ModelChoiceField(queryset=None, empty_label='')
    s_link = forms.ModelChoiceField(queryset=None, empty_label='')
    n2 = forms.IntegerField(min_value=0)
    n3 = forms.IntegerField(min_value=0)
    t1 = forms.CharField(widget=forms.Textarea(attrs={'class': 'link-suggest'}))
    t2 = forms.CharField(widget=forms.Textarea(attrs={'class': 'link-suggest'}))
    t3 = forms.CharField(widget=forms.Textarea(attrs={'class': 'link-suggest'}))
    t4 = forms.CharField(widget=forms.Textarea(attrs={'class': 'link-suggest'}))
    t5 = forms.CharField(widget=forms.Textarea(attrs={'class': 'link-suggest'}))
    ext_item = forms.ChoiceField(choices=())
   
    def __init__(self, mode, request, cat, project, application, config, s_parent_id, p_parent_id, *args, **kwargs):
        super(SpecItemForm, self).__init__(*args, **kwargs)
        self.project = project
        self.application = application
        self.mode = mode
        self.cat = cat
        self.config = config
        self.request = request
        self.helper = FormHelper(self)
        self.helper.wrapper_class = 'row'
        self.helper.label_class = 'col-md-2'
        self.helper.field_class = 'col-md-8'
        if mode == 'del':
            self.helper.add_input(Submit('submit', 'Delete'))
        else:
            self.helper.add_input(Submit('submit', 'Submit'))
            
        default_val_set = ValSet.objects.filter(project_id=project.id).get(name='Default')
        application_id = 0 if application==None else application.id
        cancel_location = '/editor/'+cat+'/'+str(project.id)+'/'+str(application_id)+\
                          '/'+str(default_val_set.id)+'/Sel_All/list_spec_items'
        self.helper.add_input(Button('cancel', 'Cancel', onclick="location.href='"+cancel_location+"';", \
                                     css_class='btn btn-danger'))
        
        self.fields['desc'].widget.attrs.update(rows = 1)
        self.fields['value'].widget.attrs.update(rows = 1)
        self.fields['rationale'].widget.attrs.update(rows = 1)
        self.fields['implementation'].widget.attrs.update(rows = 1)
        self.fields['remarks'].widget.attrs.update(rows = 1)
        self.fields['change_log'].widget.attrs.update(rows = 1)
        self.fields['t1'].widget.attrs.update(rows = 1)
        self.fields['t2'].widget.attrs.update(rows = 1)
        self.fields['t3'].widget.attrs.update(rows = 1)
        self.fields['t4'].widget.attrs.update(rows = 1)
        self.fields['t5'].widget.attrs.update(rows = 1)
        self.fields['p_kind'].choices = get_p_kind_choices(cat)
        self.fields['s_kind'].choices = get_s_kind_choices(cat)
        self.fields['p_link'].queryset = get_p_link_choices(cat, self.project, self.application, p_parent_id, s_parent_id)
        self.fields['s_link'].queryset = get_s_link_choices(cat, self.project, self.application, s_parent_id, p_parent_id)
        self.fields['n1'].initial = 0
        self.fields['n2'].initial = 0
        self.fields['n3'].initial = 0

        # Hide fields which are not required for a given category
        for field in self.fields:  
            if (field not in config['attrs']) or (field in config['ext_attrs']):
                self.fields[field].widget = forms.HiddenInput()
                self.fields[field].required = False 
                continue
            self.fields[field].label = config['attrs'][field]['label']
            if not config['attrs'][field]['req_in_form']:
                self.fields[field].required = False            
        
        # For external spec_item in add mode: load choices of external item
        if (len(config['ext_attrs']) > 0) and (self.mode == 'add'):
            get_choices_func_name = 'ext_' + cat.lower() + '_get_choices'
            self.fields['ext_item'].widget = forms.Select()
            self.fields['ext_item'].required = True
            self.fields['ext_item'].label = cat
            self.fields['ext_item'].choices = getattr(ext_cats, get_choices_func_name)(request)
        
        # In add mode, the ValSet is not visible
        if (self.mode == 'add'):
            self.fields['val_set'].widget = forms.HiddenInput()    

        # In copy and edit mode, the ValSet cannot be edited but is visible
        if (self.mode == 'copy') or (self.mode == 'edit'):     
            self.fields['val_set'].disabled = True
            val_set_id = self.initial['val_set']
            self.fields['val_set'].queryset = ValSet.objects.filter(id=val_set_id)
    
        # In split mode, the ValSet can be edited but domain and name   
        # must remain unchanged. The s_link and p_link fields must remain hidden.
        if (self.mode == 'split'):     
            self.fields['val_set'].queryset = ValSet.objects.filter(project_id=project.id).order_by('name')
            self.fields['domain'].disabled = True
            self.fields['name'].disabled = True
            self.fields['p_link'].disabled = True
            self.fields['p_link'].widget = forms.HiddenInput()
            self.fields['s_link'].disabled = True
            self.fields['s_link'].widget = forms.HiddenInput()
            
        # In delete mode, all fields but the change_log are visible but not editable
        if (self.mode == 'del'):
            for field in self.fields:  
                if (field in config['attrs']) and (field != 'change_log'):
                    self.fields[field].disabled = True
            val_set_id = self.initial['val_set']
            self.fields['val_set'].queryset = ValSet.objects.filter(id=val_set_id)
                    
    def clean(self):
        cd = self.cleaned_data
        default_val_set_id = ValSet.objects.filter(project_id=self.project.id).get(name='Default')
        
        # When in add mode: load data for external attributes
        if (len(self.config['ext_attrs']) > 0) and (self.mode == 'add'):
            get_choice_func_name = 'ext_' + self.cat.lower() + '_get_choice'
            ext_choice = getattr(ext_cats, get_choice_func_name)(self.request, cd['ext_item'])
            for ext_attr in self.config['ext_attrs']:
                cd[ext_attr] = ext_choice[ext_attr]
            
        # Check that domain and name only contain alphanumeric characters and underscores
        if not pattern_name.match(self.cleaned_data['name']):
            raise ValidationError({'name':'Name may contain only alphanumeric characters and underscores'})
        if not pattern_name.match(self.cleaned_data['domain']):
            raise ValidationError({'domain':'Domain may contain only alphanumeric characters and underscores'})
 
        # Fields of kind 'eval_ref' may only contain internal references to spec_items of the same category
        for field in self.fields:  
            if (field in self.config['attrs']) and (not field in self.config['ext_attrs']):
                if self.config['attrs'][field]['kind'] == 'eval_ref':
                    internal_refs = re.findall(pattern_edit, cd[field])
                    for ref in internal_refs:
                        if ref[0] != self.cat:
                            err_msg = 'The field '+field+' of a '+self.cat+' cannot contain internal references to '+\
                                      'internal_ref_cat of a different category: '+str(ref)
                            raise forms.ValidationError(err_msg)
         
        # Fields of kind 'ref_text' or 'eval_ref' are converted from 'edit' to 'db' representation
        # (but external attribute fields are left untouched because they are loaded from an
        #  external resource) 
        for field in self.fields:  
            if (field in self.config['attrs']) and (not field in self.config['ext_attrs']):
                if (self.config['attrs'][field]['kind'] == 'ref_text') or  (self.config['attrs'][field]['kind'] == 'eval_ref'):
                    cd[field] = convert_edit_to_db(self.project, cd[field])
        
        # Verify that, in add and copy modes, the domain:name pair is unique within non-deleted, 
        # non-obsolete spec_items in the project and ValSet
        if (self.mode == 'add') or (self.mode == 'copy'):
            if SpecItem.objects.exclude(status='DEL').exclude(status='OBS').filter(project_id=self.project.id, \
                         domain=cd['domain'], name=cd['name'], val_set_id=default_val_set_id).exists():
                raise forms.ValidationError('Add or Copy Error: Domain:Name pair already exists in this project')

        # Verify that, in edit mode, if the domain:name has been modified, it is unique within non-deleted, 
        # non-obsolete spec_items in the project and in the default ValSet
        if (self.mode == 'edit') and (('name' in self.changed_data) or ('domain' in self.changed_data)):
            if SpecItem.objects.exclude(status='DEL').exclude(status='OBS').filter(project_id=self.project.id, \
                         domain=cd['domain'], name=cd['name'], val_set_id=default_val_set_id).exists():
                    raise forms.ValidationError('Edit Error: Domain:Name pair already exists in this project')
        
        # Verify that, in split mode, the ValSet is not duplicated within the set of non-deleted, non-obsolete 
        # spec_items of a project with the same domain:name 
        if (self.mode == 'split'):
            if SpecItem.objects.exclude(status='DEL').exclude(status='OBS').filter(project_id=self.project.id, \
                     domain=cd['domain'], name=cd['name'], val_set_id=cd['val_set']).exists():
                raise forms.ValidationError('Split Error: ValSet is already in use for this domain:name')
        
        # Perform category-specific checks
        check_msg = do_cat_specific_checks(self)
        if check_msg != '':
            raise forms.ValidationError(check_msg)
 
        return cd
 
