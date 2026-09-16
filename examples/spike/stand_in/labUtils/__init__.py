"""A stand-in for the lab's `labUtils`. **Not the real library.**

Same module paths, same callables, same argument names; arithmetic simple
enough to verify by eye. It exists so the platform can be exercised end to end
without the lab's private package, and so a failure in the spike is a failure
in the platform rather than in science code nobody here can read.

Standard library only. Anything else would have to be installed into the
mounted directory for the container's architecture, which is a distraction
from what the spike is measuring.
"""

__all__ = ["growth_rates", "media_bot"]
