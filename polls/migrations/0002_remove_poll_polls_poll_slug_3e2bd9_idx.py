
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('polls', '0001_initial'),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name='poll',
            name='polls_poll_slug_3e2bd9_idx',
        ),
    ]
