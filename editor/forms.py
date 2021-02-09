import re
from django import forms
from django.forms import formsets
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from itertools import chain
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit, Button
from .utilities import get_user_choices, get_kind_choices, get_parent_choices, \
                       pattern_text, render_for_db
from .choices import HISTORY_STATUS, SPEC_ITEM_CAT, REQ_KIND, DI_KIND, DIT_KIND, \
                     MODEL_KIND, PCKT_KIND, VER_ITEM_KIND, REQ_VER_METHOD
from editor.models import Application, ValSet, Project, SpecItem
from editor.configs import configs

class ProjectForm(forms.Form):
    name = forms.CharField()
    owner = forms.ChoiceField(choices=())
    description = forms.CharField(widget=forms.Textarea)
    
    def __init__(self, *args, **kwargs):
        super(ProjectForm, self).__init__(*args, **kwargs)
        self.fields['owner'].choices = get_user_choices()
        self.helper = FormHelper(self)
        self.helper.wrapper_class = 'row'
        self.helper.label_class = 'col-md-2'
        self.helper.field_class = 'col-md-8'
        self.helper.add_input(Submit('submit', 'Submit'))
        self.fields['description'].widget.attrs.update(rows = 2)

    def clean_owner(self):    
        owner_id = self.cleaned_data['owner']
        return User.objects.get(id=owner_id)


