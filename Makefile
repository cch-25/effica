.PHONY: install dev api worker migrate seed openapi security ownership verify test integration deploy deploy-web

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

security:
	./run.sh security

ownership:
	./run.sh ownership

verify:
	./run.sh verify

test:
	./run.sh test

integration:
	./run.sh integration

deploy:
	./deploy.sh

deploy-web:
	cd apps/web && vercel --prod
