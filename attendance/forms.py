from datetime import date

from django import forms
from django.core.validators import MaxValueValidator, MinValueValidator
from django.forms import formset_factory

from attendance.models import AttendanceStatus

DATE_VALIDATORS = [MinValueValidator(date(2000, 1, 1)), MaxValueValidator(date(2099, 12, 31))]


class ScheduleFilterForm(forms.Form):
    date = forms.DateField(label="Дата", validators=DATE_VALIDATORS,
                           widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    mode = forms.ChoiceField(choices=[("day", "День"), ("week", "Неделя")], required=False)


class PeriodForm(forms.Form):
    start = forms.DateField(label="С", validators=DATE_VALIDATORS,
                            widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    end = forms.DateField(label="По", validators=DATE_VALIDATORS,
                          widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))

    def clean(self):
        data = super().clean()
        if data.get("start") and data.get("end") and data["start"] > data["end"]:
            raise forms.ValidationError("Начало периода должно быть не позже окончания")
        return data


class MarkForm(forms.Form):
    student_id = forms.IntegerField(widget=forms.HiddenInput)
    status = forms.ChoiceField(choices=AttendanceStatus.choices, widget=forms.RadioSelect)
    change_reason = forms.CharField(required=False, max_length=2000, widget=forms.HiddenInput)


MarkFormSet = formset_factory(MarkForm, extra=0, max_num=500, validate_max=True, absolute_max=500)


class MarkingForm(forms.Form):
    sheet = forms.CharField(widget=forms.HiddenInput)
    reason = forms.CharField(label="Причина правки", required=False, max_length=2000,
                             widget=forms.HiddenInput)


class ThresholdForm(forms.Form):
    threshold = forms.IntegerField(label="Порог посещаемости, %", min_value=0, max_value=100,
                                    widget=forms.NumberInput(attrs={"min": 0, "max": 100}))
