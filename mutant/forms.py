from inspect import isclass

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import EMPTY_VALUES
from django.forms.fields import ChoiceField
from django.utils.encoding import smart_unicode
from django.utils.text import capfirst

from .common import group_item_getter, choices_from_dict
from .models.field import FieldDefinition, FieldDefinitionBase


class FieldDefinitionTypeField(ChoiceField):

    def __init__(self, field_definitions=None, empty_label="---------",
                 *args, **kwargs):
        if field_definitions is None:
            field_definitions = FieldDefinitionBase._field_definitions.values()
        else:
            for fd in field_definitions:
                if not isinstance(fd, FieldDefinitionBase):
                    raise TypeError("%r is not a subclass of FieldDefinitionBase" % fd)
        fds_choices = []
        for fd in field_definitions:
            try:
                opts = fd._meta
                app_label = opts.app_label
                object_name = opts.object_name.lower()
                ct = ContentType.objects.get_by_natural_key(app_label, object_name)
            except ContentType.DoesNotExist:
                continue
            fds_choices.append({
                'value': ct.pk,
                'label': unicode(fd.get_field_description()),
                'group': unicode(fd.get_field_category()),
            })
        choices = [(u'', empty_label)] + list(choices_from_dict(sorted(fds_choices, key=group_item_getter)))
        super(FieldDefinitionTypeField, self).__init__(choices, *args, **kwargs)

    def to_python(self, value):
        if value in EMPTY_VALUES:
            return None
        try:
            ct = ContentType.objects.get_for_id(value)
        except ContentType.DoesNotExist:
            raise ValidationError(self.error_messages['invalid_choice'])
        return ct

    def valid_value(self, value):
        if isclass(value) and issubclass(value, FieldDefinition):
            value = value.get_content_type()
        if isinstance(value, ContentType):
            value = value.pk
        value = smart_unicode(value)
        return super(FieldDefinitionTypeField, self).valid_value(value)