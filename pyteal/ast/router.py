from dataclasses import astuple, dataclass, field
from enum import IntFlag
from typing import Callable, Final, Optional, cast

from algosdk import abi as sdk_abi
from algosdk import encoding
from algosdk.v2client.algod import AlgodClient

from pyteal.ast import abi
from pyteal.ast.app import OnComplete
from pyteal.ast.assert_ import Assert
from pyteal.ast.cond import Cond
from pyteal.ast.expr import Expr
from pyteal.ast.int import EnumInt, Int
from pyteal.ast.methodsig import MethodSignature
from pyteal.ast.naryexpr import And, Or
from pyteal.ast.return_ import Approve, Reject
from pyteal.ast.seq import Seq
from pyteal.ast.subroutine import (
    ABIReturnSubroutine,
    OutputKwArgInfo,
    SubroutineFnWrapper,
)
from pyteal.ast.txn import Txn
from pyteal.compiler.compiler import DEFAULT_TEAL_VERSION, Compilation, OptimizeOptions
from pyteal.compiler.sourcemap import PyTealSourceMap
from pyteal.config import METHOD_ARG_NUM_CUTOFF
from pyteal.errors import TealInputError, TealInternalError
from pyteal.ir.ops import Mode
from pyteal.stack_frame import StackFrames
from pyteal.types import TealType
from pyteal.util import algod_with_assertion


class CallConfig(IntFlag):
    """
    CallConfig: a "bitset"-like class for more fine-grained control over
    `call or create` for a method about an OnComplete case.

    This enumeration class allows for specifying one of the four following cases:
    - CALL
    - CREATE
    - ALL
    - NEVER
    for a method call on one on_complete case.
    """

    NEVER = 0
    CALL = 1
    CREATE = 2
    ALL = 3

    def approval_condition_under_config(self) -> Expr | int:
        match self:
            case CallConfig.NEVER:
                return 0
            case CallConfig.CALL:
                return Txn.application_id() != Int(0)
            case CallConfig.CREATE:
                return Txn.application_id() == Int(0)
            case CallConfig.ALL:
                return 1
            case _:
                raise TealInternalError(f"unexpected CallConfig {self}")


CallConfig.__module__ = "pyteal"


@dataclass(frozen=True)
class MethodConfig:
    """
    MethodConfig keep track of one method's CallConfigs for all OnComplete cases.

    The `MethodConfig` implementation generalized contract method call such that the registered
    method call is paired with certain OnCompletion conditions and creation conditions.
    """

    no_op: CallConfig = field(kw_only=True, default=CallConfig.NEVER)
    opt_in: CallConfig = field(kw_only=True, default=CallConfig.NEVER)
    close_out: CallConfig = field(kw_only=True, default=CallConfig.NEVER)
    clear_state: CallConfig = field(kw_only=True, default=CallConfig.NEVER)
    update_application: CallConfig = field(kw_only=True, default=CallConfig.NEVER)
    delete_application: CallConfig = field(kw_only=True, default=CallConfig.NEVER)

    def __post_init__(self):
        if self.clear_state != CallConfig.NEVER:
            raise TealInputError(
                "Attempt to construct clear state program from MethodConfig: "
                "Use Router top level argument `clear_state` instead. "
                "For more details please refer to "
                "https://pyteal.readthedocs.io/en/latest/abi.html#registering-bare-app-calls"
            )

    def is_never(self) -> bool:
        return all(map(lambda cc: cc == CallConfig.NEVER, astuple(self)))

    def approval_cond(self) -> Expr | int:
        config_oc_pairs: list[tuple[CallConfig, EnumInt]] = [
            (self.no_op, OnComplete.NoOp),
            (self.opt_in, OnComplete.OptIn),
            (self.close_out, OnComplete.CloseOut),
            (self.update_application, OnComplete.UpdateApplication),
            (self.delete_application, OnComplete.DeleteApplication),
        ]
        if all(config == CallConfig.NEVER for config, _ in config_oc_pairs):
            return 0
        elif all(config == CallConfig.ALL for config, _ in config_oc_pairs):
            return 1
        else:
            cond_list = []
            for config, oc in config_oc_pairs:
                config_cond = config.approval_condition_under_config()
                match config_cond:
                    case Expr():
                        cond_list.append(And(Txn.on_completion() == oc, config_cond))
                    case 1:
                        cond_list.append(Txn.on_completion() == oc)
                    case 0:
                        continue
                    case _:
                        raise TealInternalError(
                            f"unexpected condition_under_config: {config_cond}"
                        )
            return Or(*cond_list)


