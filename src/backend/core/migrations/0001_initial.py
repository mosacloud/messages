# Generated by Django 5.1.8 on 2025-04-29 14:13

import core.models
import django.core.validators
import django.db.models.deletion
import timezone_field.fields
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='Mailbox',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, help_text='primary key for the record as UUID', primary_key=True, serialize=False, verbose_name='id')),
                ('created_at', models.DateTimeField(auto_now_add=True, help_text='date and time at which a record was created', verbose_name='created on')),
                ('updated_at', models.DateTimeField(auto_now=True, help_text='date and time at which a record was last updated', verbose_name='updated on')),
                ('local_part', models.CharField(max_length=255, verbose_name='local part')),
            ],
            options={
                'verbose_name': 'mailbox',
                'verbose_name_plural': 'mailboxes',
                'db_table': 'messages_mailbox',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='MailDomain',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, help_text='primary key for the record as UUID', primary_key=True, serialize=False, verbose_name='id')),
                ('created_at', models.DateTimeField(auto_now_add=True, help_text='date and time at which a record was created', verbose_name='created on')),
                ('updated_at', models.DateTimeField(auto_now=True, help_text='date and time at which a record was last updated', verbose_name='updated on')),
                ('name', models.CharField(max_length=255, verbose_name='name')),
            ],
            options={
                'verbose_name': 'mail domain',
                'verbose_name_plural': 'mail domains',
                'db_table': 'messages_maildomain',
            },
        ),
        migrations.CreateModel(
            name='User',
            fields=[
                ('password', models.CharField(max_length=128, verbose_name='password')),
                ('last_login', models.DateTimeField(blank=True, null=True, verbose_name='last login')),
                ('is_superuser', models.BooleanField(default=False, help_text='Designates that this user has all permissions without explicitly assigning them.', verbose_name='superuser status')),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, help_text='primary key for the record as UUID', primary_key=True, serialize=False, verbose_name='id')),
                ('created_at', models.DateTimeField(auto_now_add=True, help_text='date and time at which a record was created', verbose_name='created on')),
                ('updated_at', models.DateTimeField(auto_now=True, help_text='date and time at which a record was last updated', verbose_name='updated on')),
                ('sub', models.CharField(blank=True, help_text='Required. 255 characters or fewer. Letters, numbers, and @/./+/-/_/: characters only.', max_length=255, null=True, unique=True, validators=[django.core.validators.RegexValidator(message='Enter a valid sub. This value may contain only letters, numbers, and @/./+/-/_/: characters.', regex='^[\\w.@+-:]+\\Z')], verbose_name='sub')),
                ('full_name', models.CharField(blank=True, max_length=100, null=True, verbose_name='full name')),
                ('short_name', models.CharField(blank=True, max_length=20, null=True, verbose_name='short name')),
                ('email', models.EmailField(blank=True, max_length=254, null=True, verbose_name='identity email address')),
                ('admin_email', models.EmailField(blank=True, max_length=254, null=True, unique=True, verbose_name='admin email address')),
                ('language', models.CharField(choices=[('en-us', 'English'), ('fr-fr', 'French'), ('de-de', 'German')], default='en-us', help_text='The language in which the user wants to see the interface.', max_length=10, verbose_name='language')),
                ('timezone', timezone_field.fields.TimeZoneField(choices_display='WITH_GMT_OFFSET', default='UTC', help_text='The timezone in which the user wants to see times.', use_pytz=False)),
                ('is_device', models.BooleanField(default=False, help_text='Whether the user is a device or a real user.', verbose_name='device')),
                ('is_staff', models.BooleanField(default=False, help_text='Whether the user can log into this admin site.', verbose_name='staff status')),
                ('is_active', models.BooleanField(default=True, help_text='Whether this user should be treated as active. Unselect this instead of deleting accounts.', verbose_name='active')),
                ('groups', models.ManyToManyField(blank=True, help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.', related_name='user_set', related_query_name='user', to='auth.group', verbose_name='groups')),
                ('user_permissions', models.ManyToManyField(blank=True, help_text='Specific permissions for this user.', related_name='user_set', related_query_name='user', to='auth.permission', verbose_name='user permissions')),
            ],
            options={
                'verbose_name': 'user',
                'verbose_name_plural': 'users',
                'db_table': 'messages_user',
            },
            managers=[
                ('objects', core.models.UserManager()),
            ],
        ),
        migrations.CreateModel(
            name='Contact',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, help_text='primary key for the record as UUID', primary_key=True, serialize=False, verbose_name='id')),
                ('created_at', models.DateTimeField(auto_now_add=True, help_text='date and time at which a record was created', verbose_name='created on')),
                ('updated_at', models.DateTimeField(auto_now=True, help_text='date and time at which a record was last updated', verbose_name='updated on')),
                ('name', models.CharField(blank=True, max_length=255, null=True, verbose_name='name')),
                ('email', models.EmailField(max_length=254, verbose_name='email')),
                ('mailbox', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='contacts', to='core.mailbox')),
            ],
            options={
                'verbose_name': 'contact',
                'verbose_name_plural': 'contacts',
                'db_table': 'messages_contact',
                'unique_together': {('email', 'mailbox')},
            },
        ),
        migrations.CreateModel(
            name='MailboxAccess',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, help_text='primary key for the record as UUID', primary_key=True, serialize=False, verbose_name='id')),
                ('created_at', models.DateTimeField(auto_now_add=True, help_text='date and time at which a record was created', verbose_name='created on')),
                ('updated_at', models.DateTimeField(auto_now=True, help_text='date and time at which a record was last updated', verbose_name='updated on')),
                ('permission', models.CharField(choices=[('read', 'Read'), ('edit', 'Edit'), ('send', 'Send'), ('delete', 'Delete'), ('admin', 'Admin')], default='read', max_length=20, verbose_name='permission')),
                ('mailbox', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='accesses', to='core.mailbox')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='mailbox_accesses', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'mailbox access',
                'verbose_name_plural': 'mailbox accesses',
                'db_table': 'messages_mailboxaccess',
            },
        ),
        migrations.AddField(
            model_name='mailbox',
            name='domain',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.maildomain'),
        ),
        migrations.CreateModel(
            name='Thread',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, help_text='primary key for the record as UUID', primary_key=True, serialize=False, verbose_name='id')),
                ('created_at', models.DateTimeField(auto_now_add=True, help_text='date and time at which a record was created', verbose_name='created on')),
                ('updated_at', models.DateTimeField(auto_now=True, help_text='date and time at which a record was last updated', verbose_name='updated on')),
                ('subject', models.CharField(max_length=255, verbose_name='subject')),
                ('snippet', models.TextField(blank=True, verbose_name='snippet')),
                ('is_read', models.BooleanField(default=False, verbose_name='is read')),
                ('mailbox', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='threads', to='core.mailbox')),
            ],
            options={
                'verbose_name': 'thread',
                'verbose_name_plural': 'threads',
                'db_table': 'messages_thread',
            },
        ),
        migrations.CreateModel(
            name='Message',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, help_text='primary key for the record as UUID', primary_key=True, serialize=False, verbose_name='id')),
                ('created_at', models.DateTimeField(auto_now_add=True, help_text='date and time at which a record was created', verbose_name='created on')),
                ('updated_at', models.DateTimeField(auto_now=True, help_text='date and time at which a record was last updated', verbose_name='updated on')),
                ('subject', models.CharField(max_length=255, verbose_name='subject')),
                ('is_draft', models.BooleanField(default=False, verbose_name='is draft')),
                ('is_sender', models.BooleanField(default=False, verbose_name='is sender')),
                ('is_starred', models.BooleanField(default=False, verbose_name='is starred')),
                ('is_trashed', models.BooleanField(default=False, verbose_name='is trashed')),
                ('is_read', models.BooleanField(default=False, verbose_name='is read')),
                ('trashed_at', models.DateTimeField(blank=True, null=True, verbose_name='trashed at')),
                ('sent_at', models.DateTimeField(blank=True, null=True, verbose_name='sent at')),
                ('read_at', models.DateTimeField(blank=True, null=True, verbose_name='read at')),
                ('mta_sent', models.BooleanField(default=False, verbose_name='mta sent')),
                ('mime_id', models.CharField(blank=True, max_length=998, null=True, verbose_name='mime id')),
                ('raw_mime', models.BinaryField(blank=True, default=b'')),
                ('draft_body', models.TextField(blank=True, null=True, verbose_name='draft body')),
                ('parent', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='core.message')),
                ('sender', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.contact')),
                ('thread', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='messages', to='core.thread')),
            ],
            options={
                'verbose_name': 'message',
                'verbose_name_plural': 'messages',
                'db_table': 'messages_message',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='mailbox',
            unique_together={('local_part', 'domain')},
        ),
        migrations.CreateModel(
            name='MessageRecipient',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, help_text='primary key for the record as UUID', primary_key=True, serialize=False, verbose_name='id')),
                ('created_at', models.DateTimeField(auto_now_add=True, help_text='date and time at which a record was created', verbose_name='created on')),
                ('updated_at', models.DateTimeField(auto_now=True, help_text='date and time at which a record was last updated', verbose_name='updated on')),
                ('type', models.CharField(choices=[('to', 'To'), ('cc', 'Cc'), ('bcc', 'Bcc')], default='to', max_length=20, verbose_name='type')),
                ('contact', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='messages', to='core.contact')),
                ('message', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='recipients', to='core.message')),
            ],
            options={
                'verbose_name': 'message recipient',
                'verbose_name_plural': 'message recipients',
                'db_table': 'messages_messagerecipient',
                'unique_together': {('message', 'contact', 'type')},
            },
        ),
    ]
