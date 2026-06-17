# Install guide for Project Ghost v0.2.5

This document covers the four toolchains a reproducer needs:

1. **Python 3.11+** for the verifier surface and the test suite.
2. **Java 17** for TLC (TLA+ model checker).
3. **Lean 4** (`4.31.0` stable) for the mechanical proofs.
4. **`tla2tools.jar` v1.8.0** for TLC itself.

Required for reproducing the full paper:

- Python 3.11 or 3.12, plus a virtualenv with the project
  installed in `-e` mode (see §1 below).
- Java 17.

Required for reproducing only the *Python-side* claims (paper
§3-5, §7-8, §8.8.x):

- Python 3.11 or 3.12 only.

Required for reproducing the *mechanical proofs* (paper §6.1-6.3):

- Java 17 (for TLC) **and/or** Lean 4 (for the type-theoretic
  proofs). Either is sufficient; both is best.

The CI matrix exercises `{ubuntu-latest, windows-latest} ×
{python 3.11, 3.12}` on every push.

---

## 1. Python environment

### 1.1 Linux / macOS

```bash
# Clone
git clone https://github.com/JFHelvetius/ghost.git
cd ghost

# Create venv
python3.11 -m venv .venv
source .venv/bin/activate

# Install in editable mode with all optional extras
pip install -e ".[dev,adapters]"

# Confirm
python -c "import project_ghost; print(project_ghost.__version__)"
```

### 1.2 Windows (PowerShell)

```powershell
# Clone
git clone https://github.com/JFHelvetius/ghost.git
Set-Location ghost

# Create venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install
pip install -e ".[dev,adapters]"

# Confirm
python -c "import project_ghost; print(project_ghost.__version__)"
```

### 1.3 Python version pinning

The project supports CPython **3.11 and 3.12**. We test both on
every CI push. CPython 3.13 is expected to work but is not yet
in the CI matrix; 3.10 and earlier are *not* supported (we use
`StrEnum` from the stdlib enum module, introduced in 3.11).

### 1.4 Optional extras

| Extra | What it adds | When you need it |
|---|---|---|
| `dev` | pytest, hypothesis, ruff, mypy | Always (running the tests) |
| `adapters` | pyulog | Reproducing §8.7-8.8 (real ULog integration) |
| `stats` | scipy | Using `ConfidenceMethod.CLOPPER_PEARSON` in FPB-v2 (the Hoeffding default does not need scipy) |

`pip install -e ".[dev,adapters]"` covers everything for the
property and discrimination experiments. SciPy is gated behind
the explicit Clopper-Pearson opt-in; the default install is
sufficient for FPB-v2 with Hoeffding.

---

## 2. Java 17 (for TLC)

### 2.1 Linux

```bash
sudo apt install openjdk-17-jre-headless
java --version
```

### 2.2 macOS

```bash
brew install temurin@17
/usr/libexec/java_home -V    # confirm Temurin 17 is selected
```

### 2.3 Windows

We recommend the portable Temurin 17 zip (no installer, no
admin rights required):

```powershell
# Download (replace x.y.z with the current 17.x version)
$url = "https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jre/hotspot/normal/eclipse"
Invoke-WebRequest -Uri $url -OutFile jre17.zip -UseBasicParsing
Expand-Archive jre17.zip -DestinationPath "$env:USERPROFILE\jdk-portable"
Remove-Item jre17.zip

# Find and verify
$JAVA = (Get-ChildItem "$env:USERPROFILE\jdk-portable\*\bin\java.exe").FullName
& $JAVA --version
```

Set the `JAVA` environment variable for subsequent commands:

```powershell
$env:JAVA = $JAVA
```

(On Unix shells, `export JAVA=$(which java)`.)

---

## 3. TLA+ tools (`tla2tools.jar`)

```bash
# At the repo root
curl -L -o tla2tools.jar \
    https://github.com/tlaplus/tlaplus/releases/download/v1.8.0/tla2tools.jar

# Verify (should print the TLC banner)
$JAVA -cp tla2tools.jar tlc2.TLC -help | head -5
```

`tla2tools.jar` is gitignored (the CI workflow downloads it per
run and caches it). The pinned version is **v1.8.0**.

---

## 4. Lean 4 (for the mechanical proofs)

### 4.1 Linux / macOS

```bash
curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf \
    | sh -s -- -y --default-toolchain leanprover/lean4:stable

# Add to PATH (or open a new shell)
source ~/.elan/env

# Verify
lean --version
```

