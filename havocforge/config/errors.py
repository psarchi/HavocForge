from havocforge.errors import HavocforgeError


class ConfigError(HavocforgeError):
    """Base error for config package."""


class ConfigDefaultsError(ConfigError):
    """Problems reading or validating default configuration files."""


class ConfigDefaultsFormatError(ConfigDefaultsError):
    """Default config file is missing or has an invalid structure."""


class DuplicateConfigRootError(ConfigDefaultsError):
    """Duplicate root definitions detected across default files."""


class ConfigBuildError(ConfigError):
    """Raised when building models from config fails."""


class ConfigValidationError(ConfigError):
    """Raised when configuration values fail validation."""


class ConfigPathError(ConfigError):
    """Raised for missing/invalid configuration paths."""


class ConfigSchemaError(ConfigError):
    """Raised for schema-related configuration issues."""


class MetaKindError(ConfigSchemaError):
    """Meta tree has an unexpected kind (e.g., non-group root)."""


class ModuleBuildError(ConfigError):
    """Raised to constructor related errors."""
