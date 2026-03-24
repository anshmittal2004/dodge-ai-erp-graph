FROM nginx:alpine

COPY index.html /usr/share/nginx/html/index.html

# Nginx config to proxy /api calls to backend
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
