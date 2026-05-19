"""Single import point for helpers shared by more than one residual phase."""

from __future__ import annotations

# Re-export the canonical ``energy_cap`` from :mod:`roco.engine.kernel.actions`
# so residual modules do not need to know that the helper lives with the
# turn-action handlers.
from roco.engine.kernel.actions import energy_cap

__all__ = ["energy_cap"]
