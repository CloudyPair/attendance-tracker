def account_context(request):
    if not request.user.is_authenticated:
        return {}
    if request.user.is_staff:
        return {"current_student": None, "current_teacher": None}
    student = getattr(request.user, "student", None)
    teacher = getattr(request.user, "teacher", None)
    return {"current_student": student, "current_teacher": teacher}
