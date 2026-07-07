<script>
  // Terms of Service — DRAFT. Accurate to the product but not legally reviewed.
  // Finalise (and the contact + governing-law city) before public launch.
  const lastUpdated = '9 June 2026';
  const contact = 'hello@yourdomain.in';
</script>

<svelte:head>
  <title>Terms of Service · SEO Health</title>
</svelte:head>

<article class="mx-auto max-w-2xl space-y-6">
  <div
    class="rounded-2xl border border-attention-100 bg-attention-50/60 px-4 py-3 text-xs text-attention-700"
  >
    <strong>Draft.</strong> These terms describe how the service works today but haven't been legally
    reviewed. Finalise them before charging customers.
  </div>

  <header>
    <h1 class="text-3xl font-semibold tracking-tight text-canvas-ink">Terms of Service</h1>
    <p class="mt-1 text-sm text-canvas-muted">Last updated: {lastUpdated}</p>
  </header>

  <p class="text-sm leading-relaxed text-canvas-muted">
    These terms govern your use of SEO Health. By creating an account or using the service, you
    agree to them.
  </p>

  <section class="space-y-2">
    <h2 class="text-lg font-semibold text-canvas-ink">1. What the service does</h2>
    <p class="text-sm leading-relaxed text-canvas-ink">
      SEO Health assesses how a business appears online — its Google&nbsp;Maps listing, website and
      Instagram — and gives a score, findings and recommendations, with optional competitor tracking
      and scheduled re-checks. It is an informational tool. We don't guarantee any particular search
      ranking, traffic or business result.
    </p>
  </section>

  <section class="space-y-2">
    <h2 class="text-lg font-semibold text-canvas-ink">2. Eligibility &amp; your account</h2>
    <p class="text-sm leading-relaxed text-canvas-ink">
      The service is for business use by people aged 18 or over. We sign you in with a one-tap email
      link — keep access to your email secure, as anyone with it can access your account. You're
      responsible for the activity on your account.
    </p>
  </section>

  <section class="space-y-2">
    <h2 class="text-lg font-semibold text-canvas-ink">3. How audits work</h2>
    <p class="text-sm leading-relaxed text-canvas-ink">
      To produce a health check we read <strong>publicly visible</strong> information from
      Google&nbsp;Maps, your website and Instagram on your behalf, and the same public information for
      competitors you choose to track. We read only public data and never access private accounts.
      Results are best-effort and may be incomplete or out of date.
    </p>
  </section>

  <section class="space-y-2">
    <h2 class="text-lg font-semibold text-canvas-ink">4. Acceptable use</h2>
    <ul class="ml-5 list-disc space-y-1.5 text-sm text-canvas-ink">
      <li>Use the service only for lawful purposes and for businesses you own or are authorised to manage.</li>
      <li>Don't attempt to disrupt, overload, reverse-engineer or scrape the service itself.</li>
      <li>Don't resell or redistribute the data we provide as your own product.</li>
    </ul>
  </section>

  <section class="space-y-2">
    <h2 class="text-lg font-semibold text-canvas-ink">5. Plans &amp; billing</h2>
    <p class="text-sm leading-relaxed text-canvas-ink">
      We offer a free plan and paid plans (Pro and Max). Paid plans are billed through Razorpay and
      renew automatically each period until cancelled. You can cancel any time from your account
      page; access continues until the end of the period you've paid for. We may change prices or
      features with reasonable notice. Refunds are covered by our
      <a class="text-healthy-700 hover:underline" href="/refund">Refund Policy</a>.
    </p>
  </section>

  <section class="space-y-2">
    <h2 class="text-lg font-semibold text-canvas-ink">6. Your data &amp; ours</h2>
    <p class="text-sm leading-relaxed text-canvas-ink">
      Your business information and audit history are yours — see the
      <a class="text-healthy-700 hover:underline" href="/privacy">Privacy Policy</a> for how we
      handle them. The SEO Health software, design and branding are ours; these terms don't grant
      you any rights in them beyond using the service.
    </p>
  </section>

  <section class="space-y-2">
    <h2 class="text-lg font-semibold text-canvas-ink">7. Disclaimers &amp; liability</h2>
    <p class="text-sm leading-relaxed text-canvas-ink">
      The service is provided "as is", without warranties, and is not professional marketing, SEO or
      legal advice. To the extent permitted by law, our total liability for any claim is limited to
      the amount you paid us in the three months before the claim.
    </p>
  </section>

  <section class="space-y-2">
    <h2 class="text-lg font-semibold text-canvas-ink">8. Suspension &amp; termination</h2>
    <p class="text-sm leading-relaxed text-canvas-ink">
      You can delete your account at any time. We may suspend or end access for misuse or to comply
      with the law.
    </p>
  </section>

  <section class="space-y-2">
    <h2 class="text-lg font-semibold text-canvas-ink">9. Governing law</h2>
    <p class="text-sm leading-relaxed text-canvas-ink">
      These terms are governed by the laws of India, with courts at <strong>[your city]</strong>
      having jurisdiction.
    </p>
  </section>

  <section class="space-y-2">
    <h2 class="text-lg font-semibold text-canvas-ink">10. Contact</h2>
    <p class="text-sm leading-relaxed text-canvas-ink">
      <a class="text-healthy-700 hover:underline" href={`mailto:${contact}`}>{contact}</a>
    </p>
  </section>
</article>
