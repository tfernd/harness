# Review lens: tensor code

For each row, run the exposing input; a finding needs the output that shows it (`harness:review`). Skip a row that does not apply.

| Fault | Exposing input |
|---|---|
| Annotations enforced? | is the import hook or `@jaxtyped` active in the tests; without it a shape mismatch raises nothing |
| Output axis free | an output of any length passes the type; read the signature for an axis bound nowhere |
| Silent broadcasting | shapes `(n, 1)` against `(n,)` with n at least 2; the batch law with 0, 1 and 2 leading axes |
| Wrong reduction axis | a non-square input with distinct prime sizes (2, 3, 5) |
| Integer wrap | the dtype's min and max; a Python bound outside the dtype |
| Promotion | uint8 minus uint8 below zero; an int tensor times a Python float; float16 mixed with float32 |
| Saturation on narrowing | the largest finite value, one step above it, the rounding midpoint |
| NaN passing a check | NaN through each comparison written `x < bound`; NaN through `min`, `max`, `argmax` |
| Signed zero, subnormals | `-0.0`, the smallest subnormal; compare bits, not values |
| Aliasing | call twice on one input and assert it is unchanged; an expanded or sliced view; a non-contiguous input before `.view` |
| Empty | a zero-length batch and a zero-length last axis |
| Device | without a GPU, run the function on `device="meta"` inputs: a CPU-made mask or constant raises `RuntimeError: Tensor on device meta is not on the expected device cpu!` (PROBED); with a GPU, compare bits with CPU |
| Ambient device | a factory (`zeros`, `arange`, `tensor`, `full`, `rand`) with no `device=` taking it from an input |
| Ties | two equal candidates; the earliest must win |
| Same-route oracle | an expected value built by the same calls as the code (the same `.to(float16)`) proves nothing; ask for float64 or a slow loop, and a tolerance measured from the dtype's eps |
| Default tolerance | `assert_close` or `allclose` with no `rtol` and `atol` |
| Lossy step | a cast, round or clamp whose safety fact is not visible above it |
| Repeated fact | an entry check that repeats a type |

Triton rows: `references/triton.md`.
