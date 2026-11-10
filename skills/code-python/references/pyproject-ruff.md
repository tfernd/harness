# Starting ruff config

A starter. Copy only when the project has none.

```toml
[tool.ruff]
line-length = 130
target-version = "py312"

[tool.ruff.lint]
select = ["E", "W", "F", "I", "B", "UP", "C90", "SIM", "RET", "PLW0602", "PLW0603", "ARG"]
ignore = ["E501"]

[tool.ruff.lint.mccabe]
max-complexity = 9

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["C901", "ARG"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
docstring-code-format = true

[tool.uv]
exclude-newer = "7 days"
```

Meaning of the selected sets: pycodestyle errors and warnings (`E`, `W`), pyflakes (`F`), import order (`I`),
bugbear (`B`), pyupgrade (`UP`), complexity (`C90`), simplify (`SIM`), flat returns (`RET`), no `global`
(`PLW0602`, `PLW0603`), unused arguments (`ARG`). `E501` is ignored because the formatter owns line layout;
`exclude-newer` makes uv ignore releases newer than 7 days.
