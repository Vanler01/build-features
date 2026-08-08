"""Scientific calculator REPL, in the spirit of a Casio fx-991ES PLUS.

Expressions are parsed to an AST and walked against an allowlist of node types.
The previous version used ``eval(expr, {"__builtins__": None}, safe_env)``, which
is not a sandbox: with no builtins at all, this still works ::

    [c for c in ().__class__.__base__.__subclasses__()
     if c.__name__ == '_wrap_close'][0].__init__.__globals__

That hands back the ``os`` module's globals, including ``__import__``, from a
plain expression a user can type at the prompt. Attribute access is the escape
hatch, so the fix is to never evaluate an attribute: ``ast.Attribute``,
``ast.Subscript``, comprehensions, lambdas and every other node outside the
allowlist below are rejected before anything is computed.

Two behaviours also follow the real calculator rather than Python:

* ``log`` is base 10 and ``ln`` is natural. Python's ``math.log`` is natural, so
  the old build answered ``log(100)`` with 4.605 instead of 2 -- silently, which
  is the worst way for a calculator to be wrong.
* ``^`` raises to a power. In Python it is bitwise XOR, so ``2^3`` used to give
  1 rather than 8, again with no error.
"""

from __future__ import annotations

import ast
import cmath
import math
from collections.abc import Callable
from typing import Any

Number = int | float | complex

# Guards against a single keystroke hanging the REPL. 9**9**9 is not a typo a
# calculator should take thirty seconds to refuse.
MAX_EXPONENT = 1_000
MAX_FACTORIAL = 1_000

DEG = "DEG"
RAD = "RAD"


class CalcError(Exception):
    """A problem with the user's expression, phrased for the user."""


# --- functions -------------------------------------------------------------


def _factorial(x: Number) -> int:
    """Factorial, accepting a whole-valued float the way a calculator does."""
    if isinstance(x, complex):
        raise CalcError("factorial needs a whole number")
    if x < 0 or (isinstance(x, float) and not x.is_integer()):
        raise CalcError("factorial needs a non-negative whole number")
    n = int(x)
    if n > MAX_FACTORIAL:
        raise CalcError(f"factorial is capped at {MAX_FACTORIAL}")
    return math.factorial(n)


def _ncr(n: Number, r: Number) -> int:
    """Combinations, the fx-991ES nCr key."""
    return math.comb(int(n), int(r))


def _npr(n: Number, r: Number) -> int:
    """Permutations, the fx-991ES nPr key."""
    return math.perm(int(n), int(r))


def _cbrt(x: Number) -> Number:
    """Cube root, including of negative numbers (the fx-991ES ∛ key)."""
    if isinstance(x, complex):
        return x ** (1 / 3)
    return math.copysign(abs(x) ** (1 / 3), x)


def _build_functions(angle_mode: str) -> dict[str, Callable[..., Any]]:
    """Build the function table for the current angle mode.

    Trig is the only thing the mode touches: a real fx-991ES applies DEG/RAD to
    the trig keys and nothing else.
    """
    to_native = math.radians if angle_mode == DEG else (lambda x: x)
    from_native = math.degrees if angle_mode == DEG else (lambda x: x)

    return {
        # trig, mode-aware
        "sin": lambda x: math.sin(to_native(x)),
        "cos": lambda x: math.cos(to_native(x)),
        "tan": lambda x: math.tan(to_native(x)),
        "asin": lambda x: from_native(math.asin(x)),
        "acos": lambda x: from_native(math.acos(x)),
        "atan": lambda x: from_native(math.atan(x)),
        # hyperbolic (always radians, as on the real thing)
        "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
        "asinh": math.asinh, "acosh": math.acosh, "atanh": math.atanh,
        # logs — calculator conventions, not Python's
        "log": math.log10,
        "ln": math.log,
        "log10": math.log10,
        "log2": math.log2,
        "logb": lambda b, x: math.log(x, b),
        # roots and powers
        "sqrt": math.sqrt,
        "cbrt": _cbrt,
        "csqrt": cmath.sqrt,
        "exp": math.exp,
        # rounding and sign
        "abs": abs, "round": round, "floor": math.floor, "ceil": math.ceil,
        "trunc": math.trunc,
        # combinatorics
        "fact": _factorial, "factorial": _factorial, "ncr": _ncr, "npr": _npr,
        # conversions
        "degrees": math.degrees, "radians": math.radians,
        "gcd": math.gcd, "hypot": math.hypot,
    }


CONSTANTS: dict[str, Number] = {"pi": math.pi, "e": math.e, "tau": math.tau}

_BINARY: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a**b,
    # On a calculator ^ is a power key, not bitwise XOR.
    ast.BitXor: lambda a, b: a**b,
}

_UNARY: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.UAdd: lambda a: +a,
    ast.USub: lambda a: -a,
}


# --- evaluation ------------------------------------------------------------


