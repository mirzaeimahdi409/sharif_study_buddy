# Generated migration for adding external_id to KnowledgeDocument
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='knowledgedocument',
            name='external_id',
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text='External document ID from RAG service',
                max_length=255,
                null=True
            ),
        ),
        migrations.AlterModelOptions(
            name='knowledgedocument',
            options={'ordering': ['-created_at']},
        ),
        migrations.AddIndex(
            model_name='knowledgedocument',
            index=models.Index(fields=['indexed_in_rag', 'created_at'], name='core_knowle_indexe_created_idx'),
        ),
    ]










