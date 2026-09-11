# Example pipelines

Worked examples that double as compiler fixtures. They are synthetic but
modelled on real pipelines, and between them they exercise every feature the
format has to support: a matrix, component reuse selected by a matrix
variable, all the fan-out kinds, `$WILL_PROVIDE$` public inputs, whole-value
substitution, and per-step overrides on an imported component.

`tests/domain/test_examples.py` compiles every file here. A change that breaks
one of them breaks the build, which is what stops the format drifting away
from what authors actually write.
