#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

GALOIS_ROOT="$PROJECT_ROOT/Galois"
BFS="$GALOIS_ROOT/build/lonestar/analytics/distributed/bfs/bfs-push-dist"

GRAPHS=(
  "bfs_data/web-Google.gr"
  "bfs_data/wiki-Talk.gr"
  "bfs_data/wiki-topcats.gr"
)

CONFIGS=(
  "1:1" 
  "1:2" 
  "1:3" 
  "1:4" 
  "1:5" 
  "1:6" 
  "1:7" 
  "1:8"
  "2:1" 
  "2:2" 
  "2:3" 
  "2:4"
  "4:1" 
  "4:2"
  "8:1"
)

RUNS=10
STARTNODE=200
OUT_DIR="$GALOIS_ROOT/exp/bfs_res"

total=$(( ${#GRAPHS} * ${#CONFIGS} ))
idx=0
echo "number of graphs: ${#GRAPHS}"
echo "number of configs: ${#CONFIGS}"
echo "number of total computations: $total"
echo

for graph in $GRAPHS; do
  gname="${${graph:t}%.gr}"
  gdir="$OUT_DIR/$gname"
  mkdir -p "$gdir"

  for cfg in $CONFIGS; do
    n="${cfg%%:*}"
    t="${cfg##*:}"
    idx=$(( idx + 1 ))

    tag="n${n}_t${t}"
    stat="$gdir/$tag.csv"
    log="$gdir/$tag.log"

    if [[ "${FORCE:-0}" != "1" && -s "$stat" ]]; then
      echo "[$idx/$total] $gname  n=$n t=$t  -> уже есть, пропускаю"
      continue
    fi

    rm -f "$stat"
    echo "[$idx/$total] $gname  n=$n t=$t  ($(date '+%H:%M:%S'))"

    mpirun -n "$n" "$BFS" "$graph" \
      -t "$t" \
      -startNode "$STARTNODE" \
      -runs "$RUNS" \
      --statFile="$stat" \
      > "$log" 2>&1
    rc=$?

    if [[ $rc -ne 0 || ! -s "$stat" ]]; then
      echo "   !!! ошибка (код $rc), см. $log"
      echo "$gname n=$n t=$t rc=$rc" >> "$FAILED_LOG"
      rm -f "$stat"
    fi
  done
done
