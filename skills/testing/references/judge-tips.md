# Judge tips

One line each; the rules of a good judge are in `SKILL.md`.

- An input meant to cover a data layout puts a nonlinear function of the position in the values (a square of the index),
  since a linear pattern hides swapped slots.
- Probe a cast or conversion before a test rests on it.
- A skip uses the framework's skip-if with a reason, never an imperative skip inside the test body.
- A bounds judge checks the values just outside the written range are untouched.
- A resource-use judge warms up first and counts every copy the code makes.
- A search for a best answer is compared with an exhaustive one by its score, never by the answer itself, since two
  answers can tie.
- A throwaway probe that loads a script by path registers the module in `sys.modules` before running it.
- A session without the project's tools runs the judge by hand and quotes the run.
