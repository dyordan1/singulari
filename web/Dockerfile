FROM node:22-slim
WORKDIR /app
COPY package.json ./
RUN npm install --no-audit --no-fund
COPY . .
RUN npm run build
ENV PORT=8080
ENV DIARY_DIR=/app/diary
ENV STATUS_DIR=/app/status
EXPOSE 8080
CMD ["npx", "tsx", "server.ts"]
