"""Workspace config persistence adapter backed by YAML files."""

from __future__ import annotations

from pathlib import Path

from reuleauxcoder.domain.config.models import ApprovalConfig
from reuleauxcoder.infrastructure.yaml.loader import load_yaml_config, save_yaml_config
from reuleauxcoder.services.config.loader import ConfigLoader


class WorkspaceConfigStore:
    """File-backed store for writable workspace configuration."""

    def __init__(self, path: Path | None = None):
        self._path = path or ConfigLoader.WORKSPACE_CONFIG_PATH

    @property
    def path(self) -> Path:
        """Return the writable workspace config path."""
        return self._path

    def save_approval_config(self, approval: ApprovalConfig) -> Path:
        """Persist approval config into workspace ``config.yaml``."""
        data = self._load()

        data["approval"] = {
            "default_mode": approval.default_mode,
            "reviewer": approval.reviewer,
            "auto_review_model_profile": approval.auto_review_model_profile,
            "auto_review_policy": approval.auto_review_policy,
            "auto_review_timeout_seconds": approval.auto_review_timeout_seconds,
            "rules": [rule.to_dict(omit_none=True) for rule in approval.rules],
        }
        save_yaml_config(self._path, data)
        return self._path

    def save_active_model_profile(self, profile_name: str) -> Path:
        """Persist active main model profile into workspace ``config.yaml``."""
        data = self._load()

        models_data = data.setdefault("models", {})
        models_data["active"] = profile_name
        models_data["active_main"] = profile_name
        save_yaml_config(self._path, data)
        return self._path

    def save_active_sub_model_profile(self, profile_name: str) -> Path:
        """Persist active sub-agent model profile into workspace ``config.yaml``."""
        data = self._load()

        models_data = data.setdefault("models", {})
        models_data["active_sub"] = profile_name
        save_yaml_config(self._path, data)
        return self._path

    def save_mcp_server_enabled(self, server_name: str, enabled: bool) -> Path:
        """Persist only the workspace-local enabled override for an MCP server."""
        data = self._load()

        mcp_data = data.setdefault("mcp", {})
        servers = mcp_data.setdefault("servers", {})
        server_data = servers.setdefault(server_name, {})
        if not isinstance(server_data, dict):
            server_data = {}
            servers[server_name] = server_data
        server_data["enabled"] = enabled
        save_yaml_config(self._path, data)
        return self._path

    def _load(self) -> dict:
        try:
            return load_yaml_config(self._path)
        except FileNotFoundError:
            return {}
