# Distributed Graph Processing (Galois)

How the running time of distributed Galois graph algorithms depends on the configuration of **n×t** — `n` MPI processes ("hosts") with `t` threads.


## Run

### 1. Build Galois

```bash
git clone --depth=1 https://github.com/IntelligentSoftwareSystems/Galois

cd Galois && mkdir build && cd build

cmake .. -DCMAKE_BUILD_TYPE=Release -DGALOIS_ENABLE_DIST=ON

make -j$(nproc) bfs-push-dist sssp-push-dist pagerank-push-dist triangle-counting-dist graph-convert
```

### 2. Run experiments:
```bash
cd src/experiment_2

./bfs.sh
./sssp.sh
./pagerank.sh
./tc.sh
```