/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{html,js,svelte,ts}'],
  theme: {
    extend: {
      colors: {
        // Design system per AuditAppPlan.md §2 — calm, friendly tones
        healthy: {
          50: '#f3f8f4',
          100: '#e3efe5',
          200: '#c6dfca',
          300: '#9cc7a4',
          400: '#6fa97a',
          500: '#4f8c5b', // primary sage / warm green
          600: '#3d7048',
          700: '#32593a',
          800: '#2a4831',
          900: '#243c2a'
        },
        attention: {
          50: '#fdf8ec',
          100: '#faedc9',
          200: '#f4dc91',
          300: '#ecc556',
          400: '#dfae31',
          500: '#c69423', // soft amber / mustard
          600: '#a3771b',
          700: '#825a17',
          800: '#6b4818',
          900: '#5a3c18'
        },
        action: {
          50: '#fdf3ef',
          100: '#fbe3da',
          200: '#f5c2b1',
          300: '#ed9b80',
          400: '#e2735a',
          500: '#d35a3f', // warm coral (never harsh red)
          600: '#bf452f',
          700: '#9c3526',
          800: '#7d2c22',
          900: '#67271f'
        },
        canvas: {
          DEFAULT: '#faf8f4', // off-white / warm grey background
          soft: '#f3f0e9',
          ink: '#2b2a26',
          muted: '#6b6960'
        }
      },
      fontFamily: {
        sans: [
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Roboto',
          'sans-serif'
        ]
      },
      borderRadius: {
        xl: '0.9rem',
        '2xl': '1.25rem'
      },
      boxShadow: {
        soft: '0 1px 2px rgba(43, 42, 38, 0.04), 0 4px 16px rgba(43, 42, 38, 0.06)'
      }
    }
  },
  plugins: []
};
