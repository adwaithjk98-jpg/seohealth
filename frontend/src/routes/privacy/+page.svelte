<script>
  // Privacy Policy — DRAFT. Written to match what the app actually does, but
  // not legally reviewed. Replace the placeholder contact + run past a real
  // template/lawyer before the public, paid launch.
  const lastUpdated = '9 June 2026';
  const contact = 'hello@yourdomain.in';
</script>

<svelte:head>
  <title>Privacy Policy · SEO Health</title>
</svelte:head>

<article class="prose-legal mx-auto max-w-2xl space-y-6">
  <div
    class="rounded-2xl border border-attention-100 bg-attention-50/60 px-4 py-3 text-xs text-attention-700"
  >
    <strong>Draft.</strong> This policy reflects how the app works today but hasn't been legally
    reviewed. Finalise it (and the contact address) before charging customers.
  </div>

  <header>
    <h1 class="text-3xl font-semibold tracking-tight text-canvas-ink">Privacy Policy</h1>
    <p class="mt-1 text-sm text-canvas-muted">Last updated: {lastUpdated}</p>
  </header>

  <p class="text-sm leading-relaxed text-canvas-muted">
    SEO Health ("we", "us") helps small businesses see and improve how they show up online. This
    policy explains what we collect, why, and the control you have over it.
  </p>

  <section class="space-y-2">
    <h2 class="text-lg font-semibold text-canvas-ink">What we collect</h2>
    <ul class="ml-5 list-disc space-y-1.5 text-sm text-canvas-ink">
      <li><strong>Account:</strong> your email address, and an optional display name.</li>
      <li>
        <strong>Business details you add:</strong> business name, city, and optionally a website URL,
        Instagram handle and Google Maps link.
      </li>
      <li>
        <strong>Audit data:</strong> the scores, findings and recommendations we generate, plus any
        competitor listings you choose to track.
      </li>
      <li>
        <strong>Payment metadata:</strong> if you subscribe, payments are handled by Razorpay. We
        store your subscription reference and status — <em>not</em> your card details.
      </li>
      <li>
        <strong>Technical:</strong> a single sign-in session cookie, and basic server logs for
        security and reliability.
      </li>
    </ul>
  </section>

  <section class="space-y-2">
    <h2 class="text-lg font-semibold text-canvas-ink">Public data we read on your behalf</h2>
    <p class="text-sm leading-relaxed text-canvas-ink">
      To produce your health checks we read <strong>publicly visible</strong> information about your
      business — your Google&nbsp;Maps listing, your website, and your Instagram profile — and, for
      competitors you choose to track, the same public information about them. We only read what is
      already public; we never sign in to or access private accounts.
    </p>
  </section>

  <section class="space-y-2">
    <h2 class="text-lg font-semibold text-canvas-ink">How we use it</h2>
    <ul class="ml-5 list-disc space-y-1.5 text-sm text-canvas-ink">
      <li>To run audits and show your dashboard.</li>
      <li>To send you a one-tap sign-in link, and — on paid plans — the weekly digest and score-change emails.</li>
      <li>To process and manage your subscription.</li>
      <li>To keep the service secure and working.</li>
    </ul>
    <p class="text-sm text-canvas-muted">
      We do not sell your data, and we don't use third-party advertising trackers.
    </p>
  </section>

  <section class="space-y-2">
    <h2 class="text-lg font-semibold text-canvas-ink">Who we share it with</h2>
    <p class="text-sm leading-relaxed text-canvas-ink">
      Only the service providers needed to run SEO Health: <strong>Razorpay</strong> (payments),
      <strong>Resend</strong> (sending email), and <strong>Google</strong> (the public Maps data we
      read, and the Places API as we grow). Each processes data only to provide their service to us.
    </p>
  </section>

  <section class="space-y-2">
    <h2 class="text-lg font-semibold text-canvas-ink">How long we keep it</h2>
    <p class="text-sm leading-relaxed text-canvas-ink">
      Detailed raw audit data is automatically pruned after about 30 days; your scores and history
      are kept so you can see progress over time. Account data is kept until you delete your account.
    </p>
  </section>

  <section class="space-y-2">
    <h2 class="text-lg font-semibold text-canvas-ink">Your rights</h2>
    <ul class="ml-5 list-disc space-y-1.5 text-sm text-canvas-ink">
      <li><strong>Access / export:</strong> download everything we hold from your account page.</li>
      <li><strong>Deletion:</strong> delete your account (and all its data) from your account page.</li>
      <li><strong>Correction:</strong> edit your business details and name in the app at any time.</li>
      <li>
        <strong>Grievances:</strong> contact us (below) and we'll respond. For users in India, this
        is also your grievance-officer contact under the DPDP Act.
      </li>
    </ul>
  </section>

  <section class="space-y-2">
    <h2 class="text-lg font-semibold text-canvas-ink">Cookies</h2>
    <p class="text-sm leading-relaxed text-canvas-ink">
      We use one essential cookie to keep you signed in. That's it — no advertising or cross-site
      tracking cookies.
    </p>
  </section>

  <section class="space-y-2">
    <h2 class="text-lg font-semibold text-canvas-ink">Changes</h2>
    <p class="text-sm leading-relaxed text-canvas-ink">
      We'll update this page if our practices change and revise the date above.
    </p>
  </section>

  <section class="space-y-2">
    <h2 class="text-lg font-semibold text-canvas-ink">Contact</h2>
    <p class="text-sm leading-relaxed text-canvas-ink">
      Questions or requests: <a class="text-healthy-700 hover:underline" href={`mailto:${contact}`}>{contact}</a>.
    </p>
  </section>

  <p class="border-t border-canvas-soft pt-4 text-xs text-canvas-muted">
    See also our <a class="text-healthy-700 hover:underline" href="/terms">Terms of Service</a> and
    <a class="text-healthy-700 hover:underline" href="/refund">Refund Policy</a>.
  </p>
</article>
