from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monitoring", "0002_ingestedtelegrammessage"),
    ]

    operations = [
        migrations.AddField(
            model_name="ingestedtelegrammessage",
            name="rag_document_id",
            field=models.CharField(
                max_length=255,
                blank=True,
                null=True,
                db_index=True,
                help_text="Document ID in RAG knowledge base (for deletion/reprocess)",
            ),
        ),
    ]




