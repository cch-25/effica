.PHONY: install dev api worker migrate seed openapi verify test integration deploy

install:
	uv sync --all-groups

dev:
	./run.sh

api:
	./run.sh api

worker:
	./run.sh worker

migrate:
	./run.sh migrate

seed:
	./run.sh seed

openapi:
	./run.sh openapi --write

verify:
	./run.sh verify

test:
	./run.sh test

integration:
	./run.sh integration

deploy:
	./deploy.sh
