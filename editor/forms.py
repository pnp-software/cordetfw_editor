from django import forms
from django.forms import formsets
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from itertools import chain
from editor.models import Application
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit, Button
from .utilities import get_user_choices
from .choices import HISTORY_STATUS, SPEC_ITEM_CAT, REQ_KIND, DI_KIND, DIT_KIND, \
                     MODEL_KIND, PCKT_KIND, VER_ITEM_KIND, REQ_VER_METHOD
    
        

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
    justification = forms.CharField(widget=forms.Textarea)
    remarks = forms.CharField(widget=forms.Textarea)
    kind = forms.ChoiceField(choices=())
    ver_method = forms.ChoiceField(choices=REQ_VER_METHOD)
    val_set = forms.ChoiceField(choices=())
    desc_pars = forms.CharField(widget=forms.Textarea)
    desc_dest = forms.CharField(widget=forms.Textarea)
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
        self.mode = kwargs.pop('mode')
        super(SpecItemForm, self).__init__(*args, **kwargs)
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
        self.fields['enab;e_check'].widget.attrs.update(rows = 1)
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
            import pdb; pdb.set_trace()
            if field not in config['form_field']:
                field.widget = forms.HiddenInput()
                break
            
        self.project = project
        self.application = application
  
  
  
 
