# urisysedge


## AI Cost Tracking

![PyPI](https://img.shields.io/badge/pypi-costs-blue) ![Version](https://img.shields.io/badge/version-0.1.1-blue) ![Python](https://img.shields.io/badge/python-3.9+-blue) ![License](https://img.shields.io/badge/license-Apache--2.0-green)
![AI Cost](https://img.shields.io/badge/AI%20Cost-$0.15-orange) ![Human Time](https://img.shields.io/badge/Human%20Time-1.0h-blue) ![Model](https://img.shields.io/badge/Model-openrouter%2Fqwen%2Fqwen3--coder--next-lightgrey)

- 🤖 **LLM usage:** $0.1500 (1 commits)
- 👤 **Human dev:** ~$100 (1.0h @ $100/h, 30min dedup)

Generated on 2026-06-16 using [openrouter/qwen/qwen3-coder-next](https://openrouter.ai/qwen/qwen3-coder-next)

---



Canonical edge runtime for URI capability packs: `Route`, `Runtime`, `JsonlEventStore`, `run_flow`.

Used by `urisys-node`, `urikvm`, `urirdp-docker`, and lab stacks. Install this before any `kvm://` / `him://` pack when not using the full `urisys` monorepo checkout.

```bash
pip install urisysedge
# monorepo dev:
pip install -e packages/python/urisysedge
```


## License

Licensed under Apache-2.0.