### 4.2 Windows (PowerShell)

```powershell
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/leanprover/elan/master/elan-init.ps1" `
    -OutFile "$env:TEMP\elan-init.ps1" -UseBasicParsing
& "$env:TEMP\elan-init.ps1" -NoPrompt $true -NoModifyPath $true `
    -DefaultToolchain "leanprover/lean4:stable"

# Find and verify
$LEAN = "$env:USERPROFILE\.elan\bin\lean.exe"
& $LEAN --version
# Expected: "Lean (version 4.31.0, ...)"
```

The Lean 4 install bundles `lake` (project manager) and the
standard library. No `mathlib` is needed — the Project Ghost
Lean proofs use only the standard library.

### 4.3 Pinned version

We target **Lean 4 `4.31.0`** (the stable channel as of v0.2.5).
The proofs are conservatively written and should survive minor
version bumps; if they don't, please open an issue.

---

## 5. End-to-end environment check

After completing §1-4, the following commands should all exit 0:

```bash
# Python
$VENV/bin/python -c "import project_ghost; print(project_ghost.__version__)"

# Java
$JAVA --version

# TLA+
$JAVA -cp tla2tools.jar tlc2.TLC -help > /dev/null

# Lean 4
$LEAN docs/proofs/Lean/Sanity.lean
```

The Lean sanity check confirms the toolchain works on a
3-line theorem before you attempt the larger proofs.

If any of the four checks fails, please consult the
troubleshooting notes below before proceeding to
[REPRODUCE.md](REPRODUCE.md).

---

## 6. Troubleshooting

### "ModuleNotFoundError: pyulog"

You installed the base wheel but not the `adapters` extra.
Re-run `pip install -e ".[dev,adapters]"`.

### "TLC: Unknown option: -workers"

Old `tla2tools.jar`. The pinned v1.8.0 supports `-workers auto`.
Re-download per §3.

### "lean: command not found" after install

The `elan` installer on Linux/macOS modifies `~/.bashrc` or
`~/.zshrc` to add `~/.elan/bin` to PATH. Open a new shell or
`source ~/.elan/env`.

On Windows the installer with `-NoModifyPath $true` does *not*
modify PATH (intentional for reproducibility); use the absolute
path `$env:USERPROFILE\.elan\bin\lean.exe` instead.

### Windows: PowerShell execution policy blocks `elan-init.ps1`

Run PowerShell with `-ExecutionPolicy Bypass` once, or
prepend `powershell -ExecutionPolicy Bypass -File` to the
elan invocation.

### `ELECTRON_RUN_AS_NODE=1` (if reproducing a future hardware demo)

Not relevant to v0.2.5 (no hardware demo). Listed for
completeness.

### "scipy not installed" when running `verify_fpb_v2` with Clopper-Pearson

Either install scipy (`pip install scipy`) or switch to
`ConfidenceMethod.HOEFFDING` (the default, stdlib-only). The
error message includes both fix options.

---

## 7. CI alignment

The CI matrix uses:

- Ubuntu 22.04 (`ubuntu-latest` at the time of writing).
- Python 3.11 + 3.12 (a `setup-python` matrix).
- Java 17 (Eclipse Temurin via `setup-java`).
- `tla2tools.jar` v1.8.0 (downloaded + cached per workflow).

Lean 4 is **not yet** in CI; the Lean proofs are exercised by
contributors locally before push. A new `lean-proofs` job is the
ADR-0042 follow-up and is on the roadmap.

If you reproduce a paper claim on a configuration the CI does
not cover (e.g. Lean on macOS, Java on Alpine), please report
your findings; we appreciate the additional coverage.

---

## 8. Summary

| Toolchain | Pin | Mandatory for |
|---|---|---|
| Python | 3.11 or 3.12 | Everything except mechanical proofs |
| Java | 17 (Temurin) | TLA+ / TLC reproduction |
| Lean | 4.31.0 stable | Lean 4 mechanical proofs |
| tla2tools.jar | v1.8.0 | TLA+ / TLC reproduction |

A minimal "I only want to verify the property-level claims" reproduction
needs Python only; this covers paper §3-5, §7-8, §8.8.x. Add Java + TLA+
tools for §6.1-6.3. Add Lean for §6.3's mechanical proofs.

Once installed, proceed to [REPRODUCE.md](REPRODUCE.md).
