---
name: review-adapter
description: Review a Harbor benchmark adapter's fidelity, grading, and parity evidence, including self-review before submission, using the same shared guide as CI.
---

# Review an adapter

The full review guide lives in `harbor-index/adapter-automation`. Use the version
selected by this repository's review workflow:

1. Read `.github/workflows/adapter-review.yml` from the adapters repository root.
   Find the full commit SHA after
   `harbor-index/adapter-automation/.github/workflows/adapter-review.yml@`.
   The `automation-ref` value should match that SHA.
2. Fetch and read
   `https://raw.githubusercontent.com/harbor-index/adapter-automation/<sha>/skills/review-adapter/SKILL.md`,
   replacing `<sha>` with that commit. Do not substitute the current `main` branch.
3. Follow the shared guide. Read the acceptance specification and parity
   diagnostics from the trusted adapters base revision, as the guide describes.

For a self-review, inspect the author's local changes too. Record the commit and
whether the working copy has uncommitted changes so the findings have a clear
scope. Reviewing files does not require posting a comment or running CI.

If the shared guide cannot be retrieved, explain that limitation. Do not claim
to have followed guidance you could not read.
