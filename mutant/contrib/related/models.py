from __future__ import unicode_literals

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db.models import deletion, fields
from django.utils.translation import ugettext_lazy as _
from picklefield.fields import PickledObjectField

from ...db.fields import PythonIdentifierField
from ...db.models import MutableModel
from ...models import FieldDefinition, FieldDefinitionManager, ModelDefinition

from .managers import ForeignKeyDefinitionManager


related_name_help_text = _('The name to use for the relation from the '
                           'related object back to this one.')

class RelatedFieldDefinition(FieldDefinition):
    to = fields.related.ForeignKey(ContentType, verbose_name=_('to'),
                                   related_name='+')
    related_name = PythonIdentifierField(_('related name'),
                                         blank=True, null=True,
                                         help_text=related_name_help_text)

    objects = FieldDefinitionManager()

    class Meta:
        app_label = 'mutant'
        abstract = True
        defined_field_options = ('related_name',)
        defined_field_category = _('Related')

    def clone(self):
        clone = super(RelatedFieldDefinition, self).clone()
        clone.to = self.to
        return clone

    @property
    def is_recursive_relationship(self):
        """
        Whether or not `to` points to this field's model definition
        """
        try:
            model_def = self.model_def
        except ModelDefinition.DoesNotExist:
            return False
        else:
            return self.to_id == model_def.contenttype_ptr_id

    @property
    def to_model_class_is_mutable(self):
        to_model_class = self.to.model_class()
        if to_model_class is None:
            try:
                getattr(self.to, 'modeldefinition')
            except ModelDefinition.DoesNotExist:
                return False
            else:
                return True
        else:
            return issubclass(to_model_class, MutableModel)

    @property
    def to_model_class(self):
        if self.to_model_class_is_mutable:
            return self.to.modeldefinition.model_class()
        else:
            return self.to.model_class()

    def clean(self):
        if self.related_name and self.to_id and not self.to_model_class_is_mutable:
            msg = _('Cannot assign a related manager to non-mutable model')
            raise ValidationError({'related_name': [msg]})

    def get_field_options(self, **overrides):
        options = super(RelatedFieldDefinition, self).get_field_options(**overrides)
        if self.is_recursive_relationship:
            options['to'] = fields.related.RECURSIVE_RELATIONSHIP_CONSTANT
        else:
            opts = self.to_model_class._meta
            options['to'] = "%s.%s" % (opts.app_label, opts.object_name)
        if not self.to_model_class_is_mutable:
            options['related_name'] = '+'
        return options

    def _south_ready_field_instance(self):
        """
        South add_column choke when passing 'self' or 'app.Model' to `to` kwarg,
        so we have to create a special version for it.
        """
        cls = self.get_field_class()
        options = self.get_field_options()
        options['to'] = self.to.model_class()
        return cls(**options)


to_field_help_text = _('The field on the related object that the '
                       'relation is to.')
on_delete_help_text = _('Behavior when an object referenced by this field '
                        'is deleted')

class ForeignKeyDefinition(RelatedFieldDefinition):
    ON_DELETE_CASCADE = 'CASCADE'
    ON_DELETE_PROTECT = 'PROTECT'
    ON_DELETE_SET_NULL = 'SET_NULL'
    ON_DELETE_SET_DEFAULT = 'SET_DEFAULT'
    ON_DELETE_SET_VALUE = 'SET_VALUE'
    ON_DELETE_DO_NOTHING = 'DO_NOTHING'

    ON_DELETE_CHOICES = (
        (ON_DELETE_CASCADE, _('CASCADE')),
        (ON_DELETE_PROTECT, _('PROTECT')),
        (ON_DELETE_SET_NULL, _('SET_NULL')),
        (ON_DELETE_SET_DEFAULT, _('SET_DEFAULT')),
        (ON_DELETE_SET_VALUE, _('SET(VALUE)')),
        (ON_DELETE_DO_NOTHING, _('DO_NOTHING')),
    )

    to_field = PythonIdentifierField(_('to field'), blank=True, null=True,
                                     help_text=to_field_help_text)
    one_to_one = fields.BooleanField(editable=False, default=False)
    on_delete = fields.CharField(_('on delete'), blank=True, null=True,
                                 max_length=11, choices=ON_DELETE_CHOICES,
                                 default=ON_DELETE_CASCADE,
                                 help_text=on_delete_help_text)
    on_delete_set_value = PickledObjectField(_('on delete set value'), null=True)

    objects = ForeignKeyDefinitionManager(one_to_one=False)

    class Meta:
        app_label = 'mutant'
        defined_field_class = fields.related.ForeignKey
        defined_field_options = ('to_field',)

    def clean(self):
        try:
            super(ForeignKeyDefinition, self).clean()
        except ValidationError as e:
            messages = e.message_dict
        else:
            messages = {}
        if self.on_delete == self.ON_DELETE_SET_NULL:
            if not self.null:
                msg = _("This field can't be null")
                messages['on_delete'] = [msg]
        elif (self.on_delete == self.ON_DELETE_SET_DEFAULT and
              self.default == fields.NOT_PROVIDED):
            msg = _('This field has no default value')
            messages['on_delete'] = [msg]
        elif (self.on_delete == self.ON_DELETE_SET_VALUE and
              self.on_delete_set_value is None):
            msg = _('You must specify a value to set on deletion')
            messages['on_delete'] = [msg]
        if messages:
            raise ValidationError(messages)

    def get_field_options(self, **overrides):
        options = super(ForeignKeyDefinition, self).get_field_options(**overrides)
        if self.on_delete == self.ON_DELETE_SET_VALUE:
            on_delete = deletion.SET(self.on_delete_set_value)
        else:
            on_delete = getattr(deletion, self.on_delete, None)
        options['on_delete'] = on_delete
        return options


