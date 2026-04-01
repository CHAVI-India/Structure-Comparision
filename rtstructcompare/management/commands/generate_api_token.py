import secrets

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from rtstructcompare.models import APIToken


class Command(BaseCommand):
    help = (
        "Manage external API tokens for the /api/feedbacks/ endpoint.\n\n"
        "  create --username <u> [--label <l>]  generate a new token\n"
        "  list   --username <u>                list tokens for a user\n"
        "  revoke --token <t>                   deactivate a token\n"
    )

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['create', 'list', 'revoke'])
        parser.add_argument('--username', help='Django username (required for create / list)')
        parser.add_argument('--label', default='', help='Optional label for the token')
        parser.add_argument('--token', help='Token string to revoke (required for revoke)')

    def handle(self, *args, **options):
        action = options['action']

        if action == 'create':
            username = options.get('username')
            if not username:
                raise CommandError('--username is required for create.')
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                raise CommandError(f'User "{username}" does not exist.')
            if not user.is_superuser:
                raise CommandError(
                    f'User "{username}" is not a superuser. '
                    'Only superusers may hold API tokens.'
                )
            raw = secrets.token_hex(32)
            tok = APIToken.objects.create(user=user, token=raw, label=options.get('label') or '')
            self.stdout.write(self.style.SUCCESS(f'Token created for {username}:'))
            self.stdout.write(f'  Token : {raw}')
            self.stdout.write(f'  ID    : {tok.id}')
            self.stdout.write(f'  Label : {tok.label or "(none)"}')
            self.stdout.write('')
            self.stdout.write('Use this header in every API request:')
            self.stdout.write(f'  Authorization: Token {raw}')

        elif action == 'list':
            username = options.get('username')
            if not username:
                raise CommandError('--username is required for list.')
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                raise CommandError(f'User "{username}" does not exist.')
            tokens = APIToken.objects.filter(user=user)
            if not tokens.exists():
                self.stdout.write(f'No tokens found for {username}.')
                return
            for t in tokens:
                status = 'active' if t.is_active else 'revoked'
                last = t.last_used_at.isoformat() if t.last_used_at else 'never'
                self.stdout.write(
                    f'[{status}]  {t.token}  label="{t.label}"  last_used={last}  id={t.id}'
                )

        elif action == 'revoke':
            raw = options.get('token')
            if not raw:
                raise CommandError('--token is required for revoke.')
            updated = APIToken.objects.filter(token=raw).update(is_active=False)
            if updated:
                self.stdout.write(self.style.SUCCESS('Token revoked successfully.'))
            else:
                raise CommandError('Token not found.')
