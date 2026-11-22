# Types: jaxtyping and beartype

Facts from the jaxtyping docs and source (v0.3.11) and the beartype docs, unless marked PROBED.

## Axis strings

| Form | Meaning |
|---|---|
| `"28 28"` | fixed sizes |
| `"channels"` | named; bound on first sight, a later mismatch fails |
| `"*batch"` | variadic: matches several axes |
| `"..."` | anonymous variadic, equal to `*_`; at most once per array |
| `"#n"` | the size, or 1 |
| `"_n"` | not checked |
| `"n-1"`, `"n*2"` | symbolic: no spaces, return types only, only axes from the arguments |

- A one-word string trips flake8 and Ruff F722; prepend a space (`" n"`). The source strips it.
- Return types may use f-strings with local variables in curly braces.
- Docs-only forms such as `name=value` (`"rows=4 cols=3"`) are for documentation.

## Dtype classes

`Shaped` any dtype; `Float` any float; `Int` any signed integer; precise names include `BFloat16`, `Float16`, `Float32`,
`Float64`, `Int8`, `UInt8`, `UInt16`, `UInt32`, `UInt64`. Float8 classes (`Float8e4m3fn`, `Float8e5m2` and others) exist
in the source but not on the docs page; whether a torch float8 tensor matches one is DERIVED from the source (it takes the
last part of `repr(dtype)`). Verify before relying on it: `isinstance(torch.zeros(1, dtype=torch.float8_e4m3fn), Float8e4m3fn[Tensor, "n"])`.

## Checking at run time

- `@jaxtyped(typechecker=beartype.beartype)` on a function; the double-decorator form is deprecated.
- `install_import_hook("package", "beartype.beartype")` decorates every function and dataclass in the package; the
  typechecker is given as a string.
- PROBED (jaxtyping 0.3.11, beartype 0.23.1, torch 2.15.0): with `from __future__ import annotations` the hook still
  refused a shape mismatch, a wrong input dtype and a wrong return dtype, although the docs advise against stringified
  annotations. A checked call cost about 15 to 18 microseconds.
- Without the hook or `@jaxtyped(typechecker=beartype)` the annotations check nothing. Call `install_import_hook` in
  `conftest.py`, before the package is imported, so the tests run the checked code.
- A dataclass decorated by the hook checks its `__init__`. A `NamedTuple` is not documented as checked; use a frozen
  dataclass for a result with tensors.
- A stringified annotation such as `x: "int"` is silently skipped (FAQ).
- Whether a return type sees the argument bindings is implied by the docs on symbolic return dims; verify with one probe.
- Whether `beartype.claw` alone gives shape binding is not documented; use the jaxtyping hook.
- beartype checks one random item of a container by default, so a bad item elsewhere can pass.
- A beartype `Is[...]` validator inside `Annotated` runs at call time; keep it O(1), and other checkers ignore it.

## Static checkers

Torch stubs declare no shape or dtype generics, so the annotation is not checked statically. Only the run-time hook checks it.