class OneToOneFieldDefinition(ForeignKeyDefinition):
    objects = ForeignKeyDefinitionManager(one_to_one=True)

    class Meta:
        app_label = 'mutant'
        proxy = True
        defined_field_class = fields.related.OneToOneField

    def save(self, *args, **kwargs):
        self.one_to_one = True
        return super(OneToOneFieldDefinition, self).save(*args, **kwargs)


through_help_text = _('Intermediary model')

db_table_help_text = _('The name of the table to create for storing the '
                       'many-to-many data')

class ManyToManyFieldDefinition(RelatedFieldDefinition):
    symmetrical = fields.NullBooleanField(_('symmetrical'))
    through = fields.related.ForeignKey(ContentType, blank=True, null=True,
                                        related_name='+',
                                        help_text=through_help_text)
    # TODO: This should not be a SlugField
    db_table = fields.SlugField(max_length=30, blank=True, null=True,
                                help_text=db_table_help_text)

    class Meta:
        app_label = 'mutant'
        defined_field_class = fields.related.ManyToManyField
        defined_field_options = ('symmetrical', 'db_table')

    def clean(self):
        try:
            super(ManyToManyFieldDefinition, self).clean()
        except ValidationError as e:
            messages = e.message_dict
        else:
            messages = {}

        if (self.symmetrical is not None and
            not self.is_recursive_relationship):
            msg = _("The relationship can only be symmetrical or not if it's "
                    "recursive, i. e. it points to 'self'")
            messages['symmetrical'] = [msg]

        if self.through:
            if self.db_table:
                msg = _('Cannot specify a db_table if an intermediate '
                        'model is used.')
                messages['db_table'] = [msg]

            if self.symmetrical:
                msg = _('Many-to-many fields with intermediate model cannot '
                        'be symmetrical.')
                messages.setdefault('symmetrical', []).append(msg)

            seen_from, seen_to = 0, 0
            to_model = self.to.model_class()
            through_class = self.through.model_class()
            from_model = self.model_def.cached_model
            for field in through_class._meta.fields:
                rel_to = getattr(field.rel, 'to', None)
                if rel_to == from_model:
                    seen_from += 1
                elif rel_to == to_model:
                    seen_to += 1
            if self.is_recursive_relationship():
                if seen_from > 2:
                    msg = _('Intermediary model %s has more than two foreign '
                            'keys to %s, which is ambiguous and is not permitted.')
                    formated_msg = msg % (through_class._meta.object_name,
                                          from_model._meta.object_name)
                    messages.setdefault('through', []).append(formated_msg)
            else:
                msg = _('Intermediary model %s has more than one foreign key '
                        ' to %s, which is ambiguous and is not permitted.')
                if seen_from > 1:
                    formated_msg = msg % (through_class._meta.object_name,
                                          from_model._meta.object_name)
                    messages.setdefault('through', []).append(formated_msg)
                if seen_to > 1:
                    formated_msg = msg % (through_class._meta.object_name,
                                          to_model._meta.object_name)
                    messages.setdefault('through', []).append(formated_msg)

        if messages:
            raise ValidationError(messages)

    def get_field_options(self, **overrides):
        options = super(ManyToManyFieldDefinition, self).get_field_options(**overrides)
        if self.through:
            options['through'] = self.through.model_class()
        return options

    def get_bound_field(self):
        opts = self.model_def.model_class(force_create=True)._meta
        for field in opts.many_to_many:
            if getattr(field, self.FIELD_DEFINITION_PK_ATTR, None) == self.pk:
                return field
