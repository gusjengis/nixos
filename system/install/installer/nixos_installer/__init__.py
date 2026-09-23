"""Interactive and non-interactive installer for this NixOS configuration.

Every decision the installer makes is available both as a command-line flag and
as a tab in the terminal interface. The two paths share one resolution step, so
a batch of machines can be installed from a single command line without the
interface ever appearing, and anything left unanswered falls back to the
configuration's own defaults rather than to a value invented here.
"""

__all__ = ["__version__"]

__version__ = "1.0.0"
