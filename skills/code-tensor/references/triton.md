# Triton

- A kernel sees pointers and `tl.constexpr` sizes. The typed wrapper states dtype, axes, device and contiguity
  (principles 1 to 5 of `harness:code-tensor`); the kernel's only shape statement is its mask.
- The tutorial guards memory with a mask: "Create a mask to guard memory operations against out-of-bounds accesses."
  What `mask` and `other` do in `tl.load` is not in the docs I read; verify against the installed version.
- `BLOCK_SIZE: tl.constexpr` must be a compile-time constant so it can be a shape value.
- The tutorial's wrapper checks that all tensors are on the same device.
- The spec is a torch reference; compare with `assert_close` and an explicit `rtol` and `atol` (`references/properties.md`).

## Example

A masked row-wise softmax kernel gets a typed wrapper `softmax_rows(x: Float[Tensor, "rows cols"]) -> Float[Tensor, "rows cols"]`
that takes device and dtype from `x`, checks contiguity at entry and launches the kernel. Its spec is
`torch.softmax(x, dim=-1)`, compared with explicit `rtol` and `atol` at `cols` of 1, BLOCK-1, BLOCK and BLOCK+1.
A vector add follows the same shape: typed wrapper, mask, torch reference.

## Debugging

| Tool | Fact |
|---|---|
| `TRITON_INTERPRET=1` | runs on the interpreter; no `bfloat16` (cast to float32) and no indirect loads such as `ptr = tl.load(ptr)` |
| `tl.device_assert` | runs only with `TRITON_DEBUG=1` |
| `tl.static_assert` | checked at compile time |
| `tl.static_print` | compile-time debugging |

## Inputs that expose kernel bugs

Sizes 0, 1, BLOCK-1, BLOCK, BLOCK+1; an output buffer padded with a sentinel that must survive; an input padded with
NaN that must not leak; index arithmetic past int32; a non-contiguous or offset input; an input aliased with the output;
each dtype the wrapper admits.
