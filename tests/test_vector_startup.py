"""Tests for vector index startup wiring, configuration, and CLI commands."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.config import AppConfig
from app.dependencies import build_service, _load_or_create_vector_index
from providers.embedding.base import EmbeddingProvider
from retrieval.composite import CompositeRetrievalProvider
from storage.vector_index import VectorIndexConfig

try:
    import usearch  # noqa: F401
    HAS_USEARCH = True
except ImportError:
    HAS_USEARCH = False

requires_usearch = pytest.mark.skipif(not HAS_USEARCH, reason="usearch not installed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class StubEmbeddingProvider(EmbeddingProvider):
    """Minimal embedding provider for startup tests."""

    def __init__(self, dims: int = 4, model: str = "test-model") -> None:
        self._dims = dims
        self._model = model

    def embed(self, texts: list[str], **kwargs) -> list[list[float]]:
        return [[0.1] * self._dims for _ in texts]

    def dimensions(self) -> int:
        return self._dims

    def model_name(self) -> str:
        return self._model


def _minimal_config(**overrides) -> AppConfig:
    """Build a minimal AppConfig with vector settings for testing."""
    defaults = dict(
        storage_backend="sqlite",
        sqlite_url="sqlite:///:memory:",
        default_use_case="demo_agent_memory",
    )
    defaults.update(overrides)
    return AppConfig(**defaults)


# ---------------------------------------------------------------------------
# Config TOML parsing
# ---------------------------------------------------------------------------

class TestVectorIndexConfig:

    def test_default_config_vector_enabled(self) -> None:
        config = AppConfig()
        assert config.vector_index.enabled is True
        assert config.vector_index.index_path == "./pallium_vector.index"
        assert config.vector_index.embedding_provider == "onnx"
        assert config.vector_index.min_similarity is None  # resolved at runtime from model

    def test_vector_index_config_from_toml(self, monkeypatch, tmp_path: Path) -> None:
        config_file = tmp_path / "pallium.local.toml"
        config_file.write_text(
            """
            default_use_case = "demo_agent_memory"

            [vector_index]
            enabled = true
            index_path = "./custom_vector.index"
            embedding_provider = "local"
            min_similarity = 0.4
            """.strip(),
            encoding="utf-8",
        )
        monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))
        config = AppConfig.from_env()

        assert config.vector_index.enabled is True
        assert config.vector_index.index_path == "./custom_vector.index"
        assert config.vector_index.embedding_provider == "local"
        assert config.vector_index.min_similarity == 0.4

    def test_vector_index_config_env_overrides(self, monkeypatch, tmp_path: Path) -> None:
        config_file = tmp_path / "pallium.local.toml"
        config_file.write_text(
            """
            default_use_case = "demo_agent_memory"

            [vector_index]
            enabled = false
            min_similarity = 0.3
            """.strip(),
            encoding="utf-8",
        )
        monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))
        monkeypatch.setenv("PALLIUM_VECTOR_INDEX_ENABLED", "true")
        monkeypatch.setenv("PALLIUM_VECTOR_INDEX_PATH", "/tmp/env_override.index")
        monkeypatch.setenv("PALLIUM_VECTOR_INDEX_EMBEDDING_PROVIDER", "remote")
        monkeypatch.setenv("PALLIUM_VECTOR_INDEX_MIN_SIMILARITY", "0.5")

        config = AppConfig.from_env()

        assert config.vector_index.enabled is True
        assert config.vector_index.index_path == "/tmp/env_override.index"
        assert config.vector_index.embedding_provider == "remote"
        assert config.vector_index.min_similarity == 0.5

    def test_vector_index_config_absent_uses_defaults(self, monkeypatch, tmp_path: Path) -> None:
        config_file = tmp_path / "pallium.local.toml"
        config_file.write_text(
            'default_use_case = "demo_agent_memory"',
            encoding="utf-8",
        )
        monkeypatch.setenv("PALLIUM_CONFIG_FILE", str(config_file))
        config = AppConfig.from_env()

        assert config.vector_index.enabled is True
        assert config.vector_index.embedding_provider == "onnx"


# ---------------------------------------------------------------------------
# build_service — vector disabled (backward compat)
# ---------------------------------------------------------------------------

class TestBuildServiceVectorDisabled:

    def test_vector_disabled_explicit_false_lexical_only(self) -> None:
        """When vector is explicitly disabled, build_service produces lexical-only service."""
        config = _minimal_config(
            vector_index=VectorIndexConfig(enabled=False),
        )
        service = build_service(config)

        assert not isinstance(service._retrieval, CompositeRetrievalProvider)
        assert service._vector_index is None
        assert service._embedding_provider is None

    def test_vector_disabled_explicit_false_with_provider(self) -> None:
        config = _minimal_config(
            vector_index=VectorIndexConfig(enabled=False, embedding_provider="local"),
        )
        service = build_service(config)

        assert not isinstance(service._retrieval, CompositeRetrievalProvider)
        assert service._vector_index is None
        assert service._embedding_provider is None


# ---------------------------------------------------------------------------
# build_service — vector enabled (mocked dependencies)
# ---------------------------------------------------------------------------

class TestBuildServiceVectorEnabled:

    def test_vector_enabled_all_three_wired(self, tmp_path: Path, monkeypatch) -> None:
        """When vector enabled with valid embedding provider, all three are wired."""
        from app.config import EmbeddingProviderConfig
        from storage.vector_index import VectorIndex

        index_path = tmp_path / "test.index"
        config = _minimal_config(
            vector_index=VectorIndexConfig(
                enabled=True,
                index_path=str(index_path),
                embedding_provider="local",
                min_similarity=0.25,
            ),
            embedding_providers={
                "local": EmbeddingProviderConfig(
                    name="local", kind="fastembed", model="test-model",
                ),
            },
        )

        stub_provider = StubEmbeddingProvider()
        mock_index = MagicMock(spec=VectorIndex)
        mock_index.entry_count.return_value = 0
        mock_index.model_name = "test-model"

        monkeypatch.setattr(
            "app.dependencies.build_embedding_provider",
            lambda config, *, provider_name: stub_provider,
        )
        monkeypatch.setattr(
            "app.dependencies._load_or_create_vector_index",
            lambda config, provider: mock_index,
        )

        service = build_service(config)

        assert service._embedding_provider is stub_provider
        assert service._vector_index is mock_index
        assert isinstance(service._retrieval, CompositeRetrievalProvider)

    def test_vector_enabled_no_embedding_provider_name_disables(self, caplog) -> None:
        """Vector enabled but no embedding_provider configured => vector disabled with error log."""
        config = _minimal_config(
            vector_index=VectorIndexConfig(enabled=True, embedding_provider=""),
        )

        with caplog.at_level(logging.ERROR):
            service = build_service(config)

        assert not isinstance(service._retrieval, CompositeRetrievalProvider)
        assert service._vector_index is None
        assert service._embedding_provider is None
        assert "no embedding_provider configured" in caplog.text.lower()


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------

class TestGracefulDegradation:

    def test_embedding_provider_import_error_disables_vector(self, monkeypatch, caplog) -> None:
        """If fastembed is not installed, vector degrades gracefully."""
        from app.config import EmbeddingProviderConfig

        config = _minimal_config(
            vector_index=VectorIndexConfig(enabled=True, embedding_provider="local"),
            embedding_providers={
                "local": EmbeddingProviderConfig(
                    name="local", kind="fastembed", model="test-model",
                ),
            },
        )

        def raise_import_error(config, *, provider_name):
            raise ImportError("No module named 'fastembed'")

        monkeypatch.setattr("app.dependencies.build_embedding_provider", raise_import_error)

        with caplog.at_level(logging.ERROR):
            service = build_service(config)

        assert not isinstance(service._retrieval, CompositeRetrievalProvider)
        assert service._vector_index is None
        assert service._embedding_provider is None
        assert "vector disabled" in caplog.text.lower() or "vector embedding provider failed" in caplog.text.lower()

    def test_usearch_not_installed_disables_vector(self, tmp_path: Path, monkeypatch, caplog) -> None:
        """If usearch is not installed, _load_or_create_vector_index returns None."""
        index_path = tmp_path / "test.index"
        vector_config = VectorIndexConfig(
            enabled=True,
            index_path=str(index_path),
            embedding_provider="local",
        )
        stub_provider = StubEmbeddingProvider()

        # Simulate usearch ImportError during create_empty
        from storage import vector_index as vi_module
        original_create_empty = vi_module.VectorIndex.create_empty

        def mock_create_empty(*args, **kwargs):
            raise ImportError("No module named 'usearch'")

        monkeypatch.setattr(vi_module.VectorIndex, "create_empty", staticmethod(mock_create_empty))

        with caplog.at_level(logging.ERROR):
            result = _load_or_create_vector_index(vector_config, stub_provider)

        assert result is None
        assert "usearch" in caplog.text.lower()


# ---------------------------------------------------------------------------
# Model mismatch detection
# ---------------------------------------------------------------------------

class TestModelMismatch:

    def test_model_mismatch_disables_vector(self, tmp_path: Path, monkeypatch, caplog) -> None:
        """If the index was built with a different model, auto-rebuild is attempted and on failure vector is disabled."""
        from app.config import EmbeddingProviderConfig
        from storage.vector_index import VectorIndex

        index_path = tmp_path / "test.index"

        # Create a mock VectorIndex with a different model name and one entry
        mock_index = MagicMock(spec=VectorIndex)
        mock_index.entry_count.return_value = 1
        mock_index.model_name = "old-model"
        mock_index.embedding_schema_version = 1

        stub_provider = StubEmbeddingProvider(model="new-model")

        # Mock storage — rebuild will call list_index_entries_by_type but
        # then fail on get_memory_object/get_source_item (simulates rebuild failure)
        mock_storage = MagicMock()
        mock_storage.list_index_entries_by_type.side_effect = RuntimeError("storage unavailable")

        config = _minimal_config(
            vector_index=VectorIndexConfig(
                enabled=True,
                index_path=str(index_path),
                embedding_provider="local",
                min_similarity=0.3,
            ),
            embedding_providers={
                "local": EmbeddingProviderConfig(
                    name="local", kind="fastembed", model="new-model",
                ),
            },
        )

        monkeypatch.setattr(
            "app.dependencies.build_embedding_provider",
            lambda config, *, provider_name: stub_provider,
        )
        monkeypatch.setattr(
            "app.dependencies._load_or_create_vector_index",
            lambda config, provider: mock_index,
        )
        monkeypatch.setattr(
            "app.dependencies.build_storage_provider",
            lambda config: mock_storage,
        )

        with caplog.at_level(logging.ERROR):
            service = build_service(config)

        assert not isinstance(service._retrieval, CompositeRetrievalProvider)
        assert service._vector_index is None
        assert service._embedding_provider is None
        assert "auto-rebuild failed" in caplog.text.lower()

    def test_model_match_with_entries_keeps_vector(self, tmp_path: Path, monkeypatch) -> None:
        """If the model matches and entry counts agree, vector is kept."""
        from app.config import EmbeddingProviderConfig
        from semantic.agent_conversation_memory_embedding import EMBEDDING_SCHEMA_VERSION
        from storage.vector_index import VectorIndex

        index_path = tmp_path / "test.index"

        mock_index = MagicMock(spec=VectorIndex)
        mock_index.entry_count.return_value = 5
        mock_index.model_name = "test-model"
        mock_index.embedding_schema_version = EMBEDDING_SCHEMA_VERSION

        stub_provider = StubEmbeddingProvider(model="test-model")

        mock_storage = MagicMock()
        mock_storage.count_index_entries_by_type.return_value = 5

        config = _minimal_config(
            vector_index=VectorIndexConfig(
                enabled=True,
                index_path=str(index_path),
                embedding_provider="local",
                min_similarity=0.3,
            ),
            embedding_providers={
                "local": EmbeddingProviderConfig(
                    name="local", kind="fastembed", model="test-model",
                ),
            },
        )

        monkeypatch.setattr(
            "app.dependencies.build_embedding_provider",
            lambda config, *, provider_name: stub_provider,
        )
        monkeypatch.setattr(
            "app.dependencies._load_or_create_vector_index",
            lambda config, provider: mock_index,
        )
        monkeypatch.setattr(
            "app.dependencies.build_storage_provider",
            lambda config: mock_storage,
        )

        service = build_service(config)

        assert isinstance(service._retrieval, CompositeRetrievalProvider)
        assert service._vector_index is mock_index
        assert service._embedding_provider is stub_provider

    def test_empty_index_skips_model_check(self, tmp_path: Path, monkeypatch) -> None:
        """If the index is empty, model check is skipped (fresh index created with current model)."""
        from app.config import EmbeddingProviderConfig
        from storage.vector_index import VectorIndex

        index_path = tmp_path / "test.index"

        mock_index = MagicMock(spec=VectorIndex)
        mock_index.entry_count.return_value = 0
        mock_index.model_name = "whatever-model"

        stub_provider = StubEmbeddingProvider(model="different-model")

        config = _minimal_config(
            vector_index=VectorIndexConfig(
                enabled=True,
                index_path=str(index_path),
                embedding_provider="local",
            ),
            embedding_providers={
                "local": EmbeddingProviderConfig(
                    name="local", kind="fastembed", model="different-model",
                ),
            },
        )

        monkeypatch.setattr(
            "app.dependencies.build_embedding_provider",
            lambda config, *, provider_name: stub_provider,
        )
        monkeypatch.setattr(
            "app.dependencies._load_or_create_vector_index",
            lambda config, provider: mock_index,
        )

        service = build_service(config)

        # Model mismatch ignored because index is empty
        assert isinstance(service._retrieval, CompositeRetrievalProvider)
        assert service._vector_index is mock_index


# ---------------------------------------------------------------------------
# Count mismatch warning
# ---------------------------------------------------------------------------

class TestCountMismatch:

    def test_count_mismatch_logs_warning_and_keeps_vector_enabled(self, tmp_path: Path, monkeypatch, caplog) -> None:
        """When SQLite and index entry counts differ, a warning is logged but vector stays enabled."""
        from app.config import EmbeddingProviderConfig
        from semantic.agent_conversation_memory_embedding import EMBEDDING_SCHEMA_VERSION
        from storage.vector_index import VectorIndex

        index_path = tmp_path / "test.index"

        mock_index = MagicMock(spec=VectorIndex)
        mock_index.entry_count.return_value = 3
        mock_index.model_name = "test-model"
        mock_index.embedding_schema_version = EMBEDDING_SCHEMA_VERSION

        stub_provider = StubEmbeddingProvider(model="test-model")

        # Mock storage to return a different count
        mock_storage = MagicMock()
        mock_storage.count_index_entries_by_type.return_value = 5

        config = _minimal_config(
            vector_index=VectorIndexConfig(
                enabled=True,
                index_path=str(index_path),
                embedding_provider="local",
            ),
            embedding_providers={
                "local": EmbeddingProviderConfig(
                    name="local", kind="fastembed", model="test-model",
                ),
            },
        )

        monkeypatch.setattr(
            "app.dependencies.build_embedding_provider",
            lambda config, *, provider_name: stub_provider,
        )
        monkeypatch.setattr(
            "app.dependencies._load_or_create_vector_index",
            lambda config, provider: mock_index,
        )
        monkeypatch.setattr(
            "app.dependencies.build_storage_provider",
            lambda config: mock_storage,
        )

        with caplog.at_level(logging.WARNING):
            service = build_service(config)

        # Vector stays enabled despite mismatch
        assert isinstance(service._retrieval, CompositeRetrievalProvider)
        assert service._vector_index is mock_index
        assert service._embedding_provider is stub_provider
        assert "mismatch" in caplog.text.lower()


# ---------------------------------------------------------------------------
# _load_or_create_vector_index
# ---------------------------------------------------------------------------

class TestLoadOrCreateVectorIndex:

    def test_usearch_import_error_returns_none(self, tmp_path: Path, caplog) -> None:
        """When usearch is not installed, _load_or_create_vector_index returns None."""
        if HAS_USEARCH:
            pytest.skip("This test requires usearch to NOT be installed")

        index_path = tmp_path / "no_usearch.index"
        config = VectorIndexConfig(index_path=str(index_path))
        provider = StubEmbeddingProvider()

        with caplog.at_level(logging.ERROR):
            result = _load_or_create_vector_index(config, provider)

        assert result is None
        assert "usearch" in caplog.text.lower()

    @requires_usearch
    def test_creates_empty_when_no_file(self, tmp_path: Path) -> None:
        index_path = tmp_path / "new.index"
        config = VectorIndexConfig(index_path=str(index_path))
        provider = StubEmbeddingProvider(dims=4, model="test-model")

        index = _load_or_create_vector_index(config, provider)

        assert index is not None
        assert index.entry_count() == 0
        assert index.model_name == "test-model"
        assert index.dimensions == 4

    @requires_usearch
    def test_loads_existing_index(self, tmp_path: Path) -> None:
        from storage.vector_index import VectorIndex

        index_path = tmp_path / "existing.index"
        original = VectorIndex.create_empty(index_path, dimensions=4, model_name="saved-model")
        original.add("entry-1", [0.1, 0.2, 0.3, 0.4])
        original.save()

        config = VectorIndexConfig(index_path=str(index_path))
        provider = StubEmbeddingProvider(dims=4, model="saved-model")

        loaded = _load_or_create_vector_index(config, provider)

        assert loaded is not None
        assert loaded.entry_count() == 1
        assert loaded.model_name == "saved-model"

    @requires_usearch
    def test_returns_none_on_general_error(self, tmp_path: Path, monkeypatch, caplog) -> None:
        """If loading fails for any reason, returns None gracefully."""
        index_path = tmp_path / "bad.index"
        # Create just the meta file with bad data to trigger an error on load
        meta_path = Path(f"{index_path}.meta.json")
        meta_path.write_text("not valid json", encoding="utf-8")
        # Also create the index file so the exists() check passes
        index_path.write_bytes(b"")

        config = VectorIndexConfig(index_path=str(index_path))
        provider = StubEmbeddingProvider()

        with caplog.at_level(logging.ERROR):
            result = _load_or_create_vector_index(config, provider)

        assert result is None
        assert "failed to load vector index" in caplog.text.lower()


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

class TestCLICommands:

    def test_rebuild_vector_index_mode_accepted_by_parser(self) -> None:
        from app.run import build_parser
        parsed = build_parser().parse_args(["rebuild-vector-index"])
        assert parsed.mode == "rebuild-vector-index"

    def test_download_embedding_model_mode_accepted_by_parser(self) -> None:
        from app.run import build_parser
        parsed = build_parser().parse_args(["download-embedding-model"])
        assert parsed.mode == "download-embedding-model"

    def test_rebuild_vector_index_disabled_returns_error(self, monkeypatch) -> None:
        from app import run as app_run
        from app.config import AppConfig

        monkeypatch.setattr(
            AppConfig,
            "from_env",
            staticmethod(lambda: _minimal_config(
                vector_index=VectorIndexConfig(enabled=False),
            )),
        )

        exit_code = app_run.run(["rebuild-vector-index"])
        assert exit_code == 1

    def test_download_embedding_model_no_provider_returns_error(self, monkeypatch) -> None:
        from app import run as app_run
        from app.config import AppConfig

        monkeypatch.setattr(
            AppConfig,
            "from_env",
            staticmethod(lambda: _minimal_config(
                vector_index=VectorIndexConfig(enabled=True, embedding_provider=""),
            )),
        )

        exit_code = app_run.run(["download-embedding-model"])
        assert exit_code == 1

    def test_download_embedding_model_success(self, monkeypatch) -> None:
        from app import run as app_run
        from app.config import AppConfig, EmbeddingProviderConfig

        stub_provider = StubEmbeddingProvider()
        config = _minimal_config(
            vector_index=VectorIndexConfig(enabled=True, embedding_provider="local"),
            embedding_providers={
                "local": EmbeddingProviderConfig(
                    name="local", kind="fastembed", model="test-model",
                ),
            },
        )

        monkeypatch.setattr(
            AppConfig,
            "from_env",
            staticmethod(lambda: config),
        )
        monkeypatch.setattr(
            "app.dependencies.build_embedding_provider",
            lambda config, *, provider_name: stub_provider,
        )

        exit_code = app_run.run(["download-embedding-model"])
        assert exit_code == 0

    @requires_usearch
    def test_rebuild_vector_index_success(self, monkeypatch, tmp_path: Path) -> None:
        from app import run as app_run
        from app.config import AppConfig, EmbeddingProviderConfig
        from core.models import IndexEntry, MemoryObject, SourceItem

        index_path = tmp_path / "rebuild.index"
        stub_provider = StubEmbeddingProvider(dims=4)
        config = _minimal_config(
            vector_index=VectorIndexConfig(
                enabled=True,
                index_path=str(index_path),
                embedding_provider="local",
            ),
            embedding_providers={
                "local": EmbeddingProviderConfig(
                    name="local", kind="fastembed", model="test-model",
                ),
            },
        )

        # Create source objects that the rebuild will look up
        memory_obj = MemoryObject(
            type="decision",
            schema_id="test",
            schema_version="1",
            payload={"decision": "Use SQLite for local storage", "rationale": "Simpler deployment model"},
            id="mo-1",
        )
        source_item = SourceItem(
            source_type="test",
            source_id="si-source-1",
            content_type="text/plain",
            content="What storage engine should we use for the local-first architecture?",
            artifact_kind="message",
            id="si-1",
        )

        mock_storage = MagicMock()
        mock_storage.list_index_entries_by_type.return_value = [
            IndexEntry(
                id="e1",
                target_kind="memory_object",
                target_id="mo-1",
                index_type="vector",
                text_view="some text",
            ),
            IndexEntry(
                id="e2",
                target_kind="source_item",
                target_id="si-1",
                index_type="vector",
                text_view="other text",
            ),
        ]
        mock_storage.get_memory_object.return_value = memory_obj
        mock_storage.get_source_item.return_value = source_item
        mock_storage.update_index_entry_text_view = MagicMock()

        monkeypatch.setattr(
            AppConfig,
            "from_env",
            staticmethod(lambda: config),
        )
        monkeypatch.setattr(
            "app.dependencies.build_embedding_provider",
            lambda config, *, provider_name: stub_provider,
        )
        monkeypatch.setattr(
            "app.dependencies.build_storage_provider",
            lambda config: mock_storage,
        )

        exit_code = app_run.run(["rebuild-vector-index"])
        assert exit_code == 0

        # Verify the index was created with the right entries
        from storage.vector_index import VectorIndex
        loaded = VectorIndex.load(index_path)
        assert loaded.entry_count() == 2


# ---------------------------------------------------------------------------
# VectorIndex property accessors
# ---------------------------------------------------------------------------

class TestVectorIndexProperties:

    @requires_usearch
    def test_model_name_property(self, tmp_path: Path) -> None:
        from storage.vector_index import VectorIndex
        index_path = tmp_path / "prop.index"
        vi = VectorIndex.create_empty(index_path, dimensions=4, model_name="my-model")
        assert vi.model_name == "my-model"

    @requires_usearch
    def test_dimensions_property(self, tmp_path: Path) -> None:
        from storage.vector_index import VectorIndex
        index_path = tmp_path / "prop.index"
        vi = VectorIndex.create_empty(index_path, dimensions=128, model_name="m")
        assert vi.dimensions == 128
