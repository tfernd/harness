# Property tests for tensor code

Oracle independence and measured tolerances: `harness:testing`.

## Strategies

- Hypothesis has no official torch strategy. Build one from `hypothesis.extra.numpy` (`arrays`, `array_shapes`,
  `mutually_broadcastable_shapes`) and convert with `torch.from_numpy` (the pattern is common; verify on the installed
  versions), or draw the shape first and build the data in the test body.
- Example: `arrays(np.float32, array_shapes(min_dims=1, max_dims=3), elements=floats(-1e3, 1e3, width=32))`, then
  `torch.from_numpy(array)` in the test body.
- `array_shapes` yields axes of size at least 1; draw sizes 0 separately to test empty input.
- `floats`: with bounds set, `allow_nan` is an error; `allow_subnormal` errors when the range has no subnormals; `width`
  sets the precision. For an array of hundreds of elements a fill value is essential (numpy docs).
- Uniform floats almost never hit the edges: weight min, max, +0, -0, subnormals, NaN, inf and one step past saturation.

## The batch law

Draw a leading shape of 0, 1 and 2 axes, stack single examples, and compare `f(stack(xs))` with
`stack(f(x) for x in xs)`. Use distinct prime axis sizes (2, 3, 5) so a transposed or wrong-axis reduction cannot match.

## Reference and laws

A numerically stable softmax is checked against a slow loop over rows in float64, and against its laws: adding a
constant per row leaves it unchanged, each row sums to 1, and it is monotone in each input. Layer norm is unchanged
by a per-row shift and positive scale.

An invariant that holds only approximately (layer norm with `eps`: a per-row scale changes the result by about
`eps / variance`) is kept honest with a tiny `eps` in the test, a variance floor in the strategy, and a tolerance
measured at those inputs, not chosen.

## Enumeration

An 8-bit or 16-bit domain (every uint8 pixel value, every token id of a small vocabulary) is built with `torch.arange`
over every code and compared with the slow reference once.

## assert_close

`torch.testing.assert_close` default tolerances (rtol, atol), torch 2.15 docs:

| dtype | rtol | atol |
|---|---|---|
| float16 | 1e-3 | 1e-5 |
| bfloat16 | 1.6e-2 | 1e-5 |
| float32 | 1.3e-6 | 1e-5 |
| float64 | 1e-7 | 1e-7 |
| other, including integers | 0.0 | 0.0 |

- No float8 row, so float8 falls under 0 and 0 (DERIVED); verify with a probe.
- Set `rtol` and `atol` together, from a measurement (`harness:testing`). `functools.partial` fits them to a project.
- `check_dtype=True` by default; with False the tensors are promoted and the larger tolerance is used.
- `equal_nan=False` by default: two NaN do not match.
- An exact claim (packing, codes) uses `torch.equal`, or compares bits.
