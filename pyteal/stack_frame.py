from ast import AST, FunctionDef, unparse
from configparser import ConfigParser
from contextlib import contextmanager
from dataclasses import dataclass
from enum import IntEnum
from inspect import FrameInfo, stack
from typing import Callable, Final, cast
import os
import re

from executing import Source  # type: ignore


@dataclass(frozen=True)
class StackFrame:
    """
    StackFrame is an _internal_ PyTeal class and is
    the first ancestor in the following linear class hierarchy:
                        StackFrame
                            |
                        PyTealFrame
                            |
    compiler.sourcemap.TealMapItem

    Somewhat confusingly, NatalStackFrame is _NOT_ in this hierarchy
    so not "is-a" StackFrame, but it pretends to be and "has-a" list of StackFrame's.

    Its most important members are:
        * frame_info of type inspect.FrameInfo
        * node of type ast.AST
    The first is a python representation of a stack frame, and the
    second represents a python AST node. The imported package `executing`
    features the method `Source.executing` which when run shortly after
    the frame_info's creation, _usually_ succeeds in recovering the
    associated AST node.

    In the current usage, there is a `creator` member which is a `NatalStackFrame`
    object -usually belonging to a PyTeal Expr- and which is assumed to have called
    the private constructor `_init_or_drop()`.

    It is not recommended that this class be accessed directly.

    Of special note, is the class variable `_internal_paths`.
    This is a whitelist of file patterns which signal to the logic
    of method `_frame_info_is_pyteal()` that a particular
    frame was _NOT_ created by the user.

    QUIRKS:
    * Unfortunately, this means that if a user created file satisfies the above pattern,
    the performance of the source mapper will degrade.
    * User generated code that includes the pattern `NatalStackFrame` may produce degraded results
    """

    frame_info: FrameInfo
    node: AST | None
    creator: "NatalStackFrame"

    # for debugging purposes:
    full_stack: list[FrameInfo] | None = None

    @classmethod
    def _init_or_drop(
        cls, creator: "NatalStackFrame", f: FrameInfo, full_stack: list[FrameInfo]
    ) -> "StackFrame | None":
        """
        Attempt to create a StackFrame object.
        However, if the resulting is considered "Python Crud" abandon and return None.
        When debugging, also persist the full_stack that was provided.
        """
        node = cast(AST | None, Source.executing(f.frame).node)
        frame = StackFrame(
            f, node, creator, full_stack if NatalStackFrame._debug else None
        )
        return frame if frame._not_py_crud() else None

    # TODO: when a source mapper is instantiated, it ought to survey
    # the user's project files and warn in the case that some file
    # matches the _internal_paths pattern
    _internal_paths = [
        "beaker/__init__.py",
        "beaker/application.py",
        "beaker/consts.py",
        "beaker/decorators.py",
        "beaker/state.py",
        "pyteal/__init__.py",
        "pyteal/ast",
        "pyteal/compiler",
        "pyteal/ir",
        "pyteal/pragma",
        "pyteal/stack_frame.py",
        "tests/abi_roundtrip.py",
        "tests/blackbox.py",
        "tests/compile_asserts.py",
        "tests/mock_version.py",
    ]
    _internal_paths_re = re.compile("|".join(_internal_paths))

    def as_pyteal_frame(
        self,
        rel_paths: bool = True,
        parent: "PyTealFrame | None" = None,
    ) -> "PyTealFrame":
        """
        Downcast one level in the class hierarchy
        """
        return PyTealFrame(
            frame_info=self.frame_info,
            node=self.node,
            creator=self.creator,
            full_stack=self.full_stack,
            rel_paths=rel_paths,
            parent=parent,
        )

    @classmethod
    def _frame_info_is_right_before_core(cls, f: FrameInfo) -> bool:
        # We keep this method around to be used in a test . Originally,
        # it was actually used in the __init__ method of StackFrame
        # to calculate `last_drop_idx`. However, as -at the time of writing-
        # last_drop_idx =ALWAYS= 1, the logic was simplified and
        # this method was removed from the live calculation.
        return bool(code := f.code_context or []) and "NatalStackFrame" in "".join(code)

    def _is_pyteal(self) -> bool:
        return self._frame_info_is_pyteal(self.frame_info)

    @classmethod
    def _frame_info_is_pyteal(cls, f: FrameInfo) -> bool:
        return bool(cls._internal_paths_re.search(f.filename))

    def _is_pyteal_import(self) -> bool:
        return self._frame_info_is_pyteal_import(self.frame_info)

    @classmethod
    def _frame_info_is_pyteal_import(cls, f: FrameInfo) -> bool:
        cc = f.code_context
        if not cc:
            return False

        code = "".join(cc).split()
        return "import" in code and "pyteal" in code

    def _not_py_crud(self) -> bool:
        """Hackery that depends on C-Python. Not sure how reliable."""
        return self._frame_info_not_py_crud(self.frame_info)

    @classmethod
    def _frame_info_not_py_crud(cls, f: FrameInfo) -> bool:
        return bool(f.code_context) or not f.filename.startswith("<")

    def __repr__(self) -> str:
        node = unparse(n) if (n := self.node) else None
        context = "".join(cc) if (cc := (fi := self.frame_info).code_context) else None
        return f"{node=}; {context=}; frame_info={fi}"

    def compiler_generated(self) -> bool | None:
        if self.creator._compiler_gen:
            return True

        return self._frame_info_compiler_generated(self.frame_info)

    @classmethod
    def _frame_info_compiler_generated(cls, f: FrameInfo) -> bool | None:
        if not (cc := f.code_context):
            return None  # we don't know / NA

        return "# T2PT" in "".join(cc)


