"""Tests for the fx-991ES PLUS calculator.

Run explicitly, from the repo root::

    python3 -m pytest test_casio.py -q

Not a bare ``pytest``: the daemon submodules carry their own test trees with
colliding module names, so an unscoped collection from here fails before it
reaches this file.

The module is loaded through importlib because its filename contains spaces and
so cannot be imported by name. Renaming it to ``casio_fx991es_plus.py`` would
remove that wrinkle, but the file is a runnable REPL rather than a library, so
it isn't worth changing out from under anyone.

The sandbox section is the reason this file exists. The previous build used
``eval`` with ``{"__builtins__": None}`` and a comment asserting that was safe;
it wasn't, and nothing would have caught it. These tests fail loudly if
attribute access ever becomes reachable again.
"""

from __future__ import annotations

import ast
import importlib.util
import math
import pathlib

import pytest

_PATH = pathlib.Path(__file__).parent / "casio fx-991es plus.py"
_spec = importlib.util.spec_from_file_location("casio_calc", _PATH)
assert _spec is not None and _spec.loader is not None
casio = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(casio)

CalcError = casio.CalcError


@pytest.fixture
def calc() -> object:
    return casio.Calculator()


# --- the sandbox -----------------------------------------------------------
#
# Each payload below is a real escape idiom. The second one is the exact
# expression that recovered os.__globals__ (and therefore __import__) from the
# previous build.

ESCAPES = [
    "().__class__",
    "().__class__.__base__.__subclasses__()",
    "[c for c in ().__class__.__base__.__subclasses__() "
    "if c.__name__=='_wrap_close'][0].__init__.__globals__",
    "(1).__class__.__mro__[1].__subclasses__()",
    "''.__class__.__mro__[1].__subclasses__()",
    "__import__('os').system('echo pwned')",
    "__import__('subprocess').run(['echo','pwned'])",
    "open('/etc/passwd').read()",
    "(lambda: 1)()",
    "[x for x in (1, 2)]",
    "{k: 1 for k in (1, 2)}",
    "(x for x in (1, 2))",
    "globals()",
    "locals()",
    "vars()",
    "getattr(pi, 'real')",
    "help.__call__()",
    "pi.__class__",
    "[1, 2][0]",
    "{'a': 1}['a']",
    "(1).bit_length()",
    "sqrt.__globals__",
]


@pytest.mark.parametrize("payload", ESCAPES)
def test_escape_attempts_are_refused(calc: object, payload: str) -> None:
    """No expression may reach an attribute, a subscript or a builtin."""
    with pytest.raises(CalcError):
        calc.evaluate(payload)


def test_the_exact_escape_that_worked_before_is_dead(calc: object) -> None:
    """Regression pin for the specific payload verified against the old build."""
    payload = (
        "[c for c in ().__class__.__base__.__subclasses__() "
        "if c.__name__ == '_wrap_close'][0].__init__.__globals__"
    )
    with pytest.raises(CalcError, match="Attribute isn't allowed"):
        calc.evaluate(payload)


def test_source_calls_no_eval_exec_or_compile() -> None:
    """Belt and braces: the escape existed for exactly as long as eval() did.

    Guards against a later convenience change reintroducing it. Checked against
    the parsed AST rather than the text, so the module docstring's description
    of the old vulnerability doesn't trip it -- a text search does, which is how
    this test first failed.
    """
    tree = ast.parse(_PATH.read_text())
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    forbidden = called & {"eval", "exec", "compile", "__import__", "open", "input"}
    # input() is legitimate in the REPL loop; everything else is not.
    assert forbidden <= {"input"}, f"calculator calls {sorted(forbidden - {'input'})}"


def test_strings_are_rejected_as_values(calc: object) -> None:
    with pytest.raises(CalcError, match="only numbers"):
        calc.evaluate("'abc'")


def test_unknown_names_are_rejected(calc: object) -> None:
    with pytest.raises(CalcError, match="isn't a known function or constant"):
        calc.evaluate("os")


def test_unknown_functions_are_rejected(calc: object) -> None:
    with pytest.raises(CalcError, match="isn't a known function"):
        calc.evaluate("system(1)")


# --- the two silent wrong answers -----------------------------------------


def test_log_is_base_ten(calc: object) -> None:
    """The old build answered 4.605 — Python's natural log — with no error."""
    assert calc.evaluate("log(100)") == pytest.approx(2)
    assert calc.evaluate("log(1000)") == pytest.approx(3)


def test_ln_is_natural(calc: object) -> None:
    assert calc.evaluate("ln(e)") == pytest.approx(1)


def test_log_and_ln_are_not_the_same_function(calc: object) -> None:
    assert calc.evaluate("log(100)") != pytest.approx(calc.evaluate("ln(100)"))


def test_caret_is_a_power_not_xor(calc: object) -> None:
    """The old build answered 1 for 2^3, because ^ is XOR in Python."""
    assert calc.evaluate("2^3") == 8
    assert calc.evaluate("2^10") == 1024


def test_caret_and_double_star_agree(calc: object) -> None:
    assert calc.evaluate("3^4") == calc.evaluate("3**4")


# --- arithmetic ------------------------------------------------------------


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1 + 2 * 3", 7),
        ("(1 + 2) * 3", 9),
        ("7 / 2", 3.5),
        ("7 // 2", 3),
        ("7 % 3", 1),
        ("-5 + 3", -2),
        ("+4", 4),
        ("2 ** 0.5", math.sqrt(2)),
        ("sqrt(16)", 4),
        ("cbrt(-27)", -3),
        ("abs(-3)", 3),
        ("hypot(3, 4)", 5),
        ("gcd(12, 18)", 6),
        ("logb(2, 1024)", 10),
        ("fact(5)", 120),
        ("ncr(10, 3)", 120),
        ("npr(5, 2)", 20),
        ("floor(2.7)", 2),
        ("ceil(2.1)", 3),
        ("round(2.567, 2)", 2.57),
    ],
)
def test_arithmetic(calc: object, expression: str, expected: float) -> None:
    assert calc.evaluate(expression) == pytest.approx(expected)


