// Upstreams this gateway routes to. Local defaults match docker-compose.yml.
export const config = {
  port: Number(process.env.PORT ?? 3000),
  authServiceUrl: process.env.AUTH_SERVICE_URL ?? 'http://auth-service:8000',
  ordersServiceUrl: process.env.ORDERS_SERVICE_URL ?? 'http://orders-service:8080',
  // Redis is owned by this gateway (rate limiter), provisioned by terraform.
  redisUrl: process.env.REDIS_URL ?? 'redis://localhost:6379',
};
