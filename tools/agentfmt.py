#!/usr/bin/env python3
"""Old name of `oar`, the reference command line for OAR (Open Agent Recipe).

The tool was called `agentfmt` before the format was named. This alias keeps
`python3 agentfmt.py ...` and `import agentfmt` working: it is the same module as oar.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oar  # noqa: E402

if __name__ == "__main__":
    sys.exit(oar.main())
sys.modules[__name__] = oar
