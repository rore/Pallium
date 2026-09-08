from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import FeaturesConfig, _build_features_config
from app.dashboard import mount_dashboard


def test_dashboard_roi_flag_defaults_off_and_honors_env_override() -> None:
    assert FeaturesConfig().dashboard_roi is False
    assert _build_features_config({"features": {"dashboard_roi": True}}, {}).dashboard_roi is True
    assert _build_features_config(
        {"features": {"dashboard_roi": True}},
        {"PALLIUM_FEATURES_DASHBOARD_ROI": "false"},
    ).dashboard_roi is False


def test_dashboard_roi_view_and_reports_are_server_gated() -> None:
    disabled = FastAPI()
    mount_dashboard(disabled)
    with TestClient(disabled) as client:
        dashboard = client.get("/dashboard")
        assert '<body data-roi-enabled="false">' in dashboard.text
        assert dashboard.headers["cache-control"] == "no-store"
        assert client.get("/dashboard/api/effectiveness/reports").status_code == 404

    enabled = FastAPI()
    mount_dashboard(enabled, show_roi=True)
    with TestClient(enabled) as client:
        dashboard = client.get("/dashboard")
        assert '<body data-roi-enabled="true">' in dashboard.text
        assert 'body[data-roi-enabled="false"] .roi-only' in dashboard.text
        assert dashboard.headers["cache-control"] == "no-store"
        assert client.get("/dashboard/api/effectiveness/reports").status_code == 200
