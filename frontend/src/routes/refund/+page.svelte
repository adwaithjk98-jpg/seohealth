<script>
  // Refund Policy — DRAFT. Razorpay requires a stated policy for subscriptions.
  // The 7-day window below is a sensible default — confirm it's the policy you
  // actually want before public launch.
  const lastUpdated = '9 June 2026';
  const contact = 'hello@yourdomain.in';
</script>

<svelte:head>
  <title>Refund Policy · AuditHealth</title>
</svelte:head>

<article class="mx-auto max-w-2xl space-y-6">
  <div
    class="rounded-2xl border border-attention-100 bg-attention-50/60 px-4 py-3 text-xs text-attention-700"
  >
    <strong>Draft.</strong> The 7-day window below is a reasonable default — confirm the exact policy
    you want, and the contact address, before going live.
  </div>

  <header>
    <h1 class="text-3xl font-semibold tracking-tight text-canvas-ink">Refund Policy</h1>
    <p class="mt-1 text-sm text-canvas-muted">Last updated: {lastUpdated}</p>
  </header>

  <section class="space-y-2">
    <h2 class="text-lg font-semibold text-canvas-ink">Free plan</h2>
    <p class="text-sm leading-relaxed text-canvas-ink">
      The free plan is free — there's nothing to pay and nothing to refund.
    </p>
  </section>

  <section class="space-y-2">
    <h2 class="text-lg font-semibold text-canvas-ink">Paid plans</h2>
    <p class="text-sm leading-relaxed text-canvas-ink">
      Paid plans (Pro and Max) are billed in advance each period through Razorpay. If you're not
      happy, email us within <strong>7 days</strong> of a charge and we'll refund that charge in
      full. After 7 days, payments for the current period are non-refundable.
    </p>
  </section>

  <section class="space-y-2">
    <h2 class="text-lg font-semibold text-canvas-ink">Cancelling</h2>
    <p class="text-sm leading-relaxed text-canvas-ink">
      You can cancel any time from your account page. Cancelling stops future charges; your paid
      features stay active until the end of the period you've already paid for. We don't charge a
      cancellation fee.
    </p>
  </section>

  <section class="space-y-2">
    <h2 class="text-lg font-semibold text-canvas-ink">How to request a refund</h2>
    <p class="text-sm leading-relaxed text-canvas-ink">
      Email <a class="text-healthy-700 hover:underline" href={`mailto:${contact}`}>{contact}</a> from
      your account email with the date of the charge. Approved refunds are returned to your original
      payment method via Razorpay, usually within 5–7 business days.
    </p>
  </section>

  <p class="border-t border-canvas-soft pt-4 text-xs text-canvas-muted">
    See also our <a class="text-healthy-700 hover:underline" href="/terms">Terms of Service</a> and
    <a class="text-healthy-700 hover:underline" href="/privacy">Privacy Policy</a>.
  </p>
</article>
