import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('webapp', '0005_order_invite_token_remove_person_guest_token'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='PizzaVendor',
            new_name='PizzaRestaurant',
        ),
        migrations.RenameModel(
            old_name='VendorTopping',
            new_name='RestaurantTopping',
        ),
        migrations.RenameField(
            model_name='order',
            old_name='vendor',
            new_name='restaurant',
        ),
        migrations.RenameField(
            model_name='restauranttopping',
            old_name='vendor',
            new_name='restaurant',
        ),
        migrations.AlterField(
            model_name='pizzarestaurant',
            name='group',
            field=models.ForeignKey(
                blank=True,
                help_text='Owning group (null = public restaurant, visible to everyone)',
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='restaurants',
                to='webapp.pizzagroup',
            ),
        ),
        migrations.AlterField(
            model_name='restauranttopping',
            name='topping',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='restaurants',
                to='webapp.topping',
            ),
        ),
        migrations.AlterField(
            model_name='pizzarestaurant',
            name='toppings',
            field=models.ManyToManyField(
                related_name='restaurants_offering',
                through='webapp.RestaurantTopping',
                to='webapp.topping',
            ),
        ),
    ]
