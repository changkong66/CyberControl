from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid5

import sympy as sp
from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic4_c3 import (
    DerivationCheckResultV1,
    DerivationStepV1,
    EquivalenceMethod,
    FormulaEquivalenceResultV1,
    FormulaIRV1,
    NumericCounterexampleV1,
)
from liyans_contracts.topic4_common import VerificationVerdict
from sympy.core.function import AppliedUndef
from sympy.parsing.sympy_parser import (
    convert_xor,
    function_exponentiation,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

from liyans.domains.verification.records import build_topic4_record

PARSER_VERSION = "c3-sympy-parser-v1"
TOOLCHAIN_VERSION = f"sympy-{sp.__version__}-c3-v1"

_ALLOWED_EXPRESSION = re.compile(r"^[A-Za-z0-9_\s+\-*/^().,!<>=\\{}\[\]]+$")
_IDENTIFIER = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
_FUNCTION_CALL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_EXPONENT = re.compile(r"(?:\^|\*\*)\s*([-+]?\d+)")
_LONG_NUMBER = re.compile(r"\d{65,}")
_RELATION = re.compile(r"(<=|>=|!=|=|<|>)")
_MATH_BLOCK = re.compile(r"\$([^$]{1,8192})\$|\\\((.{1,8192}?)\\\)", re.DOTALL)
_PROSE_PREFIX = re.compile(
    r"^(?:\bfrom\b|\bwhere\b|\bequation\b|\bequals?\b|\bsatisf(?:y|ies)\b|"
    r"\bis\b|\bdefined\s+as\b|\bgiven\b|\u4e3a|\u5373|\u7531|\u6ee1\u8db3)"
    r"\s*[:\uff1a]?\s*",
    re.IGNORECASE,
)
_PROSE_SUFFIX = re.compile(
    r"\s+(?:is|are|when|where|therefore|thus|and|or|provided|has|"
    r"\u65f6|\u5219|\u56e0\u6b64)\b.*$",
    re.IGNORECASE,
)
_LEADING_PROSE = re.compile(
    r"^(?:the|a|an|formula|equation|expression|"
    r"\u516c\u5f0f|\u65b9\u7a0b|\u8868\u8fbe\u5f0f)\s+",
    re.IGNORECASE,
)
_MATH_PREFIX = re.compile(
    r"^(?:the\s+)?(?:characteristic\s+polynomial|polynomial|transfer\s+function|"
    r"formula|equation|expression|\u7279\u5f81\u591a\u9879\u5f0f|\u65b9\u7a0b|\u516c\u5f0f)\s+",
    re.IGNORECASE,
)
_FORBIDDEN_IDENTIFIERS = frozenset(
    {
        "compile",
        "eval",
        "exec",
        "getattr",
        "globals",
        "import",
        "lambda",
        "locals",
        "open",
        "setattr",
    }
)

_TRANSFORMATIONS = standard_transformations + (
    convert_xor,
    implicit_multiplication_application,
    function_exponentiation,
)
_KNOWN_FUNCTIONS: dict[str, object] = {
    "abs": sp.Abs,
    "acos": sp.acos,
    "asin": sp.asin,
    "atan": sp.atan,
    "cos": sp.cos,
    "cosh": sp.cosh,
    "exp": sp.exp,
    "log": sp.log,
    "ln": sp.log,
    "sin": sp.sin,
    "sinh": sp.sinh,
    "sqrt": sp.sqrt,
    "tan": sp.tan,
    "tanh": sp.tanh,
}
_CONSTANTS: dict[str, object] = {
    "E": sp.E,
    "I": sp.I,
    "e": sp.E,
    "pi": sp.pi,
}
_PARSE_GLOBALS: dict[str, object] = {
    "__builtins__": {},
    "Add": sp.Add,
    "Float": sp.Float,
    "Function": sp.Function,
    "Integer": sp.Integer,
    "Mul": sp.Mul,
    "Pow": sp.Pow,
    "Rational": sp.Rational,
    "Symbol": sp.Symbol,
}
_UNICODE_REPLACEMENTS = {
    "\u00d7": "*",
    "\u00f7": "/",
    "\u2212": "-",
    "\u2264": "<=",
    "\u2265": ">=",
    "\u03b1": "alpha",
    "\u03b2": "beta",
    "\u03b3": "gamma",
    "\u03b4": "delta",
    "\u03b5": "epsilon",
    "\u03b8": "theta",
    "\u03bb": "lam",
    "\u03bc": "mu",
    "\u03c0": "pi",
    "\u03c1": "rho",
    "\u03c3": "sigma",
    "\u03c6": "phi",
    "\u03c9": "omega",
}
_LATEX_REPLACEMENTS = {
    "\\alpha": "alpha",
    "\\beta": "beta",
    "\\cdot": "*",
    "\\chi": "chi",
    "\\delta": "delta",
    "\\epsilon": "epsilon",
    "\\eta": "eta",
    "\\gamma": "gamma",
    "\\kappa": "kappa",
    "\\lambda": "lam",
    "\\left": "",
    "\\mu": "mu",
    "\\nu": "nu",
    "\\omega": "omega",
    "\\phi": "phi",
    "\\pi": "pi",
    "\\psi": "psi",
    "\\rho": "rho",
    "\\right": "",
    "\\sigma": "sigma",
    "\\tau": "tau",
    "\\theta": "theta",
    "\\times": "*",
    "\\upsilon": "upsilon",
    "\\xi": "xi",
    "\\zeta": "zeta",
}


class FormulaSecurityError(ValueError):
    """Raised when an expression violates the deterministic parser policy."""


class FormulaParseError(ValueError):
    """Raised when a bounded expression cannot be represented by SymPy."""


@dataclass(frozen=True, slots=True)
class FormulaPolicy:
    max_expression_chars: int = 8192
    max_identifiers: int = 128
    max_operations: int = 2048
    max_parenthesis_depth: int = 32
    max_absolute_exponent: int = 32
    numeric_samples: int = 24
    tolerance: float = 1e-8

    def __post_init__(self) -> None:
        if not 1 <= self.max_expression_chars <= 8192:
            raise ValueError("max_expression_chars must be between 1 and 8192")
        if not 1 <= self.max_identifiers <= 512:
            raise ValueError("max_identifiers must be between 1 and 512")
        if not 1 <= self.max_operations <= 10_000:
            raise ValueError("max_operations must be between 1 and 10000")
        if not 1 <= self.max_parenthesis_depth <= 128:
            raise ValueError("max_parenthesis_depth must be between 1 and 128")
        if not 1 <= self.max_absolute_exponent <= 128:
            raise ValueError("max_absolute_exponent must be between 1 and 128")
        if not 1 <= self.numeric_samples <= 256:
            raise ValueError("numeric_samples must be between 1 and 256")
        if not math.isfinite(self.tolerance) or not 0 < self.tolerance <= 0.01:
            raise ValueError("tolerance must be finite and between zero and 0.01")


@dataclass(frozen=True, slots=True)
class ParsedFormula:
    original: str
    normalized: str
    relation: str | None
    expression: sp.Expr
    lhs: sp.Expr | None
    rhs: sp.Expr | None
    residual: sp.Expr
    canonical_expression: str
    symbols: dict[str, str]


class SafeFormulaParser:
    def __init__(self, policy: FormulaPolicy | None = None) -> None:
        self.policy = policy or FormulaPolicy()

    def parse(self, value: str) -> ParsedFormula:
        normalized = self._normalize(value)
        self._validate_source(normalized)
        left_text, relation, right_text = self._split_relation(normalized)
        local_dict = self._local_dictionary(normalized)
        try:
            left = self._parse_expression(left_text, local_dict)
            right = None if right_text is None else self._parse_expression(right_text, local_dict)
        except (SyntaxError, TypeError, ValueError, sp.SympifyError) as exc:
            raise FormulaParseError(
                "formula cannot be parsed by the bounded SymPy grammar"
            ) from exc
        residual = left if right is None else sp.Add(left, -right, evaluate=True)
        self._validate_tree(left)
        if right is not None:
            self._validate_tree(right)
        self._validate_tree(residual)
        canonical = self._canonical(left, relation, right, residual)
        symbols = self._symbols(residual)
        if len(symbols) > self.policy.max_identifiers:
            raise FormulaSecurityError("formula contains too many distinct symbols")
        return ParsedFormula(
            original=value,
            normalized=normalized,
            relation=relation,
            expression=left,
            lhs=left if right is not None else None,
            rhs=right,
            residual=residual,
            canonical_expression=canonical,
            symbols=symbols,
        )

    def extract(self, statement: str) -> tuple[str, ...]:
        if not isinstance(statement, str):
            raise FormulaParseError("formula source statement must be a string")
        candidates: list[str] = []
        for match in _MATH_BLOCK.finditer(statement):
            candidate = next(value for value in match.groups() if value is not None)
            self._append_parseable(candidates, candidate)
        if candidates:
            return tuple(candidates)
        windows = [statement]
        windows.extend(re.split(r"[\n\u3002\uff01\uff1f!?;\uff1b]+", statement))
        for window in windows:
            stripped = _LEADING_PROSE.sub("", window.strip())
            stripped = _MATH_PREFIX.sub("", stripped)
            stripped = _PROSE_PREFIX.sub("", stripped)
            stripped = _PROSE_SUFFIX.sub("", stripped)
            stripped = stripped.strip(" .;,:\uff0c\u3002\uff1b\uff1a")
            relation = _RELATION.search(stripped)
            has_operator = any(operator in stripped for operator in ("+", "-", "*", "/", "^"))
            if relation or has_operator:
                self._append_parseable(candidates, stripped)
            if relation:
                compact = self._compact_relation_window(stripped, relation)
                if not self._trivial_numeric_relation(compact):
                    self._append_parseable(candidates, compact)
            if len(candidates) >= 16:
                break
        if not candidates:
            for window in windows:
                stripped = _LEADING_PROSE.sub("", window.strip())
                stripped = _MATH_PREFIX.sub("", stripped)
                stripped = _PROSE_PREFIX.sub("", stripped)
                stripped = _PROSE_SUFFIX.sub("", stripped)
                if any(operator in stripped for operator in ("+", "-", "*", "/", "^")):
                    self._append_parseable(candidates, stripped)
                if candidates:
                    break
        return tuple(candidates)

    @staticmethod
    def _compact_relation_window(value: str, relation: re.Match[str]) -> str:
        left_tokens = value[: relation.start()].split()
        right_tokens = value[relation.end() :].split()
        if not left_tokens or not right_tokens:
            return ""
        return f"{left_tokens[-1]}{relation.group(1)}{right_tokens[0]}"

    @staticmethod
    def _trivial_numeric_relation(value: str) -> bool:
        match = re.fullmatch(r"[-+]?\d+(?:\.\d+)?(?:<=|>=|!=|=|<|>)[-+]?\d+(?:\.\d+)?", value)
        return match is not None

    def _append_parseable(self, target: list[str], candidate: str) -> None:
        candidate = candidate.strip()
        if not candidate or candidate in target:
            return
        try:
            self.parse(candidate)
        except (FormulaParseError, FormulaSecurityError):
            return
        target.append(candidate)

    def _normalize(self, value: str) -> str:
        if not isinstance(value, str):
            raise FormulaParseError("formula must be a string")
        normalized = unicodedata.normalize("NFKC", value).strip()
        if not normalized:
            raise FormulaParseError("formula cannot be blank")
        for source, replacement in _UNICODE_REPLACEMENTS.items():
            normalized = normalized.replace(source, replacement)
        for source, replacement in _LATEX_REPLACEMENTS.items():
            normalized = normalized.replace(source, replacement)
        normalized = self._replace_latex_fraction(normalized)
        normalized = self._replace_latex_sqrt(normalized)
        normalized = self._replace_latex_subscripts(normalized)
        return re.sub(r"\s+", " ", normalized).strip()

    @staticmethod
    def _replace_latex_fraction(value: str) -> str:
        pattern = re.compile(r"\\frac\{([^{}]+)\}\{([^{}]+)\}")
        for _ in range(8):
            replaced = pattern.sub(r"((\1)/(\2))", value)
            if replaced == value:
                break
            value = replaced
        return value

    @staticmethod
    def _replace_latex_sqrt(value: str) -> str:
        pattern = re.compile(r"\\sqrt\{([^{}]+)\}")
        for _ in range(8):
            replaced = pattern.sub(r"sqrt(\1)", value)
            if replaced == value:
                break
            value = replaced
        return value

    @staticmethod
    def _replace_latex_subscripts(value: str) -> str:
        value = re.sub(r"_\{([A-Za-z0-9]+)\}", r"_\1", value)
        return re.sub(r"\^\{([-+]?\d+)\}", r"^\1", value)

    def _validate_source(self, value: str) -> None:
        if len(value) > self.policy.max_expression_chars:
            raise FormulaSecurityError("formula exceeds the expression size limit")
        if not _ALLOWED_EXPRESSION.fullmatch(value):
            raise FormulaSecurityError("formula contains characters outside the safe grammar")
        lowered = value.casefold()
        identifiers = {identifier.casefold() for identifier in _IDENTIFIER.findall(lowered)}
        if "__" in lowered or identifiers & _FORBIDDEN_IDENTIFIERS:
            raise FormulaSecurityError("formula contains a forbidden identifier")
        if _LONG_NUMBER.search(value):
            raise FormulaSecurityError("formula contains an oversized numeric literal")

        opening_for = {")": "(", "]": "[", "}": "{"}
        delimiters: list[str] = []
        maximum_depth = 0
        for character in value:
            if character in "([{":
                delimiters.append(character)
                maximum_depth = max(maximum_depth, len(delimiters))
            elif character in opening_for:
                if not delimiters or delimiters[-1] != opening_for[character]:
                    raise FormulaParseError("formula delimiters are unbalanced")
                delimiters.pop()
        if delimiters:
            raise FormulaParseError("formula delimiters are unbalanced")
        if maximum_depth > self.policy.max_parenthesis_depth:
            raise FormulaSecurityError("formula nesting exceeds the safety limit")
        for raw_exponent in _EXPONENT.findall(value):
            if abs(int(raw_exponent)) > self.policy.max_absolute_exponent:
                raise FormulaSecurityError("formula exponent exceeds the safety limit")

    @staticmethod
    def _split_relation(value: str) -> tuple[str, str | None, str | None]:
        matches = list(_RELATION.finditer(value))
        if not matches:
            return value, None, None
        if len(matches) != 1:
            raise FormulaParseError("formula must contain at most one relation operator")
        match = matches[0]
        left = value[: match.start()].strip()
        right = value[match.end() :].strip()
        if not left or not right:
            raise FormulaParseError("formula relation requires both sides")
        return left, match.group(1), right

    def _local_dictionary(self, value: str) -> dict[str, object]:
        identifiers = set(_IDENTIFIER.findall(value))
        if len(identifiers) > self.policy.max_identifiers:
            raise FormulaSecurityError("formula contains too many identifiers")
        called = set(_FUNCTION_CALL.findall(value))
        local: dict[str, object] = dict(_CONSTANTS)
        for name in identifiers:
            if name in local:
                continue
            if name in _KNOWN_FUNCTIONS:
                local[name] = _KNOWN_FUNCTIONS[name]
            elif name in called:
                local[name] = sp.Function(name)
            else:
                local[name] = sp.Symbol(name, finite=True)
        return local

    @staticmethod
    def _parse_expression(value: str, local_dict: dict[str, object]) -> sp.Expr:
        parsed = parse_expr(
            value,
            local_dict=local_dict,
            global_dict=_PARSE_GLOBALS,
            transformations=_TRANSFORMATIONS,
            evaluate=True,
        )
        if not isinstance(parsed, sp.Expr):
            raise FormulaParseError("formula did not produce a scalar expression")
        return parsed

    def _validate_tree(self, expression: sp.Expr) -> None:
        operations = int(sp.count_ops(expression, visual=False))
        if operations > self.policy.max_operations:
            raise FormulaSecurityError("formula operation count exceeds the safety limit")
        if expression.has(sp.zoo, sp.nan, sp.oo, -sp.oo):
            raise FormulaParseError("formula contains a non-finite symbolic value")

    @staticmethod
    def _canonical(
        left: sp.Expr,
        relation: str | None,
        right: sp.Expr | None,
        residual: sp.Expr,
    ) -> str:
        if relation is None or right is None:
            return sp.sstr(left, order="lex")
        if relation == "=":
            return f"{sp.sstr(residual, order='lex')} = 0"
        return f"{sp.sstr(left, order='lex')} {relation} {sp.sstr(right, order='lex')}"

    @staticmethod
    def _symbols(expression: sp.Expr) -> dict[str, str]:
        symbols = {str(symbol): "SYMBOL" for symbol in sorted(expression.free_symbols, key=str)}
        functions = {
            str(function.func): "FUNCTION"
            for function in sorted(expression.atoms(AppliedUndef), key=str)
        }
        return {**symbols, **functions}


class FormulaIRBuilder:
    def __init__(self, parser: SafeFormulaParser | None = None) -> None:
        self.parser = parser or SafeFormulaParser()

    def build(
        self,
        expression: str,
        *,
        verification_id: UUID,
        claim_id: UUID,
        trace_id: str,
        tenant_id: str,
        created_at: datetime,
        assumptions: tuple[str, ...] = (),
        units: dict[str, str] | None = None,
    ) -> FormulaIRV1:
        parsed = self.parser.parse(expression)
        digest = canonical_sha256(
            {
                "canonical_expression": parsed.canonical_expression,
                "assumptions": list(assumptions),
                "units": units or {},
                "parser_version": PARSER_VERSION,
            }
        )
        return build_topic4_record(
            FormulaIRV1,
            trace_id=trace_id,
            tenant_id=tenant_id,
            version_cas=1,
            created_at=created_at,
            immutable=True,
            schema_version="formula-ir.v1",
            formula_ir_id=uuid5(claim_id, f"formula-ir:{digest}"),
            verification_id=verification_id,
            claim_id=claim_id,
            original_expression=expression,
            canonical_expression=parsed.canonical_expression,
            lhs_expression=None if parsed.lhs is None else sp.sstr(parsed.lhs, order="lex"),
            rhs_expression=None if parsed.rhs is None else sp.sstr(parsed.rhs, order="lex"),
            symbols=parsed.symbols,
            assumptions=list(assumptions),
            units={} if units is None else dict(units),
            parser_version=PARSER_VERSION,
            expression_sha256=digest,
        )


class FormulaEquivalenceEngine:
    def __init__(
        self,
        parser: SafeFormulaParser | None = None,
        *,
        policy: FormulaPolicy | None = None,
    ) -> None:
        self.policy = policy or FormulaPolicy()
        self.parser = parser or SafeFormulaParser(self.policy)

    def compare(
        self,
        left: FormulaIRV1,
        right: FormulaIRV1,
        *,
        trace_id: str,
        tenant_id: str,
        created_at: datetime,
    ) -> FormulaEquivalenceResultV1:
        self._validate_inputs(left, right, tenant_id)
        left_parsed = self.parser.parse(left.original_expression)
        right_parsed = self.parser.parse(right.original_expression)
        symbolic = self._symbolic_equivalence(left_parsed, right_parsed)
        if symbolic is True:
            equivalent = True
            method = EquivalenceMethod.SYMBOLIC
            sampled_points = 0
            counterexamples: list[NumericCounterexampleV1] = []
            verdict = VerificationVerdict.SUPPORTED
            confidence = 0.995
        else:
            sampled_points, counterexamples, numeric_decision = self._numeric_equivalence(
                left_parsed,
                right_parsed,
                trace_id=trace_id,
                tenant_id=tenant_id,
                created_at=created_at,
            )
            equivalent = numeric_decision is True
            method = EquivalenceMethod.HYBRID if symbolic is False else EquivalenceMethod.NUMERIC
            if numeric_decision is True:
                verdict = VerificationVerdict.SUPPORTED
                confidence = min(0.95, 0.75 + sampled_points / 200)
            elif numeric_decision is False:
                verdict = VerificationVerdict.CONTRADICTED
                confidence = min(0.995, 0.9 + len(counterexamples) / 100)
            else:
                verdict = VerificationVerdict.INSUFFICIENT_EVIDENCE
                confidence = 0.35
        result_id = uuid5(
            left.claim_id,
            f"formula-equivalence:{left.formula_ir_id}:{right.formula_ir_id}:{TOOLCHAIN_VERSION}",
        )
        return build_topic4_record(
            FormulaEquivalenceResultV1,
            trace_id=trace_id,
            tenant_id=tenant_id,
            version_cas=1,
            created_at=created_at,
            immutable=True,
            schema_version="formula-equivalence.result.v1",
            formula_equivalence_result_id=result_id,
            verification_id=left.verification_id,
            claim_id=left.claim_id,
            left_formula_ir_id=left.formula_ir_id,
            right_formula_ir_id=right.formula_ir_id,
            equivalent=equivalent,
            method=method,
            tolerance=self.policy.tolerance,
            sampled_points=sampled_points,
            counterexamples=counterexamples,
            verdict=verdict,
            confidence=confidence,
            toolchain_version=TOOLCHAIN_VERSION,
        )

    @staticmethod
    def _validate_inputs(left: FormulaIRV1, right: FormulaIRV1, tenant_id: str) -> None:
        if left.tenant_id != tenant_id or right.tenant_id != tenant_id:
            raise ValueError("formula equivalence cannot cross tenant boundaries")
        if left.verification_id != right.verification_id or left.claim_id != right.claim_id:
            raise ValueError("formula equivalence inputs must belong to the same claim")

    def _symbolic_equivalence(
        self,
        left: ParsedFormula,
        right: ParsedFormula,
    ) -> bool | None:
        if left.relation != right.relation:
            return None
        try:
            difference = sp.cancel(left.residual - right.residual)
            self.parser._validate_tree(difference)
            if difference == 0:
                return True
            ratio = sp.cancel(left.residual / right.residual)
            self.parser._validate_tree(ratio)
            if ratio == 0 or ratio.free_symbols or ratio.atoms(AppliedUndef):
                return False
            numeric_ratio = complex(sp.N(ratio, 16))
            if not math.isfinite(numeric_ratio.real) or not math.isfinite(numeric_ratio.imag):
                return None
            if abs(numeric_ratio.imag) > self.policy.tolerance:
                return False
            if left.relation in {None, "="}:
                return abs(numeric_ratio.real) > self.policy.tolerance
            return numeric_ratio.real > self.policy.tolerance
        except (
            FormulaParseError,
            FormulaSecurityError,
            ArithmeticError,
            TypeError,
            ValueError,
            ZeroDivisionError,
        ):
            return None

    def _numeric_equivalence(
        self,
        left: ParsedFormula,
        right: ParsedFormula,
        *,
        trace_id: str,
        tenant_id: str,
        created_at: datetime,
    ) -> tuple[int, list[NumericCounterexampleV1], bool | None]:
        if left.relation != right.relation:
            return 0, [], None
        if left.residual.atoms(AppliedUndef) or right.residual.atoms(AppliedUndef):
            return 0, [], None
        symbols = sorted(left.residual.free_symbols | right.residual.free_symbols, key=str)
        if len(symbols) > min(self.policy.max_identifiers, 16):
            return 0, [], None
        samples = 0
        counterexamples: list[NumericCounterexampleV1] = []
        for sample_index in range(max(1, self.policy.numeric_samples * 3)):
            assignments = self._assignments(symbols, sample_index)
            evaluated = self._evaluate_pair(left, right, assignments)
            if evaluated is None:
                continue
            left_value, right_value, matches = evaluated
            samples += 1
            absolute_error = abs(left_value - right_value)
            scale = max(1.0, abs(left_value), abs(right_value))
            relative_error = absolute_error / scale
            if not matches:
                counterexamples.append(
                    build_topic4_record(
                        NumericCounterexampleV1,
                        trace_id=trace_id,
                        tenant_id=tenant_id,
                        version_cas=1,
                        created_at=created_at,
                        immutable=True,
                        schema_version="numeric-counterexample.v1",
                        assignments={str(key): value for key, value in assignments.items()},
                        left_value=left_value,
                        right_value=right_value,
                        absolute_error=absolute_error,
                        relative_error=relative_error,
                    )
                )
                if len(counterexamples) >= 8:
                    break
            if samples >= self.policy.numeric_samples:
                break
        if counterexamples:
            return samples, counterexamples, False
        if left.relation is not None:
            return samples, [], None
        if samples >= max(4, self.policy.numeric_samples // 2):
            return samples, [], True
        return samples, [], None

    @staticmethod
    def _assignments(symbols: list[sp.Symbol], sample_index: int) -> dict[sp.Symbol, float]:
        values = (-3.0, -2.0, -1.25, -0.5, 0.25, 0.75, 1.5, 2.5, 4.0)
        return {
            symbol: values[(sample_index * 5 + ordinal * 3) % len(values)]
            for ordinal, symbol in enumerate(symbols)
        }

    def _evaluate_pair(
        self,
        left: ParsedFormula,
        right: ParsedFormula,
        assignments: dict[sp.Symbol, float],
    ) -> tuple[float, float, bool] | None:
        left_value = self._evaluate_scalar(left.residual, assignments)
        right_value = self._evaluate_scalar(right.residual, assignments)
        if left_value is None or right_value is None:
            return None
        if left.relation is None:
            scale = max(1.0, abs(left_value), abs(right_value))
            matches = abs(left_value - right_value) <= self.policy.tolerance * scale
        else:
            left_truth = self._relation_truth(left.relation, left_value)
            right_truth = self._relation_truth(right.relation, right_value)
            matches = left_truth == right_truth
        return left_value, right_value, matches

    @staticmethod
    def _evaluate_scalar(
        expression: sp.Expr,
        assignments: dict[sp.Symbol, float],
    ) -> float | None:
        try:
            value = complex(sp.N(expression.subs(assignments), 16))
        except (ArithmeticError, TypeError, ValueError, ZeroDivisionError):
            return None
        if not all(math.isfinite(item) and abs(item) <= 1e12 for item in (value.real, value.imag)):
            return None
        if abs(value.imag) > 1e-9:
            return None
        return float(value.real)

    def _relation_truth(self, relation: str | None, residual: float) -> bool:
        tolerance = self.policy.tolerance * max(1.0, abs(residual))
        if relation == "=":
            return abs(residual) <= tolerance
        if relation == "!=":
            return abs(residual) > tolerance
        if relation == "<":
            return residual < -tolerance
        if relation == "<=":
            return residual <= tolerance
        if relation == ">":
            return residual > tolerance
        if relation == ">=":
            return residual >= -tolerance
        raise ValueError("unsupported relation operator")


class DerivationChecker:
    def __init__(
        self,
        equivalence: FormulaEquivalenceEngine | None = None,
    ) -> None:
        self.equivalence = equivalence or FormulaEquivalenceEngine()

    def check(
        self,
        formulas: tuple[FormulaIRV1, ...],
        *,
        rule_names: tuple[str, ...] | None,
        trace_id: str,
        tenant_id: str,
        created_at: datetime,
    ) -> DerivationCheckResultV1:
        if not formulas:
            raise ValueError("derivation requires at least one formula")
        if any(formula.tenant_id != tenant_id for formula in formulas):
            raise ValueError("derivation cannot cross tenant boundaries")
        verification_id = formulas[0].verification_id
        claim_id = formulas[0].claim_id
        if any(
            formula.verification_id != verification_id or formula.claim_id != claim_id
            for formula in formulas
        ):
            raise ValueError("derivation formulas must belong to one claim")
        rules = rule_names or tuple("ALGEBRAIC_EQUIVALENCE" for _ in formulas)
        if len(rules) != len(formulas):
            raise ValueError("derivation rule count must match formula count")
        steps: list[DerivationStepV1] = []
        confidence = 0.995
        for ordinal, (formula, rule_name) in enumerate(zip(formulas, rules, strict=True)):
            if not rule_name or len(rule_name) > 256:
                raise ValueError("derivation rule names must contain 1 to 256 characters")
            valid = True
            finding_code = None
            if ordinal > 0:
                result = self.equivalence.compare(
                    formulas[ordinal - 1],
                    formula,
                    trace_id=trace_id,
                    tenant_id=tenant_id,
                    created_at=created_at,
                )
                valid = result.equivalent
                confidence = min(confidence, result.confidence)
                if not valid:
                    finding_code = (
                        "C3_DERIVATION_NOT_EQUIVALENT"
                        if result.verdict == VerificationVerdict.CONTRADICTED
                        else "C3_DERIVATION_UNPROVEN"
                    )
            steps.append(
                build_topic4_record(
                    DerivationStepV1,
                    trace_id=trace_id,
                    tenant_id=tenant_id,
                    version_cas=1,
                    created_at=created_at,
                    immutable=True,
                    schema_version="derivation-step.v1",
                    ordinal=ordinal,
                    formula_ir_id=formula.formula_ir_id,
                    rule_name=rule_name,
                    valid_from_previous=valid,
                    finding_code=finding_code,
                )
            )
        invalid = [step.ordinal for step in steps if not step.valid_from_previous]
        first_invalid = invalid[0] if invalid else None
        verdict = (
            VerificationVerdict.SUPPORTED
            if first_invalid is None
            else VerificationVerdict.CONTRADICTED
        )
        result_id = uuid5(
            claim_id,
            "derivation:" + canonical_sha256([formula.record_sha256 for formula in formulas]),
        )
        return build_topic4_record(
            DerivationCheckResultV1,
            trace_id=trace_id,
            tenant_id=tenant_id,
            version_cas=1,
            created_at=created_at,
            immutable=True,
            schema_version="derivation-check.result.v1",
            derivation_check_result_id=result_id,
            verification_id=verification_id,
            claim_id=claim_id,
            steps=steps,
            first_invalid_ordinal=first_invalid,
            conclusion_formula_ir_id=formulas[-1].formula_ir_id,
            verdict=verdict,
            confidence=confidence if first_invalid is None else max(0.8, confidence),
        )
