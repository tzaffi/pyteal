from typing import TYPE_CHECKING

from ..types import TealType, valid_address
from ..ir import TealOp, Op, TealBlock
from .expr import Expr

if TYPE_CHECKING:
    from ..compiler import CompileOptions

class Break(Expr):
    """TODO"""

    def __teal__(self, options: 'CompileOptions'):
        start = TealSimpleBlock([])
        end = TealSimpleBlock([])

        if options.currentLoop is None:
            raise TealCompileError(...)
        
        options.breakBlocks.append(start)

        return start, end

    def __str__(self):
        return "(break)"

    def type_of(self):
        return TealType.none

Break.__module__ = "pyteal"
