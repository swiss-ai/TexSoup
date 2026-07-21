Parser Architecture
===================

TexSoup is being hardened as an executable specification for an incremental
Rust parser rewrite. Keep changes aligned with these boundaries.

Core Parser
-----------

The core parser starts at ``TexSoup.pipeline.read_core``. It takes already
prepared source and performs only:

* categorization
* tokenization
* grammar/tree construction

Core behavior belongs in ``category.py``, ``tokens.py``, ``reader.py``, and the
tree model in ``data.py``. Rust parity tests should target this boundary first:
same prepared input, same normalized tree/string output, same strict/tolerant
error behavior.

Use ``TexSoup.spec.to_spec`` for golden comparisons. It serializes the Python
tree into primitive dictionaries/lists so another implementation can be checked
without depending on Python object internals.

Feature Passes
--------------

Source-level convenience and corpus hardening live outside the core parser.
Today that layer is ``TexSoup.pipeline.standardize_source`` (also available as
the older ``prepare_source`` name) plus feature modules such as ``macros.py``.
These passes may rewrite source before tokenization, but they must be
independently testable and disableable.

Examples:

* simple macro expansion
* source normalization for known corpus idioms
* optional compatibility passes for arXiv-style packages

Case Handling
-------------

Special-case recovery should be isolated where possible. If a case is a normal
part of TeX syntax, add it to the core with parity tests. If it is a corpus
compatibility feature, keep it as a feature pass or a narrowly scoped special
argument/environment reader with a regression test that names the failure mode.

Rust Rewrite Plan
-----------------

1. Match ``read_core`` on focused grammar fixtures.
2. Match ``read_core`` on golden real-paper snippets with ``to_spec`` output.
3. Add source feature passes one by one, starting with macro expansion.
4. Run the same benchmark paper sets and artifact audits against both engines.
5. Only then replace the Python core in the public ``TexSoup`` entry point.