def test_worked_example_from_the_banner(calc: object) -> None:
    """sin(pi/2) + sqrt(16) * log(100) — 1 + 4*2."""
    assert calc.evaluate("sin(pi/2) + sqrt(16) * log(100)") == pytest.approx(9)


def test_constants(calc: object) -> None:
    assert calc.evaluate("pi") == pytest.approx(math.pi)
    assert calc.evaluate("e") == pytest.approx(math.e)
    assert calc.evaluate("tau") == pytest.approx(math.tau)


# --- angle modes -----------------------------------------------------------


def test_default_mode_is_radians(calc: object) -> None:
    assert calc.angle_mode == casio.RAD
    assert calc.evaluate("sin(pi/2)") == pytest.approx(1)


def test_degree_mode_applies_to_trig(calc: object) -> None:
    calc.set_angle_mode(casio.DEG)
    assert calc.evaluate("sin(90)") == pytest.approx(1)
    assert calc.evaluate("cos(0)") == pytest.approx(1)


def test_degree_mode_inverts_correctly(calc: object) -> None:
    calc.set_angle_mode(casio.DEG)
    assert calc.evaluate("asin(1)") == pytest.approx(90)
    assert calc.evaluate("atan(1)") == pytest.approx(45)


def test_hyperbolic_ignores_angle_mode(calc: object) -> None:
    """As on the real unit — DEG/RAD is a trig setting, not a global one."""
    calc.set_angle_mode(casio.DEG)
    assert calc.evaluate("sinh(1)") == pytest.approx(math.sinh(1))


def test_switching_modes_takes_effect_immediately(calc: object) -> None:
    rad = calc.evaluate("sin(90)")
    calc.set_angle_mode(casio.DEG)
    assert calc.evaluate("sin(90)") != pytest.approx(rad)


# --- ans -------------------------------------------------------------------


def test_ans_starts_at_zero(calc: object) -> None:
    assert calc.evaluate("ans") == 0


def test_ans_carries_the_previous_result(calc: object) -> None:
    calc.evaluate("6 * 7")
    assert calc.evaluate("ans") == 42
    assert calc.evaluate("ans + 8") == 50


def test_a_failed_expression_leaves_ans_alone(calc: object) -> None:
    """A typo must not silently destroy the value you were building on."""
    calc.evaluate("10")
    with pytest.raises(CalcError):
        calc.evaluate("bogus(1)")
    assert calc.evaluate("ans") == 10


# --- complex numbers -------------------------------------------------------


def test_csqrt_handles_negatives(calc: object) -> None:
    assert calc.evaluate("csqrt(-4)") == pytest.approx(complex(0, 2))


def test_sqrt_of_a_negative_is_an_error_that_suggests_csqrt(calc: object) -> None:
    with pytest.raises(CalcError, match="csqrt"):
        calc.evaluate("sqrt(-4)")


def test_complex_literals(calc: object) -> None:
    assert calc.evaluate("2 + 3j") == complex(2, 3)


# --- hang guards -----------------------------------------------------------


def test_absurd_exponent_is_refused_not_computed(calc: object) -> None:
    """9**9**9 would otherwise wedge the prompt rather than answer."""
    with pytest.raises(CalcError, match="exponent is capped"):
        calc.evaluate("9**9**9")


def test_absurd_factorial_is_refused(calc: object) -> None:
    with pytest.raises(CalcError, match="factorial is capped"):
        calc.evaluate("fact(999999)")


def test_small_exponents_still_work(calc: object) -> None:
    """The guard must not get in the way of ordinary use."""
    assert calc.evaluate("2**100") == 2**100


def test_negative_factorial_is_refused(calc: object) -> None:
    with pytest.raises(CalcError, match="non-negative"):
        calc.evaluate("fact(-1)")


def test_fractional_factorial_is_refused(calc: object) -> None:
    with pytest.raises(CalcError, match="whole number"):
        calc.evaluate("fact(2.5)")


# --- errors ----------------------------------------------------------------


def test_syntax_error_is_phrased_for_a_person(calc: object) -> None:
    with pytest.raises(CalcError, match="check the formatting"):
        calc.evaluate("2 +* 3")


def test_division_by_zero_propagates_for_the_repl_to_catch(calc: object) -> None:
    with pytest.raises(ZeroDivisionError):
        calc.evaluate("1/0")


def test_wrong_argument_count_is_reported(calc: object) -> None:
    with pytest.raises(CalcError, match="wrong number of arguments"):
        calc.evaluate("sqrt(1, 2)")


def test_keyword_arguments_are_refused(calc: object) -> None:
    with pytest.raises(CalcError, match="keyword arguments"):
        calc.evaluate("round(2.5, ndigits=1)")


def test_domain_error_is_reported(calc: object) -> None:
    with pytest.raises(CalcError):
        calc.evaluate("ln(-1)")


# --- display ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        (4.0, "4"),
        (-4.0, "-4"),
        (0.5, "0.5"),
        (120, "120"),
        (complex(0, 2), "0 + 2i"),
        (complex(2, -3), "2 - 3i"),
        (complex(5, 0), "5"),
    ],
)
def test_result_formatting(value: object, shown: str) -> None:
    """Complex results read as 2 + 3i, not Python's (2+3j)."""
    assert casio.format_result(value) == shown


def test_large_float_keeps_precision_not_scientific_int(calc: object) -> None:
    assert casio.format_result(calc.evaluate("2**0.5")) == "1.414213562"
