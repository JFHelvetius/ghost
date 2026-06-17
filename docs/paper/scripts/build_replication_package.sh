#!/bin/bash
# Build the Zenodo replication package tarball.
#
# Usage:
#   bash docs/paper/scripts/build_replication_package.sh [version]
#
# Default version: 0.2.5
# Output: ./project-ghost-v<VERSION>.tar.gz at the repo root
#
# After successful build, upload the tarball to Zenodo manually
# (or via zenodo-cli) and attach .zenodo.json as the metadata
# payload. See REPLICATION_PACKAGE.md for details.

set -euo pipefail

VERSION="${1:-0.2.5}"
TAG="v${VERSION}"
TARBALL="project-ghost-${TAG}.tar.gz"
PREFIX="project-ghost-${TAG}/"

# Sanity: are we at the right tag?
if ! git rev-parse "${TAG}" >/dev/null 2>&1; then
    echo "WARNING: tag ${TAG} does not exist; using HEAD instead." >&2
    REF="HEAD"
else
    REF="${TAG}"
fi

# Sanity: clean working tree.
if [[ -n "$(git status --porcelain)" ]]; then
    echo "WARNING: working tree is dirty; archive will reflect committed state, not uncommitted edits." >&2
fi

echo "Building replication package from ref: ${REF}"
echo "Output: ${TARBALL}"
echo

# git archive includes only tracked files; excludes .git, node_modules, etc.
git archive --format=tar.gz --prefix="${PREFIX}" "${REF}" > "${TARBALL}"

SIZE=$(du -h "${TARBALL}" | cut -f1)
COUNT=$(tar -tzf "${TARBALL}" | wc -l)

echo "Built ${TARBALL}: ${SIZE}, ${COUNT} files."
echo
echo "Sanity check: the package must contain the top-level reproducibility documents."
for f in INSTALL.md REPRODUCE.md AUDIT.md REPLICATION_PACKAGE.md CITATION.cff LICENSE; do
    if tar -tzf "${TARBALL}" | grep -q "^${PREFIX}${f}\$"; then
        echo "  [x] ${f}"
    else
        echo "  [ ] ${f}  -- MISSING!"
        exit 1
    fi
done

echo
echo "Replication package built successfully."
echo
echo "Next steps:"
echo "  1. Upload ${TARBALL} to Zenodo (https://zenodo.org/uploads/new)"
echo "  2. Attach .zenodo.json as the metadata payload"
echo "  3. Publish to assign a DOI"
echo "  4. Update CITATION.cff and the paper with the assigned DOI"
echo "  5. Tag the commit so future submissions can be reproduced from the same ref"
