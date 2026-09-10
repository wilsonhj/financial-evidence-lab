"""Bounded arithmetic grammar v1. No executable Python or floating-point intermediates."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, DecimalException
from typing import TypeAlias

from fel_calculation_engine.errors import FormulaError, MissingInputError, ValueTypeError
from fel_calculation_engine.units import RATIO, Unit
from fel_calculation_engine.values import CALC_CONTEXT, Quantity, require_decimal, require_safe_id

GRAMMAR_VERSION = "fel-formula/v1"
MAX_EXPRESSION_LENGTH = 4096
MAX_AST_NODES = 512
MAX_AST_DEPTH = 64
_NUMBER = re.compile(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_OPERATIONS = {"+": "add", "-": "sub", "*": "mul", "/": "div"}


@dataclass(frozen=True, slots=True)
class Reference:
    node_id: str

    def __post_init__(self) -> None:
        require_safe_id(self.node_id, "reference", FormulaError)


@dataclass(frozen=True, slots=True)
class Literal:
    value: Decimal

    def __post_init__(self) -> None:
        try:
            require_decimal(self.value, "literal")
        except ValueTypeError as exc:
            raise FormulaError(exc.message) from exc
        exponent = self.value.as_tuple().exponent
        if isinstance(exponent, int) and not -250_000 <= exponent <= 250_000:
            raise FormulaError("literal exponent exceeds canonical Decimal bounds")


@dataclass(frozen=True, slots=True)
class Unary:
    operator: str
    operand: FormulaAST

    def __post_init__(self) -> None:
        validate_formula(self)


@dataclass(frozen=True, slots=True)
class Binary:
    operator: str
    left: FormulaAST
    right: FormulaAST

    def __post_init__(self) -> None:
        validate_formula(self)


FormulaAST: TypeAlias = Reference | Literal | Unary | Binary


def validate_formula(ast: FormulaAST) -> None:
    """Validate the closed tree and bounds, including directly constructed ASTs."""
    stack = [(ast, 1)]
    count = 0
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > MAX_AST_NODES or depth > MAX_AST_DEPTH:
            raise FormulaError("formula exceeds AST node or depth limit")
        if type(node) is Reference:
            Reference.__post_init__(node)
        elif type(node) is Literal:
            Literal.__post_init__(node)
        elif type(node) is Unary:
            if type(node.operator) is not str or node.operator not in ("+", "-"):
                raise FormulaError("unary operator must be + or -")
            stack.append((node.operand, depth + 1))
        elif type(node) is Binary:
            if type(node.operator) is not str or node.operator not in _OPERATIONS:
                raise FormulaError("binary operator must be +, -, * or /")
            stack.extend(((node.right, depth + 1), (node.left, depth + 1)))
        else:
            raise FormulaError("unsupported AST node type")


def formula_dependencies(ast: FormulaAST) -> tuple[str, ...]:
    validate_formula(ast)
    found: dict[str, None] = {}
    stack = [ast]
    while stack:
        node = stack.pop()
        if isinstance(node, Reference):
            found[node.node_id] = None
        elif isinstance(node, Unary):
            stack.append(node.operand)
        elif isinstance(node, Binary):
            stack.extend((node.right, node.left))
    return tuple(found)


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.offset = 0
        self.count = 0

    def peek(self) -> str:
        while self.offset < len(self.text) and self.text[self.offset].isspace():
            self.offset += 1
        return self.text[self.offset : self.offset + 1]

    def expression(self, minimum: int = 0, depth: int = 1) -> FormulaAST:
        if depth > MAX_AST_DEPTH:
            raise FormulaError("formula exceeds parse depth limit")
        char = self.peek()
        if char in ("+", "-"):
            self.offset += 1
            left: FormulaAST = Unary(char, self.expression(3, depth + 1))
        elif char == "(":
            self.offset += 1
            left = self.expression(0, depth + 1)
            if self.peek() != ")":
                raise FormulaError("expected closing parenthesis")
            self.offset += 1
        elif char == "[":
            end = self.text.find("]", self.offset + 1)
            if end < 0:
                raise FormulaError("expected closing reference bracket")
            left = Reference(self.text[self.offset + 1 : end])
            self.offset = end + 1
        else:
            number = _NUMBER.match(self.text, self.offset)
            if number is None:
                raise FormulaError("expected reference, literal or parenthesis")
            try:
                left = Literal(Decimal(number.group(), context=CALC_CONTEXT))
            except DecimalException as exc:
                raise FormulaError("literal cannot be represented as a finite Decimal") from exc
            self.offset = number.end()
        self.count += 1
        if self.count > MAX_AST_NODES:
            raise FormulaError("formula exceeds AST node limit")
        while True:
            char = self.peek()
            precedence = {"+": 1, "-": 1, "*": 2, "/": 2}.get(char, -1)
            if precedence < minimum:
                break
            self.offset += 1
            left = Binary(char, left, self.expression(precedence + 1, depth + 1))
            self.count += 1
            if self.count > MAX_AST_NODES:
                raise FormulaError("formula exceeds AST node limit")
        return left


def parse_formula(text: str) -> FormulaAST:
    if not isinstance(text, str) or len(text) > MAX_EXPRESSION_LENGTH:
        raise FormulaError("formula must be text of at most 4096 characters", offset=0)
    parser = _Parser(text)
    try:
        ast = parser.expression()
        if parser.peek():
            raise FormulaError("unexpected token")
        if not formula_dependencies(ast):
            raise FormulaError("a formula must reference at least one node")
        return ast
    except FormulaError as exc:
        exc.details.setdefault("offset", parser.offset)
        raise


def infer_formula_unit(ast: FormulaAST, units: Mapping[str, Unit]) -> Unit:
    validate_formula(ast)

    def infer(node: FormulaAST) -> Unit:
        if isinstance(node, Reference):
            try:
                return units[node.node_id]
            except KeyError as exc:
                raise MissingInputError("missing formula reference", missing=node.node_id) from exc
        if isinstance(node, Literal):
            return RATIO
        if isinstance(node, Unary):
            return infer(node.operand)
        left, right = infer(node.left), infer(node.right)
        return getattr(left, _OPERATIONS[node.operator])(right)  # type: ignore[no-any-return]

    return infer(ast)


def evaluate_formula(ast: FormulaAST, quantities: Mapping[str, Quantity]) -> Quantity:
    validate_formula(ast)

    def compute(node: FormulaAST) -> Quantity:
        if isinstance(node, Reference):
            try:
                return quantities[node.node_id]
            except KeyError as exc:
                raise MissingInputError("missing formula reference", missing=node.node_id) from exc
        if isinstance(node, Literal):
            return Quantity(node.value, RATIO)
        if isinstance(node, Unary):
            operand = compute(node.operand)
            # copy_negate is exact; plus pins any context rounding to the engine.
            value = operand.value if node.operator == "+" else operand.value.copy_negate()
            return Quantity(CALC_CONTEXT.plus(value), operand.unit)
        left, right = compute(node.left), compute(node.right)
        if node.operator == "+":
            return left + right
        if node.operator == "-":
            return left - right
        if node.operator == "*":
            return left * right
        return left / right

    try:
        return compute(ast)
    except DecimalException as exc:
        raise FormulaError("formula arithmetic failed", operation=type(exc).__name__) from exc


def rewrite_formula_references(ast: FormulaAST, mapping: Mapping[str, str]) -> FormulaAST:
    validate_formula(ast)

    def rewrite(node: FormulaAST) -> FormulaAST:
        if isinstance(node, Reference):
            return Reference(mapping.get(node.node_id, node.node_id))
        if isinstance(node, Literal):
            return node
        if isinstance(node, Unary):
            return Unary(node.operator, rewrite(node.operand))
        return Binary(node.operator, rewrite(node.left), rewrite(node.right))

    return rewrite(ast)


def format_formula(ast: FormulaAST) -> str:
    """Unambiguous display generated from the sole authoritative AST."""
    validate_formula(ast)

    def display(node: FormulaAST) -> str:
        if isinstance(node, Reference):
            return f"[{node.node_id}]"
        if isinstance(node, Literal):
            return str(node.value)
        if isinstance(node, Unary):
            return f"({node.operator}{display(node.operand)})"
        return f"({display(node.left)} {node.operator} {display(node.right)})"

    return display(ast)
