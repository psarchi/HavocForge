from __future__ import annotations

import re
from string import ascii_lowercase, ascii_uppercase, digits
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, List, Optional

try:
    import exrex
except Exception as _e:  # noqa: BLE001 - preserved behavior
    exrex = None

from havocforge.context import GenContext
from havocforge.errors import ContextError
from havocforge.generators.base import BaseGenerator
from havocforge.generators.errors import InvalidParameterError, OutOfBoundsError

from havocforge.registry import Registry


if TYPE_CHECKING:  # avoid import cycles at runtime
    from havocforge.contracts.types import JsonValue  # noqa : F401


@Registry.register(BaseGenerator)  # type: ignore[type-abstract]
class StringGenerator(BaseGenerator):
    """Produces strings using one of: plain synthesis, template expansion, regex
        (exrex), or Faker provider resolution.

    Args:
        string_type (str | None): Dotted Faker provider path (e.g., ``"internet.domain_name"``).
        min_length (int | str | None): Minimum length for plain synthesis.
        max_length (int | str | None): Maximum length for plain synthesis.
        regex (str | None): Regular expression for generation (requires ``exrex``).
        template (str | None): Template with ``{n}`` tokens (e.g., ``"ID-{nnn}"``).
        charset (str | None): Character set used for plain synthesis (defaults to ``ascii_lowercase``).
        n_type (str | None): Token type for ``{n}`` blocks: {``"numeric"``, ``"lower"``, ``"upper"``}.
        n_charset (str | None): Explicit character set for ``{n}`` tokens (overrides ``n_type``).
    """

    __meta__ = {
        "aliases": {
            "charset": "charset",
            "max_length": "max_length",
            "min_length": "min_length",
            "n_charset": "n_charset",
            "n_type": "n_type",
            "regex": "regex",
            "string_type": "string_type",
            "template": "template",
            "bound_to": "bound_to",
            "linked_to": "bound_to",
            "bound_to_schema": "bound_to_schema",
            "bound_to_revision": "bound_to_revision",
            "pool": "pool",
            "depends_on_pool": "depends_on_pool",
        },
        "deprecations": [],
        "rules": [],
    }
    __slots__ = (
        "string_type",
        "min_length",
        "max_length",
        "regex",
        "template",
        "charset",
        "n_type",
        "n_charset",
        "bound_to",
        "bound_to_schema",
        "bound_to_revision",
        "pool",
        "depends_on_pool",
    )
    __aliases__ = ("string", "str")

    def __init__(
        self,
        string_type: Optional[str] = None,
        min_length: int | str | None = None,
        max_length: int | str | None = None,
        regex: Optional[str] = None,
        template: Optional[str] = None,
        charset: Optional[str] = None,
        n_type: Optional[str] = None,
        n_charset: Optional[str] = None,
        bound_to: Optional[str] = None,
        bound_to_schema: str | None = None,
        bound_to_revision: int | None = None,
        pool: List[str] | bool | None = None,
        depends_on_pool: str | None = None,
    ) -> None:
        """Initialize configuration for string generation.

        Args:
            string_type (str | None): Dotted Faker provider path.
            min_length (int | str | None): Minimum length for synthesis.
            max_length (int | str | None): Maximum length for synthesis.
            regex (str | None): Regular expression pattern for generation.
            template (str | None): Template with ``{n}`` tokens.
            charset (str | None): Characters for plain synthesis; defaults to ``ascii_lowercase``.
            n_type (str | None): Token type for ``{n}`` blocks.
            n_charset (str | None): Explicit charset for ``{n}`` tokens.
        """
        self.string_type = string_type
        self.min_length = min_length
        self.max_length = max_length
        self.regex = regex
        self.template = template
        # TODO(BUG): ``charset`` is overridden by ``n_charset`` when ``charset`` is None.
        #            This likely should default to ``charset or ascii_lowercase`` instead.
        self.charset = n_charset if charset is None else charset
        self.n_type = n_type
        self.n_charset = n_charset
        self.bound_to = bound_to
        self.bound_to_schema = bound_to_schema
        self.bound_to_revision = bound_to_revision
        self.pool = pool
        self.depends_on_pool = depends_on_pool

    def _resolve_faker_provider(self, name: str, ctx: GenContext) -> Callable[[], Any]:
        """Resolve a Faker provider or attribute callable from ``ctx``.

        Args:
            name (str): Dotted attribute path on ``ctx.faker``.
            ctx (GenContext): Execution context providing a Faker instance.

        Returns:
            Callable[[], Any]: Zero-arg callable producing a value.

        Raises:
            ContextError: If a Faker instance is not available in context.
            InvalidParameterError: If the provider path is invalid.
        """
        fk = getattr(ctx, "faker", None)
        if fk is None and hasattr(ctx, "get_faker"):
            fk = ctx.get_faker()
        if fk is None:
            raise ContextError("Faker is not available in generation context")
        attr: Any = fk
        for part in str(name).split("."):
            if not hasattr(attr, part):
                raise InvalidParameterError(f"Faker attribute '{name}' not found")
            attr = getattr(attr, part)
        if callable(attr):
            return attr
        return lambda: attr

    @classmethod
    def from_spec(
        cls,
        builder: Any,
        spec: Mapping[str, Any],
    ) -> "StringGenerator":
        """Construct from a generator specification mapping.

        Args:
            builder (Any): Unused builder/factory (kept for signature parity).
            spec (Mapping[str, Any]): Mapping parsed from configuration.

        Returns:
            StringGenerator: Configured instance.
        """
        return cls(
            string_type=spec.get("string_type"),
            min_length=spec.get("min_length"),
            max_length=spec.get("max_length"),
            regex=spec.get("regex"),
            template=spec.get("template"),
            charset=spec.get("charset"),
            n_type=spec.get("n_type"),
            n_charset=spec.get("n_charset"),
            bound_to=spec.get("bound_to") or spec.get("linked_to"),
            bound_to_schema=spec.get("bound_to_schema"),
            bound_to_revision=spec.get("bound_to_revision"),
            pool=spec.get("pool"),
            depends_on_pool=spec.get("depends_on_pool"),
        )

    def _sanity_check(self, ctx: GenContext) -> None:
        """Validate configuration and context preconditions.

        Args:
            ctx (GenContext): Active generation context.

        Raises:
            ContextError: If ``ctx`` is not a ``GenContext``.
            OutOfBoundsError: If ``min_length > max_length``.
            InvalidParameterError: On mutually exclusive options.
        """
        if not isinstance(ctx, GenContext):
            raise ContextError("ctx must be an instance of GenContext")
        if (
            self.min_length is not None
            and self.max_length is not None
            and (int(self.min_length) > int(self.max_length))
        ):
            raise OutOfBoundsError("min_length must be <= max_length")
        if self.string_type and (self.regex or self.template):
            raise InvalidParameterError(
                "string_type is mutually exclusive with regex/template"
            )
        if self.template and self.regex:
            raise InvalidParameterError("template is mutually exclusive with regex")

    def _token_chars(self) -> str:
        """Return the character set for ``{n}`` tokens.

        Returns:
            str: Character set used for template token expansion.
        """
        if self.n_charset:
            return self.n_charset
        if self.n_type == "numeric":
            return digits
        if self.n_type == "lower":
            return ascii_lowercase
        return ascii_uppercase

    def _apply_template(self, ctx: GenContext) -> str:
        """Expand template ``{n}`` tokens using the configured token charset.

        Args:
            ctx (GenContext): Execution context providing RNG.

        Returns:
            str: Rendered string.
        """
        template = self.template or ""

        def repl(match: re.Match[str]) -> str:
            ncount = len(match.group(1))
            chars = self._token_chars()
            out: list[str] = []
            for _ in range(ncount):
                out.append(chars[ctx.rng.randint(0, len(chars) - 1)])
            return "".join(out)

        return re.sub(r"\{(n+)\}", repl, template)

    def _plain_synth(self, ctx: GenContext) -> str:
        """Synthesize a plain random string from ``charset``.

        Args:
            ctx (GenContext): Execution context providing RNG.

        Returns:
            str: Generated string.
        """
        chars = self.charset or ascii_lowercase
        lo = int(self.min_length) if self.min_length is not None else 1
        hi = int(self.max_length) if self.max_length is not None else 100
        if hi < lo:
            hi = lo
        length = ctx.rng.randint(lo, hi)
        out: list[str] = []
        for _ in range(length):
            out.append(chars[ctx.rng.randint(0, len(chars) - 1)])
        return "".join(out)

    def _regex_generate(self, ctx: GenContext) -> str:
        """Generate a string from ``regex`` using ``exrex``.

        Args:
            ctx (GenContext): Execution context providing RNG.

        Returns:
            str: Generated string.

        Raises:
            InvalidParameterError: If ``exrex`` is unavailable or inputs are invalid.
        """
        if exrex is None:
            raise InvalidParameterError(
                "exrex is required for regex generation but is not installed"
            )
        pattern = self.regex
        if not isinstance(pattern, str) or not pattern:
            raise InvalidParameterError("regex must be a non-empty string")
        import random

        state = random.getstate()
        try:
            rnd_seed = int(ctx.rng.random() * 1_000_000_000)
            random.seed(rnd_seed)
            return exrex.getone(pattern)
        except Exception as exc:  # noqa: BLE001 - preserved behavior
            # TODO(errors): Narrow to library-specific errors once standardized.
            raise InvalidParameterError(f"regex generation failed: {exc}")
        finally:
            random.setstate(state)

    def _generate_impl(self, ctx: GenContext) -> "JsonValue":
        """Produce a value according to the generator configuration.

        Args:
            ctx (GenContext): Execution context.

        Returns:
            JsonValue: A string value.
        """
        self._sanity_check(ctx)
        if self.template:
            return self._apply_template(ctx)
        if self.regex:
            return self._regex_generate(ctx)
        if self.string_type:
            provider = self._resolve_faker_provider(self.string_type, ctx)
            out = provider()
            if out is None or not isinstance(out, str):
                raise InvalidParameterError(
                    f"Faker attribute '{self.string_type}' did not return a string"
                )
            return out
        return self._plain_synth(ctx)
