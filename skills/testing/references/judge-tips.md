# Judge tips

One line each; the rules of a good judge are in `SKILL.md`.

- An input meant to cover a data layout puts a nonlinear function of the position in the values (a bit-reversed index),
  since a linear pattern hides swapped slots.
- Probe a cast or conversion before a test rests on it.
- A skip uses the framework's skip-if with a reason, never an imperative skip inside the test body.
- A mask or bounds judge puts a sentinel buffer around the output.
- A peak-memory judge warms up first and counts every copy the code makes.
- An optimizer is compared with an exhaustive search by its objective value, never by bytes, since two solutions can
  tie.
- A throwaway probe that loads a script by path registers the module in `sys.modules` before running it.
- A session without the project's tools runs a CPU-only judge by hand and quotes the run.
