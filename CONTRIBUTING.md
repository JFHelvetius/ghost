# Contributing to Project Ghost

Thanks for taking an interest. Project Ghost is intentionally a
closed-circle project in its current phase, but issues with questions,
criticism, or property-set verification reports from third-party MCAPs
are always welcome.

## Reporting issues

- **Property violations on your own MCAP**: open an issue titled
  `[property-violation] <property-tag>` and attach:
  - The output of `ghost verify-properties --mcap <your-mcap> --json`
  - The SHA-256 of the MCAP
  - The pipeline configuration you used (M, K, W, max_history,
    or non-reference policy if applicable)

  We will investigate whether the violation is in the reference
  implementation, the verifier, or your custom wiring.

- **Bugs in the verifiers themselves**: include a minimal repro plus
  the expected vs observed report. The verifier is the
  citable surface — any divergence between its output and the
  property statement in the ADR is a release-blocking bug.

- **Documentation or wording**: issues or PRs against
  `docs/` or the README welcome. The MkDocs site
  (https://JFHelvetius.github.io/ghost/) is built from `docs/` on
  every push to `main`.

## Proposing a new property

Adding ADR-0036+ follows the pattern established by ADRs 0031–0035:

1. **Open an issue** with a sketch of the property statement, the
   policy pair it applies to, and what witness you expect (Hypothesis
   test? smoke witness? both?).
2. **Write the ADR** under `docs/adr/0036-<slug>.md` with the
   mandatory sections: Status, Context, Decision (formal statement,
   scope, verification plan), Consequences, Alternatives, References.
3. **Implement the verifier** in `src/project_ghost/properties/<name>.py`
   following the structural template from `baud.py` (frozen dataclass
   report + violation kind enum + per-cycle helpers + public
   `verify_<name>` entry point with `mcap_path`, returns a report
   with `.holds`).
4. **Add tests**: at minimum, a smoke sanity test
   (`tests/properties/test_verify_<name>_smoke.py`) and a Hypothesis
   property test with named adversarial scenarios
   (`tests/properties/test_<name>_property.py`).
5. **Wire it into `SmokeSummary`** in `closed_loop_smoke.py` so every
   reference run carries an inline veredicto, and into
   `cli.py::_cmd_verify_properties` so it appears in `ghost
   verify-properties` output.
6. **Add a docs page** `docs/properties/<name>.md` following the
   template (Citation, What it claims, Formal statement, Why it
   matters, Verifying any MCAP, Example output, Scope, See also).
7. **Lift the ADR to Accepted** only when steps 2–6 are all merged
   and CI is green.

## Code quality bar

Every PR must:

- Pass `pytest` (`pytest -q`)
- Pass `ruff check src tests` and `ruff format --check src tests`
- Pass `mypy` in strict mode
- **Pass `ghost verify-properties` on the reference smoke MCAP** —
  the build will reject any PR that breaks the property set.

CI enforces all four (`.github/workflows/ci.yml`). If your local
`ghost verify-properties` reports `VIOLATED`, the PR will not merge.

## License

By contributing you agree your contributions are licensed under
[Apache-2.0](LICENSE), the same license as the rest of the project.

## Maintainer release process

See the [Release process section in the
README](README.md#release-process). Summary:

1. Bump `version` in `pyproject.toml` and `CITATION.cff`.
2. Update `CHANGELOG.md` with the release date and notes.
3. `git commit -am "release: v<version>"`.
4. `git tag -a v<version> -m "<one-line summary>"`.
5. `git push origin main v<version>`.
6. The release workflow builds, verifies, publishes to PyPI via OIDC,
   and creates the GitHub Release. No manual `twine upload` needed.
