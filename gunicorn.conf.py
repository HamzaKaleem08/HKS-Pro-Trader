import os

bind="0.0.0.0:"+os.environ.get("PORT","8080")
workers=1
worker_class="gthread"
threads=4
timeout=90
graceful_timeout=50
keepalive=5
preload_app=False
accesslog="-"
errorlog="-"
access_log_format='%(h)s %(m)s %(U)s %(s)s %(L)s'
limit_request_line=4096
limit_request_fields=40
limit_request_field_size=2048
