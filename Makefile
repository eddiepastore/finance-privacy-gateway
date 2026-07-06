# Financial Semantic Obfuscation Gateway — common tasks. Pure stdlib; nothing to install.
.PHONY: help data demo serve api test docker-build docker-run clean

help:
	@echo "make data         - generate the synthetic sample dataset"
	@echo "make serve        - run the unified product (UI+API) at http://127.0.0.1:8770"
	@echo "make demo         - run the end-to-end CLI demo (writes output/)"
	@echo "make test         - run the full test suite"
	@echo "make docker-build - build the container image"
	@echo "make docker-run   - run the container, mapping port 8770"
	@echo "make clean        - remove generated output/ and *.db"

data:
	python3 scripts/generate_sample_data.py

serve: data
	python3 scripts/serve.py

demo: data
	python3 scripts/run_demo.py

test:
	python3 -m unittest discover -s tests

docker-build:
	docker build -t fsog-gateway .

docker-run:
	docker run --rm -p 8770:8770 fsog-gateway

clean:
	rm -rf output __pycache__ */__pycache__ */*/__pycache__ *.db
