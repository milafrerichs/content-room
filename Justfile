default_port := "7004"

default: serve

serve port=default_port:
	uv run news-cli serve --host 0.0.0.0 --port {{port}}

run:
	uv run news-cli run

start-gunicorn:
	uv run gunicorn asgi:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --workers 2

db:
	docker compose up -d db

db-stop:
	docker compose stop db

digest date="":
	uv run news-cli digest --date {{date}}

digest-send date="":
	uv run news-cli digest --date {{date}} --send
