# import asyncio
import time
import threading
from functools import reduce
from itertools import groupby  # type: ignore
import pytest

from pyteal import compileTeal, Compilation, Mode
from examples.signature.factorizer_game import logicsig

# implicitly import via no_regrassions:
# from examples.application.abi.algobank import router

from tests.compile_asserts import assert_new_v_old, assert_teal_as_expected
from tests.blackbox import PyTealDryRunExecutor
from tests.integration.graviton_test import (
    FIXTURES,
    GENERATED,
    ISSUE_199_CASES as ISSUE_199_CASES_BB,
    wrap_compile_and_save,
)
from tests.unit.sourcemap_test import no_regressions
from tests.unit.pass_by_ref_test import ISSUE_199_CASES

SKIPS = {
    1: False,
    2: False,
    3: False,
    4: False,
    5: False,
}
NUM_REPEATS_FOR_T3 = 5
ASSERT_ALGOBANK_AGAINST_FIXED = False


@pytest.mark.skipif(SKIPS[1], reason=f"{SKIPS[1]=}")
@pytest.mark.parametrize("pt", ISSUE_199_CASES)
def test_1_pass_by_ref_teal_output_is_unchanged(pt):
    assert_new_v_old(pt, 6, "unchanged")


def assert_only_the_slots_permuted(expected: list[str], actual: list[str]):
    """
    Name a bit misleading. If expected == actual, we don't actually fail anything.
    And even if only the slots are permuted, we still fail at the end.
    """
    diffs = [
        (i, x[:2], y[:2])
        for i, (e, a) in enumerate(zip(expected, actual))
        if (x := e.strip().split()) != (y := a.strip().split())
    ]

    if diffs:
        assert all(x == y for _, (x, _), (y, _) in diffs)

        slots_only = [(ln, int(x), int(y)) for ln, (_, x), (_, y) in diffs]

        maps = list(sorted({(x, y) for _, x, y in slots_only}))
        pmaps = ", ".join(f"{x}-->{y}" for x, y in maps)

        # unique keys and values:
        assert len({x for x, _ in maps}) == len(maps)
        assert len({y for _, y in maps}) == len(maps)

        assert False, f"""Shoulnd't have any diffs. However, the diff is stable in the sense that only slots got reassigned: 
{diffs=}
{pmaps=}"""


@pytest.mark.skipif(SKIPS[2], reason=f"{SKIPS[2]=}")
@pytest.mark.parametrize("pt", ISSUE_199_CASES)
def test_2_teal_output_is_unchanged(pt):
    expected: list[str]
    actual: list[str]
    expected, actual = assert_new_v_old(pt, 6, "unchanged", skip_final_assertion=True)

    assert_only_the_slots_permuted(expected, actual)


# --- MULTI COMPILE WITH NO FIXTURES --- #


def lsig345():
    return compileTeal(logicsig(3, 4, 5), Mode.Signature, version=7)


is_algobank_first_time = True


def algobank_too_complex():
    global is_algobank_first_time
    expected_lines, actual_lines = no_regressions(skip_final_assertion=True)
    if ASSERT_ALGOBANK_AGAINST_FIXED:
        assert expected_lines == actual_lines, "bailing out early!!!"

    return_value = expected_lines if is_algobank_first_time else actual_lines
    is_algobank_first_time = False
    return "\n".join(return_value)


def algobank():
    expected_lines, actual_lines = no_regressions(skip_final_assertion=True)
    if ASSERT_ALGOBANK_AGAINST_FIXED:
        assert expected_lines == actual_lines, "bailing out early!!!"

    return "\n".join(actual_lines)


def wrap_and_compile(subr):
    def compile():
        mode = Mode.Application
        return PyTealDryRunExecutor(subr, mode).compile(6, True)

    return compile


WRAPPED_199s = [wrap_and_compile(subr) for subr in ISSUE_199_CASES_BB]


def multi_compile(N, comp, sync):
    async def compile(teals: list[str], idx: int):
        teals[idx] = comp()

    teals = [""] * N

    async def main():
        # Use asyncio.gather to execute multiple foo() concurrently
        await asyncio.gather(*(compile(teals, idx) for idx in range(N)))

    if sync:
        for idx in range(N):
            teals[idx] = comp()
    else:
        asyncio.run(main())

    teals_gb = list(groupby(teals))
    return teals_gb


