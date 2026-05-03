FROM node:20-alpine AS build

WORKDIR /app/apps/web-user

ARG VITE_APP_TITLE="SmartCloud-X User Console"
ARG VITE_APP_VERSION="0.1.0"
ARG VITE_API_BASE_URL="http://localhost:8000"
ARG VITE_USE_MOCK_API="false"
ARG VITE_REQUEST_TIMEOUT_MS="30000"
ARG VITE_SSE_HEARTBEAT_SECONDS="15"

ENV VITE_APP_TITLE=${VITE_APP_TITLE}
ENV VITE_APP_VERSION=${VITE_APP_VERSION}
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_USE_MOCK_API=${VITE_USE_MOCK_API}
ENV VITE_REQUEST_TIMEOUT_MS=${VITE_REQUEST_TIMEOUT_MS}
ENV VITE_SSE_HEARTBEAT_SECONDS=${VITE_SSE_HEARTBEAT_SECONDS}

COPY tsconfig.base.json /app/tsconfig.base.json
COPY apps/web-user/package.json apps/web-user/package-lock.json apps/web-user/tsconfig.json apps/web-user/vite.config.ts apps/web-user/index.html ./
COPY packages/frontend-sdk/src /app/packages/frontend-sdk/src
COPY packages/common-schemas/src /app/packages/common-schemas/src
COPY packages/common/src /app/packages/common/src
COPY packages/common-auth/src /app/packages/common-auth/src
COPY apps/web-user/public ./public
COPY apps/web-user/src ./src

RUN npm ci && npm run build

FROM nginx:1.27-alpine

ENV VITE_APP_TITLE="SmartCloud-X User Console" \
    VITE_APP_VERSION="0.1.0" \
    VITE_API_BASE_URL="http://localhost:8000" \
    VITE_USE_MOCK_API="false" \
    VITE_REQUEST_TIMEOUT_MS="30000" \
    VITE_SSE_HEARTBEAT_SECONDS="15"

COPY apps/web-user/nginx.conf /etc/nginx/conf.d/default.conf
COPY apps/web-user/docker-entrypoint.d/40-runtime-config.sh /docker-entrypoint.d/40-runtime-config.sh
RUN chmod +x /docker-entrypoint.d/40-runtime-config.sh
COPY --from=build /app/apps/web-user/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
