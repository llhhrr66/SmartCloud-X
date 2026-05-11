FROM node:20-alpine AS build

WORKDIR /app

ARG VITE_KNOWLEDGE_SERVICE_BASE_URL=http://localhost:8030/api/knowledge/v1
ARG VITE_RAG_SERVICE_BASE_URL=http://localhost:8040/api/rag/v1
ARG VITE_OPERATOR_REASON_HEADER=X-Operator-Reason

ENV VITE_KNOWLEDGE_SERVICE_BASE_URL=${VITE_KNOWLEDGE_SERVICE_BASE_URL}
ENV VITE_RAG_SERVICE_BASE_URL=${VITE_RAG_SERVICE_BASE_URL}
ENV VITE_OPERATOR_REASON_HEADER=${VITE_OPERATOR_REASON_HEADER}

WORKDIR /app/apps/web-admin

COPY tsconfig.base.json /app/tsconfig.base.json
COPY apps/web-admin/package.json apps/web-admin/package-lock.json apps/web-admin/tsconfig.json apps/web-admin/vite.config.ts apps/web-admin/index.html ./
COPY packages/common-schemas/src /app/packages/common-schemas/src
COPY packages/frontend-sdk/src /app/packages/frontend-sdk/src
COPY apps/web-admin/src ./src

RUN npm ci && npm run build

FROM nginx:1.27-alpine

COPY apps/web-admin/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/apps/web-admin/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
