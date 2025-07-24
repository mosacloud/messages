"""API ViewSet for sharing some public settings."""

from django.conf import settings

import rest_framework as drf
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import AllowAny

from core.ai.utils import is_ai_enabled, is_ai_summary_enabled


class ConfigView(drf.views.APIView):
    """API ViewSet for sharing some public settings."""

    permission_classes = [AllowAny]

    @extend_schema(
        tags=["config"],
        responses={
            200: OpenApiResponse(
                description="A dictionary of public configuration settings.",
                response={
                    "type": "object",
                    "properties": {
                        "ENVIRONMENT": {"type": "string", "readOnly": True},
                        "POSTHOG_KEY": {
                            "type": "string",
                            "nullable": True,
                            "readOnly": True,
                        },
                        "POSTHOG_HOST": {
                            "type": "string",
                            "nullable": True,
                            "readOnly": True,
                        },
                        "POSTHOG_SURVEY_ID": {
                            "type": "string",
                            "nullable": True,
                            "readOnly": True,
                        },
                        "LANGUAGES": {
                            "type": "array",
                            "items": {"type": "string"},
                            "readOnly": True,
                        },
                        "LANGUAGE_CODE": {"type": "string", "readOnly": True},
                        "AI_ENABLED": {"type": "boolean", "readOnly": True},
                        "AI_FEATURE_SUMMARY_ENABLED": {
                            "type": "boolean",
                            "readOnly": True,
                        },
                    },
                    "required": [
                        "ENVIRONMENT",
                        "POSTHOG_KEY",
                        "POSTHOG_HOST",
                        "POSTHOG_SURVEY_ID",
                        "LANGUAGES",
                        "LANGUAGE_CODE",
                        "AI_ENABLED",
                        "AI_FEATURE_SUMMARY_ENABLED",
                    ],
                },
            )
        },
        description="Return a dictionary of public settings for the frontend to consume.",
    )
    def get(self, request):
        """
        GET /api/v1.0/config/
            Return a dictionary of public settings.
        """
        array_settings = [
            "ENVIRONMENT",
            "POSTHOG_KEY",
            "POSTHOG_HOST",
            "POSTHOG_SURVEY_ID",
            "LANGUAGES",
            "LANGUAGE_CODE",
        ]
        dict_settings = {}
        for setting in array_settings:
            if hasattr(settings, setting):
                dict_settings[setting] = getattr(settings, setting)

        dict_settings["AI_ENABLED"] = is_ai_enabled()
        dict_settings["AI_FEATURE_SUMMARY_ENABLED"] = is_ai_summary_enabled()

        return drf.response.Response(dict_settings)