MethodConfig.__module__ = "pyteal"


ActionType = Expr | SubroutineFnWrapper | ABIReturnSubroutine


@dataclass
class OnCompleteAction:
    """
    OnComplete Action, registers bare calls to one single OnCompletion case.
    """

    action: Final[ActionType | None] = field(kw_only=True, default=None)
    call_config: Final[CallConfig] = field(kw_only=True, default=CallConfig.NEVER)

    def __post_init__(self):
        if bool(self.call_config) ^ bool(self.action):
            raise TealInputError(
                f"action {self.action} and call_config {self.call_config!r} contradicts"
            )
        self.frames: StackFrames = StackFrames()

    @staticmethod
    def never() -> "OnCompleteAction":
        return OnCompleteAction()

    @staticmethod
    def create_only(f: ActionType) -> "OnCompleteAction":
        return OnCompleteAction(action=f, call_config=CallConfig.CREATE)

    @staticmethod
    def call_only(f: ActionType) -> "OnCompleteAction":
        return OnCompleteAction(action=f, call_config=CallConfig.CALL)

    @staticmethod
    def always(f: ActionType) -> "OnCompleteAction":
        return OnCompleteAction(action=f, call_config=CallConfig.ALL)

    def is_empty(self) -> bool:
        return not self.action and self.call_config == CallConfig.NEVER


OnCompleteAction.__module__ = "pyteal"


class BareCallActions:
    """
    BareCallActions keep track of bare-call registrations to all OnCompletion cases.
    """

    def __init__(
        self,
        *,
        close_out: OnCompleteAction = OnCompleteAction.never(),
        clear_state: OnCompleteAction = OnCompleteAction.never(),
        delete_application: OnCompleteAction = OnCompleteAction.never(),
        no_op: OnCompleteAction = OnCompleteAction.never(),
        opt_in: OnCompleteAction = OnCompleteAction.never(),
        update_application: OnCompleteAction = OnCompleteAction.never(),
    ):
        self.close_out: Final[OnCompleteAction] = close_out
        self.clear_state: Final[OnCompleteAction] = clear_state
        self.delete_application: Final[OnCompleteAction] = delete_application
        self.no_op: Final[OnCompleteAction] = no_op
        self.opt_in: Final[OnCompleteAction] = opt_in
        self.update_application: Final[OnCompleteAction] = update_application

        self.frames: StackFrames = StackFrames()

        if not self.clear_state.is_empty():
            raise TealInputError(
                "Attempt to construct clear state program from bare app call: "
                "Use Router top level argument `clear_state` instead. "
                "For more details please refer to "
                "https://pyteal.readthedocs.io/en/latest/abi.html#registering-bare-app-calls"
            )

    def actions(self) -> list[OnCompleteAction]:
        return [
            self.close_out,
            self.clear_state,
            self.delete_application,
            self.no_op,
            self.opt_in,
            self.update_application,
        ]

    def is_empty(self) -> bool:
        return all([a.is_empty() for a in self.actions()])

    def approval_construction(self) -> Optional[Expr]:
        oc_action_pair: list[tuple[EnumInt, OnCompleteAction]] = [
            (OnComplete.NoOp, self.no_op),
            (OnComplete.OptIn, self.opt_in),
            (OnComplete.CloseOut, self.close_out),
            (OnComplete.UpdateApplication, self.update_application),
            (OnComplete.DeleteApplication, self.delete_application),
        ]
        if all(oca.is_empty() for _, oca in oc_action_pair):
            return None
        conditions_n_branches: list[CondNode] = list()
        for oc, oca in oc_action_pair:
            if oca.is_empty():
                continue
            wrapped_handler = ASTBuilder.wrap_handler(
                False,
                cast(ActionType, oca.action),
            )
            match oca.call_config:
                case CallConfig.ALL:
                    cond_body = wrapped_handler
                case CallConfig.CALL | CallConfig.CREATE:
                    cond_body = Seq(
                        Assert(
                            cast(
                                Expr, oca.call_config.approval_condition_under_config()
                            )
                        ),
                        wrapped_handler,
                    )
                case _:
                    raise TealInternalError(
                        f"Unexpected CallConfig: {oca.call_config!r}"
                    )
            cond = Txn.on_completion() == oc
            conditions_n_branches.append(CondNode(cond, cond_body))
        return Cond(*[[n.condition, n.branch] for n in conditions_n_branches])


