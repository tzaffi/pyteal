from configparser import ConfigParser
from copy import deepcopy
from pathlib import Path
import pytest
from typing import Literal
from unittest import mock


@pytest.fixture
def mock_ConfigParser():
    patcher = mock.patch.object(ConfigParser, "getboolean", return_value=True)
    patcher.start()
    yield
    patcher.stop()


# ### ----------------- SANITY CHECKS SURVEY MOST PYTEAL CONSTRUCTS ----------------- ### #

P = "#pragma version {v}"  # fill the template at runtime

C = "comp.compile(with_sourcemap=True)"
R = "expr.compile(version=version, assemble_constants=False, optimize=optimize, with_sourcemaps=True)"

BIG_A = "pt.And(pt.Gtxn[0].rekey_to() == pt.Global.zero_address(), pt.Gtxn[1].rekey_to() == pt.Global.zero_address(), pt.Gtxn[2].rekey_to() == pt.Global.zero_address(), pt.Gtxn[3].rekey_to() == pt.Global.zero_address(), pt.Gtxn[4].rekey_to() == pt.Global.zero_address(), pt.Gtxn[0].last_valid() == pt.Gtxn[1].last_valid(), pt.Gtxn[1].last_valid() == pt.Gtxn[2].last_valid(), pt.Gtxn[2].last_valid() == pt.Gtxn[3].last_valid(), pt.Gtxn[3].last_valid() == pt.Gtxn[4].last_valid(), pt.Gtxn[0].type_enum() == pt.TxnType.AssetTransfer, pt.Gtxn[0].xfer_asset() == asset_c, pt.Gtxn[0].receiver() == receiver)"
BIG_OR = "pt.Or(pt.App.globalGet(pt.Bytes('paused')), pt.App.localGet(pt.Int(0), pt.Bytes('frozen')), pt.App.localGet(pt.Int(1), pt.Bytes('frozen')), pt.App.localGet(pt.Int(0), pt.Bytes('lock until')) >= pt.Global.latest_timestamp(), pt.App.localGet(pt.Int(1), pt.Bytes('lock until')) >= pt.Global.latest_timestamp(), pt.App.globalGet(pt.Concat(pt.Bytes('rule'), pt.Itob(pt.App.localGet(pt.Int(0), pt.Bytes('transfer group'))), pt.Itob(pt.App.localGet(pt.Int(1), pt.Bytes('transfer group'))))))"
BIG_C = "pt.Cond([pt.Txn.application_id() == pt.Int(0), foo], [pt.Txn.on_completion() == pt.OnComplete.DeleteApplication, pt.Return(is_admin)], [pt.Txn.on_completion() == pt.OnComplete.UpdateApplication, pt.Return(is_admin)], [pt.Txn.on_completion() == pt.OnComplete.CloseOut, foo], [pt.Txn.on_completion() == pt.OnComplete.OptIn, foo], [pt.Txn.application_args[0] == pt.Bytes('set admin'), foo], [pt.Txn.application_args[0] == pt.Bytes('mint'), foo], [pt.Txn.application_args[0] == pt.Bytes('transfer'), foo], [pt.Txn.accounts[4] == pt.Bytes('foo'), foo])"
BIG_W = "pt.While(i.load() < pt.Global.group_size())"
BIG_F = "pt.For(i.store(pt.Int(0)), i.load() < pt.Global.group_size(), i.store(i.load() + pt.Int(1)))"
BIG_A2 = "pt.And(pt.Int(1) - pt.Int(2), pt.Not(pt.Int(3)), pt.Int(4) ^ pt.Int(5), ~pt.Int(6), pt.BytesEq(pt.Bytes('7'), pt.Bytes('8')), pt.GetBit(pt.Int(9), pt.Int(10)), pt.SetBit(pt.Int(11), pt.Int(12), pt.Int(13)), pt.GetByte(pt.Bytes('14'), pt.Int(15)), pt.Btoi(pt.Concat(pt.BytesDiv(pt.Bytes('101'), pt.Bytes('102')), pt.BytesNot(pt.Bytes('103')), pt.BytesZero(pt.Int(10)), pt.SetBit(pt.Bytes('105'), pt.Int(106), pt.Int(107)), pt.SetByte(pt.Bytes('108'), pt.Int(109), pt.Int(110)))))"
BIG_C2 = "pt.Concat(pt.BytesDiv(pt.Bytes('101'), pt.Bytes('102')), pt.BytesNot(pt.Bytes('103')), pt.BytesZero(pt.Int(10)), pt.SetBit(pt.Bytes('105'), pt.Int(106), pt.Int(107)), pt.SetByte(pt.Bytes('108'), pt.Int(109), pt.Int(110)))"


def abi_named_tuple_example(pt):
    NUM_OPTIONS = 0

    class PollStatus(pt.abi.NamedTuple):
        question: pt.abi.Field[pt.abi.String]
        can_resubmit: pt.abi.Field[pt.abi.Bool]
        is_open: pt.abi.Field[pt.abi.Bool]
        results: pt.abi.Field[
            pt.abi.StaticArray[
                pt.abi.Tuple2[pt.abi.String, pt.abi.Uint64], Literal[NUM_OPTIONS]  # type: ignore
            ]
        ]

    @pt.ABIReturnSubroutine
    def status(*, output: PollStatus) -> pt.Expr:  # type: ignore
        """Get the status of this poll.

        Returns:
            A tuple containing the following information, in order: the question is poll is asking,
            whether the poll allows resubmission, whether the poll is open, and an array of the poll's
            current results. This array contains one entry per option, and each entry is a tuple of that
            option's value and the number of accounts who have voted for it.
        """
        question = pt.abi.make(pt.abi.String)
        can_resubmit = pt.abi.make(pt.abi.Bool)
        is_open = pt.abi.make(pt.abi.Bool)
        results = pt.abi.make(pt.abi.StaticArray[pt.abi.Tuple2[pt.abi.String, pt.abi.Uint64], Literal[NUM_OPTIONS]])  # type: ignore
        return pt.Seq(
            question.set(pt.App.globalGet(pt.Bytes("1"))),
            can_resubmit.set(pt.App.globalGet(pt.Bytes("2"))),
            is_open.set(pt.App.globalGet(pt.Bytes("3"))),
            results.set([]),
            output.set(question, can_resubmit, is_open, results),
        )

    output = PollStatus()
    return pt.Seq(status().store_into(output), pt.Int(1))  # type: ignore


def abi_method_return_example(pt):
    @pt.ABIReturnSubroutine
    def abi_sum(
        toSum: pt.abi.DynamicArray[pt.abi.Uint64], *, output: pt.abi.Uint64
    ) -> pt.Expr:
        i = pt.ScratchVar(pt.TealType.uint64)
        valueAtIndex = pt.abi.Uint64()
        return pt.Seq(
            output.set(0),
            pt.For(
                i.store(pt.Int(0)),
                i.load() < toSum.length(),
                i.store(i.load() + pt.Int(1)),
            ).Do(
                pt.Seq(
                    toSum[i.load()].store_into(valueAtIndex),
                    output.set(output.get() + valueAtIndex.get()),
                )
            ),
        )

    return pt.Seq(
        (to_sum_arr := pt.abi.make(pt.abi.DynamicArray[pt.abi.Uint64])).decode(
            pt.Txn.application_args[1]
        ),
        (res := pt.abi.Uint64()).set(abi_sum(to_sum_arr)),  # type: ignore
        pt.abi.MethodReturn(res),
        pt.Approve(),
    )


def router_example(pt):
    on_completion_actions = pt.BareCallActions(
        opt_in=pt.OnCompleteAction.call_only(pt.Log(pt.Bytes("optin call"))),
    )
    router = pt.Router("questionable", on_completion_actions, clear_state=pt.Approve())

    @router.method
    def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:
        return output.set(a.get() + b.get())

    return router


CONSTRUCTS_LATEST_VERSION = 8


def test_constructs_handles_latest_pyteal():
    import pyteal as pt

    assert CONSTRUCTS_LATEST_VERSION == pt.MAX_PROGRAM_VERSION


