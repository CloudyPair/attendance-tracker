FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt requirements-server.txt ./
RUN python -m pip install -r requirements-server.txt \
    && groupadd --gid 10001 flag \
    && useradd --uid 10001 --gid flag --create-home flag

COPY --chown=flag:flag manage.py ./
COPY --chown=flag:flag attendance ./attendance
COPY --chown=flag:flag attendance_project ./attendance_project
COPY --chown=flag:flag data ./data
COPY --chown=flag:flag deploy ./deploy
RUN mkdir -p /app/media /app/staticfiles && chown flag:flag /app/media /app/staticfiles
USER flag
EXPOSE 8000
CMD ["gunicorn", "--config", "deploy/gunicorn.conf.py", "attendance_project.wsgi:application"]
