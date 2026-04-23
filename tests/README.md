# Tests

Stdlib-only unittest suite for `reflect-and-refine`. No pytest or other dependencies.

## Run

```bash
python3 tests/run.py         # verbose output
python3 tests/run.py -q      # quiet; exits nonzero on any failure
```

## Coverage

| Test class | What it checks |
|-----------|---------------|
| `FrontmatterParser` | YAML frontmatter parser: scalars, string lists, list-of-dicts, empty lists, comments, no-frontmatter, quoted values |
| `RealUserFilter` | `is_real_user_record` filters hook injections (`isMeta: true`) and tool results (`toolUseResult` set) |
| `GateStateSemantics` | All `/reflect-and-refine` subcommands (activate / shutdown / status / audit / rate-limit / register / unregister / customize / unknown typo); cross-session ordering (last marker wins); parent skills; unregistered skills ignored |
| `DimensionAssembly` | All 7 dimensions × 3 strictness levels present; unknown dimension rendered as placeholder; strictness actually varies the text |
| `CustomChecksAssembly` | Dict and string check entries, empty list |
| `PromptResolution` | 4-layer fallback to bundled file when nothing else exists |
| `BuildBlockReason` | End-to-end: model_preference=haiku renders param; model=default/bogus omits; all placeholders substituted |

## Adding tests

Add test classes to `run.py` and register them in the `main()` tuple. No framework magic — plain `unittest.TestCase`.
