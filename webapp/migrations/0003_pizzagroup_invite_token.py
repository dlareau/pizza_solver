import uuid
import django.db.models.deletion
from django.db import migrations, models


def populate_invite_tokens(apps, schema_editor):
    PizzaGroup = apps.get_model('webapp', 'PizzaGroup')
    for group in PizzaGroup.objects.filter(invite_token__isnull=True):
        group.invite_token = uuid.uuid4()
        group.save(update_fields=['invite_token'])


class Migration(migrations.Migration):

    dependencies = [
        ('webapp', '0002_alter_order_group'),
    ]

    operations = [
        # Step 1: add nullable (existing rows get NULL)
        migrations.AddField(
            model_name='pizzagroup',
            name='invite_token',
            field=models.UUIDField(null=True, unique=True),
        ),
        # Step 2: populate unique UUIDs for existing rows
        migrations.RunPython(populate_invite_tokens, migrations.RunPython.noop),
        # Step 3: make non-nullable
        migrations.AlterField(
            model_name='pizzagroup',
            name='invite_token',
            field=models.UUIDField(default=uuid.uuid4, unique=True),
        ),
    ]
