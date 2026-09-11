# Texture metadata checklist

Implement explicit image/meta changed_paths, including uppercase extensions, and
three deterministic checks: asset/meta pairing, GUID syntax and same-path stability,
and TextureImporter/merge-marker validity. Read companion metadata from Git even
when unchanged, independent of model context truncation. Removed pairs are valid;
missing/unreadable data is not PASS. No global duplicate-GUID or reference scan,
image decoding, or project-specific compression policy is claimed.

Test with temporary Git repos before implementation, then run full suite. Retain
per-asset details and snapshot evidence in reports; deterministic FAIL must affect
the advisory assessment without AI verification. Document workflow and rerun command.