BareCallActions.__module__ = "pyteal"


@dataclass(frozen=True)
class CondNode:
    condition: Expr
    branch: Expr


CondNode.__module__ = "pyteal"


@dataclass
class ASTBuilder:
    conditions_n_branches: list[CondNode] = field(default_factory=list)

    @staticmethod
    def wrap_handler(
        is_method_call: bool, handler: ActionType, wrap_to_name: str | None = None
    ) -> Expr:
        """This is a helper function that handles transaction arguments passing in bare-app-call/abi-method handlers.

        If `is_method_call` is True, then it can only be `ABIReturnSubroutine`,
        otherwise:
            - both `ABIReturnSubroutine` and `Subroutine` takes 0 argument on the stack.
            - all three cases have none (or void) type.

        On ABI method case, if the ABI method has more than 15 args, this function manages to de-tuple
        the last (16-th) Txn app-arg into a list of ABI method arguments, and pass in to the ABI method.

        Args:
            is_method_call: a boolean value that specify if the handler is an ABI method.
            handler: an `ABIReturnSubroutine`, or `SubroutineFnWrapper` (for `Subroutine` case), or an `Expr`.
        Returns:
            Expr:
                - for bare-appcall it returns an expression that the handler takes no txn arg and Approve
                - for abi-method it returns the txn args correctly decomposed into ABI variables,
                  passed in ABIReturnSubroutine and logged, then approve.
        """
        if not is_method_call:
            wrap_to_name = "bare appcall" if wrap_to_name is None else wrap_to_name

            match handler:
                case Expr():
                    if handler.type_of() != TealType.none:
                        raise TealInputError(
                            f"{wrap_to_name} handler should be TealType.none not {handler.type_of()}."
                        )
                    if handler.has_return():
                        return handler
                    seq = Seq(handler, a := Approve())
                    a.stack_frames._compiler_gen = True
                    seq.stack_frames = handler.stack_frames
                    return seq
                case SubroutineFnWrapper():
                    if handler.type_of() != TealType.none:
                        raise TealInputError(
                            f"subroutine call should be returning TealType.none not {handler.type_of()}."
                        )
                    if handler.subroutine.argument_count() != 0:
                        raise TealInputError(
                            f"subroutine call should take 0 arg for {wrap_to_name}. "
                            f"this subroutine takes {handler.subroutine.argument_count()}."
                        )
                    seq = Seq(handler(), a := Approve())
                    a.stack_frames._compiler_gen = True
                    return seq
                case ABIReturnSubroutine():
                    if handler.type_of() != "void":
                        raise TealInputError(
                            f"abi-returning subroutine call should be returning void not {handler.type_of()}."
                        )
                    if handler.subroutine.argument_count() != 0:
                        raise TealInputError(
                            f"abi-returning subroutine call should take 0 arg for {wrap_to_name}. "
                            f"this abi-returning subroutine takes {handler.subroutine.argument_count()}."
                        )

                    seq = Seq(cast(Expr, handler()), a := Approve())
                    a.stack_frames._compiler_gen = True
                    return seq
                case _:
                    raise TealInputError(
                        f"{wrap_to_name} can only accept: none type Expr, or Subroutine/ABIReturnSubroutine with none return and no arg"
                    )
        else:
            wrap_to_name = "method call" if wrap_to_name is None else wrap_to_name
            if not isinstance(handler, ABIReturnSubroutine):
                raise TealInputError(
                    f"{wrap_to_name} should be only registering ABIReturnSubroutine, got {type(handler)}."
                )
            if not handler.is_abi_routable():
                raise TealInputError(
                    f"{wrap_to_name} ABIReturnSubroutine is not routable "
                    f"got {handler.subroutine.argument_count()} args with {len(handler.subroutine.abi_args)} ABI args."
                )

            # All subroutine args types
            arg_type_specs = cast(
                list[abi.TypeSpec], handler.subroutine.expected_arg_types
            )

            # All subroutine arg values, initialize here and use below instead of
            # creating new instances on the fly, so we don't have to think about splicing
            # back in the transaction types
            arg_vals = [typespec.new_instance() for typespec in arg_type_specs]

            # Only args that appear in app args
            app_arg_vals: list[abi.BaseType] = [
                ats for ats in arg_vals if not isinstance(ats, abi.Transaction)
            ]

            for aav in app_arg_vals:
                # If we're here we know the top level isnt a Transaction but a transaction may
                # be included in some collection type like a Tuple or Array, raise error
                # as these are not supported
                if abi.contains_type_spec(aav.type_spec(), abi.TransactionTypeSpecs):
                    raise TealInputError(
                        "A Transaction type may not be included in Tuples or Arrays"
                    )

            # assign to a var here since we modify app_arg_vals later
            tuplify = len(app_arg_vals) > METHOD_ARG_NUM_CUTOFF

            # only transaction args (these are omitted from app args)
            txn_arg_vals: list[abi.Transaction] = [
                ats for ats in arg_vals if isinstance(ats, abi.Transaction)
            ]

            # Tuple-ify any app args after the limit
            if tuplify:
                tupled_app_args = app_arg_vals[METHOD_ARG_NUM_CUTOFF - 1 :]
                last_arg_specs_grouped: list[abi.TypeSpec] = [
                    t.type_spec() for t in tupled_app_args
                ]
                app_arg_vals = app_arg_vals[: METHOD_ARG_NUM_CUTOFF - 1]
                app_arg_vals.append(
                    abi.TupleTypeSpec(*last_arg_specs_grouped).new_instance()
                )

            # decode app args
            decode_instructions: list[Expr] = [
                app_arg.decode(Txn.application_args[idx + 1])
                for idx, app_arg in enumerate(app_arg_vals)
            ]

            # "decode" transaction types by setting the relative index
            if len(txn_arg_vals) > 0:
                txn_arg_len = len(txn_arg_vals)
                # The transactions should appear in the group in the order they're specified in the method signature
                # and should be relative to the current transaction.

                # ex:
                # doit(axfer,pay,appl)
                # would be 4 transactions
                #      current_idx-3 = axfer
                #      current_idx-2 = pay
                #      current_idx-1 = appl
                #      current_idx-0 = the txn that triggered the current eval (not specified but here for completeness)

                # since we're iterating in order of the txns appearance in the args we
                # subtract the current index from the total length to get the offset.
                # and subtract that from the current index to get the absolute position
                # in the group

                txn_decode_instructions: list[Expr] = []

                for idx, arg_val in enumerate(txn_arg_vals):
                    txn_decode_instructions.append(
                        arg_val._set_index(Txn.group_index() - Int(txn_arg_len - idx))
                    )
                    spec = arg_val.type_spec()
                    if type(spec) is not abi.TransactionTypeSpec:
                        # this is a specific transaction type
                        txn_decode_instructions.append(
                            Assert(arg_val.get().type_enum() == spec.txn_type_enum())
                        )

                decode_instructions += txn_decode_instructions

            # de-tuple into specific values using `store_into` on
            # each element of the tuple'd arguments
            if tuplify:
                tupled_arg: abi.Tuple = cast(abi.Tuple, app_arg_vals[-1])
                de_tuple_instructions: list[Expr] = [
                    tupled_arg[idx].store_into(arg_val)
                    for idx, arg_val in enumerate(tupled_app_args)
                ]
                decode_instructions += de_tuple_instructions

            # NOTE: does not have to have return, can be void method
            seq2: Seq
            if handler.type_of() == "void":
                seq2 = Seq(
                    *decode_instructions,
                    cast(Expr, handler(*arg_vals)),
                    a := Approve(),
                )
            else:
                output_temp: abi.BaseType = cast(
                    OutputKwArgInfo, handler.output_kwarg_info
                ).abi_type.new_instance()
                subroutine_call: abi.ReturnedValue = cast(
                    abi.ReturnedValue, handler(*arg_vals)
                )
                seq2 = Seq(
                    *decode_instructions,
                    subroutine_call.store_into(output_temp),
                    abi_return := abi.MethodReturn(output_temp),
                    a := Approve(),
                )
                abi_return.root_expr = seq2
            a.stack_frames._compiler_gen = True
            return seq2

    def add_method_to_ast(
        self, method_signature: str, cond: Expr | int, handler: ABIReturnSubroutine
    ) -> None:
        walk_in_cond = Txn.application_args[0] == MethodSignature(method_signature)
        match cond:
            case Expr():
                act = Seq(Assert(cond), self.wrap_handler(True, handler))
                self.conditions_n_branches.append(CondNode(walk_in_cond, act))
            case 1:
                self.conditions_n_branches.append(
                    CondNode(walk_in_cond, self.wrap_handler(True, handler))
                )
            case 0:
                return
            case _:
                raise TealInputError("Invalid condition input for add_method_to_ast")

    def program_construction(self) -> Expr:
        if not self.conditions_n_branches:
            return Reject()
        return Cond(*[[n.condition, n.branch] for n in self.conditions_n_branches])


