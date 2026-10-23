"""Helpers for expectations that legitimately differ between SQLite and MySQL.

Production runs MySQL (case-insensitive utf8mb4_unicode_ci collation, Django's
default 3-byte 'utf8' connection charset); the fast suite runs SQLite. Where the
backends differ, both results are pinned explicitly.
"""

from django.db import connection


def is_mysql():
    return connection.vendor == 'mysql'
