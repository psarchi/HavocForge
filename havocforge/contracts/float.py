from __future__ import annotations
from typing import List, Optional, ClassVar, Union
from pydantic import BaseModel, ConfigDict


class FloatGeneratorSpec(BaseModel):
    """Float Generator Spec."""

    # type aliasing
    type_token: ClassVar[str] = "float"
    type_aliases: ClassVar[List[str]] = ["double", "number"]
    model_config = ConfigDict(extra="forbid")

    min: Optional[float] = None
    max: Optional[float] = None
    precision: Optional[int] = None
    bound_to: Optional[str] = None
    linked_to: Optional[str] = None
    bound_to_schema: Optional[str] = None
    bound_to_revision: Optional[int] = None
    pool: Optional[Union[List[str], bool]] = None
    depends_on_pool: Optional[str] = None