def _sourcmapping_is_off(verbose=False) -> bool:
    try:
        config = ConfigParser()
        config.read("pyteal.ini")
        enabled = config.getboolean("pyteal-source-mapper", "enabled")
        return not enabled
    except Exception as e:
        if verbose:
            print(
                f"""Turning off frame capture and disabling sourcemaps. 
Could not read section (pyteal-source-mapper, enabled) of config "pyteal.ini": {e}"""
            )
    return True


def _debug_frames(verbose=False) -> bool:
    try:
        config = ConfigParser()
        config.read("pyteal.ini")
        return config.getboolean("pyteal-source-mapper", "debug")
    except Exception as e:
        if verbose:
            print(
                f"""Disabling `debug` status for sourcemaps. 
Could not read section (pyteal-source-mapper, debug) of config "pyteal.ini": {e}"""
            )
    return False


@contextmanager
def sourcemapping_off_context():
    """Context manager that turns off sourcemapping for the duration of the context"""
    _no_stackframes_before = NatalStackFrame._no_stackframes
    _debug_before = NatalStackFrame._debug
    NatalStackFrame._no_stackframes = True
    NatalStackFrame._debug = False

    try:
        yield

    finally:
        NatalStackFrame._no_stackframes = _no_stackframes_before
        NatalStackFrame._debug = _debug_before


