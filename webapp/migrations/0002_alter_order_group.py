import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('webapp', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='order',
            name='group',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='orders',
                to='webapp.pizzagroup',
            ),
        ),
    ]
