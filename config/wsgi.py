import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
_django_app = get_wsgi_application()


def application(environ, start_response):
    # Respond to ELB health checks before Django's SecurityMiddleware runs.
    # ELB sends the task's private IP as the Host header, which would cause
    # Django to return 400 (DisallowedHost) before reaching the view.
    if environ.get("PATH_INFO") == "/health/":
        start_response("200 OK", [("Content-Type", "application/json")])
        return [b'{"status": "ok"}']
    return _django_app(environ, start_response)
