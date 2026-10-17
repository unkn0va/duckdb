#!/usr/bin/env bash
# Generate the data of the selectivity experiment next to the paper's datasets, and check it (SERVER.md, step 5):
#   <data folder>/selectivity_random/  l1.parquet (a link to the paper's synthetic/l1.parquet) and its pre-split files
#   <data folder>/selectivity_sorted/  the same shape with "a" ascending, and its pre-split files
#
# Usage: prepare_data.sh <data folder> <python with pyarrow 26.0.0>
#   <data folder> must contain nested-parquet-datasets/ (the extracted archive).
set -euo pipefail

if [ $# -ne 2 ]; then
	sed -n '2,7p' "$0"
	exit 2
fi
DATA=$(cd "$1" && pwd)
PYTHON=$2
HERE=$(cd "$(dirname "$0")" && pwd)

if [ ! -f "$DATA/nested-parquet-datasets/synthetic/l1.parquet" ]; then
	echo "ERROR: $DATA/nested-parquet-datasets/synthetic/l1.parquet not found - extract the archive into $DATA first."
	exit 1
fi
VERSION=$("$PYTHON" -c "import pyarrow; print(pyarrow.__version__)" 2>/dev/null || echo "none")
if [ "$VERSION" != "26.0.0" ] && [ "${ALLOW_OTHER_PYARROW:-0}" != "1" ]; then
	echo "ERROR: $PYTHON has pyarrow $VERSION, but 26.0.0 is needed for files identical to the laptop's."
	echo "       Install it (SERVER.md, step 1), or set ALLOW_OTHER_PYARROW=1 to generate anyway (the checksum check"
	echo "       below will then fail, but the files are still valid for the benchmark)."
	exit 1
fi

echo "== selectivity_random: the paper's l1.parquet and pre-split files cut from it"
mkdir -p "$DATA/selectivity_random"
ln -sfn ../nested-parquet-datasets/synthetic/l1.parquet "$DATA/selectivity_random/l1.parquet"
"$PYTHON" "$HERE/split_selectivity_data.py" "$DATA/selectivity_random/l1.parquet" "$DATA/selectivity_random"

echo "== selectivity_sorted: generated data with \"a\" ascending, and its pre-split files"
"$PYTHON" "$HERE/generate_selectivity_data.py" "$DATA/selectivity_sorted"

echo "== checking the generated files"
python3 "$HERE/check_data.py" "$DATA" --full --only selectivity_
