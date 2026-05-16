from __future__ import annotations
from typing import ClassVar, List, Set, Optional, Union
from pydantic import ConfigDict
from havocforge.contracts.base import ContractModel


class StringGeneratorSpec(ContractModel):
    """String generator.
    Supports templates, regex, length bounds, and provider shortcuts via string_type/n_type.
    """

    model_config = ConfigDict(extra="forbid")
    type_token: ClassVar[str] = "string"
    type_aliases: ClassVar[Set[str]] = {"str", "text"}

    template: Optional[str] = None
    regex: Optional[str] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    string_type: Optional[str] = None  # e.g., city, state, url, uuid4, word
    n_type: Optional[str] = None  # e.g., numeric templating helper
    bound_to: Optional[str] = None
    linked_to: Optional[str] = None
    bound_to_schema: Optional[str] = None
    bound_to_revision: Optional[int] = None
    pool: Optional[Union[List[str], bool]] = None
    depends_on_pool: Optional[str] = None
