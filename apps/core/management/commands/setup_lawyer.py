import os
import secrets

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

RECOVERY_CODES = 10


class Command(BaseCommand):
    help = "Create the lawyer with a TOTP device and ten one-use recovery codes."

    def add_arguments(self, parser):
        parser.add_argument("--username", default=os.environ.get("LAWYER_USERNAME", "abogado"))
        parser.add_argument("--password", default=os.environ.get("LAWYER_PASSWORD"))

    def handle(self, *args, **options):
        if not options["password"]:
            raise CommandError("set LAWYER_PASSWORD or pass --password")

        user, _ = User.objects.get_or_create(username=options["username"])
        user.set_password(options["password"])
        user.is_staff = True
        user.save()

        totp, _ = TOTPDevice.objects.get_or_create(user=user, name="whatsapp")
        totp.confirmed = True
        totp.save()

        static, _ = StaticDevice.objects.get_or_create(user=user, name="recovery")
        static.confirmed = True
        static.save()
        static.token_set.all().delete()
        codes = [secrets.token_hex(4) for _ in range(RECOVERY_CODES)]
        StaticToken.objects.bulk_create(
            [StaticToken(device=static, token=code) for code in codes]
        )

        self.stdout.write(f"usuario: {user.username}")
        self.stdout.write(f"otpauth: {totp.config_url}")
        self.stdout.write("códigos de recuperación (un solo uso): " + " ".join(codes))
