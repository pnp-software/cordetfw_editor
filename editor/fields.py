from django.db import models


class OrderedJSONField(models.JSONField):
    """
    JSONField which keeps the order of the keys of JSON objects on every database.

    MySQL 8 normalises the keys of a JSON column (shorter keys first, then alphabetical). The order of the
    categories, attributes and choices of a project configuration is significant (menus, CSV columns, the
    default choice), so on MySQL the value is stored as text, as MariaDB does for its JSON type.
    """

    def db_type(self, connection):
        if connection.vendor == 'mysql':
            return 'longtext'
        return super().db_type(connection)

    def db_check(self, connection):
        check = super().db_check(connection)
        if check is None and connection.vendor == 'mysql':
            return 'JSON_VALID(%(qn_column)s)' % self.db_type_parameters(connection)
        return check
