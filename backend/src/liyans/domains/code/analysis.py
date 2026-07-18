from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass

import numpy as np
from liyans_contracts.topic3 import CodeFileV1

_APPROVED_IMPORTS = frozenset(
    {
        "math",
        "numpy",
        "numpy.linalg",
        "scipy",
        "scipy.signal",
        "control",
        "matplotlib",
        "matplotlib.pyplot",
    }
)
_DENIED_MODULES = frozenset(
    {
        "builtins",
        "ctypes",
        "importlib",
        "marshal",
        "multiprocessing",
        "os",
        "pathlib",
        "pickle",
        "requests",
        "shutil",
        "socket",
        "subprocess",
        "sys",
        "tempfile",
        "urllib",
    }
)
_DENIED_CALLS = frozenset(
    {
        "__import__",
        "breakpoint",
        "compile",
        "eval",
        "exec",
        "input",
        "open",
    }
)
_SIMULATION_CALLS = frozenset(
    {
        "control.forced_response",
        "control.initial_response",
        "control.lsim",
        "control.step_response",
        "lsim",
        "ode",
        "odeint",
        "sim",
        "solve_ivp",
        "step",
    }
)
_MODEL_CALLS = frozenset(
    {
        "control.StateSpace",
        "control.TransferFunction",
        "control.tf",
        "signal.StateSpace",
        "signal.TransferFunction",
        "signal.tf",
        "tf",
    }
)
_STABLE_SIGNAL = re.compile(
    r"(?:\bstable\b|\bstability\b|\bconverge|\bbounded\b|\bdecay|\bsettling\b|"
    r"(?<!\u4e0d)\u7a33\u5b9a|\u6536\u655b|\u6709\u754c|\u8870\u51cf|\u8c03\u8282)",
    re.IGNORECASE,
)
_UNSTABLE_SIGNAL = re.compile(
    r"(?:unstable|diverge|divergent|\u53d1\u6563|\u4e0d\u7a33\u5b9a)",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


@dataclass(frozen=True, slots=True)
class FileAnalysis:
    path: str
    syntax_valid: bool
    static_analysis_passed: bool
    finding_codes: tuple[str, ...]
    dependencies: tuple[str, ...]
    model_detected: bool
    simulation_detected: bool
    time_grid_size: int | None
    poles: tuple[complex, ...]


@dataclass(frozen=True, slots=True)
class CodeAnalysis:
    files: tuple[FileAnalysis, ...]
    finding_codes: tuple[str, ...]
    dependencies: tuple[str, ...]
    syntax_valid: bool
    static_analysis_passed: bool
    model_detected: bool
    simulation_detected: bool
    time_grid_size: int | None
    poles: tuple[complex, ...]
    stable_claimed: bool
    unstable_claimed: bool


class PythonStaticAnalyzer:
    def __init__(self, *, max_nodes: int = 50_000, max_loop_iterations: int = 1_000_000) -> None:
        if not 1 <= max_nodes <= 100_000:
            raise ValueError("max_nodes must be between 1 and 100000")
        if not 1 <= max_loop_iterations <= 10_000_000:
            raise ValueError("max_loop_iterations must be between 1 and 10000000")
        self.max_nodes = max_nodes
        self.max_loop_iterations = max_loop_iterations

    def analyze(self, file: CodeFileV1) -> FileAnalysis:
        findings: set[str] = set()
        dependencies: set[str] = set()
        try:
            tree = ast.parse(file.content, filename=file.path, mode="exec")
        except SyntaxError:
            return FileAnalysis(
                file.path, False, False, ("C6_PYTHON_SYNTAX_INVALID",), (), False, False, None, ()
            )
        nodes = list(ast.walk(tree))
        literals = self._literal_assignments(tree)
        if len(nodes) > self.max_nodes:
            findings.add("C6_AST_NODE_LIMIT")
        model_detected = False
        simulation_detected = False
        time_grid_size: int | None = None
        poles: list[complex] = []
        for node in nodes:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name
                    dependencies.add(module.split(".")[0])
                    self._validate_import(module, findings)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                dependencies.add(module.split(".")[0] if module else "")
                self._validate_import(module, findings)
            elif isinstance(node, ast.While):
                findings.add("C6_UNBOUNDED_WHILE_LOOP")
            elif isinstance(node, ast.For):
                if self._range_iterations(node.iter) is None:
                    findings.add("C6_UNBOUNDED_FOR_LOOP")
                elif self._range_iterations(node.iter) > self.max_loop_iterations:
                    findings.add("C6_LOOP_LIMIT")
            elif isinstance(node, ast.Constant):
                if isinstance(node.value, (int, float, complex)) and not isinstance(
                    node.value, bool
                ):
                    if not self._finite_bounded(node.value):
                        findings.add("C6_NUMERIC_BOUND_EXCEEDED")
            elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
                findings.add("C6_DUNDER_ACCESS_BLOCKED")
            elif isinstance(node, ast.Call):
                call_name = self._call_name(node.func)
                if call_name in _DENIED_CALLS or call_name.rsplit(".", 1)[-1] in _DENIED_CALLS:
                    findings.add("C6_DANGEROUS_CALL")
                if call_name and any(
                    call_name == module or call_name.startswith(f"{module}.")
                    for module in _DENIED_MODULES
                ):
                    findings.add("C6_DANGEROUS_CALL")
                if call_name in _MODEL_CALLS or call_name.rsplit(".", 1)[-1] == "tf":
                    model_detected = True
                    poles.extend(self._literal_denominator_poles(node, literals))
                if call_name in _SIMULATION_CALLS or call_name.rsplit(".", 1)[-1] in {
                    "step",
                    "lsim",
                    "solve_ivp",
                }:
                    simulation_detected = True
                if call_name.rsplit(".", 1)[-1] in {"linspace", "arange"}:
                    time_grid_size = self._grid_size(node) or time_grid_size
                if call_name.startswith("numpy.random") or call_name.startswith("np.random"):
                    if not self._seeded_random_call(node):
                        findings.add("C6_NONDETERMINISTIC_RANDOM")
        dependencies.discard("")
        return FileAnalysis(
            path=file.path,
            syntax_valid=True,
            static_analysis_passed=not findings,
            finding_codes=tuple(sorted(findings)),
            dependencies=tuple(sorted(dependencies)),
            model_detected=model_detected,
            simulation_detected=simulation_detected,
            time_grid_size=time_grid_size,
            poles=tuple(poles),
        )

    @staticmethod
    def _validate_import(module: str, findings: set[str]) -> None:
        root = module.split(".")[0]
        if root in _DENIED_MODULES or module in _DENIED_MODULES:
            findings.add("C6_DANGEROUS_IMPORT")
        elif module not in _APPROVED_IMPORTS and root not in {
            value.split(".")[0] for value in _APPROVED_IMPORTS
        }:
            findings.add("C6_UNAPPROVED_IMPORT")

    @staticmethod
    def _call_name(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            prefix = PythonStaticAnalyzer._call_name(node.value)
            return f"{prefix}.{node.attr}" if prefix else node.attr
        return ""

    @staticmethod
    def _finite_bounded(value: int | float | complex) -> bool:
        if isinstance(value, complex):
            return math.isfinite(value.real) and math.isfinite(value.imag) and abs(value) <= 1e100
        return math.isfinite(float(value)) and abs(float(value)) <= 1e100

    @staticmethod
    def _range_iterations(node: ast.AST) -> int | None:
        if not isinstance(node, ast.Call) or PythonStaticAnalyzer._call_name(node.func) != "range":
            return None
        try:
            values = [int(ast.literal_eval(arg)) for arg in node.args]
        except (ValueError, TypeError, SyntaxError):
            return None
        if len(values) == 1:
            start, stop, step = 0, values[0], 1
        elif len(values) == 2:
            start, stop = values
            step = 1
        elif len(values) == 3:
            start, stop, step = values
        else:
            return None
        if step == 0:
            return None
        return len(range(start, stop, step))

    @staticmethod
    def _grid_size(node: ast.Call) -> int | None:
        if len(node.args) >= 3:
            try:
                return int(ast.literal_eval(node.args[2]))
            except (ValueError, TypeError, SyntaxError):
                return None
        return None

    @staticmethod
    def _seeded_random_call(node: ast.Call) -> bool:
        name = PythonStaticAnalyzer._call_name(node.func)
        if name.endswith("default_rng") or name.endswith("seed"):
            return bool(node.args) and isinstance(node.args[0], ast.Constant)
        return False

    @staticmethod
    def _literal_assignments(tree: ast.Module) -> dict[str, object]:
        values: dict[str, object] = {}
        for statement in tree.body:
            if (
                isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
            ):
                try:
                    values[statement.targets[0].id] = ast.literal_eval(statement.value)
                except (ValueError, TypeError, SyntaxError):
                    continue
        return values

    @staticmethod
    def _literal_denominator_poles(
        node: ast.Call,
        literals: dict[str, object],
    ) -> list[complex]:
        if len(node.args) < 2:
            return []
        try:
            denominator_node = node.args[1]
            denominator = (
                literals.get(denominator_node.id)
                if isinstance(denominator_node, ast.Name)
                else ast.literal_eval(denominator_node)
            )
            coefficients = [float(value) for value in denominator]
            if not coefficients or not all(math.isfinite(value) for value in coefficients):
                return []
            return [complex(value) for value in np.roots(coefficients)]
        except (ValueError, TypeError, SyntaxError, np.linalg.LinAlgError):
            return []


class MatlabStaticAnalyzer:
    def analyze(self, file: CodeFileV1) -> FileAnalysis:
        source = self._without_comments(file.content)
        findings: set[str] = set()
        if not self._balanced(source):
            findings.add("C6_MATLAB_DELIMITER_INVALID")
        lowered = source.casefold()
        if re.search(
            r"(?m)^\s*(?:!|system\s*\(|unix\s*\(|dos\s*\(|webread\s*\(|"
            r"webwrite\s*\(|fopen\s*\(|delete\s*\(|rmdir\s*\(|movefile\s*\(|"
            r"copyfile\s*\(|eval\s*\(|feval\s*\(|load\s*\(|save\s*\()",
            lowered,
        ):
            findings.add("C6_MATLAB_DANGEROUS_OPERATION")
        if re.search(r"(?m)^\s*while\b", lowered):
            findings.add("C6_UNBOUNDED_WHILE_LOOP")
        if lowered.count("function") != lowered.count("end") and "function" in lowered:
            findings.add("C6_MATLAB_BLOCK_TERMINATOR_MISMATCH")
        if self._for_iterations(source) is None and re.search(r"(?m)^\s*for\b", lowered):
            findings.add("C6_UNBOUNDED_FOR_LOOP")
        model_detected = bool(re.search(r"\b(?:tf|ss|zpk)\s*\(", lowered))
        simulation_detected = bool(
            re.search(r"\b(?:step|lsim|sim|ode45|ode15s|plot)\s*\(", lowered)
        )
        time_grid_size = self._time_grid_size(source)
        poles = self._literal_poles(source)
        return FileAnalysis(
            path=file.path,
            syntax_valid=not any(
                code in findings
                for code in {
                    "C6_MATLAB_DELIMITER_INVALID",
                    "C6_MATLAB_BLOCK_TERMINATOR_MISMATCH",
                }
            ),
            static_analysis_passed=not findings,
            finding_codes=tuple(sorted(findings)),
            dependencies=(),
            model_detected=model_detected,
            simulation_detected=simulation_detected,
            time_grid_size=time_grid_size,
            poles=tuple(poles),
        )

    @staticmethod
    def _without_comments(source: str) -> str:
        return re.sub(r"%[^\n\r]*", "", source)

    @staticmethod
    def _balanced(source: str) -> bool:
        pairs = {")": "(", "]": "[", "}": "{"}
        stack: list[str] = []
        for char in source:
            if char in "([{":
                stack.append(char)
            elif char in pairs:
                if not stack or stack.pop() != pairs[char]:
                    return False
        return not stack

    @staticmethod
    def _for_iterations(source: str) -> int | None:
        match = re.search(
            r"(?mi)^\s*for\s+\w+\s*=\s*([-+]?\d+(?:\.\d+)?)\s*:\s*"
            r"([-+]?\d+(?:\.\d+)?)\s*:\s*([-+]?\d+(?:\.\d+)?)",
            source,
        )
        if match is None:
            return None
        start, step, stop = (float(value) for value in match.groups())
        if step == 0:
            return None
        return max(0, int(math.floor((stop - start) / step)) + 1)

    @staticmethod
    def _time_grid_size(source: str) -> int | None:
        match = re.search(
            r"\blinspace\s*\([^,]+,[^,]+,\s*(\d+)\s*\)|"
            r"\b(?:t|time)\s*=\s*[-+]?\d+\s*:\s*[-+]?\d+(?:\.\d+)?\s*:\s*[-+]?\d+",
            source,
            re.IGNORECASE,
        )
        if match is None:
            return None
        return int(match.group(1)) if match.group(1) else 1000

    @staticmethod
    def _literal_poles(source: str) -> list[complex]:
        match = re.search(
            r"\btf\s*\(\s*\[[^\]]*\]\s*,\s*\[([^\]]+)\]\s*\)",
            source,
            re.IGNORECASE,
        )
        if match is None:
            return []
        try:
            coefficients = [float(value) for value in _NUMBER.findall(match.group(1))]
            return [complex(value) for value in np.roots(coefficients)]
        except (ValueError, TypeError, np.linalg.LinAlgError):
            return []


class CodeStaticAnalyzer:
    def __init__(
        self,
        *,
        max_nodes: int = 50_000,
        max_loop_iterations: int = 1_000_000,
        max_time_grid: int = 1_000_000,
    ) -> None:
        if not 1 <= max_time_grid <= 10_000_000:
            raise ValueError("max_time_grid must be between 1 and 10000000")
        self.python = PythonStaticAnalyzer(
            max_nodes=max_nodes,
            max_loop_iterations=max_loop_iterations,
        )
        self.matlab = MatlabStaticAnalyzer()
        self.max_time_grid = max_time_grid

    def analyze(
        self,
        files: tuple[CodeFileV1, ...],
        *,
        stable_claimed: bool,
        unstable_claimed: bool,
    ) -> CodeAnalysis:
        analyses = tuple(
            self.python.analyze(file) if file.language == "python" else self.matlab.analyze(file)
            for file in files
        )
        codes = {code for result in analyses for code in result.finding_codes}
        time_sizes = [result.time_grid_size for result in analyses if result.time_grid_size]
        time_grid_size = max(time_sizes, default=None)
        if time_grid_size is not None and time_grid_size > self.max_time_grid:
            codes.add("C6_TIME_GRID_LIMIT")
        model_detected = any(result.model_detected for result in analyses)
        simulation_detected = any(result.simulation_detected for result in analyses)
        poles = tuple(pole for result in analyses for pole in result.poles)
        if not model_detected:
            codes.add("C6_CONTROL_MODEL_MISSING")
        if not simulation_detected:
            codes.add("C6_SIMULATION_FLOW_MISSING")
        if (stable_claimed or unstable_claimed) and model_detected and not poles:
            codes.add("C6_STABILITY_UNRESOLVED")
        if stable_claimed and any(pole.real >= -1e-9 for pole in poles):
            codes.add("C6_STABILITY_CONTRADICTION")
        if unstable_claimed and poles and all(pole.real < -1e-9 for pole in poles):
            codes.add("C6_UNSTABLE_CLAIM_CONTRADICTION")
        return CodeAnalysis(
            files=analyses,
            finding_codes=tuple(sorted(codes)),
            dependencies=tuple(sorted({dep for result in analyses for dep in result.dependencies})),
            syntax_valid=all(result.syntax_valid for result in analyses),
            static_analysis_passed=all(result.static_analysis_passed for result in analyses)
            and not codes,
            model_detected=model_detected,
            simulation_detected=simulation_detected,
            time_grid_size=time_grid_size,
            poles=poles,
            stable_claimed=stable_claimed,
            unstable_claimed=unstable_claimed,
        )


def claims_stability(text: str) -> tuple[bool, bool]:
    return bool(_STABLE_SIGNAL.search(text)), bool(_UNSTABLE_SIGNAL.search(text))
