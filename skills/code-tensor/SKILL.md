---
name: code-tensor
description: Writing and reviewing PyTorch and Triton code whose correctness a reader sees at a glance - dtype and shape types, constrained scalars, entry value checks, property tests, slow references. Load before writing or reviewing code that imports torch, jaxtyping or triton.
---

# Tensor code

Python rules: `harness:code-python`. Tests: `harness:testing`. A reader checks one function without opening another.

## Principles

1. **The signature is the theorem.** Each boundary states dtype, axes and value domain. A caller supplies every fact the
   body relies on, or the body checks it at entry.
2. **Each fact sits on the cheapest rung that can state it, and only there.** The rungs: dtype class, axis string,
   constrained scalar type or `Literal`, entry check, property test, reference implementation. A check never repeats a
   type.
3. **An output axis is bound.** By an input axis of the same name, by an expression of input axes, or by a named
   property test. A name used once in a signature checks nothing: `-> UInt8[Tensor, "*rows num_pieces"]` accepts any length.
4. **A lossy step gets its own line,** with the fact that makes it safe visible above it: narrowing cast, round, clamp,
   view across dtypes, reduction, broadcast between unequal ranks, in-place write. Example: clamp to the float16
   maximum on one line, then `.to(torch.float16)` on the next, so saturation is never silent.
5. **Nothing ambient.** Device and dtype come from an input or a parameter, never from a default or a global.
6. **A comparison that must fail on NaN** is written `~(x >= bound)`, not `x < bound`.

## Types and checks

- Every tensor parameter, return and dataclass field is `Dtype[Tensor, "axes"]`; a bare `Tensor` carries no claim.
  Dtype-agnostic code uses `Shaped`.
- A recurring axis string is one named alias, defined in the module that owns the axis.
- Axes carry meaning: `Float[Tensor, "batch heads seq head_dim"]` for a query, `Float[Tensor, "batch heads seq seq"]` for
  its attention scores. A constrained scalar (`num_channels`, `num_heads`) is an annotated type that rejects `bool`.
- A value fact no type states is checked once, where the value enters: `check_<what>(value, /, *, name)` returns `None`
  and raises `ValueError` naming the value. In tensor code a value invariant is never an `assert`; use the entry check.
  (`harness:code-python` keeps `assert` for other internal invariants.)
- Compare in a widened dtype, so the check cannot wrap.
- One switch turns the value checks off, read at call time from an environment variable (no module-level mutable state):
  `def are_value_checks_enabled() -> bool: return os.environ.get("PROJECT_VALUE_CHECKS", "1") != "0"`, and each
  `check_<what>` starts with `if not are_value_checks_enabled(): return None`.
- Half precision (float16, bfloat16): compute in float32, clamp on one line, cast back on the next. Tests assert the
  output dtype equals the input's.
- jaxtyping, the import hook, symbolic dims, dtype names, beartype: `references/types.md`.

## Tests

- **Batch law:** `f(stack(xs)) == stack(f(x) for x in xs)` for any function with a variadic leading axis. It catches
  most broadcasting, reshape and reduction-axis bugs and needs only the signature.
- **A type-failure test** asserts the exact error (`jaxtyping.TypeCheckError`, `ValueError` for an entry check), never `Exception`.
- **Laws:** round trip on the stated domain, idempotence (clamping twice equals once), equivariance (softmax
  is unchanged by adding a constant per row; layer norm by a per-row shift and scale), monotonicity. Each test names the bug it fails on.
- **A slow reference is the definition:** Python ints or a loop; the fast path equals it bit for bit, or within a
  named, measured tolerance.
- **Small domains are enumerated,** not sampled: every 8-bit or 16-bit input.
- **Generators aim at the dtype's edges:** min, max, +0 and -0, subnormal, NaN, inf, one step past saturation.
- Strategies, tolerances, `assert_close`: `references/properties.md`.

## Triton

A kernel sees pointers, not types. Its typed wrapper carries principles 1 to 5, and the torch reference is the spec.
Masks, interpreter limits, device asserts: `references/triton.md`.

## Review

The lens, one fault per row with the input that exposes it: `references/review.md`.

## Rules a hook will check

Named as rules; the hook that applies them is not built yet.

- A parameter, return or dataclass field annotated bare `Tensor` in a file that imports jaxtyping.
- `assert_close`, `allclose` or `isclose` without an explicit `rtol` and `atol`; an exact claim uses `torch.equal`.

## What no tool checks

Whether an output axis is really bound, whether a lossy step has its fact above it, whether a check repeats a type,
whether a test fails on a plausible bug, and whether a device is taken from an input.