class Calculator:
    """Evaluates expressions against an allowlisted AST."""

    def __init__(self, angle_mode: str = RAD) -> None:
        """Start in the given angle mode, remembering nothing yet."""
        self.angle_mode = angle_mode
        self.ans: Number = 0
        self._functions = _build_functions(angle_mode)

    def set_angle_mode(self, mode: str) -> None:
        """Switch between DEG and RAD, rebuilding the trig table."""
        self.angle_mode = mode
        self._functions = _build_functions(mode)

    def evaluate(self, expression: str) -> Number:
        """Evaluate one expression and remember it as ``ans``."""
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise CalcError("check the formatting of that expression") from exc

        value = self._eval(tree.body)
        self.ans = value
        return value

    def _eval(self, node: ast.AST) -> Any:
        """Evaluate one allowlisted node, refusing everything else."""
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(
                node.value, int | float | complex
            ):
                raise CalcError("only numbers are allowed")
            return node.value

        if isinstance(node, ast.Name):
            if node.id in CONSTANTS:
                return CONSTANTS[node.id]
            if node.id == "ans":
                return self.ans
            raise CalcError(f"{node.id!r} isn't a known function or constant")

        if isinstance(node, ast.BinOp):
            op = _BINARY.get(type(node.op))
            if op is None:
                raise CalcError(f"{type(node.op).__name__} isn't supported")
            left, right = self._eval(node.left), self._eval(node.right)
            if type(node.op) in (ast.Pow, ast.BitXor):
                self._guard_power(left, right)
            return op(left, right)

        if isinstance(node, ast.UnaryOp):
            op = _UNARY.get(type(node.op))
            if op is None:
                raise CalcError(f"{type(node.op).__name__} isn't supported")
            return op(self._eval(node.operand))

        if isinstance(node, ast.Call):
            return self._eval_call(node)

        # Everything else -- Attribute, Subscript, Lambda, comprehensions,
        # walrus, f-strings -- lands here. Attribute in particular is the whole
        # eval escape, so this branch is the security boundary.
        raise CalcError(f"{type(node).__name__} isn't allowed in an expression")

    def _eval_call(self, node: ast.Call) -> Any:
        if not isinstance(node.func, ast.Name):
            # Blocks obj.method(...) outright, so there is no way to reach an
            # attribute even via a call.
            raise CalcError("only plain function calls are allowed")
        if node.keywords:
            raise CalcError("keyword arguments aren't supported")

        function = self._functions.get(node.func.id)
        if function is None:
            raise CalcError(f"{node.func.id!r} isn't a known function")

        args = [self._eval(arg) for arg in node.args]
        try:
            return function(*args)
        except CalcError:
            raise
        except ValueError as exc:
            raise CalcError(
                f"{node.func.id} can't take that value — "
                "for roots of negatives try csqrt()"
            ) from exc
        except TypeError as exc:
            raise CalcError(f"{node.func.id} got the wrong number of arguments") from exc
        except OverflowError as exc:
            raise CalcError("that result is too large to represent") from exc

    @staticmethod
    def _guard_power(base: Any, exponent: Any) -> None:
        """Refuse powers that would hang the process rather than answer."""
        if isinstance(exponent, complex) or isinstance(base, complex):
            return
        if abs(exponent) > MAX_EXPONENT and abs(base) > 1:
            raise CalcError(f"exponent is capped at {MAX_EXPONENT}")


# --- presentation ----------------------------------------------------------


def format_result(value: Number) -> str:
    """Render a result the way a calculator display would."""
    if isinstance(value, complex):
        if value.imag == 0:
            return format_result(value.real)
        return f"{value.real:g} {'+' if value.imag >= 0 else '-'} {abs(value.imag):g}i"
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e16:
            return str(int(value))
        return f"{value:.10g}"
    return str(value)


HELP = """\
--- Supported ---
Arithmetic   + - * / // % ** and ^ (both are powers, as on the calculator)
Trig         sin cos tan asin acos atan          (respects DEG/RAD mode)
Hyperbolic   sinh cosh tanh asinh acosh atanh    (always radians)
Logs         log (base 10)   ln (natural)   log2   logb(base, x)
Roots        sqrt  cbrt  csqrt (complex, for negatives)  exp
Rounding     round floor ceil trunc abs
Combinatorics fact(n)  ncr(n, r)  npr(n, r)
Other        degrees radians gcd hypot
Constants    pi  e  tau  ans (your last result)
Complex      write 2 + 3j

--- Commands ---
deg / rad    switch angle mode      help    this list
ans          reuse the last result  quit    exit
"""


def main() -> None:
    """Run the interactive prompt."""
    calc = Calculator(RAD)
    print("Scientific calculator (fx-991ES PLUS inspired)")
    print("Example: sin(pi/2) + sqrt(16) * log(100)")
    print("Type 'help' for the function list, 'quit' to exit.\n")

    while True:
        try:
            raw = input(f"Calc [{calc.angle_mode}] > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return

        lowered = raw.lower()
        if not raw:
            continue
        if lowered in ("quit", "exit", "q"):
            print("Bye.")
            return
        if lowered == "help":
            print(HELP)
            continue
        if lowered in ("deg", "rad"):
            calc.set_angle_mode(DEG if lowered == "deg" else RAD)
            print(f"Angle mode: {calc.angle_mode}\n")
            continue

        try:
            print(f"= {format_result(calc.evaluate(raw))}\n")
        except CalcError as exc:
            print(f"[Error] {exc}\n")
        except ZeroDivisionError:
            print("[Error] division by zero\n")
        except OverflowError:
            print("[Error] that result is too large to represent\n")
        except RecursionError:
            print("[Error] that expression is nested too deeply\n")


if __name__ == "__main__":
    main()
