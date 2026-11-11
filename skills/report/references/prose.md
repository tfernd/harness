# Writing tics to avoid in a report

Say the thing once, in the active voice, with its subject named.

| Tic | Bad | Plain |
|---|---|---|
| Negation first, then the reveal | It is not a cache bug. It is a stale key. | The key is stale. |
| Stacked negations | Not a rewrite. Not a patch. Just a rename. | The change renames `load` to `read`. |
| Significance label | This is crucial: the lock must be held. | The lock must be held, or two writers race. |
| Aphoristic closer | Simple in, simple out. | (cut it) |
| Fragment cadence | Fast. Clean. Done. | The change is done and the check passes. |
| Dressed metaphor | The parser swallowed the error. | The parser dropped the error without logging it. |
| Label first | The key insight: the cache is per process. | The cache is per process. |
| Pronoun without referent | It broke it after the move. | The move broke `load`. |
| Passive where active works | The file was changed by the hook. | The hook changed the file. |
