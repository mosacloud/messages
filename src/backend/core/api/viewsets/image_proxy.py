"""API ViewSet for proxying external images."""

import logging
from urllib.parse import unquote

import magic
import requests
from django.conf import settings
from django.http import HttpResponse
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from core import models
from core.api import permissions
from core.utils import validate_url_safety

logger = logging.getLogger(__name__)


class ImageProxyViewSet(ViewSet):
    """
    ViewSet for proxying external images to protect user privacy.

    Images are fetched on-demand from external sources and served through
    the application. This prevents tracking pixels from leaking user IP
    addresses and browsing behavior to external servers.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        description="""Proxy an external image through the server.

        This endpoint fetches images from external sources and serves them
        through the application to protect user privacy. Requires the
        PROXY_EXTERNAL_IMAGES environment variable to be set to true.
        """,
        parameters=[
            OpenApiParameter(
                name="mailbox_id",
                type=str,
                location=OpenApiParameter.PATH,
                description="ID of the mailbox",
                required=True,
            ),
            OpenApiParameter(
                name="url",
                type=str,
                location=OpenApiParameter.QUERY,
                description="The external image URL to proxy",
                required=True,
            ),
        ],
        responses={
            200: OpenApiResponse(description="Image content"),
            400: OpenApiResponse(description="Invalid request"),
            403: OpenApiResponse(description="Forbidden"),
            413: OpenApiResponse(description="Image too large"),
            502: OpenApiResponse(description="Failed to fetch external image"),
        },
    )
    def list(self, request, mailbox_id=None):
        """Proxy an external image through the server."""
        try:
            mailbox = models.Mailbox.objects.get(pk=mailbox_id)
        except models.Mailbox.DoesNotExist:
            return Response(
                {"error": "Mailbox not found"}, status=status.HTTP_404_NOT_FOUND
            )

        if not mailbox.accesses.filter(user=request.user).exists():
            return Response(
                {"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN
            )

        if not settings.PROXY_EXTERNAL_IMAGES:
            return Response(
                {"error": "Image proxy not enabled"},
                status=status.HTTP_403_FORBIDDEN,
            )

        url = request.query_params.get("url")
        if not url:
            return Response(
                {"error": "Missing url parameter"}, status=status.HTTP_400_BAD_REQUEST
            )

        url = unquote(url)

        # SSRF protection: validate URL before making any request
        is_safe, error_message = validate_url_safety(url)
        if not is_safe:
            logger.warning("Blocked unsafe URL: %s - %s", url, error_message)
            # Return placeholder image instead of JSON error for better UX
            svg_placeholder = """<svg xmlns="http://www.w3.org/2000/svg" width="400" height="100" viewBox="0 0 400 100">
  <rect width="100%" height="100%" fill="#f8f9fa"/>
  <text x="50%" y="50%" text-anchor="middle" dominant-baseline="middle"
        font-family="system-ui, -apple-system, sans-serif" font-size="14" fill="#6c757d">
    🚫 Image blocked for security reasons
  </text>
</svg>"""
            return HttpResponse(
                svg_placeholder,
                content_type="image/svg+xml",
                status=403,
            )

        max_size = settings.PROXY_MAX_IMAGE_SIZE_MB * 1024 * 1024

        try:
            response = requests.get(
                url,
                timeout=10,
                stream=True,
                headers={"User-Agent": "Messages-ImageProxy/1.0"},
                allow_redirects=False,  # Prevent redirect-based SSRF bypass
            )
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if not content_type.startswith("image/"):
                return Response(
                    {"error": "Not an image"}, status=status.HTTP_400_BAD_REQUEST
                )

            # Safely parse Content-Length header
            try:
                content_length = int(response.headers.get("content-length", 0))
            except (TypeError, ValueError):
                content_length = 0

            # Use Content-Length as a hint, but don't trust it completely
            if content_length and content_length > max_size:
                return Response(
                    {"error": "Image too large"},
                    status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                )

            # Stream content in chunks to prevent memory exhaustion
            chunks = []
            total_size = 0
            chunk_size = 8192  # 8KB chunks

            for chunk in response.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue

                total_size += len(chunk)

                # Enforce size limit while streaming
                if total_size > max_size:
                    logger.warning(
                        "Image from %s exceeds size limit: %d bytes", url, total_size
                    )
                    return Response(
                        {"error": "Image too large"},
                        status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    )

                chunks.append(chunk)

            image_content = b"".join(chunks)

            # Validate that content is actually an image (defense in depth)
            mime_type = magic.from_buffer(image_content, mime=True)
            if not mime_type.startswith("image/"):
                logger.warning("Content from %s is not a valid image: %s", url, mime_type)
                # Return placeholder image for invalid content
                svg_placeholder = """<svg xmlns="http://www.w3.org/2000/svg" width="400" height="100" viewBox="0 0 400 100">
  <rect width="100%" height="100%" fill="#f8f9fa"/>
  <text x="50%" y="50%" text-anchor="middle" dominant-baseline="middle"
        font-family="system-ui, -apple-system, sans-serif" font-size="14" fill="#6c757d">
    🚫 Image blocked for security reasons
  </text>
</svg>"""
                return HttpResponse(
                    svg_placeholder,
                    content_type="image/svg+xml",
                    status=400,
                )

            return HttpResponse(
                image_content,
                content_type=content_type,
                headers={
                    "Cache-Control": "public, max-age=2592000",
                    "X-Proxied-From": url,
                },
            )

        except requests.RequestException as e:
            logger.warning("Failed to fetch external image from %s: %s", url, e)
            return Response(
                {"error": "Failed to fetch image"}, status=status.HTTP_502_BAD_GATEWAY
            )
