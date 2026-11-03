### Mutex wait time (LOCKSTAT pass)

| cache MB | skew | threads | cache | shards | mutex acquisitions / lookup | contended | wait µs / lookup | share of thread time waiting | throughput (ops/s) |
|---|---|---|---|---|---|---|---|---|---|
| 64 | 0 | 2 | HyperClockCache (auto) | 2 | 0.0 | – | 0.000 | 0.00% | 24,028 |
| 64 | 0 | 2 | HyperClockCache (fixed) | 2 | 0.0 | – | 0.000 | 0.00% | 24,682 |
| 64 | 0 | 2 | LRUCache | 64 | 14.1 | 0.55% | 0.042 | 0.06% | 27,000 |
| 64 | 5 | 2 | HyperClockCache (auto) | 2 | 0.0 | – | 0.000 | 0.00% | 24,140 |
| 64 | 5 | 2 | HyperClockCache (fixed) | 2 | 0.0 | – | 0.000 | 0.00% | 24,269 |
| 64 | 5 | 2 | LRUCache | 64 | 14.1 | 0.51% | 0.036 | 0.05% | 27,507 |
| 64 | 10 | 2 | HyperClockCache (auto) | 2 | 0.0 | – | 0.000 | 0.00% | 27,131 |
| 64 | 10 | 2 | HyperClockCache (fixed) | 2 | 0.0 | – | 0.000 | 0.00% | 26,798 |
| 64 | 10 | 2 | LRUCache | 64 | 14.0 | 0.47% | 0.037 | 0.05% | 28,962 |
| 64 | 20 | 2 | HyperClockCache (auto) | 2 | 0.0 | – | 0.000 | 0.00% | 50,842 |
| 64 | 20 | 2 | HyperClockCache (fixed) | 2 | 0.0 | – | 0.000 | 0.00% | 48,452 |
| 64 | 20 | 2 | LRUCache | 64 | 12.2 | 0.33% | 0.022 | 0.06% | 49,953 |
| 1024 | 0 | 2 | HyperClockCache (auto) | 1 | 0.0 | – | 0.000 | 0.00% | 35,989 |
| 1024 | 0 | 2 | HyperClockCache (auto) | 4 | 0.0 | – | 0.000 | 0.00% | 36,956 |
| 1024 | 0 | 2 | HyperClockCache (fixed) | 1 | 0.0 | – | 0.000 | 0.00% | 37,186 |
| 1024 | 0 | 2 | HyperClockCache (fixed) | 4 | 0.0 | – | 0.000 | 0.00% | 38,004 |
| 1024 | 0 | 2 | LRUCache | 1 | 13.8 | 16.84% | 4.674 | 6.95% | 29,753 |
| 1024 | 0 | 2 | LRUCache | 4 | 13.8 | 4.50% | 1.166 | 1.95% | 33,379 |
| 1024 | 0 | 2 | LRUCache | 16 | 13.8 | 1.36% | 0.284 | 0.50% | 35,202 |
| 1024 | 0 | 2 | LRUCache | 64 | 13.8 | 0.46% | 0.054 | 0.09% | 35,193 |
| 1024 | 10 | 2 | HyperClockCache (auto) | 1 | 0.0 | – | 0.000 | 0.00% | 56,570 |
| 1024 | 10 | 2 | HyperClockCache (auto) | 4 | 0.0 | – | 0.000 | 0.00% | 57,242 |
| 1024 | 10 | 2 | HyperClockCache (fixed) | 1 | 0.0 | – | 0.000 | 0.00% | 63,565 |
| 1024 | 10 | 2 | HyperClockCache (fixed) | 4 | 0.0 | – | 0.000 | 0.00% | 57,851 |
| 1024 | 10 | 2 | LRUCache | 1 | 13.4 | 15.46% | 5.002 | 10.82% | 43,260 |
| 1024 | 10 | 2 | LRUCache | 4 | 13.4 | 4.25% | 1.337 | 3.37% | 50,358 |
| 1024 | 10 | 2 | LRUCache | 16 | 13.4 | 1.21% | 0.262 | 0.68% | 51,644 |
| 1024 | 10 | 2 | LRUCache | 64 | 13.4 | 0.43% | 0.086 | 0.24% | 55,630 |
| 2048 | 0 | 2 | HyperClockCache (auto) | 64 | 0.0 | – | 0.000 | 0.00% | 43,242 |
| 2048 | 0 | 2 | HyperClockCache (fixed) | 64 | 0.0 | – | 0.000 | 0.00% | 44,879 |
| 2048 | 0 | 2 | LRUCache | 64 | 13.6 | 0.44% | 0.077 | 0.16% | 41,678 |
| 2048 | 10 | 2 | HyperClockCache (auto) | 64 | 0.0 | – | 0.000 | 0.00% | 76,512 |
| 2048 | 10 | 2 | HyperClockCache (fixed) | 64 | 0.0 | – | 0.000 | 0.00% | 81,780 |
| 2048 | 10 | 2 | LRUCache | 64 | 13.2 | 0.47% | 0.086 | 0.30% | 70,218 |
