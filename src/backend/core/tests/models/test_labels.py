"""Tests for Label model ordering changes from migration 0018."""

import pytest

from core import factories
from core import models as core_models


@pytest.mark.django_db
class TestLabelOrdering:
    """Test Label model ordering changes from migration 0018."""

    def test_label_ordering_by_slug(self):
        """Test that Labels are ordered by slug field."""
        # Create labels in random order
        factories.LabelFactory(name="Charlie", slug="charlie")
        factories.LabelFactory(name="Alpha", slug="alpha")
        factories.LabelFactory(name="Beta", slug="beta")

        # Get all labels from database (should be ordered by slug)
        labels = list(core_models.Label.objects.all())

        # Verify ordering is by slug (alphabetical)
        assert len(labels) == 3
        assert labels[0].slug == "alpha"
        assert labels[1].slug == "beta"
        assert labels[2].slug == "charlie"

    def test_label_ordering_with_hierarchical_slugs(self):
        """Test that Labels with hierarchical slugs are ordered correctly."""
        mailbox = factories.MailboxFactory()
        # Create labels with hierarchical names/slugs
        factories.LabelFactory(name="Work", mailbox=mailbox)
        factories.LabelFactory(name="Work/Projects", mailbox=mailbox)
        factories.LabelFactory(name="Work/Meetings", mailbox=mailbox)
        factories.LabelFactory(name="Personal", mailbox=mailbox)

        # Get all labels from database (should be ordered by slug)
        labels = list(core_models.Label.objects.all())

        # Verify ordering is by slug (alphabetical)
        assert len(labels) == 4

        # Find our labels in the ordered list
        assert labels[0].slug == "personal"
        assert labels[1].slug == "work"
        assert labels[2].slug == "work-meetings"
        assert labels[3].slug == "work-projects"

    def test_label_ordering_with_accents(self):
        """Test that Labels with accented characters are ordered correctly."""
        # Create labels with accented characters
        factories.LabelFactory(name="État civil")
        factories.LabelFactory(name="Enfance")
        factories.LabelFactory(name="Urbanisme")

        # Get all labels from database (should be ordered by slug)
        labels = list(core_models.Label.objects.all())

        # Verify ordering is by slug (alphabetical)
        assert len(labels) == 3

        # Find our labels in the ordered list
        assert labels[0].slug == "enfance"
        assert labels[1].slug == "etat-civil"
        assert labels[2].slug == "urbanisme"

    def test_label_meta_ordering_attribute(self):
        """Test that Label model has correct ordering in Meta class."""
        # Check that the Meta class has the correct ordering
        assert core_models.Label._meta.ordering == ["slug"]

    def test_label_queryset_ordering(self):
        """Test that Label queryset respects the ordering."""
        # Create labels in random order
        factories.LabelFactory(name="Zebra", slug="zebra")
        factories.LabelFactory(name="Alpha", slug="alpha")
        factories.LabelFactory(name="Beta", slug="beta")

        # Get queryset without explicit ordering
        labels = core_models.Label.objects.all()

        # Verify the queryset is ordered by slug
        label_slugs = list(labels.values_list("slug", flat=True))
        assert label_slugs == sorted(label_slugs)

    def test_label_ordering_with_same_mailbox(self):
        """Test that Labels are ordered correctly within the same mailbox."""
        mailbox = factories.MailboxFactory()

        # Create labels in random order for the same mailbox
        factories.LabelFactory(name="Charlie", slug="charlie", mailbox=mailbox)
        factories.LabelFactory(name="Alpha", slug="alpha", mailbox=mailbox)
        factories.LabelFactory(name="Beta", slug="beta", mailbox=mailbox)

        # Get labels for this specific mailbox
        labels = list(mailbox.labels.all())

        # Verify ordering is by slug (alphabetical)
        assert len(labels) == 3
        assert labels[0].slug == "alpha"
        assert labels[1].slug == "beta"
        assert labels[2].slug == "charlie"

    def test_label_ordering_with_numbers(self):
        """Test that Labels with numbers in slugs are ordered correctly."""
        # Create labels with numbers in slugs
        factories.LabelFactory(name="Label 1")
        factories.LabelFactory(name="Label 10")
        factories.LabelFactory(name="Label 2")

        # Get all labels from database (should be ordered by slug)
        labels = list(core_models.Label.objects.all())

        # Verify ordering is by slug (alphabetical, not numerical)
        assert len(labels) == 3

        # Find our labels in the ordered list
        assert labels[0].slug == "label-1"
        assert labels[1].slug == "label-10"
        assert labels[2].slug == "label-2"