class ApplicationForm(forms.Form):
    name = forms.CharField()
    description = forms.CharField(widget=forms.Textarea)
    
    def __init__(self, *args, **kwargs):
        super(ApplicationForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper(self)
        self.helper.wrapper_class = 'row'
        self.helper.label_class = 'col-md-2'
        self.helper.field_class = 'col-md-8'
        self.helper.add_input(Submit('submit', 'Submit'))
        self.fields['description'].widget.attrs.update(rows = 2)


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
    domain = forms.CharField()
    name = forms.CharField()
    title = forms.CharField()
    desc = forms.CharField(widget=forms.Textarea(attrs={'class': 'link-suggest'}))
    value = forms.CharField(widget=forms.Textarea(attrs={'class': 'link-suggest'}))
    dim = forms.IntegerField(min_value=0)
    justification = forms.CharField(widget=forms.Textarea(attrs={'class': 'link-suggest'}))
    remarks = forms.CharField(widget=forms.Textarea(attrs={'class': 'link-suggest'}))
    kind = forms.ChoiceField(choices=())
    ver_method = forms.ChoiceField(choices=REQ_VER_METHOD)
    val_set = forms.ChoiceField(choices=())
    desc_pars = forms.CharField(widget=forms.Textarea)
    desc_dest = forms.CharField(widget=forms.Textarea)
    group = forms.IntegerField(min_value=0)
    repetition = forms.IntegerField(min_value=0)
    acceptance_check = forms.CharField(widget=forms.Textarea)
    enable_check = forms.CharField(widget=forms.Textarea)
    repeat_check = forms.CharField(widget=forms.Textarea)
    update_action = forms.CharField(widget=forms.Textarea)
    start_action = forms.CharField(widget=forms.Textarea)
    progress_action = forms.CharField(widget=forms.Textarea)
    termination_action = forms.CharField(widget=forms.Textarea)
    abort_action = forms.CharField(widget=forms.Textarea)
    pre_cond = forms.CharField(widget=forms.Textarea)
    post_cond = forms.CharField(widget=forms.Textarea)
    close_out = forms.CharField(widget=forms.Textarea)
    ver_status = forms.ChoiceField(choices=REQ_VER_METHOD)
    parent = forms.ChoiceField(choices=())
    disc = forms.ChoiceField(choices=())
   
    def __init__(self, mode, cat, project, application, config, *args, **kwargs):
        super(SpecItemForm, self).__init__(*args, **kwargs)
        self.project = project
        self.application = application
        self.mode = mode
        self.cat = cat
        self.helper = FormHelper(self)
        self.helper.wrapper_class = 'row'
        self.helper.label_class = 'col-md-2'
        self.helper.field_class = 'col-md-8'
        self.helper.add_input(Submit('submit', 'Submit'))
        self.fields['desc'].widget.attrs.update(rows = 1)
        self.fields['value'].widget.attrs.update(rows = 1)
        self.fields['justification'].widget.attrs.update(rows = 1)
        self.fields['remarks'].widget.attrs.update(rows = 1)
        self.fields['desc_pars'].widget.attrs.update(rows = 1)
        self.fields['desc_dest'].widget.attrs.update(rows = 1)
        self.fields['acceptance_check'].widget.attrs.update(rows = 1)
        self.fields['enable_check'].widget.attrs.update(rows = 1)
        self.fields['repeat_check'].widget.attrs.update(rows = 1)
        self.fields['update_action'].widget.attrs.update(rows = 1)
        self.fields['start_action'].widget.attrs.update(rows = 1)
        self.fields['progress_action'].widget.attrs.update(rows = 1)
        self.fields['termination_action'].widget.attrs.update(rows = 1)
        self.fields['abort_action'].widget.attrs.update(rows = 1)
        self.fields['pre_cond'].widget.attrs.update(rows = 1)
        self.fields['post_cond'].widget.attrs.update(rows = 1)
        self.fields['close_out'].widget.attrs.update(rows = 1)
        self.fields['kind'].choices = get_kind_choices(cat)
        self.fields['parent'].choices = get_parent_choices(cat, self.project.id)
        self.fields['dim'].initial = 0
        self.fields['group'].initial = 0
        self.fields['repetition'].initial = 0

        # Hide fields which are not required for a given category
        for field in self.fields:  
            if field not in config['attrs']:
                self.fields[field].widget = forms.HiddenInput()
                self.fields[field].required = False 
                continue
            if not config['attrs'][field]['in_form']:
                self.fields[field].widget = forms.HiddenInput()
                self.fields[field].required = False 
                continue
            self.fields[field].label = config['attrs'][field]['label']
            if not config['attrs'][field]['req_in_form']:
                self.fields[field].required = False            
        
        # In add mode, the ValSet is not visible
        if (self.mode == 'add'):
            self.fields['val_set'].widget = forms.HiddenInput()      

        # In all modes but copy and edit mode, the ValSet cannot be edited but is visible
        if (self.mode == 'copy') or (self.mode == 'edit'):     
            self.fields['val_set'].disabled = True
            val_set_id = self.initial['val_set']
            val_set_name = ValSet.objects.filter(project_id=self.project.id).get(id=val_set_id).name
            self.fields['val_set'].choices = ((val_set_id, val_set_name),)
    
        # In split mode, the ValSet can be edited but domain, name and pointer fields must remain unchanged
        # Parent field  must remain hidden
        if (self.mode == 'split'):     
            self.fields['val_set'].choices = ValSet.objects.filter(project_id=project.id).\
                                                            order_by('name').values_list('id','name')
            self.fields['domain'].disabled = True
            self.fields['name'].disabled = True
            self.fields['parent'].disabled = True
            self.fields['parent'].widget = forms.HiddenInput()
            self.fields['disc'].disabled = True
            
        # The domain of enumerated items is always equal to 'enum'  
        if cat == 'EnumItem':
            self.fields['domain'].initial = 'enum'
            self.fields['domain'].disabled = True
          
    def clean(self):
        """ Verify that: 
        (a) In add and copy modes, the domain:name pair is unique within non-deleted, non-obsolete spec_items 
            in the project and ValSet;
        (b) In edit mode, if the domain:name has been modified, it is unique within non-deleted, 
            non-obsolete spec_items in the project and in the default ValSet;
        (c) In split mode, the ValSet is not duplicated within the set of non-deleted, non-obsolete spec_items
            of a project with the same domain:name 
        (d) In edit mode, if the kind of a data item type is set to non-enumerated, it cannot have enumerated 
            items attached to it.
        (e) The value field of a data item can only contain internal references to other data items
        """
        cd = self.cleaned_data
        default_val_set_id = ValSet.objects.filter(project_id=self.project.id).get(name='Default')
        
        if (self.mode == 'add') or (self.mode == 'copy'):
            if SpecItem.objects.exclude(status='DEL').exclude(status='OBS').filter(project_id=self.project.id, \
                         domain=cd['domain'], name=cd['name'], val_set_id=default_val_set_id).exists():
                raise forms.ValidationError('Add or Copy Error: Domain:Name pair already exists in this project')

        if (self.mode == 'edit') and (('name' in self.changed_data) or ('domain' in self.changed_data)):
            if SpecItem.objects.exclude(status='DEL').exclude(status='OBS').filter(project_id=self.project.id, \
                         domain=cd['domain'], name=cd['name'], val_set_id=default_val_set_id).exists():
                    raise forms.ValidationError('Edit Error: Domain:Name pair already exists in this project')
        
        if (self.mode == 'split'):
            if SpecItem.objects.exclude(status='DEL').exclude(status='OBS').filter(project_id=self.project.id, \
                     domain=cd['domain'], name=cd['name'], val_set_id=cd['val_set']).exists():
                raise forms.ValidationError('Split Error: ValSet is already in use for this domain:name')
        
        if (self.mode == 'edit') and (self.cat == 'DataItemType') and (cd['kind'] == 'NOT_ENUM'):
            spec_item = SpecItem.objects.get(domain=cd['domain'], name=cd['name'])
            children = SpecItem.objects.filter(parent=spec_item.id)
            if children != None:
                raise forms.ValidationError('This data type has enumerated items attached to it and '+\
                                            'must therefore be of enumerated type')

        if (self.cat == 'DataItem'):
            internal_refs = re.findall(pattern_text, cd['value'])
            for ref in internal_refs:
                if ref[0:8] != 'DataItem#':
                    raise forms.ValidationError('The value field of a data item cannot contain references to non-'+\
                                            'data items: '+str(ref))

        return cd
 
    def clean_title(self):
        return render_for_db(self.cleaned_data['title'])

    def clean_desc(self):
        return render_for_db(self.cleaned_data['desc'])

    def clean_value(self):
        return render_for_db(self.cleaned_data['value'])

    def clean_justification(self):
        return render_for_db(self.cleaned_data['justification'])

    def clean_remarks(self):
        return render_for_db(self.cleaned_data['remarks'])


 
