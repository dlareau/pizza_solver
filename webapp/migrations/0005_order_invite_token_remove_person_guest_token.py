from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('webapp', '0004_pizzavendor_group'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='invite_token',
            field=models.UUIDField(blank=True, null=True, unique=True),
        ),
        migrations.RemoveField(
            model_name='person',
            name='guest_token',
        ),
    ]
