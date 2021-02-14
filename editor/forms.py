import re
from django import forms
from django.forms import formsets
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from itertools import chain
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit, Button
from .utilities import get_user_choices, get_p_kind_choices, get_p_link_choices, \
                       pattern_edit, pattern_db, convert_edit_to_db, get_s_kind_choices, \
                       get_s_link_choices
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
    n1 = forms.IntegerField(min_value=0)
    rationale = forms.CharField(widget=forms.Textarea(attrs={'class': 'link-suggest'}))
    remarks = forms.CharField(widget=forms.Textarea(attrs={'class': 'link-suggest'}))
    p_kind = forms.ChoiceField(choices=())
    s_kind = forms.ChoiceField(choices=REQ_VER_METHOD)
    val_set = forms.ModelChoiceField(queryset=None, empty_label=None)
    p_link = forms.ModelChoiceField(queryset=None, empty_label=None)
    s_link = forms.ModelChoiceField(queryset=None, empty_label=None)
    n2 = forms.IntegerField(min_value=0)
    n3 = forms.IntegerField(min_value=0)
    t1 = forms.CharField(widget=forms.Textarea(attrs={'class': 'link-suggest'}))
    t2 = forms.CharField(widget=forms.Textarea(attrs={'class': 'link-suggest'}))
    t3 = forms.CharField(widget=forms.Textarea(attrs={'class': 'link-suggest'}))
    t4 = forms.CharField(widget=forms.Textarea(attrs={'class': 'link-suggest'}))
    t5 = forms.CharField(widget=forms.Textarea(attrs={'class': 'link-suggest'}))
   
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
        self.fields['rationale'].widget.attrs.update(rows = 1)
        self.fields['remarks'].widget.attrs.update(rows = 1)
        self.fields['t1'].widget.attrs.update(rows = 1)
        self.fields['t2'].widget.attrs.update(rows = 1)
        self.fields['t3'].widget.attrs.update(rows = 1)
        self.fields['t4'].widget.attrs.update(rows = 1)
        self.fields['t5'].widget.attrs.update(rows = 1)
        self.fields['p_kind'].choices = get_p_kind_choices(cat)
        self.fields['s_kind'].choices = get_s_kind_choices(cat)
        self.fields['p_link'].queryset = get_p_link_choices(cat, self.project.id)
        self.fields['s_link'].queryset = get_s_link_choices(cat, self.project.id)
        self.fields['n1'].initial = 0
        self.fields['n2'].initial = 0
        self.fields['n3'].initial = 0

        # Hide fields which are not required for a given category
        for field in self.fields:  
            if field not in config['attrs']:
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
            self.fields['val_set'].queryset = ValSet.objects.filter(id=val_set_id)
    
        # In split mode, the ValSet can be edited but domain, name and pointer fields must remain unchanged
        # Parent field  must remain hidden
        if (self.mode == 'split'):     
            self.fields['val_set'].queryset = ValSet.objects.filter(project_id=project.id).order_by('name')
            self.fields['domain'].disabled = True
            self.fields['name'].disabled = True
            self.fields['p_link'].disabled = True
            self.fields['p_link'].widget = forms.HiddenInput()
            self.fields['s_link'].disabled = True
            self.fields['s_link'].widget = forms.HiddenInput()
                      
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
        (e) In the value field of a data item, internal references may only point to other data items
        (f) The value of a data item of enumerated type must be an internal reference to an enumerated value
            of the data item's type
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
            internal_refs = re.findall(pattern_edit, cd['value'])
            for ref in internal_refs:
                if ref[0:8] != 'DataItem#':
                    raise forms.ValidationError('The value field of a data item cannot contain references to non-'+\
                                            'data items: '+str(ref))

        if (self.cat == 'DataItem'):
            enum_type = SpecItem.objects.get(id=cd['p_link'])
            s_span = re.search(pattern_db, cd['value'].strip()).span()
            import pdb; pdb.set_trace()
            if (s_span[0] != 0) or (s_span[1] != len(cd['value'].strip())):
                raise forms.ValidationError('Data item value must be a reference to an enumerated value of the item type')
            ref = cd['value'].strip().split(':')
            try:
                enum_val = SpecItem.objects.get(id=ref[1])
            except ObjectDoesNotExist:
                raise forms.ValidationError('Data item value must be a reference to an enumerated value of the item type: '+\
                                            'The reference is invalid')
            if enum_val.p_link.id != int(cd['p_link']):
                raise forms.ValidationError('Data item value must be a reference to an enumerated value of the item type')
 
        return cd
 
    def clean_title(self):
        return convert_edit_to_db(self.cleaned_data['title'])

    def clean_desc(self):
        return convert_edit_to_db(self.cleaned_data['desc'])

    def clean_value(self):
        return convert_edit_to_db(self.cleaned_data['value'])

    def clean_justification(self):
        return convert_edit_to_db(self.cleaned_data['rationale'])

    def clean_remarks(self):
        return convert_edit_to_db(self.cleaned_data['remarks'])


 
