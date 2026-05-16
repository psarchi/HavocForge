from __future__ import annotations
from typing import List, Optional, ClassVar, Union
from pydantic import BaseModel, ConfigDict


class IntGeneratorSpec(BaseModel):
    """Int Generator Spec."""

    # type aliasing
    type_token: ClassVar[str] = "int"
    type_aliases: ClassVar[List[str]] = ["integer"]
    model_config = ConfigDict(extra="forbid")

    min: Optional[int] = None
    max: Optional[int] = None
    step: Optional[int] = None
    bound_to: Optional[str] = None
    linked_to: Optional[str] = None
    bound_to_schema: Optional[str] = None
    bound_to_revision: Optional[int] = None
    pool: Optional[Union[List[str], bool]] = None
    depends_on_pool: Optional[str] = None
