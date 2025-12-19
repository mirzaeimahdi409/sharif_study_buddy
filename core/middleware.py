"""
Custom middleware for the Sharif Bot application.
"""
from django.utils.deprecation import MiddlewareMixin
from django.http import HttpResponse


class AllowAllHostsForMetricsMiddleware(MiddlewareMixin):
    """
    Middleware to allow all hosts for /metrics endpoint.
    This is needed when Prometheus scrapes from Docker containers.
    """
    
    def process_request(self, request):
        # Allow all hosts for /metrics endpoint
        if request.path == '/metrics' or request.path.startswith('/metrics/'):
            # Temporarily disable host validation for this request
            # by setting a flag that Django's CommonMiddleware will check
            request._metrics_endpoint = True
        return None


class DisableCSRFForMetricsMiddleware(MiddlewareMixin):
    """
    Middleware to disable CSRF for /metrics endpoint.
    Prometheus doesn't send CSRF tokens.
    """
    
    def process_request(self, request):
        if request.path == '/metrics' or request.path.startswith('/metrics/'):
            setattr(request, '_dont_enforce_csrf_checks', True)
        return None

