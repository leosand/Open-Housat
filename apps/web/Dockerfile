FROM node:20-alpine AS build
WORKDIR /app
COPY apps/web/package.json ./
RUN npm install --no-audit --no-fund
COPY apps/web/ ./
RUN npm run build

FROM caddy:2-alpine
COPY --from=build /app/dist /srv
EXPOSE 80
CMD ["caddy", "file-server", "--root", "/srv", "--listen", ":80"]
