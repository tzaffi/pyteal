import asyncio
from functools import reduce
from itertools import groupby # type: ignore
import pytest

from pyteal import compileTeal, Mode
from examples.signature.factorizer_game import logicsig

# implicitly import via no_regrassions:
# from examples.application.abi.algobank import router

from tests.compile_asserts import assert_new_v_old, assert_teal_as_expected
from tests.integration.graviton_test import (
    FIXTURES,
    GENERATED,
    ISSUE_199_CASES as ISSUE_199_CASES_BB,
    wrap_compile_and_save,
)
from tests.unit.sourcemap_test import no_regressions
from tests.unit.pass_by_ref_test import ISSUE_199_CASES

SKIPS = {
    1: True,
    2: True,
    3: False,
    4: True,
}
NUM_REPEATS_FOR_T3 = 2
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
def algobank():
    global is_algobank_first_time
    expected_lines, actual_lines = no_regressions(skip_final_assertion=True)
    if ASSERT_ALGOBANK_AGAINST_FIXED:
        assert expected_lines == actual_lines, "bailing out early!!!"

    return_value = expected_lines if is_algobank_first_time else actual_lines
    is_algobank_first_time = False
    return "\n".join(return_value)


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
@pytest.mark.parametrize("expr", [lsig345, algobank])
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

    assert (
        False
    ), f"At the end of the day, this was unstable with {len(teals_gb)} distinct compilations"


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
