FROM alpine:3.20

RUN apk add --no-cache git-daemon

RUN git init --bare /git/simple-app.git
RUN git init --bare /git/semaphore.git
RUN git init --bare /git/db-test.git
RUN git init --bare /git/infrahub.git
RUN git init --bare /git/infrahub-enterprise.git
RUN git init --bare /git/failing-actions.git

EXPOSE 9418

CMD ["git", "daemon", "--verbose", "--enable=receive-pack", "--base-path=/git", "--export-all"]
