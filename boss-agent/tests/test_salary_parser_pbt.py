"""
Property-based tests and unit tests for Salary Parser.

# Feature: tools-api-docs-and-tests, Property 5: Salary Parse/Format Round-Trip

For any pair of positive integers (min_k, max_k) where min_k ≤ max_k,
calling format_salary(min_k, max_k) then parse_salary(result) SHALL return
(min_k, max_k, None). Conversely, for any salary string in "{min}-{max}K"
format, parse_salary then format_salary SHALL produce an equivalent string.

**Validates: Requirements 6.1, 6.4**
"""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from tools.getjob.platform_sync import format_salary, parse_salary

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Positive integers for salary values (K = 千元, realistic range 1-999)
st_salary_k = st.integers(min_value=1, max_value=999)

# Ordered pair (min_k, max_k) where min_k <= max_k
st_salary_pair = st.tuples(st_salary_k, st_salary_k).map(
    lambda t: (min(t), max(t))
)


# ---------------------------------------------------------------------------
# Property 5: Salary Parse/Format Round-Trip
# ---------------------------------------------------------------------------


class TestSalaryParseFormatRoundTrip:
    """
    # Feature: tools-api-docs-and-tests, Property 5: Salary Parse/Format Round-Trip

    **Validates: Requirements 6.1, 6.4**
    """

    @given(data=st_salary_pair)
    @settings(max_examples=100)
    def test_format_then_parse_round_trip(self, data: tuple[int, int]):
        """
        For any (min_k, max_k) with min_k <= max_k,
        format_salary(min_k, max_k) → parse_salary → (min_k, max_k, None).
        """
        min_k, max_k = data
        formatted = format_salary(min_k, max_k)
        parsed_min, parsed_max, parsed_months = parse_salary(formatted)
        assert parsed_min == min_k
        assert parsed_max == max_k
        assert parsed_months is None

    @given(data=st_salary_pair)
    @settings(max_examples=100)
    def test_parse_then_format_round_trip(self, data: tuple[int, int]):
        """
        For any salary string in "{min}-{max}K" format,
        parse_salary → format_salary produces an equivalent string.
        """
        min_k, max_k = data
        # Build a canonical "{min}-{max}K" string (or "{val}K" if equal)
        if min_k == max_k:
            salary_str = f"{min_k}K"
        else:
            salary_str = f"{min_k}-{max_k}K"

        parsed_min, parsed_max, _ = parse_salary(salary_str)
        assert parsed_min is not None
        assert parsed_max is not None
        re_formatted = format_salary(parsed_min, parsed_max)
        assert re_formatted == salary_str


# ---------------------------------------------------------------------------
# Unit tests: parse_salary edge cases
# ---------------------------------------------------------------------------


class TestParseSalaryEdgeCases:
    """Edge-case unit tests for parse_salary."""

    def test_negotiable(self):
        """'面议' returns (None, None, None)."""
        assert parse_salary("面议") == (None, None, None)

    def test_empty_string(self):
        """Empty string returns (None, None, None)."""
        assert parse_salary("") == (None, None, None)

    def test_none_input(self):
        """None input returns (None, None, None)."""
        assert parse_salary(None) == (None, None, None)

    def test_salary_with_months_suffix(self):
        """'25-50K·14薪' extracts salary_months=14."""
        result = parse_salary("25-50K·14薪")
        assert result == (25, 50, 14)

    def test_salary_with_13_months(self):
        """'15-25K·13薪' extracts salary_months=13."""
        result = parse_salary("15-25K·13薪")
        assert result == (15, 25, 13)

    def test_single_value(self):
        """'25K' parses as (25, 25, None)."""
        result = parse_salary("25K")
        assert result == (25, 25, None)

    def test_single_value_lowercase(self):
        """'25k' parses as (25, 25, None) — case insensitive."""
        result = parse_salary("25k")
        assert result == (25, 25, None)

    def test_range_with_both_k(self):
        """'25K-50K' parses correctly."""
        result = parse_salary("25K-50K")
        assert result == (25, 50, None)

    def test_whitespace_only(self):
        """Whitespace-only string returns (None, None, None)."""
        assert parse_salary("   ") == (None, None, None)
