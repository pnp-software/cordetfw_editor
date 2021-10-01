FROM node:16.10.0

WORKDIR /work
RUN npm install tailwindcss@2.2.16 \
                @tailwindcss/typography@0.4.1 @tailwindcss/forms@0.3.4 \
                @tailwindcss/line-clamp@0.2.1 @tailwindcss/aspect-ratio@0.2.1 \
                postcss@8.3.8 \
                autoprefixer@10.3.6

ENV NODE_ENV=production

VOLUME ["/work/templates", "/work/editor", "/work/src"]

CMD ["npx", "tailwindcss", "-i", "./src/styles.css", "-o", "./static/styles.css", "--minify", "-w"]