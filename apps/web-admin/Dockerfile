FROM node:20-alpine AS build

WORKDIR /app

ARG VITE_KNOWLEDGE_SERVICE_BASE_URL=http://localhost:8030/api/knowledge/v1
ARG VITE_RAG_SERVICE_BASE_URL=http://localhost:8040/api/rag/v1
ARG VITE_OPERATOR_REASON_HEADER=X-Operator-Reason

ENV VITE_KNOWLEDGE_SERVICE_BASE_URL=${VITE_KNOWLEDGE_SERVICE_BASE_URL}
ENV VITE_RAG_SERVICE_BASE_URL=${VITE_RAG_SERVICE_BASE_URL}
ENV VITE_OPERATOR_REASON_HEADER=${VITE_OPERATOR_REASON_HEADER}

COPY package.json package-lock.json tsconfig.json vite.config.ts index.html ./
COPY src ./src

RUN npm ci && npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
