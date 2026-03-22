from rest_framework.views import exception_handler
from rest_framework.response import Response


def custom_exception_handler(exc: Exception, context: dict) -> Response | None:
    """
    Wraps DRF's default exception response in our { error, detail } envelope.

    Standard DRF errors come back as:
      { "detail": "Not found." }
      { "field": ["error msg"] }

    We normalise to:
      { "error": "Not found." }          (for string detail)
      { "error": { "field": [...] } }    (for validation errors)
    """
    response = exception_handler(exc, context)

    if response is not None:
        data = response.data
        if isinstance(data, dict) and "detail" in data and len(data) == 1:
            response.data = {"error": str(data["detail"])}
        elif isinstance(data, dict):
            response.data = {"error": data}
        else:
            response.data = {"error": data}

    return response
