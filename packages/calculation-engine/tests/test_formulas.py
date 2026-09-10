"""Restricted formula grammar and typed execution (ADR-0018)."""

from dataclasses import replace
from decimal import ROUND_DOWN, Decimal, localcontext

import pytest
from _fixtures import CUTOFF, Q1, USD, assumption, formula, revenue_model, source

import fel_calculation_engine as calc
from fel_calculation_engine import RATIO, FormulaError, GraphSnapshot, Operator, Quantity, evaluate


def expression(node_id, text, *, unit=RATIO, period=Q1):
    return calc.ExpressionFormulaNode.from_expression(
        node_id=node_id,
        label=node_id,
        unit=unit,
        period=period,
        expression=text,
        formula_version="v1",
    )


def test_parser_precedence_unary_punctuation_repeated_references():
    assert hasattr(calc, "parse_formula"), "restricted formula parser is missing"
    ast = calc.parse_formula(" -[revenue.us:2024-Q1] + 2 * (+[x] - .5) / 3 ")
    assert calc.formula_dependencies(ast) == ("revenue.us:2024-Q1", "x")
    assert calc.evaluate_formula(
        ast,
        {
            "revenue.us:2024-Q1": Quantity(Decimal("2"), RATIO),
            "x": Quantity(Decimal("5"), RATIO),
        },
    ) == Quantity(Decimal("1"), RATIO)
    node = expression("twice", "[x] + [x]")
    assert node.inputs() == (("reference[0]", "x"),)
    run = evaluate(GraphSnapshot.build("m", [assumption("x", "2"), node]), cutoff=CUTOFF)
    assert run.quantity("twice").value == 4
    assert len(run.result("twice").input_result_ids) == 1


@pytest.mark.parametrize(
    "text",
    [
        "",
        "1 + 2",
        "x + 2",
        "[x].value",
        "[x][0]",
        "__import__('os')",
        "True",
        "[x] ** 2",
        "[x] // 2",
        "[x] = 2",
        "[x] < 2",
        "[x] + NaN",
        "[x] + Infinity",
        "[x] +",
        "([x]",
        "[bad id]",
        "[]",
        "[x] + 1e250001",
        "[x]+1e-250001",
        "[x] + 1.0000000000000000000000000000000001",
        " " * 4097,
        "(" * 65 + "[x]" + ")" * 65,
        "-" * 65 + "[x]",
        "+".join(["[x]"] * 258),
    ],
)
def test_invalid_or_excessive_text_is_a_typed_offset_error(text):
    assert hasattr(calc, "parse_formula"), "restricted formula parser is missing"
    with pytest.raises(FormulaError) as exc:
        calc.parse_formula(text)
    assert isinstance(exc.value.details["offset"], int)


def test_direct_ast_is_closed_and_bounded_and_rewrite_is_structural():
    assert hasattr(calc, "Reference"), "closed typed AST is missing"
    with pytest.raises(FormulaError):
        calc.Binary("**", calc.Reference("x"), calc.Literal(Decimal("2")))
    with pytest.raises(FormulaError):
        calc.Unary("-", "x")
    with pytest.raises(FormulaError):
        calc.Literal(Decimal("NaN"))
    ast = calc.parse_formula("[x] + [xx]")
    rewired = calc.rewrite_formula_references(ast, {"x": "x--bull"})
    assert calc.formula_dependencies(rewired) == ("x--bull", "xx")
    assert calc.formula_dependencies(ast) == ("x", "xx")
    for _ in range(63):
        ast = calc.Unary("-", ast) if _ < 62 else ast
    with pytest.raises(FormulaError):
        calc.Unary("-", ast)


def test_expression_units_periods_and_pinned_decimal_context():
    assert hasattr(calc, "ExpressionFormulaNode"), "expression node is missing"
    node = expression("z", "-[x] * (1 + [growth])", unit=USD)
    snap = GraphSnapshot.build(
        "m", [source("x", "1.234567890123456789012345678901234"), assumption("growth", "0.5"), node]
    )
    expected = evaluate(snap, cutoff=CUTOFF)
    with localcontext() as ambient:
        ambient.prec = 3
        ambient.rounding = ROUND_DOWN
        actual = evaluate(snap, cutoff=CUTOFF)
    assert actual == expected
    assert actual.quantity("z").value == Decimal("-1.851851835185185183518518518351851")
    with pytest.raises(calc.UnitError):
        GraphSnapshot.build("m", [source("x", "2"), expression("z", "[x]+1", unit=USD)])
    with pytest.raises(calc.PeriodError):
        GraphSnapshot.build(
            "m", [assumption("x", "2"), expression("z", "[x]*2", period=calc.FiscalYear(2024))]
        )
    with pytest.raises(FormulaError):
        evaluate(
            GraphSnapshot.build("m", [assumption("x", "2"), expression("z", "[x]/0")]),
            cutoff=CUTOFF,
        )


def test_expression_identity_whitespace_version_and_legacy_payload():
    assert hasattr(calc, "ExpressionFormulaNode"), "expression node is missing"
    nodes = [assumption("x", "2"), expression("z", "[x] * 2")]
    a = GraphSnapshot.build("m", nodes)
    b = GraphSnapshot.build("m", [nodes[0], expression("z", " [x]*2.0 ")])
    assert a.snapshot_id == b.snapshot_id
    assert a.payload()["schema"] == "fel-calc-snapshot/v2"
    assert (
        GraphSnapshot.build("legacy", revenue_model()).payload()["schema"] == "fel-calc-snapshot/v1"
    )
    assert a.snapshot_id != a.with_nodes([replace(nodes[1], formula_version="v2")]).snapshot_id
    old = formula("z", Operator.MUL, ("x", "two"), unit=RATIO)
    snap = GraphSnapshot.build("m", [nodes[0], assumption("two", "2"), old])
    assert evaluate(a, cutoff=CUTOFF).quantity("z") == evaluate(snap, cutoff=CUTOFF).quantity("z")