CONSTRUCTS = [
    (  # 0: Int
        lambda pt: pt.Return(pt.Int(42)),
        [[P, C], ["int 42", "pt.Int(42)"], ["return", "pt.Return(pt.Int(42))"]],
    ),
    (lambda pt: pt.Int(42), [[P, C], ["int 42", "pt.Int(42)"], ["return", C]]),
    (  # 2: Bytes
        lambda pt: pt.Seq(pt.Pop(pt.Bytes("hello world")), pt.Int(1)),
        [
            [P, C],
            ['byte "hello world"', "pt.Bytes('hello world')"],
            ["pop", "pt.Pop(pt.Bytes('hello world'))"],
            ["int 1", "pt.Int(1)"],
            ["return", C],
        ],
    ),
    (  # 3: *
        lambda pt: pt.Int(2) * pt.Int(3),
        [
            [P, C],
            ["int 2", "pt.Int(2)"],
            ["int 3", "pt.Int(3)"],
            ["*", "pt.Int(2) * pt.Int(3)"],
            ["return", C],
        ],
    ),
    (  # 4: ^
        lambda pt: pt.Int(2) ^ pt.Int(3),
        [
            [P, C],
            ["int 2", "pt.Int(2)"],
            ["int 3", "pt.Int(3)"],
            ["^", "pt.Int(2) ^ pt.Int(3)"],
            ["return", C],
        ],
    ),
    (  # 5: +*
        lambda pt: pt.Int(1) + pt.Int(2) * pt.Int(3),
        [
            [P, C],
            ["int 1", "pt.Int(1)"],
            ["int 2", "pt.Int(2)"],
            ["int 3", "pt.Int(3)"],
            ["*", "pt.Int(2) * pt.Int(3)"],
            ["+", "pt.Int(1) + pt.Int(2) * pt.Int(3)"],
            ["return", C],
        ],
    ),
    (  # 6: ~
        lambda pt: ~pt.Int(1),
        [[P, C], ["int 1", "pt.Int(1)"], ["~", "~pt.Int(1)"], ["return", C]],
    ),
    (  # 7: And Or
        lambda pt: pt.And(
            pt.Int(1),
            pt.Int(2),
            pt.Or(pt.Int(3), pt.Int(4), pt.Or(pt.And(pt.Int(5), pt.Int(6)))),
        ),
        [
            [P, C],
            ["int 1", "pt.Int(1)"],
            ["int 2", "pt.Int(2)"],
            [
                "&&",
                "pt.And(pt.Int(1), pt.Int(2), pt.Or(pt.Int(3), pt.Int(4), pt.Or(pt.And(pt.Int(5), pt.Int(6)))))",
            ],
            ["int 3", "pt.Int(3)"],
            ["int 4", "pt.Int(4)"],
            [
                "||",
                "pt.Or(pt.Int(3), pt.Int(4), pt.Or(pt.And(pt.Int(5), pt.Int(6))))",
            ],
            ["int 5", "pt.Int(5)"],
            ["int 6", "pt.Int(6)"],
            ["&&", "pt.And(pt.Int(5), pt.Int(6))"],
            [
                "||",
                "pt.Or(pt.Int(3), pt.Int(4), pt.Or(pt.And(pt.Int(5), pt.Int(6))))",
            ],
            [
                "&&",
                "pt.And(pt.Int(1), pt.Int(2), pt.Or(pt.Int(3), pt.Int(4), pt.Or(pt.And(pt.Int(5), pt.Int(6)))))",
            ],
            ["return", C],
        ],
    ),
    (  # 8: Btoi BytesAnd
        lambda pt: pt.Btoi(
            pt.BytesAnd(pt.Bytes("base16", "0xBEEF"), pt.Bytes("base16", "0x1337"))
        ),
        [
            [P, C],
            ["byte 0xBEEF", "pt.Bytes('base16', '0xBEEF')"],
            ["byte 0x1337", "pt.Bytes('base16', '0x1337')"],
            [
                "b&",
                "pt.BytesAnd(pt.Bytes('base16', '0xBEEF'), pt.Bytes('base16', '0x1337'))",
            ],
            [
                "btoi",
                "pt.Btoi(pt.BytesAnd(pt.Bytes('base16', '0xBEEF'), pt.Bytes('base16', '0x1337')))",
            ],
            ["return", C],
        ],
        4,
    ),
    (  # 9: Btoi BytesZero
        lambda pt: pt.Btoi(pt.BytesZero(pt.Int(4))),
        [
            [P, C],
            ["int 4", "pt.Int(4)"],
            ["bzero", "pt.BytesZero(pt.Int(4))"],
            ["btoi", "pt.Btoi(pt.BytesZero(pt.Int(4)))"],
            ["return", C],
        ],
        4,
    ),
    (  # 10: BytesNot
        lambda pt: pt.Btoi(pt.BytesNot(pt.Bytes("base16", "0xFF00"))),
        [
            [P, C],
            ["byte 0xFF00", "pt.Bytes('base16', '0xFF00')"],
            ["b~", "pt.BytesNot(pt.Bytes('base16', '0xFF00'))"],
            ["btoi", "pt.Btoi(pt.BytesNot(pt.Bytes('base16', '0xFF00')))"],
            ["return", C],
        ],
        4,
    ),
    (  # 11: Get/SetBit
        lambda pt: pt.Seq(
            pt.Pop(pt.SetBit(pt.Bytes("base16", "0x00"), pt.Int(3), pt.Int(1))),
            pt.GetBit(pt.Int(16), pt.Int(64)),
        ),
        [
            [P, C],
            ("byte 0x00", "pt.Bytes('base16', '0x00')"),
            ("int 3", "pt.Int(3)"),
            ("int 1", "pt.Int(1)"),
            (
                "setbit",
                "pt.SetBit(pt.Bytes('base16', '0x00'), pt.Int(3), pt.Int(1))",
            ),
            (
                "pop",
                "pt.Pop(pt.SetBit(pt.Bytes('base16', '0x00'), pt.Int(3), pt.Int(1)))",
            ),
            ("int 16", "pt.Int(16)"),
            ("int 64", "pt.Int(64)"),
            ("getbit", "pt.GetBit(pt.Int(16), pt.Int(64))"),
            ("return", C),
        ],
        3,
    ),
    (  # 12: Get/SetByte
        lambda pt: pt.Seq(
            pt.Pop(pt.SetByte(pt.Bytes("base16", "0xff00"), pt.Int(0), pt.Int(0))),
            pt.GetByte(pt.Bytes("abc"), pt.Int(2)),
        ),
        [
            [P, C],
            ("byte 0xff00", "pt.Bytes('base16', '0xff00')"),
            ("int 0", "pt.Int(0)"),
            ("int 0", "pt.Int(0)"),
            (
                "setbyte",
                "pt.SetByte(pt.Bytes('base16', '0xff00'), pt.Int(0), pt.Int(0))",
            ),
            (
                "pop",
                "pt.Pop(pt.SetByte(pt.Bytes('base16', '0xff00'), pt.Int(0), pt.Int(0)))",
            ),
            ('byte "abc"', "pt.Bytes('abc')"),
            ("int 2", "pt.Int(2)"),
            ("getbyte", "pt.GetByte(pt.Bytes('abc'), pt.Int(2))"),
            ("return", C),
        ],
        3,
    ),
    (  # 13: Concat
        lambda pt: pt.Btoi(pt.Concat(pt.Bytes("a"), pt.Bytes("b"), pt.Bytes("c"))),
        [
            [P, C],
            ('byte "a"', "pt.Bytes('a')"),
            ('byte "b"', "pt.Bytes('b')"),
            ("concat", "pt.Concat(pt.Bytes('a'), pt.Bytes('b'), pt.Bytes('c'))"),
            ('byte "c"', "pt.Bytes('c')"),
            ("concat", "pt.Concat(pt.Bytes('a'), pt.Bytes('b'), pt.Bytes('c'))"),
            (
                "btoi",
                "pt.Btoi(pt.Concat(pt.Bytes('a'), pt.Bytes('b'), pt.Bytes('c')))",
            ),
            ("return", C),
        ],
    ),
    (  # 14: Substring
        lambda pt: pt.Btoi(pt.Substring(pt.Bytes("algorand"), pt.Int(2), pt.Int(8))),
        [
            [P, C],
            ('byte "algorand"', "pt.Bytes('algorand')"),
            (
                "extract 2 6",
                "pt.Substring(pt.Bytes('algorand'), pt.Int(2), pt.Int(8))",
            ),
            (
                "btoi",
                "pt.Btoi(pt.Substring(pt.Bytes('algorand'), pt.Int(2), pt.Int(8)))",
            ),
            (
                "return",
                C,
            ),
        ],
        5,
    ),
    (  # 15: Extract
        lambda pt: pt.Btoi(pt.Extract(pt.Bytes("algorand"), pt.Int(2), pt.Int(6))),
        [
            [P, C],
            ('byte "algorand"', "pt.Bytes('algorand')"),
            (
                "extract 2 6",
                "pt.Extract(pt.Bytes('algorand'), pt.Int(2), pt.Int(6))",
            ),
            (
                "btoi",
                "pt.Btoi(pt.Extract(pt.Bytes('algorand'), pt.Int(2), pt.Int(6)))",
            ),
            ("return", C),
        ],
        5,
    ),
    (  # 16: Txn
        lambda pt: pt.And(
            pt.Txn.type_enum() == pt.TxnType.Payment,
            pt.Txn.fee() < pt.Int(100),
            pt.Txn.first_valid() % pt.Int(50) == pt.Int(0),
            pt.Txn.last_valid() == pt.Int(5000) + pt.Txn.first_valid(),
            pt.Txn.lease() == pt.Bytes("base64", "023sdDE2"),
        ),
        [
            [P, C],
            ("txn TypeEnum", "pt.Txn.type_enum()"),
            ("int pay", "pt.Txn.type_enum() == pt.TxnType.Payment"),
            ("==", "pt.Txn.type_enum() == pt.TxnType.Payment"),
            ("txn Fee", "pt.Txn.fee()"),
            ("int 100", "pt.Int(100)"),
            ("<", "pt.Txn.fee() < pt.Int(100)"),
            (
                "&&",
                "pt.And(pt.Txn.type_enum() == pt.TxnType.Payment, pt.Txn.fee() < pt.Int(100), pt.Txn.first_valid() % pt.Int(50) == pt.Int(0), pt.Txn.last_valid() == pt.Int(5000) + pt.Txn.first_valid(), pt.Txn.lease() == pt.Bytes('base64', '023sdDE2'))",
            ),
            ("txn FirstValid", "pt.Txn.first_valid()"),
            ("int 50", "pt.Int(50)"),
            ("%", "pt.Txn.first_valid() % pt.Int(50)"),
            ("int 0", "pt.Int(0)"),
            ("==", "pt.Txn.first_valid() % pt.Int(50) == pt.Int(0)"),
            (
                "&&",
                "pt.And(pt.Txn.type_enum() == pt.TxnType.Payment, pt.Txn.fee() < pt.Int(100), pt.Txn.first_valid() % pt.Int(50) == pt.Int(0), pt.Txn.last_valid() == pt.Int(5000) + pt.Txn.first_valid(), pt.Txn.lease() == pt.Bytes('base64', '023sdDE2'))",
            ),
            ("txn LastValid", "pt.Txn.last_valid()"),
            ("int 5000", "pt.Int(5000)"),
            ("txn FirstValid", "pt.Txn.first_valid()"),
            ("+", "pt.Int(5000) + pt.Txn.first_valid()"),
            ("==", "pt.Txn.last_valid() == pt.Int(5000) + pt.Txn.first_valid()"),
            (
                "&&",
                "pt.And(pt.Txn.type_enum() == pt.TxnType.Payment, pt.Txn.fee() < pt.Int(100), pt.Txn.first_valid() % pt.Int(50) == pt.Int(0), pt.Txn.last_valid() == pt.Int(5000) + pt.Txn.first_valid(), pt.Txn.lease() == pt.Bytes('base64', '023sdDE2'))",
            ),
            ("txn Lease", "pt.Txn.lease()"),
            ("byte base64(023sdDE2)", "pt.Bytes('base64', '023sdDE2')"),
            ("==", "pt.Txn.lease() == pt.Bytes('base64', '023sdDE2')"),
            (
                "&&",
                "pt.And(pt.Txn.type_enum() == pt.TxnType.Payment, pt.Txn.fee() < pt.Int(100), pt.Txn.first_valid() % pt.Int(50) == pt.Int(0), pt.Txn.last_valid() == pt.Int(5000) + pt.Txn.first_valid(), pt.Txn.lease() == pt.Bytes('base64', '023sdDE2'))",
            ),
            ("return", C),
        ],
    ),
    (  # 17: Cond
        lambda pt: [
            is_admin := pt.App.localGet(pt.Int(0), pt.Bytes("admin")),
            foo := pt.Return(pt.Int(1)),
            pt.Cond(
                [pt.Txn.application_id() == pt.Int(0), foo],
                [
                    pt.Txn.on_completion() == pt.OnComplete.DeleteApplication,
                    pt.Return(is_admin),
                ],
                [
                    pt.Txn.on_completion() == pt.OnComplete.UpdateApplication,
                    pt.Return(is_admin),
                ],
                [pt.Txn.on_completion() == pt.OnComplete.CloseOut, foo],
                [pt.Txn.on_completion() == pt.OnComplete.OptIn, foo],
                [pt.Txn.application_args[0] == pt.Bytes("set admin"), foo],
                [pt.Txn.application_args[0] == pt.Bytes("mint"), foo],
                [pt.Txn.application_args[0] == pt.Bytes("transfer"), foo],
                [pt.Txn.accounts[4] == pt.Bytes("foo"), foo],
            ),
        ][-1],
        [
            [P, C],
            ("txn ApplicationID", "pt.Txn.application_id()"),
            ("int 0", "pt.Int(0)"),
            ("==", "pt.Txn.application_id() == pt.Int(0)"),
            ("bnz main_l18", "pt.Txn.application_id() == pt.Int(0)"),
            ("txn OnCompletion", "pt.Txn.on_completion()"),
            (
                "int DeleteApplication",
                "pt.Txn.on_completion() == pt.OnComplete.DeleteApplication",
            ),  # source inferencing at work here!!!!
            ("==", "pt.Txn.on_completion() == pt.OnComplete.DeleteApplication"),
            (
                "bnz main_l17",
                "pt.Txn.on_completion() == pt.OnComplete.DeleteApplication",
            ),
            ("txn OnCompletion", "pt.Txn.on_completion()"),
            (
                "int UpdateApplication",
                "pt.Txn.on_completion() == pt.OnComplete.UpdateApplication",
            ),  # source inferencing
            ("==", "pt.Txn.on_completion() == pt.OnComplete.UpdateApplication"),
            (
                "bnz main_l16",
                "pt.Txn.on_completion() == pt.OnComplete.UpdateApplication",
            ),  # yep
            ("txn OnCompletion", "pt.Txn.on_completion()"),
            ("int CloseOut", "pt.Txn.on_completion() == pt.OnComplete.CloseOut"),
            ("==", "pt.Txn.on_completion() == pt.OnComplete.CloseOut"),
            ("bnz main_l15", "pt.Txn.on_completion() == pt.OnComplete.CloseOut"),
            ("txn OnCompletion", "pt.Txn.on_completion()"),
            ("int OptIn", "pt.Txn.on_completion() == pt.OnComplete.OptIn"),
            ("==", "pt.Txn.on_completion() == pt.OnComplete.OptIn"),
            ("bnz main_l14", "pt.Txn.on_completion() == pt.OnComplete.OptIn"),
            ("txna ApplicationArgs 0", "pt.Txn.application_args[0]"),
            ('byte "set admin"', "pt.Bytes('set admin')"),
            ("==", "pt.Txn.application_args[0] == pt.Bytes('set admin')"),
            ("bnz main_l13", "pt.Txn.application_args[0] == pt.Bytes('set admin')"),
            ("txna ApplicationArgs 0", "pt.Txn.application_args[0]"),
            ('byte "mint"', "pt.Bytes('mint')"),
            ("==", "pt.Txn.application_args[0] == pt.Bytes('mint')"),
            ("bnz main_l12", "pt.Txn.application_args[0] == pt.Bytes('mint')"),
            ("txna ApplicationArgs 0", "pt.Txn.application_args[0]"),
            ('byte "transfer"', "pt.Bytes('transfer')"),
            ("==", "pt.Txn.application_args[0] == pt.Bytes('transfer')"),
            ("bnz main_l11", "pt.Txn.application_args[0] == pt.Bytes('transfer')"),
            ("txna Accounts 4", "pt.Txn.accounts[4]"),
            ('byte "foo"', "pt.Bytes('foo')"),
            ("==", "pt.Txn.accounts[4] == pt.Bytes('foo')"),
            ("bnz main_l10", "pt.Txn.accounts[4] == pt.Bytes('foo')"),
            ("err", BIG_C),
            ("main_l10:", "pt.Txn.accounts[4] == pt.Bytes('foo')"),
            ("int 1", "pt.Int(1)"),
            ("return", "pt.Return(pt.Int(1))"),
            ("main_l11:", "pt.Txn.application_args[0] == pt.Bytes('transfer')"),
            ("int 1", "pt.Int(1)"),
            ("return", "pt.Return(pt.Int(1))"),
            ("main_l12:", "pt.Txn.application_args[0] == pt.Bytes('mint')"),
            ("int 1", "pt.Int(1)"),
            ("return", "pt.Return(pt.Int(1))"),
            ("main_l13:", "pt.Txn.application_args[0] == pt.Bytes('set admin')"),
            ("int 1", "pt.Int(1)"),
            ("return", "pt.Return(pt.Int(1))"),
            ("main_l14:", "pt.Txn.on_completion() == pt.OnComplete.OptIn"),
            ("int 1", "pt.Int(1)"),
            ("return", "pt.Return(pt.Int(1))"),
            ("main_l15:", "pt.Txn.on_completion() == pt.OnComplete.CloseOut"),
            ("int 1", "pt.Int(1)"),
            ("return", "pt.Return(pt.Int(1))"),
            ("main_l16:", "pt.Txn.on_completion() == pt.OnComplete.UpdateApplication"),
            ("int 0", "pt.Int(0)"),
            ('byte "admin"', "pt.Bytes('admin')"),
            ("app_local_get", "pt.App.localGet(pt.Int(0), pt.Bytes('admin'))"),
            ("return", "pt.Return(is_admin)"),
            ("main_l17:", "pt.Txn.on_completion() == pt.OnComplete.DeleteApplication"),
            ("int 0", "pt.Int(0)"),
            ('byte "admin"', "pt.Bytes('admin')"),
            ("app_local_get", "pt.App.localGet(pt.Int(0), pt.Bytes('admin'))"),
            ("return", "pt.Return(is_admin)"),
            ("main_l18:", "pt.Txn.application_id() == pt.Int(0)"),
            ("int 1", "pt.Int(1)"),
            ("return", "pt.Return(pt.Int(1))"),
        ],
        2,
        "Application",
    ),
    (  # 18: Tmpl Gtxn TxnType
        lambda pt: [
            asset_c := pt.Tmpl.Int("TMPL_ASSET_C"),
            receiver := pt.Tmpl.Addr("TMPL_RECEIVER"),
            pt.And(
                pt.Gtxn[0].rekey_to() == pt.Global.zero_address(),
                pt.Gtxn[1].rekey_to() == pt.Global.zero_address(),
                pt.Gtxn[2].rekey_to() == pt.Global.zero_address(),
                pt.Gtxn[3].rekey_to() == pt.Global.zero_address(),
                pt.Gtxn[4].rekey_to() == pt.Global.zero_address(),
                pt.Gtxn[0].last_valid() == pt.Gtxn[1].last_valid(),
                pt.Gtxn[1].last_valid() == pt.Gtxn[2].last_valid(),
                pt.Gtxn[2].last_valid() == pt.Gtxn[3].last_valid(),
                pt.Gtxn[3].last_valid() == pt.Gtxn[4].last_valid(),
                pt.Gtxn[0].type_enum() == pt.TxnType.AssetTransfer,
                pt.Gtxn[0].xfer_asset() == asset_c,
                pt.Gtxn[0].receiver() == receiver,
            ),
        ][-1],
        [
            [P, C],
            ("gtxn 0 RekeyTo", "pt.Gtxn[0].rekey_to()"),
            ("global ZeroAddress", "pt.Global.zero_address()"),
            ("==", "pt.Gtxn[0].rekey_to() == pt.Global.zero_address()"),
            ("gtxn 1 RekeyTo", "pt.Gtxn[1].rekey_to()"),
            ("global ZeroAddress", "pt.Global.zero_address()"),
            ("==", "pt.Gtxn[1].rekey_to() == pt.Global.zero_address()"),
            ("&&", BIG_A),
            ("gtxn 2 RekeyTo", "pt.Gtxn[2].rekey_to()"),
            ("global ZeroAddress", "pt.Global.zero_address()"),
            ("==", "pt.Gtxn[2].rekey_to() == pt.Global.zero_address()"),
            ("&&", BIG_A),
            ("gtxn 3 RekeyTo", "pt.Gtxn[3].rekey_to()"),
            ("global ZeroAddress", "pt.Global.zero_address()"),
            ("==", "pt.Gtxn[3].rekey_to() == pt.Global.zero_address()"),
            ("&&", BIG_A),
            ("gtxn 4 RekeyTo", "pt.Gtxn[4].rekey_to()"),
            ("global ZeroAddress", "pt.Global.zero_address()"),
            ("==", "pt.Gtxn[4].rekey_to() == pt.Global.zero_address()"),
            ("&&", BIG_A),
            ("gtxn 0 LastValid", "pt.Gtxn[0].last_valid()"),
            ("gtxn 1 LastValid", "pt.Gtxn[1].last_valid()"),
            ("==", "pt.Gtxn[0].last_valid() == pt.Gtxn[1].last_valid()"),
            ("&&", BIG_A),
            ("gtxn 1 LastValid", "pt.Gtxn[1].last_valid()"),
            ("gtxn 2 LastValid", "pt.Gtxn[2].last_valid()"),
            ("==", "pt.Gtxn[1].last_valid() == pt.Gtxn[2].last_valid()"),
            ("&&", BIG_A),
            ("gtxn 2 LastValid", "pt.Gtxn[2].last_valid()"),
            ("gtxn 3 LastValid", "pt.Gtxn[3].last_valid()"),
            ("==", "pt.Gtxn[2].last_valid() == pt.Gtxn[3].last_valid()"),
            ("&&", BIG_A),
            ("gtxn 3 LastValid", "pt.Gtxn[3].last_valid()"),
            ("gtxn 4 LastValid", "pt.Gtxn[4].last_valid()"),
            ("==", "pt.Gtxn[3].last_valid() == pt.Gtxn[4].last_valid()"),
            ("&&", BIG_A),
            ("gtxn 0 TypeEnum", "pt.Gtxn[0].type_enum()"),
            (
                "int axfer",
                "pt.Gtxn[0].type_enum() == pt.TxnType.AssetTransfer",
            ),  # source inference
            ("==", "pt.Gtxn[0].type_enum() == pt.TxnType.AssetTransfer"),
            ("&&", BIG_A),
            ("gtxn 0 XferAsset", "pt.Gtxn[0].xfer_asset()"),
            ("int TMPL_ASSET_C", "pt.Tmpl.Int('TMPL_ASSET_C')"),
            ("==", "pt.Gtxn[0].xfer_asset() == asset_c"),
            ("&&", BIG_A),
            ("gtxn 0 Receiver", "pt.Gtxn[0].receiver()"),
            ("addr TMPL_RECEIVER", "pt.Tmpl.Addr('TMPL_RECEIVER')"),
            ("==", "pt.Gtxn[0].receiver() == receiver"),
            ("&&", BIG_A),
            ("return", C),
        ],
    ),
    (  # 19: Txn.application_args
        lambda pt: pt.And(
            pt.Txn.application_args.length(),  # get the number of application arguments in the transaction
            # as of AVM v5, PyTeal expressions can be used to dynamically index into array properties as well
            pt.Btoi(
                pt.Txn.application_args[pt.Txn.application_args.length() - pt.Int(1)]
            ),
        ),
        [
            [P, C],
            ("txn NumAppArgs", "pt.Txn.application_args.length()"),
            ("txn NumAppArgs", "pt.Txn.application_args.length()"),
            ("int 1", "pt.Int(1)"),
            ("-", "pt.Txn.application_args.length() - pt.Int(1)"),
            (
                "txnas ApplicationArgs",
                "pt.Txn.application_args[pt.Txn.application_args.length() - pt.Int(1)]",
            ),
            (
                "btoi",
                "pt.Btoi(pt.Txn.application_args[pt.Txn.application_args.length() - pt.Int(1)])",
            ),
            (
                "&&",
                "pt.And(pt.Txn.application_args.length(), pt.Btoi(pt.Txn.application_args[pt.Txn.application_args.length() - pt.Int(1)]))",
            ),
            ("return", C),
        ],
        5,
    ),
    (  # 20: App
        lambda pt: pt.Seq(
            receiver_max_balance := pt.App.localGetEx(  # noqa: F841
                pt.Int(1), pt.App.id(), pt.Bytes("max balance")
            ),
            pt.Or(
                pt.App.globalGet(pt.Bytes("paused")),
                pt.App.localGet(pt.Int(0), pt.Bytes("frozen")),
                pt.App.localGet(pt.Int(1), pt.Bytes("frozen")),
                pt.App.localGet(pt.Int(0), pt.Bytes("lock until"))
                >= pt.Global.latest_timestamp(),
                pt.App.localGet(pt.Int(1), pt.Bytes("lock until"))
                >= pt.Global.latest_timestamp(),
                pt.App.globalGet(
                    pt.Concat(
                        pt.Bytes("rule"),
                        pt.Itob(pt.App.localGet(pt.Int(0), pt.Bytes("transfer group"))),
                        pt.Itob(pt.App.localGet(pt.Int(1), pt.Bytes("transfer group"))),
                    )
                ),
            ),
        ),
        [
            [P, C],
            ("int 1", "pt.Int(1)"),
            ("global CurrentApplicationID", "pt.App.id()"),
            ('byte "max balance"', "pt.Bytes('max balance')"),
            (
                "app_local_get_ex",
                "pt.App.localGetEx(pt.Int(1), pt.App.id(), pt.Bytes('max balance'))",
            ),
            (
                "store 1",
                "pt.App.localGetEx(pt.Int(1), pt.App.id(), pt.Bytes('max balance'))",
            ),
            (
                "store 0",
                "pt.App.localGetEx(pt.Int(1), pt.App.id(), pt.Bytes('max balance'))",
            ),
            ('byte "paused"', "pt.Bytes('paused')"),
            ("app_global_get", "pt.App.globalGet(pt.Bytes('paused'))"),
            ("int 0", "pt.Int(0)"),
            ('byte "frozen"', "pt.Bytes('frozen')"),
            ("app_local_get", "pt.App.localGet(pt.Int(0), pt.Bytes('frozen'))"),
            ("||", BIG_OR),
            ("int 1", "pt.Int(1)"),
            ('byte "frozen"', "pt.Bytes('frozen')"),
            ("app_local_get", "pt.App.localGet(pt.Int(1), pt.Bytes('frozen'))"),
            ("||", BIG_OR),
            ("int 0", "pt.Int(0)"),
            ('byte "lock until"', "pt.Bytes('lock until')"),
            ("app_local_get", "pt.App.localGet(pt.Int(0), pt.Bytes('lock until'))"),
            ("global LatestTimestamp", "pt.Global.latest_timestamp()"),
            (
                ">=",
                "pt.App.localGet(pt.Int(0), pt.Bytes('lock until')) >= pt.Global.latest_timestamp()",
            ),
            ("||", BIG_OR),
            ("int 1", "pt.Int(1)"),
            ('byte "lock until"', "pt.Bytes('lock until')"),
            ("app_local_get", "pt.App.localGet(pt.Int(1), pt.Bytes('lock until'))"),
            ("global LatestTimestamp", "pt.Global.latest_timestamp()"),
            (
                ">=",
                "pt.App.localGet(pt.Int(1), pt.Bytes('lock until')) >= pt.Global.latest_timestamp()",
            ),
            ("||", BIG_OR),
            ('byte "rule"', "pt.Bytes('rule')"),
            ("int 0", "pt.Int(0)"),
            ('byte "transfer group"', "pt.Bytes('transfer group')"),
            (
                "app_local_get",
                "pt.App.localGet(pt.Int(0), pt.Bytes('transfer group'))",
            ),
            (
                "itob",
                "pt.Itob(pt.App.localGet(pt.Int(0), pt.Bytes('transfer group')))",
            ),
            (
                "concat",
                "pt.Concat(pt.Bytes('rule'), pt.Itob(pt.App.localGet(pt.Int(0), pt.Bytes('transfer group'))), pt.Itob(pt.App.localGet(pt.Int(1), pt.Bytes('transfer group'))))",
            ),
            ("int 1", "pt.Int(1)"),
            ('byte "transfer group"', "pt.Bytes('transfer group')"),
            (
                "app_local_get",
                "pt.App.localGet(pt.Int(1), pt.Bytes('transfer group'))",
            ),
            ("itob", "pt.Itob(pt.App.localGet(pt.Int(1), pt.Bytes('transfer group')))"),
            (
                "concat",
                "pt.Concat(pt.Bytes('rule'), pt.Itob(pt.App.localGet(pt.Int(0), pt.Bytes('transfer group'))), pt.Itob(pt.App.localGet(pt.Int(1), pt.Bytes('transfer group'))))",
            ),
            (
                "app_global_get",
                "pt.App.globalGet(pt.Concat(pt.Bytes('rule'), pt.Itob(pt.App.localGet(pt.Int(0), pt.Bytes('transfer group'))), pt.Itob(pt.App.localGet(pt.Int(1), pt.Bytes('transfer group')))))",
            ),
            ("||", BIG_OR),
            ("return", C),
        ],
        2,
        "Application",
    ),
    (  # 21: EcdsaCurve Sha512_256
        lambda pt: pt.EcdsaVerify(
            pt.EcdsaCurve.Secp256k1,
            pt.Sha512_256(pt.Bytes("testdata")),
            pt.Bytes(
                "base16",
                "33602297203d2753372cea7794ffe1756a278cbc4907b15a0dd132c9fb82555e",
            ),
            pt.Bytes(
                "base16",
                "20f112126cf3e2eac6e8d4f97a403d21bab07b8dbb77154511bb7b07c0173195",
            ),
            (
                pt.Bytes(
                    "base16",
                    "d6143a58c90c06b594e4414cb788659c2805e0056b1dfceea32c03f59efec517",
                ),
                pt.Bytes(
                    "base16",
                    "00bd2400c479efe5ea556f37e1dc11ccb20f1e642dbfe00ca346fffeae508298",
                ),
            ),
        ),
        [
            [P, C],
            ['byte "testdata"', "pt.Bytes('testdata')"],
            ["sha512_256", "pt.Sha512_256(pt.Bytes('testdata'))"],
            [
                "byte 0x33602297203d2753372cea7794ffe1756a278cbc4907b15a0dd132c9fb82555e",
                "pt.Bytes('base16', '33602297203d2753372cea7794ffe1756a278cbc4907b15a0dd132c9fb82555e')",
            ],
            [
                "byte 0x20f112126cf3e2eac6e8d4f97a403d21bab07b8dbb77154511bb7b07c0173195",
                "pt.Bytes('base16', '20f112126cf3e2eac6e8d4f97a403d21bab07b8dbb77154511bb7b07c0173195')",
            ],
            [
                "byte 0xd6143a58c90c06b594e4414cb788659c2805e0056b1dfceea32c03f59efec517",
                "pt.Bytes('base16', 'd6143a58c90c06b594e4414cb788659c2805e0056b1dfceea32c03f59efec517')",
            ],
            [
                "byte 0x00bd2400c479efe5ea556f37e1dc11ccb20f1e642dbfe00ca346fffeae508298",
                "pt.Bytes('base16', '00bd2400c479efe5ea556f37e1dc11ccb20f1e642dbfe00ca346fffeae508298')",
            ],
            [
                "ecdsa_verify Secp256k1",
                "pt.EcdsaVerify(pt.EcdsaCurve.Secp256k1, pt.Sha512_256(pt.Bytes('testdata')), pt.Bytes('base16', '33602297203d2753372cea7794ffe1756a278cbc4907b15a0dd132c9fb82555e'), pt.Bytes('base16', '20f112126cf3e2eac6e8d4f97a403d21bab07b8dbb77154511bb7b07c0173195'), (pt.Bytes('base16', 'd6143a58c90c06b594e4414cb788659c2805e0056b1dfceea32c03f59efec517'), pt.Bytes('base16', '00bd2400c479efe5ea556f37e1dc11ccb20f1e642dbfe00ca346fffeae508298')))",
            ],
            ["return", C],
        ],
        5,
    ),
    (  # 22: ScratchVar (simple Assert )
        lambda pt: [
            myvar := pt.ScratchVar(
                pt.TealType.uint64
            ),  # assign a scratch slot in any available slot
            anotherVar := pt.ScratchVar(
                pt.TealType.bytes, 4
            ),  # assign this scratch slot to slot #4
            pt.Seq(
                [
                    myvar.store(pt.Int(5)),
                    anotherVar.store(pt.Bytes("hello")),
                    pt.Assert(myvar.load() == pt.Int(5)),
                    pt.Return(pt.Int(1)),
                ]
            ),
        ][-1],
        [
            [P, C],
            ["int 5", "pt.Int(5)"],
            ["store 0", "myvar.store(pt.Int(5))"],
            ['byte "hello"', "pt.Bytes('hello')"],
            ["store 4", "anotherVar.store(pt.Bytes('hello'))"],
            ["load 0", "myvar.load()"],
            ["int 5", "pt.Int(5)"],
            ["==", "myvar.load() == pt.Int(5)"],
            ["assert", "pt.Assert(myvar.load() == pt.Int(5))"],
            ["int 1", "pt.Int(1)"],
            ["return", "pt.Return(pt.Int(1))"],
        ],
        3,
    ),
    (  # 23: DynamicScratchVar
        lambda pt: [
            s := pt.ScratchVar(pt.TealType.uint64),
            d := pt.DynamicScratchVar(pt.TealType.uint64),
            pt.Seq(
                d.set_index(s),
                s.store(pt.Int(7)),
                d.store(d.load() + pt.Int(3)),
                pt.Assert(s.load() == pt.Int(10)),
                pt.Int(1),
            ),
        ][-1],
        [
            [P, C],
            ["int 0", "d.set_index(s)"],
            ["store 1", "d.set_index(s)"],
            ["int 7", "pt.Int(7)"],
            ["store 0", "s.store(pt.Int(7))"],
            ["load 1", "d.store(d.load() + pt.Int(3))"],
            ["load 1", "d.load()"],
            ["loads", "d.load()"],
            ["int 3", "pt.Int(3)"],
            ["+", "d.load() + pt.Int(3)"],
            ["stores", "d.store(d.load() + pt.Int(3))"],
            ["load 0", "s.load()"],
            ["int 10", "pt.Int(10)"],
            ["==", "s.load() == pt.Int(10)"],
            ["assert", "pt.Assert(s.load() == pt.Int(10))"],
            ["int 1", "pt.Int(1)"],
            ["return", C],
        ],
        5,
    ),
    (  # 24: If/Then/Else ImportScratchVaplue
        lambda pt: [  # App is called at transaction index 0
            greeting := pt.ScratchVar(
                pt.TealType.bytes, 20
            ),  # this variable will live in scratch slot 20
            app1_seq := pt.Seq(
                [
                    pt.If(pt.Txn.sender() == pt.App.globalGet(pt.Bytes("creator")))
                    .Then(greeting.store(pt.Bytes("hi creator!")))
                    .Else(greeting.store(pt.Bytes("hi user!"))),
                    pt.Int(1),
                ]
            ),
            greetingFromPreviousApp := pt.ImportScratchValue(
                0, 20
            ),  # loading scratch slot 20 from the transaction at index 0
            app2_seq := pt.Seq(
                [
                    # not shown: make sure that the transaction at index 0 is an app call to App A
                    pt.App.globalPut(
                        pt.Bytes("greeting from prev app"), greetingFromPreviousApp
                    ),
                    pt.Int(1),
                ]
            ),
            pt.And(app1_seq, app2_seq),
        ][-1],
        [
            [P, C],
            ["txn Sender", "pt.Txn.sender()"],
            ['byte "creator"', "pt.Bytes('creator')"],
            ["app_global_get", "pt.App.globalGet(pt.Bytes('creator'))"],
            ["==", "pt.Txn.sender() == pt.App.globalGet(pt.Bytes('creator'))"],
            [
                "bnz main_l2",
                "pt.If(pt.Txn.sender() == pt.App.globalGet(pt.Bytes('creator')))",
            ],
            ['byte "hi user!"', "pt.Bytes('hi user!')"],
            ["store 20", "greeting.store(pt.Bytes('hi user!'))"],
            [
                "b main_l3",
                "pt.If(pt.Txn.sender() == pt.App.globalGet(pt.Bytes('creator')))",
            ],
            [
                "main_l2:",
                "pt.If(pt.Txn.sender() == pt.App.globalGet(pt.Bytes('creator')))",
            ],
            ['byte "hi creator!"', "pt.Bytes('hi creator!')"],
            ["store 20", "greeting.store(pt.Bytes('hi creator!'))"],
            [
                "main_l3:",
                "pt.If(pt.Txn.sender() == pt.App.globalGet(pt.Bytes('creator')))",
            ],  # pt.If(...) etc. sent us over here
            ["int 1", "pt.Int(1)"],
            ['byte "greeting from prev app"', "pt.Bytes('greeting from prev app')"],
            ["gload 0 20", "pt.ImportScratchValue(0, 20)"],
            [
                "app_global_put",
                "pt.App.globalPut(pt.Bytes('greeting from prev app'), greetingFromPreviousApp)",
            ],
            ["int 1", "pt.Int(1)"],
            ["&&", "pt.And(app1_seq, app2_seq)"],
            ["return", C],
        ],
        4,
        "Application",
    ),
    (  # 25: If/Then/ElseIf/ElseIf/Else
        lambda pt: [
            arg := pt.Btoi(pt.Arg(1)),
            pt.If(arg == pt.Int(0))
            .Then(pt.Reject())
            .ElseIf(arg == pt.Int(1))
            .Then(pt.Reject())
            .ElseIf(arg == pt.Int(2))
            .Then(pt.Approve())
            .Else(pt.Reject()),
        ][-1],
        [
            [P, C],
            ("arg 1", "pt.Arg(1)"),
            ("btoi", "pt.Btoi(pt.Arg(1))"),
            ("int 0", "pt.Int(0)"),
            ("==", "arg == pt.Int(0)"),
            ("bnz main_l6", "pt.If(arg == pt.Int(0))"),
            ("arg 1", "pt.Arg(1)"),
            ("btoi", "pt.Btoi(pt.Arg(1))"),
            ("int 1", "pt.Int(1)"),
            ("==", "arg == pt.Int(1)"),
            ("bnz main_l5", "arg == pt.Int(1)"),
            ("arg 1", "pt.Arg(1)"),
            ("btoi", "pt.Btoi(pt.Arg(1))"),
            ("int 2", "pt.Int(2)"),
            ("==", "arg == pt.Int(2)"),
            ("bnz main_l4", "arg == pt.Int(2)"),
            ("int 0", "pt.Reject()"),
            ("return", "pt.Reject()"),
            ("main_l4:", "arg == pt.Int(2)"),
            ("int 1", "pt.Approve()"),
            ("return", "pt.Approve()"),
            ("main_l5:", "arg == pt.Int(1)"),
            ("int 0", "pt.Reject()"),
            ("return", "pt.Reject()"),
            ("main_l6:", "pt.If(arg == pt.Int(0))"),
            ("int 0", "pt.Reject()"),
            ("return", "pt.Reject()"),
        ],
        2,
        "Signature",
    ),
    (  # 26: While/Do
        lambda pt: [
            totalFees := pt.ScratchVar(pt.TealType.uint64),
            i := pt.ScratchVar(pt.TealType.uint64),
            pt.Seq(
                i.store(pt.Int(0)),
                totalFees.store(pt.Int(0)),
                pt.While(i.load() < pt.Global.group_size()).Do(
                    totalFees.store(totalFees.load() + pt.Gtxn[i.load()].fee()),
                    i.store(i.load() + pt.Int(1)),
                ),
                pt.Approve(),
            ),
        ][-1],
        (
            [P, C],
            ("int 0", "pt.Int(0)"),
            ("store 1", "i.store(pt.Int(0))"),
            ("int 0", "pt.Int(0)"),
            ("store 0", "totalFees.store(pt.Int(0))"),
            ("main_l1:", BIG_W),  # yes, this makes sense to be While(...)
            ("load 1", "i.load()"),
            ("global GroupSize", "pt.Global.group_size()"),
            ("<", "i.load() < pt.Global.group_size()"),
            ("bz main_l3", BIG_W),  # yes, this as well cause we're exiting while
            ("load 0", "totalFees.load()"),
            ("load 1", "i.load()"),
            ("gtxns Fee", "pt.Gtxn[i.load()].fee()"),
            ("+", "totalFees.load() + pt.Gtxn[i.load()].fee()"),
            ("store 0", "totalFees.store(totalFees.load() + pt.Gtxn[i.load()].fee())"),
            ("load 1", "i.load()"),
            ("int 1", "pt.Int(1)"),
            ("+", "i.load() + pt.Int(1)"),
            ("store 1", "i.store(i.load() + pt.Int(1))"),
            ("b main_l1", BIG_W),  # but the only reason for this is While(...)
            ("main_l3:", BIG_W),  # and this exit condition as well for the While(...)
            ("int 1", "pt.Approve()"),
            ("return", "pt.Approve()"),
        ),
        3,
    ),
    (  # 27: For/Do
        lambda pt: [
            totalFees := pt.ScratchVar(pt.TealType.uint64),
            i := pt.ScratchVar(pt.TealType.uint64),
            pt.Seq(
                totalFees.store(pt.Int(0)),
                pt.For(
                    i.store(pt.Int(0)),
                    i.load() < pt.Global.group_size(),
                    i.store(i.load() + pt.Int(1)),
                ).Do(totalFees.store(totalFees.load() + pt.Gtxn[i.load()].fee())),
                pt.Approve(),
            ),
        ][-1],
        [
            [P, C],
            ("int 0", "pt.Int(0)"),
            ("store 0", "totalFees.store(pt.Int(0))"),
            ("int 0", "pt.Int(0)"),
            ("store 1", "i.store(pt.Int(0))"),
            ("main_l1:", BIG_F),
            ("load 1", "i.load()"),
            ("global GroupSize", "pt.Global.group_size()"),
            ("<", "i.load() < pt.Global.group_size()"),
            ("bz main_l3", BIG_F),  # .Do(...) seems a bit more appropriate here
            ("load 0", "totalFees.load()"),
            ("load 1", "i.load()"),
            ("gtxns Fee", "pt.Gtxn[i.load()].fee()"),
            ("+", "totalFees.load() + pt.Gtxn[i.load()].fee()"),
            ("store 0", "totalFees.store(totalFees.load() + pt.Gtxn[i.load()].fee())"),
            ("load 1", "i.load()"),
            ("int 1", "pt.Int(1)"),
            ("+", "i.load() + pt.Int(1)"),
            ("store 1", "i.store(i.load() + pt.Int(1))"),
            ("b main_l1", BIG_F),
            ("main_l3:", BIG_F),
            ("int 1", "pt.Approve()"),
            ("return", "pt.Approve()"),
        ],
        3,
    ),
    (  # 28: For/Do nested with If/Then/ElseIf/Then + Break/Continue
        lambda pt: [
            numPayments := pt.ScratchVar(pt.TealType.uint64),
            i := pt.ScratchVar(pt.TealType.uint64),
            pt.Seq(
                numPayments.store(pt.Int(0)),
                pt.For(
                    i.store(pt.Int(0)),
                    i.load() < pt.Global.group_size(),
                    i.store(i.load() + pt.Int(1)),
                ).Do(
                    pt.If(pt.Gtxn[i.load()].type_enum() != pt.TxnType.Payment)
                    .Then(pt.Continue())
                    .ElseIf(pt.Int(42))
                    .Then(pt.Break()),
                    numPayments.store(numPayments.load() + pt.Int(1)),
                ),
                pt.Approve(),
            ),
        ][-1],
        [
            [P, C],
            ("int 0", "pt.Int(0)"),
            ("store 0", "numPayments.store(pt.Int(0))"),
            ("int 0", "pt.Int(0)"),
            ("store 1", "i.store(pt.Int(0))"),
            (
                "main_l1:",
                "pt.For(i.store(pt.Int(0)), i.load() < pt.Global.group_size(), i.store(i.load() + pt.Int(1)))",
            ),
            ("load 1", "i.load()"),
            ("global GroupSize", "pt.Global.group_size()"),
            ("<", "i.load() < pt.Global.group_size()"),
            (
                "bz main_l6",
                "pt.For(i.store(pt.Int(0)), i.load() < pt.Global.group_size(), i.store(i.load() + pt.Int(1)))",
            ),
            ("load 1", "i.load()"),
            ("gtxns TypeEnum", "pt.Gtxn[i.load()].type_enum()"),
            ("int pay", "pt.Gtxn[i.load()].type_enum() != pt.TxnType.Payment"),
            ("!=", "pt.Gtxn[i.load()].type_enum() != pt.TxnType.Payment"),
            (
                "bnz main_l5",
                "pt.If(pt.Gtxn[i.load()].type_enum() != pt.TxnType.Payment)",  # pt.Continue() is better
            ),
            ("int 42", "pt.Int(42)"),
            (
                "bnz main_l6",
                "pt.If(pt.Gtxn[i.load()].type_enum() != pt.TxnType.Payment).Then(pt.Continue()).ElseIf(pt.Int(42))",  # pt.Break() would be better
            ),
            ("load 0", "numPayments.load()"),
            ("int 1", "pt.Int(1)"),
            ("+", "numPayments.load() + pt.Int(1)"),
            ("store 0", "numPayments.store(numPayments.load() + pt.Int(1))"),
            (
                "main_l5:",
                "pt.For(i.store(pt.Int(0)), i.load() < pt.Global.group_size(), i.store(i.load() + pt.Int(1)))",
            ),
            ("load 1", "i.load()"),
            ("int 1", "pt.Int(1)"),
            ("+", "i.load() + pt.Int(1)"),
            ("store 1", "i.store(i.load() + pt.Int(1))"),
            (
                "b main_l1",
                "pt.For(i.store(pt.Int(0)), i.load() < pt.Global.group_size(), i.store(i.load() + pt.Int(1)))",
            ),
            (
                "main_l6:",
                "pt.For(i.store(pt.Int(0)), i.load() < pt.Global.group_size(), i.store(i.load() + pt.Int(1)))",
            ),
            ("int 1", "pt.Approve()"),
            ("return", "pt.Approve()"),
        ],
        3,
    ),
    (  # 29: For/Do w embedded Cond + Break/Continue
        lambda pt: pt.Seq(
            pt.For(pt.Pop(pt.Int(1)), pt.Int(2), pt.Pop(pt.Int(3))).Do(
                pt.Seq(
                    pt.Cond(
                        [pt.Int(4), pt.Continue()],
                        [pt.Int(5), pt.Break()],
                    ),
                    pt.Pop(pt.Int(6)),
                )
            ),
            pt.Reject(),
        ),
        [
            [P, C],
            ("int 1", "pt.Int(1)"),
            ("pop", "pt.Pop(pt.Int(1))"),
            ("main_l1:", "pt.For(pt.Pop(pt.Int(1)), pt.Int(2), pt.Pop(pt.Int(3)))"),
            ("int 2", "pt.Int(2)"),
            ("bz main_l6", "pt.For(pt.Pop(pt.Int(1)), pt.Int(2), pt.Pop(pt.Int(3)))"),
            ("int 4", "pt.Int(4)"),
            (
                "bnz main_l5",
                "pt.Int(4)",
            ),
            ("int 5", "pt.Int(5)"),
            (
                "bnz main_l6",
                "pt.Int(5)",
            ),
            ("err", "pt.Cond([pt.Int(4), pt.Continue()], [pt.Int(5), pt.Break()])"),
            (
                "main_l5:",
                "pt.For(pt.Pop(pt.Int(1)), pt.Int(2), pt.Pop(pt.Int(3)))",  # Continue would be better
            ),
            ("int 3", "pt.Int(3)"),
            ("pop", "pt.Pop(pt.Int(3))"),
            (
                "b main_l1",
                "pt.For(pt.Pop(pt.Int(1)), pt.Int(2), pt.Pop(pt.Int(3)))",
            ),
            ("main_l6:", "pt.For(pt.Pop(pt.Int(1)), pt.Int(2), pt.Pop(pt.Int(3)))"),
            ("int 0", "pt.Reject()"),
            ("return", "pt.Reject()"),
        ],
    ),
    (  # 30: While/Do w empbedded Cond + Break/Continue
        lambda pt: pt.Seq(
            pt.Pop(pt.Int(0)),
            pt.While(pt.Int(1)).Do(
                pt.Cond(
                    [pt.Int(2), pt.Continue()],
                    [pt.Int(3), pt.Break()],
                    [pt.Int(4), pt.Pop(pt.Int(5))],
                ),
                pt.Pop(pt.Int(6)),
            ),
            pt.Reject(),
        ),
        # This example shows that Continue() and Break() don't receive credit for the labelled targets
        [
            [P, C],
            ("int 0", "pt.Int(0)"),
            ("pop", "pt.Pop(pt.Int(0))"),
            ("main_l1:", "pt.While(pt.Int(1))"),
            ("int 1", "pt.Int(1)"),
            (
                "bz main_l7",
                "pt.While(pt.Int(1))",
            ),  # makes sense as While determines where to branch
            ("int 2", "pt.Int(2)"),
            (
                "bnz main_l1",  # TODO: this could be improved as Continue() ought to get credit here
                "pt.Int(2)",
            ),
            ("int 3", "pt.Int(3)"),
            (
                "bnz main_l7",  # TODO: this could be improved as Break() ought to get credit here
                "pt.Int(3)",
            ),
            ("int 4", "pt.Int(4)"),
            (
                "bnz main_l6",  # makes sense
                "pt.Int(4)",
            ),
            (
                "err",  # makes sense
                "pt.Cond([pt.Int(2), pt.Continue()], [pt.Int(3), pt.Break()], [pt.Int(4), pt.Pop(pt.Int(5))])",
            ),
            (
                "main_l6:",  # makes sense
                "pt.While(pt.Int(1))",
            ),
            ("int 5", "pt.Int(5)"),
            ("pop", "pt.Pop(pt.Int(5))"),
            ("int 6", "pt.Int(6)"),
            ("pop", "pt.Pop(pt.Int(6))"),
            (
                "b main_l1",
                "pt.While(pt.Int(1))",
            ),
            (
                "main_l7:",
                "pt.While(pt.Int(1))",
            ),  # makes sense as this is the exit condition - but it could also have been Break()
            ("int 0", "pt.Reject()"),
            ("return", "pt.Reject()"),
        ],
    ),
    (  # 31: Assert (varargs)
        lambda pt: pt.Seq(
            foo := pt.App.globalGetEx(pt.Txn.applications[0], pt.Bytes("flo")),
            pt.Assert(
                pt.Txn.sender() == pt.App.globalGet(pt.Bytes("alice")),
                pt.App.globalGet(pt.Bytes("bob")) != pt.Int(0),
                pt.App.globalGet(pt.Bytes("chiro")) == pt.Bytes("danillo"),
                pt.Global.latest_timestamp() > pt.App.globalGet(pt.Bytes("enya")),
                foo.hasValue(),
            ),
            pt.Int(42),
        ),
        [
            [P, C],
            ("txna Applications 0", "pt.Txn.applications[0]"),
            ('byte "flo"', "pt.Bytes('flo')"),
            (
                "app_global_get_ex",
                "pt.App.globalGetEx(pt.Txn.applications[0], pt.Bytes('flo'))",
            ),
            ("store 1", "pt.App.globalGetEx(pt.Txn.applications[0], pt.Bytes('flo'))"),
            ("store 0", "pt.App.globalGetEx(pt.Txn.applications[0], pt.Bytes('flo'))"),
            ("txn Sender", "pt.Txn.sender()"),
            ('byte "alice"', "pt.Bytes('alice')"),
            ("app_global_get", "pt.App.globalGet(pt.Bytes('alice'))"),
            ("==", "pt.Txn.sender() == pt.App.globalGet(pt.Bytes('alice'))"),
            ("assert", "pt.Txn.sender() == pt.App.globalGet(pt.Bytes('alice'))"),
            ('byte "bob"', "pt.Bytes('bob')"),
            ("app_global_get", "pt.App.globalGet(pt.Bytes('bob'))"),
            ("int 0", "pt.Int(0)"),
            ("!=", "pt.App.globalGet(pt.Bytes('bob')) != pt.Int(0)"),
            ("assert", "pt.App.globalGet(pt.Bytes('bob')) != pt.Int(0)"),
            ('byte "chiro"', "pt.Bytes('chiro')"),
            ("app_global_get", "pt.App.globalGet(pt.Bytes('chiro'))"),
            ('byte "danillo"', "pt.Bytes('danillo')"),
            ("==", "pt.App.globalGet(pt.Bytes('chiro')) == pt.Bytes('danillo')"),
            ("assert", "pt.App.globalGet(pt.Bytes('chiro')) == pt.Bytes('danillo')"),
            ("global LatestTimestamp", "pt.Global.latest_timestamp()"),
            ('byte "enya"', "pt.Bytes('enya')"),
            ("app_global_get", "pt.App.globalGet(pt.Bytes('enya'))"),
            (">", "pt.Global.latest_timestamp() > pt.App.globalGet(pt.Bytes('enya'))"),
            (
                "assert",
                "pt.Global.latest_timestamp() > pt.App.globalGet(pt.Bytes('enya'))",
            ),
            ("load 1", "foo.hasValue()"),
            ("assert", "foo.hasValue()"),
            ("int 42", "pt.Int(42)"),
            ("return", C),
        ],
        3,
        "Application",
    ),
    (  # 32 - arithmetic
        lambda pt: pt.And(
            pt.Int(1) - pt.Int(2),
            pt.Not(pt.Int(3)),
            pt.Int(4) ^ pt.Int(5),
            ~pt.Int(6),
            pt.BytesEq(pt.Bytes("7"), pt.Bytes("8")),
            pt.GetBit(pt.Int(9), pt.Int(10)),
            pt.SetBit(pt.Int(11), pt.Int(12), pt.Int(13)),
            pt.GetByte(pt.Bytes("14"), pt.Int(15)),
            pt.Btoi(
                pt.Concat(
                    pt.BytesDiv(pt.Bytes("101"), pt.Bytes("102")),
                    pt.BytesNot(pt.Bytes("103")),
                    pt.BytesZero(pt.Int(10)),
                    pt.SetBit(pt.Bytes("105"), pt.Int(106), pt.Int(107)),
                    pt.SetByte(pt.Bytes("108"), pt.Int(109), pt.Int(110)),
                )
            ),
        ),
        [
            [P, C],
            ("int 1", "pt.Int(1)"),
            ("int 2", "pt.Int(2)"),
            ("-", "pt.Int(1) - pt.Int(2)"),
            ("int 3", "pt.Int(3)"),
            ("!", "pt.Not(pt.Int(3))"),
            ("&&", BIG_A2),
            ("int 4", "pt.Int(4)"),
            ("int 5", "pt.Int(5)"),
            ("^", "pt.Int(4) ^ pt.Int(5)"),
            ("&&", BIG_A2),
            ("int 6", "pt.Int(6)"),
            ("~", "~pt.Int(6)"),
            ("&&", BIG_A2),
            ('byte "7"', "pt.Bytes('7')"),
            ('byte "8"', "pt.Bytes('8')"),
            ("b==", "pt.BytesEq(pt.Bytes('7'), pt.Bytes('8'))"),
            ("&&", BIG_A2),
            ("int 9", "pt.Int(9)"),
            ("int 10", "pt.Int(10)"),
            ("getbit", "pt.GetBit(pt.Int(9), pt.Int(10))"),
            ("&&", BIG_A2),
            ("int 11", "pt.Int(11)"),
            ("int 12", "pt.Int(12)"),
            ("int 13", "pt.Int(13)"),
            ("setbit", "pt.SetBit(pt.Int(11), pt.Int(12), pt.Int(13))"),
            ("&&", BIG_A2),
            ('byte "14"', "pt.Bytes('14')"),
            ("int 15", "pt.Int(15)"),
            ("getbyte", "pt.GetByte(pt.Bytes('14'), pt.Int(15))"),
            ("&&", BIG_A2),
            ('byte "101"', "pt.Bytes('101')"),
            ('byte "102"', "pt.Bytes('102')"),
            ("b/", "pt.BytesDiv(pt.Bytes('101'), pt.Bytes('102'))"),
            ('byte "103"', "pt.Bytes('103')"),
            ("b~", "pt.BytesNot(pt.Bytes('103'))"),
            ("concat", BIG_C2),
            ("int 10", "pt.Int(10)"),
            ("bzero", "pt.BytesZero(pt.Int(10))"),
            ("concat", BIG_C2),
            ('byte "105"', "pt.Bytes('105')"),
            ("int 106", "pt.Int(106)"),
            ("int 107", "pt.Int(107)"),
            ("setbit", "pt.SetBit(pt.Bytes('105'), pt.Int(106), pt.Int(107))"),
            ("concat", BIG_C2),
            ('byte "108"', "pt.Bytes('108')"),
            ("int 109", "pt.Int(109)"),
            ("int 110", "pt.Int(110)"),
            ("setbyte", "pt.SetByte(pt.Bytes('108'), pt.Int(109), pt.Int(110))"),
            ("concat", BIG_C2),
            ("btoi", f"pt.Btoi({BIG_C2})"),
            ("&&", BIG_A2),
            ("return", C),
        ],
        4,
    ),
    (  # 33 - ABI Subroutine + NamedTuple (scratch slots)
        abi_named_tuple_example,
        [
            [P, C],
            ("callsub status_0", "status()"),
            ("store 0", "status().store_into(output)"),
            ("int 1", "pt.Int(1)"),
            ("return", "comp.compile(with_sourcemap=True)"),
            ("", "status().store_into(output)"),
            ("// status", "status().store_into(output)"),
            ("status_0:", "status().store_into(output)"),
            ('byte "1"', "pt.Bytes('1')"),
            ("app_global_get", "pt.App.globalGet(pt.Bytes('1'))"),
            ("store 2", "question.set(pt.App.globalGet(pt.Bytes('1')))"),
            ("load 2", "question.set(pt.App.globalGet(pt.Bytes('1')))"),
            ("len", "question.set(pt.App.globalGet(pt.Bytes('1')))"),
            ("itob", "question.set(pt.App.globalGet(pt.Bytes('1')))"),
            ("extract 6 0", "question.set(pt.App.globalGet(pt.Bytes('1')))"),
            ("load 2", "question.set(pt.App.globalGet(pt.Bytes('1')))"),
            ("concat", "question.set(pt.App.globalGet(pt.Bytes('1')))"),
            ("store 2", "question.set(pt.App.globalGet(pt.Bytes('1')))"),
            ('byte "2"', "pt.Bytes('2')"),
            ("app_global_get", "pt.App.globalGet(pt.Bytes('2'))"),
            ("!", "can_resubmit.set(pt.App.globalGet(pt.Bytes('2')))"),
            ("!", "can_resubmit.set(pt.App.globalGet(pt.Bytes('2')))"),
            ("store 3", "can_resubmit.set(pt.App.globalGet(pt.Bytes('2')))"),
            ('byte "3"', "pt.Bytes('3')"),
            ("app_global_get", "pt.App.globalGet(pt.Bytes('3'))"),
            ("!", "is_open.set(pt.App.globalGet(pt.Bytes('3')))"),
            ("!", "is_open.set(pt.App.globalGet(pt.Bytes('3')))"),
            ("store 4", "is_open.set(pt.App.globalGet(pt.Bytes('3')))"),
            ('byte ""', "results.set([])"),
            ("store 5", "results.set([])"),
            ("load 2", "output.set(question, can_resubmit, is_open, results)"),
            ("store 9", "output.set(question, can_resubmit, is_open, results)"),
            ("load 9", "output.set(question, can_resubmit, is_open, results)"),
            ("store 8", "output.set(question, can_resubmit, is_open, results)"),
            ("int 5", "output.set(question, can_resubmit, is_open, results)"),
            ("store 6", "output.set(question, can_resubmit, is_open, results)"),
            ("load 6", "output.set(question, can_resubmit, is_open, results)"),
            ("load 9", "output.set(question, can_resubmit, is_open, results)"),
            ("len", "output.set(question, can_resubmit, is_open, results)"),
            ("+", "output.set(question, can_resubmit, is_open, results)"),
            ("store 7", "output.set(question, can_resubmit, is_open, results)"),
            ("load 7", "output.set(question, can_resubmit, is_open, results)"),
            ("int 65536", "output.set(question, can_resubmit, is_open, results)"),
            ("<", "output.set(question, can_resubmit, is_open, results)"),
            ("assert", "output.set(question, can_resubmit, is_open, results)"),
            ("load 6", "output.set(question, can_resubmit, is_open, results)"),
            ("itob", "output.set(question, can_resubmit, is_open, results)"),
            ("extract 6 0", "output.set(question, can_resubmit, is_open, results)"),
            ("byte 0x00", "output.set(question, can_resubmit, is_open, results)"),
            ("int 0", "output.set(question, can_resubmit, is_open, results)"),
            ("load 3", "output.set(question, can_resubmit, is_open, results)"),
            ("setbit", "output.set(question, can_resubmit, is_open, results)"),
            ("int 1", "output.set(question, can_resubmit, is_open, results)"),
            ("load 4", "output.set(question, can_resubmit, is_open, results)"),
            ("setbit", "output.set(question, can_resubmit, is_open, results)"),
            ("concat", "output.set(question, can_resubmit, is_open, results)"),
            ("load 5", "output.set(question, can_resubmit, is_open, results)"),
            ("store 9", "output.set(question, can_resubmit, is_open, results)"),
            ("load 8", "output.set(question, can_resubmit, is_open, results)"),
            ("load 9", "output.set(question, can_resubmit, is_open, results)"),
            ("concat", "output.set(question, can_resubmit, is_open, results)"),
            ("store 8", "output.set(question, can_resubmit, is_open, results)"),
            ("load 7", "output.set(question, can_resubmit, is_open, results)"),
            ("store 6", "output.set(question, can_resubmit, is_open, results)"),
            ("load 6", "output.set(question, can_resubmit, is_open, results)"),
            ("itob", "output.set(question, can_resubmit, is_open, results)"),
            ("extract 6 0", "output.set(question, can_resubmit, is_open, results)"),
            ("concat", "output.set(question, can_resubmit, is_open, results)"),
            ("load 8", "output.set(question, can_resubmit, is_open, results)"),
            ("concat", "output.set(question, can_resubmit, is_open, results)"),
            ("store 1", "output.set(question, can_resubmit, is_open, results)"),
            ("load 1", "status().store_into(output)"),
            ("retsub", "return pt.Seq(status().store_into(output), pt.Int(1))"),
        ],
        5,
        "Application",
        dict(frame_pointers=False),
    ),
    (  # 34 - ABI Subroutine + NamedTuple (frame pointers)
        abi_named_tuple_example,
        [
            [P, C],
            ("callsub status_0", "status()"),
            ("store 0", "status().store_into(output)"),
            ("int 1", "pt.Int(1)"),
            ("return", "comp.compile(with_sourcemap=True)"),
            ("", "status().store_into(output)"),
            ("// status", "status().store_into(output)"),
            ("status_0:", "status().store_into(output)"),
            ("proto 0 1", "status().store_into(output)"),
            ('byte ""', "status().store_into(output)"),
            ("dup", "status().store_into(output)"),
            ("int 0", "status().store_into(output)"),
            ("dup", "status().store_into(output)"),
            ('byte ""', "status().store_into(output)"),
            ("int 0", "status().store_into(output)"),
            ("dup", "status().store_into(output)"),
            ('byte ""', "status().store_into(output)"),
            ("dup", "status().store_into(output)"),
            ("int 0", "status().store_into(output)"),
            ("dup", "status().store_into(output)"),
            ('byte ""', "status().store_into(output)"),
            ("dup", "status().store_into(output)"),
            ('byte "1"', "pt.Bytes('1')"),
            ("app_global_get", "pt.App.globalGet(pt.Bytes('1'))"),
            ("frame_bury 1", "question.set(pt.App.globalGet(pt.Bytes('1')))"),
            ("frame_dig 1", "question.set(pt.App.globalGet(pt.Bytes('1')))"),
            ("len", "question.set(pt.App.globalGet(pt.Bytes('1')))"),
            ("itob", "question.set(pt.App.globalGet(pt.Bytes('1')))"),
            ("extract 6 0", "question.set(pt.App.globalGet(pt.Bytes('1')))"),
            ("frame_dig 1", "question.set(pt.App.globalGet(pt.Bytes('1')))"),
            ("concat", "question.set(pt.App.globalGet(pt.Bytes('1')))"),
            ("frame_bury 1", "question.set(pt.App.globalGet(pt.Bytes('1')))"),
            ('byte "2"', "pt.Bytes('2')"),
            ("app_global_get", "pt.App.globalGet(pt.Bytes('2'))"),
            ("!", "can_resubmit.set(pt.App.globalGet(pt.Bytes('2')))"),
            ("!", "can_resubmit.set(pt.App.globalGet(pt.Bytes('2')))"),
            ("frame_bury 2", "can_resubmit.set(pt.App.globalGet(pt.Bytes('2')))"),
            ('byte "3"', "pt.Bytes('3')"),
            ("app_global_get", "pt.App.globalGet(pt.Bytes('3'))"),
            ("!", "is_open.set(pt.App.globalGet(pt.Bytes('3')))"),
            ("!", "is_open.set(pt.App.globalGet(pt.Bytes('3')))"),
            ("frame_bury 3", "is_open.set(pt.App.globalGet(pt.Bytes('3')))"),
            ('byte ""', "results.set([])"),
            ("frame_bury 4", "results.set([])"),
            ("frame_dig 1", "output.set(question, can_resubmit, is_open, results)"),
            ("frame_bury 12", "output.set(question, can_resubmit, is_open, results)"),
            ("frame_dig 12", "output.set(question, can_resubmit, is_open, results)"),
            ("frame_bury 11", "output.set(question, can_resubmit, is_open, results)"),
            ("int 5", "output.set(question, can_resubmit, is_open, results)"),
            ("frame_bury 9", "output.set(question, can_resubmit, is_open, results)"),
            ("frame_dig 9", "output.set(question, can_resubmit, is_open, results)"),
            ("frame_dig 12", "output.set(question, can_resubmit, is_open, results)"),
            ("len", "output.set(question, can_resubmit, is_open, results)"),
            ("+", "output.set(question, can_resubmit, is_open, results)"),
            ("frame_bury 10", "output.set(question, can_resubmit, is_open, results)"),
            ("frame_dig 10", "output.set(question, can_resubmit, is_open, results)"),
            ("int 65536", "output.set(question, can_resubmit, is_open, results)"),
            ("<", "output.set(question, can_resubmit, is_open, results)"),
            ("assert", "output.set(question, can_resubmit, is_open, results)"),
            ("frame_dig 9", "output.set(question, can_resubmit, is_open, results)"),
            ("itob", "output.set(question, can_resubmit, is_open, results)"),
            ("extract 6 0", "output.set(question, can_resubmit, is_open, results)"),
            ("byte 0x00", "output.set(question, can_resubmit, is_open, results)"),
            ("int 0", "output.set(question, can_resubmit, is_open, results)"),
            ("frame_dig 2", "output.set(question, can_resubmit, is_open, results)"),
            ("setbit", "output.set(question, can_resubmit, is_open, results)"),
            ("int 1", "output.set(question, can_resubmit, is_open, results)"),
            ("frame_dig 3", "output.set(question, can_resubmit, is_open, results)"),
            ("setbit", "output.set(question, can_resubmit, is_open, results)"),
            ("concat", "output.set(question, can_resubmit, is_open, results)"),
            ("frame_dig 4", "output.set(question, can_resubmit, is_open, results)"),
            ("frame_bury 12", "output.set(question, can_resubmit, is_open, results)"),
            ("frame_dig 11", "output.set(question, can_resubmit, is_open, results)"),
            ("frame_dig 12", "output.set(question, can_resubmit, is_open, results)"),
            ("concat", "output.set(question, can_resubmit, is_open, results)"),
            ("frame_bury 11", "output.set(question, can_resubmit, is_open, results)"),
            ("frame_dig 10", "output.set(question, can_resubmit, is_open, results)"),
            ("frame_bury 9", "output.set(question, can_resubmit, is_open, results)"),
            ("frame_dig 9", "output.set(question, can_resubmit, is_open, results)"),
            ("itob", "output.set(question, can_resubmit, is_open, results)"),
            ("extract 6 0", "output.set(question, can_resubmit, is_open, results)"),
            ("concat", "output.set(question, can_resubmit, is_open, results)"),
            ("frame_dig 11", "output.set(question, can_resubmit, is_open, results)"),
            ("concat", "output.set(question, can_resubmit, is_open, results)"),
            ("frame_bury 0", "output.set(question, can_resubmit, is_open, results)"),
            ("retsub", "return pt.Seq(status().store_into(output), pt.Int(1))"),
        ],
        8,
        "Application",
        dict(frame_pointers=True),
    ),
    (  # 35 - ABI Subroutine + MethodReturn (scratch slots)
        abi_method_return_example,
        [
            [P, C],
            ("txna ApplicationArgs 1", "pt.Txn.application_args[1]"),
            (
                "store 0",
                "(to_sum_arr := pt.abi.make(pt.abi.DynamicArray[pt.abi.Uint64])).decode(pt.Txn.application_args[1])",
            ),
            ("load 0", "comp.compile(with_sourcemap=True)"),
            ("callsub abisum_0", "abi_sum(to_sum_arr)"),
            ("store 1", "(res := pt.abi.Uint64()).set(abi_sum(to_sum_arr))"),
            ("byte 0x151f7c75", "comp.compile(with_sourcemap=True)"),
            ("load 1", "comp.compile(with_sourcemap=True)"),
            ("itob", "comp.compile(with_sourcemap=True)"),
            ("concat", "comp.compile(with_sourcemap=True)"),
            ("log", "comp.compile(with_sourcemap=True)"),
            ("int 1", "pt.Approve()"),
            ("return", "pt.Approve()"),
            ("", "(res := pt.abi.Uint64()).set(abi_sum(to_sum_arr))"),
            ("// abi_sum", "(res := pt.abi.Uint64()).set(abi_sum(to_sum_arr))"),
            ("abisum_0:", "(res := pt.abi.Uint64()).set(abi_sum(to_sum_arr))"),
            ("store 2", "(res := pt.abi.Uint64()).set(abi_sum(to_sum_arr))"),
            ("int 0", "output.set(0)"),
            ("store 3", "output.set(0)"),
            ("int 0", "pt.Int(0)"),
            ("store 4", "i.store(pt.Int(0))"),
            (
                "abisum_0_l1:",
                "pt.For(i.store(pt.Int(0)), i.load() < toSum.length(), i.store(i.load() + pt.Int(1)))",
            ),
            ("load 4", "i.load()"),
            ("load 2", "toSum.length()"),
            ("int 0", "toSum.length()"),
            ("extract_uint16", "toSum.length()"),
            ("store 6", "toSum.length()"),
            ("load 6", "toSum.length()"),
            ("<", "i.load() < toSum.length()"),
            (
                "bz abisum_0_l3",
                "pt.For(i.store(pt.Int(0)), i.load() < toSum.length(), i.store(i.load() + pt.Int(1)))",
            ),
            ("load 2", "toSum[i.load()].store_into(valueAtIndex)"),
            ("int 8", "toSum[i.load()].store_into(valueAtIndex)"),
            ("load 4", "i.load()"),
            ("*", "toSum[i.load()].store_into(valueAtIndex)"),
            ("int 2", "toSum[i.load()].store_into(valueAtIndex)"),
            ("+", "toSum[i.load()].store_into(valueAtIndex)"),
            ("extract_uint64", "toSum[i.load()].store_into(valueAtIndex)"),
            ("store 5", "toSum[i.load()].store_into(valueAtIndex)"),
            ("load 3", "output.get()"),
            ("load 5", "valueAtIndex.get()"),
            ("+", "output.get() + valueAtIndex.get()"),
            ("store 3", "output.set(output.get() + valueAtIndex.get())"),
            ("load 4", "i.load()"),
            ("int 1", "pt.Int(1)"),
            ("+", "i.load() + pt.Int(1)"),
            ("store 4", "i.store(i.load() + pt.Int(1))"),
            (
                "b abisum_0_l1",
                "pt.For(i.store(pt.Int(0)), i.load() < toSum.length(), i.store(i.load() + pt.Int(1)))",
            ),
            (
                "abisum_0_l3:",
                "pt.For(i.store(pt.Int(0)), i.load() < toSum.length(), i.store(i.load() + pt.Int(1)))",
            ),
            ("load 3", "(res := pt.abi.Uint64()).set(abi_sum(to_sum_arr))"),
            (
                "retsub",
                "return pt.Seq((to_sum_arr := pt.abi.make(pt.abi.DynamicArray[pt.abi.Uint64])).decode(pt.Txn.application_args[1]), (res := pt.abi.Uint64()).set(abi_sum(to_sum_arr)), pt.abi.MethodReturn(res), pt.Approve())",
            ),
        ],
        5,
        "Application",
        dict(frame_pointers=False),
    ),
    (  # 36 - ABI Subroutine + MethodReturn (frame pointers)
        abi_method_return_example,
        [
            [P, C],
            ("txna ApplicationArgs 1", "pt.Txn.application_args[1]"),
            (
                "store 0",
                "(to_sum_arr := pt.abi.make(pt.abi.DynamicArray[pt.abi.Uint64])).decode(pt.Txn.application_args[1])",
            ),
            ("load 0", "comp.compile(with_sourcemap=True)"),
            ("callsub abisum_0", "abi_sum(to_sum_arr)"),
            ("store 1", "(res := pt.abi.Uint64()).set(abi_sum(to_sum_arr))"),
            ("byte 0x151f7c75", "comp.compile(with_sourcemap=True)"),
            ("load 1", "comp.compile(with_sourcemap=True)"),
            ("itob", "comp.compile(with_sourcemap=True)"),
            ("concat", "comp.compile(with_sourcemap=True)"),
            ("log", "comp.compile(with_sourcemap=True)"),
            ("int 1", "pt.Approve()"),
            ("return", "pt.Approve()"),
            ("", "(res := pt.abi.Uint64()).set(abi_sum(to_sum_arr))"),
            ("// abi_sum", "(res := pt.abi.Uint64()).set(abi_sum(to_sum_arr))"),
            ("abisum_0:", "(res := pt.abi.Uint64()).set(abi_sum(to_sum_arr))"),
            ("proto 1 1", "(res := pt.abi.Uint64()).set(abi_sum(to_sum_arr))"),
            ("int 0", "(res := pt.abi.Uint64()).set(abi_sum(to_sum_arr))"),
            ("dupn 3", "(res := pt.abi.Uint64()).set(abi_sum(to_sum_arr))"),
            ("int 0", "output.set(0)"),
            ("frame_bury 0", "output.set(0)"),
            ("int 0", "pt.Int(0)"),
            ("store 2", "i.store(pt.Int(0))"),
            (
                "abisum_0_l1:",
                "pt.For(i.store(pt.Int(0)), i.load() < toSum.length(), i.store(i.load() + pt.Int(1)))",
            ),
            ("load 2", "i.load()"),
            ("frame_dig -1", "toSum.length()"),
            ("int 0", "toSum.length()"),
            ("extract_uint16", "toSum.length()"),
            ("frame_bury 2", "toSum.length()"),
            ("frame_dig 2", "toSum.length()"),
            ("<", "i.load() < toSum.length()"),
            (
                "bz abisum_0_l3",
                "pt.For(i.store(pt.Int(0)), i.load() < toSum.length(), i.store(i.load() + pt.Int(1)))",
            ),
            ("frame_dig -1", "toSum[i.load()].store_into(valueAtIndex)"),
            ("int 8", "toSum[i.load()].store_into(valueAtIndex)"),
            ("load 2", "i.load()"),
            ("*", "toSum[i.load()].store_into(valueAtIndex)"),
            ("int 2", "toSum[i.load()].store_into(valueAtIndex)"),
            ("+", "toSum[i.load()].store_into(valueAtIndex)"),
            ("extract_uint64", "toSum[i.load()].store_into(valueAtIndex)"),
            ("frame_bury 1", "toSum[i.load()].store_into(valueAtIndex)"),
            ("frame_dig 0", "output.get()"),
            ("frame_dig 1", "valueAtIndex.get()"),
            ("+", "output.get() + valueAtIndex.get()"),
            ("frame_bury 0", "output.set(output.get() + valueAtIndex.get())"),
            ("load 2", "i.load()"),
            ("int 1", "pt.Int(1)"),
            ("+", "i.load() + pt.Int(1)"),
            ("store 2", "i.store(i.load() + pt.Int(1))"),
            (
                "b abisum_0_l1",
                "pt.For(i.store(pt.Int(0)), i.load() < toSum.length(), i.store(i.load() + pt.Int(1)))",
            ),
            (
                "abisum_0_l3:",
                "pt.For(i.store(pt.Int(0)), i.load() < toSum.length(), i.store(i.load() + pt.Int(1)))",
            ),
            (
                "retsub",
                "return pt.Seq((to_sum_arr := pt.abi.make(pt.abi.DynamicArray[pt.abi.Uint64])).decode(pt.Txn.application_args[1]), (res := pt.abi.Uint64()).set(abi_sum(to_sum_arr)), pt.abi.MethodReturn(res), pt.Approve())",
            ),
        ],
        8,
        "Application",
        dict(frame_pointers=True),
    ),
    (  # 37 - Router (scratch slots)
        router_example,
        [
            [P, R],
            (
                "txn NumAppArgs",
                "pt.BareCallActions(opt_in=pt.OnCompleteAction.call_only(pt.Log(pt.Bytes('optin call'))))",
            ),
            (
                "int 0",
                "pt.BareCallActions(opt_in=pt.OnCompleteAction.call_only(pt.Log(pt.Bytes('optin call'))))",
            ),
            (
                "==",
                "pt.BareCallActions(opt_in=pt.OnCompleteAction.call_only(pt.Log(pt.Bytes('optin call'))))",
            ),
            (
                "bnz main_l4",
                "pt.BareCallActions(opt_in=pt.OnCompleteAction.call_only(pt.Log(pt.Bytes('optin call'))))",
            ),
            (
                "txna ApplicationArgs 0",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                'method "add(uint64,uint64)uint64"',
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "==",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "bnz main_l3",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "err",
                "expr.compile(version=version, assemble_constants=False, optimize=optimize, with_sourcemaps=True)",
            ),
            (
                "main_l3:",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "txn OnCompletion",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            ("int NoOp", "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:"),
            (
                "==",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "txn ApplicationID",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "int 0",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "!=",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "&&",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "assert",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "txna ApplicationArgs 1",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "btoi",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "store 0",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "txna ApplicationArgs 2",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "btoi",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "store 1",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "load 0",
                "expr.compile(version=version, assemble_constants=False, optimize=optimize, with_sourcemaps=True)",
            ),
            (
                "load 1",
                "expr.compile(version=version, assemble_constants=False, optimize=optimize, with_sourcemaps=True)",
            ),
            (
                "callsub add_0",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "store 2",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "byte 0x151f7c75",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "load 2",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "itob",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "concat",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "log",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "int 1",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "return",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "main_l4:",
                "pt.Router('questionable', on_completion_actions, clear_state=pt.Approve())",
            ),
            (
                "txn OnCompletion",
                "pt.Router('questionable', on_completion_actions, clear_state=pt.Approve())",
            ),
            ("int OptIn", "pt.Router('questionable', on_completion_actions, clear_state=pt.Approve())"),
            (
                "==",
                "pt.Router('questionable', on_completion_actions, clear_state=pt.Approve())",
            ),
            (
                "bnz main_l6",
                "pt.Router('questionable', on_completion_actions, clear_state=pt.Approve())",
            ),
            (
                "err",
                "pt.BareCallActions(opt_in=pt.OnCompleteAction.call_only(pt.Log(pt.Bytes('optin call'))))",
            ),
            (
                "main_l6:",
                "pt.Router('questionable', on_completion_actions, clear_state=pt.Approve())",
            ),
            (
                "txn ApplicationID",
                "pt.Router('questionable', on_completion_actions, clear_state=pt.Approve())",
            ),
            (
                "int 0",
                "pt.Router('questionable', on_completion_actions, clear_state=pt.Approve())",
            ),
            (
                "!=",
                "pt.Router('questionable', on_completion_actions, clear_state=pt.Approve())",
            ),
            (
                "assert",
                "pt.Router('questionable', on_completion_actions, clear_state=pt.Approve())",
            ),
            ('byte "optin call"', "pt.Bytes('optin call')"),
            ("log", "pt.Log(pt.Bytes('optin call'))"),
            (
                "int 1",
                "pt.Router('questionable', on_completion_actions, clear_state=pt.Approve())",
            ),
            (
                "return",
                "pt.Router('questionable', on_completion_actions, clear_state=pt.Approve())",
            ),
            (
                "",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "// add",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "add_0:",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "store 4",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "store 3",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            ("load 3", "a.get()"),
            ("load 4", "b.get()"),
            ("+", "a.get() + b.get()"),
            ("store 5", "output.set(a.get() + b.get())"),
            (
                "load 5",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "retsub",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
        ],
        5,
        "Application",
        dict(frame_pointers=False),
    ),
    (  # 38 - Router (frame pointers)
        router_example,
        [
            [P, R],
            (
                "txn NumAppArgs",
                "pt.BareCallActions(opt_in=pt.OnCompleteAction.call_only(pt.Log(pt.Bytes('optin call'))))",
            ),
            (
                "int 0",
                "pt.BareCallActions(opt_in=pt.OnCompleteAction.call_only(pt.Log(pt.Bytes('optin call'))))",
            ),
            (
                "==",
                "pt.BareCallActions(opt_in=pt.OnCompleteAction.call_only(pt.Log(pt.Bytes('optin call'))))",
            ),
            (
                "bnz main_l4",
                "pt.BareCallActions(opt_in=pt.OnCompleteAction.call_only(pt.Log(pt.Bytes('optin call'))))",
            ),
            (
                "txna ApplicationArgs 0",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                'method "add(uint64,uint64)uint64"',
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "==",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "bnz main_l3",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "err",
                "expr.compile(version=version, assemble_constants=False, optimize=optimize, with_sourcemaps=True)",
            ),
            (
                "main_l3:",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "txn OnCompletion",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "int NoOp",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "==",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "txn ApplicationID",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "int 0",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "!=",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "&&",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "assert",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "txna ApplicationArgs 1",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "btoi",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "store 0",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "txna ApplicationArgs 2",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "btoi",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "store 1",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "load 0",
                "expr.compile(version=version, assemble_constants=False, optimize=optimize, with_sourcemaps=True)",
            ),
            (
                "load 1",
                "expr.compile(version=version, assemble_constants=False, optimize=optimize, with_sourcemaps=True)",
            ),
            (
                "callsub add_0",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "store 2",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "byte 0x151f7c75",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "load 2",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "itob",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "concat",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "log",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "int 1",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "return",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "main_l4:",
                "pt.Router('questionable', on_completion_actions, clear_state=pt.Approve())",
            ),
            (
                "txn OnCompletion",
                "pt.Router('questionable', on_completion_actions, clear_state=pt.Approve())",
            ),
            (
                "int OptIn",
                "pt.Router('questionable', on_completion_actions, clear_state=pt.Approve())",
            ),
            (
                "==",
                "pt.Router('questionable', on_completion_actions, clear_state=pt.Approve())",
            ),
            (
                "bnz main_l6",
                "pt.Router('questionable', on_completion_actions, clear_state=pt.Approve())",
            ),
            (
                "err",
                "pt.BareCallActions(opt_in=pt.OnCompleteAction.call_only(pt.Log(pt.Bytes('optin call'))))",
            ),
            (
                "main_l6:",
                "pt.Router('questionable', on_completion_actions, clear_state=pt.Approve())",
            ),
            (
                "txn ApplicationID",
                "pt.Router('questionable', on_completion_actions, clear_state=pt.Approve())",
            ),
            (
                "int 0",
                "pt.Router('questionable', on_completion_actions, clear_state=pt.Approve())",
            ),
            (
                "!=",
                "pt.Router('questionable', on_completion_actions, clear_state=pt.Approve())",
            ),
            (
                "assert",
                "pt.Router('questionable', on_completion_actions, clear_state=pt.Approve())",
            ),
            ('byte "optin call"', "pt.Bytes('optin call')"),
            ("log", "pt.Log(pt.Bytes('optin call'))"),
            (
                "int 1",
                "pt.Router('questionable', on_completion_actions, clear_state=pt.Approve())",
            ),
            (
                "return",
                "pt.Router('questionable', on_completion_actions, clear_state=pt.Approve())",
            ),
            (
                "",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "// add",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "add_0:",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "proto 2 1",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            (
                "int 0",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
            ("frame_dig -2", "a.get()"),
            ("frame_dig -1", "b.get()"),
            ("+", "a.get() + b.get()"),
            ("frame_bury 0", "output.set(a.get() + b.get())"),
            (
                "retsub",
                "def add(a: pt.abi.Uint64, b: pt.abi.Uint64, *, output: pt.abi.Uint64) -> pt.Expr:",
            ),
        ],
        8,
        "Application",
        dict(frame_pointers=True),
    ),
]


@pytest.mark.parametrize("i, test_case", enumerate(CONSTRUCTS))
@pytest.mark.parametrize("mode", ["Application", "Signature"])
@pytest.mark.parametrize("version", range(2, CONSTRUCTS_LATEST_VERSION + 1))
@pytest.mark.serial
def test_constructs(mock_ConfigParser, i, test_case, mode, version):
    import pyteal as pt

    expr, line2unparsed = test_case[:2]
    line2unparsed = deepcopy(line2unparsed)
    # fill the pragma template:
    line2unparsed[0][0] = line2unparsed[0][0].format(v=version)

    expr = expr(pt)
    if len(test_case) > 2:
        min_version = test_case[2]
        if version < min_version:
            return
    if len(test_case) > 3:
        fixed_mode = test_case[3]
        if mode != fixed_mode:
            return
    optimize = None
    if len(test_case) > 4:
        optimize = pt.OptimizeOptions(**test_case[4])

    mode = getattr(pt.Mode, mode)
    if isinstance(expr, pt.Router):
        assert len(test_case) > 3 and fixed_mode == "Application"  # type: ignore

        router_bundle = expr.compile(
            version=version,
            assemble_constants=False,
            optimize=optimize,
            with_sourcemaps=True,
        )
        sourcemap = router_bundle.approval_sourcemap
    else:
        comp = pt.Compilation(
            expr, mode, version=version, assemble_constants=False, optimize=optimize
        )
        bundle = comp.compile(with_sourcemap=True)
        sourcemap = bundle.sourcemap

    msg = f"[CASE #{i}]: {expr=}"

    assert sourcemap, msg
    assert sourcemap._hybrid is True, msg

    tmis = sourcemap.as_list()
    N = len(tmis)

    teal_linenos = [tmi.teal_lineno for tmi in tmis]
    assert list(range(1, N + 1)) == teal_linenos

    teal_lines = [tmi.teal_line for tmi in tmis]
    assert teal_lines == [
        l for chunk in sourcemap.teal_chunks for l in chunk.splitlines()
    ]

    unparsed = [tmi.hybrid_unparsed() for tmi in tmis]  # type: ignore
    msg = f"{msg}, {tmis=}"
    FORCE_FAIL_FOR_CASE_CREATION = False
    if FORCE_FAIL_FOR_CASE_CREATION:
        ouch = [(t, unparsed[i]) for i, t in enumerate(teal_lines)]
        print(ouch)
        x = "DEBUG" * 100
        assert not x, ouch

    expected_lines, expected_unparsed = list(zip(*line2unparsed))

    assert list(expected_lines) == teal_lines, msg
    assert list(expected_unparsed) == unparsed, msg
