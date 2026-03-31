default_port := "7004"

serve port=default_port:
	uv run news-cli serve --host 0.0.0.0 --port {{port}}

run:
	uv run news-cli run
