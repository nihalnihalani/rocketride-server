# =============================================================================
# RocketRide Engine
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

"""The Vector Explorer's additive tools on every vector store node (contract section 4.4).

``VectorExplorerExtTools`` is mixed into ``VectorStoreToolMixin`` (``document_store``)
ahead of ``VectorExplorerTools``, so every store node that answers the explorer's
tools also answers the tools defined here. It holds the tools that came after the
first contract: ``recommend`` (similar chunks from positive and negative example
keys) and ``similarity_matrix`` (the pairwise similarities of up to
``matrix_keys_max`` keys). Neither accepts or returns a stored vector.

Every tool here is written as the tools in ``vx_tools`` are:

* ``@tool_function(..., audience=('dap',))`` over ``@vx_tools.vectordb_tool``, so
  it is listed for external (DAP) callers only and an agent's tool catalog does
  not change;
* ``vx_write_gate.check_read()`` first (a read refused on a public key answers
  ``READS_PUBLIC``);
* inputs read with the ``vx_tools`` argument helpers and the limits of
  ``vx_defaults.VECTOR_TOOL_LIMITS`` (reported in ``dialect.limits``);
* the store reached through ``self._vx_store()`` (``VectorExplorerTools``, next in
  the method resolution order of the node).

This module may import from ``vx_tools`` (the wrapper, the argument helpers, the
``_vx_*`` plumbing); ``vx_tools`` never imports from it, so there is no import
cycle. The class is empty until those tools land; ``capabilities`` and
``dialect.limits`` already name what they will need.
"""

__all__ = ['VectorExplorerExtTools']


class VectorExplorerExtTools:
    """The Vector Explorer's additive tools; mixed into ``VectorStoreToolMixin`` before ``VectorExplorerTools``."""
