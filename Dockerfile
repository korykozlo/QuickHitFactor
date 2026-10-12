# QuickHitFactor: the static app plus the member lookup server. No npm dependencies.
# Plain requests to uspsa.org only: no Python or Playwright, so the browser fallback is off.
FROM node:22-alpine

ENV NODE_ENV=production \
    PORT=8000 \
    SCRAPE_FALLBACK=0

WORKDIR /app
COPY package.json calc.js index.html og-image.png ./
COPY data ./data
COPY diagrams ./diagrams
COPY server/server.js server/uspsa.js ./server/
RUN chown -R node:node /app/data

USER node
EXPOSE 8000
CMD ["node", "server/server.js"]
