const colors = require('tailwindcss/colors')

module.exports = {
    mode: "jit",

    purge: [
        './templates/**/*.html',
        './editor/templates/*.html',
        './editor/*.py',
    ],
    darkMode: false, // or 'media' or 'class'
    theme: {
        extend: {
            colors: {
                'blue-gray': colors.blueGray,
            },
        },
    },
    variants: {
        extend: {},
    },
    plugins: [
        require('@tailwindcss/forms'),
        require('@tailwindcss/typography'),
        require('@tailwindcss/line-clamp'),
        require('@tailwindcss/aspect-ratio'),
    ],
}