@pytest.mark.skipif(SKIPS[3], reason=f"{SKIPS[3]=}")
@pytest.mark.parametrize("expr", [lsig345, algobank] + WRAPPED_199s)
@pytest.mark.parametrize("sync", [True, False])
def test_3_repeated_compilation(expr, sync):
    global is_algobank_first_time
    is_algobank_first_time = True
    teals_gb = multi_compile(NUM_REPEATS_FOR_T3, expr, sync)

    assert teals_gb, "we should have at least one element!!!"

    if len(teals_gb) == 1:
        return  # COPACETI

    # WLOG - at least 2
    t1, t2 = [t.splitlines() for t, _ in teals_gb[:2]]

    pairs = list(zip(t1, t2))
    diffs = [(i, x, y) for i, (x, y) in enumerate(pairs) if x != y]

    def op(x):
        return x.split()[0]

    assert all(op(d[1]) == op(d[2]) for d in diffs)

    def slot(x):
        return int(x.split()[1])

    maps = [(i, slot(x), {slot(y)}) for i, x, y in diffs]

    def dict_append(d, t):
        d[k] = (d[k] | t[2]) if (k := t[1]) in d else t[2]
        return d

    unified = reduce(
        dict_append,
        maps,
        dict(),
    )

    assert all(len(v) == 1 for v in unified.values())

    assert False, f"""At the end of the day, this was unstable with {len(teals_gb)} distinct compilations:
{diffs=}
"""


# Really, this was an integration test:
@pytest.mark.skipif(SKIPS[4], reason=f"{SKIPS[4]=}")
@pytest.mark.parametrize("subr", ISSUE_199_CASES_BB)
@pytest.mark.parametrize("mode", Mode)
def test_4_stable_teal_generation(subr, mode):
    """
    TODO: here's an example of issue #199 at play - need to run a dynamic version of `git bisect`
    to figure out what is driving this
    """
    case_name = subr.name()
    print(f"stable TEAL generation test for {case_name} in mode {mode}")

    # HANG NOTE: I prefer not to modify this test, for it is skipped now on thread-unsafe behavior,
    # and I would suggest revisiting later after we have satisfied solution for #199.
    _, _, tealfile = wrap_compile_and_save(subr, mode, 6, True, "stability", case_name)
    path2actual = GENERATED / "stability" / tealfile
    path2expected = FIXTURES / "stability" / tealfile
    expected_lines, actual_lines = assert_teal_as_expected(
        path2actual, path2expected, skip_final_assertion=True
    )
    assert_only_the_slots_permuted(expected_lines, actual_lines)


