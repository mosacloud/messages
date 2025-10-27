"""API ViewSet for proxying external images."""

import logging
from urllib.parse import unquote

import requests
from django.http import HttpResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from core import models
from core.api import permissions

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
        _proxy_external_images setting to be enabled for the mailbox domain.
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
            200: OpenApiParameter(description="Image content"),
            400: OpenApiParameter(description="Invalid request"),
            403: OpenApiParameter(description="Forbidden"),
            413: OpenApiParameter(description="Image too large"),
            502: OpenApiParameter(description="Failed to fetch external image"),
        },
    )
    @action(detail=False, methods=["get"], url_path="")
    def proxy(self, request, mailbox_id=None):
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

        custom_attrs = mailbox.domain.custom_attributes or {}
        if not custom_attrs.get("_proxy_external_images"):
            return Response(
                {"error": "Image proxy not enabled for this domain"},
                status=status.HTTP_403_FORBIDDEN,
            )

        url = request.query_params.get("url")
        if not url:
            return Response(
                {"error": "Missing url parameter"}, status=status.HTTP_400_BAD_REQUEST
            )

        url = unquote(url)

        max_size = custom_attrs.get("_proxy_max_image_size_mb", 5) * 1024 * 1024

        try:
            response = requests.get(
                url,
                timeout=10,
                stream=True,
                headers={"User-Agent": "Messages-ImageProxy/1.0"},
            )
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if not content_type.startswith("image/"):
                return Response(
                    {"error": "Not an image"}, status=status.HTTP_400_BAD_REQUEST
                )

            content_length = int(response.headers.get("content-length", 0))
            if content_length > max_size:
                return Response(
                    {"error": "Image too large"},
                    status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                )

            image_content = response.content
            if len(image_content) > max_size:
                return Response(
                    {"error": "Image too large"},
                    status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
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
