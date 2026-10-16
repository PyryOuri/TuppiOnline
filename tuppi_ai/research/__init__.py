"""Isolated research implementations for the C0-C5 programme.

Nothing in this package is imported by the live factory (`tuppi_ai.best`), the
server or the existing evaluators, and nothing here edits them. The design is
`audit_deliverables/tuppi_implementation_plan/IMPLEMENTATION_SPEC.md`; progress
and evidence are recorded in `audit_deliverables/tuppi_implementation_output/`.

Module-level imports stay dependency-light (no engine, no native library) so
that pure pieces can also run in an isolated oracle process under a different
environment.
"""