@dataclass
class RouterBundle:
    approval_program: Expr
    clear_program: Expr
    abi_contract: sdk_abi.Contract
    approval_teal: str
    clear_teal: str
    approval_sourcemap: Optional[PyTealSourceMap] = None
    clear_sourcemap: Optional[PyTealSourceMap] = None
    approval_annotated_teal: Optional[str] = None
    clear_annotated_teal: Optional[str] = None
    input: Optional["_RouterCompileInput"] = None


@dataclass
class _RouterCompileInput:
    version: int
    assemble_constants: bool
    optimize_opts: Optional[OptimizeOptions] = None
    with_sourcemap: bool = False
    source_inference: bool = True
    pcs_in_sourcemap: bool = False
    approval_filename: Optional[str] = None
    clear_filename: Optional[str] = None
    algod_client: Optional[AlgodClient] = None
    annotate_teal: bool = False
    annotate_teal_headers: bool = False
    annotate_teal_concise: bool = True
    # deprecated:
    _hybrid_source: bool = True

    def __post_init__(self):
        # The following params are non-sensical when truthy without sourcemaps.
        # However, they are not defining anything actionable so are simple ignored
        # rather than erroring when `with_source == False`:
        # * pcs_in_sourcemap
        # * approval_filename
        # * clear_filename
        # * algod_client

        # On the other hand, self.annotate_teal indicates a user request which cannot
        # be provided on when there isn't a sourcemap
        if self.annotate_teal and not self.with_sourcemap:
            raise ValueError(
                "In order annotate generated teal source, must set source_inference True"
            )

        if self.pcs_in_sourcemap:
            # bootstrap an algod_client if not provided, and in either case, run a healthcheck
            self.algod_client = algod_with_assertion(self.algod_client)

    def get_compilation(self, program: Expr) -> Compilation:
        return Compilation(
            ast=program,
            mode=Mode.Application,
            version=self.version,
            assemble_constants=self.assemble_constants,
            optimize=self.optimize_opts,
        )


