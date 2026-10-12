# ЛР2. Рефакторинг

Проверка, что поведение не изменилось: вывод `python manage.py demo` до и после
каждого шага одинаковый (в ЛР6 это будут делать модульные тесты).

## Выполненные шаги

### 1. Extract Method: `Student.has_active_delegation(now)`

Выражение `any(d.is_active(now) for d in user.delegations.all())` повторялось в
`AccessPolicy.can_mark` и `AccessPolicy.can_assign_delegate`
(`attendance/services/policy.py`). Вынесено в метод модели `Student`
(`attendance/models.py`) — знание о том, как устроен список замен, теперь в одном месте.

```python
# было
has_role = user.is_headman_or_deputy() or any(d.is_active(now) for d in user.delegations.all())
# стало
has_role = user.is_headman_or_deputy() or user.has_active_delegation(now)
```

### 2. Extract Method: `Student.belongs_to(group)`

Проверка «студент состоит в группе X» повторялась в четырёх местах:
`can_mark`, `can_assign_delegate`, `can_resolve_dispute`, `Delegation.revoke`.
Заменена одним методом.

```python
# было
if user.group is None or user.group_id != lesson.course.group_id:
# стало
if not user.belongs_to(lesson.course.group):
```

### 3. Replace Inheritance with Delegation: `User` → профили `Student` / `Teacher`

В первой версии диаграммы классов `Student` и `Teacher` наследовались от
`User`. Теперь учётная запись — одна модель `User` (на базе `AbstractUser`:
пароль, вход, права админки), а `Student` и `Teacher` — профили со связью
1 : 0..1 (`user.student`, `user.teacher`). Причина: аутентификацию даёт
`django.contrib.auth`, а наследование от пользователя усложняет вход и админку.
Изменение отражено в `UML/class_domain.puml`.

### 4. Удаление дублирующего слоя (Inline Class)

Сначала классы диаграммы были написаны дважды: «чистые» Python-классы
(`attendance/domain`) для правил и Django-модели для хранения, плюс
преобразователь между ними. Правила перенесены в методы моделей, а
дублирующие классы и преобразователь удалены. В результате один класс
диаграммы соответствует ровно одному классу кода. Без Django остался только
`AttendanceCalculator` (`attendance/services/calculator.py`): ему не нужна БД.

## Что показать вживую в VS Code (Pylance)

| Операция | Как | Пример |
|---|---|---|
| Rename | F2 на имени → новое имя → Enter (Shift+Enter — предпросмотр) | `AttendanceCalculator.allowed_misses` → `remaining_misses`: меняется в `calculator.py` и `management/commands/demo.py` |
| Extract Method | выделить выражение → Ctrl+. → «Extract method» | `self.used_at is None and now < self.expires_at` в `LinkToken.is_valid` |
| Extract Variable | выделить выражение → Ctrl+. → «Extract variable» | `present + missed` в `AttendanceCalculator.calculate` |
| Organize Imports | Shift+Alt+O | любой модуль в `attendance/services` |

После каждой операции — запустить `python manage.py demo` и показать, что
вывод не изменился. Затем Ctrl+Z, чтобы вернуть код.

Ограничения (вопрос 4 из методички): рефакторинг Python в Pylance опирается на
статический анализ, поэтому имена, к которым обращаются динамически
(`getattr`, строки в шаблонах Django, имена полей в `filter(...)`), он не
найдёт. Нет операций «Change Signature» / «Reorder parameters», как в Visual
Studio для C#. При переименовании поля модели нужна ещё миграция
(`makemigrations`), её IDE не создаёт.
