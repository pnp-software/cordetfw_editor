from django import forms
from django.forms import formsets
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from itertools import chain
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit, Button
from .utilities import get_user_choices, get_kind_choices
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
    desc = forms.CharField(widget=forms.Textarea)
    value = forms.CharField(widget=forms.Textarea)
    dim = forms.IntegerField(min_value=0)
    justification = forms.CharField(widget=forms.Textarea)
    remarks = forms.CharField(widget=forms.Textarea)
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
   
    def __init__(self, mode, cat, project, application, config, *args, **kwargs):
        super(SpecItemForm, self).__init__(*args, **kwargs)
        self.project = project
        self.application = application
        self.mode = mode
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
        self.fields['val_set'].choices = ValSet.objects.filter(project_id=project.id).\
                                                order_by('name').values_list('id','name')
        for field in self.fields:
            if field not in config['form_fields']:
                self.fields[field].widget = forms.HiddenInput()
                self.fields[field].required = False 
                continue
            self.fields[field].label = config['form_fields'][field]['label']
            if not config['form_fields'][field]['req']:
                self.fields[field].required = False            
        if self.mode == 'copy':
            self.fields['val_set'].disabled = False
        else:
            self.fields['val_set'].disabled = True
          
    def clean(self):
        """ Verify that the domain:name pair is not duplicated """
        cleaned_data = self.cleaned_data
        if self.mode == 'copy' or self.mode == 'add':
            if SpecItem.objects.exclude(status='DEL').exclude(status='OBS').\
                        filter(project_id=self.project.id, domain=cleaned_data['domain'], name=cleaned_data['name']).exists():
                raise forms.ValidationError('Add or Copy Error: Domain:Name pair already exists in this project')
        if self.mode == 'edit':
            if (('name' in self.changed_data) or ('domain' in self.changed_data)):
                if SpecItem.objects.exclude(status='DEL').exclude(status='OBS').\
                        filter(project_id=self.project.id, domain=cleaned_data['domain'], name=cleaned_data['name']).exists():
                    raise forms.ValidationError('Edit Error: Domain:Name pair already exists in this project')
        return cleaned_data
 
  
 
