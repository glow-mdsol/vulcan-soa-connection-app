import os

import pytest


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".env.test"
    path.write_text(
        "FHIR_BASE_URL=http://localhost:8888/fhir\n"
        "OAUTH_AUTHORIZE_URL=http://localhost:8888/auth/authorize\n"
        "OAUTH_TOKEN_URL=http://localhost:8888/auth/token\n"
        "SMART_CLIENT_ID=test-client\n"
        "SMART_CLIENT_SECRET=test-secret\n"
        "REDIRECT_URI=http://localhost:8000/callback\n"
    )
    monkeypatch.setenv("ENV_FILE", str(path))
    return path


def test_settings_load_from_env_file(env_file):
    # Re-import after setting ENV_FILE so the module-level default re-evaluates.
    import importlib

    import vulcan_soa.config as config_module

    importlib.reload(config_module)
    settings = config_module.Settings()

    assert settings.fhir_base_url == "http://localhost:8888/fhir"
    assert settings.smart_client_id == "test-client"
    assert settings.frontend_url == "http://localhost:5173"
