"""AI assistant subpackage.

Isolated from the rest of the backend by design: everything under
``astock_backtester.ai`` depends only on ``models`` and the public ``data``
layer, never the other way around.  The AI module is strictly read-only over
the local warehouse and never participates in the candidate pipeline.
"""

from __future__ import annotations

from astock_backtester.ai.errors import AiError, AiNotConfigured, AiUpstreamError
from astock_backtester.ai.facade import AiService

__all__ = ["AiError", "AiNotConfigured", "AiService", "AiUpstreamError"]