class Router:
    """
    The Router class helps construct the approval and clear state programs for an ARC-4 compliant
    application.

    Additionally, this class can produce an ARC-4 contract description object for the application.

    **WARNING:** The ABI Router is still taking shape and is subject to backwards incompatible changes.

    * Based on feedback, the API and usage patterns are likely to change.
    * Expect migration issues in future PyTeal versions.

    For these reasons, we strongly recommend using :any:`pragma` to pin the version of PyTeal in your
    source code.
    """

    def __init__(
        self,
        name: str,
        bare_calls: BareCallActions | None = None,
        descr: str | None = None,
        *,
        clear_state: Optional[ActionType] = None,
    ) -> None:
        """
        Args:
            name: the name of the smart contract, used in the JSON object.
            bare_calls: the bare app call registered for each on_completion.
            descr: a description of the smart contract, used in the JSON object.
            clear_state: an expression describing the behavior of clear state program. This
                expression will be the entirety of the clear state program; no additional code is
                inserted by the Router. If not provided, the clear state program will always reject.
        """

        self.name: str = name
        self.descr = descr

        self.approval_ast = ASTBuilder()
        self.clear_state: Expr = (
            Reject()
            if clear_state is None
            else ASTBuilder.wrap_handler(False, clear_state, "clear state call")
        )

        self.methods: list[sdk_abi.Method] = []
        self.method_sig_to_selector: dict[str, bytes] = dict()
        self.method_selector_to_sig: dict[bytes, str] = dict()

        if bare_calls and not bare_calls.is_empty():
            bare_call_approval = bare_calls.approval_construction()
            if bare_call_approval:
                cond = Txn.application_args.length() == Int(0)
                act = cast(Expr, bare_call_approval)
                StackFrames.reframe_asts(bare_calls.frames, cond)
                act.stack_frames = bare_calls.frames
                self.approval_ast.conditions_n_branches.append(CondNode(cond, act))

    def add_method_handler(
        self,
        method_call: ABIReturnSubroutine,
        overriding_name: str | None = None,
        method_config: MethodConfig | None = None,
        description: str | None = None,
    ) -> ABIReturnSubroutine:
        """Add a method call handler to this Router.

        Args:
            method_call: An ABIReturnSubroutine that implements the method body.
            overriding_name (optional): A name for this method. Defaults to the function name of
                method_call.
            method_config (optional): An object describing the on completion actions and
                creation/non-creation call statuses that are valid for calling this method. All
                invalid configurations will be rejected. Defaults to :code:`MethodConfig(no_op=CallConfig.CALL)`
                (i.e. only the no-op action during a non-creation call is accepted) if none is provided.
            description (optional): A description for this method. Defaults to the docstring of
                method_call, if there is one.
        """
        if not isinstance(method_call, ABIReturnSubroutine):
            raise TealInputError(
                "for adding method handler, must be ABIReturnSubroutine"
            )
        method_signature = method_call.method_signature(overriding_name)
        if method_config is None:
            method_config = MethodConfig(no_op=CallConfig.CALL)
        if method_config.is_never():
            raise TealInputError(
                f"registered method {method_signature} is never executed"
            )
        method_selector = encoding.checksum(bytes(method_signature, "utf-8"))[:4]

        if method_signature in self.method_sig_to_selector:
            raise TealInputError(f"re-registering method {method_signature} detected")
        if method_selector in self.method_selector_to_sig:
            raise TealInputError(
                f"re-registering method {method_signature} has hash collision "
                f"with {self.method_selector_to_sig[method_selector]}"
            )

        meth = method_call.method_spec()
        if description is not None:
            meth.desc = description
        self.methods.append(meth)

        self.method_sig_to_selector[method_signature] = method_selector
        self.method_selector_to_sig[method_selector] = method_signature

        method_approval_cond = method_config.approval_cond()
        self.approval_ast.add_method_to_ast(
            method_signature, method_approval_cond, method_call
        )
        return method_call

    def method(
        self,
        func: Callable | None = None,
        /,
        *,
        name: str | None = None,
        description: str | None = None,
        no_op: CallConfig | None = None,
        opt_in: CallConfig | None = None,
        close_out: CallConfig | None = None,
        clear_state: CallConfig | None = None,
        update_application: CallConfig | None = None,
        delete_application: CallConfig | None = None,
    ):
        """This is an alternative way to register a method, as supposed to :code:`add_method_handler`.

        This is a decorator that's meant to be used over a Python function, which is internally
        wrapped with ABIReturnSubroutine. Additional keyword arguments on this decorator can be used
        to specify the OnCompletion statuses that are valid for the registered method.

        NOTE: By default, all OnCompletion actions other than `no_op` are set to `CallConfig.NEVER`,
        while `no_op` field is set to `CallConfig.CALL`. However, if you provide any keywords for
        OnCompletion actions, then the `no_op` field will default to `CallConfig.NEVER`.

        Args:
            func: A function that implements the method body. This should *NOT* be wrapped with the
                :code:`ABIReturnSubroutine` decorator yet.
            name (optional): A name for this method. Defaults to the function name of func.
            description (optional): A description for this method. Defaults to the docstring of
                func, if there is one.
            no_op (optional): The allowed calls during :code:`OnComplete.NoOp`.
            opt_in (optional): The allowed calls during :code:`OnComplete.OptIn`.
            close_out (optional): The allowed calls during :code:`OnComplete.CloseOut`.
            clear_state (optional): The allowed calls during :code:`OnComplete.ClearState`.
                This argument has been deprecated, and will error on compile time if one wants to access it.
                Use Router top level argument `clear_state` instead.
            update_application (optional): The allowed calls during :code:`OnComplete.UpdateApplication`.
            delete_application (optional): The allowed calls during :code:`OnComplete.DeleteApplication`.
        """
        # we use `is None` extensively for CallConfig to distinguish 2 following cases
        # - None
        # - CallConfig.Never
        # both cases evaluate to False in if statement.

        if clear_state is not None:
            raise TealInputError(
                "Attempt to register ABI method for clear state program: "
                "Use Router top level argument `clear_state` instead. "
                "For more details please refer to "
                "https://pyteal.readthedocs.io/en/latest/abi.html#registering-bare-app-calls"
            )

        def wrap(_func) -> ABIReturnSubroutine:
            wrapped_subroutine = ABIReturnSubroutine(_func, overriding_name=name)
            call_configs: MethodConfig

            ocs = dict(
                no_op=no_op,
                opt_in=opt_in,
                close_out=close_out,
                update_application=update_application,
                delete_application=delete_application,
            )
            if all(oc is None for oc in ocs.values()):
                call_configs = MethodConfig(no_op=CallConfig.CALL)
            else:

                def none_to_never(x: None | CallConfig):
                    return CallConfig.NEVER if x is None else x

                call_configs = MethodConfig(
                    **{k: none_to_never(v) for k, v in ocs.items()}
                )
            return self.add_method_handler(
                wrapped_subroutine, name, call_configs, description
            )

        if not func:
            return wrap
        return wrap(func)

    def contract_construct(self) -> sdk_abi.Contract:
        """A helper function in constructing a `Contract` object.

        It takes out the method spec from approval program methods,
        and constructs an `Contract` object.

        Returns:
            A Python SDK `Contract` object constructed from the registered methods on this router.
        """

        return sdk_abi.Contract(self.name, self.methods, self.descr)

    def build_program(self) -> tuple[Expr, Expr, sdk_abi.Contract]:
        """
        Constructs ASTs for approval and clear-state programs from the registered methods and bare
        app calls in the router, and also generates a Contract object to allow client read and call
        the methods easily.

        Note that if no methods or bare app call actions have been registered to either the approval
        or clear state programs, then that program will reject all transactions.

        Returns:
            A tuple of three objects.

            * approval_program: an AST for approval program
            * clear_state_program: an AST for clear-state program
            * contract: a Python SDK Contract object to allow clients to make off-chain calls
        """
        return (
            self.approval_ast.program_construction(),
            self.clear_state,
            self.contract_construct(),
        )

    def compile_program(
        self,
        *,
        version: int = DEFAULT_TEAL_VERSION,
        assemble_constants: bool = False,
        optimize: Optional[OptimizeOptions] = None,
    ) -> tuple[str, str, sdk_abi.Contract]:
        """
        DEPRECATED BUT KEPT FOR BACKWARDS COMPATIBILITY. PREFER Router.compile().

        Constructs and compiles approval and clear-state programs from the registered methods and
        bare app calls in the router, and also generates a Contract object to allow client read and call
        the methods easily.

        This method combines :any:`Router.build_program` and :any:`compileTeal`.

        Note that if no methods or bare app call actions have been registered to either the approval
        or clear state programs, then that program will reject all transactions.

        Returns:
            A tuple of three objects.

            * approval_program: compiled approval program string
            * clear_state_program: compiled clear-state program string
            * contract: a Python SDK Contract object to allow clients to make off-chain calls
        """
        input = _RouterCompileInput(
            version=version,
            assemble_constants=assemble_constants,
            optimize_opts=optimize,
        )
        cpb = self._build_impl(input)

        return cpb.approval_teal, cpb.clear_teal, cpb.abi_contract

    def compile(
        self,
        *,
        version: int = DEFAULT_TEAL_VERSION,
        assemble_constants: bool = False,
        optimize: Optional[OptimizeOptions] = None,
        approval_filename: Optional[str] = None,
        clear_filename: Optional[str] = None,
        with_sourcemaps: bool = False,
        pcs_in_sourcemap: bool = False,
        algod_client: Optional[AlgodClient] = None,
        annotate_teal: bool = True,
        annotate_teal_headers: bool = False,
        annotate_teal_concise: bool = True,
        # deprecated:
        _source_inference: bool = True,
        _hybrid_source: bool = True,
    ) -> RouterBundle:
        """
        TODO: out of date comment

        Constructs and compiles approval and clear-state programs from the registered methods and
        bare app calls in the router, and also generates a Contract object to allow client read and call
        the methods easily.

        This method combines :any:`Router.build_program` and :any:`compileTeal`.

        Note that if no methods or bare app call actions have been registered to either the approval
        or clear state programs, then that program will reject all transactions.

        Returns:
            A tuple of three objects.

            * approval_program: compiled approval program string
            * clear_state_program: compiled clear-state program string
            * contract: a Python SDK Contract object to allow clients to make off-chain calls
        """
        approval_filename = approval_filename or f"{self.name}_approval.teal"
        clear_filename = clear_filename or f"{self.name}_clear.teal"

        input = _RouterCompileInput(
            version=version,
            assemble_constants=assemble_constants,
            optimize_opts=optimize,
            with_sourcemap=with_sourcemaps,
            approval_filename=approval_filename,
            clear_filename=clear_filename,
            pcs_in_sourcemap=pcs_in_sourcemap,
            algod_client=algod_client,
            annotate_teal=annotate_teal,
            annotate_teal_headers=annotate_teal_headers,
            annotate_teal_concise=annotate_teal_concise,
            # deprecated:
            source_inference=_source_inference,
            _hybrid_source=_hybrid_source,
        )
        return self._build_impl(input)

    def _build_impl(self, input: _RouterCompileInput) -> RouterBundle:
        ap, csp, contract = self.build_program()

        abundle = input.get_compilation(ap).compile(
            with_sourcemap=input.with_sourcemap,
            teal_filename=input.approval_filename,
            pcs_in_sourcemap=input.pcs_in_sourcemap,
            algod_client=input.algod_client,
            annotate_teal=input.annotate_teal,
            annotate_teal_headers=input.annotate_teal_headers,
            annotate_teal_concise=input.annotate_teal_concise,
            # deprecated:
            _source_inference=input.source_inference,
            _hybrid_source=input._hybrid_source,
        )

        csbundle = input.get_compilation(csp).compile(
            with_sourcemap=input.with_sourcemap,
            teal_filename=input.clear_filename,
            pcs_in_sourcemap=input.pcs_in_sourcemap,
            algod_client=input.algod_client,
            annotate_teal=input.annotate_teal,
            annotate_teal_headers=input.annotate_teal_headers,
            annotate_teal_concise=input.annotate_teal_concise,
            # DEPRECATED:
            _source_inference=input.source_inference,
            _hybrid_source=input._hybrid_source,
        )

        return RouterBundle(
            approval_program=ap,
            clear_program=csp,
            abi_contract=contract,
            approval_teal=abundle.teal,
            clear_teal=csbundle.teal,
            approval_sourcemap=abundle.sourcemap,
            clear_sourcemap=csbundle.sourcemap,
            approval_annotated_teal=abundle.annotated_teal,
            clear_annotated_teal=csbundle.annotated_teal,
            input=input,
        )


Router.__module__ = "pyteal"
