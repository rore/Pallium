"""W5 PR 1 — [features] typed_extraction_shadow flag parsing tests."""

from __future__ import annotations

import pytest

from app.config import FeaturesConfig, _build_features_config


class TestTypedExtractionShadowFlagParsing:
    def test_default_is_false(self):
        cfg = FeaturesConfig()
        assert cfg.typed_extraction_shadow is False

    def test_missing_features_section_defaults_to_false(self):
        cfg = _build_features_config({}, {})
        assert cfg.typed_extraction_shadow is False

    def test_toml_true(self):
        cfg = _build_features_config(
            {"features": {"typed_extraction_shadow": True}}, {}
        )
        assert cfg.typed_extraction_shadow is True

    def test_toml_false_stays_false(self):
        cfg = _build_features_config(
            {"features": {"typed_extraction_shadow": False}}, {}
        )
        assert cfg.typed_extraction_shadow is False

    def test_env_var_true_overrides_toml_false(self):
        cfg = _build_features_config(
            {"features": {"typed_extraction_shadow": False}},
            {"PALLIUM_FEATURES_TYPED_EXTRACTION_SHADOW": "true"},
        )
        assert cfg.typed_extraction_shadow is True

    def test_env_var_false_overrides_toml_true(self):
        cfg = _build_features_config(
            {"features": {"typed_extraction_shadow": True}},
            {"PALLIUM_FEATURES_TYPED_EXTRACTION_SHADOW": "false"},
        )
        assert cfg.typed_extraction_shadow is False

    def test_env_var_alone_true(self):
        cfg = _build_features_config(
            {},
            {"PALLIUM_FEATURES_TYPED_EXTRACTION_SHADOW": "true"},
        )
        assert cfg.typed_extraction_shadow is True

    def test_flag_independent_of_operational_fact_derivation(self):
        # Enabling one flag does not affect the other.
        cfg = _build_features_config(
            {
                "features": {
                    "operational_fact_derivation": True,
                    "typed_extraction_shadow": False,
                }
            },
            {},
        )
        assert cfg.operational_fact_derivation is True
        assert cfg.typed_extraction_shadow is False

        cfg = _build_features_config(
            {
                "features": {
                    "operational_fact_derivation": False,
                    "typed_extraction_shadow": True,
                }
            },
            {},
        )
        assert cfg.operational_fact_derivation is False
        assert cfg.typed_extraction_shadow is True

    def test_invalid_features_section_raises(self):
        with pytest.raises(ValueError, match="\\[features\\] must be a table"):
            _build_features_config({"features": "not-a-table"}, {})
