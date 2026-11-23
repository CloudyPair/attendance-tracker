import os

bind = "0.0.0.0:8000"
workers = int(os.getenv("WEB_CONCURRENCY", "2"))
threads = 2
worker_class = "gthread"
timeout = 90
accesslog = "-"
errorlog = "-"
capture_output = True
