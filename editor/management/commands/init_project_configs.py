import copy

from django.core.management.base import BaseCommand
from django.db import transaction

from editor.config_validation import validate_config
from editor.models import Project
from editor.project_config import (add_missing_relationship_settings, filter_template_for_data, get_unknown_cats,
                                   load_template)


class Command(BaseCommand):
    help = ('Initialize Project.config from the shared template, filtered for the data of each project. '
            'Projects which already have a configuration are skipped, so the command can be run repeatedly.')

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would be initialized without writing to the database.')
        parser.add_argument('--upgrade-format', action='store_true',
                            help='Also complete the configurations of projects which are already configured: '
                                 'category definitions without "links"/"validators" get the template '
                                 'values. Existing keys and everything else are left unchanged.')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        template = load_template()
        initialized = skipped = upgraded = 0
        for project_id in Project.objects.order_by('id').values_list('id', flat=True):
            with transaction.atomic():
                project = Project.objects.select_for_update().get(id=project_id)
                if project.config:
                    config = copy.deepcopy(project.config)
                    if options['upgrade_format'] and add_missing_relationship_settings(config):
                        if not dry_run:
                            project.config = config
                            project.save(update_fields=['config'])
                        upgraded += 1
                        self.stdout.write('Project %d (%s): %s relationship settings' % (
                            project.id, project.name, 'would add' if dry_run else 'added'))
                        continue
                    skipped += 1
                    self.stdout.write('Project %d (%s): already configured, skipped' % (project.id, project.name))
                    continue
                config = filter_template_for_data(template, project)
                for cat in get_unknown_cats(template, project):
                    self.stderr.write('Project %d (%s): category %s is not defined in the template and is not '
                                      'included in the configuration' % (project.id, project.name, cat))
                # The proposal is stored anyway (the owner reviews it); problems are reported, never fixed silently
                for error in validate_config(config, project):
                    self.stderr.write('Project %d (%s): configuration problem at %s' % (
                        project.id, project.name, error))
                if not dry_run:
                    project.config = config
                    project.save(update_fields=['config'])     # leaves updated_at and all data untouched
                initialized += 1
                removed = sorted(set(template['cats']) - set(config['cats']))
                self.stdout.write('Project %d (%s): %s with %d categories (removed: %s)' % (
                    project.id, project.name, 'would initialize' if dry_run else 'initialized',
                    len(config['cats']), ', '.join(removed) or 'none'))
        self.stdout.write('%s: %d project(s) %s, %d skipped' % (
            'Dry run' if dry_run else 'Done', initialized, 'to initialize' if dry_run else 'initialized', skipped))
        if options['upgrade_format']:
            self.stdout.write('%d project(s) %s' % (upgraded, 'to upgrade' if dry_run else 'upgraded'))
