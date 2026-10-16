/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/templates/**/*.html",
    "./app/static/js/**/*.js",
    "./FilmsOverWeb-webOS/**/*.html"
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        brand: {
          red: '#e5a00d',
          redHover: '#c78707',
          yellow: '#e5a00d',
          yellowHover: '#c78707',
          accent: '#e5a00d',
          accentHover: '#c78707',
          blue: '#00a8e1',
          dark: '#0b0c0e',
          surface: '#14171f',
          border: '#222734'
        }
      }
    }
  },
  plugins: []
}
