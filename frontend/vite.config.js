import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    port: 5173,
    // Bind to IPv4 explicitly. Vite's default binds to ``[::1]`` (IPv6
    // loopback) only — fine for browser localhost, but Tailscale Funnel
    // proxies to ``127.0.0.1:PORT`` and 502s when nothing's there.
    // Setting host pins us to IPv4 so the tunnel works after every
    // ``npm run dev``, with no extra CLI flag.
    host: '127.0.0.1',
    // Allow requests from Cloudflare Tunnel + Tailscale Funnel hosts so
    // the dev server doesn't 403 traffic coming through the public URL
    // we use on a phone. localhost still works as always.
    allowedHosts: ['.trycloudflare.com', '.cfargotunnel.com', '.ts.net'],
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      }
    }
  }
});
