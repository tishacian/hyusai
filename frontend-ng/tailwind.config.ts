import type { Config } from 'tailwindcss';

export default {
  content: ['./src/**/*.{html,ts}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#e0fbff',
          100: '#b8f5ff',
          200: '#80ecff',
          300: '#33dcfd',
          400: '#0fc9ee',
          500: '#00bcd4',
          600: '#00a0b4',
          700: '#008092',
          800: '#006576',
          900: '#004a56',
        },
        accent: {
          DEFAULT: '#1fb8cc',
        },
        success: {
          DEFAULT: '#34d399',
          bg: 'rgba(52, 211, 153, 0.10)',
        },
        warning: {
          DEFAULT: '#f5b84a',
          bg: 'rgba(245, 184, 74, 0.10)',
        },
        danger: {
          DEFAULT: '#ef5a6f',
          bg: 'rgba(239, 90, 111, 0.10)',
        },
        info: {
          DEFAULT: '#8ec5e6',
          bg: 'rgba(142, 197, 230, 0.10)',
        },
        surface: {
          light: '#f8fafc',
          dark: '#0d1116',
          'card-light': '#ffffff',
          'card-dark': '#121820',
          'raised-dark': '#182029',
          'muted-dark': '#0a0d11',
        },
      },
      fontFamily: {
        sans: ['var(--ck-font-sans)'],
        mono: ['var(--ck-font-mono)'],
      },
      borderRadius: {
        xs: '4px',
        sm: '4px',
        DEFAULT: '6px',
        md: '6px',
        lg: '10px',
        xl: '10px',
      },
      boxShadow: {
        'inset-border': 'inset 0 0 0 1px rgba(255, 255, 255, 0.06)',
        elevated: '0 8px 24px -4px rgba(0, 0, 0, 0.4), 0 2px 8px -2px rgba(0, 0, 0, 0.3)',
      },
      keyframes: {
        'gradient-shift': {
          '0%, 100%': { backgroundPosition: '0% 50%' },
          '50%': { backgroundPosition: '100% 50%' },
        },
        'pulse-glow': {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(0, 188, 212, 0.55)' },
          '50%': { boxShadow: '0 0 0 8px rgba(0, 188, 212, 0)' },
        },
        'slide-up': {
          '0%': { transform: 'translateY(8px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        'fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-400px 0' },
          '100%': { backgroundPosition: '400px 0' },
        },
        'underline-flow': {
          '0%, 100%': { transform: 'translateX(-100%)' },
          '50%': { transform: 'translateX(100%)' },
        },
      },
      animation: {
        'gradient-shift': 'gradient-shift 12s ease infinite',
        'pulse-glow': 'pulse-glow 2s ease-in-out infinite',
        'slide-up': 'slide-up 0.25s ease-out',
        'fade-in': 'fade-in 0.3s ease-out',
        shimmer: 'shimmer 1.8s linear infinite',
        'underline-flow': 'underline-flow 6s ease-in-out infinite',
      },
      backdropBlur: {
        xs: '2px',
      },
    },
  },
  plugins: [require('@tailwindcss/typography')],
} satisfies Config;
