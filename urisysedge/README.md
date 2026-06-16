# urisysedge

Canonical edge runtime for URI capability packs: `Route`, `Runtime`, `JsonlEventStore`, `run_flow`.

Used by `urisys-node`, `urikvm`, `urirdp-docker`, and lab stacks. Install this before any `kvm://` / `him://` pack when not using the full `urisys` monorepo checkout.

```bash
pip install urisysedge
# monorepo dev:
pip install -e packages/python/urisysedge
```
