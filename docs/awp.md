# Optional AWP orbit propagator

The repository points to AWP as a Git submodule at commit `f90a593c76095cb1e94c609a947a1430458cefe2`. Initialize it with:

```bash
git submodule update --init --recursive
python -m pip install -e ".[awp]"
```

The core SGP4-based factorial campaign does not need AWP. The `awp-check` command uses AWP's two-body-plus-J2 propagation and compares it to SGP4 after a frame conversion. This is a model comparison, not validation against measured truth. Drag and third-body runs add further assumptions that must be reported.

AWP is maintained at [alfonsogonzalez/AWP](https://github.com/alfonsogonzalez/AWP). Its license was not present in the checked upstream checkout when this student repository was prepared, so AWP is kept outside the main MIT license as a source-only submodule. Review the upstream repository's current license and terms before redistributing or relying on that component.
