"""Сохранить авторов прежних правок при переходе от Student к User."""
from django.conf import settings
from django.db import migrations, models
from django.db.migrations.exceptions import IrreversibleError
import django.db.models.deletion


def move_actors(apps, schema_editor):
    database = schema_editor.connection.alias
    Student = apps.get_model("attendance", "Student")
    Change = apps.get_model("attendance", "AttendanceChange")
    Dispute = apps.get_model("attendance", "Dispute")
    Reason = apps.get_model("attendance", "AbsenceReason")
    users = dict(Student.objects.using(database).values_list("pk", "user_id"))
    changes = list(Change.objects.using(database).all())
    for change in changes:
        change.actor_user_id = users[change.changed_by_id]
    Change.objects.using(database).bulk_update(changes, ["actor_user"], batch_size=500)
    evidence = dict(Reason.objects.using(database).exclude(attachment="").values_list("record_id", "attachment"))
    disputes = list(Dispute.objects.using(database).all())
    for dispute in disputes:
        dispute.resolver_user_id = users.get(dispute.resolved_by_id)
        dispute.attachment = evidence.get(dispute.record_id, "")
    Dispute.objects.using(database).bulk_update(disputes, ["resolver_user", "attachment"], batch_size=500)


def restore_student_actors(apps, schema_editor):
    database = schema_editor.connection.alias
    Student = apps.get_model("attendance", "Student")
    Change = apps.get_model("attendance", "AttendanceChange")
    Dispute = apps.get_model("attendance", "Dispute")
    students = dict(Student.objects.using(database).values_list("user_id", "pk"))
    changes = list(Change.objects.using(database).all())
    disputes = list(Dispute.objects.using(database).all())
    if any(c.actor_user_id not in students for c in changes) or any(
            d.resolver_user_id and d.resolver_user_id not in students for d in disputes):
        raise IrreversibleError("Есть решения преподавателей: прежняя схема поддерживает только студентов")
    for change in changes:
        change.changed_by_id = students[change.actor_user_id]
    for dispute in disputes:
        dispute.resolved_by_id = students.get(dispute.resolver_user_id)
    Change.objects.using(database).bulk_update(changes, ["changed_by"], batch_size=500)
    Dispute.objects.using(database).bulk_update(disputes, ["resolved_by"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [("attendance", "0003_delegation_expiry_notified_at_notification_attempts_and_more")]
    operations = [
        migrations.AlterField(model_name="attendancechange", name="changed_by",
            field=models.ForeignKey(to="attendance.student", null=True, related_name="+",
                on_delete=django.db.models.deletion.PROTECT, verbose_name="изменил")),
        migrations.AddField(model_name="attendancechange", name="actor_user",
            field=models.ForeignKey(to=settings.AUTH_USER_MODEL, null=True, related_name="+",
                on_delete=django.db.models.deletion.PROTECT, verbose_name="изменил")),
        migrations.AddField(model_name="dispute", name="resolver_user",
            field=models.ForeignKey(to=settings.AUTH_USER_MODEL, null=True, blank=True, related_name="+",
                on_delete=django.db.models.deletion.SET_NULL, verbose_name="рассмотрел")),
        migrations.AddField(model_name="dispute", name="attachment",
            field=models.FileField(blank=True, upload_to="disputes/%Y/%m/", verbose_name="подтверждающий документ")),
        migrations.RunPython(move_actors, restore_student_actors),
        migrations.RemoveField(model_name="attendancechange", name="changed_by"),
        migrations.RemoveField(model_name="dispute", name="resolved_by"),
        migrations.RenameField(model_name="attendancechange", old_name="actor_user", new_name="changed_by"),
        migrations.RenameField(model_name="dispute", old_name="resolver_user", new_name="resolved_by"),
        migrations.AlterField(model_name="attendancechange", name="changed_by",
            field=models.ForeignKey(to=settings.AUTH_USER_MODEL, related_name="+",
                on_delete=django.db.models.deletion.PROTECT, verbose_name="изменил")),
    ]
