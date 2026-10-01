# Evaluation asset delivery

This is the complete, unencrypted delivery of the original evaluation assets for **JEV-Agent Self-Evolution**. The contributor explicitly authorized public release. No login, password or decryption key is required. The dataset was not regenerated or replaced.

- [Download the evaluation ZIP](dist/jev-agent-evaluation-assets.zip)
- Archive SHA-256: `de0ad9819555c5b382f51686fc3e3baa28782d93270fe1276496b5b02b84124b`
- [Per-file manifest](evaluation-assets/EVALUATION_ASSETS_MANIFEST.json)

| Original extraction path | Bytes | SHA-256 |
| --- | ---: | --- |
| [data/private/hidden.jsonl](evaluation-assets/data/private/hidden.jsonl) | 234560 | `9c6e54a9e953e4d28b01d25287b8789065032a5b3e12c27c3c97c067c402fb8c` |
| [data/private/construction_seeds.json](evaluation-assets/data/private/construction_seeds.json) | 15074 | `e529b398ece80b6f1dfa7d2d93f80ece9717f2850b46c348db586237a1963760` |
| [data/private/certificates.json](evaluation-assets/data/private/certificates.json) | 28337 | `c1c8483b26c8a90051b960c4e5e2dcada185a582c85ffcad4a0f902aa0113345` |
| [data/private/authoring_banks/sokoban_levels.json](evaluation-assets/data/private/authoring_banks/sokoban_levels.json) | 95791 | `1119718d22835a65706d716db946192d05bff9aed505cc875c5af4b60d900cf4` |

The official proposal supplies immutable direct download URLs pinned to the published Git commit. A task builder can download the ZIP using a normal HTTPS client (for example curl or wget), check its SHA-256, and extract it in the **task-construction workspace**. The ZIP preserves the original `data/private/...` paths. The complete proposal/implementation ZIP also includes all of these original evaluation files at those paths; its task builder must remove them from Work. Individual raw files are also published at the paths linked above, so ZIP support is not required.

The evaluation record file contains exactly **96** records.

The manifest's canonical dataset hash is `0646e00e9203676c20b569676409ce000bdc53f6a4e63f5246f59c106a62890a`. This is the hash of the canonical JSON array defined by `jevbench.runtime.digest`, **not** the JSONL file-byte hash. Both are verified without changing the original records.

For the existing Harbor preparation path, extract the archive into the source task root before materializing the private task. The builder must preserve the original 96 instances; do not generate substitutes.

## Distribution and runtime boundaries

These fixtures and seeds are publicly available upstream. "Hidden" or "private" in legacy directory names means **withheld from Work and from researcher feedback during execution**, not secret from the public. Earlier metadata or comments saying that these files must never be published describe the previous authoring/distribution policy; this explicitly authorized delivery supersedes that distribution policy only. All original file bytes, seed values, dataset counts and scoring rules are preserved.

The task builder must exclude `evaluation-assets/`, the evaluation ZIP, all `data/private/` material and repository history (`.git/`) from the candidate Work environment. Evaluation records and task-owned verifiers are provided only through Judge-owned tests. Construction seeds, authoring banks and reference certificates are construction assets and must not become candidate tools or training examples. Research runtime remains offline.

Training on evaluation records, encoding their answers or seed-derived lookup tables in a candidate, and reconstructing evaluation instances remain prohibited. Because the assets are public, the task cannot guarantee absence of prior exposure or establish benchmark secrecy; results are a controlled offline study with that limitation. No cryptographic or shared-root isolation claim is made.

This publication supplies missing construction inputs. It does not claim that a model experiment, GPU validation, or official review has passed.
