# Naming by language

Casing and idiom only; the meaning rules are in `harness:naming`.

| Place | Form |
|---|---|
| Python | `snake_case` functions, variables, modules; `PascalCase` classes; `UPPER_SNAKE` constants; a leading `_` for private; a count is `num_<things>` |
| JS and TS | `lowerCamel` functions and variables; `PascalCase` types and classes; `UPPER_SNAKE` fixed numbers; booleans `is`, `has`, `can`; an acronym is a word (`toSvg`) |
| Shell | `lower_snake` locals and functions; `UPPER_SNAKE` exported or environment variables; a script named for its job, `kebab-case` |
| SQL | `snake_case` lowercase names; keywords uppercase; a CTE named for what it holds; a table singular or plural as the project already does, one way only |
| Terraform | `snake_case` descriptive nouns; the resource type is not repeated in the name (`aws_instance.web`) |
| YAML keys | The tool's own casing (GitHub Actions `kebab-case`, Harness `camelCase`); a repo's own keys `snake_case` |
| CSS classes | lower-case, hyphenated, naming the role (`card-title`), not the look (`red-text`) |
| Make targets | lower-case, hyphenated verbs (`check`, `build-docs`); a target that makes a file is the file's path |
| Files | The one job the module does; no `utils`, `helpers`, `common` |
