/*
 * lockstat: measure pthread mutex wait time of a process (LD_PRELOAD shim).
 *
 * Wraps pthread_mutex_lock. The uncontended path is a trylock that succeeds
 * (the same atomic operation the real lock would do first) plus a per-thread
 * counter increment. Only when trylock fails is the blocking lock timed with
 * CLOCK_MONOTONIC. Counters live in per-thread, cache-line-padded slots, so
 * the instrumentation itself adds no shared-cache-line traffic.
 *
 * At exit the totals, and the same counters per thread, are written as JSON to
 * $LOCKSTAT_OUT:
 *   {"acquisitions": N, "contended": N, "wait_ns": N, "max_wait_ns": N,
 *    "threads_seen": K, "slots": [[acquisitions, contended, wait_ns], ...]}
 * A thread gets its slot at its first mutex lock, so slots are in order of
 * thread start. db_bench starts fresh reader threads for every benchmark and
 * each locks a mutex at once, so in a "readrandom,...,readrandom" run the
 * last T slots are the T reader threads of the measured phase: their counters
 * are exactly the measured phase's lock waits, without the DB-open noise.
 *
 * In db_bench readrandom on a read-only DB, the hot pthread mutexes are the
 * LRUCache shard mutexes (HyperClockCache lookups are lock-free).
 *
 * build: gcc -O2 -shared -fPIC -ftls-model=initial-exec -o liblockstat.so lockstat.c -ldl -lpthread
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#define MAX_SLOTS 4096

struct slot {
  uint64_t acquisitions;
  uint64_t contended;
  uint64_t wait_ns;
  uint64_t max_wait_ns;
  char pad[64 - 4 * sizeof(uint64_t)];
} __attribute__((aligned(64)));

static struct slot slots[MAX_SLOTS];
static struct slot overflow_slot; /* shared fallback, only if > MAX_SLOTS threads */
static unsigned next_slot;        /* atomic */
static __thread struct slot *my_slot;
static int (*real_lock)(pthread_mutex_t *);

static struct slot *get_slot(void) {
  if (__builtin_expect(my_slot == NULL, 0)) {
    unsigned i = __atomic_fetch_add(&next_slot, 1, __ATOMIC_RELAXED);
    my_slot = i < MAX_SLOTS ? &slots[i] : &overflow_slot;
  }
  return my_slot;
}

static inline uint64_t now_ns(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

__attribute__((constructor)) static void lockstat_init(void) {
  real_lock = (int (*)(pthread_mutex_t *))dlsym(RTLD_NEXT, "pthread_mutex_lock");
}

int pthread_mutex_lock(pthread_mutex_t *m) {
  if (__builtin_expect(real_lock == NULL, 0)) lockstat_init();
  struct slot *s = get_slot();
  int r = pthread_mutex_trylock(m);
  if (r == 0) {
    s->acquisitions++;
    return 0;
  }
  if (r != EBUSY) return real_lock(m); /* e.g. EDEADLK semantics: defer to libc */
  uint64_t t0 = now_ns();
  r = real_lock(m);
  uint64_t w = now_ns() - t0;
  s->acquisitions++;
  s->contended++;
  s->wait_ns += w;
  if (w > s->max_wait_ns) s->max_wait_ns = w;
  return r;
}

__attribute__((destructor)) static void lockstat_report(void) {
  const char *path = getenv("LOCKSTAT_OUT");
  if (!path) return;
  uint64_t acq = 0, cont = 0, wait = 0, maxw = 0;
  unsigned n = __atomic_load_n(&next_slot, __ATOMIC_RELAXED);
  if (n > MAX_SLOTS) n = MAX_SLOTS;
  for (unsigned i = 0; i < n; i++) {
    acq += slots[i].acquisitions;
    cont += slots[i].contended;
    wait += slots[i].wait_ns;
    if (slots[i].max_wait_ns > maxw) maxw = slots[i].max_wait_ns;
  }
  acq += overflow_slot.acquisitions;
  cont += overflow_slot.contended;
  wait += overflow_slot.wait_ns;
  FILE *f = fopen(path, "w");
  if (!f) return;
  fprintf(f,
          "{\"acquisitions\": %llu, \"contended\": %llu, \"wait_ns\": %llu, "
          "\"max_wait_ns\": %llu, \"threads_seen\": %u, \"slots\": [",
          (unsigned long long)acq, (unsigned long long)cont,
          (unsigned long long)wait, (unsigned long long)maxw,
          __atomic_load_n(&next_slot, __ATOMIC_RELAXED));
  for (unsigned i = 0; i < n; i++) {
    fprintf(f, "%s[%llu, %llu, %llu]", i ? ", " : "",
            (unsigned long long)slots[i].acquisitions,
            (unsigned long long)slots[i].contended,
            (unsigned long long)slots[i].wait_ns);
  }
  fprintf(f, "]}\n");
  fclose(f);
}
