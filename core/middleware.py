"""
Custom middleware for the Sharif Bot application.
"""
from django.utils.deprecation import MiddlewareMixin
from django.http import HttpResponse


class AllowAllHostsForMetricsMiddleware(MiddlewareMixin):
    """
    Middleware to allow all hosts for /metrics endpoint.
    This is needed when Prometheus scrapes from Docker containers.
    Fixes the issue where Docker container names with underscores are rejected.
    Must be placed BEFORE CommonMiddleware in MIDDLEWARE list.
    """

    def process_request(self, request):
        # Allow all hosts for /metrics endpoint
        if request.path == '/metrics' or request.path.startswith('/metrics/'):
            # Override the host header to a valid hostname
            # This prevents DisallowedHost errors for Docker container names with underscores
            # Extract port if present
            original_host = request.META.get('HTTP_HOST', '')
            if ':' in original_host:
                # Keep the port, but change hostname to localhost
                port = original_host.split(':', 1)[1]
                request.META['HTTP_HOST'] = f'localhost:{port}'
            else:
                request.META['HTTP_HOST'] = 'localhost'

            # Also update SERVER_NAME if present
            if 'SERVER_NAME' in request.META:
                request.META['SERVER_NAME'] = 'localhost'
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
