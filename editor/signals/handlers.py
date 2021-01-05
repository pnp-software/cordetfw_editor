import logging
from admin_honeypot.signals import honeypot
from django.dispatch import receiver

@receiver(honeypot)
def honeypot_to_logger(sender, **kwargs):
    honeypot_logger = logging.getLogger('admin.honeypot')
    honeypot_logger.warning('logging attempt by: {who}; {addr}'.format(
        who=kwargs['instance'],
        addr=kwargs['request'].META['REMOTE_ADDR']))
