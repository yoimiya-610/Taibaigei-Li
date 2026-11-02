from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
import re
import sys
from types import ModuleType
from typing import Any


FEATURE_KEY_PATTERN = re.compile(r"[a-z][a-z0-9_]*")
PLUGIN_MODULE_PREFIXES = ("mybot.plugins.", "mybot.plugins_disabled.")


class FeatureScope(StrEnum):
    GROUP = "group"
    SYSTEM = "system"


class PrivacyLevel(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    PERSONAL = "personal"
    SENSITIVE = "sensitive"


class BackupPolicy(StrEnum):
    NONE = "none"
    STANDARD = "standard"
    OPTIONAL = "optional"


@dataclass(frozen=True)
class PluginMetadata:
    module_name: str
    feature_key: str
    name: str
    default_enabled: bool
    scope: FeatureScope
    permission_level: int | None
    data_files: tuple[str, ...]
    privacy_level: PrivacyLevel
    backup_policy: BackupPolicy
    protected: bool = False
    legacy_feature_keys: tuple[str, ...] = ()


class PluginMetadataError(ValueError):
    pass


_METADATA_BY_MODULE: dict[str, PluginMetadata] = {}
_METADATA_BY_FEATURE: dict[str, PluginMetadata] = {}
_FEATURE_ALIASES: dict[str, str] = {}


def _normalize_data_files(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise PluginMetadataError("data_file_must_be_string")
        path = PurePosixPath(value.strip().replace("\\", "/"))
        if (
            not value.strip()
            or path.is_absolute()
            or ".." in path.parts
            or not path.parts
            or path.parts[0] != "data"
        ):
            raise PluginMetadataError(f"invalid_data_file: {value}")
        rendered = path.as_posix()
        if rendered not in normalized:
            normalized.append(rendered)
    return tuple(normalized)


def _normalize_feature_keys(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        key = value.strip() if isinstance(value, str) else ""
        if not FEATURE_KEY_PATTERN.fullmatch(key):
            raise PluginMetadataError(f"invalid_legacy_feature_key: {value}")
        if key not in normalized:
            normalized.append(key)
    return tuple(normalized)


def declare_plugin(
    *,
    module_name: str,
    feature_key: str,
    name: str,
    default_enabled: bool,
    scope: FeatureScope | str,
    permission_level: int | None,
    data_files: tuple[str, ...] = (),
    privacy_level: PrivacyLevel | str = PrivacyLevel.PUBLIC,
    backup_policy: BackupPolicy | str = BackupPolicy.NONE,
    protected: bool = False,
    legacy_feature_keys: tuple[str, ...] = (),
) -> PluginMetadata:
    if not any(module_name.startswith(prefix) for prefix in PLUGIN_MODULE_PREFIXES):
        raise PluginMetadataError(f"invalid_plugin_module: {module_name}")
    if not FEATURE_KEY_PATTERN.fullmatch(feature_key):
        raise PluginMetadataError(f"invalid_feature_key: {feature_key}")
    normalized_name = name.strip() if isinstance(name, str) else ""
    if not normalized_name:
        raise PluginMetadataError("feature_name_required")
    if not isinstance(default_enabled, bool):
        raise PluginMetadataError("default_enabled_must_be_bool")

    normalized_scope = FeatureScope(scope)
    if normalized_scope is FeatureScope.GROUP:
        if not isinstance(permission_level, int) or isinstance(permission_level, bool):
            raise PluginMetadataError("group_feature_permission_required")
        if not 1 <= permission_level <= 5:
            raise PluginMetadataError("invalid_group_feature_permission")
    elif permission_level is not None:
        raise PluginMetadataError("system_feature_permission_must_be_none")

    normalized_files = _normalize_data_files(tuple(data_files))
    normalized_backup = BackupPolicy(backup_policy)
    if normalized_files and normalized_backup is BackupPolicy.NONE:
        raise PluginMetadataError("data_files_require_backup_policy")
    if not normalized_files and normalized_backup is not BackupPolicy.NONE:
        raise PluginMetadataError("backup_policy_requires_data_files")

    aliases = _normalize_feature_keys(tuple(legacy_feature_keys))
    if feature_key in aliases:
        raise PluginMetadataError("feature_key_cannot_alias_itself")

    metadata = PluginMetadata(
        module_name=module_name,
        feature_key=feature_key,
        name=normalized_name,
        default_enabled=default_enabled,
        scope=normalized_scope,
        permission_level=permission_level,
        data_files=normalized_files,
        privacy_level=PrivacyLevel(privacy_level),
        backup_policy=normalized_backup,
        protected=bool(protected),
        legacy_feature_keys=aliases,
    )

    existing_module = _METADATA_BY_MODULE.get(module_name)
    existing_feature = _METADATA_BY_FEATURE.get(feature_key)
    if existing_module is not None and existing_module != metadata:
        raise PluginMetadataError(f"duplicate_plugin_module: {module_name}")
    if existing_feature is not None and existing_feature != metadata:
        raise PluginMetadataError(f"duplicate_feature_key: {feature_key}")
    for alias in aliases:
        owner = _FEATURE_ALIASES.get(alias)
        if owner is not None and owner != feature_key:
            raise PluginMetadataError(f"duplicate_feature_alias: {alias}")
        if alias in _METADATA_BY_FEATURE and alias != feature_key:
            raise PluginMetadataError(f"feature_alias_conflicts_with_key: {alias}")

    _METADATA_BY_MODULE[module_name] = metadata
    _METADATA_BY_FEATURE[feature_key] = metadata
    for alias in aliases:
        _FEATURE_ALIASES[alias] = feature_key
    return metadata


def canonical_feature_key(feature_key: str) -> str:
    return _FEATURE_ALIASES.get(feature_key, feature_key)


def get_plugin_metadata_for_module(module_name: str) -> PluginMetadata | None:
    normalized = module_name.removeprefix("mybot.")
    return _METADATA_BY_MODULE.get(f"mybot.{normalized}")


def get_plugin_metadata_for_feature(feature_key: str) -> PluginMetadata | None:
    return _METADATA_BY_FEATURE.get(canonical_feature_key(feature_key))


def iter_plugin_metadata() -> tuple[PluginMetadata, ...]:
    return tuple(
        sorted(
            _METADATA_BY_FEATURE.values(),
            key=lambda metadata: (metadata.name, metadata.feature_key),
        )
    )


def iter_loaded_plugin_modules() -> Iterator[tuple[str, ModuleType]]:
    for module_name, module in list(sys.modules.items()):
        if not isinstance(module, ModuleType):
            continue
        prefix = next(
            (
                candidate
                for candidate in PLUGIN_MODULE_PREFIXES
                if module_name.startswith(candidate)
            ),
            None,
        )
        if prefix is None:
            continue
        relative_parts = module_name[len(prefix) :].split(".")
        if any(part.startswith("_") for part in relative_parts):
            continue
        yield module_name, module


def validate_loaded_plugin_metadata() -> None:
    errors: list[str] = []
    seen_features: dict[str, str] = {}
    for module_name, module in iter_loaded_plugin_modules():
        metadata = getattr(module, "PLUGIN_META", None)
        if not isinstance(metadata, PluginMetadata):
            errors.append(f"{module_name}: missing PLUGIN_META")
            continue
        if metadata.module_name != module_name:
            errors.append(
                f"{module_name}: metadata module is {metadata.module_name}"
            )
        registered = get_plugin_metadata_for_module(module_name)
        if registered != metadata:
            errors.append(f"{module_name}: metadata is not registered")
        owner = seen_features.setdefault(metadata.feature_key, module_name)
        if owner != module_name:
            errors.append(
                f"{module_name}: feature {metadata.feature_key} already belongs to {owner}"
            )
    if errors:
        raise PluginMetadataError("; ".join(errors))


class MetadataFieldMapping(Mapping[str, Any]):
    def __init__(self, field_name: str):
        self._field_name = field_name

    def __getitem__(self, key: str) -> Any:
        metadata = get_plugin_metadata_for_feature(key)
        if metadata is None:
            raise KeyError(key)
        return getattr(metadata, self._field_name)

    def __iter__(self) -> Iterator[str]:
        return iter(_METADATA_BY_FEATURE)

    def __len__(self) -> int:
        return len(_METADATA_BY_FEATURE)


FEATURE_NAMES: Mapping[str, str] = MetadataFieldMapping("name")
DEFAULT_FEATURE_ENABLED: Mapping[str, bool] = MetadataFieldMapping("default_enabled")