@pytest.mark.parametrize("N", range(2, 11))
@pytest.mark.skipif(SKIPS[5], reason=f"{SKIPS[5]=}")
def test_5_algobank_in_detail(N):
    from pyteal import (
        abi,
        ABIReturnSubroutine,
        App,
        Approve,
        Assert,
        BareCallActions,
        Bytes,
        CallConfig,
        Expr,
        Int,
        Global,
        InnerTxnBuilder,
        MethodConfig,
        OnCompleteAction,
        OptimizeOptions,
        Router,
        Seq,
        Subroutine,
        TealType,
        Txn,
        TxnField,
        TxnType,
    )

    @Subroutine(TealType.none)
    def assert_sender_is_creator() -> Expr:
        return Assert(Txn.sender() == Global.creator_address())

    # move any balance that the user has into the "lost" amount when they close out or clear state
    transfer_balance_to_lost = App.globalPut(
        Bytes("lost"),
        App.globalGet(Bytes("lost")) + App.localGet(Txn.sender(), Bytes("balance")),
    )

    mc = MethodConfig(no_op=CallConfig.CALL, opt_in=CallConfig.CALL)

    @ABIReturnSubroutine
    def deposit(payment: abi.PaymentTransaction, sender: abi.Account) -> Expr:
        """This method receives a payment from an account opted into this app and records it as a deposit.

        The caller may opt into this app during this call.

        Args:
            payment: A payment transaction containing the amount of Algos the user wishes to deposit.
                The receiver of this transaction must be this app's escrow account.
            sender: An account that is opted into this app (or will opt in during this method call).
                The deposited funds will be recorded in this account's local state. This account must
                be the same as the sender of the `payment` transaction.
        """
        return Seq(
            Assert(payment.get().sender() == sender.address()),
            Assert(payment.get().receiver() == Global.current_application_address()),
            App.localPut(
                sender.address(),
                Bytes("balance"),
                App.localGet(sender.address(), Bytes("balance"))
                + payment.get().amount(),
            ),
        )

    @ABIReturnSubroutine
    def getBalance(user: abi.Account, *, output: abi.Uint64) -> Expr:
        """Lookup the balance of a user held by this app.

        Args:
            user: The user whose balance you wish to look up. This user must be opted into this app.

        Returns:
            The balance corresponding to the given user, in microAlgos.
        """
        return output.set(App.localGet(user.address(), Bytes("balance")))

    @ABIReturnSubroutine
    def withdraw(amount: abi.Uint64, recipient: abi.Account) -> Expr:
        """Withdraw an amount of Algos held by this app.

        The sender of this method call will be the source of the Algos, and the destination will be
        the `recipient` argument.

        The Algos will be transferred to the recipient using an inner transaction whose fee is set
        to 0, meaning the caller's transaction must include a surplus fee to cover the inner
        transaction.

        Args:
            amount: The amount of Algos requested to be withdraw, in microAlgos. This method will fail
                if this amount exceeds the amount of Algos held by this app for the method call sender.
            recipient: An account who will receive the withdrawn Algos. This may or may not be the same
                as the method call sender.
        """
        return Seq(
            # if amount is larger than App.localGet(Txn.sender(), Bytes("balance")), the subtraction
            # will underflow and fail this method call
            App.localPut(
                Txn.sender(),
                Bytes("balance"),
                App.localGet(Txn.sender(), Bytes("balance")) - amount.get(),
            ),
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.type_enum: TxnType.Payment,
                    TxnField.receiver: recipient.address(),
                    TxnField.amount: amount.get(),
                    TxnField.fee: Int(0),
                }
            ),
            InnerTxnBuilder.Submit(),
        )

    bcas = BareCallActions(
        # approve a creation no-op call
        no_op=OnCompleteAction(action=Approve(), call_config=CallConfig.CREATE),
        # approve opt-in calls during normal usage, and during creation as a convenience for the creator
        opt_in=OnCompleteAction(action=Approve(), call_config=CallConfig.ALL),
        # move any balance that the user has into the "lost" amount when they close out or clear state
        close_out=OnCompleteAction(
            action=transfer_balance_to_lost, call_config=CallConfig.CALL
        ),
        # only the creator can update or delete the app
        update_application=OnCompleteAction(
            action=assert_sender_is_creator, call_config=CallConfig.CALL
        ),
        delete_application=OnCompleteAction(
            action=assert_sender_is_creator, call_config=CallConfig.CALL
        ),
    )

    def build():
        r = Router(
            name="AlgoBank",
            bare_calls=bcas,
            clear_state=transfer_balance_to_lost,
        )
        r.add_method_handler(deposit, method_config=mc)
        r.add_method_handler(getBalance)
        r.add_method_handler(withdraw)
        return r

    def compile(router):
        return router.compile_program(
        version=6, optimize=OptimizeOptions(scratch_slots=True)
    )

    # routers = [build() for _ in range(N)]
    # assert routers[0] is not routers[1]
    router = build()
    routers = [router] * N
    outputs = [None] * N

    def assert_sameness(i, j):
        assert (o1 := outputs[i])
        assert (o2 := outputs[j])
        a1, c1, j1 = o1
        a2, c2, j2 = o2
        assert j1.dictify() == j2.dictify()
        assert c1 == c2
        assert a1 == a2

    #NEW:
    def compile_at(idx: int):
        outputs[idx] = compile(routers[idx])

    def main():
        threads = [threading.Thread(target=compile_at, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        while Compilation.ready_to_unpause < N:
            time.sleep(0.1)

        Compilation.paused = False


    # ORIG:
    # async def compile_at(idx: int):
    #     outputs[idx] = compile(routers[idx])

    # async def main():
    #     await asyncio.gather(*(compile_at(i) for i in range(N)))
    #     while Compilation.ready_to_unpause < N:
    #         asyncio.sleep(0.1)
    #     Compilation.paused = False

    # asyncio.run(main())

    main()

    for i in range(1, N):
        assert_sameness(i-1, i)

