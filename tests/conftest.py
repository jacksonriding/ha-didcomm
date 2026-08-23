"""Shared Home Assistant custom integration test fixtures."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow Home Assistant to load this repository's integration."""
    yield
