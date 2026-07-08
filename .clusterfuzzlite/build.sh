#!/bin/bash -eu

cd "$SRC/usage"

# Keep fuzzing isolated from this repo's macOS-only runtime dependencies.
export PYTHONPATH="$SRC/usage"

for fuzzer in fuzz/fuzz_*.py; do
  compile_python_fuzzer "$fuzzer"
done
