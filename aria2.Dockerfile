FROM alpine:3.20

RUN apk add --no-cache aria2 curl

WORKDIR /usr/src/app

CMD ["aria2c", "--conf-path=/config/aria2.conf", "--daemon=false", "--rpc-listen-all=true"]
