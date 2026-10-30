# Standard upstream-runner reproduction

`agentcad.json` is the unchanged `--publish` report from the clean standard-runner
execution submitted in [upstream PR #15](https://github.com/U-C4N/Autocad-MCP/pull/15).
It is a new measurement, not a replacement for `integrated/` or earlier evidence.

- Product: `39fa4b55899233ab7ac5cbb52714a4767ca164c6` (clean).
- Evaluator: `8c805f049fd6048a8b99b3d7be1f1e9534ac7cfc` (clean), based on
  upstream `58a05ddfc34a9832c626e82cd88ecdce8e16a62a`; matrix v8 / evaluator v8.1.
- Result: 31 attempted, 31 passed, 100.0; the common v2 subset is 10/10.
- [Original published JSON](https://github.com/lizaixi01/Autocad-MCP/blob/3c4d5981e60b67bc7f5b4c24c825ffcb29d2b788/benchmarks/results/published/agentcad.json).
- [296-file archive and per-file manifest](https://github.com/lizaixi01/Autocad-MCP/tree/3c4d5981e60b67bc7f5b4c24c825ffcb29d2b788/benchmarks/results/published/agentcad-evidence-v8).
  ZIP SHA256: `8db2d928e6faae6486c0e9b60af3f7acfcaded6f45debd55ce1e9f1f6c486018`;
  1,601,093 bytes. Includes 46 returned artifact references, protocol transcripts,
  exact playbooks, 62 product source files and upstream regression output.
- [Independent final review](https://github.com/U-C4N/Autocad-MCP/pull/15#issuecomment-6519002120).

The standard runner's top-level `git_sha` is the evaluator commit, while
`adapter_metadata.product_sha` identifies AgentCAD. Runtime parity does not
assign a source-review score, certify general engineering correctness or
establish official leaderboard acceptance.
