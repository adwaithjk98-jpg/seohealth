<script>
  /**
   * Soft confetti + checkmark burst overlaid above a target element. Mount
   * conditionally so each burst is a fresh animation cycle. Auto-cleans by
   * relying on the parent to drop it after ~900ms.
   *
   * Calm palette only — no harsh primaries. Matches §2 of AuditAppPlan.md
   * ("Soft colors, gentle animations").
   */

  // 10 confetti shards on a circular spray; cx/cy + rotation are pre-baked so
  // each shard takes a unique flight path without RNG (consistent for tests).
  const SHARDS = [
    { cx: 70, cy: -30, rot: 220, color: '#4f8c5b', delay: 0 },
    { cx: -65, cy: -35, rot: -180, color: '#c69423', delay: 30 },
    { cx: 40, cy: -70, rot: 280, color: '#6fa97a', delay: 60 },
    { cx: -45, cy: -65, rot: -240, color: '#dfae31', delay: 90 },
    { cx: 80, cy: 20, rot: 120, color: '#4f8c5b', delay: 20 },
    { cx: -80, cy: 25, rot: -160, color: '#9cc7a4', delay: 50 },
    { cx: 25, cy: -80, rot: 320, color: '#dfae31', delay: 80 },
    { cx: -20, cy: -80, rot: -300, color: '#6fa97a', delay: 10 },
    { cx: 55, cy: 50, rot: 90, color: '#c69423', delay: 70 },
    { cx: -55, cy: 50, rot: -100, color: '#4f8c5b', delay: 40 }
  ];
</script>

<div
  class="pointer-events-none absolute left-1/2 top-1/2 z-10 -translate-x-1/2 -translate-y-1/2"
  aria-hidden="true"
>
  <div
    class="grid h-16 w-16 animate-done-pop place-items-center rounded-full bg-healthy-500 text-white shadow-soft"
  >
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 20 20"
      fill="currentColor"
      class="h-8 w-8"
    >
      <path
        fill-rule="evenodd"
        d="M16.704 5.29a1 1 0 010 1.42l-7.5 7.5a1 1 0 01-1.42 0l-3.5-3.5a1 1 0 011.42-1.42L8.5 12.08l6.79-6.79a1 1 0 011.414 0z"
        clip-rule="evenodd"
      />
    </svg>
  </div>

  {#each SHARDS as shard}
    <span
      class="animate-confetti absolute left-1/2 top-1/2 block h-2 w-2 rounded-sm"
      style="background:{shard.color}; --cx:{shard.cx}px; --cy:{shard.cy}px; --rot:{shard.rot}deg; animation-delay:{shard.delay}ms;"
    ></span>
  {/each}
</div>
