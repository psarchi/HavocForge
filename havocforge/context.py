"""Execution context carrying configuration and runtime state.

Provides deterministic RNG, locale-bound Faker instance, and metadata
construction for generated values.
"""

from __future__ import annotations

import base64
import hashlib
import pickle
import random
import time
from random import Random
from typing import Any

import faker

from .errors import InvalidLocaleError, InvalidRNGError


def _now_iso_utc_ms() -> str:
    """Return the current UTC timestamp in ISO-8601 with millisecond precision.

    Returns:
        str: Timestamp like ``YYYY-MM-DDTHH:MM:SS.mmmZ``.
    """
    now = time.time()
    seconds = int(now)
    millis = int((now - seconds) * 1000)
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(seconds)) + f".{millis:03d}Z"


def _derive_seed64(*parts: object) -> int:
    """Derive a deterministic 64-bit seed from ``parts``.

    Args:
        *parts (object): Values contributing to the seed derivation.

    Returns:
        int: Unsigned 64-bit integer derived from SHA1 digest prefix.
    """
    digest = hashlib.sha1("|".join(map(str, parts)).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


class GenContext:
    """Generation context providing RNG, Faker, and run metadata.

    Args:
        seed (int | None): Deterministic seed. If ``None`` and ``rng`` is not provided,
            a random 64-bit seed is generated.
        rng (Random | None): Preconstructed RNG. If provided, takes precedence over ``seed``.
        locale (str | None): Locale for the Faker provider (e.g., ``"en_US"``).

    Attributes:
        temporal_tracker: Reference to TemporalTracker singleton for timeline state management.
    """

    __slots__ = (
        "rng",
        "seed",
        "rng_state",
        "rng_state_b64",
        "locale",
        "_faker",
        "sequence",
        "request_id",
        "trace_id",
        "scenario",
        "config_hash",
        "generator_version",
        "emit_meta",
        "schema_name",
        "schema_version",
        "temporal_tracker",
        "_depends_on",
        "_correlation_client",
        "_pool_cache",
    )

    def __init__(
        self,
        seed: int | None = None,
        rng: Random | None = None,
        locale: str | None = None,
    ) -> None:
        """Initialize RNG, Faker locale, and basic metadata fields.

        Args:
            seed (int | None): Deterministic seed. Ignored when ``rng`` is provided.
            rng (Random | None): Deterministic random generator instance.
            locale (str | None): Locale string for Faker.
        """
        if rng is not None:
            if not isinstance(rng, random.Random):
                raise InvalidRNGError("rng must be an instance of random.Random")
            self.rng = rng
            self.seed = seed
            try:
                state = self.rng.getstate()
                self.rng_state = state
                self.rng_state_b64 = base64.b64encode(pickle.dumps(state)).decode()
            except Exception:  # noqa: BLE001 (preserve behavior)
                # TODO(errors): Investigate environments where RNG state is not picklable.
                self.rng_state = None
                self.rng_state_b64 = None
        else:
            if seed is None:
                seed = random.getrandbits(64)
            self.seed = seed
            self.rng = random.Random(seed)
            state = self.rng.getstate()
            self.rng_state = state
            self.rng_state_b64 = base64.b64encode(pickle.dumps(state)).decode()

        self.locale = locale
        self._faker: faker.Faker | None = None
        self.sequence = 0
        self.request_id: str | None = None
        self.trace_id: str | None = None
        self.scenario: str | None = None
        self.config_hash: str | None = None
        self.generator_version = "0.1.0"
        self.emit_meta = True
        self.schema_name: str | None = None
        self.schema_version = "unknown"
        self.temporal_tracker: Any = None
        self._depends_on: Any = None
        self._correlation_client: Any = None
        self._pool_cache: dict[str, dict] = {}

    @property
    def faker(self) -> faker.Faker:
        """Lazily construct and return a locale-aware Faker instance.

        Returns:
            faker.Faker: Seeded Faker instance.

        Raises:
            InvalidLocaleError: If the requested locale is invalid.
        """
        if self._faker is None:
            try:
                fk = faker.Faker(self.locale) if self.locale else faker.Faker()
            except Exception as exc:  # noqa: BLE001 (preserve behavior)
                raise InvalidLocaleError(str(exc)) from exc

            # Derive a stable seed for Faker using either explicit seed or RNG fingerprint.
            if self.seed is not None:
                fk_seed = _derive_seed64(
                    self.seed, "faker", self.schema_name or "", "v1"
                )
            else:
                fk_seed = _derive_seed64(
                    self.rng_state_b64 or "", "faker", self.schema_name or "", "v1"
                )
            fk.seed_instance(fk_seed)
            self._faker = fk
        return self._faker

    def build_meta(self) -> dict[str, Any]:
        """Build response metadata dictionary.

        Returns:
            dict[str, Any]: Metadata with seed, schema, timestamp, and placeholders
                for count and chaos_applied (populated by server layer).
        """
        return {
            "seed": self.seed,
            "schema": self.schema_name,
            "generated_at": _now_iso_utc_ms(),
            "count": None,
            "chaos_applied": [],
        }