class NatalStackFrame:
    """
    PyTeal's source mapper deduces the code-location of a user's Expr
    via a NatalStackFrame object that is associated with the Expr object.

    When source mapping is disabled (cf. `pyteal.ini`), NatalStackFrame'
    constructor is a no-op.

    When source mapping is enabled, it wraps a list of StackFrame's.

    Under normal operations, only the "best" frame is kept in the list, so
    the name is misleading.
    """

    _no_stackframes: bool = _sourcmapping_is_off()
    _debug: bool = _debug_frames()
    _keep_all_debugging = False

    @classmethod
    def sourcemapping_is_off(cls, _force_refresh: bool = False) -> bool:
        """
        The `_force_refresh` parameter, is mainly for test validation purposes.
        It is discouraged for use in the wild because:
        * Frames are useful in an "all or nothing" capacity. For example, in preparing
            for a source mapping, it would be error prone to generate frames for
            a subset of analyzed PyTeal
        * Setting `_force_refresh = True` will cause a read from the file system every
            time Frames are initialized and will result in significant performance degredation
        """
        if _force_refresh:
            cls._no_stackframes = _sourcmapping_is_off()

        return cls._no_stackframes

    def __init__(
        self,
    ):
        self._compiler_gen: bool = False
        self._frames: list[StackFrame] = []

        if self.sourcemapping_is_off():
            return

        # 1. get the full stack trace
        full_stack = stack()

        # 2. discard frames whose filename begins with "<"
        frame_infos = list(filter(StackFrame._frame_info_not_py_crud, full_stack))

        def _make_stack_frames(fis):
            return [
                frame
                for f in fis
                if (frame := StackFrame._init_or_drop(self, f, full_stack))
            ]

        if self._keep_all_debugging or len(frame_infos) <= 1:
            self._frames = _make_stack_frames(frame_infos)
            return

        # 3. start the best frame search right after where NatalStackFrame() was constructed
        # For more details see the unit test:
        # tests/unit/sourcemap_monkey_unit_test.py::test_frame_info_is_right_before_core_last_drop_idx
        i = 2  # formerly this was `last_drop_idx = 1; i = last_drop_idx + 1`

        # 4. fast forward the right bound until we're out of pyteal-library code
        # This sets last_keep_idx to the first frame index which isn't pyteal
        while i < len(frame_infos) and StackFrame._frame_info_is_pyteal(frame_infos[i]):
            i += 1
        last_keep_idx = i

        # 5. if the pyteal-library exit point was an import, the expression was
        # generated by pyteal itself. So let's back up and look for a "# T2PT*" comment
        # which will give us a clue for what to do with this expression
        if StackFrame._frame_info_is_pyteal_import(frame_infos[last_keep_idx]):
            found = False
            i = -1
            for i in range(last_keep_idx - 1, -1, -1):
                if StackFrame._frame_info_compiler_generated(frame_infos[i]):
                    found = True
                    break

            if found and i >= 0:
                last_keep_idx = i

        # 6. Keep only the last frame in the list. We maintain _as_ a list
        # since in the case of `self._debug == True`, we'd like access to the full list.
        # TODO: this is likely obsolete since full_stack is available on the PyTealFrame object when debugging
        frame_infos = frame_infos[last_keep_idx : last_keep_idx + 1]

        # 7. we finish by constructing a list[StackFrame] from our one remaining frame_info
        self._frames = _make_stack_frames(frame_infos)

    def __len__(self) -> int:
        return len(self._frames)

    def best(self) -> StackFrame:
        """
        Return the best guess as to the user-authored birthplace of the
        associated StackFrame's
        """
        assert (
            self._frames
        ), f"expected to have some frames but currently {self._frames=}"
        return self._frames[-1]

    def __repr__(self) -> str:
        return f"{'C' if self._compiler_gen else 'U'}{self._frames}"

    def nodes(self) -> list[AST | None]:
        return [f.node for f in self._frames]

    @classmethod
    def _walk_asts(cls, func: Callable[["Expr"], None], *exprs: "Expr") -> None:  # type: ignore
        from pyteal.ast import (
            Assert,
            BinaryExpr,
            Cond,
            Expr,
            Return,
            Seq,
            SubroutineDeclaration,
        )
        from pyteal.ast.frame import Proto

        for expr in exprs:
            e = cast(Expr, expr)
            func(e)

            match e:
                case Assert():
                    cls._walk_asts(func, *e.cond)
                case BinaryExpr():
                    cls._walk_asts(func, e.argLeft, e.argRight)
                case Cond():
                    cls._walk_asts(func, *(y for x in e.args for y in x))
                case Proto():
                    cls._walk_asts(func, e.mem_layout)
                case Seq():
                    cls._walk_asts(func, *e.args)
                case Return():
                    cls._walk_asts(func, e.value)
                case SubroutineDeclaration():
                    cls._walk_asts(func, e.body)
                case _:
                    # TODO: implement more cases, but no need to error as this isn't used for functionality's sake.
                    pass

    @classmethod
    def _debug_asts(cls, *exprs: "Expr") -> None:  # type: ignore
        """
        For deubgging purposes only!
        """
        from pyteal.ast import Expr

        if cls.sourcemapping_is_off():
            return

        def dbg(e: Expr):
            print(
                type(e), ": ", e.stack_frames.best().as_pyteal_frame().hybrid_unparsed()
            )

        cls._walk_asts(dbg, *exprs)

    @classmethod
    def mark_asts_as_compiler_gen(cls, *exprs: "Expr") -> None:  # type: ignore
        from pyteal.ast import Expr

        if cls.sourcemapping_is_off():
            return

        def mark(e: Expr):
            e.stack_frames._compiler_gen = True

        cls._walk_asts(mark, *exprs)

    @classmethod
    def reframe_asts(cls, stack_frames: "NatalStackFrame", *exprs: "Expr") -> None:  # type: ignore
        from pyteal.ast import Expr

        if cls.sourcemapping_is_off():
            return

        def set_frames(e: Expr):
            e.stack_frames = stack_frames

        cls._walk_asts(set_frames, *exprs)

    @classmethod
    def reframe_ops_in_blocks(cls, root_expr: "Expr", start: "TealBlock") -> None:  # type: ignore
        start._sframes_container = root_expr
        for op in start.ops:
            op._sframes_container = root_expr

        if nxt := start.nextBlock:
            cls.reframe_ops_in_blocks(root_expr, nxt)


