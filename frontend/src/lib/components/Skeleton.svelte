<script>
  /**
   * Soft shimmer placeholder. Wraps the `.skeleton` utility so callers don't
   * have to redeclare height / width classes inline every time.
   *
   * @type {{
   *   height?: string,
   *   width?: string,
   *   rounded?: 'sm' | 'md' | 'lg' | 'xl' | '2xl' | 'full',
   *   class?: string
   * }}
   */
  let {
    height = 'h-4',
    width = 'w-full',
    rounded = 'xl',
    class: extraClass = ''
  } = $props();

  const roundedClass = $derived(
    {
      sm: 'rounded-sm',
      md: 'rounded-md',
      lg: 'rounded-lg',
      xl: 'rounded-xl',
      '2xl': 'rounded-2xl',
      full: 'rounded-full'
    }[rounded]
  );
</script>

<div class={`skeleton ${height} ${width} ${roundedClass} ${extraClass}`} aria-hidden="true"></div>
