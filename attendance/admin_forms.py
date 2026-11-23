"""Небольшие формы служебного раздела: профиль и учетная запись вместе."""
from django import forms
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.db import transaction
from django.forms.models import BaseInlineFormSet

from .models import Course, GroupRole, Student, Teacher, User


class ProfileFields(forms.ModelForm):
    username = forms.CharField(label="Логин", max_length=150, validators=[UnicodeUsernameValidator()])
    last_name = forms.CharField(label="Фамилия", max_length=150)
    first_name = forms.CharField(label="Имя и отчество", max_length=150)
    password = forms.CharField(label="Новый пароль", required=False, widget=forms.PasswordInput,
                               help_text="При создании без пароля используется 1234. При изменении пустое поле сохраняет текущий пароль.")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            for field in ("username", "first_name", "last_name"):
                self.initial[field] = getattr(self.instance.user, field)

    def clean_username(self):
        username = self.cleaned_data["username"]
        matches = User.objects.filter(username=username)
        if self.instance.pk:
            matches = matches.exclude(pk=self.instance.user_id)
        if matches.exists():
            raise forms.ValidationError("Этот логин уже занят")
        return username

    def save(self, commit=True):
        profile = super().save(commit=False)
        user = profile.user if profile.user_id else User()
        for field in ("username", "first_name", "last_name"):
            setattr(user, field, self.cleaned_data[field])
        password = self.cleaned_data.get("password")
        if password or not user.pk:
            user.set_password(password or "1234")
        user.save()
        profile.user = user
        if commit:
            profile.save()
            self.save_m2m()
        return profile


class StudentManagementForm(ProfileFields):
    class Meta:
        model = Student
        fields = ("username", "last_name", "first_name", "role", "password")

    def _get_validation_exclusions(self):
        exclusions = super()._get_validation_exclusions()
        # Смена старосты проверяется по всему набору строк, а не по старым ролям в БД.
        exclusions.add("role")
        return exclusions


class StudentManagementFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        seen_roles, usernames = set(), set()
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            username = form.cleaned_data.get("username")
            if username and username in usernames:
                raise forms.ValidationError("У студентов должны быть разные логины")
            usernames.add(username)
            role = form.cleaned_data.get("role")
            if role in (GroupRole.HEADMAN, GroupRole.DEPUTY):
                if role in seen_roles:
                    raise forms.ValidationError("В группе может быть только один староста и один заместитель")
                seen_roles.add(role)

    @transaction.atomic
    def save(self, commit=True):
        if commit:
            changing = [form.instance.pk for form in self.initial_forms
                        if "role" in form.changed_data and not form.cleaned_data.get("DELETE")]
            Student.objects.filter(pk__in=changing).update(role=GroupRole.MEMBER)
        return super().save(commit=commit)


class TeacherManagementForm(ProfileFields):
    courses = forms.ModelMultipleChoiceField(label="Предметы и группы", queryset=Course.objects.none(),
        required=False, widget=forms.SelectMultiple(attrs={"size": 9}),
        help_text="Выберите предметы у нужных групп. Для нескольких вариантов удерживайте Ctrl.")

    class Meta:
        model = Teacher
        fields = ("username", "last_name", "first_name", "password", "courses")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["courses"].queryset = Course.objects.select_related("subject", "group").order_by("subject__name", "group__name")
        if self.instance.pk:
            self.initial["courses"] = self.instance.courses.all()

    def _save_m2m(self):
        super()._save_m2m()
        self.instance.courses.set(self.cleaned_data["courses"])


class ScheduleDownloadForm(forms.Form):
    group_name = forms.CharField(label="Группа в МИЭТ", max_length=50)
