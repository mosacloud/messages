"""Test suite for ImportFileUploadViewSet."""
# pylint: disable=redefined-outer-name, unused-argument

from unittest import mock

from django.urls import reverse

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from core import enums, factories
from core.api.utils import get_file_key

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    """Create a test user."""
    return factories.UserFactory()


@pytest.fixture
def api_client(user):
    """Create an authenticated API client."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class TestMessagesArchiveUploadViewSet:
    """Test the create action for direct and multipart uploads."""

    def test_api_messages_archive_create_direct_upload(self, api_client, user):
        """
        Test creating a direct upload should return a signed URL to upload
        the file directly to the message imports bucket.
        """
        url = reverse("messages-archive-upload-list")
        data = {"filename": "test.eml", "content_type": "message/rfc822"}

        with mock.patch(
            "core.api.viewsets.import_message.generate_presigned_url",
            return_value="https://s3.example.com/presigned-url?signature=abc123",
        ) as mock_generate_presigned_url:
            response = api_client.post(url, data, format="json")

            assert response.status_code == status.HTTP_201_CREATED
            assert response.data["filename"] == "test.eml"
            assert (
                response.data["url"]
                == "https://s3.example.com/presigned-url?signature=abc123"
            )

            # Verify generate_presigned_url was called correctly
            mock_generate_presigned_url.assert_called_once()
            call_args = mock_generate_presigned_url.call_args
            assert call_args[1]["ClientMethod"] == "put_object"
            assert call_args[1]["Params"]["Key"] == get_file_key(user.id, "test.eml")

    def test_api_messages_archive_create_multipart_upload(self, api_client):
        """Test creating a multipart upload (returns upload_id)."""
        url = reverse("messages-archive-upload-list") + "?multipart"
        data = {"filename": "large-file.mbox", "content_type": "application/mbox"}

        with mock.patch(
            "core.api.viewsets.import_message.MessagesArchiveUploadViewSet.storage.connection.meta.client.create_multipart_upload",  # pylint: disable=line-too-long
            return_value={"UploadId": "test-upload-id-12345"},
        ) as mock_create_multipart_upload:
            response = api_client.post(url, data, format="json")

        mock_create_multipart_upload.assert_called_once()
        assert response.status_code == status.HTTP_201_CREATED
        assert "filename" in response.data
        assert "upload_id" in response.data
        assert "url" not in response.data
        assert response.data["filename"] == "large-file.mbox"
        assert response.data["upload_id"] == "test-upload-id-12345"

    def test_api_messages_archive_create_upload_missing_content_type(self, api_client):
        """Test creating upload without content type."""
        url = reverse("messages-archive-upload-list")
        data = {"filename": "test.eml"}

        response = api_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["content_type"] == ["This field is required."]

    def test_api_messages_archive_create_upload_invalid_content_type(self, api_client):
        """Test creating upload with invalid content type."""
        url = reverse("messages-archive-upload-list")
        data = {
            "filename": "test.txt",
            "content_type": "text/html",  # Not in ARCHIVE_SUPPORTED_MIME_TYPES
        }

        response = api_client.post(url, data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["content_type"] == [
            "Only EML and MBOX files are supported."
        ]

    def test_api_messages_archive_create_upload_missing_filename(self, api_client):
        """Test creating upload without filename."""
        url = reverse("messages-archive-upload-list")
        data = {"content_type": "message/rfc822"}

        response = api_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["filename"] == ["This field is required."]

    def test_api_messages_archive_create_upload_unauthenticated(self):
        """Test creating upload without authentication."""
        client = APIClient()
        url = reverse("messages-archive-upload-list")
        data = {"filename": "test.eml", "content_type": "message/rfc822"}

        response = client.post(url, data, format="json")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.parametrize("mime_type", enums.ARCHIVE_SUPPORTED_MIME_TYPES)
    def test_api_messages_archive_create_upload_all_supported_mime_types(
        self, api_client, mime_type
    ):
        """Test creating upload with all supported MIME types."""
        url = reverse("messages-archive-upload-list")
        data = {"filename": "test-file", "content_type": mime_type}

        response = api_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_201_CREATED

    def test_api_messages_archive_create_part_upload(self, api_client, user):
        """Test creating a presigned URL for a part upload."""
        upload_id = "test-upload-id-12345"
        url = reverse(
            "messages-archive-upload-create-part-upload",
            kwargs={"upload_id": upload_id},
        )
        data = {"filename": "large-file.mbox", "part_number": 1}

        with mock.patch(
            "core.api.viewsets.import_message.generate_presigned_url",
            return_value="https://s3.example.com/presigned-url?signature=abc123&part_number=1",
        ) as mock_generate_presigned_url:
            response = api_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["filename"] == "large-file.mbox"
        assert response.data["part_number"] == 1
        assert response.data["upload_id"] == upload_id
        assert (
            response.data["url"]
            == "https://s3.example.com/presigned-url?signature=abc123&part_number=1"
        )

        # Verify generate_presigned_url was called correctly
        mock_generate_presigned_url.assert_called_once()
        call_args = mock_generate_presigned_url.call_args
        assert call_args[1]["ClientMethod"] == "upload_part"
        assert call_args[1]["Params"]["Key"] == get_file_key(user.id, "large-file.mbox")
        assert call_args[1]["Params"]["UploadId"] == upload_id
        assert call_args[1]["Params"]["PartNumber"] == 1

    def test_api_messages_archive_create_part_upload_multiple_parts(self, api_client):
        """Test creating presigned URLs for multiple parts."""
        upload_id = "test-upload-id-12345"
        url = reverse(
            "messages-archive-upload-create-part-upload",
            kwargs={"upload_id": upload_id},
        )

        for part_number in [1, 2, 3]:
            data = {"filename": "large-file.mbox", "part_number": part_number}

            with mock.patch(
                "core.api.viewsets.import_message.generate_presigned_url",
                return_value=f"https://s3.example.com/presigned-url?signature=abc123&part_number={part_number}",
            ):
                response = api_client.post(url, data, format="json")

            assert response.status_code == status.HTTP_201_CREATED
            assert response.data["part_number"] == part_number
            assert (
                response.data["url"]
                == f"https://s3.example.com/presigned-url?signature=abc123&part_number={part_number}"
            )

    def test_api_messages_archive_create_part_upload_missing_filename(self, api_client):
        """Test creating part upload without filename."""
        upload_id = "test-upload-id-12345"
        url = reverse(
            "messages-archive-upload-create-part-upload",
            kwargs={"upload_id": upload_id},
        )
        data = {"part_number": 1}

        response = api_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["filename"] == ["This field is required."]

    def test_api_messages_archive_create_part_upload_unauthenticated(self):
        """Test creating part upload without authentication."""
        client = APIClient()
        upload_id = "test-upload-id-12345"
        url = reverse(
            "messages-archive-upload-create-part-upload",
            kwargs={"upload_id": upload_id},
        )
        data = {"filename": "large-file.mbox", "part_number": 1}

        response = client.post(url, data, format="json")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_api_messages_archive_complete_multipart_upload(self, api_client, user):
        """Test completing a multipart upload."""
        upload_id = "test-upload-id-12345"
        url = reverse("messages-archive-upload-detail", kwargs={"upload_id": upload_id})
        data = {
            "filename": "large-file.mbox",
            "parts": [
                {"ETag": "etag1", "PartNumber": 1},
                {"ETag": "etag2", "PartNumber": 2},
                {"ETag": "etag3", "PartNumber": 3},
            ],
        }

        with mock.patch(
            "core.api.viewsets.import_message.MessagesArchiveUploadViewSet.storage.connection.meta.client.complete_multipart_upload",  # pylint: disable=line-too-long
            return_value=None,
        ) as mock_complete_multipart_upload:
            response = api_client.put(url, data, format="json")

        assert response.status_code == status.HTTP_204_NO_CONTENT

        # Verify complete_multipart_upload was called correctly
        mock_complete_multipart_upload.assert_called_once()
        call_args = mock_complete_multipart_upload.call_args
        assert call_args[1]["Key"] == get_file_key(user.id, "large-file.mbox")
        assert call_args[1]["UploadId"] == upload_id
        assert call_args[1]["MultipartUpload"]["Parts"] == [
            {"ETag": "etag1", "PartNumber": 1},
            {"ETag": "etag2", "PartNumber": 2},
            {"ETag": "etag3", "PartNumber": 3},
        ]

    def test_api_messages_archive_complete_multipart_upload_missing_filename(
        self, api_client
    ):
        """Test completing upload without filename."""
        upload_id = "test-upload-id-12345"
        url = reverse("messages-archive-upload-detail", kwargs={"upload_id": upload_id})
        data = {"parts": [{"ETag": "etag1", "PartNumber": 1}]}

        response = api_client.put(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["filename"] == ["This field is required."]

    def test_api_messages_archive_complete_multipart_upload_missing_parts(
        self, api_client
    ):
        """Test completing upload without parts."""
        upload_id = "test-upload-id-12345"
        url = reverse("messages-archive-upload-detail", kwargs={"upload_id": upload_id})
        data = {"filename": "large-file.mbox"}

        response = api_client.put(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["parts"] == ["This field is required."]

    def test_api_messages_archive_complete_multipart_upload_unauthenticated(self):
        """Test completing upload without authentication."""
        client = APIClient()
        upload_id = "test-upload-id-12345"
        url = reverse("messages-archive-upload-detail", kwargs={"upload_id": upload_id})
        data = {
            "filename": "large-file.mbox",
            "parts": [{"ETag": "etag1", "PartNumber": 1}],
        }

        response = client.put(url, data, format="json")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_api_messages_archive_abort_multipart_upload(self, api_client, user):
        """Test aborting a multipart upload."""
        upload_id = "test-upload-id-12345"
        url = reverse("messages-archive-upload-detail", kwargs={"upload_id": upload_id})
        data = {"filename": "large-file.mbox"}

        with mock.patch(
            "core.api.viewsets.import_message.MessagesArchiveUploadViewSet.storage.connection.meta.client.abort_multipart_upload",  # pylint: disable=line-too-long
            return_value=None,
        ) as mock_abort_multipart_upload:
            response = api_client.delete(url, data, format="json")

        assert response.status_code == status.HTTP_204_NO_CONTENT

        # Verify abort_multipart_upload was called correctly
        mock_abort_multipart_upload.assert_called_once()
        call_args = mock_abort_multipart_upload.call_args
        assert call_args[1]["Key"] == get_file_key(user.id, "large-file.mbox")
        assert call_args[1]["UploadId"] == upload_id

    def test_api_messages_archive_abort_multipart_upload_missing_filename(
        self, api_client
    ):
        """Test aborting upload without filename."""
        upload_id = "test-upload-id-12345"
        url = reverse("messages-archive-upload-detail", kwargs={"upload_id": upload_id})
        data = {}

        response = api_client.delete(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["filename"] == ["This field is required."]

    def test_api_messages_archive_abort_multipart_upload_unauthenticated(self):
        """Test aborting upload without authentication."""
        client = APIClient()
        upload_id = "test-upload-id-12345"
        url = reverse("messages-archive-upload-detail", kwargs={"upload_id": upload_id})
        data = {"filename": "large-file.mbox"}

        response = client.delete(url, data, format="json")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