class PT_GENERATED:
    PRAGMA = "PyTeal generated pragma"
    SUBR_LABEL = "PyTeal generated subroutine label"
    RETURN_NONE = "PyTeal generated return for TealType.none"
    RETURN_VALUE = "PyTeal generated return for non-null TealType"
    SUBR_PARAM = "PyTeal generated subroutine parameter handler instruction"
    BRANCH = "PyTeal generated branching"
    BRANCH_LABEL = "PyTeal generated branching label"
    TYPE_ENUM_TXN = "PyTeal generated transaction Type Enum"
    TYPE_ENUM_ONCOMPLETE = "PyTeal generated OnComplete Type Enum"
    FLAGGED_BY_DEV = "Developer has flagged expression as compiler generated"


_PT_GEN = {
    "# T2PT0": PT_GENERATED.PRAGMA,
    "# T2PT1": PT_GENERATED.SUBR_LABEL,
    "# T2PT2": PT_GENERATED.RETURN_NONE,
    "# T2PT3": PT_GENERATED.RETURN_VALUE,
    "# T2PT4": PT_GENERATED.SUBR_PARAM,
    "# T2PT5": PT_GENERATED.BRANCH,
    "# T2PT6": PT_GENERATED.BRANCH_LABEL,
    "# T2PT7": PT_GENERATED.TYPE_ENUM_TXN,
    "# T2PT8": PT_GENERATED.TYPE_ENUM_ONCOMPLETE,
}


class PyTealFrameStatus(IntEnum):
    """integer values indicate 'confidence' on a scale of 0 - 10"""

    MISSING = 0
    MISSING_AST = 1
    MISSING_CODE = 2
    PYTEAL_GENERATED = 3
    PATCHED_BY_PREV_OVERRIDE_NEXT = 4
    PATCHED_BY_NEXT_OVERRIDE_PREV = 5
    PATCHED_BY_PREV = 6
    PATCHED_BY_NEXT = 7
    PATCHED_BY_PREV_AND_NEXT = 8
    COPACETIC = 9  # currently, 90% confident is as good as it gets

    def human(self) -> str:
        match self:
            case self.MISSING:
                return "sourcemapping line: total failure"
            case self.MISSING_AST:
                return "unreliable as missing AST"
            case self.MISSING_CODE:
                return "unreliable as couldn't retrieve source"
            case self.PYTEAL_GENERATED:
                return "INCOMPLETE"  # "incomplete as source not user generated"
            case self.PATCHED_BY_PREV_OVERRIDE_NEXT:
                return "previously INCOMPLETE- patched to previous frame (ambiguous)"
            case self.PATCHED_BY_NEXT_OVERRIDE_PREV:
                return "previously INCOMPLETE- patched to next frame (ambiguous)"
            case self.PATCHED_BY_PREV:
                return "previously INCOMPLETE- patched to previous frame"
            case self.PATCHED_BY_NEXT:
                return "previously INCOMPLETE- patched to next frame"
            case self.PATCHED_BY_PREV_AND_NEXT:
                return "previously INCOMPLETE- patched"
            case self.COPACETIC:
                return "COPACETIC"

        raise Exception(f"unrecognized {type(self)} - THIS SHOULD NEVER HAPPEN!")


