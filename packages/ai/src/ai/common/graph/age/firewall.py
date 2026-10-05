# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# =============================================================================

"""Query firewall for the Cypher -> AGE pipeline.

Two rule families, applied per the design:

- **Resource caps** — enforced on BOTH paths (safe and raw EXECUTE). Raw
  execute skips *semantic* checks, never resource limits: a runaway traversal
  is just as expensive when a trusted app submits it. The database-side
  backstop is a ``statement_timeout`` the emitter sets per transaction.
- **Semantic rules** — safe path only. Writes and procedure CALLs are
  rejected here before translation; the true guard is the read-only
  transaction the node runs safe queries in (server-side, like FalkorDB's
  RO_QUERY), with this check giving precise, pre-flight errors.
- **Qualified calls** — both paths. The safe path rejects every
  schema-qualified function call (``ns.fn(...)``): it runs the built-in Cypher
  functions only. The raw path admits a qualified function only when its name
  is on an explicit allowlist (empty by default) and gates every CALLed
  procedure the same way.

Caps are constructor arguments; the node currently wires only
``statement_timeout_ms`` through its config (``query_timeout_ms`` in
services.json) and leaves the rest at these defaults, which were
sanity-checked against the pinned AGE 1.5.0 container.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet, Tuple

from .analysis import CypherFacts
from .errors import AgeFirewallRejected

# Defaults tuned against the pinned container (see the layer README):
# unbounded/deep variable-length traversals are the main resource hazard —
# AGE expands them recursively; depth 10 on a connected graph is already huge.
DEFAULT_MAX_QUERY_LENGTH = 10_000
DEFAULT_MAX_VAR_LENGTH_DEPTH = 10
DEFAULT_STATEMENT_TIMEOUT_MS = 30_000
# The ANTLR parser burns ~14 stack frames per expression nesting level, so
# Python's default recursion limit trips around 70 nested parens. 50 keeps a
# deterministic, well-messaged rejection comfortably below that cliff.
DEFAULT_MAX_NESTING_DEPTH = 50


@dataclass(frozen=True)
class FirewallConfig:
    max_query_length: int = DEFAULT_MAX_QUERY_LENGTH
    max_var_length_depth: int = DEFAULT_MAX_VAR_LENGTH_DEPTH
    max_nesting_depth: int = DEFAULT_MAX_NESTING_DEPTH
    # Applied by the emitter as SET LOCAL statement_timeout in the query's
    # transaction — the database-side resource backstop for both paths.
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS
    # Raw (execute) path only: exact ``schema.function`` names that may be
    # called qualified, or CALLed as procedures. Compared segment by segment,
    # case-sensitively, after back-quote unescaping. Never consulted on the safe
    # path, and empty by default.
    allowed_qualified_functions: FrozenSet[str] = field(default_factory=frozenset)


def check_pre_parse(cypher: str, config: FirewallConfig) -> None:
    """Caps that must run BEFORE the parse — both paths.

    The ANTLR parse is the expensive step these caps exist to bound (linear
    CPU in query length; stack depth in expression nesting), so checking them
    after ``analyze()`` would defeat their purpose. Character scans only —
    no parser involvement. Raises AgeFirewallRejected on violation.

    The nesting scan counts brackets inside string literals too; a legitimate
    string containing 50+ consecutive open brackets is contrived enough that
    the deterministic pre-parse rejection is the better trade.
    """
    if len(cypher) > config.max_query_length:
        raise AgeFirewallRejected(
            'max_query_length',
            f'query is {len(cypher)} chars (limit {config.max_query_length})',
        )
    depth = 0
    for ch in cypher:
        if ch in '([{':
            depth += 1
            if depth > config.max_nesting_depth:
                raise AgeFirewallRejected(
                    'max_nesting_depth',
                    f'expression nesting exceeds {config.max_nesting_depth} levels '
                    '(reduce parenthesis/bracket nesting)',
                )
        elif ch in ')]}':
            depth = max(0, depth - 1)


def check_resource_caps(facts: CypherFacts, config: FirewallConfig) -> None:
    """Resource caps — both paths. Raises AgeFirewallRejected on violation."""
    if len(facts.query) > config.max_query_length:
        raise AgeFirewallRejected(
            'max_query_length',
            f'query is {len(facts.query)} chars (limit {config.max_query_length})',
        )

    for lower, upper in facts.var_length_ranges:
        if upper is None:
            raise AgeFirewallRejected(
                'unbounded_var_length',
                f'variable-length pattern without an upper bound (use e.g. *1..{config.max_var_length_depth})',
            )
        if upper > config.max_var_length_depth:
            raise AgeFirewallRejected(
                'max_var_length_depth',
                f'variable-length upper bound {upper} exceeds limit {config.max_var_length_depth}',
            )
        if lower is not None and lower > upper:
            raise AgeFirewallRejected('invalid_var_length_range', f'lower bound {lower} exceeds upper bound {upper}')


def check_semantics_readonly(facts: CypherFacts) -> None:
    """Semantic rules — safe path only. Rejects writes and procedure CALLs."""
    if facts.write_clauses:
        clauses = ', '.join(sorted(facts.write_clauses))
        raise AgeFirewallRejected(
            'write_clause',
            f'{clauses} not allowed on the read-only path (use the execute path for writes)',
        )
    if facts.has_call:
        raise AgeFirewallRejected('procedure_call', 'CALL is not allowed on the read-only path')


def _display(segments: Tuple[str, ...]) -> str:
    return '.'.join(segments)


def _allowed(segments: Tuple[str, ...], config: FirewallConfig) -> bool:
    return any(tuple(entry.split('.')) == segments for entry in config.allowed_qualified_functions)


def check_qualified_calls(facts: CypherFacts, config: FirewallConfig, *, safe: bool) -> None:
    """Gate schema-qualified function calls (both paths) and raw-path procedures.

    Safe path: every qualified function call is rejected, wherever it sits in
    the statement (the facts come from a full parse-tree walk). Procedure CALLs
    are left to :func:`check_semantics_readonly`, which rejects them all.

    Raw path: a qualified function call, or any CALLed procedure, must match an
    entry of ``config.allowed_qualified_functions`` exactly.
    """
    for segments in facts.qualified_functions:
        if safe or not _allowed(segments, config):
            where = 'the read-only path' if safe else 'the execute path (not on its allowlist)'
            raise AgeFirewallRejected(
                'qualified_function',
                f'schema-qualified function call {_display(segments)}() is not allowed on {where}; '
                'use the built-in Cypher functions',
            )
    if safe:
        return
    for segments in facts.procedure_names:
        if not _allowed(segments, config):
            raise AgeFirewallRejected(
                'procedure_call',
                f'CALL {_display(segments)} is not allowed on the execute path (not on its allowlist)',
            )