class PyTealFrame(StackFrame):
    """
    PyTealFrame is the middle generation in the StackFrame class hierarchy.

    It adds a richer and more polished set of methods to learn about the PyTeal source.
    """

    def __init__(
        self,
        frame_info: FrameInfo,
        node: AST | None,
        creator: NatalStackFrame,
        full_stack: list[FrameInfo] | None,
        rel_paths: bool = True,
        parent: "PyTealFrame | None" = None,
    ):
        super().__init__(frame_info, node, creator, full_stack)
        self.rel_paths: Final[bool] = rel_paths
        self.parent: "Final[PyTealFrame | None]" = parent

        self._raw_code: str | None = None
        self._status: PyTealFrameStatus | None = None

    def __repr__(self) -> str:
        """
        This repr isn't compliant, but keeping as it's useful for debugging in VSCode
        """
        return self._str_impl(verbose=False)

    def __eq__(self, other: object) -> bool:
        """We don't care about parents here. TODO: this comment is too rude"""
        if not isinstance(other, PyTealFrame):
            return False

        return all(
            [
                self.frame_info == other.frame_info,
                self.node == other.node,
                self.rel_paths == other.rel_paths,
            ]
        )

    def clone(self, status: PyTealFrameStatus) -> "PyTealFrame":
        ptf = PyTealFrame(
            frame_info=self.frame_info,
            node=self.node,
            creator=self.creator,
            full_stack=self.full_stack,
            rel_paths=self.rel_paths,
        )
        ptf._status = status

        return ptf

    def location(self) -> str:
        return f"{self.file()}:{self.lineno()}" if self.frame_info else ""

    def file(self) -> str:
        if not self.frame_info:
            return ""

        path = self.frame_info.filename
        return os.path.relpath(path) if self.rel_paths else path

    def root(self) -> str:
        if not self.frame_info:
            return ""

        path = self.frame_info.filename
        return path[: -len(self.file())]

    def code_qualname(self) -> str:
        return (
            Source.executing(self.frame_info.frame).code_qualname()
            if self.frame_info
            else ""
        )

    def lineno(self) -> int | None:
        naive_lineno = self.frame_info.lineno if self.frame_info else None
        if naive_lineno is None:
            return naive_lineno

        hybrid_line, offset = self._hybrid_w_offset()
        if hybrid_line.startswith(self.raw_code()):
            return naive_lineno

        return naive_lineno + offset

    def column(self) -> int:
        """Provide accurate 0-indexed column offset when available. Or 0 when not."""
        return self.node_col_offset() or 0

    def compiler_generated_reason(self) -> str | None:
        """
        None indicates either "unkown" or "not compiler generated".
        To distinguish between these two usages, call `compiler_generated()` first.
        """
        if not self.compiler_generated():
            return None

        if self.creator._compiler_gen:
            return PT_GENERATED.FLAGGED_BY_DEV

        for k, v in _PT_GEN.items():
            if k in self.raw_code():
                return v

        raise AssertionError(
            "This should never happen as the call to self.compiler_generated() should have prevented this case."
        )

    # VARIATIONS ON THE THEME OF SOURCE CODE:

    def raw_code(self) -> str:
        if self._raw_code is None:
            self._raw_code = (
                ("".join(self.frame_info.code_context)).strip()
                if self.frame_info and self.frame_info.code_context
                else ""
            )

        return self._raw_code

    def hybrid_unparsed(self) -> str:
        """
        Attempt to unparse the node and return the most apropos line
        """
        return self._hybrid_w_offset()[0]

    def _hybrid_w_offset(self) -> tuple[str, int]:
        """
        Attempt to unparse the node and return the most apropos line,
        together with its offset in comparison with its raw code.
        """
        raw_code = self.raw_code()
        node = self.node
        pt_chunk = self.node_source()
        return self._hybrid_impl(raw_code, node, pt_chunk)

    @classmethod
    def _hybrid_impl(
        cls, code: str, node: AST | None, pt_chunk: str
    ) -> tuple[str, int]:
        """
        Given a chunk of PyTeal `pt_chunk` represending a node's source,
        and `code` representing a FrameInfo's code_context,
        return information about the most appropriate code to use in
        the source map.
        When the node source isn't available, return `code`
        and an offset of 0.
        When the node source is a single line, return `pt_chunk`
        and an offset of 0.
        When the node source is a multi-line chunk, in the case of
        a non-FunctionDef node, we assume that the offset is 0.
        Finally, in the case of a FunctionDef node, find the offset
        by finding where the prefix `def` appears in the chunk.
        """
        if pt_chunk:
            pt_lines = pt_chunk.splitlines()
            if len(pt_lines) == 1:
                return pt_chunk, 0

            offset = i = 0
            if pt_lines and isinstance(node, FunctionDef):
                code_idx = -1
                for i, line in enumerate(pt_lines):
                    if line.startswith(code):
                        code_idx = i
                    if line.startswith("def"):
                        if code_idx >= 0:
                            offset = i - code_idx
                        return pt_lines[i], offset
                if code_idx >= 0:
                    return pt_lines[code_idx], 0

        return code, 0

    # END OF VARIATIONS ON A THEME OF CODE
    def failed_ast(self) -> bool:
        return not self.node

    def status_code(self) -> PyTealFrameStatus:
        if self._status is not None:
            return self._status

        if self.frame_info is None:
            return PyTealFrameStatus.MISSING

        if self.node is None:
            return PyTealFrameStatus.MISSING_AST

        if self.compiler_generated():
            return PyTealFrameStatus.PYTEAL_GENERATED

        if not self.raw_code():
            return PyTealFrameStatus.MISSING_CODE

        return PyTealFrameStatus.COPACETIC

    def status(self) -> str:
        return self.status_code().human()

    def node_source(self) -> str:
        return unparse(self.node) if self.node else ""

    def node_lineno(self) -> int | None:
        return getattr(self.node, "lineno", None) if self.node else None

    def node_col_offset(self) -> int | None:
        """0-indexed BEGINNING column offset"""
        return getattr(self.node, "col_offset", None) if self.node else None

    def node_end_lineno(self) -> int | None:
        return getattr(self.node, "end_lineno", None) if self.node else None

    def node_end_col_offset(self) -> int | None:
        """0-indexed ENDING column offset"""
        return getattr(self.node, "end_col_offset", None) if self.node else None

    def node_source_window(self) -> str:
        boundaries = (
            self.node_lineno(),
            self.node_col_offset(),
            self.node_end_lineno(),
            self.node_end_col_offset(),
        )
        if not all(b is not None for b in boundaries):
            return ""
        return "L{}:{}-L{}:{}".format(*boundaries)

    def __str__(self) -> str:
        return self._str_impl(verbose=True)

    def _str_impl(self, verbose: bool = True) -> str:
        if not self.frame_info:
            return "None"

        spaces = "\n\t\t\t"
        short = f"<{self.raw_code()}>{spaces}@{self.location()}"
        if not verbose:
            return short

        return f"""{short}
{self.frame_info.index=}
{self.frame_info.function=}
{self.frame_info.frame=}"""
